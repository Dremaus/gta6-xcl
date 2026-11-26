#!/usr/bin/env python3
"""Parse VItoriaBr/fxceless frame logs into a CSV/JSON baseline.

Backwards-compatible CLI over ``victory_log.py``. It reads both record kinds:
the ``N fps, N ms/frame ... N draws/frame, dropped N ...`` line and the
``frame times: ... each: ...`` / ``usual frame (...)`` lines.

    python tools/bench/parse_victory_log.py LOG --csv out.csv
    python tools/bench/parse_victory_log.py LOG --frames --gate-fps 30
    python tools/bench/parse_victory_log.py LOG --min-draws 1000 --min-ms 100
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_gate
import victory_log


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logs", nargs="+", type=Path, help="game-stderr.log / game-run.log")
    ap.add_argument("--csv", type=Path, help="write per-line rows here")
    ap.add_argument("--json", action="store_true", help="print JSON instead of a table")
    ap.add_argument("--frames", action="store_true",
                    help="use the frame log's per-frame times (p50/p95/1%% low)")
    ap.add_argument("--gate-fps", type=float,
                    help="judge the matching gate (5, 10, 20 or 30)")
    ap.add_argument("--min-draws", type=int, default=0,
                    help="ignore frames below this draw count (e.g. 1000 for 3D)")
    ap.add_argument("--min-ms", type=float, default=0.0,
                    help="ignore frames below this frame time (e.g. 100 for 3D)")
    args = ap.parse_args()

    all_rows: list[dict] = []
    per_log: list[dict] = []
    frames: list[float] = []
    precision = "none"

    for path in args.logs:
        if not path.is_file():
            print(f"missing: {path}", file=sys.stderr)
            return 2
        parsed = victory_log.read_log(path)
        rows = [r for r in parsed["fps_lines"] if r["draws"] is not None]
        rows = [r for r in rows if r["draws"] >= args.min_draws and r["ms_per_frame"] >= args.min_ms]
        for r in rows:
            r["source"] = path.name
        all_rows.extend(rows)

        if args.frames:
            got = []
            for rec in parsed["frame_times"]:
                if (rec["median_ms"] or 0) >= args.min_ms and (rec["usual_ms"] or 0) >= 0:
                    got.extend(rec["each_ms"])
            frames.extend(got)
            precision = "per-frame" if got else precision

        per_log.append(
            {
                "path": str(path),
                "fps_lines": len(rows),
                "frame_buckets": len(parsed["frame_times"]),
                "frame_times": sum(len(r["each_ms"]) for r in parsed["frame_times"]),
                "panics": len(parsed["panics"]),
            }
        )

    if args.csv:
        fields = ["source", "line", "fps", "ms_per_frame", "draws", "dropped"]
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in all_rows:
                writer.writerow({**row, "line": row.get("line", "")})

    if frames:
        summary = victory_log.summarize_frames(frames)
        summary["precision"] = precision
    else:
        summary = victory_log.summarize_frames([r["ms_per_frame"] for r in all_rows])
        summary["precision"] = "coarse" if all_rows else "none"

    # The FPS-line averages are reported whatever the frame source is: they
    # are the numbers earlier reports quote.
    fps_values = victory_log.numeric(r["fps"] for r in all_rows)
    if fps_values:
        summary["fps_mean"] = round(sum(fps_values) / len(fps_values), 3)
        summary["fps_median"] = round(statistics.median(fps_values), 3)
    else:
        summary.setdefault("fps_mean", None)
        summary.setdefault("fps_median", None)

    draws = victory_log.numeric(r["draws"] for r in all_rows)
    if draws:
        summary["draws_mean"] = round(sum(draws) / len(draws), 1)
        summary["draws_max"] = int(max(draws))
    # Keys the earlier parser always printed.
    summary.setdefault("ms_max", summary.get("max_ms"))

    gate = None
    if args.gate_fps:
        budget = 1000.0 / args.gate_fps
        p50_ok = summary.get("p50_ms") is not None and summary["p50_ms"] <= budget
        p95_ok = summary.get("p95_ms") is not None and summary["p95_ms"] <= bench_gate.TARGET_P95_MS
        # The p95 rule belongs to the 30 fps target; lower gates judge p50 only.
        is_target = abs(args.gate_fps - bench_gate.TARGET_FPS) < 1e-9
        gate = {
            "fps": args.gate_fps,
            "budget_ms": round(budget, 3),
            "p50_ok": p50_ok,
            "p95_ms": summary.get("p95_ms"),
            "p95_budget_ms": bench_gate.TARGET_P95_MS,
            "p95_ok": p95_ok,
            "pass": p50_ok and (p95_ok if is_target else True),
            "reached": bench_gate.reached_gate(summary.get("p50_ms"), summary.get("p95_ms")),
        }

    payload = {"summary": summary, "gate": gate, "logs": per_log}
    if args.json:
        payload["rows"] = all_rows
        print(json.dumps(payload, indent=2))
    else:
        for log in per_log:
            print(
                f"{log['path']}: {log['fps_lines']} fps lines, "
                f"{log['frame_times']} per-frame times in {log['frame_buckets']} buckets"
            )
        print(json.dumps({k: v for k, v in payload.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
