# Memory, VRAM and streaming — VItoriaBr / fxceless on 8 GB + 16 GB

Date: 2026-11-25. Scope: texture upload/refresh, levels-on-demand, card buffers,
staging pool, page mapping/remap, copy-back, UMA/shadow memory, Windows pagefile.
Sources: `D:\git\VItoriaBr` (baseline), `D:\git\fxceless-victory` (fork),
`D:\Gry\VItoriaBr-data\logs\*`, `D:\Gry\fxceless-data\logs\*`,
`benchmarks/`, `docs/EXPERIMENTS-2026-11-25.md`.

No game was launched and no main repo was modified for this document. Every
claim below is either a line of source, a line of a log, or a number already
measured by the operator/repo and cited as such.

## Streszczenie (PL)

- **Karta jest przeciążona**: proces trzyma 6,8–7,7 GB przy budżecie DXGI
  7 188 MB (95–107%), więc Windows zrzuca część VRAM do pamięci współdzielonej,
  a warstwa przebudowuje 5–7 GB tekstur na przebieg (fxceless, 300 s).
- **Największy koszt ramki, który da się usunąć ustawieniem**, to przeznaczony
  na streaming budżet: 250 ms (z „catchup” 750 ms) na klatkę plus do 1 500 ms
  dla „bake”. To nie GPU — to wątek nagrywający klatkę.
- **Propozycja**: zamrozić budżet streamingu (`STAGE_MS=24`, `STAGE_MB=64`,
  `CATCHUP=0`), sprawdzić `TEXTURE_NO_WAIT=1`, a VRAM (`LEVELS_ON_DEMAND`,
  budżet tekstur) potraktować jako **warunek kolejnych bramek**, nie jako
  dzisiejszy zysk. 30 fps to nadal nie wynik tej zmiany.

## 1. The budget this layer actually has

From `game-run.log` (VItoriaBr, RTX 4060 Laptop):

```
video memory as the system counts it, right before the swap chain is made:
  the card's own:        budget 7188 MB, in use 45 MB, 3722 MB could still be reserved
  the PC's shared:       budget 7189 MB, in use 192 MB, 3722 MB could still be reserved
```

So the process budget is **7 188 MB (7.02 GiB)**, not 8 192 MB. Every threshold
below is a percentage of that number:

| Threshold | Bytes | Where | Effect |
|---|---:|---|---|
| texture queue line (`VICTORY_TEXTURE_ROOM_PERCENT`, 90) | 6 469 MB | `resource.rs:1504` | no new host copy of an index texture |
| **VRAM pressure cliff 85%** | **6 110 MB** | `host.rs:134` | sweep idle timer drops to **1 000 ms** |
| moderate 75% | 5 391 MB | `host.rs:136` | sweep idle timer 2 500 ms |
| calm | — | `host.rs:139` | sweep idle timer 5 000 ms |
| card-buffer reserve | 1 024 MB − made | `shadow.rs:158`, `shadow.rs:208` | kept free for title-buffer copies |
| render-target reserve | 3 072 MB − made | `resource.rs:1464` | kept free for targets |

Measured operator states: baseline **6.8–7.7 GB (95–107%)**; E2b
(`VICTORY_TEXTURE_BUDGET_MB=4096`, `VICTORY_CARD_BUFFERS_MB=768`) **5.3 GB
(74%)**. Both are in `docs/EXPERIMENTS-2026-11-25.md`.

Two consequences that the rest of this document builds on:

1. At 95–107% the card is **over its budget**: Windows demotes part of the
   process's VRAM to the shared (system-memory) segment, and every read of a
   demoted byte goes over PCIe. `resource.rs:1413-1414` names this failure
   mode: "Past the budget the system moves the card's memory into the PC's,
   which ended runs 20 and 24."
2. The sweep needs **4 frames and** `idle_ms` (`host.rs:103-107`,
   `resource.rs:1757`). At 0.6–1 fps **4 frames is 4–6 s**, so the 4-frame floor
   is the active policy and the 1 000 ms timer is inert. At ≥4 fps the 1 s
   timer becomes the active policy — a cliff that waits exactly at gates
   G2–G4. `docs/EXPERIMENTS-2026-11-25.md` (E2b: VRAM −2.2 GB, fps unchanged)
   is consistent with this: at 1 fps, freeing VRAM could not change eviction.

## 2. Where the memory goes — code map

| Path | Code | What it holds | Measured / documented size |
|---|---|---|---|
| Title texture host copies (index + placed) | `resource.rs:1296` `hosted()`, `resource.rs:1416` `room()` | D3D12 textures in VRAM; one per address+desc ever viewed | 4.3–5.5 GB of host copies on 8 GB (`tiles.rs:9-14`); 7.3 GB at the first world frame of run 193 |
| Levels-on-demand tiles | `tiles.rs:78` `wanted()`, `tiles.rs:154` `take()`, `tiles.rs:557` `UpdateTileMappings` | 64 MiB heaps of 64 KiB tiles; only mips the title mapped | saves 2.2–3.0 GB of 4.3–5.5 GB (run 189, `tiles.rs:9-14`) |
| Staging buffers | `texture.rs:105` `staging_buffer()`, `texture.rs:506` `let_go_idle()` | **system RAM**, one full-size linear copy per texture being detiled | 2 246 buffers / 2.1 GB at end of run 24 (`texture.rs:499-505`) |
| Title buffer copies (shadow) | `shadow.rs:28` `Shadow`, `shadow.rs:2289` `refresh()`, `shadow.rs:2339` `gpu_writes()` | PC memory by default; ≥1 MiB goes to VRAM (`shadow.rs:158`) | 190–330 MB of distinct ranges per list in run 69; 762 MB of copies in run 193 |
| Buffer copies in VRAM | `shadow.rs:247` `card_for()`, `shadow.rs:208` `card_room_kept()` | VRAM side + "before" twin (a copy shaders write costs 2×) | cap 1 024 MB, admission up to 97% of budget |
| Windows outside buffers | `shadow.rs:334` `window_card_for()` (`VICTORY_CARD_WINDOWS_MB`) | 4 MiB windows of title memory; default 0 = PC memory | 861 windows / 3.5 GB of shared memory in run 104 |
| Copy-back snapshots | `shadow.rs:2360` `writing()`, `shadow.rs:2478` `copy_back_with()` | per-copy `before` buffer + parallel compare | "~2.3 million page faults per world frame" (`shadow.rs:2358`); 42–70 MB fetched per frame (fxceless README) |
| Raw-address memory | `memory.rs:59` `COPIES = 1023`, `memory.rs:244` `ready()` | numbered copies of 4 MiB windows for shaders that use 40-bit addresses | **up to 4 GiB** of VRAM; every dispatch refreshes *all* numbered copies (`memory.rs:42-45`) |
| In-place title memory | `inplace.rs:88` `level()`, `inplace.rs:30-36` | D3D12 heap opened on the title's own pages — no copy | refused for the page pool; opening pins pages in RAM |
| Remap / page watching | `watch.rs:387` `writes()`, `watch.rs:1028` `title_memory_remapped()`, `host.rs:6849` `Step::Texture` | write-watch journal + 64 KiB guards; detile at submit | refresh waits measured at 2 566 ms for 110 MB in run 93 (`texture.rs:391-397`) |

## 3. Top 3 VRAM/streaming costs

Ranking: measured ms per frame, restricted to terms this document owns (texture
staging, detile, VRAM residency) and to levers not already in the relay/queue
path. Two larger measured terms — title-memory copies **250–760 ms** and
copy-back **93–443 ms** — are real but belong to the relay/queue work that is
already switched on (`VICTORY_RELAY=2`, `VICTORY_COPY_PLAIN=1`,
`VICTORY_QUEUE2=1`). They are listed in §4 so nothing is hidden, not re-counted
here.

### C1 — The staging pass is a fixed 250 ms (750 ms) budget on the frame's recording thread

**Files:** `draw.rs:1759` `heap_textures()`, `draw.rs:1769-1775`
(`VICTORY_TEXTURE_STAGE_MB`, 192), `draw.rs:1850-1859`
(`VICTORY_TEXTURE_STAGE_MS`, 250; `VICTORY_TEXTURE_CATCHUP` ×3),
`draw.rs:88-94` (`VICTORY_EARLY_TEXTURES_MS = 12`,
`VICTORY_BAKE_TEXTURES_MS = 1500`, 2 GiB), `draw.rs:1816`
(`texture_slots_due(frame, 4096)`), `draw.rs:1875` (the break).

The pass runs from the draw recording path (call sites `draw.rs:1563` and
`draw.rs:1663`, the latter for early/bake draws), i.e. **on the thread that
records the frame**, before the frame's command lists are submitted. Its
limits are:

```rust
per_frame = VICTORY_TEXTURE_STAGE_MB (192 MB)      // draw.rs:1774
span      = VICTORY_TEXTURE_STAGE_MS (250 ms)      // draw.rs:1852
if due.len() >= 1024 && VICTORY_TEXTURE_CATCHUP != "0" {
    (per_frame, span) = (per_frame * 3, span * 3);  // 576 MB, 750 ms — draw.rs:1859
}
```

With the operator's **~23 000 slots waiting**, `due.len() >= 1024` is true every
frame, so every frame is a catch-up frame: up to **750 ms** of staging on the
recording thread, before a single draw is submitted. 750 ms is 22.5× the whole
30 fps budget. Two hidden budgets sit on top of it:

- `VICTORY_EARLY_TEXTURES_MS = 12` — the first draw of every frame with a view
  heap gets 12 ms (64 MB) of staging (`draw.rs:1631-1632`).
- `VICTORY_BAKE_TEXTURES_MS = 1500` — **every** draw whose pixel shader is one
  of the title's bake programs may stage textures up to 1 500 ms / 2 GiB per
  frame (`draw.rs:1628-1630`). This is the only budget in the layer the size of
  a whole measured frame, and it overrides the per-frame span
  (`draw.rs:1863-1868`).

The normal pass runs once a frame (`draw.rs:1423-1427` guards it on the frame
counter), so its span is effectively per frame; the early/bake passes are
**additive** to it within the same frame (up to 750 + 1 500 ms of staging).

Evidence:

- fxceless README run 270: "the texture pass **fills its 250 ms time budget
  either way**, so frames are no shorter"; 1.36 ms per upload with the staging
  pool, 1.92 ms without → ~130–180 uploads inside 250 ms, ~390–550 inside the
  750 ms catch-up budget, per frame.
- VItoriaBr source: "making and staging 192 MB of textures took **1.6–2.2 s of
  each of the world's first twenty frames** (run 20)" (`draw.rs:1846-1849`),
  and "22 000 slots due, 2–3 minutes of black surfaces at 192 MB a frame"
  (`draw.rs:1854-1855`).
- The frame line separates it: `heap buffers {picked} passes {picked_ms} ms` is
  "both parts" — the texture pass (`HEAP_PASS_PARTS[0]`, `draw.rs:1564`) and
  the buffer-view pass (`host.rs:7499-7503`). The measured 950–2 708 ms heap
  pass therefore *contains* up to 750 ms of texture staging; the rest is the
  buffer-view/descriptor pass (Agent A's slice), not this one.
- Per-frame cost is the line `the pass over the heap per frame ... ms in its
  pass over textures picked by index`. In the menu-only run it read `0.0 ms`
  because the world was not loaded — it must be read in the 3D scene.

This is also why VItoriaBr and the fxceless fork both sit at ~1 fps despite
different VRAM totals: the pass is budget-bound, not workload-bound.

### C2 — Every upload detiles the whole texture, then drops the staging buffer

**Files:** `texture.rs:989-1112` `refresh_timed()`, `texture.rs:1144-1190`
`detile()`, `texture.rs:105-128` `staging_buffer()`, `draw.rs:2078`
`texture::unstage(resource)`, `texture.rs:1214` `fingerprint()`.

`refresh_timed` asks the write watch for the texture's pages
(`watch::writes`, `watch.rs:387`). If any page was written, it reads the **whole
texture** (the full console layout) and `detile` walks **every mip and slice**
into the staging buffer. The module says it outright: "shortcut: a change
detiles the whole texture, not the pages written" (`texture.rs:13`). There is no
per-page or per-mip invalidation.

Then, for a texture picked by index, `draw.rs:2078` drops the staging buffer
immediately after the upload (`texture::unstage`), so the next upload makes a
new one, reads the whole texture again and detiles it again. Only tabled
textures keep theirs (`draw.rs:2059-2066`).

Evidence:

- `texture.rs:391-397`: "the frame line's `textures` is **seconds a frame** in
  some runs … (2 566 ms for 110 MB in run 93, 314 ms for 132 MB in run 91)",
  i.e. 23 ms/MB in the bad case, 2.4 ms/MB in the good one — both far above the
  0.3 ms/MB in-place read (`texture.rs:434-439`).
- Operator: `textures 100–270 ms` per frame in the 3D scene.
- VItoriaBr `game-stderr.log`: 201 "changed after its upload" re-uploads,
  **83.8 MB**, one of them a **8 294 400-byte (3840×2160)** texture
  (`slot=11676 address=0xb4d000000 bytes=8294400 frames_after_upload=576`).
  A single 8 MB re-detile is ~19 ms in the good case and ~190 ms in the run-93
  case. The log prints the first 200 such events and every 1 000th
  (`draw.rs:1909`), and `changed` ended at 201 — so 201 is the true count for
  that run, not a truncated one.
- RAM side: 2 246 staging buffers / 2.1 GB kept at the end of run 24
  (`texture.rs:499-505`), and the staging pool only reuses buffers ≤8 MiB
  (`texture.rs:89`), so the big ones are made and freed every time.

### C3 — VRAM residency: over budget, a 4-frame eviction floor, and 5–7 GB rebuilt per run

**Files:** `resource.rs:1755-1811` (`let_go_idle`), `host.rs:123-141`
(`vram_idle_ms`), `host.rs:184-205` (`sweep`), `resource.rs:1416-1444` (`room`),
`resource.rs:1464-1476` (`targets_room_kept`), `shadow.rs:267`.

`let_go_idle` drops the host copy of a texture the title fills when nothing
names it for `idle_ms` **and** `IDLE_FRAMES = 4` frames
(`resource.rs:1757`, `1762`). `idle_ms` is
`vram_idle_ms(CurrentUsage, Budget)`: **1 000 ms at ≥85%**, 2 500 ms at ≥75%,
5 000 ms otherwise; both conditions must hold (`host.rs:103-107`). The next use
makes the host copy anew, makes a staging buffer, detiles the whole texture and
uploads it again.

At 0.6–1 fps, 4 frames = 4–6 s, so the 4-frame floor binds and the pressure
timer is inert; at ≥4 fps the 1 s timer binds. That makes the VRAM work a
**gate prerequisite**, not a today-fix. It still costs today in the tail:

- fxceless log, the "last 96 things done" ring printed at device removal
  (`fxceless-data/logs/game-stderr.log`, 21:11:34): in the 58.6 s the ring
  covers, **39 sweeps, 12 762 host copies of textures let go, 2 828 MiB**, plus
  **122 windows, 600 MiB**. Sizes range from 18 to 1 083 copies per sweep; some
  sweeps are 400–700 copies and 80–130 MiB. Example line:
  `sweep: 514 host copies of textures the title fills let go (128128 KiB), each
  held by its title texture alone (no list, no slot)`.
- fxceless README runs 269–272: "Textures made again after being let go for
  lack of room: **5.1 and 6.9 GB** in the runs without [buffer copies on the
  card], **1.9 and 1.1 GB** with." And: "That is what the long frames are made
  of." Long frames (>250 ms) fell from 21–26% of the last stretch to 4–6%.
- The tail arithmetic: long frames averaged 391 ms with **204 uploads**; at
  1.36–1.92 ms per upload that is 280–390 ms, i.e. the long frame *is* the
  uploads (`fxceless` README run 270).

So C3 does not set the median frame; it sets the tail, and it will set the
median as soon as frames get short enough for the 1 s timer to engage.

### What the operator's own logs add

- `VItoriaBr-data/logs/game-stderr.log` (176 s, 242 lines): **201** of them are
  "a texture picked by index changed after its upload with nothing to tell of
  it: uploaded again" — the slot's 48 KiB fingerprint changed after the upload
  (`draw.rs:1897-1899`), which the layer's own comment attributes to a title
  that fills a texture's memory after its view was written, with no descriptor
  write and nothing from the runtime to tell of it (`draw.rs:1889-1896`); the
  texture was re-detiled. 112 distinct slots, 45 056 B to 8 294 400 B.
- `fxceless-data/logs/game-stderr.log`: 202 of the same warning, then
  `ERROR victory_gpu::host: host GPU device removed after 1 submissions sent
  ahead`, with `last: Some(Placed(false, [3, 32761, 0, 0, 1024, 0, 1024,
  589825, 71, 1, 0, 261, 3145728, 32761]))` — a 1024×1024, format 71,
  3 145 728-byte view, taken while textures picked by index were made ready
  (`draw.rs:2036-2045`). Device loss is Agent J's; the memory relevance is that
  it happened **inside the texture pass**, i.e. on the path this document
  proposes to shorten.

## 4. Terms this document does not own (measured, larger than C2/C3)

**Title-memory copies — 250–760 ms/frame.** `Shadow::refresh` (`shadow.rs:2289`)
brings every range a submission reads up to date from title memory; the
submission-time steps run in `host.rs:6784-6858`. Already addressed by
`VICTORY_RELAY=2` (landing on its own thread), `VICTORY_COPY_PLAIN=1` (in-place
copies, ~12 400/frame, 290 MB/frame, README), `VICTORY_WIDE_REFRESH=1`
(parallel refresh; fxceless tried the `alt` variant and saw no gain, README)
and `VICTORY_JOIN_COPIES=1`. If this remains the largest term after C1 is fixed,
the structural answer is in-place title memory (`VICTORY_INPLACE`), which the
fxceless probe refuses for the page pool and the highest-traffic buffer
(`inplace.rs:30-36`) — Agent B's territory.

**Copy-back — 93–443 ms/frame.** `shadow.rs:2478` compares every declared write
range with the snapshot by 64 KiB piece — "gigabytes a frame, bound by memory
speed" (`shadow.rs:2494-2495`) — then merges only the differing stretches.
Repo run 86 reports 78 ms; fxceless fetches 42–70 MB/frame. Addressed by
`VICTORY_RELAY=2`, `VICTORY_QUEUE2=1`, `VICTORY_WIDE_BACK=1`; `VICTORY_CARD_FETCH_INFLIGHT=1`
cuts copy-back to ~45 ms but pushes GPU time to 200–330 ms and loses net fps
(README) — keep it off.

**Raw-address copies (`memory.rs`).** Up to 1 023 numbered copies; a copy is a
4 MiB window *or the whole buffer it found*, and `ready()` refreshes **all**
numbered copies on every dispatch that uses raw addresses (`memory.rs:42-45`,
`memory.rs:303-311`). Latent 1–4 GiB of VRAM and an O(copies × buffer)
per-dispatch refresh. Dormant while `VICTORY_BVH_BUILDER` is off; do not turn
the builder on without capping `COPIES` and refreshing only the named window.

**Levels-on-demand.** `tiles.rs:41-44`: "tiles are not taken back while the
host copy lives" — so it is the sweep (C3) that returns VRAM, not the tile
allocator. Saves 2.2–3.0 GB on 8 GB, costs one `UpdateTileMappings` per upload
(`tiles.rs:557`) and a 64 MiB-granular heap pool (`tiles.rs:59-64`). Its own
status line reports `MB of the card not allocated for levels the title does not
hold` (`tiles.rs:695-715`) — gate on that number and on the µs of
`UpdateTileMappings`.

**Staging pool.** On by default; only ≤8 MiB buffers are reused
(`texture.rs:89`). fxceless measured 128.9 page faults/upload with it vs 132.7
without, and 1.36 vs 1.92 ms/upload, with no frame-time gain because the pass
fills its budget either way (README run 270). Keep it on; it is not a lever.

**Windows / buffer copies on the card.** `VICTORY_CARD_WINDOWS_MB` (default 0)
moved 355 allocator windows / 1 356 MB into VRAM and cut texture re-makes from
5.1/6.9 GB to 1.9/1.1 GB and long frames from 21–26% to 4–6% (fxceless runs
271–272, on a 10.2 GB card). The mechanism is not explained ("why fewer
textures are let go is not known"), and on 8 GB it competes with textures
directly. Treat as a separate arm, not part of the safe set.

**Pagefile / RAM.** The process commits far more than 16 GB: fxceless measured
**~24 GB commit, 16 GB resident, on a 32 GB PC**, with the PC's shared segment
at **5.7 GB** (README run 272; 3.8 GB with upload heaps in run 273). On this
16 GB laptop every byte above ~14 GB is pagefile-backed, and a pagefile-backed
title read is a disk fault on the frame thread. The layer already reacts:
`ram_idle_ms` drops the staging cache from 10 s to **2 s** when free RAM is
under 2 GiB (`host.rs:146-161`), i.e. the churn of C2 accelerates exactly when
RAM is tight. Current machine: pagefile 21.8 GB, commit free 12.1 GB idle,
2.7 GB free RAM idle (`docs/PERF-DIAGNOSIS-2026-11-25.md` §09). A fixed 32 GB
pagefile on D: prevents error 1455; it does not make pagefile reads cheap.

## 5. Proposed change for 8 GB VRAM / 16 GB RAM

**One mechanism: bound the texture-staging work a frame may do.** It is the
only per-frame cost in this document that is a fixed, self-imposed budget on
the frame's recording thread, and it is set 7.5–45× above the 33.3 ms target.

### Set B (safe; only texture *latency*, no content change)

```powershell
$env:VICTORY_TEXTURE_CATCHUP   = "0"    # no ×3 burst while the backlog is large
$env:VICTORY_TEXTURE_STAGE_MS  = "24"   # pass may take 24 ms of the frame (was 250, 750 with catchup)
$env:VICTORY_TEXTURE_STAGE_MB  = "64"   # and 64 MB (was 192, 576 with catchup)
$env:VICTORY_TEXTURE_NO_WAIT   = "1"    # refreshes never wait for a remap; kernel copy instead
$env:VICTORY_STAGING_POOL      = "1"    # default; keep (cheaper uploads, fewer faults)
```

Keep the E2b VRAM settings as they are (`VICTORY_TEXTURE_BUDGET_MB=4096`,
`VICTORY_CARD_BUFFERS_MB=768`) so the arm changes one mechanism only.

**Expected effect.** Up to ~726 ms of the frame's staging budget disappears
(750 → 24 ms). Against the measured 1 112–1 253 ms (E2b) that is roughly
**0.4–0.9 s/frame (1.1–2.5 fps)**, depending on how much of the 726 ms is
actually spent each frame — a move toward G1, not G4. It does **not** touch
copies (250–760 ms), copy-back (93–443 ms) or the buffer-view/descriptor pass.

**Cost / risk.** Textures appear later: the backlog of ~23 000 slots drains at
~12–18 uploads/frame by the time budget (more only if the textures are small)
instead of ~390–550, so black/untextured surfaces persist for ~15–40 minutes
(it depends on the new frame rate) instead of ~1 minute at 1.5 s/frame. No
incorrect pixels, no device loss, no format change. `VICTORY_TEXTURE_NO_WAIT=1` can skip a refresh for one frame
when the runtime is remapping (`texture.rs:1037-1044`) — visual latency only;
the README measured `textures` 900–3 700 ms → 6–25 ms with it, and no device
loss.

**Rollback.** The whole set is environment-only, per process: close the game,
unset the five variables (or start a new shell). Nothing is written to disk.

### Set C (diagnostic only — attribution, not a default)

Add:

```powershell
$env:VICTORY_BAKE_TEXTURES_MS  = "0"    # a bake draw may no longer stage 1 500 ms / 2 GiB
$env:VICTORY_EARLY_TEXTURES_MS = "0"    # nor the first draw of a frame 12 ms
```

**Risk:** the bake comment is explicit — "What a bake may read must be there
now" (`draw.rs:1629`). Zeroing it can bake *untextured* decorations into a
render target, which is a persistent visual defect, not just late pop-in. Use
it only to measure whether the bake budget is spent at all, with a screenshot
check, and never promote it without a fix that prefetches bake textures off the
frame thread.

### What to do *after* the 3 runs (separate arms, one at a time)

1. `VICTORY_LEVELS_ON_DEMAND=1` — the only setting that removes 2.2–3.0 GB of
   VRAM need without dropping texels (`tiles.rs:9-14`). Gate on the tile status
   line and on `UpdateTileMappings` µs, not on fps alone.
2. `VICTORY_TEXTURE_BUDGET_MB=3584` — keeps `used` comfortably under the 75%
   cliff (5 391 MB) so that, once frames are short, the sweep stays at 2.5 s
   instead of 1 s. E2b's 4 096 MB left it at 74%, one percent from the cliff.
3. `VICTORY_CARD_WINDOWS_MB=512` — measured to cut re-makes 3–6× on a 10 GB
   card; unexplained, and it costs VRAM. Only after (1) has freed some.

## 6. Three-run test plan

Same save, same scene, same camera, the same 120 s stretch in the opening
cutscene's first room, `VICTORY_LOG=info`, `VICTORY_FRAME_LOG=1`,
`VICTORY_CARD_ACCOUNTING=1`. Three arms, one launch each; then the winning arm
twice more for p50/p95 (baseline discipline in `tools/bench/README.md`).

| Arm | Settings | Question it answers |
|---|---|---|
| **A** | E2b preset (4096 / 768, 720p, ambient 0, levels on demand, late wait 3, wide back, back own view, loop 256) | what a frame costs today |
| **B** | A + Set B (§5) | does the staging budget own the frame? |
| **C** | B + Set C (bake/early 0) | is the 1 500 ms bake budget being spent? |

### Commands

```powershell
# 0. one-time: fixed 32 GB pagefile on D:, High Performance power plan, close
#    everything else. Verify (locale-independent):
Get-CimInstance Win32_OperatingSystem | Select-Object FreePhysicalMemory,TotalVisibleMemorySize
Get-CimInstance Win32_PageFileUsage | Select-Object Name,AllocatedBaseSize,CurrentUsage

# 1. arm A — the current best preset (example: VItoriaBr)
$env:VICTORY_LOG="info"; $env:VICTORY_FRAME_LOG="1"; $env:VICTORY_CARD_ACCOUNTING="1"
$env:VICTORY_TEXTURE_BUDGET_MB="4096"; $env:VICTORY_CARD_BUFFERS_MB="768"
$env:VICTORY_LEVELS_ON_DEMAND="1"; $env:VICTORY_LATE_WAIT="3"
$env:VICTORY_WIDE_BACK="1"; $env:VICTORY_BACK_OWN_VIEW="1"; $env:VICTORY_SHADER_LOOP_LIMIT="256"
$env:VICTORY_DISPLAY_MODE="1280x720"; $env:VICTORY_AMBIENT="0"
Remove-Item Env:VICTORY_TEXTURE_CATCHUP,Env:VICTORY_TEXTURE_STAGE_MS,Env:VICTORY_TEXTURE_STAGE_MB,Env:VICTORY_TEXTURE_NO_WAIT,Env:VICTORY_STAGING_POOL,Env:VICTORY_BAKE_TEXTURES_MS,Env:VICTORY_EARLY_TEXTURES_MS -ErrorAction SilentlyContinue
cd D:\git\VItoriaBr
.\target\release\victory.exe run --execute "D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\game_scarlett_master.exe" 2> "D:\Gry\VItoriaBr-data\logs\e2-mem-A.log"

# 2. arm B — add the staging bounds
$env:VICTORY_TEXTURE_CATCHUP="0"; $env:VICTORY_TEXTURE_STAGE_MS="24"; $env:VICTORY_TEXTURE_STAGE_MB="64"
$env:VICTORY_TEXTURE_NO_WAIT="1"; $env:VICTORY_STAGING_POOL="1"
.\target\release\victory.exe run --execute "D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\game_scarlett_master.exe" 2> "D:\Gry\VItoriaBr-data\logs\e2-mem-B.log"

# 3. arm C — attribution only
$env:VICTORY_BAKE_TEXTURES_MS="0"; $env:VICTORY_EARLY_TEXTURES_MS="0"
.\target\release\victory.exe run --execute "D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\game_scarlett_master.exe" 2> "D:\Gry\VItoriaBr-data\logs\e2-mem-C.log"
```

Run VRAM/GPU sampling in a second window during each arm:

```powershell
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader -lms 1000 |
  Tee-Object -FilePath "D:\Gry\VItoriaBr-data\logs\e2-mem-B-vram.csv"
```

### Analysis

```powershell
cd D:\git\gta6-30fps
python tools\bench\parse_victory_log.py "D:\Gry\VItoriaBr-data\logs\e2-mem-A.log" --min-draws 500 --min-ms 100 --csv benchmarks\e2-mem-A.csv
python tools\bench\parse_victory_log.py "D:\Gry\VItoriaBr-data\logs\e2-mem-B.log" --min-draws 500 --min-ms 100 --csv benchmarks\e2-mem-B.csv
python tools\bench\parse_victory_log.py "D:\Gry\VItoriaBr-data\logs\e2-mem-C.log" --min-draws 500 --min-ms 100 --csv benchmarks\e2-mem-C.csv

# the terms this document is about, per arm
Select-String -Path "D:\Gry\VItoriaBr-data\logs\e2-mem-B.log" `
  -Pattern 'pass over the heap|textures picked by index:|card accounting|textures with levels on demand|sweep:' |
  ForEach-Object { $_.Line } | Set-Content "D:\Gry\VItoriaBr-data\logs\e2-mem-B-memory.txt"
```

Also record, from the frame log's `usual frame` / `long frame` lines:
`textures: refresh X ms, N uploads`, `copies X ms N MB`,
`copy-back X ms N MB`, `faults: N page`, `MB free`.

### Promotion gate

Promote Set B only if **all** hold:

1. p50 ms/frame improves by ≥15% in arm B vs A, and the direction repeats in
   the two confirmation runs;
2. `the pass over the heap ... ms in its pass over textures picked by index`
   drops by roughly the budget delta;
3. no device removal, no new `ERROR` line, and a screenshot of the same spot
   shows no new missing surfaces beyond slower pop-in;
4. VRAM peak does not rise (it should not: Set B uploads less);
5. rollback is the env unset (it is).

If arm C ≫ arm B, the bake budget is real and the next step is code, not
settings: prefetch bake textures on a worker before the bake draw, or cap
`VICTORY_BAKE_TEXTURES_MS` at ~250 for playability and accept the bake risk
only with a visual diff.

## 7. What not to do (measured dead ends)

| Attempt | Result | Source |
|---|---|---|
| Lower texture budget to 4 GB / card buffers 768 MB | VRAM 7.5 → 5.3 GB, fps still 1 | E2b, `docs/EXPERIMENTS-2026-11-25.md` |
| `VICTORY_TEXTURE_COPY=1` (read every texture through the kernel) | 0.6 ms/MB vs 0.3 in place; both runs lost the device | `texture.rs:431-443` |
| `VICTORY_CARD_FETCH_INFLIGHT=1` | copy-back 162 → 45 ms, GPU 50–65 → 200–330 ms, net fps loss | README |
| `VICTORY_STAGING_POOL` with 128 MB kept | no frame-time gain; the pass fills its budget anyway | fxceless run 270 |
| `VICTORY_INPLACE=2` (title buffers in place) | both opening paths pin title pages; the highest-traffic buffer cannot be opened | fxceless README, `inplace.rs:30-36` |
| `VICTORY_TEXTURE_SWEEP=0` (never evict) | untested here, but at 95–107% it removes the only valve; the card overshoots into shared memory | `resource.rs:1753` |
| Pagefile as a fix | prevents 1455, but pagefile-backed texture reads are disk faults on the frame thread | §4 |

## 8. Open questions and handoffs

- **Agent A (descriptor/draw):** the heap pass is `HEAP_PASS_PARTS[0]` (texture
  staging, up to 750 ms) + the buffer-view pass. After Set B, re-measure the
  split; the remaining heap cost is the descriptor/table pass, not this one.
- **Agent D (bench):** the frame log's `usual frame` line is the only place
  that separates `textures` (detile) from the staging pass; the per-second line
  merges both into `preparing`. A dedicated column for `HEAP_PASS_PARTS[0]`
  would make this doc's gate mechanical.
- **Agent J (TDR):** fxceless lost the device inside the texture pass
  (`draw.rs:2036-2045`, `Placed(false, …, 3145728)`). Shortening the pass may
  change the failure rate; the DRED build is the instrument.
- **Open:** why the fxceless card-window runs cut texture re-makes 3–6× is not
  explained in the repo. Reproduce on 8 GB with 512 MB before trusting it.
- **Open:** `memory.rs` refreshes every numbered copy per dispatch; if the RT
  builder is ever enabled, this is a 4 GiB + O(copies) hazard and needs a
  dirty-window mask first.
- **Not this document:** shader/PSO warm-up (E1), submit/draw batching (E3),
  present (F), HLE (G), recompilation (H), assets (I), TDR (J).
