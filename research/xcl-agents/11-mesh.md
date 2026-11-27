# 11 — World mesh pipelines: two-pass execution integration

Date: 2026-11-27. Repo: `D:\git\xcl` (GPL-2.0-only). Base `main` = `7f1a617b` (#2052 fence fix, `XCL_DIRECT_SPLIT_ANY`, lazy level pages, PSO admission; dedup reverted — all preserved).
Integration branch: `agent/mesh` in worktree `D:\git\xcl-wt-mesh`, HEAD `46fbe753` (14 commits over `7f1a617b`). No game launch, no title data.

## 1. PR #541 — fetch and diff (`pr-541` = `6bd8f641`, 7 commits, merge-base `a1672ef`)

Changes, against main:
- `gpu/recomp/emit.rs`: `passthrough_max_vertices` (DXC accounts 32-vertex chunks; 32768 B budget); the mesh pass-through declaration is chosen by vertex budget, separately from the dispatch group count (`mv <= cap`, not `split == 1`); `passthrough_split` uses the same cap.
- `gpu/recomp/tests.rs`: 3 tests for that budget (already on main via #304, see below).
- `hle/d3d12x/real.rs`:
  - deletes the AS-slot refusal and adds `mesh_shader_slots(ms_slot, as_slot)`: a console MS container alone in AS becomes the MS, AS is cleared; any real AS, an existing MS, or a PC shader in AS is left untouched;
  - defers a moved MS in the cached-only attempt (`pso_async::lazy() && dxc::defer()`), so `go_background` gives the title a stand-in and the worker/first bind translates;
  - `fallback_stream` retypes the AS subobject to MS with the dummy mesh shader and uses the dummy-mesh PS (`console_ms_in_as_slot`), so the stand-in is a valid mesh pipeline instead of PS-only;
  - stand-in `RENDER_TARGET_FORMATS` / `DEPTH_STENCIL_FORMAT` go through `device_x::pc_target_format` (e.g. 118→45, 115→28).
- Layout it assumes: a console MS container (stage `MS` from the DXIL program header) sits in the AS subobject, no MS subobject, PS in the PS slot, graphics state (blend/sample mask/rasterizer/depth/RTV formats) present; VS slot empty; DS/HS/GS slots may be present but empty. Retail world/minimap streams match this.
- Vendor specificity: none in the rule itself. The lazy-defer rationale is performance observed on NVIDIA (seconds) and AMD wave64 (past a minute), and the stand-in/format fixes are driver-generic.

## 2. PR #2092 — fetch and diff (`pr-2092` = `e856fa7d`, 9 commits, merge-base `06c9f55`)

- Core `4aaaf467` (rebased #724): hooks console list slot #127 `DispatchMesh` (newer layout #129→#127); `list_device`; `TwoPassPso` execution:
  - direct path: allocate a record buffer, bind the translated MS **compute** stage (`Dispatch n`), UAV barrier, bind the title's mesh PSO (`n * mesh_groups_per_record`, all X), call PC `DispatchMesh`;
  - indirect path: on an `ExecuteIndirect` whose command signature contains `DispatchMesh`, duplicate the signature with `DISPATCH` as a companion (device_x), rewrite arguments for both passes with `SCALE_ARGS_HLSL`, run one command at a time (compute then mesh, UAV barrier between), cap groups; count buffer honored.
- `console_list.rs`: MS root arguments start at user SGPR `s16`, 16 inline SGPRs (`user_data_ms`), allocator release for two-pass buffers.
- `runner.rs`: every memory window u2..u5 bound to `mem` (main already has this plus dispatch-chain slabs; conflict resolved to main).
- Assumes: title calls `DispatchMesh` at #127/#129; the two-pass compute writes one record per group and the mesh pass preserves the title's PS; graphics root args are in `bind`'s `layout_gfx/args_gfx`; indirect args/count live in a console buffer in unified memory; 32 MiB record buffer per list is enough (cap 128 MiB, groups beyond cap dropped loudly).
- Vendor specificity: generic. It originated on RTX 3090/5090; the NVIDIA 5090 “ExecuteIndirect fetches args without waiting” workaround is main's existing `fresh_indirect_arguments`, not part of this PR. Heap-window binding is generic.
- Known upstream gap (not fixed by #2092): the compute pass does not receive descriptor-heap base addresses (`s23/s24`, #1803), so records can be `(1,1)` and targets stay empty; GPU-view memory #697 is also needed for real geometry. Execution is the contribution here.

## 3. Ported to `agent/mesh`

- Skipped #541's three recompiler commits: main already contains the same `passthrough_max_vertices` and layout/count split (main's comments cite the 96-case bisect; tests `mesh_split_accounts_vertex_chunks`, `mesh_layout_independent_of_group_count`).
- Cherry-picked #541's four `real.rs` commits (`6fd32455`, `db29fbab`, `38af06d1`, `8ba13ee3`) and all nine #2092 commits (`9c66401b`, `3a27cbc0`, `89f18279`, `fa8e3cbf`, `47e8da75`, `4a3cfa66`, `4fed68c5`, `55dfe230`, `1e8e201c`).
- Conflict resolutions kept main's newer work: lazy MS still `return None` (not the PR's `E_INVALIDARG`), main's fallback blend/formats path, main's `execute_indirect` build-defer, main's runner u2..u5.
- Added `46fbe753`: moved-MS log once per unique MS hash (bounded 4096) plus a count at powers of two; refuse a real VS beside the MS with both hashes; every two-pass skip warns with pso/groups/sig (no silent drop); unit test `a_vertex_shader_beside_an_ms_is_still_rejected`.
- Nothing from #541/#2092 remains unported. Remaining work is measurement and the known #2092 inputs gap, not missing dispatch code.

## 4. Correctness

- Console MS goes through `console_mesh(ms, ps, wave32_only(this))` → `console_mesh_with` → `fssm_wave64`; a wave64 program is split when the adapter is wave32-only or `XCL_SPLIT_WAVE64=1`, exactly the compute path. The compute pass is `cs_6_6`; the PS uses `graphics_wave32`.
- Acceptance: AS-slot MS accepted only when AS parses as stage `MS` and no MS subobject exists. Real VS + MS is refused (`E_INVALIDARG`) with `VS <hash> and MS <hash>`; AS beside MS is refused with both hashes and subobject list; `note_translation_error` dedups by full reason (hash included), cap 40.
- Draws/dispatches on a two-pass PSO are never silently discarded: direct/indirect skips increment `DRAWS_SKIPPED` and warn (first 8) with pso, group/sig and reason; pending pipelines warn too.

## 5. Build and tests

Lock: `D:\git\.xcl-build.lock` acquired atomically with `New-Item`, held through build/tests, released.
- `cargo build --release -p xcl`: **pass** (1m05s, 3 pre-existing warnings).
- `cargo test --release -p xcl --lib mesh_slot_tests`: **5 passed** (`a_console_ms_in_the_as_slot_is_the_mesh_shader`, `a_vertex_shader_beside_an_ms_is_still_rejected`, `the_stand_in_of_a_moved_ms_is_a_mesh_pipeline`, `the_stand_in_of_a_stream_has_the_pcs_target_formats`, `a_moved_ms_defers_in_the_attempt_only`).
- `cargo test --release -p xcl --lib two_pass`: **18 passed**, 1 skipped (`two_pass_binds_set_the_shared_view_heap`: no heap windows). Includes GPU `gpu_mesh_mode_two_passes`, `gpu_two_pass_indirect_commands_keep_their_own_records`, group-cap/scratch tests.
- `cargo test --release -p xcl --lib mesh_arguments`: **1 passed** (`mesh_arguments_go_in_user_sgprs_from_s16`).
- `cargo test --release -p xcl --lib dispatch_mesh`: **2 passed** (signature tracking; newer-layout 129→127 mapping).

## 6. Run recipe and proof lines

```
cd D:\git\xcl-wt-mesh
cargo build --release -p xcl
$env:XCL_NETWORK='0'; $env:XCL_ACTIVITY='1'
$env:XCL_RUN_SECONDS='120'; $env:XCL_FRAME_DUMP='240'
$env:XCL_PRESS_AT='16:A,20:A,24:A'   # walk into the world; not run here
.\scripts\smoke.ps1 -Game <title folder> -Seconds 120 `
  -Xcl D:\git\xcl-wt-mesh\target\release\xcl.exe -StartupTimeoutSeconds 120
```
Expected success lines (source anchors in `D:\git\xcl-wt-mesh`):
- `D3D12.X: mesh pipeline with its MS <hash> in the AS slot - translated as MS (#n)` — `real.rs:6420`, from `translated_mesh_stream_once` (`real.rs:6371`); one per unique MS hash.
- `D3D12.X: pipeline from the console MS in two passes (compute <n> B + mesh <n> B DXIL)` — `real.rs:6195`, `finish_two_pass` after `TwoPassPso` registration (`real.rs:6192`).
- `D3D12.X: two-pass DispatchMesh #n (<groups> groups, split <k>, kind MS)` — `bind.rs:679`.
- `D3D12.X: two-pass ExecuteIndirect(DispatchMesh) #n (max <m>, split <k>, kind MS)` — `bind.rs:768`.
Failure lines to grep: `two-pass DispatchMesh ... skipped`, `two-pass ExecuteIndirect(DispatchMesh) ... skipped`, `draw with two-pass MS pipeline ... skipped`, `mesh pipeline with VS ... and MS ... - refused`.

## 7. Risks of each ported piece

- AS-slot acceptance: if a title ever puts a real amplification program in a container whose header says `MS`, it is moved and mis-translated. Mitigation: stage check, no MS subobject, unit tests; refusal log is gone, so verify world output.
- Lazy defer: first bind now pays translation; a title that expects the PSO ready in the creation call gets a stand-in (draws nothing until built). Boot wins, first-frame latency risk.
- Fallback retype: stand-in mesh pipeline is dummy MS/PS — correct shape, draws nothing. Without it the driver refused PS-only stand-ins (proven upstream).
- Direct DispatchMesh: only works if the title's call lands on #127/#129. Wrong slot = world still empty. Test pins the mapping only, not a retail call.
- Record buffer/caps: 32 MiB/list (cap 128 MiB), groups past cap dropped with a warning; large records can still drop geometry. Upstream saw up to 4.8 GB of record buffers; VRAM pressure can cause device removal.
- Indirect path: requires args/count in console/UMA and a `DispatchMesh` signature; otherwise skipped with a warning. `indirect_arg_bytes` table is untested for exotic signatures.
- MS user SGPRs (`s16`, 16 inline): based on retail root-layout decode; wrong for another title → garbage args, (1,1) records.
- Not passing `s23/s24` heap bases (#1803): known upstream cause of `(1,1)` records and empty G-buffer; this branch executes mesh draws but may only clear to grey. That is the acceptable first milestone, not visible geometry.
- Memory windows/`SCALE_ARGS_HLSL`: argument reads go through UMA windows; a title buffer outside one is skipped loudly, not corrupted.

## 8. Remaining

1. Title run with the recipe above; capture (a) the four proof lines, (b) `two-pass DispatchMesh` counts, (c) frame brightness and report.json `translated_pipelines/failed_pipelines`.
2. If records are `(1,1)`/targets empty, port #1803's heap-address pass (`with_heaps` in `two_pass_io`) and address #697 GPU-view readability; that is required for geometry, not for dispatch.
3. AMD wave64 run (split path) and a long run for VRAM/device-removal.
4. No code revert of #2052 / lazy pages / PSO admission; branch is based directly on `7f1a617b`.
