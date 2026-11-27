# 8 — RT/BVH builder: Victory-NVIDIA evidence, XCL state, 8 GB call

**Verdict:** keep RT/BVH **off** on the 8 GB RTX 4060. `XCL_RAYTRACING` only
edits OPTIONS5, and both title logs show it is never queried; the builder is not
running either. Victory's default is also RT off (slow/incomplete). Checked
`D:\git\xcl` b75c0f30 + worktree `D:\git\xcl-wt-rt`; no code change.
## 1. What Victory-NVIDIA changed (GPL-3.0 clone, ideas only)
- **Diagnosis (77e13a9, 2026-11-25):** builder could not run on NVIDIA; every
  ray missed, rooms went white depending on view. They skipped 1,000
  `CS_RaytracingResolve` + 34 traced-shadow programs (`VICTORY_SKIP_PIPELINES` /
  `rt_off_hashes.txt`), kept screen-probe/visibility traces (skipping left
  rainbow glitter), and added `VICTORY_AMBIENT_MOST`: do not shade rays that
  have no structures.
- **Builder fixes (6a2d9f9, 24a479d, 30f46c9, 2c20d7a, adf5706, b558934,
  810efe5, 96bfd0e):** 59/64 trace programs and irradiance shading translate;
  builder programs are recognised by spilled user data (`spill.rs`);
  `image_bvh(64)_intersect_ray` emulated (`bvh.rs`, `emit/lower.rs`); memory by
  raw address (`memory.rs`); root UAVs, byte/16-bit accesses, fences, bounds.
  `VICTORY_BVH_MISS=1` makes stale nodes miss instead of walking garbage.
- **All-or-none (`pipeline.rs:239-360`):** all builder pipelines must have host
  pipelines before any stage runs; the first dispatch creates them all. A partly
  translated builder wrote garbage bounds and killed the title (run 98).
- **Real RT option (6395727):** `-RayTracing` / `VICTORY_BVH_BUILDER=1`; builder
  runs on NVIDIA on CGBJ's renderer. RTX 5070, Series S, DLSS: 15-17 fps without,
  13-15 with; +frame generation ~0.1 fps. Menu: "RAY TRACING (SLOW, BROKEN)"
  (`menu.rs:76`). Builder drops fell from ~6,640/frame (`ab-d2baseline`) to ~1.
- **Descriptor slots are separate:** a9632bc: NVIDIA caps the view heap at
  1,000,000 vs 1,245,184, so the 2^18 dynamic pool refused 1,100-4,800 tables/
  frame; `VICTORY_DYNAMIC_SLOTS=524288` -> 0-33; 47747d6 fixed cross-heap
  release. Graphics draws, not builder dispatches.
- **Current state (`README.md:207`, `fork-ray-tracing.md`):** no RT by default.
  Builder costs ~40 ms/frame; structures overlap (8/65 good), ~90 missing
  pages/frame, 5 shadow programs do not translate.
## 2. XCL today
- `config.rs:53-56,253-266`: `raytracing = "auto" | "off" | "tier1_0" |
  "tier1_1"`, `XCL_RAYTRACING` overrides `xcl.toml`. `real.rs:3031-3045` applies
  it to OPTIONS5 and logs the first call; `null.rs:417-420` does the same on the
  null backend. No other consumer exists in the tree.
- On an RTX 4060 (DXR 1.1): `auto` -> 11, `tier1_1` -> 11, `tier1_0` -> 10,
  `off` -> 0. That number is the only difference; XCL's path never changes.
- Observed: `xcl.toml` has `raytracing = "off"`; `xcl.log` (17:08) and
  `xcl.prev.log` contain no `CheckFeatureSupport(D3D12_OPTIONS5)` line. The
  title never queried it, so all four values are equivalent here. (The `.bak`
  used `auto`/anaconda; these logs are lockhart/off.)
- **Builder support is real but opt-in:** `xboxbvhbuilder.dll` loads.
  `console_list.rs:12` is "compute only, `XCL_CONSOLE_LISTS=1`"; slots #146/#148
  at `real.rs:1040-1042`; extra-argument `CreateComputePipelineState` at
  `real.rs:891`; tests `console_dlls_e2e.rs:616,728` make the real DLL build
  BLAS/TLAS on the GPU. `gpu/bvh.rs` + `dxil/lower_image.rs` cover the nodes and
  `image_bvh(64)_intersect_ray`; `gpu::bvh::build` is test-only.
- **The title's builder has never run in these logs:** `report.json`
  `called_stubs` has no #146/#148 (its AllocateUploadMemory is required per
  build), and `XCL_CONSOLE_LISTS` was unset. With it set, `device_x.rs:91-120`
  gives every console list the console shape, while `console_list` has no draw
  records, so the first graphics record is "unknown record ... rest skipped".
  Not a title-safe switch; no XCL analogue of Victory's skipped resolve passes.
## 3. 8 GB recommendation
Keep this and change nothing else for RT:
```
raytracing = "off"      # xcl.toml; XCL_RAYTRACING=off for clarity
# XCL_CONSOLE_LISTS unset
```
Reasons: Victory's builder costs ~40 ms/frame and is still incomplete on a
12 GB 5070; the XCL 8 GB run reached 24.3 GB commit / 11.1 GB sparse and died
`E_OUTOFMEMORY`; Victory's notes put raw-address copies at 1-4 GiB with a
per-dispatch refresh while the builder is on; LNX's native BVH crashes ~1 min
later; no XCL title-builder run exists. `auto` vs `tier1_1` makes no difference
here; `off` is the only value that could make a querying title decline RT.
If white/hazy rooms persist with RT off, the Victory-proven fix is to skip the
programs that shade missed rays, not to enable RT. XCL needs a hash-addressed
skip (e.g. `XCL_SKIP_SHADERS=<hash,...>` at pipeline creation or bind) and an
ambient stand-in; hashes must come from a run (`XCL_PSO_TRACE=1` / `[SHADER]`,
mapped offline with `xcl shaders`). No patch is recommended for the 8 GB
setting; a builder experiment needs console-list draw support and a VRAM
budget, not a small diff.

## 4. Verification
- `grep -F "CheckFeatureSupport(D3D12_OPTIONS5)" xcl.log`: absent means the
  switch is inert; present gives `RaytracingTier N (host M)`.
- `D3D12.X: console code so far:` (`bind.rs:62`) every 2 s: draws/dispatches.
  Builder traffic adds dispatches (52 programs, ~10 per BLAS build) and should
  show #146/#148 in `report.json` `called_stubs`.
- `XCL_CONSOLE_LISTS_LOG=1`: `console list: N dispatches, M skipped ...`;
  `skipped (PSO without a translation)` or `unknown record` exposes gaps.
- `XCL_ACTIVITY=1`: 2 s presents/draws/dispatches; compare before/after.
- `XCL_FRAME_DUMP=60`: `present: frame N ... L of 518400 samples not black`
  (`present.rs:1510`); compare mean and white-clipped fraction of the BMPs.
  `XCL_FRAME_DUMP_FULL=1` for one full frame.
- `XCL_PSO_TRACE=1` and `[SHADER]` hashes; map names offline with `xcl shaders`.
