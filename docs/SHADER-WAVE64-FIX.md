# Shader wave64→32 fix — design

**Date:** 2026-11-26  
**Role:** independent shader/pipeline engineer  
**Status:** design only — not implemented, not committed  
**License:** GPL-3.0  
**Companion:** `SHADER-FAILURES.md`, `shader-failures.csv`

---

## Problem

All 7 refused compute shaders emit **wave64 DXIL** (`emitted_wave=Some(64)`) on a host with 32-lane waves (RTX 4060 Laptop). `CreateComputePipelineState` rejects wave64 DXIL with `E_INVALIDARG` (0x80070057).

| Hash | Shader | group | console_lanes | LDS_dwords | emitted_wave |
|------|--------|-------|---------------|------------|--------------|
| `02384a60fda6f2d0` | CS_DefragHeap_ComputeRelocations | 64 | yes | 128 | 64 |
| `369cbe906ea72764` | CS_Visibility | 64 | no | 128 | 64 |
| `2cc4c197ee29e291` | CS_Tiling_Generate_Opaque | 128 | yes | 4224 | 64 |
| `2da4beb386509b77` | CS_AlphTransmissionPrefilterMip | 256 | yes | 128 | 64 |
| `6b82bc7d22016cb5` | CS_CollectTriangles_Meshlets | 1024 | yes | 8192 | 64 |
| `5dc3b25986622949` | CS_TransmissionVolumetrics_Tiled | 64 | yes | 128 | 64 |
| `6f225b641c5b0708` | CS_TransmissionVolumetrics_Tiled_LocalLights | 64 | yes | 128 | 64 |

The `emit/mod.rs:367-395` wave64→32 retry (`without_early_outs` / `with_local_waves` / `with_local_waves_any`) does not convert them. Translation succeeds (7/7 translated) but emitted DXIL still requires 64 lanes.

**Root cause:** shaders use cross-lane operations (ballot, lane reads/writes, LDS shared within a console wave, wide blocks) that cannot be safely lowered to per-half-wave execution without LDS exchange dwords, which the current retry does not emit.

**Ruled out:** root signature too large (root_params 1-4), too many samplers (0-6), descriptor/view-heap overflow, unsupported DXIL feature. Wave64 is the sole cause.

---

## Fix design

### Approach

Extend the wave64→32 retry in `emit/mod.rs:367-395` so the *emitted DXIL* targets host wave size (32) with correct cross-lane emulation:

1. **For shaders where all cross-lane code stays within 32-lane halves** (DPP rows, `ds_swizzle`, `v_permlane16`/`v_permlanex16`): existing `with_local_waves` path already works — ensure it is reached.

2. **For shaders with cross-half operations** (`v_mbcnt`, `v_readlane`, `v_writelane`, `ds_permute`, `ds_bpermute`, masks as numbers, lane-constant masks): emit wave32 DXIL with **LDS exchange dwords** — lanes 32..63 are the other host wave; masks, lane reads and lane numbers go through two exchange dwords past the program's LDS (already partially implemented in `lower.rs:1433-1439` via `exchange = Some((s.lds_dwords, group <= 32, all))`).

3. **For shaders with LDS shared within a console wave without barriers** (group > 32 threads with LDS): split into two waves of 32, insert a group barrier before every LDS access (already partially implemented in `lower.rs:1406-1431` via `lds_meetings`).

### Code changes

**`crates/victory-shader/src/emit/mod.rs`** (lines 367-395):
- Extend the `done()` closure to accept wave=32 from any retry form (currently requires `*wave != Some(64)`).
- Ensure `with_local_waves_any` is reached as a final fallback for all compute shaders (not gated behind `!strict && !exact_only` in a way that skips it).
- Add `VICTORY_WAVE_FORCE_32=1` escape hatch: force wave32 emission for compute shaders, accepting potential cross-lane result differences (for debugging / controlled rollout).

**`crates/victory-shader/src/emit/lower.rs`** (lines 1376-1439):
- Broaden the `if !partial && wave == 64 && host_max_wave() == 32 && (...)` condition so more shaders enter the wave32 path.
- Ensure `exchange` LDS dwords are allocated when `crosses=true` (line 1433-1439 already does this; verify it is reached).
- Ensure `lds_meetings` barrier insertion works for group > 32 (line 1417-1419).

### What is NOT changed
- `HostShader.wave_size` field (already added in diagnostic worktree — keep it).
- `Translated.wave_size` field (already added — keep it).
- `VICTORY_DIAG` eprintln in `host.rs` (keep for observability).

---

## Build and test commands

All commands run in worktree `D:\git\VItoriaBr-shader-diag` (NOT in `D:\git\VItoriaBr-opt`):

```powershell
# Build
cd D:\git\VItoriaBr-shader-diag
cargo build --offline --release -p victory -j 2 --features diagnostics

# CPU tests (no game, no GPU)
cargo test --offline --release -p victory-shader --lib -j 2
cargo test --offline --release -p victory-gpu --lib -j 2

# Focused translate (GPU-free, offline)
$env:VICTORY_TRANSLATE_ONLY='02384a60fda6f2d0,369cbe906ea72764,2cc4c197ee29e291,2da4beb386509b77,6b82bc7d22016cb5,5dc3b25986622949,6f225b641c5b0708'
$env:VICTORY_HOST_MAX_WAVE='32'
$env:VICTORY_VIEW_LIMIT='1000000'
$env:VICTORY_SHADER_LOOP_LIMIT='256'
.\target\release\victory.exe translate 'D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\shaders.rpf' --pipelines --list --jobs 1
```

**Acceptance:**
- All 7 hashes → "pipeline created", 0 refused
- Emitted DXIL wave = 32 for all 7
- CPU unit tests pass (victory-shader, victory-gpu)
- Pixel-compare (if possible): alpha resolve, visibility, tiling, defrag heap, triangle clip/meshlets, transmission volumetrics — no regression

---

## Risk

- **Medium.** Wrong wave lowering changes cross-lane results (ballot, shared memory, wave ops).
- Shader `369cbe906ea72764` (CS_Visibility) has `console_lanes=false` but `lds_dwords=128` and `one_wave=true` — LDS shared within a single console wave of 64 threads; splitting to 2 host waves of 32 needs barriers.
- Shader `6b82bc7d22016cb5` (CS_CollectTriangles_Meshlets) has `group=1024`, `lds_dwords=8192` — many console waves, large LDS; exchange dwords per group may be significant.

---

## Rollback

- Revert `emit/mod.rs` and `emit/lower.rs` changes (worktree only, not committed to `D:\git\VItoriaBr-opt`).
- Set `VICTORY_WAVE_FORCE_32=0` (or unset) to disable the escape hatch.
- Fall back to refusing wave64 compute shaders gracefully (current behavior — drops, no crash).

---

## Next step after Fix 2

Run the world with `VICTORY_DROP_MAP=1` (operator approval, 5 min, screenshot + log) to classify each refused shader as P0 (feeds visible geometry) vs P1/P2 (cosmetic). This closes U2 (which compute shader feeds visible geometry).

---

## Files changed (in worktree only)

- `crates/victory-shader/src/emit/mod.rs` — wave64→32 retry extension
- `crates/victory-shader/src/emit/lower.rs` — LDS exchange / barrier logic
- `crates/victory-gpu/src/pipeline.rs` — `Translated.wave_size` field + `VICTORY_DROP_MAP`
- `crates/victory-gpu/src/pipeline/host.rs` — `VICTORY_DIAG` eprintln
- `crates/victory-gpu/src/shader_cache.rs` — propagate `wave_size`
- `crates/victory-shader/src/emit/mod.rs` — `HostShader.wave_size` field

**Not committed** to `D:\git\VItoriaBr-opt` (read-only). **Not committed** to `D:\git\gta6-30fps` (docs only).
