# HLE hot paths — GTA VI 1.0.2.1 on VItoriaBr / fxceless

Date: 2026-11-25. Scope: `crates/victory-hle` and the `victory-gpu` entry points
HLE calls. This is a static inspection; no game was launched and no repository
was modified. Frequencies marked **[repo]** come from comments or the existing
diagnosis documents, **[inferred]** from the call site, and **[unverified]** need
the instrumentation in §6.

This document does **not** cover D3D12.X translation, descriptor/heap passes,
PSO/pipeline work, present, or the VRAM budget. See `MEMORY-STREAMING.md` for
the streaming/VRAM side and `PERF-DIAGNOSIS-2026-11-25.md` for the frame split.

## TL;DR

- HLE is **not** the 40–120× gap. It is a **per-frame tax on the same eight
  cores** that the D3D12.X translation already saturates, plus lock traffic
  that can stall the GPU-side title-memory reader.
- Top 3 avoidable HLE costs, in order:
  1. **`xmem::map_alias` and `XMemMapPhysicalPagesScatter`** do **one
     `MapViewOfFile3` + `VirtualFree` + `VirtualAlloc` per 64 KiB page** while
     the GPU side already hands HLE a whole range. On a streamed texture this
     is the largest HLE syscall count in the frame.
  2. **DirectStorage per-request path** (`execute` / `into_destination` /
     `page_window` / `queue`): per-request heap allocations, a per-request
     section-view map/unmap, a global scheduler mutex per enqueue, and a
     per-request scan of the page table. ~450 reads/frame **[repo]**.
  3. **XMA audio path** (`AcpHalSubmit` + the 2 ms decoder pump) — GameInput's
     8 ms keyboard scan is a close contender; see below. Audio: two locks of
     the same `SEEN` mutex per command, one `HEAP` mutex per output block,
     `VecDeque::pop_front` per sample, and a `Vec` allocation per decoded
     frame. Continuous on the title's mixer cadence (375 blocks/s **[repo]**).
- **Close contender for #3:** the GameInput poll thread scans **~244 virtual-key
  codes with `GetAsyncKeyState` every 8 ms** while the window is focused
  (~30k user32 calls/s), builds two `Vec`s, and drops them when nothing changed.
  One `GetKeyboardState` (if it works on the poll thread) or a 22-key
  gamepad/fallback set removes most of it. Audio and input are close; measure
  both before choosing #3.
- **Sleeper, highest behavioural leverage:** `XMemGetWorkingSetStatistics`
  performs a process-memory query on **every call** and reports
  `PROCESS_MEMORY_COUNTERS::PagefileUsage` as the title's usage. The title has
  been observed seeing ~27 GB against a 13.5 GB budget **[repo]**. If it polls
  this per frame, cache it and report title-owned bytes; the over-report can
  itself drive more streaming churn.
- HLE work is second-order against 27 µs/draw translation and 250–760 ms
  copies, but it is on the critical path and compounds through contention.
  Removing it is worth single-digit to low-tens of ms/frame, not 30 fps alone.

## Implemented

Date: 2026-11-25. Worktree `D:\git\VItoriaBr-opt-hle` (branch
`hle-opt-gameinput-xmem`, base `5a84eb4`). Two of the top findings, each with
unit tests, an environment kill switch and a measurement hook. The title was
**not** launched from this workstream.

### 1. GameInput keyboard scan (`gameinput.rs`, the `host` module)

- **Before:** the poll thread scanned 247 virtual keys (244 `GetAsyncKeyState`
  calls) every 8 ms while focused, ~30k user32 calls/s, whether or not a
  gamepad drives the title.
- **After:**
  - The scan checks the 24 keys the title can use through our devices (the 14
    fallback buttons plus `WASD`/`IJKL`/`Z`/`C`), not every key.
  - Rate: without a pad, every poll as before (fallback-pad latency
    unchanged). With a pad connected, `VICTORY_INPUT_RATE_MS` (default 64 ms).
  - Focus changes always rescan: losing focus clears the keys immediately,
    returning restores them at once.
  - Escape hatches: `VICTORY_INPUT_KEYS=full` (the old full scan),
    `VICTORY_INPUT_RATE_MS=<ms>` (0 = every poll).
- **Counter/log:** every 1,024 polls (~8 s) an `info!` line
  `input keyboard scans` prints `polls`, `scans`, `skipped`, `vk_calls`.
- **Expected:** with a pad, ~31k `GetAsyncKeyState`/s → ~375/s; without one,
  ~31k → ~3k/s. Poll-thread CPU and user32 traffic drop ~10× (it is a
  background thread, so the frame log moves little; the win is contention).
- **Tests:** `the_scan_covers_every_key_the_title_can_use`,
  `a_scan_is_due_on_focus_change_or_after_the_interval`,
  `keyboard_interval_follows_pads_and_the_override`.

### 2. xmem batching and identity remaps (`xmem.rs`)

- **Before:** `map_alias` did one `VirtualFree` + `MapViewOfFile3` +
  `VirtualAlloc` + GPU-side remap notification per 64 KiB page;
  `XMemMapPhysicalPagesScatter` called `XMemMapPhysicalPages` once per page,
  re-taking `PHYSICAL` and the `MAPPING` remap guard each time.
- **After:**
  - `map_alias`: identity fast path (the destination already shows the same
    section and offset → true no-op, no guard, no syscalls); one source-view
    lookup per call, and one `map` for the whole run when one view covers the
    source, with the per-page loop kept as the fallback for split
    placeholders.
  - `XMemMapPhysicalPages`: identity fast path when the view at `address`
    already shows exactly the requested pages.
  - `XMemMapPhysicalPagesScatter`: one `PHYSICAL` lock and one remap guard per
    call; consecutive addresses over consecutive slices of one section
    coalesce into one unmap + one map; consecutive clears coalesce into one
    unmap.
  - Internals refactored into `map_pages_locked` / `scatter_locked` /
    `map_alias_locked` so tests can hold the page-table lock.
  - Kill switch: `VICTORY_HLE_XMEM_BATCH=0` restores the old per-page
    behaviour everywhere (identity checks included).
- **Expected:** a 16-page remap goes from 48 kernel calls + 16 guard
  acquisitions + 32 GPU bookkeeping calls to 3 + 1 + 2; identity remaps cost
  ~0. The frame log's `remapping: N calls X ms (Y waiting)` should fall by the
  pages-per-call factor — 5–30 ms/frame at the reported texture rate, ~1–3 ms
  if `XMEM_PAGES` was really only ~83/frame. Scatter: N locks + N guards → 1.
- **Tests (test-only counters in `Physical`):**
  `map_alias_coalesces_runs_and_skips_identity_remaps`,
  `mapping_the_same_pages_again_is_a_no_op`,
  `scatter_coalesces_runs_and_takes_one_guard`,
  `scatter_still_clears_and_maps_each_address_alone_when_not_contiguous`.

### Build and test results (worktree)

- `cargo test -p victory-hle`: **110 passed, 0 failed** (7 new tests).
- `cargo clippy -p victory-hle --all-targets`: clean.
- `cargo build --locked --release -p victory`: ok.
- Toolchain note: the worktree was built with the machine's cargo 1.100.0
  (the repo pins 1.98.1); nothing used is newer than Rust 1.87.

### Benchmark (operator only; not run here)

```powershell
cd D:\git\VItoriaBr-opt-hle
$env:VICTORY_LOG = "victory_hle=info"
$env:VICTORY_FRAME_LOG = "1"
.\target\release\victory.exe run "D:\Gry\GTA6\GTA6.exe" --execute --console series-x 2> D:\git\gta6-30fps\benchmarks\hle-impl.log
```

Then the §7 parser, and compare `remapping:`, `disk:` and p50/p95 against the
baseline CSV. Watch the `input keyboard scans` line for `vk_calls`. A/B:
`$env:VICTORY_HLE_XMEM_BATCH = "0"` and `$env:VICTORY_INPUT_KEYS = "full"`.
Runbook reminder: the supervisor loads the reference save, clicks the game
window first, then presses Enter — this workstream never starts the title.

### Risks

- Reduced key set: keys outside the 24 (letters, digits, F-keys) no longer
  reach the title's keyboard device. Rollback: `VICTORY_INPUT_KEYS=full`.
- 64 ms keyboard rate with a pad can miss a tap shorter than one slow poll.
  Rollback: `VICTORY_INPUT_RATE_MS=8` or `0`.
- xmem identity skips rely on `views`/`shown` bookkeeping staying exact; a
  drifted table would skip a real remap and leave stale GPU-side guard state.
  The new tests assert no unmap/map/guard on identity; `VICTORY_HLE_XMEM_BATCH=0`
  is the rollback. A large `MEM_REPLACE_PLACEHOLDER` can fail on a split
  placeholder; the per-page fallback covers it.

## 1. Per-frame call map

None of the HLE exports is a per-draw shim: descriptors, heap passes, root
signatures, PSO selection and draw submission live in `victory-gpu`. HLE cost
arrives per **frame** (input, working-set poll), per **streaming request**
(DirectStorage, page maps), and per **audio block** (XMA), plus startup/menu
calls. That is why the top 3 below are not draw-shaped.

| Path | Trigger / evidence of rate | Verdict |
|---|---|---|
| `xmem::map_alias` via `CopyPageMappingsBatchX` | Each streamed texture mapped into the tiled heap; ~260 uploads/frame **[repo: PERF-DIAGNOSIS §03]**; ~83 remap notifications/frame in run 235, up to ~850 remaps in a streaming frame **[repo]** | **HOT** |
| `xmem::XMemMapPhysicalPages` / `...Scatter` | Title maps physical pages into pool views; per texture/batch **[inferred]** | **HOT** (same family) |
| `xmem::XMemGetWorkingSetStatistics` | Streaming budget poll; logged every 1,024th call **[repo: `xmem.rs:966-984`]**; rate **[unverified]** | **HOT if per frame** |
| `xmem::XMemVirtualQuery` (`xmem.rs:182-204`) | One `VirtualQueryEx` per call; allocators may poll it while streaming | Cache stable reservations if it shows in profiles |
| `dstorage::enqueue_request` → `queue` / `submit` / `execute` | ~450 disk reads/frame **[repo]** | **HOT** |
| `dstorage::open_file` | Per streamed file; load/streaming | WARM |
| `audio::submit` + XMA `pump` / `decode` | 375 audio blocks/s; decoder wakes every 2 ms **[repo: `audio.rs:711`, `:670`]** | **WARM, continuous** |
| `gameinput::current_reading` + 8 ms poll | Title reads input every frame **[repo: `gameinput.rs:334`]**; poll thread scans 247 keys per 8 ms while focused (see below) | WARM, but the poll scan is ~31k calls/s |
| `xgameruntime::QueryApiImpl` | Once per runtime API call; title calls are not per frame by design **[inferred]** | COLD |
| `xasync::*` | Per async operation; `XAsyncGetStatus(false)` is already lock-free | COLD/WARM |
| `files::*` | Path translation at open; synchronous `ReadFile`/`fread` if the title streams outside DS | CONDITIONAL |
| `xg::XGCreateTextureComputer` | Per texture computer; streaming-dependent | CONDITIONAL |
| `xgamesave`, `storage`, `xuser`, `xsystem`, downloads | Startup/menu/save | COLD |
| Import binding (`registry::lookup`, `host::imp::module`) | Startup only | COLD |

Repo note: VItoriaBr and fxceless have the same hot paths. Differences at
inspection time: fxceless's `watch.rs` has a `viewed` shortcut VItoriaBr lacks;
VItoriaBr carries the held-page `dstorage::submit_as` logic and the XMA
read-block wrap fix in `audio.rs`. Line numbers below are VItoriaBr; fxceless
offsets are given in §2.

**Startup-only, not worth optimizing per frame:** import binding
(`registry::lookup`, `host::imp::module`), `DStorageGetFactory`, queue/status
creation, `set_staging_buffer_size`, `XGameRuntimeInitialize`, the large
6.1 GiB `XMemAllocatePhysicalPages` at load, `XMemTransferMemory`, load-time
`XGCreateTextureComputer` calls, game saves/storage/user/system, `d3d12x`
device creation, and window/lifecycle setup. They can be slow at load; they do
not repeat per frame unless the title chooses to.

## 2. Top 3 hot paths

### #1 — `xmem::map_alias`: the GPU batches, HLE unbundles per page

**Files / lines (VItoriaBr):**

| Item | Location |
|---|---|
| Entry from D3D12.X batch | `crates/victory-gpu/src/queue.rs:1197-1248` (`copy_page_mappings`, `CopyPageMappingsBatchX`) |
| HLE map | `crates/victory-hle/src/modules/xmem.rs:742-770` (`map_alias`) |
| Per-page loop | `xmem.rs:748-768` |
| One page's map | `xmem.rs:774-819` (`map`) |
| Unmap / split | `xmem.rs:871-923` (`unmap`) |
| Public page map | `xmem.rs:666-706` (`XMemMapPhysicalPages`) |
| Scatter (one call per page) | `xmem.rs:710-735` (`XMemMapPhysicalPagesScatter`) |
| Remap guard | `victory-gpu/src/watch.rs:995-1000` (`title_memory_remapping`) |

**Per call.** `map_alias(to, from, len)` takes the global `PHYSICAL` mutex and
the `MAPPING` write lock once, calls `unmap` over the destination, then walks
`0..len` **one 64 KiB page at a time**. Every page does:

- `VirtualFree(base, PAGE, MEM_RELEASE | MEM_PRESERVE_PLACEHOLDER)`
- `MapViewOfFile3(..., MEM_REPLACE_PLACEHOLDER, ...)`
- `VirtualAlloc(base, PAGE, MEM_COMMIT, ...)` (`commit`)
- `victory_gpu::title_memory_remapped(base, PAGE)` and
  `victory_gpu::title_memory_view(...)`; VItoriaBr's `title_memory_remapped`
  alone allocates **four `Vec`s** and removes ranges from four `BTreeSet`s per
  call (`watch.rs:1038-1052`), then `descriptor::host::remapped` takes the
  `REMAPPED` mutex and records the page range (`descriptor/host.rs:494-507`),
  and `inplace::views_gone` / `title_memory_freeing` lock `VIEWS` per page
- one `physical.shown` `HashMap` entry (a `Vec` allocation on first address)
- one `physical.views` `BTreeMap` insert

`XMemMapPhysicalPages` already coalesces consecutive pages into one run
(`xmem.rs:685-704`), but `XMemMapPhysicalPagesScatter` calls it **once per
page** (`xmem.rs:718-733`), re-taking the write lock and redoing the `unmap`
scan each time. `map_alias` unmaps its whole range once but then maps it one
page at a time.

**Why it is avoidable.** `CopyPageMappingsBatchX` passes ranges
(`r.count` pages) and contiguous pool addresses. The common case is one source
view and one destination range. HLE can map the whole run with one
`MapViewOfFile3`, exactly as `XMemMapPhysicalPages` already does, and can skip
the operation entirely when the destination already shows the same
section/offset (a stream ring remapping the same window). Kind 1
(`queue.rs:1235`) deliberately maps the same source page at each destination
page and stays per page; the win is kind 0/2 and contiguous scatter runs.

**Frequency / size.** ~260 texture uploads/frame are reported; remap counts
range from ~83/frame in run 235 **[repo: fxceless `watch.rs:1140-1144`]** to
~850 in a streaming frame **[repo: PERF-DIAGNOSIS §03]**. A 4K BC7 texture with
mips is tens of MB; even a 1 MB range is 16 pages, so the per-page multiplier
is 16× over the batch the GPU already formed. By construction this is the
largest syscall source in HLE on this path.

**Fast paths.**

1. **Run-coalesce `map_alias`.** Take one source-view lookup per run (the
   `views` `BTreeMap` is range-indexed by address); for a single view, one
   `map(to, len, slice)` replaces N page maps. Fall back to per-page only if
   `map` fails on a split placeholder.
2. **Identity fast path.** If `physical.views[to]` already covers the same
   `len`, section and offset as the source (the common exact-base case), return
   `true` without `unmap`, `map`, or any `title_memory_*` call. Apply the same
   check to `XMemMapPhysicalPages` when its page list matches the current view.
   This preserves bytes, guards and protection; it is a true no-op.
3. **Batch scatter.** Refactor `XMemMapPhysicalPages` into a
   `map_pages_locked(&mut Physical, ...)` helper; `Scatter` takes the
   `PHYSICAL` mutex and `title_memory_remapping()` **once**, groups contiguous
   address runs, and unmaps each run once. N pages currently means N write
   locks and N `unmap` scans.
4. **Run-keyed page table.** `physical.pages` is a `HashMap<page, Slice>` and
   `physical.shown` is a `HashMap<(section, index), Vec<address>>`. A run key
   `(start_page, count, section, base_index)` removes the per-page hash lookups
   and the per-page `Vec` allocations; `shown_at` then answers with one range
   query. A faster hasher (FxHash) is a cheaper intermediate step.
5. **Narrow the critical section.** `PHYSICAL` is held while
   `title_memory_remapped` / `title_memory_view` take the GPU-side locks, and
   every DirectStorage page write takes `PHYSICAL` in `shown_at`. Sharding by
   section (or an `RwLock` with read-side `runs`/`shown_at` and write-side
   `map`) would stop map and write from serialising on one mutex. Do this only
   after §6 shows `RemapWaitUs` or `process kernel` is material.

**Expected.** For a 16-page run, 48 kernel calls + 32 GPU bookkeeping calls
become 3 + 2, and the `REMAPPED`/`VIEWS` locks fall from 16 to 1; identity
remaps become ~0. Order-of-magnitude: 5–30 ms/frame at the reported texture
rate, plus less `MAPPING` read-lock interference. Measure with `RemapUs` /
`RemapWaitUs` / `Remaps` already in the frame log. If `XMEM_PAGES` shows only
~83 pages/frame, the win is ~1–3 ms; if it shows 1,000+, it is 10–30 ms.

**Risk.** Destination placeholders may have been split by earlier per-page
maps; a large `MEM_REPLACE_PLACEHOLDER` can fail. Keep the per-page fallback
and a `VICTORY_HLE_XMEM_BATCH=0` escape hatch. Do not skip `title_memory_*`
when the mapping changes bytes or protection.

**Confidence:** high that the per-page loop exists; medium on the ms until
`XMEM_PAGES` is counted.

### #2 — DirectStorage: per-request allocation, per-request view, global lock

**Files / lines (VItoriaBr / fxceless):**

| Item | VItoriaBr | fxceless |
|---|---|---|
| `open_file` + always-on `WALLS_FILES` push | `dstorage.rs:117-151` (push `:149`) | same (`:149`) |
| `enqueue_request` | `:778-784` | `:810-816` |
| `queue` (global scheduler lock) | `:802-830` (lock `:808`) | `:834-863` |
| `submit` | `:832-843` | `:885-896` |
| `execute` | `:854-930` | `:907-980` |
| raw-read bounce allocation | `:891-900` (`vec![0; size]`) | `:944-953` |
| compressed source allocation | `:1018-1030` (`vec![0; size]`) | `:1071-1081` |
| `into_destination` | `:1065-1147` | `:1118-1200` |
| page window map | `xmem.rs:600-610` | same |
| page write notification | `xmem.rs:658-662` | same |
| `count` (4 atomics + clock) | `:525-565` | `:527-567` |

**Per request.**

- **Enqueue:** global `Mutex<Lanes>` + `HashMap<u64, Lane>` lookup + five
  length checks; at half capacity `submit_as` moves the batch and calls
  `notify_all` while holding the same lock.
- **Submit:** one global lock, `submit_as` assigns sequence numbers and
  `flush()`es status entries, then `notify_all`.
- **Raw read:** `vec![0; size]` bounce buffer, `ReadFile`, then
  `copy_from_slice` into title memory. That is an allocation and a full copy
  per raw read, added solely because a kernel write can fail on a guarded
  block (`dstorage.rs:882-900`).
- **Compressed read:** `read_source` allocates a source `Vec`, zlib/BCPack
  decode writes into the destination; one allocation per request.
- **Page destination:** `runs()` allocates a `Vec`, `page_window` maps a
  section view, `pages_written` calls `shown_at` (another `Vec` pair) under
  `PHYSICAL`, then the view is unmapped. A per-request `MapViewOfFile` +
  `UnmapViewOfFile` pair, plus a page-table scan.
- **Fallback:** another `vec![0; len]` + copy (`dstorage.rs:1110`).
- **Completion:** the request does four atomic adds (three in `count`, one in
  `read_into`) + three `Instant::elapsed` reads in `count` per request
  (`dstorage.rs:528-543`).

With ~450 reads/frame, a 1 µs saving per request is 0.45 ms/frame; a 10 µs
saving is 4.5 ms. This path is also where the "copies/textures" buckets in the
frame line partially come from (`disk: ... worker ms` includes `execute`).

**Fast paths.**

1. **Per-worker scratch, bounded.** Give each worker a `Scratch { bounce,
   source }` reused across requests (`Vec::resize` only when growing, cap e.g.
   8 MiB, shrink/drop above it). Removes allocator churn and zeroing from the
   hot loop. Bound = worker count × 2 buffers.
2. **Direct-first read with bounce fallback.** For non-page destinations, read
   straight into the destination after `kernel_will_write`; on
   `ERROR_INVALID_USER_BUFFER` retry through the scratch bounce. The title only
   observes completion, so a failed direct read is safe to retry. Gate with
   `VICTORY_DSTORAGE_DIRECT=1` for A/B.
3. **Per-worker section-view cache.** The destination pages of consecutive
   streaming requests usually belong to the same section and nearby offsets.
   Cache one `View` per worker keyed by `(section, offset, len)` (or a small
   LRU of 2–4 entries), reuse it while requests fall inside, and unmap on
   eviction. Bound the committed window (e.g. `VICTORY_DSTORAGE_VIEW_MB=4`,
   default 0 until measured). This removes a map/unmap pair per request.
4. **Stack/scratch `runs` and `shown_at`.** Replace the per-call `Vec`s with a
   fixed `[Option<(Slice, usize)>; 4]` and a thread-local scratch for
   `shown_at`; spill to `Vec` only for many-run cases. Removes ~450–900
   allocations/frame on the page path.
5. **Lane lookup.** Replace `HashMap<u64, Lane>` with `Vec<Lane>` indexed by
   the monotonic queue id (ids start at 0), so enqueue/submit is an array
   index, not a SipHash lookup. Keep tombstones for closed queues.
6. **Batch outside the lock.** Reserve capacity under the lock, then move
   commands / assign sequences in a per-lane structure; or shard the scheduler
   by queue. This is phase 2 — the allocation/view fixes are larger.
7. **`WALLS_FILES` only when tracing.** `open_file` always converts the path,
   clones it, and pushes `(file, path)` into a process-lifetime `Vec`, even
   with `VICTORY_WALLS_TRACE` unset; `File` has no `Drop`, so entries are never
   removed and the list grows for the whole session. Better: store the path in
   `File` state (the instance already owns the handle) and read it from
   `request.source` in `walls_request`; remove the global list entirely. At
   minimum gate the push on `walls_trace() != 0` and move the per-open `info!`
   to `debug!`.
8. **Bound the worker pool.** `scheduler()` starts
   `available_parallelism()` workers (`dstorage.rs:424-436`) — 16 on the
   8845HS — and every one competes with the title's render/submit threads.
   Add `VICTORY_DSTORAGE_WORKERS` (default 4–8) and A/B it; the existing
   `VICTORY_DISK_CORES=slow` is a coarser alternative.

**Expected.** Removing one allocation + one copy per raw read and one
map/unmap per page request is plausibly 5–15 ms/frame at the reported rate.
The lock reduction mainly helps workers and the title thread that enqueues.

**Risk.** Direct reads change the guard interaction; keep the bounce fallback
and the guard notifications (`kernel_will_write` / `title_memory_written`).
View caching must invalidate on `XMemFreePhysicalPages`, `title_memory_remapped`
and section reuse; a stale cached view would write freed/reused pages. Start
with a single cache entry and a page-number generation check.

**Confidence:** high on the allocations and per-request view; medium on how
often the raw bounce path is used until `DS_REQ_*` is counted.

### #3 — XMA audio: locks and copies on the mixer cadence

**Files / lines (VItoriaBr):**

| Item | Location |
|---|---|
| Coprocessor submit | `audio.rs:820-865` |
| Double `SEEN` lock | `audio.rs:828-831` |
| State mutex | `audio.rs:833` |
| XMA voice lock / command | `audio.rs:679-694`, `:412-493` |
| Decoder wake thread (2 ms) | `audio.rs:660-672` (park `:670`) |
| Pump all voices | `audio.rs:496-511` |
| Per-block write + per-sample pop | `audio.rs:514-544` (`heap_bytes` `:525`, `pop_front` `:529`) |
| Decode allocation | `audio.rs:549-628` (`Vec::with_capacity` `:595`) |
| Heap lookup under mutex | `audio.rs:183-191` |

**Per audio block / command.**

- `AcpHalSubmit` takes `SEEN` **twice** for the same command (a read lock/unlock
  then a write lock/unlock), then the per-connection `State` mutex, then for
  XMA commands the `XMA` `RwLock` and a per-voice mutex, then the `HEAP` mutex
  for the notification word.
- The decoder thread wakes every 2 ms, takes the `XMA` read lock, and locks
  **every allocated voice**, even when no voice is active.
- Each 256-byte output block calls `heap_bytes`, which takes the global `HEAP`
  mutex and does a `BTreeMap` range lookup.
- Each sample is moved with `VecDeque::pop_front` and copied into the ring
  (`audio.rs:528-532`).
- Each decoded 512-sample frame allocates a fresh `Vec::with_capacity`.

The decode itself is necessary CPU work that the console's hardware did; the
locks, per-sample queue traffic, allocations and 2 ms polling are shim
overhead. It runs on the title's time-critical mixer thread (`audio.rs:356-359`)
and a separate decoder thread, so it competes with the render/submit threads.

**Fast paths.**

1. **One `SEEN` lock per command.** Read and set the bit under one guard; log
   only when the bit was new.
2. **PCM ring instead of `VecDeque`.** Allocate a per-voice `Box<[i16]>` ring
   (bounded by the context's output block count × 128 samples), write decoded
   frames into it with `copy_from_slice`, and let `pump` copy contiguous runs
   into the output blocks. Removes one `pop_front` per sample and the
   intermediate `extend` copy.
3. **Reuse the decode scratch.** Keep a per-voice `Vec<i16>` and `clear()` it;
   `Decoder::decode` appends 512 samples. Removes one allocation per frame.
4. **Event-driven decoder.** `park()` until `enable`/`advance_read`; use
   `park_timeout` only while at least one voice is enabled and not full. Skip
   the all-voice loop when an atomic active count is 0.
5. **Cache the heap block per voice.** On enable/advance, resolve the output
   ring and notification block once; if the block generation is unchanged,
   derive the host pointer without taking `HEAP`. Invalidate on `ApuFree` and
   `AcpHalReleaseShapeContexts`.

**Expected.** Low single-digit % CPU, mostly removed from the audio thread and
from lock interference. It will not move a 1 s frame alone, but it is
continuous and it is extra work the console did on hardware.

**Risk.** Sample order, loop/skip semantics and the read-block wrap are
already subtle (VItoriaBr has a fix fxceless lacks). Keep the existing XMA
tests and add an A/B that records the title's audio (`VICTORY_AUDIO_CAPTURE`)
and compares it sample-for-sample.

**Confidence:** medium; depends on active voice count and command rate, which
`AUDIO_*` counters resolve.

### Close contender — GameInput's 8 ms keyboard scan

`Host::keys` (`gameinput.rs:1164-1189`, same lines in fxceless) runs on every
poll, and `poll` runs every 8 ms (`POLL`, `gameinput.rs:62`;
`Hub::poll`, `:403-411`). While `focused()` (`:1241-1248`) is true — normal
gameplay — it loops `0x08..=0xFE` (247 values, 3 modifier values skipped)
and calls `GetAsyncKeyState` **once per virtual-key code** (`:1172-1176`):
about 30k user32 calls/s, plus a `Vec<u8>` and a `Vec<KeyState>` per poll. It
does this even when a gamepad is connected and the title never reads the
keyboard device.

Fast path: try `GetKeyboardState` once per poll (it returns all 256 states in
one call; verify it is not stale on the non-message-pumping poll thread). If it
is stale, scan only the keys the title can use through HLE: the 14 fallback
buttons plus WASD/IJKL/Z/C (about 22), with `VICTORY_INPUT_KEYS=full` as the
diagnostic escape hatch. Reuse fixed arrays for the held keys and `KeyState`
list. This is a smaller and safer change than the XMA ring; measure it against
audio before choosing #3. The 8 ms sampling can also miss a tap shorter than
one poll; a low-level keyboard hook would be both cheaper and more correct if
the title needs every keystroke.

### Sleeper — `XMemGetWorkingSetStatistics`

`xmem.rs:949-988` calls `K32GetProcessMemoryInfo` on every invocation and
reports `counters.PagefileUsage` (the whole process, including the layer and
its card buffers) as `title_used`. The code's own comment records a run where
the title saw **27 GB against a 13.5 GB limit** (`xmem.rs:966-970`). A title
that budgets streaming from this pair believes it is far over budget; that can
increase eviction/re-read churn, which feeds #1 and #2, and can trigger
`XMemTransferMemory` calls that move title memory to the system for no reason.

**If it is called per frame** (likely; it logs only every 1,024th call):

- Cache the result for 50–100 ms (`VICTORY_MEM_STATS_TTL_MS`), or maintain an
  atomic `TITLE_USED` updated by `XMemVirtualAlloc`/`XMemAlloc`/free/transfer.
- Report title-owned bytes, not process commit. If exact accounting is not
  ready, subtract the layer's known allocations or clamp to `title_limit` as a
  stopgap; do not report a value above the console budget.
- Move the 1/1,024 `info!` to `debug!`.

This is the cheapest change with a possible behavioural payoff; verify the
call rate before ranking it above audio.

## 3. Long tail and verdicts

| Path | Why it is not top 3 | Action if measurement changes the ranking |
|---|---|---|
| `gameinput::current_reading` (`gameinput.rs:589-622`) | Per frame, but one mutex + a six-slot scan + an atomic refcount; sub-µs | The 8 ms keyboard scan is the real cost; see the close contender above |
| `xgameruntime::QueryApiImpl` (`xgameruntime.rs:222-261`) | Linear scan of ~26 GUID pairs per runtime API call; runtime calls are not per frame | Build a sorted static table once or cache the last pair |
| `xasync` (`xasync.rs:498-631`) | `XAsyncGetStatus(false)` is lock-free; begin locks `CALLS` twice (check + insert), complete up to twice on failure; only per operation | Combine the check/insert; store a tagged call pointer in the block |
| `xasync::Pool::submit` / delayed callbacks (`xasync.rs:165-173`, `:221-225`) | Spawns a thread per excess task or delayed timer; fine for a few saves, bad for a burst | Fixed-size pool + timer wheel; cap threads |
| `files::translate` (`files.rs:140-177`) | Takes `DRIVES` mutex and allocates a path `Vec` per call; mostly open/load | Read-mostly drive snapshot + fixed stack buffer for short paths |
| `files::ReadFile` / `fread` (`files.rs:527-572`) | `fread` allocates a bounce of up to 1 MiB per call and copies; conditional on the title using CRT I/O for streaming | Per-thread scratch; direct read when the range is unguarded |
| `xg::XGCreateTextureComputer` (`xg.rs:104-135`) | `Texture::new` walks mips and allocates; per texture, not per draw | Bounded desc→layout cache only if repeated identical descriptors appear |
| `net::once` (`net.rs:70-77`) | Global mutex + `String` lookups for every blocked connect; a retrying title could hit it often | Bounded negative cache; check the destination hash before allocating |
| `xstore::offline` (`xstore.rs:68-71`) | Info log + async completion per store call; startup/menu | Cache the game licence; move log to debug |
| `storage::path` / `space_info` (`storage.rs:50-144`) | `runtime::title()` clone + drive mount per path; recursive `used_bytes` + `GetDiskFreeSpaceExW` per space query | Cache the folder and quota with a TTL/dirty flag if polled |
| `xgamesave::quota_async` (`xgamesave.rs:683-692`, `:430-434`) | Recursive `used_bytes` + `GetDiskFreeSpaceExW` per call; menu/save only | Cache the quota; invalidate on writes |
| `dsp::XDspSubmitCommand` (`dsp.rs:199-227`) | Zeroes one output block per command; the silence is required | No change unless profiling says the zero-fill dominates |
| `apu::XApuEnqueueCommand` (`apu.rs:235-313`) | Opus decode + `vec![0f32; ...]` per command; offline single-player rarely uses voice | Reuse a per-stream PCM scratch if voice chat is active |
| `kernel::OutputDebugString` (`kernel.rs:215-234`) | `info!` per call; retail titles rarely log per frame | Rate-limit or `debug!`; keep the last line for crash context |
| `XMemTransferMemory` (`xmem.rs:992-1008`) | `info!` per call; transfers are rare | Move to `debug!` if it appears per frame |
| `lifecycle`, window, display | Startup/exit | None |
| Import binding | Startup only; no per-call trampoline after binding | None |

## 4. Logging / formatting audit

Release builds cap at `INFO` (`victory-core/src/logging.rs:14-18`), so **every
`info!` on a hot path is live**; `debug!`/`trace!` are compiled out and their
field expressions are not evaluated. Audit result:

| Live log | Rate | Change |
|---|---|---|
| `dstorage: file opened` (`dstorage.rs:145`) | Per file open | `debug!`; avoids `iid_text`'s `String` and build the path only when tracing |
| `dstorage: a queue half full...` (`dstorage.rs:875-880`) | Powers of two | Keep |
| `XMemTransferMemory` (`xmem.rs:994`) | Per transfer | `debug!` |
| `the title asks how much memory it uses` (`xmem.rs:976-984`) | 1/1,024 calls | `debug!` or remove |
| `first coprocessor command` (`audio.rs:831`) | Once per command kind | Keep |
| `input device` (`gameinput.rs:497`) | Connect/disconnect only | Keep |
| `store call: offline` (`xstore.rs:69`) | Per store call | `debug!` if it repeats |
| `network ... blocked` (`net.rs:74`) | First per destination | Keep, but bound the seen list |
| `game event dropped` (`xgame.rs:156`) | Per event | `debug!`; guard the `to_string_lossy` with `tracing::enabled!(DEBUG)` |
| `XErrorReport` (`xgameruntime.rs:263-271`) | Per reported error; a retrying title can spam | Rate-limit per `(hr, message)` or `debug!` after the first |
| `runtime method not implemented` (`xgameruntime.rs:122-131`) | Per unimplemented slot call | Warn once per `(area, slot)` |
| title `OutputDebugString` (`kernel.rs:215-229`) | Per call; a chatty title can log per frame | Keep the last line for crash context; rate-limit the log |

Also unconditional work around logs:

- `dstorage::open_file` always clones the path for `WALLS_FILES` (`:144-149`)
  and never removes it; see #2.
- `dstorage::submit` computes `pending` before `debug!` (`:839`); one lookup
  per Submit, negligible, but move it inside a debug guard if touched.
- `runtime::title()` deep-clones a `Title` (a `String` + `PathBuf`) under a
  mutex on every call (`runtime.rs:170-176`); `xgame::title_id` calls it per
  invocation (`xgame.rs:61-63`). Return an `Arc<Title>` or cache the id in an
  atomic if this ever shows up.
- `kernel::GetModuleFileNameW/A` (`kernel.rs:50-79`) locks `IMAGE_PATHS` and
  clones a `PathBuf` per call through `runtime::image_path`; a title that
  builds a path every frame pays a mutex + allocation. Cache the main image
  path in a `OnceLock` for the common `module == NULL` case.

## 5. Fast-path patterns, mapped to the requested categories

| Pattern | Where | Bound / invariant |
|---|---|---|
| **Bounded cache** | per-worker dstorage scratch (2 buffers, 8 MiB cap); per-worker section view (1–4 entries, 4 MiB window) | Worker count × cap; evict on section free/remap |
| **Bounded cache** | working-set stats TTL (single entry, 50–100 ms) | One entry; no unbounded history |
| **Lock-free lookup** | dstorage status (`is_complete` already atomic); xasync non-waiting status; gameinput newest-reading snapshot | Do not weaken ordering: status is `Acquire`/`Release` |
| **Lock-free lookup** | lane `Vec` index instead of `HashMap`; run-keyed page table | Ids are monotonic; tombstones for closed lanes |
| **Lazy formatting** | `info!` → `debug!` on open/transfer/working-set/event; guard `to_string_lossy` | Release cap remains INFO; no formatting when disabled |
| **Batched completion** | dstorage status entries already batch per lane; one `notify_all` per Submit/auto-submit | Keep per-lane order; no completion before earlier reads |
| **Batched mapping** | `map_alias` / `Scatter` one `MapViewOfFile3` per run, one `MAPPING` lock per call | Per-page fallback on placeholder split |
| **Batched input** | one `GetKeyboardState` (or a 22-key set) instead of ~244 `GetAsyncKeyState` calls per 8 ms | Same held-key list the title sees |
| **Lazy thread** | XMA decoder parks until enable/advance; scan active voices only | 2 ms timeout only while active, to avoid underruns |

What not to do:

- Do not skip `title_memory_remapped` for a mapping that changes
  section/offset; only skip a verified identity remap.
- Do not cache a section view across `XMemFreePhysicalPages` or section-handle
  reuse without a generation check.
- Do not bypass `kernel_will_write` / `title_memory_written`; the GPU side's
  guard and write-watch state depends on them.
- Do not return zeroed/unwritten pages on a failed write; the title polls only
  completion and will silently use stale bytes (`dstorage.rs:1156-1163`).

## 6. Verification and test plan

### 6.1 Zero-code baseline (do this first)

The frame log already measures #1 and most of #2 without a patch:

- `remapping: N calls X ms (Y waiting for readers)` = `T::Remaps`,
  `T::RemapUs`, `T::RemapWaitUs` (`victory-gpu/src/framelog.rs:446-448`).
  `RemapUs` covers the `MAPPING` guard, i.e. one whole `map_alias` or
  `XMemMapPhysicalPages` call; `Scatter` takes that guard once **per page**.
  `RemapWaitUs` is contention with GPU-side title-memory reads.
- `disk: N reads X MB Y worker ms` = `T::DiskReads`, `T::DiskBytes`,
  `T::DiskUs` (`framelog.rs:452-454`). `DiskUs` covers file read, decompress,
  bounce copy, page-window map and `shown_at`.
- `process: X user Y kernel ms` shows kernel time that page maps should reduce.

Extract the fields from the `usual frame` line:

```powershell
$log = "D:\Gry\VItoriaBr-data\logs\game-stderr.log"
Select-String -Path $log -Pattern 'usual frame' | Select-Object -Last 5
```

```powershell
python -c "import re,sys
p=re.compile(r'remapping:\s*(\d+) calls\s*([\d.]+) ms\s*\(([\d.]+) waiting.*?disk:\s*(\d+) reads\s*([\d.]+) MB\s*([\d.]+) worker ms')
for l in open(sys.argv[1],encoding='utf-8',errors='replace'):
    if 'usual frame' in l:
        m=p.search(l)
        if m: print('remaps calls/ms/wait, disk reads/MB/ms =', m.groups())
" $log
```

Record p50/p95 and per-frame times with the existing parser:

```powershell
python D:\git\gta6-30fps\tools\bench\parse_victory_log.py $log --frames --csv D:\git\gta6-30fps\benchmarks\hle-baseline.csv
```

Acceptance for the baseline: 3 runs, warm cache, same save/scene, 60 s window,
`p50`/`p95` spread < 10 %. If `RemapUs` is < 5 ms/frame and `DiskUs` is
< 20 ms/frame, HLE is not worth touching before the D3D12.X work.

### 6.2 Instrumentation (scratch clone only)

Do **not** commit instrumentation to the main repos. In a scratch clone
(`git clone --shared`) add `crates/victory-hle/src/profile.rs` (and `mod
profile;` in `lib.rs`):

- `AtomicU64` counters, `Relaxed`: calls, bytes, `ns`, allocations, lock waits,
  cache hits, identity hits.
- One `OnceLock<bool>` for `VICTORY_HLE_PROF=1`; if off, each hook is one
  predictable branch.
- A 5 s reporter thread that prints one line, e.g.:
  `hle: xmem maps=... pages=... identity=... us=... | ds req=... page=... bounce=... maps=... us=... | ws calls=... cached=... us=... | audio cmd=... pump=... voices=... allocs=...`
- Time with `Instant::now()` only inside `if enabled`; never format in the hot
  path.

Minimum counters to resolve the open questions:

| Question | Counter |
|---|---|
| How many pages per `map_alias` call? | `XMEM_MAP_CALLS`, `XMEM_PAGES`, `XMEM_RUNS`, `XMEM_IDENTITY` |
| How many `Scatter` calls/pages? | `XMEM_SCATTER_CALLS`, `XMEM_SCATTER_PAGES` |
| Is the raw-read bounce path common? | `DS_REQ_RAW`, `DS_REQ_ZLIB`, `DS_REQ_BCPACK`, `DS_REQ_PAGE`, `DS_REQ_MEMORY` |
| How often does bounce happen? | `DS_BOUNCE_ALLOCS`, `DS_BOUNCE_BYTES` |
| Per-request view cost? | `DS_VIEW_MAPS`, `DS_VIEW_MAP_NS` |
| Working-set rate? | `WS_CALLS`, `WS_NS`, `WS_TTL_HITS` |
| Audio lock/alloc cost? | `AUDIO_SUBMITS`, `AUDIO_PUMP_NS`, `AUDIO_DECODE_ALLOCS`, `AUDIO_HEAP_LOCKS` |
| Input per-frame cost? | `INPUT_READINGS`, `INPUT_LOCK_WAIT_NS`, `INPUT_POLLS`, `INPUT_VK_SCANS` |

Run with `VICTORY_HLE_PROF=1` and capture the 5 s lines alongside the frame
line. This answers "is it per frame?" without guessing.

### 6.3 A/B protocol

- One change per build; 3 runs per arm; same save, scene, camera, resolution,
  power plan, driver, warm shader cache.
- Metrics: p50/p95 frame time, `RemapUs`/`RemapWaitUs`, `DiskUs`, process
  user/kernel ms, disk reads/MB, uploads, draws, dropped, VRAM peak.
- Correctness: same screenshot at the same frame, save/load, 5-minute soak, no
  device loss, no new `warn!`/`error!`.
- Promotion gate: a change stays only if it improves the target metric by
  ≥10 % (or removes ≥50 % of the path's per-frame cost) **and** p95 does not
  regress by >2 % **and** the image is unchanged.
- Keep an environment kill switch per change so the operator can A/B without a
  rebuild:
  `VICTORY_HLE_XMEM_BATCH`, `VICTORY_DSTORAGE_SCRATCH`,
  `VICTORY_DSTORAGE_DIRECT`, `VICTORY_DSTORAGE_VIEW_MB`,
  `VICTORY_DSTORAGE_WORKERS`, `VICTORY_XMA_RING`, `VICTORY_MEM_STATS_TTL_MS`,
  `VICTORY_INPUT_KEYS`.

### 6.4 Unit and micro tests (no game)

- `map_alias` run coalescing: map 16 consecutive pages; assert one `map` call
  per source run (test-only counter) and correct bytes at both ends.
- Identity remap: map the same range twice; assert no `unmap`/`map` and no
  `title_memory_*` call on the second.
- `Scatter`: map N contiguous addresses; assert one `title_memory_remapping`
  acquisition and one `unmap` per run.
- dstorage scratch: repeated raw reads with the same size; assert one
  allocation and correct contents; force a larger request and assert growth.
- Direct-first read: normal destination uses direct (test counter); a forced
  read error falls back and still returns the right bytes.
- Working-set TTL: two calls inside the TTL return the same value; after the
  TTL a changed commit is visible.
- Audio ring: decode a known XMA packet; compare the ring output to the
  existing `VecDeque` path sample-for-sample; loop and skip cases included.

### 6.5 Optional ETW / WPR attribution

If symbols resolve (release has `debug = "line-tables-only"`), run in an
administrator shell:

```powershell
wpr -start CPU -filemode
# run the title for 60 s at the reference scene
wpr -stop D:\git\gta6-30fps\benchmarks\hle.etl
```

Open `hle.etl` in Windows Performance Analyzer → CPU Usage (Sampled) → filter
`Process = victory.exe` → group by Stack. Look for
`victory_hle!...xmem::map`, `...dstorage::execute`, `...audio::pump`,
`...xmem::XMemGetWorkingSetStatistics`. A before/after weight drop confirms the
microbench. If WPA is unavailable, install the Windows Performance Toolkit
from the ADK; do not add it to the repo.

### 6.6 Acceptance and rollback

| Change | Target metric | Pass | Rollback |
|---|---|---|---|
| xmem batch/identity | `RemapUs` per frame | −50 % or more, p95 not worse | `VICTORY_HLE_XMEM_BATCH=0` |
| dstorage scratch/direct | `DiskUs` per frame, kernel ms | −20 %, p95 not worse | `VICTORY_DSTORAGE_SCRATCH=0`, `..._DIRECT=0` |
| dstorage view cache | `DiskUs`, map count | −20 %, no stale bytes | `VICTORY_DSTORAGE_VIEW_MB=0` |
| dstorage workers | p95, CPU contention | better p95 at 4–8 workers | `VICTORY_DSTORAGE_WORKERS=16` |
| working set | `WS_CALLS`, streaming reads | calls cached >90 %, reads not up | `VICTORY_MEM_STATS_TTL_MS=0` |
| audio ring | audio thread CPU, WAV diff | −30 % CPU, bit-identical PCM | `VICTORY_XMA_RING=0` |
| input scan | `INPUT_VK_SCANS`, poll-thread CPU | −80 % VK calls, same keys reported | `VICTORY_INPUT_KEYS=full` |

A change that only moves time between `RemapUs` and `DiskUs` is not a win;
look at p50/p95 and total CPU.

## 7. Exact commands

### Build and unit tests

```powershell
cd D:\git\VItoriaBr
cargo test -p victory-hle
cargo build --release -p victory
cargo build --profile diag -p victory --features diagnostics

cd D:\git\fxceless-victory
cargo test -p victory-hle
cargo build --release -p victory
```

### Run one capture (operator; this agent does not launch the title)

```powershell
cd D:\git\VItoriaBr
$env:VICTORY_LOG = "victory_hle=info"
$env:VICTORY_FRAME_LOG = "1"
.\target\release\victory.exe run "D:\Gry\GTA6\GTA6.exe" --execute --console series-x 2> D:\git\gta6-30fps\benchmarks\hle-baseline.log
```

Use the same title path and console model as the existing baseline. For the
instrumented scratch clone, add `$env:VICTORY_HLE_PROF = "1"`.

### Parse

```powershell
python D:\git\gta6-30fps\tools\bench\parse_victory_log.py D:\git\gta6-30fps\benchmarks\hle-baseline.log --frames --csv D:\git\gta6-30fps\benchmarks\hle-baseline.csv
Select-String -Path D:\git\gta6-30fps\benchmarks\hle-baseline.log -Pattern 'usual frame|remapping:|disk:' | Select-Object -Last 20
```

### Three-run harness

```powershell
python D:\git\gta6-30fps\tools\bench\bench_run.py --runtime vitoriabr --variant hle-xmem-batch --cache warm --runs 3 --window 60 --out D:\git\gta6-30fps\benchmarks\runs\2026-11-25-hle-xmem-batch
```

The driver never starts the game; the supervisor loads the reference save and
keeps the camera still (see `BENCHMARK-PROTOCOL.md`).

### Static inspection used for this document

```powershell
Select-String -Path D:\git\VItoriaBr\crates\victory-hle\src\modules\xmem.rs -Pattern 'map_alias|XMemMapPhysicalPagesScatter|page_window|shown_at|XMemGetWorkingSetStatistics'
Select-String -Path D:\git\VItoriaBr\crates\victory-hle\src\modules\dstorage.rs -Pattern 'fn queue|fn execute|let bounce|page_window|WALLS_FILES'
Select-String -Path D:\git\VItoriaBr\crates\victory-hle\src\modules\audio.rs -Pattern 'extern "system" fn submit|fn pump|fn decode|heap_bytes|Vec::with_capacity'
```

## 8. Open questions that could change the ranking

1. **Pages per remap.** The 83/frame note may count `title_memory_remapped`
   calls, not `map_alias` calls. The `XMEM_PAGES` counter decides whether #1 is
   80 syscalls or 2,000 per frame.
2. **Working-set rate.** If it is once per frame, promote the working-set cache
   above audio; if it is once per 10 s, audio stays #3.
3. **Queue count.** `Lanes::start` scans every lane twice per job. If the title
   creates many queues, that is a separate O(queues) cost per request.
4. **Async bursts.** If the title submits many XAsync tasks in one frame,
   `Pool::submit` can create a thread per excess task; count the pool growth
   before deciding on a fixed pool.
5. **Bounce frequency.** If most streaming reads use `PAGE_DESTINATION`, the
   bounce path is minor and the view cache is the main #2 win.
6. **XMA voice count.** The 2 ms pass locks every allocated voice; a count of
   256+ makes the lazy-thread fix more valuable.
7. **Input read count.** If the title calls `current_reading` several times per
   frame for each device, the seqlock snapshot is worth it; otherwise leave it.

## 9. Handoffs / non-goals

- **Do not duplicate `MEMORY-STREAMING.md`:** that document owns VRAM budget,
  staging, eviction and the texture pass. This one owns HLE call overhead.
- **Do not duplicate the D3D12.X agents (A–F, H–J):** descriptor heaps,
  indirect draws, PSO/pipeline waits and present are out of scope here.
- **Do not tune the scheduler or shim semantics by changing observable
  behaviour.** Every fast path above is an identity or a proven fallback; a
  request that would have failed must still fail, and a page that would have
  been unwritten must still be reported.
- **Do not launch the title from this workstream.** The commands in §7 are for
  the operator/supervisor with the reference save.

## References (source)

- `D:\git\VItoriaBr\crates\victory-hle\src\modules\xmem.rs`, `dstorage.rs`,
  `audio.rs`, `gameinput.rs`, `xgameruntime.rs`, `files.rs`
- `D:\git\fxceless-victory\crates\victory-hle\src\modules\xmem.rs`, `dstorage.rs`,
  `audio.rs`, `gameinput.rs`
- `D:\git\VItoriaBr\crates\victory-gpu\src\queue.rs`, `watch.rs`, `framelog.rs`
- `D:\git\fxceless-victory\crates\victory-gpu\src\watch.rs` (83 remaps/frame note)
- `D:\git\gta6-30fps\docs\PERF-DIAGNOSIS-2026-11-25.md` §03 (450 reads/frame,
  260 uploads/frame)
- `D:\git\gta6-30fps\docs\MEMORY-STREAMING.md` (VRAM/streaming budget)
