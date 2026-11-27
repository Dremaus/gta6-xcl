# 1 - Host commit: where the 24 GB is, and what to cut

Branch `agent/mem` in `D:\git\xcl-wt-mem` (baseline commit `5512f920` = 8b957bec + the local
fork patches: memcap, uma/dxc real-machine reads, XCL_SKIP_PREPARATION).
Evidence: `C:\Users\witek\AppData\Local\XCL\RockstarGamesInc.28872443D20A7\logs\xcl.log`
(run 2026-11-27 12:45, `XCL_ACTIVITY=1`, `XCL_SKIP_PREPARATION=1`).

## 1. What the `memory:` line counts (`crates/xcl/src/host.rs:69-92`)

`PrivateUsage` of the process (host commit), then `QueryVideoMemoryInfo` LOCAL/NON_LOCAL usage,
then XCL's own counters. The run's numbers at the crash:

```
t=171.98  memory: 24314 MB committed; video 13655 MB local, 1233 MB non-local;
          target pages 7454 MB (pools 7616); arenas 245 in use/309 made;
          sparse pools 4736 MB (3164 mapped)      <- this is the last `memory:` line
t=169.785 D3D12.X: no video memory for more pages of title textures (0x8007000E)  x12
t=169.876 unhandled exception 0x80000003 at game+0x193e00f, rax=0x8007000E (E_OUTOFMEMORY)
          breakpad: memory.load_percent=98, system.memory.free=194 MB, swap.free=330 MB
```

**GPU bytes are host commit bytes.** WDDM charges the process commit for every D3D12
allocation, and the run shows it 1:1: t=2 -> t=14 commit +9082 MB while sparse pools +4224 MB
and LOCAL +4419 MB (sum 8643). That is why a `CreateHeap` of a 64 MiB DEFAULT heap fails with
E_OUTOFMEMORY while an 8 GB card already "holds" 13.6 GB: the binding limit is commit, not VRAM.
Accounting: 24314 = 14888 (all GPU) + 9426 (title's own heap + XCL). The title's host-side
heap grew ~6.5 GB during the load; XCL's own baseline is ~3 GB at t=2 (`memory: 3584 MB`,
`video 615 MB`).

## 2. Process-private commit vs VRAM by allocation path

| path | file:line | lands in |
|---|---|---|
| 64 KiB page (MEM_64K_PAGES) reservation | `kernelx.rs:270-280` | sparse **VA only** (no commit, no VRAM) |
| commit inside that reservation / a sparse window | `kernelx.rs:261-265` -> `commit_sparse` `kernelx.rs:246-252` | `MEM_COMMIT` **host** + `sparse::committed` -> one 64 KiB **VRAM** tile (`sparse.rs:1326`) |
| MEM_GRAPHICS commit (`XMemAlloc` graphics, `XMemVirtualAlloc`) | `kernelx.rs:281-298`, `560-581`; `sparse.rs:1197-1209` | host commit + VRAM tile, in sparse window 0..2 |
| MEM_GRAPHICS reserve (no commit) | `kernelx.rs:299-325` | sparse VA only (write-watched) |
| GPU heaps with `PAGE_GRAPHICS_*` (CPU writes, GPU reads) | `kernelx.rs:331-346` | coherent UMA window: `MEM_RESERVE|MEM_COMMIT` at `uma.rs:271` -> host commit; imported as a D3D12 heap (`real.rs:301-326`) |
| GPU-visible memory the windows had no room for | `kernelx.rs:353-360` -> `reserve_watched` `kernelx.rs:376-383` | plain host commit (write-watched) |
| everything else | `kernelx.rs:361` | plain host commit |
| tiled title textures (sampled / RT / DS / UAV) | `vram.rs:1289-1308` `place_pages`, `vram.rs:946-1032` `place_on_pages` | **VRAM pages** in 64 MiB pools: `vram.rs:510-525`, 1024 x 64 KiB (`vram.rs:173-175`); counted as host commit by WDDM |
| arenas (untileable: D32S8, MSAA) | `vram.rs:149-170` | DEFAULT heaps, same commit cost |
| XCL arena pool (`Arena::take`) | `uma.rs:121-122`, `196-224` | 64 MiB of the coherent window, zeroed up front |

Windows/layout: `MAX_RUNTIME_SPARSE_WINDOWS=3` (`uma.rs:35-39`) = 12 GiB sparse VA, reserve-only;
the measured run used 11131 MB of it. Coherent window: `coherent_window_sizes` `uma.rs:57-71`,
`coherent_hint_for` `uma.rs:786-805`, floor `RUNTIME_COMMITTED_CAP=512 MiB` (`uma.rs:98`); this
run got 512 MB because free commit 17346 MB < `NEEDS_FOR_COHERENT_HEAPS` 17 GiB (`uma.rs:813`).

## 3. Where commit is redundant, by MB saved / risk

1. **Pages for mip levels that hold nothing: ~4.6-6.8 GB (top pick).**
   `place_pages` gives every tile of a sampled texture a page at placement. The same title was
   measured in commit `3ea5edc1`: at world setup **80 690 pages, 6 809 with texels** = ~92 %
   of ~5 GiB had nothing behind them. The lazy path already exists (`vram.rs:998-1016`,
   `map_levels` `vram.rs:1315-1356`, driven by `title_textures.rs:1171-1178`, which skips
   all-zero levels and documents that an unmapped tile "reads as zeros as it would with them").
   It was just off by default (`XCL_TEXTURE_LEVEL_PAGES=1` required).
2. **Unmapped-but-retained sparse pool tiles: up to 1572 MB.** `sparse pools 4736 (3164
   mapped)`. Pools are 64 MiB (`sparse.rs:35-36`) and only retire when *every* tile is free
   (`sparse.rs:657-681`), so free tiles scatter: 74 pools for 49 441 used tiles. Reclaiming it
   means moving live tile mappings between heaps (remap + fences); high risk, do later.
3. **Page-pool slack: ~162 MB** (`pools 7616` for `7454` used) + 64 MiB spare
   (`keep_spare_pools()`=1, `vram.rs:572-580`). Not worth a patch.
4. **Coherent window: ~200 MB** of its 512 MB unused (`coherent 311/512`). It is the only
   CPU-writable GPU memory draw arguments use; shrinking it risks the per-draw path.
5. **Nothing is "kept after use"**: `forget_pages`/`sweep_idle` (`vram.rs:206-225`) and
   `retire_free_pools` free on release/idle; the residue is fragmentation, not leaks.

Not a commit cut, but it explains the death: `XMemGetWorkingSetStatistics` (`kernelx.rs:776-785`)
and `TitleMemoryStatus` (`kernelx.rs:846-864`) report the **whole process commit** as the
title's usage, capped at 8192 MB - so from t~14 s the title sees used==total, avail 0, and its
breakpad report says `memory.load_percent=98`. Do **not** "fix" this by reporting less without a
run: a lower number tells the engine it has room to stream more. (It is XCL's ~3 GB plus all GPU
bytes that inflate it; the title's own bytes are ~9.4 GB.)

## 4. Patches implemented (branch `agent/mem`, `cargo check -p xcl --tests` clean)

**P1 - level pages by default** (`vram.rs`, `level_pages()`): 92 % of the pages in the measured
scenario hold nothing, so allocate a level's pages with its first texels instead of at placement.
Expected: `target pages` 7454 MB -> ~600-1500 MB, commit 24314 -> **~18-19 GB**; pools follow.
Risk: a GPU-side copy into a sampled (non-UAV/RTV/DSV) texture that does not go through
`title_textures` would land in unmapped tiles and be dropped. Escape hatch, no rebuild:
`XCL_TEXTURE_LEVEL_PAGES=0` restores the old behaviour. Tests keep the eager default
(`cfg!(test)`) so existing assertions stand.

```diff
-        let on = std::env::var("XCL_TEXTURE_LEVEL_PAGES").is_ok_and(|v| v.trim() == "1");
+        // (a test binary keeps the eager path: its tests assert the pages of every level; the
+        // lazy ones set `LEVEL_PAGES_FOR_TEST`)
+        let on = std::env::var("XCL_TEXTURE_LEVEL_PAGES").map_or(!cfg!(test), |v| v.trim() != "0");
```

**P2 - reclaim before a page placement fails** (`vram.rs`, `Pages::bind_range`): the run failed
in a burst of 12 `CreateHeap`s while idle pages (kept 2 s for a returning target, `IDLE`
`vram.rs:176-181`) and cooled tiles (`COOL`) were still held. On the first failure, force the
idle sweep and the cooling drain (only there - the forced reuse may catch a tile still in
flight), then retry once and log the shortfall instead of silently returning E_OUTOFMEMORY.
Expected: 0.1-0.8 GB at the moment of pressure, and a diagnosable log line instead of a title
crash. Risk: a transient artifact in the frame that hit exhaustion, never in normal operation.

```diff
+        let mut fresh = self.take_batch_for(dev, missing, preferred, now);
+        if fresh.is_none() {
+            let forced = now + IDLE + COOL;
+            let idle = self.idle.len();
+            self.sweep(forced);
+            self.pool.drain_cooling(forced + COOL);
+            let gave_up = idle.saturating_sub(self.idle.len());
+            crate::xlog_warn!("D3D12.X: no video memory for {missing} more 64 KiB page(s) of
+                title textures - gave up {gave_up} idle page(s) and the cooled tiles, retrying");
+            fresh = self.take_batch_for(dev, missing, preferred, forced);
+            ...
+        }
+        let fresh = fresh?;
```
(plus the `take_batch_for` helper; the full diff is commit 2 of the branch.)

## 5. Verification (orchestrator)

```
XCL_ACTIVITY=1            # same run as before
```
- `memory:` line: expect `target pages` ~0.6-1.5 GB (was 7454), commit ~18 GB (was 24314),
  `sparse pools` unchanged (~4.7 GB), no `no video memory for more pages` WARN.
- New log line: `D3D12.X: a sampled texture's levels get their video memory pages when an
  upload first has texels for them`, and `level pages: N textures standing for X MB have pages
  for Y MB` every 1024 levels.
- A/B in one run without rebuilding: `XCL_TEXTURE_LEVEL_PAGES=0` (old: 7454 MB) vs unset (new).
- If a visual gap appears on a texture, check whether its levels arrive by a GPU copy (not a
  CPU upload); the fallback is to scope lazy levels to textures whose first upload is a
  `title_textures` upload.

## 6. Next steps (in order)

1. If pages fall as expected but commit is still too high, the remaining big blocks are the
   title's own ~9.4 GB host heap (that is what `XCL_HOST_MEMORY_MB` caps - it was **not** set in
   this run: no `XCL_HOST_MEMORY_MB=` line) and sparse pools 4.7 GB.
2. Sparse-pool compaction (1.5 GB): move the live tiles of a mostly-free pool into another and
   release the heap - needs a reverse tile -> resources index and a fence, so a separate change.
3. `memory.load_percent`/`TitleMemoryStatus`: make the title-owned figure exclude XCL's own
   allocations (not all GPU bytes), only after confirming from a run that the engine gates
   streaming on it; otherwise it can raise memory use.