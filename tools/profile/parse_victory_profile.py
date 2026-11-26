#!/usr/bin/env python3
"""Summarise VItoriaBr's profiler .folded stacks.

The sampler writes `profile.txt` and `profile.txt.folded`. Each .folded line is:

    ROLE;frame;frame;...;innermost <microseconds>

Function names have spaces replaced by `_` and `;` by `:`. We report, per role:
self time (innermost frame), inclusive time (any frame), and totals.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

LINE = re.compile(r"^(?P<stack>.+)\s+(?P<us>\d+)$")


def parse(path: Path) -> list[tuple[str, list[str], int]]:
    rows: list[tuple[str, list[str], int]] = []
    for raw in path.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        m = LINE.match(raw)
        if not m:
            continue
        frames = m.group("stack").split(";")
        if not frames:
            continue
        role = frames[0] or "?"
        rest = [f for f in frames[1:] if f]
        if not rest:
            rest = [role]
        rows.append((role, rest, int(m.group("us"))))
    return rows


def summarise(rows: list[tuple[str, list[str], int]]) -> dict:
    roles: dict[str, dict] = {}
    for role, frames, us in rows:
        r = roles.setdefault(role, {"total_us": 0, "self": defaultdict(int), "incl": defaultdict(int)})
        r["total_us"] += us
        r["self"][frames[-1]] += us
        for f in set(frames):
            r["incl"][f] += us
    return roles


def top(d: dict[str, int], total: int, n: int = 20) -> list[dict]:
    return [
        {"function": k, "us": v, "pct": round(100.0 * v / total, 2) if total else 0.0}
        for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folded", type=Path, help="profile.txt.folded")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--csv", type=Path, help="per-function CSV")
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    if not args.folded.is_file():
        print(f"missing: {args.folded}", file=sys.stderr)
        return 2
    rows = parse(args.folded)
    roles = summarise(rows)
    out = {}
    for role, r in roles.items():
        out[role] = {
            "total_us": r["total_us"],
            "self_top": top(r["self"], r["total_us"], args.top),
            "inclusive_top": top(r["incl"], r["total_us"], args.top),
        }

    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["role", "function", "self_us", "self_pct", "inclusive_us", "inclusive_pct"])
            for role, r in roles.items():
                for fn, us in sorted(r["self"].items(), key=lambda kv: -kv[1]):
                    w.writerow([
                        role, fn, us,
                        round(100.0 * us / r["total_us"], 2) if r["total_us"] else 0.0,
                        r["incl"].get(fn, 0),
                        round(100.0 * r["incl"].get(fn, 0) / r["total_us"], 2) if r["total_us"] else 0.0,
                    ])

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        for role, r in out.items():
            print(f"\n== {role} ({r['total_us']/1e6:.2f} s sampled) ==")
            for row in r["self_top"][:10]:
                print(f"  self {row['pct']:5.1f}%  {row['us']/1000:9.1f} ms  {row['function']}")
            print("  -- inclusive --")
            for row in r["inclusive_top"][:10]:
                print(f"  incl {row['pct']:5.1f}%  {row['us']/1000:9.1f} ms  {row['function']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
