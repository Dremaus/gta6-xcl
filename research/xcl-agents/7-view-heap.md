# 7 - View heap / descriptor slots on NVIDIA: VIctory vs XCL

VIctory clone `D:\git\victory-nvidia` (ideas only; GPL-3.0), XCL `D:\git\xcl` main `b75c0f30`.
Worktree `D:\git\xcl-wt-heap`, branch `agent/heap`, commit `f419d1e3`. No game launched.
Evidence: `...\logs\xcl.log` (2606 presents / 3000 s) and `xcl.prev.log`.

## 1. What VIctory-NVIDIA changed

Its host view heap is a fixed shader-visible pool, never the size the title asks.
- `crates/victory-gpu/src/descriptor/host.rs:1854,1860`: `PORTABLE_VIEWS = 1_000_000`
  (NVIDIA's cap), `UNCAPPED_VIEWS = 1<<21` (AMD).
- `:1889` `probe_view_limit()` tries 2^22 / 2^21 / 1M and tells the translator the last
  slot (`set_view_heap_limit`); shaders clamp indices at/above it to a null slot
  (`victory-shader/src/emit/shader.rs:151-168`, `lower.rs:1349`).
- `:2003-2008` `HostHeap::new` mirrors only `null - extra` title slots and warns
  `host view heap capped at {size}; views past it read a null slot` - the README's
  "NVIDIA caps the view heap below what the title asks for".
- Per-draw tables use slots past the title's: `DYNAMIC = 1<<18` (`:1938`), up to 2^20 on
  AMD (`dynamic_slots`, `:1946`). Exhaustion refuses the table (`host.rs:2280`) and
  `draw.rs:1962` drops the draw - the actual "thousands of draws a frame were dropped".
- Repair is lifetime: `State::tables_done` (`draw.rs:581-597`), `Detached::release_tables`
  (`list.rs:278`) on GPU completion (`host.rs:5091,5571`), `settle_for_fence` (`:3397`).
  `docs/bug-journal.md:19`: 16 submissions pinned slots and exhausted the 262k pool.

Mechanism: one capped host heap + translator null clamp + dynamic slots returned when the
GPU is done. Views past the cap read null; only a failed per-draw table drops a draw.

## 2. XCL's equivalent (structurally different)

- `real.rs:1072-1125` `dev_create_descriptor_heap_x`: a view heap asks the PC for **2n**
  descriptors (SRV/UAV pair) and clears `SHADER_VISIBLE` when the shared heap exists: the
  title's heap is a CPU-only mirror. The log's "shader visible" is the title's request.
- `console_heap.rs:97,104,142,154-186`: one shared heap of
  `min(OPTIONS19 MaxViewDescriptorHeapSize, 1_000_000)`; `PAGE_SLOTS = 256`, 2 descriptors
  per slot, so **~500,000 view slots**. `page_of` (`:271`) / `reserve_global` (`:253`)
  place a page on first use; `unregister` (`:384`) returns pages.
- Shaders index only that heap; guard `gpu/dxil/lower_image.rs:18,28-36`
  (`tw0 < 999_999`) and `gpu/recomp/emit.rs:2655`.
- There is **no per-draw dynamic descriptor pool**: shaders read the title's T# table from
  UMA. Skips exist only for pipeline/bind failures (`bind.rs:49,287,299,555,603`);
  `bind.rs:62` prints `... draws with translated pipelines (X skipped, Y with PC
  pipelines) ...`.
- On overflow (`console_heap.rs:262`) main wrote `index = 2k` for an unplaced page
  (`slot`, `:460`): another heap's view, a memory-window raw UAV at 4..18 (with
  `XCL_HEAP_WINDOWS=1`), or a guard-rejected index at k >= 500k. Symptom: wrong/black
  textures or an NVIDIA hang, **not** a dropped draw.
- `XCL_HEAP_WINDOWS` binds UMA windows as UAVs at descriptors 4..19; it is not a view-heap knob (`pso.rs:110-119`, `real.rs:370-376`, `console_heap.rs:225-249`).

## 3. Can this title hit it? What the logs say

- `xcl.log:106` `one shader-visible PC heap of 1000000 view descriptors`.
- `xcl.log:107` the title's `1245184 view slots` heap was accepted as a 2,490,368-descriptor
  CPU-only mirror. A 1.245M-slot shader-visible heap cannot exist on NVIDIA; XCL never asks.
- No `the shared heap (1000000) is full` in either log.
- `xcl.log:26648` `12812 draws ... (0 skipped, 0 with PC pipelines), 8192 dispatches
  (0 skipped)`; `xcl.prev.log:20531` `20075 ... (0 skipped), 4096 ... (0 skipped)`.
- The 1:1 window is the loading screen: `xcl.prev.log:12.012` `55 presents, 55 draws,
  0 dispatches`; it becomes 10:1 by 36 s. The title had not submitted yet, not a drop.
- The stall is a fence cycle: `xcl.log:20780-20784` `Wait64BitValueX ... >= 0xa32 ...
  (prod=qNone/tySome(0); wait-before-signal)`. `0xa32` = 2610 vs 2606 presents: it waits
  for 4 presents that never reach the GPU; activity is then 0/0 for 2,900 s.

Verdict: XCL cannot hit the **same** shader-visible cap: it never creates a shader-visible
heap of the title's size. Its ceiling is 500k view slots (half VIctory's 1M), and neither
log reaches it. If the world touches >~1953 pages, `console_heap.rs:262` is the signal.

## 4. Decision and change

- `XCL_HEAP_WINDOWS=1` (with/without `XCL_UMA_WINDOWS=8|16`) does **not** address this.
- Applied the smallest clearly-correct fix `f419d1e3` (9 lines): an unplaced page's slots
  name the null SRV/UAV pair at 0/1 instead of `2k`; `census` agrees. It prevents the
  aliased view/hang if the heap fills; it changes no draw counts. `cargo check --release
  -p xcl --lib` passes (3 pre-existing warnings); 12 `console_heap` tests pass.
- Capacity, if the full warning appears: do not hand-raise `GLOBAL_MAX`. XCL's own
  `origin/nvidia-dev` has the series main lacks: `1088d4e0` (2^21 + null fill),
  `23336dd5` (null fallback), `02a834a3` (50/75/90% log), `f93c9cbc`, `09cf0e3d`.
  1.245M x 2 / 1M = 2.49x (upstream says 2.56x). Merge those; 2^21 needs its guard/null fill.

## 5. A/B verification

VIctory (the fix removes these):
```
WARN  host view heap capped at <size>; views past it read a null slot
WARN  no free dynamic descriptor slots: a table is not made
once  a draw whose descriptor table found no free slots is dropped
```
After: none of the three; draws per frame rise from ~1 to hundreds.

XCL has no descriptor-drop counter, so the proof is the skip field:
```
A (main b75c0f30):
INFO  console descriptor heaps: one shader-visible PC heap of 1000000 view descriptors
INFO  D3D12.X: console code so far: 12812 draws ... (0 skipped, 0 with PC pipelines), 8192 dispatches (0 skipped)
      (no "the shared heap (1000000) is full" line)
B (only if A logs the full warning; after merging 1088d4e0 + 02a834a3):
INFO  console descriptor heaps: one shader-visible PC heap of 2097152 view descriptors
INFO  console descriptor heaps: the shared heap is past 50 % full: N of its 2097152 descriptors in use, M pages placed
INFO  D3D12.X: console code so far: ... (0 skipped, ...)
```
Keep `0 skipped` / `0 with PC pipelines`; rising `activity (2 s): ... draws` after the load screen is the title rendering, not a view-heap proof.
