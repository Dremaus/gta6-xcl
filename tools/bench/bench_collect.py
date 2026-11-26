#!/usr/bin/env python3
"""Build one ``run.json`` from a measurement window.

No game process is started here: the supervisor runs the title, stamps a
window, and this tool turns the logs plus the hardware samples into evidence.

    python tools/bench/bench_collect.py --runtime vitoriabr --variant baseline \
        --cache warm --run-id r01 --start 2026-11-25T20:00:00Z \
        --end 2026-11-25T20:01:00Z --out benchmarks/runs/x/r01/run.json
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_gate
import bench_guard
import settings_xml
import victory_log

SCHEMA = 1

RUNTIMES = {
    "vitoriabr": {
        "label": "VItoriaBr",
        "data_root": r"D:\Gry\VItoriaBr-data",
        "launcher": r"D:\Gry\VItoriaBr-data\Launch-VItoriaBr.ps1",
    },
    "fxceless": {
        "label": "fxceless",
        "data_root": r"D:\Gry\fxceless-data",
        "launcher": r"D:\Gry\fxceless-data\Launch-Fxceless.ps1",
    },
}


def epoch(text: str) -> float:
    t = text.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    return datetime.fromisoformat(t).timestamp()


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def nvidia_smi() -> dict:
    cmd = [
        "nvidia-smi",
        "--query-gpu=name,memory.total,driver_version",
        "--format=csv,noheader,nounits",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=20, text=True)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0 or not out.stdout.strip():
        return {}
    parts = [p.strip() for p in out.stdout.splitlines()[0].split(",")]
    if len(parts) < 3:
        return {}
    return {"gpu": parts[0], "vram_total_mb": float(parts[1]), "driver": parts[2]}


POWER_PLANS = {
    "381b4222-f694-41f0-9685-ff5bb260df2e": "Balanced",
    "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c": "High performance",
    "a1841308-3541-4fab-bc81-f71556f20b4a": "Power saver",
}


def power_plan() -> str:
    """Active scheme by GUID; the localized name is not stable across hosts."""
    try:
        out = subprocess.run(
            ["powercfg", "/getactivescheme"], capture_output=True, timeout=20
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    text = out.stdout.decode("mbcs", "replace") if sys.platform == "win32" else out.stdout.decode("utf-8", "replace")
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", text, re.I)
    if not match:
        return " ".join(text.split())
    guid = match.group(1).lower()
    return POWER_PLANS.get(guid, f"custom {guid}")


def cpu_name() -> str:
    if sys.platform != "win32":
        return platform.processor() or platform.machine()
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Processor).Name"],
            capture_output=True, timeout=30,
        )
        name = out.stdout.decode("mbcs", "replace").strip()
        if name:
            return name
    except (OSError, subprocess.SubprocessError):
        pass
    return platform.processor() or platform.machine()


def host_info() -> dict:
    info = {
        "cpu": cpu_name(),
        "os": f"{platform.system()} {platform.release()} {platform.version()}",
        "power_plan": power_plan(),
    }
    info.update(nvidia_smi())
    return info


def read_samples(path: Path | None, t0: float, t1: float) -> list[dict]:
    if not path or not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = row.get("t")
        if isinstance(t, (int, float)) and t0 <= t <= t1:
            rows.append(row)
    return rows


def summarise_samples(rows: list[dict]) -> dict:
    used = [r["used_mb"] for r in rows if isinstance(r.get("used_mb"), (int, float))]
    commit = [r["commit_mb"] for r in rows if isinstance(r.get("commit_mb"), (int, float))]
    util = [r["util"] for r in rows if isinstance(r.get("util"), (int, float))]
    temp = [r["temp_c"] for r in rows if isinstance(r.get("temp_c"), (int, float))]
    return {
        "samples": len(rows),
        "vram_peak_mb": round(max(used), 0) if used else None,
        "vram_mean_mb": round(statistics.fmean(used), 0) if used else None,
        "commit_peak_mb": round(max(commit), 0) if commit else None,
        "gpu_util_mean_pct": round(statistics.fmean(util), 1) if util else None,
        "gpu_temp_max_c": round(max(temp), 0) if temp else None,
    }


def draws_summary(parsed: dict, t0: float, t1: float) -> dict:
    rows = [r for r in parsed["fps_lines"] if r.get("ts") is not None and t0 <= r["ts"] <= t1]
    draws = victory_log.numeric(r.get("draws") for r in rows)
    if not draws:
        usual = [r for r in parsed["usual_frames"] if r.get("ts") is not None and t0 <= r["ts"] <= t1]
        draws = victory_log.numeric(r.get("draws") for r in usual)
    dropped = victory_log.numeric(r.get("dropped") for r in rows)
    return {
        "mean": round(statistics.fmean(draws), 1) if draws else None,
        "max": int(max(draws)) if draws else None,
        "dropped_mean": round(statistics.fmean(dropped), 1) if dropped else None,
        "dropped_max": int(max(dropped)) if dropped else None,
    }


def phase_summary(parsed: dict, t0: float, t1: float) -> dict:
    rows = [r for r in parsed["fps_lines"] if r.get("ts") is not None and t0 <= r["ts"] <= t1]
    out: dict = {"fps_lines": len(rows)}
    for key in (
        "cpu_prepare_ms",
        "copy_ms",
        "texture_ms",
        "gpu_ms",
        "back_ms",
        "heap_ms",
    ):
        vals = victory_log.numeric(r.get(key) for r in rows)
        out[key] = round(statistics.fmean(vals), 1) if vals else None
    usual = [r for r in parsed["usual_frames"] if r.get("ts") is not None and t0 <= r["ts"] <= t1]
    if usual:
        out["submit_call_ms"] = round(
            statistics.fmean(victory_log.numeric(r.get("submit_call_ms") for r in usual)), 1
        )
        out["card_wait_ms"] = round(
            statistics.fmean(victory_log.numeric(r.get("card_wait_ms") for r in usual)), 1
        )
        out["card_idle_ms"] = round(
            statistics.fmean(victory_log.numeric(r.get("card_idle_ms") for r in usual)), 1
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runtime", choices=sorted(RUNTIMES), default="vitoriabr")
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--cache", default="unknown",
                    choices=["cold", "warm", "cold-then-warm", "unknown"])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--start", help="window start, ISO-8601 UTC")
    ap.add_argument("--end", help="window end, ISO-8601 UTC")
    ap.add_argument("--whole-log", action="store_true",
                    help="measure the whole log (calibration/testing only)")
    ap.add_argument("--data-root", type=Path)
    ap.add_argument("--stderr", type=Path)
    ap.add_argument("--stdout", type=Path)
    ap.add_argument("--samples", type=Path, help="JSONL from bench_run (VRAM/commit)")
    ap.add_argument("--settings", type=Path,
                    help="settings.xml to record (default: found under the data root)")
    ap.add_argument("--env-file", type=Path, help="JSON of the VICTORY_* environment")
    ap.add_argument("--notes", default="")
    ap.add_argument("--min-frames", type=int, default=bench_gate.MIN_FRAMES)
    ap.add_argument("--emit-series", action="store_true", help="store every frame time")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    preset = RUNTIMES[args.runtime]
    data_root = args.data_root or Path(preset["data_root"])
    stderr = args.stderr or data_root / "logs" / "game-stderr.log"
    stdout = args.stdout or data_root / "logs" / "game-stdout.log"

    if not stderr.is_file():
        print(f"missing log: {stderr}", file=sys.stderr)
        return 2

    parsed = victory_log.read_log(stderr)

    if args.whole_log:
        # Calibration on an existing log: the window is the log's own span, so
        # crash and Event Log evidence is bounded to it instead of all time.
        # The first reporting bucket covers up to a minute before its own
        # timestamp, so the start is pulled back to keep those frames.
        if parsed["first_ts"] is not None:
            t0 = parsed["first_ts"] - 60.0
            t1 = parsed["last_ts"] or parsed["first_ts"]
        else:
            mtime = stderr.stat().st_mtime
            t0, t1 = mtime - 3600.0, mtime
        if t1 <= t0:
            t1 = t0 + 1.0
    elif args.start and args.end:
        t0, t1 = epoch(args.start), epoch(args.end)
    else:
        ap.error("give --start and --end, or --whole-log")
    if t1 <= t0:
        ap.error("--end must be after --start")

    frames, precision = victory_log.frames_in_window(parsed, t0, t1)
    stats = victory_log.summarize_frames(frames)
    draws = draws_summary(parsed, t0, t1)
    samples = summarise_samples(read_samples(args.samples, t0, t1))
    stability = bench_guard.collect(data_root, t0, t1)
    gates = bench_gate.evaluate(
        stats,
        draws_mean=draws["mean"],
        vram_peak_mb=samples["vram_peak_mb"],
        tdr=stability["tdr"],
        fatal_crash=stability["fatal"],
        min_frames=args.min_frames,
        precision=precision,
    )

    env: dict = {}
    launch: dict = {}
    env_file = args.env_file or (data_root / "logs" / "bench-env.json")
    if env_file.is_file():
        try:
            record = json.loads(env_file.read_text(encoding="utf-8-sig"))
            env = record.get("env", {}) if isinstance(record, dict) else {}
            launch = {k: v for k, v in record.items() if k != "env"} if isinstance(record, dict) else {}
            launch["source"] = str(env_file)
        except (json.JSONDecodeError, OSError, ValueError):
            env, launch = {}, {}

    settings = settings_xml.read_settings(args.settings, data_root)

    run = {
        "schema": SCHEMA,
        "created_utc": iso(datetime.now(tz=timezone.utc).timestamp()),
        "run_id": args.run_id,
        "variant": args.variant,
        "runtime": args.runtime,
        "runtime_label": preset["label"],
        "cache": args.cache,
        "window": {
            "start_utc": iso(t0),
            "end_utc": iso(t1),
            "whole_log": args.whole_log,
            "seconds": round(t1 - t0, 1),
        },
        "host": host_info(),
        "env": env,
        "launch": launch,
        "settings": settings,
        "logs": {
            "stderr": str(stderr),
            "stderr_bytes": parsed["bytes"],
            "stdout": str(stdout),
            "records": parsed["records"],
        },
        "precision": precision,
        "frames": stats,
        "draws": draws,
        "phases": phase_summary(parsed, t0, t1),
        "samples": samples,
        "stability": stability,
        "gates": gates,
        "notes": args.notes,
    }
    if args.emit_series:
        run["frame_series_ms"] = frames

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")

    print(f"{args.run_id}: {precision}, {stats.get('frames', 0)} frames, "
          f"p50 {stats.get('p50_ms', 'n/a')} ms, p95 {stats.get('p95_ms', 'n/a')} ms, "
          f"1% low {stats.get('low1_fps', 'n/a')} fps")
    print(f"  draws {draws['mean']}, VRAM peak {samples['vram_peak_mb']} MB, "
          f"commit peak {samples['commit_peak_mb']} MB")
    print(f"  {settings_xml.describe(settings)}")
    print(f"  {stability['summary']}")
    print(f"  verdict {gates['verdict']} (gate {gates['gate_reached'] or 'none'})")
    for reason in gates["reasons"]:
        print(f"  - {reason}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
