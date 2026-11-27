# 16 — Park: three hypotheses killed by experiments; the budget-accounting deadlock remains

Runs on XCL main `7318cf60`, device lockhart, 600 s, key-cycling harness.
Every run renders a REAL scene before the park (frame dump non_dark ~99.9 %).

## Experiment ledger (all decisive, all falsifiable)

| # | hypothesis | test | result | verdict |
|---|---|---|---|---|
| 1 | auth gate (CreateTicketXbl3 offline) | `xbox_live_tokens=true` (run 205725) | park EARLIER (~136 s), 5.2 fps avg | REJECTED |
| 2 | host-RAM view (GlobalMemoryStatusEx passthrough) | `XCL_HOST_MEMORY_MB=8192` (run 213248; install line confirmed in log t=0.001, constant avail=4096 MB / load 50 %) | park returns t≈158 s | REJECTED |
| 3 | network wait (thread 27396 blocked in real `recv()`) | `XCL_NETWORK=0` (run 214346) | park t≈156 s, run much WORSE (2055/600 s = 3.4 fps) | REJECTED |
| 4 | title-budget accounting gate | `title_memory_mb=28672` in xcl.toml (run started this session) | pending | — |

## The surviving mechanism (code + dump evidence)

`crates/xcl/src/hle/kernelx.rs`:
- `:599-608` `XMemAlloc/XMemFree` route to the TITLE's own hooks; `:613-629` `adopt_title_hooks`
  reads the exe export `__XMemAllocationHooks__` (log: "XMem: the title has allocation hooks
  (game+0x4deb420, game+0x4e38ec0)"). `:642-656` `runtime_alloc` calls the title hook for console-runtime memory.
- `:831-844` `process_private_bytes()` = private bytes of the WHOLE HOST PROCESS (XCL itself included).
- `:846-864` `TitleMemoryStatus`: `total = title_memory_budget_mb`, `used = min(private_bytes, total)`,
  `avail = total - used`. `:776-785` `XMemGetWorkingSetStatistics` uses the same limit.
- With budget 8192 MB on this machine, host private/commit was 12.8 GB at t≈6 s (report 15) →
  **avail = 0 from early boot**. Config source: `config.rs:117-123` (`title_memory_mb`, 0 = device default).

Dump evidence (report 15, run 203520): 39/45 title threads wait on ONE event
(`KERNELBASE+0x1427f = WaitForSingleObjectEx`, resolved via PE export parsing); the render thread
parks at `game+0x23cf735`, the second waiter at `game+0x23cf4f2` — the same function family as the
HISTORICAL fatal OOM asserts `game+0x23cf683/+0x23cf729` seen in crashed runs before the lazy-page and
UMA fixes. Same family = same title-side handler: it used to FATAL, now it WAITS.

Coherent story: the title's RAGE allocator sizes itself from TitleMemoryStatus. avail=0 does not stop
the game loop (60 fps for ~150 s) but the first *blocking* allocation on world entry parks the
allocator on its "memory freed" event — and freeing can never help, because `used` counts XCL's own
host footprint, which the title cannot release. Park onset correlates with local VRAM crossing the
8 GB card (8355→9891 MB at t=150–196, report 15 §B) = exactly when new mandatory allocations happen.

Why the old assert and the new park differ: before the memory-wall fixes, `used` was even larger and
allocation attempts hit the fatal path; today the same handler chooses its wait branch.

## If experiment 4 confirms (run 213xxx/next)

- Park shifts/dissolves while presents continue past t=210 s → gate input is proven to be
  `total - process_private_bytes`.
- Correct fix is NOT a 32 GB budget (titles size pools from `total`): implement honest
  title-side accounting — count bytes handed to the title through XCL HLE alloc paths
  (`XMemAllocDefault` `:560`, `XMemVirtualAlloc` `:661`, physical-page paths `:1497-1532`),
  subtract on the matching frees, and report THAT as `used`. Keep `total = 8192`.
- Fallback (worse): floor the reported avail at a small constant when private bytes are dominated
  by XCL-internal use; risks the title believing headroom it can't get at the host level.

## Next-run note

xcl.toml currently carries `title_memory_mb = 28672` for the experiment — MUST be restored to 8192
(or removed → device default) once the verdict is recorded, before any tuning run.
