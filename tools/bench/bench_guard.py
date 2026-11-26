#!/usr/bin/env python3
"""Crash, device-loss (TDR) and Windows Event Log evidence for a bench window.

Three sources, all read-only:

* ``<data>/data/<title>/crashes.log`` - the runtime's own crash journal. Each
  entry starts with ``unix time N, process P``. The log is authoritative for
  device removal and unhandled exceptions; ``failed printing to stderr`` there
  is the pipe closing on exit, not a crash.
* ``<data>/data/<title>/temp/victory-*.crash.log`` - telemetry snapshots the
  runtime writes on a fatal fault (frame, running time, tile heap).
* Windows Event Log - ``Application`` 1000/1001/1002 and ``System`` 41/4101/
  1001/17/18/19, filtered to the measurement window.
"""

from __future__ import annotations

import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

CRASH_HEAD = re.compile(r"^unix time (?P<unix>\d+), process (?P<pid>\d+)\s*$", re.M)
GPU_MODULE = re.compile(r"nvlddmkm|amdkmdag|igdkmd|dxgkrnl|d3d12|dxgi", re.I)
TITLE_MODULE = re.compile(r"victory|game_scarlett", re.I)
# Only these are the benchmarked processes; helper binaries crashing do not
# invalidate a measurement window.
BENCH_APP = re.compile(r"^(?:victory|game_scarlett_master)\.exe$", re.I)
DEVICE_REMOVED = re.compile(
    r"device removed|host gpu failure|0x887a0007|dxgi_error_device_removed", re.I
)
DEVICE_UNSUPPORTED = re.compile(r"0x887a0004", re.I)
PIPE_CLOSED = re.compile(r"failed printing to stderr|os error 232|trwa zamykanie potoku", re.I)
UNHANDLED = re.compile(r"unhandled exception", re.I)

EVENT_APPLICATION = "Application"
EVENT_SYSTEM = "System"
QUERY = {
    # WER 1001 is informational and floods the log; keep real faults only.
    EVENT_APPLICATION: "*[System[(EventID=1000 or EventID=1002)]]",
    EVENT_SYSTEM: "*[System[(EventID=41 or EventID=4101 or EventID=1001 or EventID=17 "
    "or EventID=18 or EventID=19)]]",
}


def _normalize_time(text: str) -> str:
    """Trim the 7-digit event fraction to 6 so ``fromisoformat`` accepts it."""
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?$", text)
    if not m:
        return text
    frac = (m.group(2) or "")[:6]
    zone = m.group(3) or "Z"
    return f"{m.group(1)}.{frac}{zone}" if frac else f"{m.group(1)}{zone}"


def _epoch(text: str | None) -> float | None:
    if not text:
        return None
    t = _normalize_time(text.strip())
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(t).timestamp()
    except ValueError:
        return None


def read_crashes(
    path: Path, since: float | None = None, until: float | None = None
) -> list[dict]:
    """Entries in the runtime's ``crashes.log`` inside ``[since, until]``."""
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    heads = list(CRASH_HEAD.finditer(text))
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[head.end() : end].strip()
        unix = int(head.group("unix"))
        if since is not None and unix < since:
            continue
        if until is not None and unix > until:
            continue
        if DEVICE_REMOVED.search(body):
            kind, fatal = "device_removed", True
        elif UNHANDLED.search(body):
            kind, fatal = "unhandled_exception", True
        elif PIPE_CLOSED.search(body):
            kind, fatal = "log_pipe", False
        elif "panic" in body.lower():
            kind, fatal = "panic", False
        else:
            kind, fatal = "other", False
        # One fault can be journaled several times in the same second.
        key = (kind, unix)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "source": "crashes.log",
                "unix": unix,
                "at_utc": datetime.fromtimestamp(unix, timezone.utc).isoformat(),
                "process": int(head.group("pid")),
                "kind": kind,
                "fatal": fatal,
                "device_removed": kind == "device_removed",
                "device_unsupported": bool(DEVICE_UNSUPPORTED.search(body)),
                "text": " ".join(body.split())[:500],
            }
        )
    return out


def _run_wevtutil(channel: str, query: str, count: int = 60) -> tuple[str, str | None]:
    cmd = ["wevtutil", "qe", channel, f"/q:{query}", f"/c:{count}", "/rd:true", "/f:xml"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=45)
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover - host specific
        return "", str(exc)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip()
        return "", err or f"wevtutil exit {proc.returncode}"
    return proc.stdout.decode("utf-8", "replace"), None


def _xml_events(blob: str) -> list[dict]:
    if not blob.strip():
        return []
    # wevtutil prints one <Event> per line, no XML declaration or root element.
    wrapped = "<Events>" + blob + "</Events>"
    try:
        root = ET.fromstring(wrapped)
    except ET.ParseError:
        return []
    ns = {"e": "http://schemas.microsoft.com/win/2004/08/events/event"}
    out = []
    for ev in root.findall("e:Event", ns):
        system = ev.find("e:System", ns)
        if system is None:
            continue
        provider = system.find("e:Provider", ns)
        event_id = system.findtext("e:EventID", default="", namespaces=ns)
        created = system.find("e:TimeCreated", ns)
        data = {
            d.get("Name") or "": (d.text or "")
            for d in ev.findall("e:EventData/e:Data", ns)
        }
        out.append(
            {
                "channel": system.findtext("e:Channel", default="", namespaces=ns),
                "provider": provider.get("Name") if provider is not None else "",
                "id": int(event_id) if event_id.isdigit() else None,
                "at_utc": created.get("SystemTime") if created is not None else None,
                "data": data,
            }
        )
    return out


def _classify(ev: dict) -> tuple[str, bool, bool]:
    """-> (kind, tdr, fatal)."""
    channel, event_id, data = ev["channel"], ev["id"], ev["data"]
    if channel == EVENT_SYSTEM and event_id == 4101:
        return "tdr", True, False
    if channel == EVENT_SYSTEM and event_id == 1001:
        return "bugcheck", False, True
    if channel == EVENT_SYSTEM and event_id == 41:
        return "power_loss", False, True
    if channel == EVENT_SYSTEM and event_id in (17, 18, 19):
        return "whea", False, True
    if channel == EVENT_APPLICATION and event_id == 1000:
        module = data.get("ModuleName", "")
        app = data.get("AppName", "")
        if GPU_MODULE.search(module):
            return "gpu_driver_crash", True, True
        if BENCH_APP.match(app) or TITLE_MODULE.search(module):
            return "title_crash", False, True
        return "app_crash", False, False
    if channel == EVENT_APPLICATION and event_id == 1002:
        return "app_hang", False, TITLE_MODULE.search(data.get("AppName", "")) is not None
    if channel == EVENT_APPLICATION and event_id == 1001:
        return "wer", False, False
    return "event", False, False


def scan_event_log(t0: float, t1: float) -> dict:
    """Events in ``[t0, t1]`` that matter for stability."""
    events: list[dict] = []
    errors: list[str] = []
    for channel, query in QUERY.items():
        blob, err = _run_wevtutil(channel, query)
        if err:
            errors.append(f"{channel}: {err}")
            continue
        for ev in _xml_events(blob):
            at = _epoch(ev.get("at_utc"))
            if at is None or not (t0 <= at <= t1):
                continue
            kind, tdr, fatal = _classify(ev)
            events.append(
                {
                    "source": "eventlog",
                    "channel": ev["channel"],
                    "provider": ev["provider"],
                    "id": ev["id"],
                    "at_utc": ev["at_utc"],
                    "kind": kind,
                    "tdr": tdr,
                    "fatal": fatal,
                    "app": ev["data"].get("AppName", ""),
                    "module": ev["data"].get("ModuleName", ""),
                    "exception": ev["data"].get("ExceptionCode", ""),
                    "offset": ev["data"].get("FaultingOffset", ""),
                }
            )
    return {
        "available": not errors or bool(events),
        "errors": errors,
        "events": sorted(events, key=lambda e: e["at_utc"] or ""),
        "tdr": any(e["tdr"] for e in events),
        "fatal": any(e["fatal"] for e in events),
    }


def scan_crash_dumps(temp_dir: Path, since: float, until: float | None = None) -> list[dict]:
    """Telemetry snapshots written next to the runtime during the window."""
    if not temp_dir.is_dir():
        return []
    out = []
    for path in sorted(temp_dir.glob("victory-*.crash.log")):
        mtime = path.stat().st_mtime
        if mtime < since:
            continue
        if until is not None and mtime > until:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")[:4000]
        def grab(pattern: str) -> str | None:
            m = re.search(pattern, text)
            return m.group(1) if m else None
        out.append(
            {
                "file": path.name,
                "running_time": grab(r"Game Running Time:\s*([0-9hms:]+)"),
                "frame": grab(r"^\s*Frame:\s*(\d+)"),
                "tile_heap_used_mb": grab(r"TileHeap:\s*used \((\d+)Mb\)"),
                "tile_heap_total_mb": grab(r"TileHeap:.*total \((\d+)Mb\)"),
                "game_physical_mb": grab(r"Game Physical:\s*(\d+)/"),
            }
        )
    return out


def collect(data_root: Path, t0: float, t1: float) -> dict:
    """Full stability picture for one measurement window.

    A fault handler writes its journal a moment after the frame that faulted,
    and an Application Error event lands a few seconds later, so both are
    accepted up to 10 s past the window. Telemetry dumps are flushed later
    still and are accepted up to 300 s past it.

    A title crash within 30 s after a ``failed printing to stderr`` panic is
    the process dying on the way out (the harness closed the pipe), not a
    fault in the measured window; it is kept in the evidence as ``at_exit``
    but does not block the verdict.
    """
    title_dir = data_root / "data" / "7952987A"
    crashes = read_crashes(title_dir / "crashes.log", since=t0, until=t1 + 10.0)
    eventlog = scan_event_log(t0, t1 + 10.0)
    dumps = scan_crash_dumps(title_dir / "temp", since=t0, until=t1 + 300.0)

    pipe_times = sorted(c["unix"] for c in crashes if c["kind"] == "log_pipe")

    def at_exit(ts: float) -> bool:
        return any(p - 1.0 <= ts <= p + 30.0 for p in pipe_times)

    for entry in crashes:
        if entry["kind"] in ("unhandled_exception", "panic") and at_exit(entry["unix"]):
            entry["at_exit"] = True
            entry["fatal"] = False
    for event in eventlog["events"]:
        at = _epoch(event.get("at_utc"))
        if at is not None and event["kind"] in ("title_crash", "gpu_driver_crash") and at_exit(at):
            event["at_exit"] = True
            event["fatal"] = False
            event["tdr"] = False
    eventlog["tdr"] = any(e["tdr"] for e in eventlog["events"])
    eventlog["fatal"] = any(e["fatal"] for e in eventlog["events"])

    tdr = eventlog["tdr"] or any(c["device_removed"] for c in crashes)
    # Panics alone are not fatal: a pipe closing on exit logs one.
    fatal = (
        eventlog["fatal"]
        or any(c["fatal"] for c in crashes)
    )
    return {
        "tdr": tdr,
        "fatal": fatal,
        "device_unsupported": any(c["device_unsupported"] for c in crashes),
        "crashes_log": crashes,
        "eventlog": eventlog,
        "crash_dumps": dumps,
        "summary": _summary(tdr, fatal, crashes, eventlog),
    }


def _summary(tdr: bool, fatal: bool, crashes: list[dict], eventlog: dict) -> str:
    if tdr and fatal:
        return "device removed and a fatal crash in the window"
    if tdr:
        return "device removed (TDR) in the window"
    if fatal:
        return "fatal crash in the window"
    if crashes:
        kinds = sorted({c["kind"] for c in crashes})
        return "crashes.log entries without a fatal fault: " + ", ".join(kinds)
    return "no crash, panic or device removal in the window"
