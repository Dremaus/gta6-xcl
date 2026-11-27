# 18 — Black 3D with working 2D: root-cause diagnosis

Read-only pass over `D:\git\xcl` main 7318cf60 + logs of runs 214346 (xcl.prev.log) and 215736 (xcl.log). No files changed; `xcl-wt-memacct` untouched (kernelx.rs TitleMemoryStatus accounting excluded). ECC: reverse-engineer-anything-style evidence discipline applied to own source+logs; **REA itself does NOT apply** — source is available (per rea-evidence.md §3: stated explicitly).

## Evidence table

| # | Fact | Source |
|---|------|--------|
| E1 | UMA WARN t=1.512 (215736): "17291 MB of commit free, under **17408 MB**: the title's GPU heaps stay outside unified memory (a larger page file gives them the coherent window)" | xcl.log; gate `gpu/uma.rs:796-801`, threshold `NEEDS_FOR_COHERENT_HEAPS = 17<<30` `gpu/uma.rs:813` |
| E2 | Coherent window only 512 MB, filled 311→323/512 MB by t=413 | xcl.log t=1.526, "console code so far" lines |
| E3 | 8× WARN t=141.889-141.915 (215736) / t=152.102 (214346): `two-pass ExecuteIndirect(DispatchMesh) … skipped: its arguments are not in a console buffer in unified memory` | `hle/d3d12x/bind.rs:768,809`; onset = 2D→3D transition (black between t=146-177) |
| E4 | Skipped-draw counter (reason log-capped at 8): 128→1409→5804 (t=250.289) →6498 (t=413.694) of 19053 translated draws; prev run 64→3288 by t=161.282 | "console code so far" lines; `bind.rs:806` `count(DRAWS_SKIPPED)` |
| E5 | Last activity with presents>0 at t=142.416 (215736); draws/submits continue to t≈271, then full park; prev run presents stop ~t=139 too | xcl.log "activity (2 s)" lines |
| E6 | 6 new mirrors t=146.5-149.8, all micro IBs/VBs 8-756 B; total mirrors 2 MB; "no room for a copy"=0 | `list_x.rs:3652-3739` (`gpu_va`/`mirror_of`); log |
| E7 | Present always 2 planes: plane0 1920x1080 fmt28 (game), plane1 3840x2160 fmt28 (overlay); composited, logged once | `present.rs:1092-1210`; xcl.log t=10.049; 9-ui-plane.md |
| E8 | Presented content non-black ONLY 2D palette (dominant `0xff2c2020` = cover art) until last dump t=134.8; no scene color ever | "present: frame … raw texels" lines |
| E9 | `1 writes … queue had not got there after 10000 ms` t=168.1; video memory 11911 MB local committed on 8 GB card t=599.7 | `cpu_writes.rs:187` path; xcl.log |
| E10 | `[STUB] ID3D12PipelineState(stand-in)::#11 … amd_fidelityfx_upscaler_xbox.dll` t=149.89 / t=158.57 — slots ≥9 return 0 | `standin.rs:244-263` |

## A) UMA mirror path — real, but too small to be THE cause
`gpu_va` (list_x.rs:3652): only **VB and IB bound via IA** get mirrors (3966, 4013, mirror=true); `DrawIndexedX` inline indices get a copy-at-bind (4037). SRVs/CBs are NOT mirrored here (they resolve through heap windows/#1803 heap bases, bind.rs:510). `sync_title_buffers` (3743-3807) copies the read range **at record time, on the CPU** — for GPU-written buffers that is a stale/racy snapshot (docstring admits "what the title writes there afterwards is not seen" for non-mirrored). Failure modes: non-readable VA → returned untranslated (GPU cannot address it → reads zeros); 2 GiB mirror cap → degrades to copy-at-bind (3720-3723). Volume evidence (E6: 8 buffers, 2 MB total; cap never hit) ⇒ contributes at most a handful of small draws at onset, not the 1000+/frame 3D stream.

## C) Mesh shader output path — the 3D draw stream is fail-closed skipped
Two-pass EI: `execute_indirect` (bind.rs:745) requires `console_buffer(args)` (755) and `commands ≤ buffer` else **skip** (766-769). GTA VI's meshlet culling writes DispatchMesh args into GPU heaps that E1/E2 placed OUTSIDE the 512 MB coherent window ⇒ batch after batch skipped. E4: thousands of skipped draws, first ones seconds before black onset, silent after the 8-line log cap; every other skip reason (pending-pso bind.rs:824/727, "PC pipeline is a mesh shader" 836/1096, scratch-cap 610) never logged. Successful `two-pass DispatchMesh #2048` (t=160.7) proves the MS path itself works when args are in UMA. So MS is not silently emitting — it is being **skipped**, by design-fail-closed, exactly at the 2D→3D boundary.

## D) Present/composition — unresolved but bounded
Main composites 1..N planes premultiplied over plane0 (9-ui-plane.md); `backbuffer_like` (present.rs:318) silently drops non-presentable planes (single-sample, ≥640x360, swap format) and `resolved.is_empty()` → no-op present. Dumped composites (E8) show only 2D palette then nothing (presents die at t≈142, E5), consistent with plane0 (1080p game) empty **or** dropped — main cannot tell. `xcl-wt-ui` 1041d843 (present.rs only) adds: "N of M presented planes resolved" + "plane i left out — not backbuffer-like ({desc})", per-plane USES counters (rt binds/UAV/copy/clears), and per-plane BMP dumps (`plane<i>`) under XCL_FRAME_DUMP. It answers exactly: 3D RT empty (plane0 dump black, clears>0 binds>0) vs never-drawn (binds=0) vs dropped by format (left-out line) vs compositor (composite black, planes lit).

## B) Depth — no mechanism found
ClearDepthStencilView is a straight forward (list_x.rs:4392-4405); console DepthFunc flows through unchanged (hashed real.rs:5157, traced 5563-5565); `LESS` appears only as test fixture (real.rs:5239) and stand-in fallback default (7235). No console→PC reversal/rewrite exists ⇒ cannot reject all pixels. Weak.

## Ranked verdict
1. **A+C unified (HIGH)**: free-commit gate (E1) → 512 MB window (E2) → title GPU heaps outside UMA → meshlet EI draws fail-closed skipped (E3/E4, bind.rs:768) → plane0 never drawn → 2D-only present (E8) → title stalls/parks (E5/E9 consequence). XCL's own comment predicts precisely this state: "its GPU heaps outside unified memory: **no image**" (uma.rs:794).
2. **D (MEDIUM)**: can only be adjudicated by plane dumps (xcl-wt-ui); also covers plane-order/alpha doubt.
3. **A alone (LOW-MED)**: record-time CPU mirror staleness — only 8 tiny buffers.
4. **E9/FFX E10 (LOW)**: VRAM oversubscription stall and stand-in slot-11 stub aggravate/attest but post-date skip onset.
5. **B (VERY LOW)**: no depth rewrite exists.

## ONE decisive next-run experiment (no build, no lock needed)
Close the E1 gap (+117 MB!) the log itself prescribes: enlarge the page file so free commit ≥ 18432 MB at launch.
1. Admin: `wmic pagefileset where "Indexing='C'" list` → set InitialSize=24576, MaximumSize=32768 (fastest volume; needs ~33 GB free disk) or switch to system-managed with headroom. Verify pre-launch: `(Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory -ge 18874368` (KB).
2. Run same binary, same env (XCL_RAYTRACING=off, XCL_SKIP_PREPARATION=1, title memory 28672, memcap as before) **plus** `XCL_TRACE_FRAME=1`, `XCL_FRAME_DUMP=20`, `XCL_RUN_SECONDS=300`.
3. Read gates: (i) no "commit free, under" WARN; (ii) "console code so far … (0 skipped)" through t≈180 — note window converges across runs (uma_coherent.txt=3.03 GB now; kernelx.rs:830) so judge on the first run with "coherent ~3.5 GB+", re-run once if still 512; (iii) if black persists despite 0 skips, C is falsified → merge xcl-wt-ui (1041d843) next, build serialized under `D:\git\.xcl-build.lock` and only after the memacct agent finishes. Do NOT use `XCL_COHERENT_MB` (bypasses the commit gate, uma.rs:788 — risks commit failure).
