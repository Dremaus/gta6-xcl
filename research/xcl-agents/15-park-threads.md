# 15 — Parked-thread dump analysis + XCL title-visible memory/network surfaces (xcl prev-run 203520)

Source of stacks: `%LOCALAPPDATA%\XCL\RockstarGamesInc.28872443D20A7\logs\xcl.prev.log`
Dump 1 line 21490 (t=210, 145 thr), Dump 2 line 21657 (t=330, 144), Dump 3 line 21816 (t=450, 145).
**All three dumps show byte-identical title-thread stacks** (only OS pool churn: combase 6612 and 16404 exit, 8772/6020 appear; xcl-pso-2 26428 momentarily active at t=330).

## A) Title threads with game_scarlett_master.exe frames — 45 total, all identical across dumps

| TID | Park primitive (top 3 OS frames) | Game frames (top→bottom, trunc) | Role guess |
|---|---|---|---|
| 22596 | ntdll+0x166464 < KERNELBASE+0x1427f | +0x56a0d < **+0x23cf735** < +0x8126a7 < +0x53ec040 < +0x53ebf3a < +0x661f0 < +0x1d109c9 < +0x5a91c0d < +0x56a1e5a (under xcl.exe+0x9f987) | RENDER/frame thread |
| 11376 | 0x1427f | +0x43c3d5d < **+0x23cf4f2 < +0x23cf2d3 < +0x23cf104** < +0x2215eca | OOM-assert-family waiter #2 |
| 23880,10512,1912,24908,5028,10472,25896,14672,3176,23596,27956,15364,25968,2816,29820 (×15) | 0x1427f | +0x221c3c2 < +0x2215eca | worker pool (incl. 2816 = xapu submitter, wakes ~5 s to decode until t=241) |
| 9984,1124,28024,25956 (×4) | 0x1427f | +0x22511f < +0x22170d3 < +0x2215eca | worker pool B |
| 29012,29040,10364,22336 (×4) | 0x1427f | +0x22511f < +0x25782e2 < +0x2578607 < +0x2215eca | worker pool C |
| 25700 | 0x1427f | +0x22511f < +0x2a8bc5c | pool D |
| 20336 | 0x1427f | +0x22511f < +0x2a1bc0 < +0x5b6bf7e | pool E |
| 31548, 23448 | 0x1427f | +0x56a0d < +0x2218c82 | event-wait pair |
| 18796 | 0x1427f | +0x55e8b2a (single frame) | trampoline waiter |
| 27596 | 0x1427f | +0x19b4eaf | |
| 32712 | 0x1427f | +0x3a1a200 | |
| 23972 | 0x1427f | +0x56a0d < +0x4e7f358 < +0x6259 < +0x442fb32 | |
| 28740 | 0x1427f | +0x56a0d < +0x4e7f358 < +0x6259 < +0x3a1a5ab | |
| 30584 | 0x1427f | +0x56a0d < +0x1da8776 | |
| 13512 | 0x1427f | +0x41ec1a9 | net-services cluster (0x41e–0x41f) |
| 5452 | 0x1427f | +0x41eb52b | net cluster |
| 31816 | 0x1427f | +0x56a0d < +0x41ea2f4 | net cluster |
| 1196 | 0x1427f | +0x43adeda < +0x43add8d | service cluster (0x43a–0x43c, adj. to 11376's +0x43c3d5d) |
| 21404 | ntdll+0x166a64 < +0xd3194 < KERNELBASE+0x8cca1 | +0x43ae2ad < +0x1e95177 | svc, WaitMultiple family |
| 7888 | 8cca1 family | +0x25a595c < +0x25a5764 | |
| 15244 | 8cca1 family | +0x3da3da9 | XUser auth thread — still retries tokens t=215/292/343 (0x80072EFD) |
| 22240 | 8cca1 family | via **xcl.exe+0x6109e1** < +0x2215b0b | blocked INSIDE xcl call (dstorage region) |
| 23332 | ntdll+0x16a054 < +0x88fd3 < KERNELBASE+0xddce8 | via **xcl.exe+0x607999/0x6119f8/0x6103cd** < +0xf2cc43 < +0xe8905 < +0x194162 < +0x50498d1 | blocked INSIDE xcl call since < t=210, all 3 dumps |
| **27396** | ntdll+0x166464 < **mswsock+0x951a < ws2_32+0x210b1** | +0x41f19cc < +0x2215eca | **blocking recv() on a real host socket, forever idle** |

Non-game title modules: bink2scarlett waiters ×6 (19272,9332,25508,25292,13108,30172), amdxx64 waiters ×16 — all sleeping via KERNELBASE+0x1bea8/0x1427f, identical ×3. xapu itself keeps decoding Opus until t=241 (log 21646) then goes silent — consequence of park, not cause.
Classify: 39/45 at single primitive KERNELBASE+0x1427f (WaitForSingleObjectEx); 4 at WaitForMultiple family (0x8cca1); 1 recv; 1 condvar inside xcl; plus render thread inside the +0x23cf735 wait — **two threads (22596, 11376) sit in the +0x23cf104–735 OOM-assert-family wait**.

## B) Title-visible memory values (D:\git\xcl, main 7318cf60)

1. `crates/xcl/src/memcap.rs:23-41` — `XCL_HOST_MEMORY_MB` installs detours on kernel32 `GlobalMemoryStatusEx`/`GlobalMemoryStatus`; `memcap.rs:53-67` clamps totalPhys to cap, **reports `ullAvailPhys = cap/2`, `dwMemoryLoad = 50` constant** ("title's watchdog ends the process at load ~93", memcap.rs:59-61). **Run 203520 log has NO `XCL_HOST_MEMORY_MB=` line → hook NOT installed → title polled REAL host free RAM all run.**
2. `crates/xcl/src/hle/kernelx.rs:846-868` `TitleMemoryStatus`/`JobTitleMemoryStatus`: total = static budget (`config.rs:117-123`, 8192 MiB lockhart), used = `process_private_bytes().min(limit)` (kernelx.rs:831-844) → avail saturates to **0** as soon as host-process commit > budget.
3. `kernelx.rs:776-785` `XMemGetWorkingSetStatistics`: same budget + clamped private-bytes.
4. `gpu/uma.rs:851-856` `XCL_UMA_MB` (host.rs:35-36 sets it), `:79-90 XCL_UMA_WINDOWS`, `:780-790 XCL_COHERENT_MB` — title graphics reservation sizes; `uma.rs:812-826 free_commit()` (NEEDS_FOR_COHERENT_HEAPS=17 GB) is XCL-internal placement, bypasses the cap via `memcap::system_memory`.
- **Answer:** yes, in default config the title sees real host free physical RAM via un-hooked GlobalMemoryStatusEx; budget APIs (TitleMemoryStatus/XMem*) show only 8192-MiB-derived values. The knob is `XCL_HOST_MEMORY_MB` (memcap.rs:25) — it alone changes the free-memory numbers the title polls. DXGI QueryVideoMemoryInfo is XCL-internal only (real.rs:440-441, vram.rs, title_textures.rs).
- Timeline cross-check (prev.log): commit crossed 8192 MB at **t≈6 s** (line 281: 12791 MB) yet rendering ran ~60 fps to t≈180 — so TitleMemoryStatus.avail==0 is NOT the gate. Park onset coincides with local VRAM passing the 8192-MB card (t=150: 8355, t=160: 9507, t=196: 9891 MB) + commit 22→23.3 GB — real host free physical collapsing exactly then.

## C) Networking under XCL

- `netoff.rs:1-15,61-63` — socket/WinHTTP refusal exists but only with `XCL_NETWORK=0`; `hle/mod.rs:193-198` routes winhttp/ws2_32 to netoff only when offline. Prev.log has **no `XCL_NETWORK=0` notes → real system ws2_32/winhttp was used**.
- So thread 27396's `recv()` (mswsock→ws2_32) is a genuine blocking winsock recv on a real host socket; no XCL timer/pump will ever wake it unless the remote peer sends. Not "no answers by design" — by default the network is simply passed through; auth POSTs fail host-side with 0x80072EFD (ERROR_WINHTTP_CANNOT_CONNECT, log 21637/21652/21804).
- Could the park wait on that response? The recv thread's caller region (0x41f–0x41e) is the net-services cluster; but the render thread's park site (+0x23cf735) is in the same function as the historical **OOM asserts** (+0x23cf683/729) and on the frame path (+0x53ec040), and XUser retries continued past the park (tokens #10–#12) without a frame ever resuming. Counter-evidence: `xbox_live_tokens=true` made things WORSE (park at 136 s) — if the park were waiting for a network answer, supplying tokens should have helped.

## D) Verdict (ranked)

1. **Memory-headroom gate (title-side), ~70%:** park sites +0x23cf104–735 = allocator's wait-for-memory helper (same function as OOM asserts); gate input is the un-hooked GlobalMemoryStatusEx host-truth (free phys collapsed at t≈180–196 under VRAM spill >8 GB card); budget APIs exonerated by the t=6 s avail=0 evidence.
2. **Network-wait gate, ~10%:** recv idle-by-design but token retries continued and tokens=true worsened the park.
3. **Other, ~20%:** (a) XCL-side dstorage/IO completion stall — threads 23332/22240 blocked *inside xcl.exe 0x60xxxx–0x61xxxx* (dstorage region) identically ×3 dumps, could be victim or co-driver; (b) plain host thrash (23 GB commit on 16 GB RAM) — indistinguishable from (1) without the knob test.

## Decisive next run (300 s, no dumps)

```powershell
$env:XCL_HOST_MEMORY_MB='8192'; $env:XCL_RUN_SECONDS='300'; Remove-Item Env:XCL_THREAD_DUMP_AT -EA SilentlyContinue
xcl run "D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK"
```
(`XCL_RUN_SECONDS` = host.rs:111-117 self-terminate; memcap install logs at host.rs:39.)
With the cap the title sees **constant** ullAvailPhys=4096 MB / load 50 % (memcap.rs:58-66) regardless of host pressure.
- **CONFIRM (1):** presents/frames continue past t=210 at normal fps (no contiguous 0-present window) → gate reads the host-RAM passthrough.
- **REFUTE (1):** same single park at t≈180–200 despite fake-steady free RAM → move to 3(a): the avail=0 saturation of TitleMemoryStatus at higher thresholds, or the dstorage-internal wait (23332/22240); then test raising `title_memory_mb` in xcl.toml and `XCL_ACTIVITY=1` around the dstorage queue.

Skills: **research-ops** applied (evidence-first local-log + source read, current-state claims cited to file:line). **REA does not apply**: per D:\git\gta6-30fps\research\xcl-agents\rea-evidence.md there is no Ghidra/decompile provider configured here and the task is read-only log/source analysis — no binary was executed or disassembled; conclusions rest on XCL source (GPL-2.0 fork @ 7318cf60) and the captured thread dumps only.
