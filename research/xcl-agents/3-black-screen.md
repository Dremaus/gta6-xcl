# 3 — Black world at XCL HEAD 8b957bec: diagnosis
Scope: HEAD 8b957bec + local patches, read-only; no code changed, nothing launched. The supplied
log/report are an earlier 8 GB run (RTX 4060 Laptop, 512 MB UMA, 11.1 GB sparse) that ended at
t=169.8 s in E_OUTOFMEMORY (real.rs:3413) with a bright loading dump; the black run is not in it.
## Verdict (ranked)

1. **The world NGG pipelines never exist.** `translated_mesh_stream_once` refuses a console MS alone
   in the AS slot (real.rs:6214-6222). The log has 40 such refusals at t=42.7-44.6 s; `report.json`
   `d3d12.translation_errors` has exactly those 40, `translated_pipelines=21`, `failed_pipelines=0`
   (the refusal never reaches `note_fallback`, real.rs:137-138, 3751). The first hash is the one named
   in upstream #541; PR 2057 reaches the world grey with the same 40 refusals. No mesh PSO -> no world.
2. **Even translated, HEAD cannot execute them.** Two-pass MS/GS PSOs are registered
   (real.rs:5800-5829, 6185-6191) but only consumed by skip paths: bind.rs:294-308
   (ExecuteIndirect) and 549-563 (Draw*). Nothing dispatches `TwoPassPso.compute` or fills its record
   buffer. `DispatchMesh` is not hooked (command-list table real.rs:975-1044; only 129->127,
   real.rs:7229), so the PC method runs the pass-through MS over an unfilled buffer. Upstream #2092 is
   exactly this path; porting #541 alone builds pipelines that HEAD still refuses to draw.
3. **The 1:1:0 black state is the title's placeholder frame, not a world through ExecuteIndirect.**
   In the same log, t=30-42 s shows 80-125 presents/2 s, 1 draw/present, 0 dispatches and every dump
   0 of 518400 lit — before world data. Its load frames are 1:1:1 (t=68 s); world load is 100-400
   draws/2 s + dispatches (t=92-122 s). The counters also hide skipped draws and DispatchMesh (Q1),
   so this pattern cannot be this title's world path.
4. **Composite/plane ambiguity.** With 2-plane PresentX the `frame` dump is the 4 K swapchain
   composite (present.rs:1123-1129), not plane 0. In the log plane 0 is 1920x1080 and plane 1
   3840x2160 (t=26.5 s); an opaque plane 1 or compositor error can black the output while plane 0 draws.
5. **VRAM.** The supplied run dies of video-memory exhaustion (real.rs:3413, vram.rs:521). If the
   black run is also 8 GB, world pages never arrive and the title keeps presenting the placeholder.
   Fences/missing methods/async have no positive evidence (Q2.5-7).
## Q1 — what the counters mean; 1 draw/present proves nothing

- `present::activity()` = (PresentX, ExecuteCommandLists), not draws (present.rs:303-305). `PRESENTS`
  increments in `present_x_frame` (present.rs:117) before `present_now`'s early returns.
- `bind::activity()` returns only `DRAWS`/`DISPATCHES` (bind.rs:42-52); it omits `DRAWS_SKIPPED`
  (bind.rs:287, 299, 555, 603) and `DRAWS_PC` (565). `DRAWS`++ at 598; **one ExecuteIndirect counts
  as one draw** at bind.rs:351 regardless of `max_count`; `DISPATCHES`++ at 890.
- PC-vtable `cl_draw_instanced`/`cl_execute_indirect` count nothing (real.rs:7107-7135); console-list
  replay counts only its own dispatches (console_list.rs:916), not bind's.
- **DispatchMesh is uncounted and untraced**: no command-list hook (real.rs:975-1044). 0 draws +
  0 dispatches is fully compatible with thousands of DispatchMesh calls.
- Hence 1 draw/present fits one indirect draw emitting N GPU draws, one fullscreen composite, one real
  draw with every world draw skipped, or an invisible DispatchMesh world. Not proof either way.
## Q2 — XCL-side conditions that can leave the title black

1. AS-slot MS refusal: real.rs:6218-6222; path 6930-6943. With `XCL_ASYNC_PSO=0` it is synchronous;
   with async on it still returns E_INVALIDARG because the refusal precedes any DXC miss, so `attempt`
   is not deferred. `failed_pipelines` stays 0 (only driver fallbacks count, real.rs:3751).
2. AS and MS both present refused (real.rs:6228-6235); MS translation failures (incomplete pso.rs:1118-1122,
   no NGG variant 1137, unknown MS interface 1138) -> E_INVALIDARG real.rs:6245-6252; legacy GS pairing
   real.rs:6305-6355 (E_INVALIDARG 6344/6348/6351), pso.rs:1220-1239.
3. Two-pass execution missing: verdict 2; `TwoPassPso` has no non-skip consumer.
4. Rect lists: bind.rs:433-483; a failed expansion draws only 3 vertices (496-500) = half rects;
   generated GS pso.rs:1244-1250; fallbacks real.rs:5267-5274, 6457-6465. Missing geometry, not black.
5. Async/lazy/preload: pso_async.rs:265-267 (ASYNC=0 inline), 1051-1139 (resolve/stand-in), 499-557
   (preload only warms `used`). They change timing, not whether an AS-slot PSO exists.
6. Missing D3D12.X methods: `called_stubs` #126/#142/#75 once per present, stubbed S_OK (real.rs:807-814);
   #131/#132 (console cache flushes; PR 2057 makes them UAV barriers) only 4 calls. Low, but a per-frame
   flush stub would break GPU-written indirect arguments.
7. Fences/present: 0 timed-out frame waits and 0 unflipped stats in every activity line (detail with
   XCL_TRACE_FRAME_EVENTS=1, frame.rs:353-357); present early-outs present.rs:1036/1071/1083-1093 can
   drop a present while PRESENTS counted it, but the frame dump proves present_now ran; show_compiling
   (433-467) cannot show an inline compile under ASYNC=0. VRAM: real.rs:3413, vram.rs:521.
## Q3 — cheapest decisive experiment (one run, same save/state)

```
XCL_ASYNC_PSO=0 XCL_PSO_PRELOAD=0 XCL_ACTIVITY=1 XCL_TRACE_FRAME=1 XCL_FRAME_DUMP=60 XCL_PSO_TRACE=1 XCL_TRACE_UI_ANY=1 XCL_TRACE_FRAME_EVENTS=1
```

Keep ASYNC/PRELOAD as in the black run (they do not affect the refusal); do not add PR 2057's
translation envs. `XCL_GPU_PROFILE` does not exist in HEAD (only in PR 2057's #1766), so do not plan
around it. `XCL_FRAME_DUMP=60` dumps ~1/s (`=1` means every 120th, present.rs:1247-1257); add
`XCL_FRAME_DUMP_FULL=1` for one full 4 K frame. Run 60 s past the point the world should appear.

1. `WARN ... mesh pipeline with its MS <hash> in the AS slot - refused` (real.rs:6220): count,
   `report.json d3d12.translation_errors`, `translated_pipelines`, `background_pipelines`; grep
   `pipeline from the console MS in two passes` (real.rs:6191) — is any mesh PSO built at all?
2. After 300 presents, one `frame trace: draws vs <vs> ps <ps> into (w,h,fmt,samples)[ (presented)] ...`
   per distinct draw (bind.rs:654-660). One line into the presented target = no world draws; many lines
   into offscreen 1080p/4 K targets = world draws exist.
3. `frame trace: PresentX #n of <plane0> ... - rt binds A, UAV B, copy C, clears D; most used ...`
   (present.rs:175): A=0,D>0 -> only clears its presented plane; C>0 -> copies a scene in; A>0 -> draws in.
4. `present: frame <n> ... N of 518400 samples not black` vs `present: rt <n> ...` (present.rs:1453-1462;
   rt is the busiest RT, 1178-1198). frame 0 + rt lit -> presentation/composite; both 0 -> no world pixels.
5. Skips: `draw with two-pass ... skipped` (bind.rs:558-561), `ExecuteIndirect with two-pass ... skipped`
   (302-305), `console code so far: ... (M skipped ...)` (61-64); invisible in the 2 s line today.
6. `driver compile start/finish` (real.rs:4059/4065): no big compiles after load = the title stopped
   creating pipelines (H1); big compiles during the black phase = it is still building.

Expected verdicts:
- H1: 40 refusals, `translated_pipelines` ~21, only the fullscreen/presented draw kind, plane 0 A=0, no
  MS two-pass line, `rt` dump black -> port #541 + #2092.
- H2: a two-pass MS PSO line, no ExecuteIndirect-skip lines, only the composite draw kind, still black ->
  DispatchMesh over an unfilled record buffer; only #2092 fixes it (no counter can prove DispatchMesh).
- H4: plane 0 A>0 and `rt` lit while `frame` is 0 -> compositor/plane 1; re-run with
  `XCL_TRACE_SHADERS=<vs/ps hash>` (bind.rs:663-775). H5: CreateHeap refused / no video memory -> streaming.
## Q4 — patch

Behaviour is not a small patch: #304's vertex-chunk budget is in HEAD, but #541 (translate AS-slot MS)
and #2092 (execute two-pass on DispatchMesh/ExecuteIndirect) are both open upstream; #541 alone builds
pipelines that HEAD still skips. Do not "just delete the refusal".

The small patch clearly implied makes the black run self-diagnosing: the 2 s line hides skipped/PC
draws, so "1 draw/present" cannot be told from "1 draw + 200 skipped + 10k DispatchMesh".

```diff
--- a/crates/xcl/src/hle/d3d12x/bind.rs
+++ b/crates/xcl/src/hle/d3d12x/bind.rs
@@ -44,6 +44,10 @@ pub fn activity() -> (u64, u64) {
     (COUNTS[DRAWS].load(Ordering::Relaxed), COUNTS[DISPATCHES].load(Ordering::Relaxed))
 }
+/// all five console counters, including the ones `activity` leaves out
+pub fn activity_detail() -> [u64; 5] {
+    std::array::from_fn(|i| COUNTS[i].load(Ordering::Relaxed))
+}
--- a/crates/xcl/src/host.rs
+++ b/crates/xcl/src/host.rs
@@ -64,3 +64,5 @@
+                let c = crate::hle::d3d12x::bind::activity_detail();
+                crate::xlog_info!("console totals: {} draws ({} skipped, {} PC), {} dispatches ({} skipped)", c[0], c[1], c[2], c[3], c[4]);
```
