# 10 - GPU-sided memory compares: Victory's win and XCL's real ceiling

Worktree `D:\git\xcl-wt-gpuwatch` (branch `agent/gpuwatch`, base `b75c0f30`); no game launch.
Evidence: this title's XCL log (run 2026-11-27, 8,192 submits by t=63.57 s), Victory clone
`D:\git\victory-nvidia` (GPL-3.0, ideas only), microbenchmarks of XCL's exact hash and
`GetWriteWatch` here (Win11 26200, 16 GB, RTX 4060 Laptop 8 GB).

## TL;DR

- Victory moved the **shader-write compare** to the card: a compute pass hashes each 64 KiB piece of
  a card-resident copy, compares it with the hash of the bytes last sent up, and fetches back only
  flagged pieces. README claims 11 -> ~22 fps (`README.md:110`).
- XCL's hot path is **not** that compare. It is `GetWriteWatch` (OS page-dirty scan) before every
  submit: **4.22 ms/submit**, ~4.3 submits/frame = **~18 ms/frame**. The 64 B chunk compare is
  29 us/submit; the upload 144 us/submit. GPU-ing those has a **0.75 ms/frame** ceiling.
- The look cannot move to the GPU: the data is in CPU memory and uploading it is the cost being avoided. The viable GPU compare is the **copy-back diff** (data already on the card), designed below; gate it on readback bytes, which XCL does not measure yet.
- The Victory-sized win is CPU-side: **fewer looks** (look elision) and **cheaper compares**
  (per-page texture hashes). `XCL_LOOK_SKIP`/`XCL_WATCH_HOT` exist only on branch `pr-2057`, not on
  main; porting them is same-repo GPL-2.0-only work.

## 1. What Victory moved, exactly

- **Where:** `crates/victory-gpu/src/host.rs:2137-2216` (`CARD_COMPARE`), dispatched by `card_pass`
  (`:2232-2245`) after a submission's lists (`card_before` `:4411-4670`, compare `:4647-4657`);
  results consumed by `card_back` (`:5158-5285`).
- **Buffers:** `hashes` = 16 B per 64 KiB piece (128-bit hash of card bytes as last sent up),
  `differs` = one dword per piece (bit 0 = differs), both UAVs. The old "before" twin (a second full
  card copy) became this hash table: 399 MB saved (run 75, `:4521-4526`).
- **Shader:** 64 threads per 64 KiB piece, each reading every 64th 16 B; thread 0 folds 64 hashes,
  compares with `hashes.Load4(piece*16)`, writes the flag. One thread per piece took 24.8 ms of an
  82 ms frame (405 passes, capture `replay1`); 64 threads cut hash passes 79 -> 66 ms of card time
  (`docs/findings.md:39-43`).
- **Why it won:** the CPU had byte-compared **550-710 MB/frame** against a snapshot to find shader writes; after the move only **~25 MB** is fetched/compared (`docs/README-fxceless.md:64-67`). Correctness: shaders write only declared ranges; an unchanged hash means the piece is not fetched and stays as the CPU had it.

## 2. XCL's current path and the hot loop

`refresh` `title_textures.rs:702` -> `take_written` `:715-729` over `cached_watch_ranges` `:662-685`
(built by `watch_ranges` `:1321-1345`, 64 MiB gap merge) -> `sparse::before_execute`
`sparse.rs:1554` -> `scan_page` `:334-371` per dirty 4 KiB page -> `upload_dirty` `:1137-1194`
(memcpy changed 64 B runs into the 64 MiB ring, then `CopyBufferRegion`) -> title queue waits the
upload fence `:1637`. `sent` is 64 u64 per 4 KiB page (`:93`); `TILE=64 KiB`, `PAGE=4 KiB`,
`CHUNK=64 B` (`:34-54`). `XCL_TRACE_MEM` `uma.rs:629-642`; `XCL_COHERENT_MB` `:780-788`;
`XCL_COHERENT_HEAPS` `kernelx.rs:331-360`. `XCL_WATCH_HOT`, `XCL_LOOK_SKIP`, `XCL_LOOK_AHEAD` are
absent on main; they are on `pr-2057` (`title_textures.rs` ~857-1100), whose comments measure an
8 GiB look at 4.3-4.9 ms, 64 x 2 MiB looks at 0.2 ms, and a retail world at ~66 submits/frame behind
a 7 ms look over ~11 GiB.

| stage (8,192 submits) | total | per submit | per frame (4.3 submits) |
|---|---:|---:|---:|
| write-watch (848,839 dirty pages) | 34,580 ms | 4.22 ms | **18.1 ms** |
| chunk scan | 239 ms | 29 us | 0.13 ms |
| upload (385,199 runs, 6.36 GB) | 1,178 ms | 144 us | 0.62 ms |
| lock wait | 304 ms | 37 us | 0.16 ms |

At t=56-64 s: 236 submits / 2 s, 55 presents / 2 s = 4.3 submits/frame, 27.5 fps; ~447 4 KiB
pages/frame (1.79 MB) hashed as ~28,600 64 B chunks. Per byte: **0.052 ns/B** (19.3 GB/s, 213 ns
per 4 KiB page, 3.3 ns per 64 B chunk), matching 29 us for ~104 pages. `content_hash` for texture
dedupe runs at 20 GB/s over ~25 MB/frame (`title_textures.rs:1108-1113`) = **1.25 ms/frame**.

CPU blocks in `GetWriteWatch`, not hashing: 97% of the look. Microbench: one full 1 GiB call = **1.08 ms**; a first call on a fresh 2 MiB subrange = **~0.49 ms** (same range repeated ~9 us); 64 x 16 MiB subranges = 31 ms. A ~4 GiB watched set therefore costs ~4 ms/look, matching the log. Stable whole-allocation calls beat many narrow ones; range churn during streaming is what makes subranges expensive.

## 3. Achievable win (16 GB RAM, RTX 4060, 21 GB commit)

| change | basis | expected |
|---|---|---:|
| look elision (`XCL_LOOK_SKIP` port) | skip when all lists closed before the last look | **~14-18 ms/frame** if most submits skip |
| per-page texture hash (dirty pages only) | 25 MB/frame at 20 GB/s | **~1.1 ms/frame** |
| whole-allocation watch + CPU filter | 1.08 ms/GiB vs 0.49 ms/fresh subrange | 0-2 ms/frame; measure churn |
| hot blocks (`pr-2057`) | upstream 0.2 ms for 64 x 2 MiB | 10x cut **if** ranges are stable; verify here |
| GPU upload-side compare | replaces 29 us scan + 144 us upload | **<=0.75 ms/frame**; reject (410 MB table, false positives) |
| GPU copy-back diff | only card-resident data | unknown; gate on readback bytes |

Commit is 23.5 GB here with 0.8 GB free: the world is pagefile-bound, so CPU savings may show in
menus/loading before in-world fps. Do the commit work first (`1-memory.md`).

## 4. Smallest viable GPU compare: readback diff

Only in `readback_ranges`/`readback_after_execute` (`sparse.rs:1023-1101`, `:1247-1276`), where the
GPU already has both sides: the tile and the CPU view's page signature.

- **Upload:** nothing per compare. Keep a GPU `page_sig` table: one 64-bit XOR of the page's 64 `sent` hashes per 4 KiB page (~25 MB for 12 GiB sparse VA, ~15 MB for the 3.7 GB mapped) plus a validity bit. Update 8-16 B only when `sent` changes (upload/merge/zero).
- **Shader/dispatch:** `cs_6_6` (compile pattern `real.rs:9048`, root signature `:8991`), one group
  of 64 threads per page, `Dispatch(pages,1,1)`: `h = hash_words(tile.Load8(p*4096+t*64))`; fold 64
  `h` with XOR, compare with `sig.Load(p*8)`, `flags.Store(p*4, differs)`. 4 KiB/page is noise.
- **Results:** flags (1 dword/page) -> `CopyBufferRegion` into the existing readback heap -> fence -> CPU map; coalesce flagged pages into runs and copy only those. Reuse `readback`/`readback_buf` (`sparse.rs:257`, `:949`). One extra fence wait (~50-150 us).
- **Correctness gate:** signatures derive from the same `sent` hashes the uploader trusts; invalidate
  on decommit/remap/zero (`decommit_tiles`, `clear_sent_range`, `release_if_unused`); missing/stale
  => treat as differing. `XCL_RB_DIFF_VERIFY=1` copies the whole range and asserts every differing
  page was flagged; 10 min streaming, 0 misses required.
- **Patch points:** `sparse.rs:88-100` (signature table), `:1137-1194` (update sig after upload),
  `:1023-1101` (diff pass before `pending`), `:1247-1276` (counters), `:1326-1347`
  (commit/decommit invalidate), new `sparse/diff.rs` (shader/PSO/buffers). `list_x.rs:2060` and
  `:3363` callers need no change.

## 5. Prototype decision and benchmark plan

No prototype: the upload-side ceiling is 0.75 ms/frame, the readback win is unmeasured, and the
integration sits on the submit fast path that needs an in-game run (not allowed here). Measure first.

1. Counter-only patch: `readback_after_execute` calls/ranges/pages/bytes; `readback_ranges` pages
   copied, wait us, memcpy us; log every 256 calls like `sparse.rs:1613-1632`. Run 5 min reference
   scene (`BENCHMARK-PROTOCOL.md`).
2. Gate: if readback is <2 MB/frame and <0.5 ms/frame, stop; the GPU diff has no payload.
3. A/B the CPU wins: port `XCL_LOOK_SKIP`, add per-page texture hashes, whole-allocation watch.
   3 runs each, p50/p95 frame time, same save/scene; accept >=3% with no correctness change.
4. If readback bytes are large: `XCL_RB_DIFF=1` (default off), A/B against step 3; accept >=3% and
   0 misses under `XCL_RB_DIFF_VERIFY=1`; rollback is the env var.
5. Instrument look cost per submit (`looks`, `ranges`, `MiB walked`, `dirty pages`, `us`); the
   current line only aggregates.

