# Shader failure inventory + first-bind/DROPPED mapping

**Date:** 2026-11-26  
**Role:** independent shader/pipeline engineer (NOT performance — no zero-copy CBV, relay, queue2, port submission)  
**Scope:** read-only — no changes to `D:\git\VItoriaBr-opt`, no game launch, no game bytes in repo (hashes and reasons only).  
**License:** GPL-3.0  
**Companion CSV:** `D:\git\gta6-30fps\docs\shader-failures.csv`

---

## 0. Executive summary

| Finding | Confidence | Where |
|---|---|---|
| 7 compute shaders refused by host pipeline with `0x80070057` (`E_INVALIDARG` from `CreateComputePipelineState`) | Very high | `host.rs:602-605`, all fast/ab-d2 logs |
| 6 of them named in brief: `02384a60fda6f2d0`, `369cbe906ea72764`, `2cc4c197ee29e291`, `2da4beb386509b77`, `6b82bc7d22016cb5`, `5dc3b25986622949` | Very high | logs |
| 7th compute also refused: `6f225b641c5b0708` (in ab-d2D2-0, ab-d2D2-0r, ab-d2D2-1..5, fast2, fast3, fast4) | Very high | logs |
| Cause of `0x80070057` — **confirmed: wave64** (all 7 emit wave64 DXIL on a 32-lane host; `CreateComputePipelineState` E_INVALIDARG) | Very high | instrumented `translate --pipelines --list` with `VICTORY_TRANSLATE_ONLY`; `emit/mod.rs` wave64 retry does not convert them |
| GS/ES never reach host pipeline (`host.rs:413-421`, `emit/mod.rs:315-331`) | Confirmed by source | emit filters Vs/Ps/Cs/Ms only |
| PS lacks system SGPR model (`io.rs:335-340`, `lower.rs:2450`) | Confirmed by source | `initialized_sgprs` only for CS |
| `MASK_ELSEWHERE` in lane-mask lowering (`lower.rs:3272-3331`) | Confirmed by source | ballot can't restore out-of-active-block lanes |
| Ray-tracing structure builder OFF — thousands of drops/frame | Confirmed by logs + source | `pipeline.rs:380-434`, `builder_off` |
| `note_drop`/`note_why` carry NO draw_id — cannot map to visible geometry yet | Confirmed by source | `draw.rs`, `pipeline.rs:574-594` |

**P0 for visible geometry:** the ray-tracing structure builder (thousands of drops/frame; BVH unbuilt → black/missing surfaces) and any of the 7 refused compute shaders that feed visible passes (unknown until first-bind/DROPPED mapping exists).  
**P1:** PS system-SGPR gap, CS lane-mask gap, GS/ES (195 GS = voxelization/GI, not primary geometry per `SHADER-PIPELINE.md:186-192`).  
**P2:** int3 title-side assert and write-AV (separate crash class, not shader-related).

---

## 1. How a shader gets (or doesn't get) a host pipeline

### 1.1 Translation gate (`crates/victory-shader/src/emit/mod.rs:315-331`)

`translate_plain()` selects exactly one native program per container:
```
matches!(p.stage, HwStage::Vs | HwStage::Ps | HwStage::Cs | HwStage::Ms)
```
GS and ES containers end with `"a container without a vertex, pixel, compute or mesh program"` — refused before the host ever sees them.

### 1.2 Host pipeline gate (`crates/victory-gpu/src/pipeline/host.rs:404-422`)

`HostPipeline::new()` accepts only:
- one compute shader, OR
- vertex/mesh + optional pixel

Any other stage → `refuse("only vertex, mesh, pixel and compute stages are translated")`, logged **once per reason** (not once per hash).

### 1.3 PSO creation (`crates/victory-gpu/src/pipeline/library.rs:512-565`)

`library::pipeline()` tries the pipeline library first (`load`), then calls `create()` = `ID3D12Device::CreateComputePipelineState` directly. On `E_INVALIDARG` (0x80070057) the pipeline is refused and logged at `host.rs:602-605`:
```
host pipeline refused error=Parametr jest niepoprawny. (0x80070057) shaders=[compute <hash>]
```
**No wave size, root-parameter count, sampler count, or DXIL feature is logged** — that is the gap to close. (Closed by instrumented run: all 7 are wave=64 with small root_params 1-4, samplers 0-6.)

### 1.4 First bind / DROPPED (`crates/victory-gpu/src/pipeline.rs:493-605`, `draw.rs`)

- `bound()` logs `first bind` once per pipeline when a list binds it (stage, size, hash) — **no draw id**.
- `note_drop()` → `note_why()` → `capture::op(0, "DROPPED <why>")` — **no hash, no draw id, no stage**.
- `note_drop()` is called from `draw.rs` (draw/dispatch/execute_indirect paths) and `list.rs`, but the `why` string from `make::missing()` is `"refused {...}"` or `"<stage> <hash>"` — **not tied to a draw**.
- `take_drops()` is called once per 5 s host frame line (`host.rs:7579`).

**Gap:** there is no `first_bind → hash → reason → draw_id` chain. `VICTORY_DROP_MAP=1` (diagnostics-only, once per hash: `DROPPED <hash> <stage> <reason> <draw_id/geometry>`) is needed to separate P0 (feeds visible geometry) from P1/P2 (cosmetic).

---

## 2. Refused compute shaders — `0x80070057`

Observed in every log (ab-d2baseline, ab-d2D2-0/0r/1/2/2r/3/3b/3c/4/5, fast2, fast3, fast4). All 7 share the same signature: DXIL validates OK, translation OK, `CreateComputePipelineState` fails with `E_INVALIDARG`.

| # | Hash | Stage | Logs seen | user_data | samplers |
|---|------|-------|-----------|-----------|----------|
| 1 | `02384a60fda6f2d0` | compute | ab-d2baseline, ab-d2D2-0/0r/1/2/2r/3/3b/3c/4/5, fast2, fast3, fast4 | 3 | 0 |
| 2 | `369cbe906ea72764` | compute | same | 1 | 0..2 |
| 3 | `2cc4c197ee29e291` | compute | same | 3 | 1 |
| 4 | `2da4beb386509b77` | compute | same | 2 | 2 |
| 5 | `6b82bc7d22016cb5` | compute | ab-d2baseline, ab-d2D2-0/0r/1/2/2r/3/3b/3c/4, fast2, fast3 | — | — |
| 6 | `5dc3b25986622949` | compute | ab-d2baseline, ab-d2D2-0/0r/1/2/2r/3/3b/3c/4, fast2, fast3 | — | — |
| 7 | `6f225b641c5b0708` | compute | ab-d2D2-0/0r/1/2/2r/3/3b/3c/4/5, fast2, fast3 | — | — |

(user_data/samplers come from `shader translated` tracing lines: `user_data=N`, `samplers=M`.)

### 2.1 Cause of `0x80070057` — confirmed: **wave64** (emitted DXIL)

**CONFIRMED by instrumented run** (worktree `D:\git\VItoriaBr-shader-diag`, now removed; not committed to main). All 7 refused compute shaders emit **wave64 DXIL** (`emitted_wave=Some(64)`) on a host with 32-lane waves (RTX 4060 Laptop). `CreateComputePipelineState` rejects wave64 DXIL with `E_INVALIDARG` (0x80070057). The console-side `native.wave64` flag is also true for all 7, but the diagnostic reads the *emitted* DXIL wave size (`HostShader.wave_size`), not the input flag.

Diagnostic output per hash (`VICTORY_DIAG compute_refused hash=? stage=compute hr=0x80070057 emitted_wave=Some(64) ...`):

| # | Hash | Shader name | input_wave | emitted_wave | cross_lane_ops | LDS_dwords | root_params | samplers | dxil_len | hr | Verdict |
|---|------|-------------|------------|--------------|--------------|------------|-------------|----------|----------|-----|---------|
| 1 | `02384a60fda6f2d0` | `CS_DefragHeap_ComputeRelocations_9e6def81_Wrapped` | 64 | 64 | yes (lane ops / wide blocks) | 128 | 1 | 0 | 7112 | 0x80070057 | **wave64 → host 32-lane reject** |
| 2 | `369cbe906ea72764` | `CS_Visibility_7226f52c_Wrapped` | 64 | 64 | no cross-lane; LDS shared in wave | 128 | 1 | 0 | 6308 | 0x80070057 | **wave64 → host 32-lane reject** |
| 3 | `2cc4c197ee29e291` | `CS_Tiling_Generate_Opaque_fe0149af_Wrapped` | 64 | 64 | yes (lane ops / wide blocks) | 4224 | 3 | 1 | 7772 | 0x80070057 | **wave64 → host 32-lane reject** |
| 4 | `2da4beb386509b77` | `CS_AlphTransmissionPrefilterMip_610a2fad_Wrapped` | 64 | 64 | yes (lane ops / wide blocks) | 128 | 2 | 2 | 10448 | 0x80070057 | **wave64 → host 32-lane reject** |
| 5 | `6b82bc7d22016cb5` | `CS_CollectTriangles_Meshlets_cb481f38_Wrapped` | 64 | 64 | yes (lane ops / wide blocks) | 8192 | 4 | 0 | 47300 | 0x80070057 | **wave64 → host 32-lane reject** |
| 6 | `5dc3b25986622949` | `CS_TransmissionVolumetrics_Tiled_ff333313_Wrapped` | 64 | 64 | yes (lane ops / wide blocks) | 128 | 3 | 6 | 44932 | 0x80070057 | **wave64 → host 32-lane reject** |
| 7 | `6f225b641c5b0708` | `CS_TransmissionVolumetrics_Tiled_LocalLights_ff333313_Wrapped` | 64 | 64 | yes (lane ops / wide blocks) | 128 | 3 | 6 | 67808 | 0x80070057 | **wave64 → host 32-lane reject** |

Method: instrumented `emit::Host::compute_pipeline` (the path `translate --pipelines` uses — `translate.rs:637`) to eprintln `VICTORY_DIAG compute_refused hash=? stage=compute hr=0x80070057 emitted_wave=N root_params=N samplers=N user_data_dwords=N dxil_len=N` on `CreateComputePipelineState` failure. `wave_size` field added to `HostShader` (`emit/mod.rs`) populated from the emitted `wave_size` (not the console-side `native.wave64`), so `emitted_wave=64` is the *emitted* DXIL wave. Additional `VICTORY_WAVE_LOWER_DEBUG` in `lower.rs:1376` showed `group`, `console_lanes`, `one_wave`, `lds_dwords` per shader.

**Root cause:** all 7 are console wave64 compute programs. The `emit/mod.rs:367-395` wave64→32 retry (`without_early_outs` / `with_local_waves` / `with_local_waves_any`) does not convert them to 32-lane DXIL — translation succeeds (7/7 translated) but the emitted DXIL still requires 64 lanes, so `CreateComputePipelineState` on the 32-lane host fails with `E_INVALIDARG`. The retry fails because these shaders use cross-lane operations (ballot, lane reads/writes, LDS shared within a console wave) that cannot be safely lowered to per-half-wave execution without LDS exchange dwords, which the current retry does not emit.

**Ruled out:** root signature too large (root_params 1-4, all small), too many samplers (0-6), descriptor/view-heap overflow (dxil 6-68KB, no view-heap indices past caps), unsupported DXIL feature (translation+emit succeed; only PSO creation fails). Wave64 is the sole cause.

**Fix 2 status:** NOT yet implemented. The retry in `emit/mod.rs:367-395` needs to be extended to emit wave32 DXIL with correct cross-lane emulation (LDS exchange dwords for masks/lane reads that cross halves, `with_local_waves` with `local_ok=true` for intra-half operations). Do not remove `WaveSize` without emulation.

---

## 3. Other failure categories

| Category | Count (est.) | Source | Notes |
|---|---|---|---|
| GS refused (stage not translated) | 195 (per `SHADER-PIPELINE.md:186-192`) | `emit/mod.rs:315-331`, `host.rs:413-421` | Voxelization/GI, not primary geometry. P1 pending first-bind. |
| ES refused | included above | same | ES→GS handover `s_setpc_b64` treated as indirect jump (`lower.rs:10589`), refused. |
| PS missing system SGPR | ~10 (per brief) | `io.rs:335-340`, `lower.rs:2450` | `initialized_sgprs` only for CS; PS reads `Val::Missing("a hardware SGPR input")`. |
| CS `MASK_ELSEWHERE` | ~1 (per brief) | `lower.rs:3272-3331` | Ballot can't restore lanes outside active block. |
| Ray-tracing builder stages | 64 programs walk RT structures; builder OFF | `pipeline.rs:320-434` | Thousands of drops/frame. `CS_IrradianceCache_ShadowTrace_WithFar` (f607780aa8e502d0) named. |
| Unknown (48, per `SHADER-PIPELINE.md:186-192`) | 48 | not confirmed by `--list` run | No current `--list` output available (large .rpf archives skipped by 2 GB `MAX_FILE`). |

---

## 4. First-bind / DROPPED mapping — status

`capture::op()` writes `DROPPED <why>` only when `VICTORY_CAPTURE` is set and the frame is listed; `take_drops()` aggregates by reason string only. Neither carries hash + draw id.

**Needed:** diagnostics-only `VICTORY_DROP_MAP=1` in `draw.rs`/`pipeline.rs`, logging once per hash:
```
DROPPED <hash> <stage> <reason> <draw_id/geometry>
```
Then run the world (operator approval, 5 min, screenshot + log) to classify each refused shader as P0 (feeds visible geometry) vs P1/P2 (cosmetic).

Without this, P0 vs P1/P2 cannot be assigned. The ray-tracing builder is the leading P0 candidate purely by volume (thousands of drops/frame), but that is inference, not measurement.

---

## 5. Proposed fixes (gain/risk order)

## 5. Proposed fixes (gain/risk order)

### Fix 1 — Diagnose `0x80070057` — COMPLETE
**Done:** instrumented `emit::Host::compute_pipeline` in worktree `D:\git\VItoriaBr-shader-diag` (removed after use, not committed). All 7 refused compute shaders emit wave64 DXIL on a 32-lane host → `CreateComputePipelineState` E_INVALIDARG.
**Regression test:** `translate --pipelines --list` on `shaders.rpf` with `VICTORY_TRANSLATE_ONLY=<hash>` for each refused hash → `CreateComputePipelineState` returns 0x80070057 (reproduced).
**Risk:** none (diagnostics only).

### Fix 2 — Compute wave64 → host-wave lowering (NEXT SINGLE FIX, P0/P1)
**What:** all 7 compute shaders are console wave64 programs on a 32-lane host. The `emit/mod.rs:367-395` wave64→32 retry does not convert them. Extend the retry so the *emitted DXIL* targets the host wave size (32), so `CreateComputePipelineState` accepts it. Alternative: refuse gracefully with a clear reason and let the title fall back (degrades the affected passes).
**Acceptance:** refused compute count drops from 7 to 0; `translate --pipelines --list` on each refused hash yields "pipeline created"; pixel-compare vs reference shows no regression on lighting/culling/transmission passes.
**Risk:** medium — wrong wave lowering changes cross-lane results (ballot, shared memory, wave ops). Validate with pixel compare on the affected passes (alpha resolve, visibility, tiling, defrag heap, triangle clip/meshlets, transmission volumetrics).

### Fix 3 — Ray-tracing structure builder decision (P0)
**What:** decide `VICTORY_BVH_BUILDER=1` (all builder stages must have host pipelines — all-or-none, `pipeline.rs:403-434`) or `VICTORY_BVH_HOLD=1` with logged, bounded drops. Current state: builder off, thousands of silent drops/frame.
**Acceptance:** `dropped ... ray-tracing structure builder` = 0 (if on) or a stable, logged, bounded drop (if off); no new artefacts in pixel-compare regression (same save/camera, 3 runs).
**Risk:** high if on (builder stores into title memory; run 98 showed title death within 1 s of first builder submission when 14/35 stages translated).

### Fix 4 — PS system SGPR (P1)
**What:** parse `SPI_SHADER_PGM_RSRC2_PS.user_sgpr`; add `Input::PsSystem` for `{bc_optimize, prim_mask, lds_offset}`; if usage is only `s_mov_b32 m0, sN` → `v_interp*`, substitute 0/undef; else refuse with precise reason.
**Acceptance:** 10/10 PS translate + validate + PSO; buffer output matches reference; no PS count regression.
**Risk:** low — PS either translates with substituted system values or is refused explicitly.

### Fix 5 — CS `MASK_ELSEWHERE` lane mask (P1)
**What:** for groups ≤ 64 lanes replace 64-bit mask with LDS (`groupshared`); for multi-wave, per-wave masks + sum.
**Acceptance:** 1/1 CS translates; no CS count regression.
**Risk:** low-medium.

### Fix 6 — GS/ES (P2, large change)
**What:** implement GS/ES translation (compute + mesh passthrough) — large translator change.
**Acceptance:** pixel-compare regression; GS count > 0 translates.
**Risk:** high — XCL is GPL-2.0 (reimplement from description only, no copy); needs pixel-compare test harness.

**Not proposed:** any DRM/anti-tamper bypass; no patching of the title `0xCC` int3 (`image+0x5149aec`); no `--pipelines` parallel with a running game.

### Fix 3 — Ray-tracing structure builder decision (P0)
**What:** decide `VICTORY_BVH_BUILDER=1` (all 35 builder stages must have host pipelines — all-or-none, `pipeline.rs:403-434`) or `VICTORY_BVH_HOLD=1` with logged, bounded drops. Current state: builder off, thousands of silent drops/frame.
**Acceptance:** `dropped ... ray-tracing structure builder` = 0 (if on) or a stable, logged, bounded drop (if off); no new artefacts in pixel-compare regression (same save/camera, 3 runs).
**Risk:** high if on (builder stores into title memory; run 98 showed title death within 1 s of first builder submission when 14/35 stages translated).

### Fix 4 — PS system SGPR (P1)
**What:** parse `SPI_SHADER_PGM_RSRC2_PS.user_sgpr`; add `Input::PsSystem` for `{bc_optimize, prim_mask, lds_offset}`; if usage is only `s_mov_b32 m0, sN` → `v_interp*`, substitute 0/undef; else refuse with precise reason.
**Acceptance:** 10/10 PS translate + validate + PSO; buffer output matches reference; no PS count regression.
**Risk:** low — PS either translates with substituted system values or is refused explicitly.

### Fix 5 — CS `MASK_ELSEWHERE` lane mask (P1)
**What:** for groups ≤ 64 lanes replace 64-bit mask with LDS (`groupshared`); for multi-wave, per-wave masks + sum.
**Acceptance:** 1/1 CS translates; no CS count regression.
**Risk:** low-medium.

### Fix 6 — GS/ES (P2, large change)
**What:** implement GS/ES translation (compute + mesh passthrough) — large translator change.
**Acceptance:** pixel-compare regression; GS count > 0 translates.
**Risk:** high — XCL is GPL-2.0 (reimplement from description only, no copy); needs pixel-compare test harness.

**Not proposed:** any DRM/anti-tamper bypass; no patching of the title `0xCC` int3 (`image+0x5149aec`); no `--pipelines` parallel with a running game.

---

## 6. Unknowns

| # | Unknown | Impact |
|---|---|---|
| U1 | Root cause of `0x80070057` for the 7 compute shards | **CLOSED — wave64** (all 7 emit wave64 DXIL on 32-lane host) |
| U2 | Which refused shader feeds visible geometry (first-bind/DROPPED missing draw id) | High — P0 vs P1/P2 unassignable for compute shaders |
| U3 | Whether ray-tracing builder feeds visible passes | High — P0 if yes, acceptable-drop if no |
| U4 | `254` shader count (195 GS + 10 PS + 1 CS + 48 unknown) not confirmed by current `--list` | Medium — large .rpf archives skipped by 2 GB limit |
| U5 | Whether `VICTORY_DROP_MAP=1` instrumented run is approved | Medium — blocks P0 assignment for compute shaders |

---

## 7. Next single fix

**Extend the `emit/mod.rs:367-395` wave64→32 retry so the *emitted DXIL* targets the host wave size (32) for compute shaders.** All 7 refused compute shaders emit wave64 DXIL on a 32-lane host; `CreateComputePipelineState` rejects them with 0x80070057. U1 is closed (cause = wave64), so this fix directly addresses the root cause.

Acceptance: `translate --pipelines --list` on each refused hash (`VICTORY_TRANSLATE_ONLY=<hash>`) yields "pipeline created"; refused compute count drops from 7 to 0; pixel-compare vs reference shows no regression on the affected passes (alpha resolve, visibility, tiling, defrag heap, triangle clip/meshlets, transmission volumetrics).

Do not commit instrumentation to `D:\git\VItoriaBr-opt` (read-only). The instrumented worktree `D:\git\VItoriaBr-shader-diag` was removed after use.

**After Fix 2:** run the world with `VICTORY_DROP_MAP=1` (operator approval, 5 min, screenshot + log) to classify each refused shader as P0 (feeds visible geometry) vs P1/P2 (cosmetic) — closes U2.
