# 8 — RT/BVH builder: Victory-NVIDIA evidence, XCL state, 8 GB call

**Verdict:** keep RT/BVH **off** on the 8 GB RTX 4060. `XCL_RAYTRACING` is not a
title-side RT switch in XCL: it only edits `CheckFeatureSupport(D3D12_OPTIONS5)`,
and both available title logs show the title never calls it. The builder is not
running either. Victory-NVIDIA's current default is also RT off; their builder
is an option because it is slow and still incomplete.

Checked `D:\git\xcl` at `b75c0f30` and worktree `D:\git\xcl-wt-rt` (same tree; no code change).

## 1. What Victory-NVIDIA changed (GPL-3.0 clone, ideas only)

- **Diagnosis (77e13a9, 2026-11-25):** the builder could not run on NVIDIA, so
  every ray missed and rooms went white depending on view angle. They skipped
  the 1,000 `CS_RaytracingResolve` + 34 traced-shadow programs through
  `VICTORY_SKIP_PIPELINES` / `scripts/rt_off_hashes.txt`, kept the screen-probe
  and visibility traces (skipping those left rainbow glitter), and added
  `VICTORY_AMBIENT_MOST`. This is the actual white-room fix: do not shade rays
  that have no structures.
- **Builder translation/fixes (6a2d9f9, 24a479d, 30f46c9, 2c20d7a, adf5706,
  b558934, 810efe5, 96bfd0e):** 59/64 trace programs and irradiance shading
  translate; builder programs are recognised by their spilled user-data table
  (`spill.rs`); `image_bvh(64)_intersect_ray` is emulated (`bvh.rs`,
  `emit/lower.rs`); title memory is read by raw address (`memory.rs`); root
  UAVs, byte/16-bit accesses, fences, bounded stores, size waits.
  `VICTORY_BVH_MISS=1` makes stale nodes miss instead of walking garbage.
- **All-or-none rule (`victory-gpu/src/pipeline.rs:239-360`):** every builder
  pipeline the title has created must have a host pipeline before any builder
  stage runs; the first builder dispatch creates them all. A partly translated
  builder wrote garbage bounds into title memory and killed the title (run 98).
- **Real RT as an option (6395727, 2026-11-26):** `-RayTracing` /
  `VICTORY_BVH_BUILDER=1`; the builder runs on NVIDIA on CGBJ's renderer.
  Measured on RTX 5070, Series S, DLSS: 15-17 fps without, 13-15 with; with
  frame generation about 0.1 fps. The menu labels it "RAY TRACING (SLOW,
  BROKEN)" (`host/menu.rs:76`). Dropped builder dispatches fell from ~6,640 per
  frame (`ab-d2baseline`, builder off) to about one when the builder ran.
- **NVIDIA descriptor slots are a separate issue:** a9632bc: NVIDIA caps the
  view heap at 1,000,000 vs the title's 1,245,184; the 2^18 dynamic pool refused
  1,100-4,800 tables per frame. `VICTORY_DYNAMIC_SLOTS=524288` -> 0-33 refused;
  47747d6 fixed cross-heap slot release. These are dropped graphics draws, not
  builder dispatches.
- **Current state (`README.md:207`, `docs/fork-ray-tracing.md`):** no RT by
  default. Builder on costs ~40 ms/frame extra; dynamic structures overlap
  (8 of 65 good in one run), ~90 missing pages/frame, 5 shadow programs do not
  translate. The ambient estimate is the default.

## 2. XCL today

- `config.rs:53-56,253-266`: `raytracing = "auto" | "off" | "tier1_0" |
  "tier1_1"`, `XCL_RAYTRACING` overrides `xcl.toml`. `real.rs:3031-3045` applies
  it to OPTIONS5 and logs the first call; `null.rs:417-420` does the same on the
  null backend. No other consumer exists in the tree.
- On an RTX 4060 (DXR 1.1): `auto` -> 11, `tier1_1` -> 11, `tier1_0` -> 10,
  `off` -> 0. That number is the only difference; XCL's own path never changes.
- Observed: `xcl.toml` has `raytracing = "off"`; `xcl.log` (17:08) and
  `xcl.prev.log` contain no `CheckFeatureSupport(D3D12_OPTIONS5)` line. The
  title never queried it, so all four values are equivalent for this title in
  these runs. (The `.bak` used `auto`/anaconda; these logs are lockhart/off.)
- **Builder support is real but opt-in:** `xboxbvhbuilder.dll` loads.
  `console_list.rs:12` is "compute only, `XCL_CONSOLE_LISTS=1`"; slots #146/#148
  at `real.rs:1040-1042`; extra-argument `CreateComputePipelineState` at
  `real.rs:891`; tests `console_dlls_e2e.rs:616,728` make the real DLL build
  BLAS/TLAS on the GPU. `gpu/bvh.rs` and `dxil/lower_image.rs` cover the nodes
  and `image_bvh(64)_intersect_ray`; `gpu::bvh::build` is test-only.
- **But the title's builder has never run in the available logs:** `report.json`
  `called_stubs` has no #146/#148, and there are no console-list lines.
  `XCL_CONSOLE_LISTS` was unset. With it set, `device_x.rs:91-120` gives every
  console list the console shape, while `console_list` has no draw records — the
  first graphics record would be "unknown record ... rest skipped". It is not a
  title-safe switch, and XCL has no analogue of Victory's skipped resolve passes.

## 3. 8 GB recommendation

Keep this, and change nothing else for RT:

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
  (`present.rs:1510`); compare mean and white-clipped fraction of the BMPs to
  catch white-outs. `XCL_FRAME_DUMP_FULL=1` for one full frame.
- `XCL_PSO_TRACE=1` and `[SHADER]` hashes; map names offline with `xcl shaders`
  (no game launch). Also count `report.json` translation errors.
