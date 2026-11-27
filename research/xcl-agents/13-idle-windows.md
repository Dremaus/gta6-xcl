# 13 — Idle windows: the title parks OUTSIDE the frame loop (H2), memory is innocent (H1 rejected)

Run `xcl-lockhart-200952`, 600 s, no crash (ended by `XCL_RUN_SECONDS`), 4775 presents (7.96 fps avg).
Log: `%LOCALAPPDATA%\XCL\RockstarGamesInc.28872443D20A7\logs\xcl.log` (23 135 lines).
**REA not applicable** per `rea-evidence.md` §3: claims here rest on the complete XCL source at `7318cf60` + the run log, not on a source-less binary.

## 1. Timeline of idle buckets — one contiguous terminal stall, not periodic

The orchestrator's 227 = buckets with 0 presents. Of those, 11 still show submits/draws (t=94.1, 124.1, 162.1–178.4 — the dying tail). Fully-zero buckets: **216**, in **3 contiguous windows**:

| window | t (s) | length | what |
|---|---|---|---|
| W0 | 2.0 – 10.0 | 8 s | boot before first PresentX |
| W1 | 34.0 | 2 s | single boot-phase blip |
| W2 | **180.4 – 598.6** | **418 s (70 % of run)** | terminal stall |

Present cadence into W2: 124–125/bucket (≈62 fps) t=38–82 → decays 89→71→37 → 60/bucket (30 fps) t=96–108 → 15–46/bucket t=110–160 → **dies**. A repeating pattern would scream timeout loop; this is a monotonic decay into one permanent park.

## 2. What happens inside W2 — evidence table

| probe (t=180.4–598.6) | observed | reading |
|---|---|---|
| `memory:` progression | commit = **23372 MB in 416 s, only 2 distinct values** (23372/23434); non-local pinned 4411; target pages pinned 2758 | **no paging at all → H1 dead** |
| DirectStorage (activity counters) | 4 buckets with `DSreq=1` (t=182/192/222/254), **zero after t=254** | loader/streaming idle, not starved |
| `driver compile` | 0 lines (last at t=175.5) | compiles were fixed by the blob cache, gone |
| `[STUB]` first-call, `[WARN]`, `[ERROR]` | **0 lines inside W2** | no unimplemented-method hit logged at the wall |
| `compute split` summary | frozen at `71/742/27` from t=180.0 to t=600 | zero GPU work issued |
| `translated as MS`, `two-pass DispatchMesh`, `Wait64BitValueX` | 0 (last at t=165.1 / 161.2) | render pipeline fully quiet |
| frame-loop counters | 0 submits, 0 frame-event waits, 0 statistics | title not even waiting on present/queue |
| xapu Opus decoder (thread 5660) | counts **grow** 9179→16520 packets until **t=297**, then stop | process alive; audio drains, then parks too |
| `XUser: token` network worker | **#11 at t=390.2 inside W2**: `POST …CreateTicketXbl3 — none: no Xbox Live (0x80072EFD)` | a title-side thread is ALIVE and retrying auth during the stall |
| GameInput DS4 pairs | 838 lines, exactly **1 pair/s**, same cadence during the healthy 125 fps phase (166 pairs before t=180) | constant background, uncorrelated with the stall |

Auth-retry rhythm: token #0–#10 every 14–44 s from t=22.5 to **t=163.9** — then presents decay to zero at t≈180 (226 s until the lone #11). The stall begins at the last visible online-gate failure.

## 3. DualShock 4 churn — symptom, not wall

`crates/xcl/src/hle/playstation.rs`: `pad()` spawns one XCL-internal reader thread (25860 in the log) unless `XCL_PLAYSTATION_PAD=0` (`v.trim() != "0"`, line 40; README:182). `reader()` sleeps **1 s** per scan — matching the measured 1.0 s period (the orchestrator's 0.4 s read is not in this log). It opens the HID path, first `ReadFile` fails immediately, logs read+disconnected within 1 ms, and **`STATE` is never set to `Some`** — the title never actually receives a pad from this path. Work is on XCL's own thread with microsecond mutex ops; it cannot park a title thread. `XCL_PLAYSTATION_PAD=0` only silences 838 log lines. The one in-window input event, `gamepad buttons 0x2 pressed for the first time` (t=200.4, `gameinput.rs:306-325` poll path), confirms host input still flowed while the title did not poll it.

## 4. Memory vs the 8 GiB title budget

Title memory (8192 MiB, `MicrosoftGame.Config`, `config.rs:20`) is a console-side budget; the 23 372 MB `committed by the process` is the **host** commit (XCL address space: PC-side copies, UMA windows, sparse pools 4736 MB/3179 mapped — `kernelx.rs:347` notes a retail-game fallback above the 4 GiB windows). Progression: 3665→14771 (t=22)→18283 (t=42, stable 40 s)→19662 (t=102)→21127 (t=162)→23372 (t=182)→**flat**. The loader finished allocating and then everything stopped; a starved-by-paging loader would show churn, not a 416 s frozen plateau. The mild pre-stall decay (t=82–160) cannot be fully attributed from this log, but it is not the wall.

## 5. Verdict

**H2, ~85 % confidence.** The title is blocked outside rendering; the frame loop never runs during W2 (0 submits even, so not queue backpressure or a present wait). Leading suspect: an **online/auth-gate park** (last failed `CreateTicketXbl3` at t=163.9 immediately precedes the death; a title network worker still wakes at t=390; audio drains until t=297 then the whole title sleeps). Ruled out: driver compiles, DS4 churn, memory/paging (H1), any logged stub/warn/error.

## 6. The ONE decisive experiment (next run)

`XCL_THREAD_DUMP_AT=s1,s2,…` exists and does exactly what's needed: at each listed second (since start) an `xcl-thread-dump` thread suspends **every** thread of the process and logs each RIP + unwound call stack (`host.rs:97-110` → `eh.rs:650+`). No dump was taken in this run. Three dumps inside W2 will name the wait the title threads sit on (WinHTTP recv vs. a console sync vs. something else) — turning 85 % into certainty.

```
$env:XCL_THREAD_DUMP_AT='210,330,450'   # three parks, all inside W2 (180.4–598.6)
$env:XCL_ACTIVITY='1'; $env:XCL_RUN_SECONDS='600'
$env:XCL_PLAYSTATION_PAD='0'            # optional: removes 838 noise lines, not causal
# same launcher invocation as xcl-lockhart-200952; new run tag xcl-lockhart-<HHMMSS>
```

Pass criterion: `grep 'thread dump|THREAD' xcl.log` shows ≥3 dumps; the title's main thread stack resolves to one blocked call site. If it resolves into WinHTTP/XUser waits, the fix direction is the offline-auth path (`netoff.rs`/`xgameruntime`), not memory or gamepad.
