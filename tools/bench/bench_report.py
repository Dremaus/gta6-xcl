#!/usr/bin/env python3
"""Aggregate run.json files into the benchmark report.

Three runs are the unit: the reported p50 is the median of the runs' p50, the
reported p95 is the worst run's p95 (conservative), and the 1% low is the
worst run's. The 30 fps gate needs p50 <= 33.3 ms, p95 <= 40 ms, a valid 3D
window and no device loss.

    python tools/bench/bench_report.py --runs benchmarks/runs/x/r01/run.json \
        benchmarks/runs/x/r02/run.json benchmarks/runs/x/r03/run.json \
        --variant baseline --out benchmarks/runs/x/report.md

``--from-csv`` renders the stored baseline snapshot instead; single rows are
not a 3-run measurement, so those gates are indicative only.
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_gate
import settings_xml

HERE = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = HERE.parent.parent / "benchmarks" / "report-template.md"


def n(value, digits: int = 1, dash: str = "n/a") -> str:
    if value is None:
        return dash
    if isinstance(value, str):
        return value
    if digits == 0:
        return f"{value:.0f}"
    return f"{value:.{digits}f}"


def load_runs(paths: list[Path]) -> list[dict]:
    runs = []
    for path in paths:
        runs.append(json.loads(path.read_text(encoding="utf-8-sig")))
    return runs


def settings_signature(run: dict) -> str | None:
    """Compact settings.xml identity, for the mid-campaign consistency check."""
    record = run.get("settings") or {}
    if not record.get("found") or record.get("parse_error"):
        return None
    g = record.get("graphics", {})
    v = record.get("video", {})
    r = v.get("refreshRate", {})
    res = v.get("resolutionFullscreen", {})
    return (
        f"desiredFPS={g.get('desiredFPS')} limit={v.get('frameRateLimit')} "
        f"vsync={v.get('vSync')} refresh={r.get('numerator')}/{r.get('denominator')} "
        f"res={res.get('width')}x{res.get('height')}"
    )


def aggregate(runs: list[dict]) -> dict:
    p50 = [r["frames"]["p50_ms"] for r in runs if r.get("frames", {}).get("p50_ms") is not None]
    p95 = [r["frames"]["p95_ms"] for r in runs if r.get("frames", {}).get("p95_ms") is not None]
    p99 = [r["frames"]["p99_ms"] for r in runs if r.get("frames", {}).get("p99_ms") is not None]
    low1 = [r["frames"]["low1_fps"] for r in runs if r.get("frames", {}).get("low1_fps") is not None]
    draws = [r["draws"]["mean"] for r in runs if r.get("draws", {}).get("mean") is not None]
    vram = [r["samples"]["vram_peak_mb"] for r in runs if r.get("samples", {}).get("vram_peak_mb")]
    commit = [r["samples"]["commit_peak_mb"] for r in runs if r.get("samples", {}).get("commit_peak_mb")]

    primary_p50 = statistics.median(p50) if p50 else None
    worst_p95 = max(p95) if p95 else None
    worst_low1 = min(low1) if low1 else None
    spread = (max(p50) / min(p50)) if len(p50) > 1 and min(p50) > 0 else None

    return {
        "runs": len(runs),
        "p50_ms": round(primary_p50, 2) if primary_p50 is not None else None,
        "p95_ms": round(worst_p95, 2) if worst_p95 is not None else None,
        "p99_ms": round(max(p99), 2) if p99 else None,
        "low1_fps": round(worst_low1, 3) if worst_low1 is not None else None,
        "fps_p50": round(1000.0 / primary_p50, 2) if primary_p50 else None,
        "draws_mean": round(statistics.fmean(draws), 1) if draws else None,
        "vram_peak_mb": max(vram) if vram else None,
        "commit_peak_mb": max(commit) if commit else None,
        "p50_spread": round(spread, 3) if spread else None,
        "tdr": any(r.get("stability", {}).get("tdr") for r in runs),
        "fatal": any(r.get("stability", {}).get("fatal") for r in runs),
        "valid": all(r.get("gates", {}).get("valid") for r in runs),
        "precision": sorted({r.get("precision", "unknown") for r in runs}),
    }


def aggregate_gates(agg: dict) -> dict:
    stats = {"frames": 10 ** 9, "p50_ms": agg["p50_ms"], "p95_ms": agg["p95_ms"]}
    gates = bench_gate.evaluate(
        stats,
        draws_mean=agg["draws_mean"],
        vram_peak_mb=agg["vram_peak_mb"],
        tdr=agg["tdr"],
        fatal_crash=agg["fatal"],
        min_frames=0,
        precision=",".join(agg["precision"]),
    )
    if not agg["valid"]:
        gates["usable"] = False
        gates["valid"] = False
        gates["verdict"] = "BLOCKED"
        gates["gate_reached"] = None
    return gates


PHASE_COLUMNS = [
    ("cpu_prepare_ms", "prepare"),
    ("copy_ms", "copies"),
    ("texture_ms", "textures"),
    ("gpu_ms", "GPU"),
    ("back_ms", "copy-back"),
    ("heap_ms", "heap pass"),
    ("submit_call_ms", "submit call"),
    ("card_wait_ms", "card wait"),
    ("card_idle_ms", "card idle"),
]


def phases_table(runs: list[dict]) -> str:
    """Mean cost of the frame's parts: where the 33.3 ms actually goes."""
    cols = [
        (key, label)
        for key, label in PHASE_COLUMNS
        if any(r.get("phases", {}).get(key) is not None for r in runs)
    ]
    if not cols:
        return ("_No phase breakdown in these logs. It needs the fps line and the "
                "`usual frame (...)` line at `VICTORY_LOG=info`._")
    head = "| run | " + " | ".join(f"{label} ms" for _, label in cols) + " |\n"
    sep = "|---|" + "---:|" * len(cols) + "\n"
    rows = []
    for r in runs:
        phases = r.get("phases", {})
        cells = " | ".join(n(phases.get(key), 1) for key, _ in cols)
        rows.append(f"| {r.get('run_id', '?')} | {cells} |")
    return head + sep + "\n".join(rows)


def runs_table(runs: list[dict]) -> str:
    head = ("| run | cache | frames | p50 ms | p95 ms | 1% low fps | draws | "
            "VRAM peak MB | commit peak MB | stability |\n"
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---|\n")
    rows = []
    for r in runs:
        f, s, d = r.get("frames", {}), r.get("samples", {}), r.get("draws", {})
        rows.append(
            f"| {r.get('run_id', '?')} | {r.get('cache', '?')} | {f.get('frames', 0)} | "
            f"{n(f.get('p50_ms'))} | {n(f.get('p95_ms'))} | {n(f.get('low1_fps'), 2)} | "
            f"{n(d.get('mean'), 0)} | {n(s.get('vram_peak_mb'), 0)} | "
            f"{n(s.get('commit_peak_mb'), 0)} | {r.get('stability', {}).get('summary', 'n/a')} |"
        )
    return head + "\n".join(rows)


def gates_table(gates: dict) -> str:
    head = ("| gate | target | p50 budget | measured p50 | p95 | result |\n"
            "|---|---:|---:|---:|---:|---|\n")
    rows = []
    for row in gates["gates"]:
        p95_cell = n(row.get("p95_ms"), 2) + " ms" if row.get("p95_gated") else "-"
        rows.append(
            f"| {row['gate']} | {row['fps']:.0f} fps | {row['budget_ms']:.2f} ms | "
            f"{n(row['p50_ms'], 2)} ms | {p95_cell} | {'PASS' if row['passed'] else 'FAIL'} |"
        )
    return head + "\n".join(rows)


def method_block(runs: list[dict], campaign: Path | None) -> str:
    first = runs[0]
    lines = [
        f"- Runtime: **{first.get('runtime_label', first.get('runtime'))}**, "
        f"variant `{first.get('variant')}`, cache `{first.get('cache')}`.",
        f"- Window: {n(first.get('window', {}).get('seconds'), 1)} s per run, "
        f"{len(runs)} runs.",
        f"- Precision: `{', '.join(sorted({r.get('precision', '?') for r in runs}))}` "
        f"(per-frame = `VICTORY_FRAME_LOG=1`; coarse = fps-line averages).",
        f"- Scene protocol: `docs/BENCHMARK-PROTOCOL.md`.",
        f"- Logs: `{first.get('logs', {}).get('stderr')}`.",
    ]
    settings = first.get("settings") or {}
    if settings.get("found") and not settings.get("parse_error"):
        lines.append(f"- {settings_xml.describe(settings)}.")
    else:
        lines.append("- settings.xml: not recorded for these runs.")
    env = first.get("env", {})
    if env:
        lines.append(
            f"- Display/ambient: `{env.get('VICTORY_DISPLAY_MODE', '?')}` / "
            f"`{env.get('VICTORY_AMBIENT', '?')}`; {len(env)} `VICTORY_*` switches "
            f"recorded in `run.json` under `env`."
        )
    launch = first.get("launch", {})
    if launch.get("profile"):
        lines.append(f"- Launcher profile: `{launch['profile']}` (`bench-env.json`).")
    if campaign and campaign.is_file():
        lines.append(f"- Campaign file: `{campaign}`.")
    lines.append(
        "- Aggregate rule: p50 = median of the runs, p95 = worst run, "
        "1% low = worst run's 1000/p99."
    )
    return "\n".join(lines)


def render(runs: list[dict], template: str, campaign: Path | None) -> str:
    agg = aggregate(runs)
    gates = aggregate_gates(agg)
    first = runs[0]

    verdict = gates["verdict"]
    p50 = agg["p50_ms"]
    ratio = (p50 / bench_gate.TARGET_MS) if p50 else None
    if verdict == "PASS":
        summary = (f"p50 **{n(p50, 1)} ms** ({n(agg['fps_p50'], 1)} fps), "
                   f"p95 **{n(agg['p95_ms'], 1)} ms**, 1% low "
                   f"**{n(agg['low1_fps'], 2)} fps** — the 30 fps gate holds.")
    elif p50 is None:
        summary = "No frame data in the window. Check `VICTORY_LOG=info` and the log path."
    elif p50 <= bench_gate.TARGET_MS and agg["p95_ms"] is not None:
        summary = (f"p50 **{n(p50, 1)} ms** meets the 33.3 ms budget, but p95 "
                   f"**{n(agg['p95_ms'], 1)} ms** exceeds 40 ms: the 30 fps gate fails "
                   f"on consistency, not on the average. 1% low "
                   f"**{n(agg['low1_fps'], 2)} fps**.")
    else:
        summary = (f"p50 **{n(p50, 1)} ms** ({n(agg['fps_p50'], 2)} fps), "
                   f"p95 **{n(agg['p95_ms'], 1)} ms**, 1% low **{n(agg['low1_fps'], 2)} fps**. "
                   f"p50 is **{n(ratio, 1)}x** the 33.3 ms budget; gate "
                   f"**{gates['gate_reached'] or 'none'}**.")

    host = first.get("host", {})
    host_lines = [
        f"- GPU: {host.get('gpu', 'n/a')} "
        f"({n(host.get('vram_total_mb'), 0)} MB), driver {host.get('driver', 'n/a')}",
        f"- CPU: {host.get('cpu', 'n/a')}",
        f"- OS: {host.get('os', 'n/a')}",
        f"- Power plan: {host.get('power_plan', 'n/a')}",
    ]

    stability_lines = []
    if agg["p50_spread"] is not None:
        spread = agg["p50_spread"]
        if spread <= 1.10:
            spread_note = "stable"
        elif spread <= 1.25:
            spread_note = "borderline — repeat the campaign before promoting"
        else:
            spread_note = "unstable — reject the campaign"
        stability_lines.append(
            f"- Run-to-run p50 spread: **{n(spread, 3)}x** ({spread_note}; "
            f"promote only at <= 1.10x)."
        )
    settings_sigs = {settings_signature(r) for r in runs} - {None}
    if len(settings_sigs) > 1:
        stability_lines.append(
            "- **settings.xml differs between runs** ("
            + ", ".join(sorted(settings_sigs))
            + "): the arm changed mid-campaign - reject and repeat."
        )
    for r in runs:
        st = r.get("stability", {})
        stability_lines.append(
            f"- `{r.get('run_id')}`: {st.get('summary', 'n/a')} "
            f"(tdr={st.get('tdr')}, fatal={st.get('fatal')})"
        )
        for crash in st.get("crashes_log", []):
            stability_lines.append(
                f"  - {crash['kind']} at {crash['at_utc']}: {crash['text'][:160]}"
            )
        for ev in st.get("eventlog", {}).get("events", []):
            stability_lines.append(
                f"  - event {ev.get('id')} {ev.get('provider')} "
                f"({ev.get('kind')}) at {ev.get('at_utc')}"
            )
        if r.get("notes"):
            stability_lines.append(f"  - note: {r['notes']}")
    for reason in gates["reasons"]:
        stability_lines.append(f"- blocker: {reason}")
    for error in first.get("stability", {}).get("eventlog", {}).get("errors", []):
        stability_lines.append(f"- event log unavailable: {error}")

    values = {
        "TITLE": f"Benchmark report — {first.get('variant', '?')} — "
                 f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
        "VERDICT": f"{verdict} — gate {gates['gate_reached'] or 'none'} "
                   f"(target 30 fps / 33.3 ms p50, p95 <= 40 ms)",
        "SUMMARY": summary,
        "HOST": "\n".join(host_lines),
        "RUNS_TABLE": runs_table(runs),
        "PHASES": phases_table(runs),
        "AGGREGATE": (
            f"- p50 (median of {agg['runs']} run{'s' if agg['runs'] != 1 else ''}): "
            f"**{n(agg['p50_ms'], 2)} ms** = {n(agg['fps_p50'], 2)} fps\n"
            f"- p95 (worst run): **{n(agg['p95_ms'], 2)} ms**\n"
            f"- p99 (worst run): **{n(agg['p99_ms'], 2)} ms**\n"
            f"- 1% low (worst run): **{n(agg['low1_fps'], 3)} fps**\n"
            f"- draws (mean): {n(agg['draws_mean'], 0)}\n"
            f"- VRAM peak: {n(agg['vram_peak_mb'], 0)}{' MB' if agg['vram_peak_mb'] else ''}; "
            f"commit peak: {n(agg['commit_peak_mb'], 0)}"
            f"{' MB' if agg['commit_peak_mb'] else ''}"
        ),
        "GATES": gates_table(gates),
        "STABILITY": "\n".join(stability_lines) or "- none",
        "METHOD": method_block(runs, campaign),
    }
    text = template
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def snapshot_from_csv(path: Path) -> dict:
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    out = []
    for row in rows:
        ms = float(row["ms_per_frame"]) if row.get("ms_per_frame") else None
        fps = float(row["fps"]) if row.get("fps") else None
        out.append(
            {
                "source": row.get("source", ""),
                "date": row.get("date", ""),
                "ms": ms,
                "fps": fps,
                "draws": row.get("draws", ""),
                "dropped": row.get("dropped", ""),
                "note": row.get("note", ""),
                "gate": bench_gate.gate_for(ms),
            }
        )
    return {"rows": out}


def render_snapshot(snapshot: dict, source: Path) -> str:
    rows = snapshot["rows"]
    lines = [
        f"# Baseline snapshot — {source.name}",
        "",
        "Single stored sample per variant. This is **not** the 3-run protocol:",
        "a p95 and a 1% low need per-frame data, which this CSV does not have.",
        "The gate column is indicative only.",
        "",
        "| source | date | ms/frame | fps | draws | dropped | gate (indicative) | note |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['source']} | {row['date']} | {n(row['ms'], 1)} | {n(row['fps'], 1)} | "
            f"{row['draws'] or 'n/a'} | {row['dropped'] or 'n/a'} | "
            f"{row['gate'] or 'below G1'} | {row['note']} |"
        )
    best = min((r for r in rows if r["ms"]), key=lambda r: r["ms"], default=None)
    lines += ["", "## Reading", ""]
    if best:
        ratio = best["ms"] / bench_gate.TARGET_MS
        lines.append(
            f"- Fastest stored sample: **{best['source']}** at {n(best['ms'], 1)} ms "
            f"({n(best['fps'], 1)} fps, {best['draws'] or 'n/a'} draws, "
            f"gate {best['gate'] or 'below G1'})."
        )
        lines.append(
            f"- That is **{n(ratio, 1)}x** the 33.3 ms budget on the hardware named in the note."
        )
    lines += [
        "- To judge the 30 fps gate, run the 3-run protocol in "
        "`docs/BENCHMARK-PROTOCOL.md`; it produces per-frame times, p95 and 1% low.",
        "",
        f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')} "
        f"from `{source}`._",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs", nargs="*", type=Path, default=[])
    ap.add_argument("--variant")
    ap.add_argument("--from-csv", type=Path)
    ap.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    ap.add_argument("--campaign", type=Path, help="campaign.json next to the runs")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args()

    if args.from_csv:
        snapshot = snapshot_from_csv(args.from_csv)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(render_snapshot(snapshot, args.from_csv), encoding="utf-8")
        if args.json_out:
            args.json_out.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.out} ({len(snapshot['rows'])} rows, single-sample snapshot)")
        return 0

    if not args.runs:
        ap.error("give --runs ... or --from-csv FILE")
    missing = [str(p) for p in args.runs if not p.is_file()]
    if missing:
        print("missing run files: " + ", ".join(missing), file=sys.stderr)
        return 2

    runs = load_runs(args.runs)
    if args.variant:
        for run in runs:
            run["variant"] = args.variant
    template = args.template.read_text(encoding="utf-8") if args.template.is_file() else (
        "# {{TITLE}}\n\n**Verdict: {{VERDICT}}**\n\n{{SUMMARY}}\n\n"
        "## Host\n\n{{HOST}}\n\n## Runs\n\n{{RUNS_TABLE}}\n\n"
        "## Frame budget\n\n{{PHASES}}\n\n"
        "## Aggregate\n\n{{AGGREGATE}}\n\n## Gates\n\n{{GATES}}\n\n"
        "## Stability\n\n{{STABILITY}}\n\n## Method\n\n{{METHOD}}\n"
    )

    campaign = args.campaign or (Path(args.runs[0]).parent.parent / "campaign.json")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(runs, template, campaign), encoding="utf-8")

    agg = aggregate(runs)
    gates = aggregate_gates(agg)
    print(f"verdict {gates['verdict']} gate {gates['gate_reached'] or 'none'} "
          f"p50 {n(agg['p50_ms'])} ms p95 {n(agg['p95_ms'])} ms")
    print(f"wrote {args.out}")
    if args.json_out:
        args.json_out.write_text(
            json.dumps({"aggregate": agg, "gates": gates}, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
