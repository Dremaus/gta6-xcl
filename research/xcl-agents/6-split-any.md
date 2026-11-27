# XCL split-any: opt-in dispatch chains for multi-wave compute programs

Worktree `D:\git\xcl-wt-split`, branch `agent/split`, commit **aa1b8693** (parent `b75c0f30`).
opencode / DeepSeek V4.1 Flash 1017. No PR (repo rule for this model); local branch only.

## Why the 64-thread programs were built whole (confirmed)

- `gpu/dxil/kernel.rs:480` made the piece limit 0 unless `!split || split_tid.is_some()`.
- The old gate on `main` (`kernel.rs:629` there) was `limit > 0 && hw == 32 &&
  (numthreads == [32,1,1] || split_tid.is_some())`.
- `split_tid` exists only for the wave64-on-wave32 form with exactly `[64,1,1]` and no LDS
  (`kernel.rs:262`). So nothing chained for `[64,2,1]`, `[128,1,1]`, any 2-D/3-D group, a
  64x1x1 program with LDS, or any compute program on a native-wave64 GPU (`hw == 64`); those
  whole PSOs cost the driver ~16 s at 0.9-1.2 MB DXIL in the measured run.

## Soundness verdict

Splitting by the **thread index in the group** is sound on the accepted subset:

- A chain dispatches every group once per piece, in order, with a UAV barrier between
  pieces. Only per-thread SSA values and global memory cross. Groupshared is per-dispatch,
  so the cut analysis refuses every `Op::Load/Store` that is not the split wave64 inter-half
  exchange, plus allocas/atomics (`module/split.rs:136-155`).
- `split_compute` takes the `tid` Value and replays the entry block through it in every
  piece (`module/split.rs:108-133`), so each dispatch recomputes the same logical
  thread -> slot map. Scratch is `stride * product(numthreads)` words per group, indexed by
  tid (`:119,183-187`, `Scratch::new`): one distinct slot per thread for any numthreads.
  (The old `threads[0]` slot count was only correct for single-wave groups.)
- Identity is unique and dispatch-stable: `flattenedThreadIdInGroup` for 1-D groups; the
  translator's own `xcl_wt`, or `xcl_xw`/`xcl_xs`/`xcl_xc`, counters otherwise (chunks of 32
  or 64 threads = one hardware wave). The replay prefix also swallows the lane setup's
  trailing `GROUP_SYNC` (`:120-133`), which is group-convergent.
- Pieces finish at the whole's wave size (`SplitTarget.wave`, `:190-206,305`), so native
  wave64 keeps 64-lane semantics.
- Opt-in only: a piece drops `WaveOps`/`TiledResources` when its blocks no longer contain
  the call that justified the whole's flag (`:316-330`). DXC 1.9.2602.17 rejects a stale
  flag ("Flags must match usage", declared=524304 actual=16 in the first test). This code is
  not reached on the kept path, so its bytes stay unchanged.

Still refused, deliberately, leaving the program whole as today: LDS-using programs,
alloca/atomic programs, barriers outside the halves exchange, and one SCC over
`4 * XCL_DIRECT_SPLIT_INSTRUCTIONS`. **If the measured 1.2 MB giants use LDS, this opt-in
still leaves them whole**: group-shared state cannot cross a dispatch without a
snapshot/restore design. The driver-blob cache and huge-PSO gate remain the fallbacks.

## Patch (3 files, +262/-37)

- `gpu/dxil/kernel.rs`: `XCL_DIRECT_SPLIT_ANY=1`, `XCL_DIRECT_SPLIT_ANY_BYTES` (262144)
  (`:56-72`); `SplitPolicy` (`:96`) with the old gate kept exactly as `kept` (`:660-663`)
  and `any` for every compute entry with a tid (`:666`); the chain is kept only when the
  whole DXIL reaches the threshold (`:683-686`); `any_tid` captured per compute entry
  (`:248,262`).
- `gpu/dxil/module/split.rs`: `SplitTarget { tid, halves, wave, infer_flags }` (`:93`);
  tid-keyed `split_compute` with an allow-list of `xcl_wt` (native multi-wave) and
  `xcl_xw|xs|xc` (halves) (`:108-117`); slot count `product(numthreads)` (`:119,185-188`);
  prefix replay (`:120-133`); target wave size (`:305`); gated flag re-derivation
  (`:316-330`).
- `gpu/recomp/pso.rs:273-278,521-525`: `dispatch-split-any-<bytes>` cache tag in both
  identities; unset means no tag, so default cache entries and bytes are unchanged.

## Tests (6 pure tests, all run)

`cargo check -p xcl --lib --tests` -> `Finished dev` (warnings pre-existing).
Each `cargo test -p xcl --lib <filter>` -> `1 passed; 0 failed; 1358 filtered out`.

- `split_any_chains_multi_wave_groups_by_thread_id`: [64,1,1] and [64,2,1] native wave32,
  limit 16, threshold 1 -> chain Some, `pieces >= 2`, `dwords_per_group % total == 0`, whole
  and every piece validated by DXC; default policy -> chain None for both.
- `split_any_chains_a_native_wave64_program`: [64,1,1] native wave64 (`hw = 64`) -> chain
  Some, every piece finished at wave size 64 and validated by DXC. This was the AMD case.
- `split_any_keeps_a_small_program_whole`: one-round fixture, limit 64 -> None.
- `split_any_keeps_the_whole_under_the_byte_threshold`: `any_bytes = usize::MAX` -> None.
- `oversized_loop_occupies_one_piece_up_to_the_hard_ceiling` and
  `slabs_cover_a_dispatch_once_within_their_size`: unchanged, pass.
- `split_any_chain_matches_the_whole_multi_wave_groups` (GPU: whole vs
  `dispatch_split_by(..., most=1)`, [64,1,1] and [64,2,1]) is in the tree but was **not run
  to completion here**: this session was told not to touch the GPU. Run it on hardware
  before trusting multi-wave results.

## Verification for the title run

Under `D:\git\.xcl-build.lock`:
`cargo check -p xcl --lib --tests`
`cargo test -p xcl --lib split_any_chains_multi_wave_groups_by_thread_id`
(`test result: ok. 1 passed; 0 failed`)

Run with `XCL_DIRECT_DXIL=1 XCL_DIRECT_SPLIT_ANY=1` (optionally
`XCL_DIRECT_SPLIT_ANY_BYTES=262144`, `XCL_PSO_TRACE=1`). At exit `host.rs` prints
`dispatch_chain::log_counts` (`real/dispatch_chain.rs:19`):

`compute split: N programs split, M pieces built, D chained dispatches issued in S slabs; scratch X MiB (most Y, largest dispatch Z in one slab)`

Expected on the world load: `N`/`M`/`D` non-zero for the previously whole 64-thread
programs, and per-piece `driver compile start/finish` lines instead of one 0.9-1.2 MB whole.
Refusals log `compute split: piece i of n refused, the program stays whole: ...` and fall
back exactly as before.
