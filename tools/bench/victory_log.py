#!/usr/bin/env python3
"""Parse the victory runtimes' frame logs (VItoriaBr / fxceless).

Two record kinds matter, both written at INFO level:

  FPS line (every ~5 s, needs ``VICTORY_LOG=info``)::

    2026-11-25T20:23:03.139Z  INFO victory_gpu::host: 0.2 fps, 4016.6 ms/frame
    (1500.2 preparing: copies 600.0 ms 1.2 MB, textures 120.0 ms 8.0 MB;
    8.1 on the GPU; 300.0 copying back 64.0 MB), 2973 draws/frame,
    dropped 2844 without a host pipeline (253 being made) and 0 indirect;
    heap buffers 3.0 passes 950.0 ms; ...

  Frame log (every 5 s, needs ``VICTORY_FRAME_LOG=1``)::

    frame times: 12 frames in 5.0 s: shortest 900 ms, median 1200, longest
    4000; 4 long (over 1800 ms, the usual frame of the last 64 being 1200);
    each: 900 1100 1200 4000 ...
    usual frame (the mean of 8 not long): 1100 ms | render thread: ... in
    submit calls 812.0 ... | submit thread: ... preparing 40.0, waiting for
    the card 95.0 ... | card: idle 12.0 ms (10.0 behind us); ... | 2973
    draws | 512 MB free | ...

The frame log is the primary source: it carries true per-frame times. The FPS
line is the fallback and always supplies draws / dropped / phase costs.

Record shapes come from ``crates/victory-gpu/src/host.rs`` and
``crates/victory-gpu/src/framelog.rs`` in both runtimes.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

# --- log plumbing ---------------------------------------------------------

ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
PS_PREFIX = re.compile(r"^\s*(?:powershell\.exe|python\.exe|pwsh\.exe)\s*:\s*", re.I)
STAMP = re.compile(
    r"^\s*(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))\s+(?P<body>.*)$"
)
# PowerShell transcript decoration that must never become a log record body.
NOISE = re.compile(
    r"^(?:At line:\d+|CategoryInfo\s*:|FullyQualifiedErrorId\s*:|Catégorie\s*:|"
    r"\+|Exception\s*:|FullyQualifiedErrorId\b)",
    re.I,
)


def parse_ts(text: str) -> float | None:
    """ISO-8601 timestamp -> epoch seconds (UTC). ``None`` if unparseable."""
    t = text.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(t).timestamp()
    except ValueError:
        return None


def iter_records(path: Path) -> Iterator[tuple[float | None, str]]:
    """Yield ``(epoch, text)`` per log record, repairing wrapped lines.

    ``game-stderr.log`` arrives unwrapped, so joining is a no-op there. A
    PowerShell transcript (``game-run.log``) wraps long records at the console
    width, sometimes mid-token (``VICT`` / ``ORY_QUEUE2``); continuation lines
    carry no timestamp and are appended with no separator so a split number or
    word is restored.
    """
    ts: float | None = None
    body: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = PS_PREFIX.sub("", ANSI.sub("", raw))
        m = STAMP.match(line)
        if m:
            if body:
                yield ts, "".join(body)
            ts = parse_ts(m.group("ts"))
            body = [m.group("body")]
            continue
        stripped = line.strip()
        if not stripped or NOISE.match(stripped):
            continue
        if body:
            body.append(stripped)
    if body:
        yield ts, "".join(body)


# --- FPS line -------------------------------------------------------------

FPS_CORE = re.compile(r"(?P<fps>\d+(?:\.\d+)?)\s+fps,\s*(?P<ms>\d+(?:\.\d+)?)\s+ms/frame")
DRAWS = re.compile(r"(?P<n>\d+)\s+draws/frame")
DROPPED = re.compile(
    r"dropped\s+(?P<n>\d+)\s+without a host pipeline"
    r"(?:\s*\((?P<making>\d+)\s+being made\))?"
)
CPU = re.compile(r"(?P<v>\d+(?:\.\d+)?)\s+preparing")
COPY = re.compile(r"copies\s+(?P<ms>\d+(?:\.\d+)?)\s+ms\s+(?P<mb>\d+(?:\.\d+)?)\s+MB")
TEXTURE = re.compile(r"textures\s+(?P<ms>\d+(?:\.\d+)?)\s+ms\s+(?P<mb>\d+(?:\.\d+)?)\s+MB")
GPU = re.compile(r"(?P<v>\d+(?:\.\d+)?)\s+on the\s+GPU")
BACK_MS = re.compile(r"(?P<ms>\d+(?:\.\d+)?)\s+copying back")
BACK_MB = re.compile(r"copying back\s+(?P<mb>\d+(?:\.\d+)?)\s+MB")
HEAP = re.compile(r"heap buffers\s+(?P<passes>\d+(?:\.\d+)?)\s+passes\s+(?P<ms>\d+(?:\.\d+)?)\s+ms")


def _f(pattern: re.Pattern[str], text: str, group: str = "v") -> float | None:
    m = pattern.search(text)
    return float(m.group(group)) if m else None


def parse_fps_line(text: str) -> dict | None:
    m = FPS_CORE.search(text)
    if not m:
        return None
    draws = DRAWS.search(text)
    dropped = DROPPED.search(text)
    heap = HEAP.search(text)
    return {
        "fps": float(m.group("fps")),
        "ms_per_frame": float(m.group("ms")),
        "draws": int(draws.group("n")) if draws else None,
        "dropped": int(dropped.group("n")) if dropped else None,
        "pipelines_making": int(dropped.group("making")) if dropped and dropped.group("making") else 0,
        "cpu_prepare_ms": _f(CPU, text),
        "copy_ms": _f(COPY, text, "ms"),
        "copy_mb": _f(COPY, text, "mb"),
        "texture_ms": _f(TEXTURE, text, "ms"),
        "texture_mb": _f(TEXTURE, text, "mb"),
        "gpu_ms": _f(GPU, text),
        "back_ms": _f(BACK_MS, text, "ms"),
        "back_mb": _f(BACK_MB, text, "mb"),
        "heap_passes": _f(HEAP, text, "passes"),
        "heap_ms": _f(HEAP, text, "ms"),
    }


# --- frame log ------------------------------------------------------------

FRAME_TIMES = re.compile(
    r"frame times:\s*(?P<n>\d+) frames in (?P<secs>[\d.]+) s: "
    r"shortest (?P<shortest>\d+) ms, median (?P<median>\d+), longest (?P<longest>\d+); "
    r"(?P<long>\d+) long \(over (?P<over>\d+) ms, the usual frame of the last "
    r"(?P<recent>\d+) being (?P<usual>\d+)\); each: (?P<each>[\d ]+)"
)
USUAL_HEAD = re.compile(r"usual frame \(the mean of (?P<n>\d+) not long\): (?P<ms>[\d.]+) ms")
LONG_FRAME = re.compile(r"long frame (?P<n>\d+) at (?P<at>[\d.]+) s: (?P<ms>[\d.]+) ms")
SUBMIT_CALLS = re.compile(r"in submit calls (?P<v>[\d.]+)")
PREPARING = re.compile(r"preparing (?P<v>[\d.]+)")
CARD_WAIT = re.compile(r"waiting for the card (?P<v>[\d.]+)")
CARD_IDLE = re.compile(r"card: idle (?P<idle>[\d.]+) ms \((?P<behind>[\d.]+) behind us\)")
PRESENT = re.compile(r"in the present call (?P<v>[\d.]+)")
REFRESH = re.compile(r"refresh (?P<v>[\d.]+) ms")
RECORDING = re.compile(r"recording, all threads: (?P<v>[\d.]+) ms")
DRAWS_PLAIN = re.compile(r"(?P<n>\d+)\s+draws\b")
FREE_MB = re.compile(r"(?P<v>[\d.]+)\s+MB free")
COPY_PAIR = re.compile(r"copies (?P<ms>[\d.]+) ms (?P<mb>[\d.]+) MB")
BACK_PAIR = re.compile(r"copy-back (?P<ms>[\d.]+) ms (?P<mb>[\d.]+) MB")


def parse_frame_times(text: str) -> dict | None:
    m = FRAME_TIMES.search(text)
    if not m:
        return None
    each = [float(x) for x in m.group("each").split()]
    if len(each) != int(m.group("n")):
        # A truncated line still carries usable frames; keep what is there.
        pass
    return {
        "frames": int(m.group("n")),
        "seconds": float(m.group("secs")),
        "each_ms": each,
        "shortest_ms": float(m.group("shortest")),
        "median_ms": float(m.group("median")),
        "longest_ms": float(m.group("longest")),
        "long_frames": int(m.group("long")),
        "long_over_ms": float(m.group("over")),
        "usual_ms": float(m.group("usual")),
    }


def parse_usual_frame(text: str) -> dict | None:
    m = USUAL_HEAD.search(text)
    if not m:
        return None
    draws = DRAWS_PLAIN.search(text)
    idle = CARD_IDLE.search(text)
    copies = COPY_PAIR.search(text)
    back = BACK_PAIR.search(text)
    return {
        "mean_of": int(m.group("n")),
        "ms": float(m.group("ms")),
        "submit_call_ms": _f(SUBMIT_CALLS, text),
        "present_call_ms": _f(PRESENT, text),
        "preparing_ms": _f(PREPARING, text),
        "card_wait_ms": _f(CARD_WAIT, text),
        "card_idle_ms": float(idle.group("idle")) if idle else None,
        "card_idle_behind_ms": float(idle.group("behind")) if idle else None,
        "refresh_ms": _f(REFRESH, text),
        "recording_ms": _f(RECORDING, text),
        "draws": int(draws.group("n")) if draws else None,
        "free_mb": _f(FREE_MB, text),
        "copy_ms": float(copies.group("ms")) if copies else None,
        "copy_mb": float(copies.group("mb")) if copies else None,
        "back_ms": float(back.group("ms")) if back else None,
        "back_mb": float(back.group("mb")) if back else None,
    }


def parse_long_frame(text: str) -> dict | None:
    m = LONG_FRAME.search(text)
    if not m:
        return None
    row = parse_usual_frame(text) or {}
    row.update({"frame": int(m.group("n")), "at_s": float(m.group("at")), "ms": float(m.group("ms"))})
    return row


# --- reading a whole log --------------------------------------------------


def read_log(path: Path) -> dict:
    """Collect every record kind from one log file."""
    out: dict = {
        "path": str(path),
        "bytes": path.stat().st_size if path.is_file() else 0,
        "records": 0,
        "first_ts": None,
        "last_ts": None,
        "fps_lines": [],
        "frame_times": [],
        "usual_frames": [],
        "long_frames": [],
        "panics": [],
    }
    if not path.is_file():
        return out
    for ts, text in iter_records(path):
        out["records"] += 1
        if ts is not None:
            out["first_ts"] = ts if out["first_ts"] is None else min(out["first_ts"], ts)
            out["last_ts"] = ts if out["last_ts"] is None else max(out["last_ts"], ts)
        row = parse_frame_times(text)
        if row:
            row["ts"] = ts
            out["frame_times"].append(row)
            continue
        row = parse_long_frame(text)
        if row:
            row["ts"] = ts
            out["long_frames"].append(row)
            continue
        row = parse_usual_frame(text)
        if row:
            row["ts"] = ts
            out["usual_frames"].append(row)
            continue
        row = parse_fps_line(text)
        if row:
            row["ts"] = ts
            out["fps_lines"].append(row)
            continue
        if "panicked at" in text or "unhandled exception" in text:
            out["panics"].append({"ts": ts, "text": text[:400]})
    return out


def frames_in_window(parsed: dict, t0: float, t1: float) -> tuple[list[float], str]:
    """Frame times inside ``[t0, t1]`` and the precision achieved.

    A ``frame times`` record lists its frames in order over ``seconds`` ending
    at the record's timestamp, so a frame's time is interpolated at the middle
    of its slice. At a 5 s bucket and a 60 s window the boundary error is under
    one bucket.
    """
    frames: list[float] = []
    for rec in parsed.get("frame_times", []):
        ts = rec.get("ts")
        each = rec.get("each_ms") or []
        secs = rec.get("seconds") or 0.0
        if ts is None or not each or secs <= 0:
            continue
        n = len(each)
        start = ts - secs
        for i, ms in enumerate(each):
            at = start + secs * (i + 0.5) / n
            if t0 <= at <= t1:
                frames.append(float(ms))
    if frames:
        return frames, "per-frame"
    coarse = [
        float(r["ms_per_frame"])
        for r in parsed.get("fps_lines", [])
        if r.get("ts") is not None and t0 <= r["ts"] <= t1
    ]
    return coarse, "coarse" if coarse else "none"


# --- statistics -----------------------------------------------------------


def percentile(values: Iterable[float], p: float) -> float | None:
    """Linear-interpolated percentile, ``p`` in 0..100."""
    s = sorted(values)
    if not s:
        return None
    if len(s) == 1:
        return float(s[0])
    k = (len(s) - 1) * (p / 100.0)
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return float(s[int(k)])
    return float(s[lo] * (hi - k) + s[hi] * (k - lo))


def summarize_frames(ms_values: list[float]) -> dict:
    """p50/p95/p99, 1% and 0.1% low, all from frame times in milliseconds."""
    if not ms_values:
        return {"frames": 0}
    ms = sorted(float(v) for v in ms_values)
    mean = sum(ms) / len(ms)
    p50 = percentile(ms, 50)
    p95 = percentile(ms, 95)
    p99 = percentile(ms, 99)
    p999 = percentile(ms, 99.9)
    return {
        "frames": len(ms),
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "p999_ms": round(p999, 2),
        "min_ms": round(ms[0], 2),
        "max_ms": round(ms[-1], 2),
        "mean_ms": round(mean, 2),
        "fps_mean": round(1000.0 / mean, 3),
        "fps_p50": round(1000.0 / p50, 3),
        "low1_fps": round(1000.0 / p99, 3),
        "low01_fps": round(1000.0 / p999, 3),
        "stutter_p99_over_p50": round(p99 / p50, 2),
    }


def numeric(values: Iterable[float | None]) -> list[float]:
    return [float(v) for v in values if v is not None]
