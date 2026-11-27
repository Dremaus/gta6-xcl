# XCL PSO queue: "58 731 pipelines queued, 0 running, 0 done"

Scope: `pso_async.rs`, `dxc.rs`, `shaders.rs`. Branch `agent/pso`, commit 7fa11cf4
(8b957bec + the XCL_SKIP_PREPARATION / memcap.rs / uma.rs patches, kept).

## Root cause: the three numbers count different things

`present.rs:446-449` mixes two counters:

- `running`/`done` = `dxc::compile_counts()` (`dxc.rs:1193`): cache-miss DXC
  compiles inside `Compiling`, and finished ones. `Compiling::start()` is only
  reached *after* `wait_for_memory` admits the thread (`dxc.rs:614` vs `1134`).
  Admission waits, console->HLSL translation, driver `CreatePipelineState` and
  DXIL cache hits are invisible here.
- old `queued` = `pso_async::counts()` third value (`pso_async.rs:1311`): every
  `PENDING` entry whose `done` is false. `submit_as` inserts one per pipeline the
  title creates (`pso_async.rs:388-404`, `real.rs:5672-5675`); entries leave only
  on the title's Release (`pso_async.rs:1196`). With default lazy mode
  (`pso_async.rs:377`) an unbound pipeline is queued nowhere; its job stays in
  `Pending` until the first bind. So 58 731 was not work - it was stand-ins the
  title had created and not released. The module notes a retail title makes
  ~51 000 pipelines in its first 30 s (`pso_async.rs:375`).

Only entries whose shader key is in `used-pipelines.txt` become speculative
preload (`pso_async.rs:411`); the rest are dormant. On a cold cache
(`XCL_SKIP_PREPARATION`) the preload list is empty and the number is purely the
title's object count.

## Memory admission path

`dxc.rs:534` (old `:446`):

1. a DXC/PSO worker calls `wait_for_memory` (`dxc.rs:614`);
2. `need = RESERVE_GB (6) + WORKING` GB (`:538-539`), `plenty = avail_commit >=
   need`; `avail_commit` reads the real machine via `memcap::system_memory`
   (the `XCL_HOST_MEMORY_MB` detour is bypassed on purpose);
3. at 24 GB committed on 16 GB RAM, available commit is ~0: `plenty` false; the
   wanted bypass admitted up to `WANTED_AT_ONCE` (6) and the old `elapsed >= 60 s`
   clause admitted *every* waiter at once, each compile growing to 0.7 GB
   (`dxc.rs:400-401`) - the OOM cliff;
4. otherwise one compile at a time via `WORKING.compare_exchange(0,1)`, so the
   2-4 preload workers and demand serialise;
5. preload builds are not "wanted" (`Demand.wanted` only from a bind,
   `pso_async.rs:97`), so under pressure they move last while still holding a
   pool worker each.

Nothing bounded the speculative side: pre-patch `submit_as` pushed every
known-key pipeline into `Preload.list` (`pso_async.rs:411-416`), and each
`Pending` retains its `Job` -> `OwnedDesc` -> a copy of the shader blobs
(`real.rs:5449-5451`, `5664-5671`). 58 731 stand-ins x ~400 KB retained
blob/desc, plus the driver PSO of each built pipeline (`pso_async.rs:375-376`),
is the same order as the measured 24 GB: unbounded, and pointed at work the
title may never bind.

`shaders.rs`: startup disables the DXIL size cap (`p.max_dxil = 0`,
`shaders.rs:1660`) because capped pipelines count as preparation failure
(`:1835`). Intentional, not the runtime queue; flagged as follow-up.
## Patch (7fa11cf4)

`dxc.rs`
- `admission()`: pure `(avail, need, working, wanted, min_free) -> Many | One |
  Wait`, unit-tested.
- Hard floor `XCL_DXC_MIN_FREE_GB` (default 2, 0 = off): below it at most one
  compile, wanted or not; the 60 s path is gone.
- Above the floor a wanted compile still needs 1 GB free for itself, up to
  `WANTED_AT_ONCE`, instead of bypassing memory checks.
- `free_commit_gb()` for `pso_async`; `waiting_for_memory()` + `WaitingCount`
  (counts a call once it sleeps) for the title.

`pso_async.rs`
- `preload_admitted()`: cap + commit gate, unit-tested.
- `Preload` gains `cap` (`XCL_PSO_PRELOAD_CAP`, default 2048) and `min_free_gb`
  (`XCL_PSO_PRELOAD_MIN_FREE_GB`, default 3). Over the cap or under the floor an
  entry stays lazy; its first bind still sends it (`resolve_within` /
  `resolve_spared`). The worker re-checks free commit before building and drops
  (not builds) speculative entries under pressure.
- `Progress { built, failed, unresolved, building, preloading }` + `progress()`:
  `building` = sent/taken, `preloading` = real list, `unresolved` = dormant
  stand-ins. `counts()` is unchanged for the report but documented as stand-ins.
- Preload workers set `sent` when they take a job, so in-flight preloads show as
  `building`.

`present.rs`: title is `compiling shaders: R running, D done, K built[, B
building][, P preloading][, W waiting for memory][, F failed]`; dormant stand-ins
no longer look queued and `active` watches the real queues only.

Demand before speculation is structural: binds build inline or enqueue to the
normal workers (`need_by_submit` first); a bind taking a job out of a `Pending`
turns the preload entry into a no-op; preload workers are lowest-priority and
commit-capped.
## Risk

- Below the floor a wanted compile can wait one compile behind an unwanted one
  (bounded, no deadlock; `MemorySlot` is RAII; `XCL_DXC_MIN_FREE_GB=0` restores
  the old wanted concurrency). Cold-cache preparation under pressure serialises
  instead of the 60 s burst: slower, but no longer OOM.
- Cap 2048 means after a >2048-pipeline previous run some world pipelines build
  on first bind; correctness unchanged. `progress()` walks PENDING once per
  window timer, locking each `done`: ~1-2 ms at 58 k stand-ins.
## Test

- `dxc::admission_tests`: `plenty_admits_many`, `below_the_floor_only_one_compile_runs`,
  `short_commit_bounds_wanted_compiles_by_free_room` (working > 0 below the
  floor must stay `Wait`; the 60 s thundering herd is the regression case).
- `pso_async::preload_tests`: `the_preload_list_is_capped`,
  `low_commit_keeps_speculative_pipelines_lazy`.

## Verification

- `cargo check -p xcl`: OK. `cargo test -p xcl --lib`: 1323 passed, 0 failed,
  27 ignored (5 new; 1327 after the dedup). `cargo clippy -p xcl --lib`: no new warnings in touched
  code; pre-existing `approx_constant` errors in `gpu/dxil/lower_*.rs` remain.
  `rustfmt --check` is not clean at HEAD; new code follows the file's style.
- No game launched, no GPU touched.

## Dedup (18291190)

Every stand-in kept a private copy of its shader bytes:

- `OwnedDesc` owned `Vec<Vec<u8>>` / `Vec<u8>` (pre-patch `real.rs:5399-5402`);
- `own_shader` copied each stage (pre-patch `:5451`) and `own_stream` each
  subobject (`:5521`), then rewrote the descriptor to point at the copy;
- `go_background` moves that `OwnedDesc` into the `Job` (`:5801`), which
  `submit_as` stores in the `Pending` for the pipeline's whole life; the preload
  list and a bind take that same `Job`, so there is one copy per pipeline, not
  one per path. Stand-in driver PSOs were already shared by key
  (`standin.rs:1-8`), so these copies were what remained.

Now `intern_shader` (`real.rs:5465`) keeps one `Arc<[u8]>` per program in a
content-addressed store, `ShaderStore = HashMap<(len, FNV-1a), Weak<[u8]>>`
(`:5448`), compares the bytes before sharing (collision-safe) and prunes dead
keys every 1024 entries. `OwnedDesc` holds `ShaderBlob { bytes: Arc, hash }`
(`:5396`), so descriptors point at the shared allocation and
`OwnedDesc::shaders_key` combines the cached hashes (no second hash pass over
~23 GB). The store is weak: a blob is freed with the last `Pending`/Job using
it; release ordering and `done` flags are unchanged.

Accounting per stand-in with S shader bytes in k blobs: before S bytes in k
allocations (+24 B Vec header each); after the unique program's shared copy
plus 16 B per blob pointer. A duplicate 400 KiB (409,600 B) stand-in with
k=2 saves 409,600 - 8k = 409,584 B; at 400,000 B it is 399,984 B. 58 731 x
409,600 B = 24.06 GB, the measured commit. With N=58 731 and U unique
programs, saved = (N-U) x (S-8k):

| U | saved | copies left | expected commit (24 GB case) |
|---|---|---|---|
| 2 000 | 23.2 GB | 0.8 GB | ~2-3 GB |
| 5 000 | 22.0 GB | 2.1 GB | ~3-4 GB |
| 10 000 | 20.0 GB | 4.1 GB | ~5-6 GB |
| 20 000 | 15.9 GB | 8.2 GB | ~9-10 GB |
| 58 731 | 0 | 24 GB | ~24 GB (unchanged) |

Expected commit is the measured 24 GB minus the deduplicated copies, plus at
most ~0.8 GB of driver PSOs (`XCL_PSO_PRELOAD_CAP` 2048) and the title's own
data. Exact S and U are logged every 64 MiB ("B of shader blobs requested, B in
unique allocations"); the next run measures the real ratio.

Tests (`real::shared_shader_tests`): identical content shares one allocation
and survives one owner's release; different content (same length too) does not
share; releasing one descriptor leaves the other's `CS` bytes live (strong
count 1, no strong ref in the store); the cached key equals `shaders_key`.
`cargo test -p xcl --lib`: 1327 passed, 0 failed, 27 ignored. `XCL_ASYNC_PSO=0`
never takes `go_background` (direct `translated_*` path), so it is untouched;
`shaders_key` only became generic over `AsRef<[u8]>`.

## Follow-ups

`dispatch_chain::build` still copies the whole DXIL per chain
(`dispatch_chain.rs:94`); driver PSOs remain per built pipeline (bounded by the
preload cap). The `XCL_ASYNC_PSO=0` run (1 draw/present, 0 dispatches) is a
submit-side problem, not this queue.


---

# Driver blob cache: why the huge PSOs were not written

Worktree `D:\git\xcl-wt-cache`, branch `agent/pso-cache`, commit **35606f33** on
`main` 7f1a617b (worktree commit, not pushed). No game launched, no GPU work.

## Evidence (xcl.log, run 18:15:44 - 18:20:44, XCL_RUN_SECONDS=300)

- Five compute compiles >= 10 s, all `driver blob absent`:
  `710108 B` 11.3 s, `694668 B` 11.0 s, `1161732 B` 23.3 s, `1167344 B` 22.9 s,
  `1238616 B` 25.7 s. The first four wrote a `.chain.pso` at the exact finish
  second, with these `GetCachedBlob` sizes (HRESULT S_OK; an empty/failed blob
  is not stored):
  `ad5dc` 988,846 B, `a998c` 966,542 B, `11ba04` 1,544,734 B,
  `11cff0` 1,545,470 B, `12e658` 1,661,342 B.
- The fifth (`965776 B`, start 298.674 s) has no finish line and no file: the run
  was ended at 300.002 s before `GetCachedBlob`/write. A cut-short run cannot
  cache the program it is still compiling; this is not a write error.
- Filenames hash the **translated DXIL** (`fnv64(dxil)`), not the console record:
  no name contains `50b71c6c227e4ea4`/`c1cffdc3f13a4f2f` (checked: 0). The 79
  stable records are stable, but a name check by record hash is impossible.
  Mapping is now logged: `GetCachedBlob ... returned N KB (hr 0x0)` and
  `keeping ... as <path>` / `loading ... <path>` for every program >= 512 KB.

## The recurring, write-side miss

Two **graphics** PSOs (`c1cffdc3f13a4f2f`, 819,688 and 819,904 B DXIL) are
`driver blob absent` in `xcl.prev.log` *and* `xcl.log`, and no `gfx-*-c81e8.pso`
/ `-c82c0.pso` exists. They finish in 0 - 1 ms: the driver's own cache rebuilt
them, so `driver_cache::keep` skipped the store under its only rule -
`worth_keeping(took) = took >= 250 ms`. A 1.4 MB blob was therefore never
written, and the next run asked again. This is the "rule that only stores
builds over N ms"; the size was not considered.

## Patch (2 files, +338/-46)

- `driver_cache::worth_keeping(took, bytes)`: a blob at or over
  `DIAG_BYTES` (512 KiB) is kept even when its build was fast; the fast build
  only means the driver's cache was warm this time. Every skipped store now logs
  the size and the reason (`FastAndSmall`, over-budget, unwritable with the OS
  error from `write_result`).
- The disk copy no longer depends on `COMPUTE_BLOBS` accepting the blob (its
  512 MB budget): `keep_compute_blob`/`keep_graphics_blob` return the blob they
  read, and the store site writes that. `GetCachedBlob`'s HRESULT and size are
  logged for compute and graphics PSOs >= 512 KB; `read_pso_cached_blob_result`
  keeps the HRESULT.
- The same cache file is logged on write and on load, with `flags` and
  `chained`, so a namespace mismatch (`.pso` vs `.chain.pso`) is visible.
- Driver folder budget `XCL_PSO_DISK_MAX_MB` (4096; 0 = off): after a write the
  oldest `*.pso` files are removed until the folder fits, tracked in
  `ON_DISK`. Pure `trim_count(sizes_oldest_first, total, cap, incoming)`.
- Chain-whole forms of huge programs are prewarmed on one low-priority
  `xcl-pso-prewarm` thread (`XCL_PSO_PREWARM_MAX`, 8 per run, 0 = off) when no
  `.chain.pso` exists, so the blob exists before a scratch-less dispatch needs it
  and before a cut-short run ends. `scratch_for` retries a failed scratch
  allocation with one group's worth (one dispatch per group) instead of falling
  back to the whole PSO; the fallback, if any, logs allocator/bytes/grid.

## Tests / build (under `D:\git\.xcl-build.lock`, atomic New-Item, released)

- `cargo check -p xcl --lib --release`: OK.
- `cargo test -p xcl --lib --release`: **1335 passed, 0 failed, 27 ignored**
  (was 1334; +1 policy test, +1 prewarm test, +1 eviction test).
  New: `a_big_blob_is_kept_even_when_the_driver_rebuilt_it_fast`,
  `the_oldest_blobs_make_room_for_a_new_one_within_the_budget`,
  `only_a_huge_whole_without_a_kept_blob_is_prewarmed`.
- `cargo clippy -p xcl --lib --release`: only the two pre-existing
  `approx_constant` errors (`gpu/dxil/lower_*.rs`) and pre-existing warnings;
  no new warning in the touched code.

## Expected next run

The 819 KB graphics PSOs log `GetCachedBlob ... returned N KB (hr 0x0)` and
`keeping ...` when first built, then `driver blob supplied` (~30 ms) instead of
`absent`; the huge compute `.chain.pso` files already written are loads
(~150 ms). Any remaining skip prints its size and reason, and the prewarm build
means a 25 s whole compile no longer has to finish before the 300 s cut.
