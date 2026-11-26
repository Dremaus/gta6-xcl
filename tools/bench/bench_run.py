#!/usr/bin/env python3
"""Interactive 3-run benchmark driver. It never starts the game.

The supervisor launches the title, loads the reference save and keeps the
camera still; this tool stamps the measurement window, samples the hardware
and writes one ``run.json`` per run through ``bench_collect.py``.

    python tools/bench/bench_run.py --runtime vitoriabr --variant baseline \
        --cache warm --runs 3 --window 60 \
        --out benchmarks/runs/2026-11-25-baseline-warm

Cache modes:
  warm            all runs on the existing shader cache
  cold-then-warm  run 1 on a cleared cache (the supervisor clears it), runs
                  2-3 on the cache run 1 filled

The game must already be closed before a run starts so the log timestamps
belong to this run; the driver checks that and refuses to guess.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_collect
import settings_xml

RUNNING = ("victory.exe", "game_scarlett_master.exe")
SCENE = """
Reference scene (docs/BENCHMARK-PROTOCOL.md):
  1. Launch the title, choose Continue on save slot 0009000000000001.
  2. Wait until streaming settles and the loading indicator is gone.
  3. Do not move, do not touch the camera, no cutscene, no pause menu.
  4. Keep the window focused; do not alt-tab during the measurement.
"""


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def running_processes() -> list[str]:
    try:
        out = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"], capture_output=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return []
    text = out.stdout.decode("utf-8", "replace").lower()
    return [name for name in RUNNING if name in text]


def nvidia_smi() -> dict:
    cmd = [
        "nvidia-smi",
        "--query-gpu=memory.used,utilization.gpu,temperature.gpu,clocks.sm",
        "--format=csv,noheader,nounits",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=20, text=True)
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0 or not out.stdout.strip():
        return {}
    parts = [p.strip() for p in out.stdout.splitlines()[0].split(",")]
    if len(parts) < 4:
        return {}
    try:
        return {
            "used_mb": float(parts[0]),
            "util": float(parts[1]),
            "temp_c": float(parts[2]),
            "clock_mhz": float(parts[3]),
        }
    except ValueError:
        return {}


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def commit_mb() -> float | None:
    if sys.platform != "win32":
        return None
    try:
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return round((status.ullTotalPageFile - status.ullAvailPageFile) / (1 << 20), 0)
    except (AttributeError, OSError):
        return None


class Sampler(threading.Thread):
    def __init__(self, path: Path, interval: float):
        super().__init__(daemon=True)
        self.path = path
        self.interval = interval
        self.stop_event = threading.Event()

    def run(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            while not self.stop_event.is_set():
                row = {"t": round(time.time(), 3), "commit_mb": commit_mb()}
                row.update(nvidia_smi())
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                self.stop_event.wait(self.interval)

    def stop(self) -> None:
        self.stop_event.set()
        self.join(timeout=20)


def cache_state(data_root: Path) -> dict:
    shaders = data_root / "cache" / "shaders"
    if not shaders.is_dir():
        return {"path": str(shaders), "entries": 0, "bytes": 0}
    entries = 0
    total = 0
    for root, _dirs, files in os.walk(shaders):
        for name in files:
            entries += 1
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return {"path": str(shaders), "entries": entries, "bytes": total}


def ask(prompt: str, non_interactive: bool) -> None:
    if non_interactive:
        return
    input(prompt)


VK_RETURN = 0x0D


def return_down() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return (ctypes.windll.user32.GetAsyncKeyState(VK_RETURN) & 0x8000) != 0
    except (AttributeError, OSError):
        return False


def wait_for_return(prompt: str, non_interactive: bool, anywhere: bool) -> None:
    """One Enter press. ``anywhere`` waits for the physical key globally, so
    the operator can click the game window (it keeps focus) and press Enter
    while the game is still the foreground window."""
    if non_interactive:
        return
    print(prompt, flush=True)
    if not anywhere or sys.platform != "win32":
        input()
        return
    while return_down():  # let a held key release first (debounce)
        time.sleep(0.05)
    while not return_down():  # wait for a fresh press
        time.sleep(0.05)
    while return_down():  # and release again before returning
        time.sleep(0.05)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runtime", choices=sorted(bench_collect.RUNTIMES), default="vitoriabr")
    ap.add_argument("--variant", default="baseline")
    ap.add_argument("--cache", choices=["warm", "cold-then-warm"], default="warm")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--window", type=float, default=60.0, help="seconds per run")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--data-root", type=Path)
    ap.add_argument("--stderr", type=Path)
    ap.add_argument("--settings", type=Path,
                    help="settings.xml to record (default: found under the data root)")
    ap.add_argument("--samples-interval", type=float, default=2.0)
    ap.add_argument("--allow-dirty-cache", action="store_true")
    ap.add_argument("--non-interactive", action="store_true",
                    help="skip the Enter prompts (the window still runs)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    ap.add_argument("--skip-report", action="store_true")
    args = ap.parse_args()

    preset = bench_collect.RUNTIMES[args.runtime]
    data_root = args.data_root or Path(preset["data_root"])
    stderr = args.stderr or data_root / "logs" / "game-stderr.log"
    out_dir = args.out

    settings_path = args.settings or settings_xml.find_settings(data_root)
    settings = settings_xml.read_settings(settings_path, data_root)

    cache = cache_state(data_root)
    busy = running_processes()
    host = bench_collect.host_info()
    plan = {
        "runtime": preset["label"],
        "launcher": preset["launcher"],
        "data_root": str(data_root),
        "stderr": str(stderr),
        "runs": args.runs,
        "window_s": args.window,
        "cache_mode": args.cache,
        "cache_entries": cache["entries"],
        "cache_mb": round(cache["bytes"] / (1 << 20), 1),
        "host": host,
        "settings": settings,
        "out": str(out_dir),
    }
    print(json.dumps(plan, indent=2))
    print(settings_xml.describe(settings))

    if args.dry_run:
        print("dry run: no measurement taken")
        return 0

    if busy:
        print(f"\nREFUSING: still running: {', '.join(busy)}", file=sys.stderr)
        print("Close the game before a run so the log window is unambiguous.", file=sys.stderr)
        return 3
    if args.cache == "warm" and cache["entries"] == 0:
        print("\nREFUSING: --cache warm but the shader cache is empty.", file=sys.stderr)
        print("Run the launcher with -Warm first, or use --cache cold-then-warm.", file=sys.stderr)
        return 3

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "campaign.json").write_text(
        json.dumps(
            {
                "schema": bench_collect.SCHEMA,
                "created_utc": iso(time.time()),
                "variant": args.variant,
                "runtime": args.runtime,
                "cache_mode": args.cache,
                "runs": args.runs,
                "window_s": args.window,
                "cache": cache,
                "host": host,
                "settings": settings,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(SCENE)
    ask("\nPress Enter when the title is at the reference scene... ", args.non_interactive)

    run_files: list[Path] = []
    for index in range(1, args.runs + 1):
        run_id = f"r{index:02d}"
        run_dir = out_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        cold = args.cache == "cold-then-warm" and index == 1

        if cold:
            print("\nCOLD RUN: clear the shader cache before launching.")
            print(f"  Remove-Item -Recurse -Force '{cache['path']}'")
            ask("Press Enter once the cache is cleared and the title is relaunched... ",
                args.non_interactive)
            now_cache = cache_state(data_root)
            if now_cache["entries"] > 0 and not args.allow_dirty_cache:
                print(f"REFUSING: cache still holds {now_cache['entries']} files; "
                      f"pass --allow-dirty-cache to record it anyway.", file=sys.stderr)
                return 3

        print(f"\n=== {run_id} / {args.runs} ({'cold' if cold else 'warm'} cache) ===")
        wait_for_return(
            "START gate: 1) click the game window once - it keeps focus. "
            "2) press Enter.\n"
            "  (Enter is read globally; do not touch the mouse or keyboard "
            "for the whole window.)",
            args.non_interactive,
            anywhere=True,
        )

        t0 = time.time()
        sampler = Sampler(run_dir / "samples.jsonl", args.samples_interval)
        sampler.start()
        deadline = t0 + args.window
        while time.time() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.time())))
        t1 = time.time()
        sampler.stop()

        ask("Measurement stopped. Press Enter to collect this run... ",
            args.non_interactive)
        notes = ""
        if not args.non_interactive:
            notes = input("Optional note for this run (Enter to skip): ").strip()

        run_json = run_dir / "run.json"
        cmd = [
            sys.executable,
            str(Path(__file__).with_name("bench_collect.py")),
            "--runtime", args.runtime,
            "--variant", args.variant,
            "--cache", "cold" if cold else "warm",
            "--run-id", run_id,
            "--start", iso(t0),
            "--end", iso(t1),
            "--data-root", str(data_root),
            "--samples", str(run_dir / "samples.jsonl"),
            "--notes", notes,
            "--out", str(run_json),
        ]
        if settings_path:
            cmd += ["--settings", str(settings_path)]
        if args.stderr:
            cmd += ["--stderr", str(args.stderr)]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print(f"{run_id}: collection failed with exit {result.returncode}", file=sys.stderr)
            return result.returncode
        run_files.append(run_json)

        if index < args.runs:
            ask("\nRestart the title for the next run (fresh process per run). "
                "Press Enter when the reference scene is ready again... ",
                args.non_interactive)

    if not args.skip_report:
        report = out_dir / "report.md"
        cmd = [
            sys.executable,
            str(Path(__file__).with_name("bench_report.py")),
            "--runs", *[str(p) for p in run_files],
            "--variant", args.variant,
            "--out", str(report),
        ]
        subprocess.run(cmd, check=False)
        print(f"\nreport: {report}")

    print(f"\n{len(run_files)} runs written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
