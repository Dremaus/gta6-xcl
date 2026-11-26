#!/usr/bin/env python3
"""The 30 fps target and the 5/10/20/30 fps gates.

One definition, used by the collector, the report and the parser CLI.

A run is a measurement window over the reference scene. Gates G1-G3 are judged
on the p50 frame time; the 30 fps gate additionally requires p95 <= 40 ms.
"""

from __future__ import annotations

TARGET_FPS = 30.0
TARGET_MS = 1000.0 / TARGET_FPS  # 33.333...
TARGET_P95_MS = 40.0

# (gate, fps, p50 budget in ms)
GATES = [
    ("G1", 5.0, 200.0),
    ("G2", 10.0, 100.0),
    ("G3", 20.0, 50.0),
    ("G4", 30.0, TARGET_MS),
]

# A window must show real 3D gameplay, not the menu (41 draws) or a loading
# screen. The measured scene has run 1 011-5 183 draws on this laptop.
MIN_FRAMES = 10
MIN_DRAWS = 100
MAX_DRAWS = 9000
# 8 GB card: past ~7 800 MB the title starts evicting and the frame time is
# no longer a property of the code under test.
VRAM_LIMIT_MB = 7800


def gate_for(p50_ms: float | None) -> str | None:
    """Highest gate whose p50 budget is met (p50 ladder only)."""
    if p50_ms is None:
        return None
    reached = None
    for name, _fps, budget in GATES:
        if p50_ms <= budget:
            reached = name
    return reached


def reached_gate(p50_ms: float | None, p95_ms: float | None, usable: bool = True) -> str | None:
    """Highest gate fully met: p50 budget, and for 30 fps also p95 <= 40 ms."""
    if not usable or p50_ms is None:
        return None
    reached = None
    for name, fps, budget in GATES:
        if p50_ms > budget:
            continue
        if fps >= TARGET_FPS and not (p95_ms is not None and p95_ms <= TARGET_P95_MS):
            continue
        reached = name
    return reached


def gate_table(p50_ms: float | None, p95_ms: float | None) -> list[dict]:
    rows = []
    for name, fps, budget in GATES:
        p50_ok = p50_ms is not None and p50_ms <= budget
        p95_ok = p95_ms is not None and p95_ms <= TARGET_P95_MS
        needs_p95 = fps >= TARGET_FPS
        rows.append(
            {
                "gate": name,
                "fps": fps,
                "budget_ms": round(budget, 2),
                "p50_ms": p50_ms,
                "p95_ms": p95_ms,
                "passed": p50_ok and (p95_ok if needs_p95 else True),
                "p95_ok": p95_ok,
                "p95_gated": needs_p95,
            }
        )
    return rows


def evaluate(
    stats: dict,
    *,
    draws_mean: float | None,
    vram_peak_mb: float | None,
    tdr: bool,
    fatal_crash: bool,
    min_frames: int = MIN_FRAMES,
    precision: str = "per-frame",
) -> dict:
    """Judge one measurement window.

    ``usable`` says the window is evidence at all: enough frames, a real 3D
    scene (draws in band), no device loss, no fatal crash. ``PASS`` needs a
    usable window that also meets p50 <= 33.3 ms and p95 <= 40 ms. A usable
    window that misses the target is ``FAIL``; an unusable one is ``BLOCKED``.
    """
    reasons: list[str] = []
    frames = int(stats.get("frames") or 0)
    p50 = stats.get("p50_ms")
    p95 = stats.get("p95_ms")

    if frames < min_frames:
        reasons.append(f"too few frames in the window: {frames} < {min_frames}")
    if draws_mean is None:
        reasons.append("no draws/frame in the window (is VICTORY_LOG=info set?)")
    elif draws_mean < MIN_DRAWS:
        reasons.append(f"menu-level draws: {draws_mean:.0f} < {MIN_DRAWS} (not the 3D scene)")
    elif draws_mean > MAX_DRAWS:
        reasons.append(f"draws above the expected band: {draws_mean:.0f} > {MAX_DRAWS}")
    if tdr:
        reasons.append("device removed / TDR during the window")
    if fatal_crash:
        reasons.append("fatal crash during the window")

    draws_ok = draws_mean is not None and MIN_DRAWS <= draws_mean <= MAX_DRAWS
    usable = p50 is not None and frames >= min_frames and draws_ok and not tdr and not fatal_crash
    p95_ok = p95 is not None and p95 <= TARGET_P95_MS
    g4 = usable and p50 <= TARGET_MS and p95_ok

    if vram_peak_mb is not None and vram_peak_mb > VRAM_LIMIT_MB:
        reasons.append(
            f"VRAM peak {vram_peak_mb:.0f} MB > {VRAM_LIMIT_MB} MB (eviction risk, not a verdict blocker)"
        )

    if g4:
        verdict = "PASS"
    elif usable:
        verdict = "FAIL"
    else:
        verdict = "BLOCKED"

    return {
        "verdict": verdict,
        "target_fps": TARGET_FPS,
        "target_ms": round(TARGET_MS, 3),
        "target_p95_ms": TARGET_P95_MS,
        "usable": usable,
        "valid": usable,
        "g4_pass": g4,
        "gate_reached": reached_gate(p50, p95, usable),
        "precision": precision,
        "reasons": reasons,
        "gates": gate_table(p50, p95),
    }
