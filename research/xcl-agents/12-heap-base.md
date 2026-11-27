# 12 — Heap base registers for translated programs (#1803 port)

Date: 2026-11-27. Repo: `D:\git\xcl` (GPL-2.0-only). Base `main` = `cc2cf931` (#541 + #2092 + driver-blob cache).
Branch: `agent/heapbase` in worktree `D:\git\xcl-wt-heapbase`, commit `06bb97ac`. No game launch, no GPU use, no title data.

## 1. What #1803 changes (`pr-1803` = `cb007514`, one commit, merge-base `4178e888`)

Upstream title "shaders that index the heaps themselves get the heaps' addresses":
- **Convention**: NOT fixed s23/s24 slots. The 32-bit console addresses of the bound heaps are **appended to the user SGPR block after the inline arguments, view heap first** — a root signature's
  `CBV_SRV_UAV_HEAP_DIRECTLY_INDEXED` (0x400) / `SAMPLER_HEAP_DIRECTLY_INDEXED` (0x800) flags (RTS0 dword 5, byte offset 20) select which bases go. For the mesh layout (args from s16,
  `inline_ms`) with 7 inline dwords this *lands at* s23/s24 — matching the earlier observation.
- `console_list.rs`: `Layout.heaps: [bool; 2]` from the flags; pure `with_heaps(l, user_sgprs, sgprs, heaps)` appends bases (a compute shader with no registers left gets none).
- `bind.rs`: `State.heaps: [u32; 2]`, `set_heaps()` records them; `bind_abi` wraps both gfx and compute user-data paths; reset/clear_state zero them; `inherit_for_split` copies them.
- `list_x.rs`: `set_descriptor_heaps_x` feeds `bind::set_heaps` (null heaps → zeros).
- `console_heap.rs`: `base(obj) -> Option<(sampler, u32)>` = the heap's console shadow-slot address (always allocated, shared or not).
- Test: `heap_addresses_follow_the_arguments` (gfx/compute caps, order view→sampler).

## 2. Port to `agent/heapbase`

Cherry-pick `cb007514` had two conflicts (fork mesh work touched the same spots), resolved keeping both sides:
- `bind.rs` `reset()`: fork's scratch/res-buffer retirement kept; `s.heaps = [0; 2]` added.
- `console_list.rs`: `Layout` keeps fork `inline_ms` **and** PR `heaps`; `user_data_ms` kept next to new `with_heaps`.
Everything else (`set_heaps`, `bind_abi`, `inherit_for_split`, `base()`, `set_descriptor_heaps_x`, tests) auto-merged.

**Fork-specific completion (the actual blocker fix)**: #1803 only touches `bind_abi`, but the two-pass mesh
path builds its io block in `bind_two_pass_stage`/`two_pass_io` — bypassing `bind_abi` entirely. So the
translated mesh program (compute pass) still received zeros at s23/s24 → `(1,1)` records. Added:
- `two_pass_io(..., heaps)` wraps `user_data_ms` (MS pass) and `user_data_gfx` (mesh pass) in `with_heaps`;
- `bind_two_pass_stage` captures `s.heaps` from bind state (set by SetDescriptorHeaps, both direct
  DispatchMesh and the two-pass ExecuteIndirect paths use it);
- **once per unique MS hash** (bounded 4096, same SEEN pattern as `46fbe753`):
  `D3D12.X: two-pass MS <hash> gets heap bases view 0x…, sampler 0x… (directly indexed: view …, sampler …)`;
  `TwoPassPso` gained `ms_hash` = `fnv64` of the console MS blob;
- no draw/dispatch dropped: a set flag with no bound heap stays a logged zero (counters/skips unchanged).

## 3. Build and tests

Lock `D:\git\.xcl-build.lock` acquired atomically with New-Item, held through build + tests, released.
- `cargo build --release -p xcl`: **pass** (2m00s, 3 pre-existing warnings: two `fetch_update` deprecations, one vram dead-code).
- `cargo test --release -p xcl --lib heap`: **43 passed, 0 failed** – includes PR `heap_addresses_follow_the_arguments`,
  new `mesh_heap_bases_land_at_s23_and_s24`, new `two_pass_io_gets_the_heap_bases_after_the_arguments`,
  `two_pass_binds_set_the_shared_view_heap` (was skipped on `agent/mesh`, passes here), `gpu::xbox::mesh_stage_heaps_follow_the_arguments`.
- `cargo test --release -p xcl --lib two_pass`: **19 passed, 0 failed** (GPU-dependent ones self-skip).
- `cargo test --release -p xcl --lib mesh`: **42 passed**; `--lib dispatch`: **28 passed**.

New unit tests (pure):
- `mesh_heap_bases_land_at_s23_and_s24` (console_list): RTS0 blob with flags 0xC00 and 28 B inline →
  `user_data_ms` args s16..s22, view base at **s23**, sampler at **s24**; flags with zero heaps → zeros (logged case).
- `two_pass_io_gets_the_heap_bases_after_the_arguments` (bind): same through `two_pass_io` for the MS pass
  (s23/s24) and the gfx pass (after s8 args), no-flags → no bases, length stays `KERNEL_SGPRS`, `IO_UMA_BASE_HI` intact.
- `two_pass_io_carries_the_unified_memory_base` updated for the new signature.

## 4. Run recipe (orchestrator)

```
cd D:\git\xcl-wt-heapbase
cargo build --release -p xcl
$env:XCL_NETWORK='0'; $env:XCL_ACTIVITY='1'; $env:XCL_RUN_SECONDS='180'
$env:XCL_FRAME_DUMP='240'; $env:XCL_PRESS_AT='16:A,20:A,24:A'
# new run tag per run, e.g. xcl-lockhart-<HHMMSS>; driver DLL from target\release\xcl.dll
```
Log: `C:\Users\witek\AppData\Local\XCL\RockstarGamesInc.28872443D20A7\logs\xcl.log`.

## 5. Proof lines to grep (pass criteria)

1. Heap bases non-zero and bind reached: `Select-String xcl.log -Pattern 'two-pass MS .* gets heap bases'`
   — one line per unique MS hash, `view 0x6…` (window-0 console address), not `view 0x0`. If flags are
   true but bases are 0x0, the title bound its heaps without XCL seeing SetDescriptorHeaps (next bug).
2. Mesh still accepted + dispatched (regression vs xcl-lockhart-192243): `MS_accepted=` count ~167,
   `refused=0`, and `two-pass DispatchMesh #N` count strictly larger than the 15 of the 116 s run and
   growing with run time.
3. Records no longer `(1,1)` / geometry appears: frame-dump stats JSON `non_dark_samples > 0` on world
   frames (`frame_<n>.bmp` in the logs folder); presents survive past ~116 s.
4. Driver-compile stalls (separate known issue, unchanged): `>=10 s` driver compiles (max 34.8 s) remain
   on the critical path; the blob-cache fix only makes re-runs fast.

## 6. Residual risk

- If the title's directly-indexed mesh signature indexes the **sampler** heap in a different slot order
  than view-first, one log line per MS hash shows it (swap in `with_heaps` — single place).
- `layout_gfx` is used for the MS pass: a title whose mesh root signature differs from the bound gfx one
  would get the gfx flags; the per-MS-hash log exposes flags vs bases to catch this on the first run.
