# Copy-loop A/B matrix — Kelvaroq/LNX mechanisms vs VItoriaBr-opt

Date: 2026-11-26. Scope: read-only analysis for the 16 GB RAM / 8 GB VRAM laptop
(RTX 4060 Laptop, 8,188 MiB, driver 617.14). The game was **not** launched for
this document (the running PID 21992 was not touched); `D:\git\VItoriaBr-opt`
was read only — no rebuild, no modification, no commit anywhere.

Sources actually read (Firecrawl is not registered in this session; all web
fetches went through plain `webfetch` against `raw.githubusercontent.com`,
which worked, so no fallback was needed):

- Kelvaroq `README.md` and `documentation.md` (French), patches 0038–0048 as
  described there; branch/revision pinned to victory-fork `f85101b`.
- `D:\git\LNX-victory\README.md` (8 GB preset: relay=2, wide_back/refresh/merge,
  card_rehash_runs, join_copies, pipeline_wait_ms=50, texture_skip_mips,
  texture_no_wait, card_fetch_inflight=0, present_plane).
- Our docs: `PER-DRAW-COST.md`, `PERFORMANCE_BUDGET.md`, `STABILITY-TDR.md`,
  `EXPERIMENTS-2026-11-25.md`, `PERF-DIAGNOSIS-2026-11-25.md`.
- Logs (read-only): `safe-mem`, `fast`, `fast2`, `fast3`, `fast4` stderr/stdout,
  launchers `Launch-VItoriaBr-{SafeMem,Fast,Fast2,Fast3,Fast4}.ps1`,
  `...\data\7952987A\crashes.log`, and `victory.pdb` (symbol lookup only).
- Code read: `crates/victory-gpu/src/{host,queue,queue2,draw,watch,shadow,framelog}.rs`,
  `crates/victory-hle/src/modules/dstorage.rs`.

Streszczenie (PL): najlepszy zmierzony profil (Fast3) to 418–535 ms/klatkę;
klatka jest **CPU/submit-bound** — karta stoi bezczynnie ~1.0 s z 1.29 s, wątek
submission ma 0.77–1.15 s pracy, a licznik faultów pokazuje 300–700 tys. stron
na klatkę. Fast4 nie zmienił niczego: `VICTORY_JOIN_PARTS` **nie istnieje** w
naszym drzewie, więc jego „2.3 fps” to szum, a crash to wyścig DirectStorage z
remapem pamięci tytułu, nie ścieżka join. Sufit na 16 GB/8 GB to realnie
120–200 ms (5–8 fps) po przeniesieniu wszystkich wygranych z pętli kopiowania;
33 ms wymaga ścieżki natywnej.

## 0. TL;DR

1. **Fast4's independent variable is empty.** `VICTORY_JOIN_PARTS` has zero
   occurrences in `D:\git\VItoriaBr-opt` (checked across `crates/**/*.rs`); it
   is also absent from the binary's env-name registry. Fast4's launcher is
   Fast3 plus a variable nothing reads. 2.3 vs 2.4 fps is noise; the measured
   436 vs 418 ms is inside the scene-to-scene spread of the same profile.
2. **Fast4's only recorded crash is a DirectStorage inflate writing into
   title memory whose page was gone at that instant** (the reporter's later
   `VirtualQuery` says `read-write` — the same TOCTOU our crash notes
   already describe). The stack symbolizes to `dstorage.rs:511 →
   dstorage.rs:918 → zlib-rs inflate`, destination `0x54311ac00` (the
   range of the other title VAs in `crashes.log`), 5 s after launch, at the
   menu (frame 64, 96 draws). It is the non-page destination path, which has
   no retry loop. No copy path is on the stack; the leading *amplifier* is
   `relay=2`, whose weaker barrier lets the title recycle the destination
   (§5). The independent triage in `CRASH-TRIAGE-INT3-AV.md` agrees.
3. **The int3 at `image+0x5149aec` is not a fast run.** The last recorded one
   in `crashes.log` is 13:19 local, PID 29876, before any Fast launch; the
   fast logs contain no `0x80000003`. That class is the title's own fixed-size
   pool assert, documented earlier and unrelated to the copy loop.
4. **The present call is where the wait surfaces; copy/watch work is what it
   waits for.**
   A representative Fast3 frame (log line, 2215 draws): 1288 ms total, present
   call 1270 ms of which 1162 ms is `lines and settling`; submit thread 1148 ms
   at work (preparing 515, copies 117 ms/68 MB, copy-back 137 ms/20 MB); card
   idle 1081 ms, 1020 ms "behind us"; title lists on the GPU only 343 ms;
   faults 528,619 page + 546 guard; disk 1,352 reads / 194 MB. Async present
   therefore moves p95 (the tail spent waiting) more than p50 (bounded by the
   submit thread's work).
5. **Kelvaroq's 2.35x came from mechanisms we do not have** (mesh amplification,
   wide card hash, ReBAR read-only copies), not from switch combinations we
   already run. Their async present fixed p95 (568→262 ms), not p50 (115.5→108.5).

## 1. Method — benchmark-methodology adapted to a switch matrix

`benchmark-methodology` is written for competitor scoring, so its letter is
adapted, its discipline is kept: **one evidence line per claim, no composite
score, asserted vs proven separated, calibrated across rows.**

Grading used per row (four dimensions, reported separately — never averaged):

| Dimension | Levels |
|---|---|
| Presence here | in tree + switch / in tree + code-only / absent |
| Evidence | **A** measured in this tree with logs · **B** measured elsewhere, same mechanism present · **C** projection from arithmetic |
| Risk class | `TDR` device hang/removal · `AV` access violation into title memory · `int3` title assert · `vis` picture/state only · `none` |
| Reversibility | env (one line) / code+flag / code only |

Calibration rules applied:

- Δms are quoted against **Fast3** (operator 418 ms; framelog best-12 median
  379 ms at 1,574 draws; worst logged 1612 ms). The scene varies ±2x between
  runs, so a Δ under ~8% is not a result.
- The operator (title bar) figures and the framelog medians disagree for
  Fast2/Fast3 (see §2). Both are reported; neither is silently preferred.
- Every "expected" number states its arithmetic basis. A range with no basis
  is marked `unknown` rather than guessed.

## 2. Baseline reconciliation

Operator figures are the agreed baselines; the framelog column is the same
logs re-parsed with `tools/bench/parse_frame_cost.py` plus a tail-12 extract.

| Run | Delta vs previous | Operator fps / ms | Framelog 3D p50 (draws) | Tail-12 p50 | Recorded crash |
|---|---|---|---|---|---|
| SafeMem | relay/late/join/async/queue2 **off**, no UNCAP/BORDERLESS/REFRESH | 0.7 / 1385 | 2630 ms (4410) | 2743 ms (4989) | none in log |
| Fast | +`RELAY=2 LATE_WAIT=2 JOIN_COPIES=1 WIDE_REFRESH/MERGE=1 CARD_REHASH_RUNS=1 ASYNC_SUBMIT=1` +`UNCAP BORDERLESS REFRESH=120` | 1.5–1.7 / 630–670 | 664 ms (2896) | 507 ms (1137) | none in log |
| Fast2 | +`JOIN_PARTS=1` (**no-op**) | 2.0 / 507–535 | 757 ms (1698) | 552 ms (1368) | none in log |
| Fast3 | +`QUEUE2=1` | 2.4 / 418 | 692 ms (2218) | 719 ms (1972) | none in log |
| Fast4 | +`JOIN_PARTS=8` (**no-op**) | 2.3 / 436 | — (log overwritten) | — | `0xc0000005` @`victory.exe+0x66cfae`, 5 s, menu; crash log `victory-20261126-184738-8164` |

Honest reading: **only SafeMem → Fast is unambiguous** (2.6 s → 0.5–0.7 s, and
the whole relay/late bundle is implicated, not one switch). Fast → Fast2 →
Fast3 is *directionally* consistent with the operator readings but the logs'
draw counts differ (2,896 / 1,698 / 2,218) and the p50s overlap; treat the
"2.4 fps" as the best observed stretch, not as a repeatable 90 ms step.
Fast2's delta was a no-op, which is itself the cleanest evidence that these
runs are noise-limited at ±10%: a switch that does nothing "gained" 0.4 fps in
the operator's reading.

Why the framelog and the operator differ: the framelog prints a row every few
frames including streaming/loading stretches; the title bar is read later, in
steady state, and at a different draw count. Fixed-camera, draw-matched
extraction is a prerequisite for the §4 runs.

## 3. Matrix — switch or patch, mechanism, Δms, risk, evidence, rollback

### 3a. Present in our tree

Δ is against Fast3 (418 ms operator; framelog medians 379–719 ms depending on the
stretch, 1.4–2.2k draws) unless stated. "Bundle" = measured only as part of the SafeMem→Fast step.

| # | Switch / patch | Mechanism (code, one line) | Measured or expected ms saved | Risk | Evidence | Rollback |
|---|---|---|---|---|---|---|
| A1 | `VICTORY_INDIRECT_WINDOW=1` (off by default) | Up to 64 consecutive mesh records clamped in one pass into the list's scratch buffer; following draws read them with no pass and no barrier — `draw.rs:143-190`, `WINDOW_MOST=64` | **−60…−150 expected.** Basis: 3.4–4.1k mesh records/frame × 14–16 µs of clamp (our own timing, `draw.rs` run 79) + two full drains per record; Kelvaroq removed the same per-record clamp for −78 ms of a 198 ms median (0041) | `vis` low-med (tail records holding garbage charge budget; `bound_ahead` leaves them empty) | B+ — our code timings + Kelvaroq 0041 (198.3→119.8, GPU busy 78→35%) | unset env |
| A2 | `VICTORY_LATE_WAIT=3` | Present stops being a settle point; back-buffer copy becomes a flight of its own; swapchain presents behind it — `host.rs:2070-2086` | **−20…−80 p50, −300…−600 p95 expected.** Basis: present call 1270 ms of a 1288 ms frame (1162 ms `lines and settling`); long-frame present p50 606 ms | `TDR` med (deepest async stage; title told fences late; highest in runs that also use UNCAP/REFRESH=120) | B — Kelvaroq 0046/0048: p50 115.5→108.5, **p95 568→262**, heavy frames 1022→1648 | `=2` |
| A3 | `VICTORY_ASYNC_PRESENT=1` (gated: needs A2 + `ASYNC_SUBMIT=1`) | Present returns at once, held behind the queue's line; one present in the air (`PRESENTS_HELD`) — `queue.rs` `present_behind`/`send_behind` | **−0…−40 p50, −100…−400 p95.** Basis: capped by the submit thread's 770–1150 ms work/frame; it removes the *wait*, not the work | `TDR`/`AV` low-med; saved/listed frames fall back to the old path, so screenshots still work | B — Kelvaroq 0046/0048 (same mechanism, 2 frames ahead; ours holds 1) | unset env |
| A4 | `VICTORY_LATE_WAIT=1` (remove-test of stage 2) | Stage 2 diffs the page against the copy to merge title bytes under flights' writes (`host.rs:2047-2068`); stage 1 settles at the present instead | **−80…+80, unknown sign.** Probe of the 300–700k guard faults/frame and 2.7 s kernel time — if stage 2 owns them, 1 wins | `none`; more settling, slower tail | C+ — our framelog fault counters + code path | `=2` |
| A5 | `VICTORY_BACK_OWN_VIEW=1` | What shaders wrote goes back into title view memory through our own view — `shadow::put_back_own` | **−20…−60.** Basis: copy-back 85–137 ms/frame, 7–20 MB | `AV` low-med (writes title view memory — same hazard family as §5) | A− (our framelog line), untested alone | unset env |
| A6 | `VICTORY_JOIN_COPIES=1` | Back-to-back replay copies into the same destination become one step — `host.rs:3517-3545` | Bundle; **−5…−25 expected** (copies 117–217 ms/frame) | `AV` low | B (bundle + STABILITY: 10,171 copies joined) | `=0` |
| A7 | `VICTORY_CARD_REHASH_RUNS=1` | Re-hash only touching pieces, once — `host.rs` card passes | **−5…−30** (GPU passes; 130 hash passes over 301 pieces + 59 compares/frame) | `TDR` low | A (per-frame line) + B (Kelvaroq hash finding) | `=0` |
| A8 | `VICTORY_WIDE_REFRESH=1`, `WIDE_MERGE=1` | Submission refreshes/merges across threads | Bundle only | CPU contention on 8C/16T (title job system) | B− | `=0` |
| A9 | `VICTORY_WIDE_BACK=0` (remove-test) | Snapshot+compare across threads; **on by default here**, launcher's `=1` is redundant | ±0 — verifies a default, not a win | `none` | A (code default) | re-enable (default) |
| A10 | `VICTORY_COPY_PLAIN=1` | `rep movsb` in-process copies, read-fault replay (`plaincopy.rs`) | Bundle; **4–8 ms + >1 s spikes removed.** Basis: 0.06 ms/MB × 68–135 MB; Kelvaroq 0044: 7–12% at ≥5k draws | `AV` low | B — Kelvaroq 0044 (0.34→0.28 ms/MB; spikes gone) | `=0` |
| A11 | `VICTORY_CARD_BUFFERS_MIN_MB` / `CARD_BUFFERS_MB=512` | Shader-written buffers get a card copy; compare/fetch on the card | **Already active** — 301 pieces in card memory, 130 hash passes/frame. Verify by accounting line, do not A/B blind | VRAM (112–273 MB free) | A | unchanged |
| A12 | `VICTORY_QUEUE2=1 → 3` | bit 1 = fetch lane (10 jobs/19.2 MB/2.7 ms); bit 2 = CPU-changed bytes up-lane (**0 jobs today**) | ≈0 — the up lane has no traffic in this scene | `TDR` low | A (per-frame queue2 line) | `=1` |
| A13 | `VICTORY_CARD_FETCH_INFLIGHT=1` | Fetch inside the flight | **Do not enable**: LNX measured GPU ~600 ms vs ~100 ms (triples GPU time) | `TDR` high | B — LNX README | `=0` |
| A14 | `VICTORY_TEXTURE_STAGE_MS/MB` 24/64 → 48/128 | Larger per-frame staging budget | 0…±, moves streaming cost between frames | VRAM | B — Agent E (759–1561 → 13.8–29.5 ms once bounded) | `24`/`64` |
| A15 | `VICTORY_RELAY=2` | Land flights on their own thread; wait only for flights declaring the memory read (`host.rs:2125-2140`) | **Bundle: 1385 → ~650 ms** (with A6–A8, A10, A16, UNCAP) | `TDR` low-med today (H5 rejected; no reset in 4.5–6.5 min 3D); `AV` — the destination-vacate window points here, so test `RELAY=1` | A | `=0` (or `=1` to test the barrier) |
| A16 | `VICTORY_ASYNC_SUBMIT=1` | Prepare and send on `victory-submit` (`queue.rs:behind`) | Bundle | `AV` med (title frees list memory while our thread works; refs held) | A + code | `=0` |

Notes that prevent operator error:
- `VICTORY_LATE_WAITS=1` (plural) is a different switch: it sleeps to the next
  tick in `frame.rs`. Nothing in this matrix sets it.
- `WIDE_BACK` is on unless `=0`; the Fast launcher's `=1` changes nothing.
- `QUEUE2=3` (Kelvaroq's default) is *not* better here today: the up lane that
  bit 2 opens carried 0 jobs in Fast3.

### 3b. Kelvaroq mechanisms absent from our tree (port queue, not env)

| # | Patch | Mechanism | Expected here | Risk | Evidence | Rollback |
|---|---|---|---|---|---|---|
| B1 | 0041 mesh launch | GPU amplification stage reads and bounds the indirect record inside the draw, then launches groups; no clamp pass, no waits between mesh draws | **−60…−120** (our clamp windows are the substitute; their p50 198.3→119.8, i.e. −78) | `TDR`/`vis` high (new DXIL stage, 4-byte payload rule, silent wrong draws) | B (their A/B, RTX 5080) | code flag |
| B2 | 0041b wide card hash | 64 KiB block hashed by 64 threads instead of one thread chaining 4,096 dependent reads | −10…−40 (ours is already 130 passes/301 pieces, not 500–1,400) | low | B (their hash-only run: 140–156 ms at 5.5–6k draws) | code flag |
| B3 | 0038 ReBAR read-only copies | Windows and small buffers the GPU only reads live in CPU-visible VRAM (`VICTORY_REBAR_COPIES_MB`, 2048) | **unknown magnitude, structural.** Removes PCIe reads per draw of ~3.3 GB of windows | VRAM med-high on 8 GB | B (mechanism only, no isolated A/B) | code flag |
| B4 | 0045 watch once per reservation | One `GetWriteWatch` per reservation and submission, reused; no ask on already-guarded view memory; small reads grouped per page | **−20…−60** at matched draws (their 129.2→109.5, −15%) | low | B | code flag |
| B5 | lazy landing | Copy GPU writes back only on a CPU fault, not every submission (~50 ms/frame of their relay thread) | −40…−80 | `AV`/correctness high | B (their plan, not shipped) | code flag |
| B6 | 2 frames ahead | Kelvaroq presents up to 2 frames ahead; ours holds 1 | −0…−30 beyond A3 | `TDR` med | B | code flag |
| B7 | unified memory | Share the title's pages with the GPU (copies 100 MB → <8 MB/frame) | **The only order-of-magnitude fix** — and out of reach on 16 GB RAM (§6) | `AV` very high | B (their new layer, in testing) | n/a |

## 4. Ranked next five A/B runs

One independent variable each, run against **Fast3** as the base (relay=2,
late=2, join_copies=1, wide_refresh/merge=1, card_rehash_runs=1, async_submit=1,
queue2=1, copy_plain=1, texture no-wait, 720p, uncap, ambient 0). Five minutes
**in the world**, not five minutes from launch.

Run 0 (instrumentation, not an A/B, do it once): `VICTORY_PROFILE=1` for 5 min
to split `preparing` (515 ms) into texture staging / heap pass / clamp waits.
It changes timing; use it only to choose where to look, never as a measurement.

| Rank | Run (IV) | Base | Hypothesis and falsifier | Expected | Risk | Rollback |
|---|---|---|---|---|---|---|
| 1 | `VICTORY_INDIRECT_WINDOW=1` | Fast3 | The per-record clamp + two full drains is the largest **removable** CPU-side item. Falsified if clamp counters fall but p50 moves <3% ⇒ `preparing` is staging/faults, not clamp | −60…−150 ms | `vis` low-med | unset |
| 2 | `VICTORY_LATE_WAIT=3` | Fast3 | Present settling is 1.16 s of the worst frame and 606 ms p50 in long frames. Falsified if p50 regresses >5% (then the submit thread, not present, is the wall) | −20…−80 p50 / −300…−600 p95 | `TDR` med | `=2` |
| 3 | `VICTORY_ASYNC_PRESENT=1` | Run 2 config (stage 3 is mandatory) | With present off the critical path, the frame should collapse to submit-thread work (~770 ms worst). Falsified if p50 is unchanged ⇒ submit work is the ceiling | −0…−40 p50 / −100…−400 p95 | `TDR`/`AV` low-med | unset |
| 4 | `VICTORY_LATE_WAIT=1` | Fast3 | Stage 2's page-diff merge owns the 300–700k guard faults and 2.7 s kernel/frame. Falsified if faults and kernel time are flat ⇒ the faults are the copy path itself | −80…+80 (probe) | `none` | `=2` |
| 5 | `VICTORY_BACK_OWN_VIEW=1` | Fast3 | Copy-back (85–137 ms, 7–20 MB) shrinks when our own view is used. Falsified if copy-back line is flat | −20…−60 ms | `AV` low-med | unset |

Ranking rationale: 1 and 2 attack the two largest logged line items that are
still switchable; 3 is the only way to bank 2's p95 gain (and is Kelvaroq's
shipped pair); 4 is a cheap, high-information remove-test of the one mechanism
whose cost we have never measured; 5 is the last low-risk copy-path switch with
a logged millisecond figure. Not ranked: `QUEUE2=3` (no traffic), `WIDE_*`
(bundle, no isolated figure), `CARD_FETCH_INFLIGHT` (known regression),
`TEXTURE_STAGE_*` (moves cost, does not remove it), any `JOIN_PARTS` value
(does not exist).

**Crash A/B, separate from the five** (do it before or after, not inside a
timed arm): `VICTORY_RELAY=1` against `RELAY=2`, same Fast3 base, 5 min each,
same crash markers. It is the only test that can confirm or clear the
destination-vacate amplifier named in §5; if both arms crash at a similar
rate, stop switch-hunting and patch the non-page destination path.

### Protocol for each run (5 minutes, comparable)

```powershell
# base = D:\Gry\VItoriaBr-data\Launch-VItoriaBr-Fast3.ps1, one line changed:
$env:VICTORY_INDIRECT_WINDOW = '1'      # run 1 only
# keep the launcher's keys: 25:Enter,45:Y,58:Enter,72:Enter,90:Enter
# then, in the world, the same walk for every arm:
$env:VICTORY_KEYS = '25:Enter,45:Y,58:Enter,72:Enter,90:Enter,120:w,5:s,60:a,5:d,120:w'
# screenshot at t=4:30 with the usual tool (screen-*.png).
# VICTORY_CAPTURE takes a FOLDER, not a flag; saved/listed frames present the
# old way, so do not leave it set for a timed arm:
#   $env:VICTORY_CAPTURE = 'D:\Gry\VItoriaBr-data\capture'
```

- **Window**: start the clock when the title reports draws > 300 and keeps them;
  stop at +300 s. Same save, same spawn, same walk.
- **Screenshot**: one at 4:30 to `D:\Gry\VItoriaBr-data\logs\`, plus a second at
  0:30 for the loading comparison. Accept the arm only if the picture is
  identical outside known artifacts (textures left out are logged).
- **Log**: full stderr to `...\logs\ab-<name>-stderr.log`; require the framelog
  to be continuous (a gap > 30 s at a live process is a hang, per
  `STABILITY-TDR.md`).
- **Crash markers** (any of these ends the run and rejects the arm):
  `unhandled exception`, `0x887A0005`, `0x887A0007`, `0x80000003`, `int3`,
  `dstorage: retries used up`, `driver's errors`, `no free dynamic descriptor
  slots`, and any new `*.crash.log`.
- **Metrics extracted**: p50/p95 of 3D ms/frame at matched draws (±10%),
  present split (`in the present call`, `lines and settling`), submit thread
  (`preparing`, `copies`, `copy-back`), card idle and "behind us", guard/page
  faults, `N MB free`, clamp count, dropped draws.
- **Gate**: accept if p50 improves ≥8% at matched draws **and** p95 does not
  worsen **and** no new crash class; promote only after a repeat run; otherwise
  roll back the single line.
- **VRAM/RAM guard**: abort at VRAM free ≤ 500 MB for 3 samples, or commit
  free < 1 GB (16 GB box; Fast3 already logged 112–273 MB free).

## 5. The Fast4 crash — hypothesis with evidence

### What actually happened

| Time (local) | Event | Evidence |
|---|---|---|
| 18:47:33.03 | launch, image mapped, DirectStorage opens 12 archive files, 16 workers | `fast4-stderr.log` |
| 18:47:37.96 | frame 64 presented, 96 draws (menu), host compute pipelines being built | same |
| 18:47:37.98 | `0xc0000005` write `0x54311ac00` at `victory.exe+0x66cfae`; then unhandled → Breakpad | same + `crashes.log:1004` |
| earlier Fast4 launch (17:32–17:47) | operator read 2.3 fps / 436 ms; its log was deleted by the launcher at 18:47:33 | launcher `Remove-Item`; no surviving file |

`crashes.log` has **no** `0x80000003` after 13:19 local (PID 29876, three writes),
and none of the five fast logs contains `int3`. The last int3 is therefore not a
Fast4 event; if a Fast4 run did assert at 17:3x, it left no record.

### Symbolized stack (victory.pdb, line tables)

| Frame | Address | Symbolized to |
|---|---|---|
| #0 | `victory.exe+0x66cfae` | `zlib-rs-0.6.8/src/inflate.rs:1901` |
| #1 | `+0x66ef9a` | `zlib-rs-0.6.8/src/inflate.rs:2401` |
| #2 | `+0x660757` | `zlib-rs-0.6.8/src/stable.rs:158` |
| #3 | `+0xd6442` | `std/thread/local.rs:427` (the thread-local inflater) |
| #4 | `+0x100bd0` | **`victory-hle/src/modules/dstorage.rs:918`** — `into_destination(... inflate(&source, out))` |
| #5 | `+0x10450f` | **`dstorage.rs:511`** — worker loop `execute(&job.request)` |
| #6–#8 | — | unwinder artifacts (`sys/backtrace.rs`, `ops/function.rs`, `sys/thread/windows.rs`) |

### Mechanism (code)

`into_destination` (`dstorage.rs:1065`) for a non-page destination does:

1. `kernel_will_write(destination, len)` — opens the guarded blocks;
2. `slice::from_raw_parts_mut(destination, len)` — a raw slice **into title VA**;
3. `fill(out)` — here, zlib inflate writes straight into title memory.

If the title frees or re-maps that block between (1) and (3), the page is
`MEM_RESERVE` and the write is an unhandled AV. The **page-destination** path
has a retry loop for exactly this (`dstorage.rs:1114-1160`,
`VICTORY_DSTORAGE_RETRIES`, 12 tries ≈ 0.9 s, `xmem::write_physical`); the
non-page path has no retry — it writes in place. The crash is that gap, not a
copy-loop ordering bug.

### Which fast path is most likely?

Two questions, two answers — they are not the same question.

**1. Which fast path is on this stack?** None. The faulting code is the
DirectStorage worker's inflate (`dstorage.rs:511` -> `dstorage.rs:918` ->
`zlib-rs`), not relay / late / queue2 / async / join. `join` is not even a
candidate, and the Fast3 -> Fast4 delta proves it:

- `Select-String` over `crates/**/*.rs` for `JOIN_PARTS`/`join_parts`: **0 hits**;
- the source's env-name registry (the `"VICTORY_*"` literals) lists
  `VICTORY_JOIN_COPIES` but no `VICTORY_JOIN_PARTS`, and the built
  `victory.exe` is from this tree;
- every other switch is byte-identical between `Launch-VItoriaBr-Fast3.ps1` and
  `Launch-VItoriaBr-Fast4.ps1`.

So the operator's 436 vs 418 ms and 2.3 vs 2.4 fps are noise, and no part of
the crash can be charged to a `JOIN_PARTS` value.

**2. Which switch let the destination be vacated while the inflate was still
writing?** Here the evidence points at **`relay=2` (`relay_exact`)**, with
`async_submit` second: `relay_exact` removes the "wait for everything" barrier
for a submission that reads title memory a flight may write
(`host.rs:2125-2140`), so the title can run ahead and free or recycle a
destination that the I/O still owns. That is the mechanism the independent
triage in `CRASH-TRIAGE-INT3-AV.md` reaches as well (its verdict 4:
"mechanistically strong for `relay=2` ... not yet A/B-proven"). The earlier H5
rejection of the relay family concerned **device removal**, a different
symptom; it does not clear relay here.

Correlated factors that widen the window regardless of which switch is blamed:
1,352-2,109 DirectStorage reads per frame (194-312 MB) with 16 workers at
0.3-2.4 fps, `TEXTURE_NO_WAIT=1` (a texture may keep its image during a remap
attempt), `LEVELS_ON_DEMAND=1` (VA recycling), and 112-273 MB VRAM free. The
5 s timing (menu, first bulk load) fits an I/O-completion-vs-remap race, not a
steady-state draw path.

**What to disable first, in order**

1. `VICTORY_RELAY=1` — keeps the late stage and the async-present gate as they
   are, but restores "wait for everything" for submissions that read title
   memory. One line, and it tests the barrier hypothesis directly.
2. `VICTORY_TEXTURE_NO_WAIT=0` — if the crash recurs at `RELAY=1`; expect
   slower streaming and more missing textures (the log counts them).
3. `VICTORY_LEVELS_ON_DEMAND=0` — last, because it costs VRAM we do not have.
4. Only if a **second** crash shows a *layer* write (not zlib), disable
   `VICTORY_LATE_WAIT=2` first: it is the one fast path that writes title bytes
   under in-flight shader writes (`host.rs:3457`). This stack does not
   implicate it.


**Code fix that removes the class** (not an env): fill into a scratch buffer,
then write with `xmem::write_physical` + the existing retry loop, or wrap the
destination in the guard/VEH path the page route uses. Cost: one copy of the
inflated block (~64 KiB–1 MB); benefit: no fatal AV on a recycled destination,
and a `retries` counter we can watch.

**int3 class (for the record)**: `image+0x5149aec` is the title's own assert on
a fixed-size lock-free pool (22,500 × 224 B, `image+0xa9ec938`), reached when
deferred deletions stall at low frame rates; it was measured at 503 s in the
earlier VItoriaBr-tdr work and is speed-coupled, not switch-coupled. If it
recurs, run `VICTORY_POOL_WATCH=ga9ec938` and look at frees, not at the copy
loop.

## 6. Honest ceiling — 16 GB RAM / 8 GB VRAM

Measured components (Fast3 long frame, 2,215 draws, 1,288 ms):

- GPU work of the title's own lists: **343 ms** (338 lists). Our send/hash
  11.6–27.7 ms, compare 8.4–29.1 ms.
- Card idle: **1,081 ms, of which 1,020 ms "behind us"** (waiting for CPU).
- Submit thread: **1,148 ms** at work (preparing 515, copies 117/68 MB,
  copy-back 137/20 MB, waiting for card 34).
- Recording, all threads: 2,933 ms in 17,911 calls (title's own 8-thread work).
- Faults: **528,619 page + 546 guard per frame**; process kernel 2,750 ms.
- Disk: 1,352 reads, 194 MB, 10,603 worker-ms per frame.
- VRAM free: 112–273 MB.

So the frame is not 33 ms away from a scheduling fix; it is dominated by
keeping two memories in sync — the same diagnosis Kelvaroq states ("about two
thirds of the frame"), just at 8 GB/16 GB instead of 16 GB/64 GB.

Projection (arithmetic, grade C, not a promise):

| Step | p50 | Basis |
|---|---|---|
| Fast3 today | 418–535 ms | measured |
| + A1…A5 accepted (all env wins) | ~300–380 ms | −60…−150 of clamp/present/copy-back |
| + B1 mesh launch, B2 wide hash | ~220–300 ms | their combined 0041+0041b was −40% at 4.5–6.4k draws |
| + B3 ReBAR copies, B4 watch-once | ~160–240 ms (4–6 fps) | −20…−60 each, both unmeasured here |
| + B5 lazy landing (if correct) | ~120–200 ms (5–8 fps) | −40…−80 |

**Ceiling: 8–10 fps is the optimistic case on this box; 5–8 fps is realistic**
at 720p and 1.5–2.2k draws. Two hard walls:

- **16 GB RAM.** Kelvaroq's own 36-minute playtest peaked at **15.5 GB** RSS on
  a 32 GB machine; their pre-unified build left ~19 GB behind per session. Any
  unified/shared-memory layer must map the title's whole footprint; on 16 GB
  with a 34–63 GB pagefile that is pagefile thrash. Note what the counters do
  and do not say: the 528k figure is guard-page faults from write watching, not
  pagefile faults, but the 2.7 s of kernel time and 194 MB/frame of streaming
  are the shape paging takes. Consequence: `TEXTURE_SKIP_MIPS`
  and `LEVELS_ON_DEMAND` stay permanently on, so the streaming churn (194 MB/
  frame) never goes away.
- **8 GB VRAM.** 112–273 MB free with 3 GB textures + 512 MB card buffers. There
  is no room to grow ReBAR read-only copies, mesh scratch, or more card pieces;
  every port in §3b must be budgeted against that headroom.

**What only the native replay can fix** (none of these is a switch):

1. **33 ms itself.** 30 fps at 3,850 draws = 8.65 µs/draw all-in; we are at
   ~200–350 µs/draw. That is 25–40x, and it is per-draw host work plus copies,
   not a missing optimization.
2. **64-lane compute on a 32-lane GPU.** 7 compute pipelines are refused today
   (forcing them to 32 lanes gives wrong results) — Kelvaroq is at the same wall.
3. **Ray tracing / BVH builder.** ~515 dropped draws per frame and black skin;
   DXR is implemented in Kelvaroq's test build, not in ours.
4. **Device methods 0x1c8 / 0x218.** 16,000+ pipeline calls a run go unimplemented.
5. **The ~1,420 remaining clamped non-mesh indirect calls** — mesh launch does
   not cover them.

## 7. Port queue after the five runs (ordered by expected gain / cost)

1. **B1 mesh launch (0041)** — the largest externally measured win (−40% median,
   GPU busy 78→35%); it also removes the clamp waits that A1 only groups.
2. **B3 ReBAR read-only copies (0038)** — structural; needs the VRAM budget work
   first (target ≤ 1 GB, not their 2 GB).
3. **B4 watch-once per reservation (0045)** — cheap, ~15% in their A/B, and it
   directly targets our 300–700k fault counter.
4. **B2 wide card hash (0041b)** — small, bounded, low risk; do it with B1.
5. **B5 lazy landing** — largest of the copy-back items, highest correctness
   risk; only after B4 shows how much of the fault load is watch-related.
6. **B7 unified memory** — the real fix; impossible on 16 GB RAM, so keep it as
   the argument for a 32 GB/16 GB-VRAM machine, not as a task on this one.

## 8. What would falsify this matrix

- A1 < 3% with clamp counters falling ⇒ the clamp is not the wall; `preparing`
  is staging + faults, and the next run should be a staging A/B (A14), not
  more copy switches.
- A2 regresses p50 > 5% ⇒ present settling was hiding submit-thread cost; skip
  A3 and go straight to splitting submit work (code).
- A3 changes nothing ⇒ the submit thread is the hard ceiling at ~770 ms; the
  only remaining env lever is A1, everything else is a port.
- A4 leaves faults at 300k+ ⇒ the faults are the copy path, not stage 2's merge;
  B4/B5 become the priority.
- A5 shows copy-back flat ⇒ the copy-back line was measuring fence time, not
  copy work; remove A5 from the queue.
- `RELAY=1` reproduces the dstorage AV at a similar rate ⇒ the weaker barrier
  is not the amplifier; the destination was vacated by title-side reuse and
  the only fix is the code change in §5.
- A second crash with the same `dstorage` stack after `TEXTURE_NO_WAIT=0` ⇒
  stop switch-hunting; patch the non-page destination path (§5) before any
  further perf run.
