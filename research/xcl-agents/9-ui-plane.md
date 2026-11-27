# 9 - UI plane and video frame order: VIctory-NVIDIA vs XCL

Ideas only from GPL-3.0 `D:\git\victory-nvidia` (no code copied); XCL `main` b75c0f30. Worktree `D:\git\xcl-wt-ui`, branch `agent/ui`, commit 1041d843 (diagnostics only, not on main). No game launched, no game data. Built/tested under `D:\git\.xcl-build.lock`, shared release target: `cargo check -p xcl --lib --release` OK; `cargo test -p xcl --lib --release -- present::` = 13 passed.

**Verdict.** XCL main does **not** ignore PresentX plane 1: since #615 (`2ca749ab`) it parses every plane at 0x48 stride and composites 1..N over plane 0 with premultiplied alpha. It can still lose plane 1 silently: `extract_planes` skips malformed planes and `backbuffer_like` drops formats/sizes without a log; `Compositor::record` also lacks the upstream hardening that rejects invalid planes (`a1ab3517`, not on main). XCL cannot present frames out of order (presents are locked and executed one at a time); Bink only skips or forwards. Victory's video bug was texture-upload staging, not Bink, and XCL's upload path has no equivalent ring replay.

## 1. Victory fixes

### Interface plane (menus/loading/subtitles)

- `7997a20` added `crates/victory-gpu/src/compose.rs` (ported from fxceless #1189). `compose.rs:13-31`: scene t0, interface t1; PS returns `float4(saturate(o.rgb + s.rgb * (1 - saturate(o.a))), 1)` - premultiplied interface over the game, full-screen triangle. `compose.rs:34-190` `Composer`; `:195` `view()` picks SRV formats.
- `crates/victory-gpu/src/host.rs:9747` `present_planes`: base + optional overlay (`:9756`), composer at `9788`/`9828`, both planes transitioned to `PIXEL_SHADER_RESOURCE` (`9874-9881`), drawn, then back (`9905-9915`); failure warns "two-plane composer not made ... showing base plane only" and copies plane 0.
- `crates/victory-gpu/src/queue.rs:672` `Plane` is the 0x18 prefix (token, count, resource**); `:684` `RetailPlane` adds source rect, destination, colour space and 7 options: retail stride **72 (0x48)**, asserted `:692`; `overlay_resource` (`:695-713`) reads plane 1's prefix there. Before `45e90f4` it read `plane_parameters.add(1)` (24-byte stride), got garbage as plane 1 and presented plane 0 only - the Series S two-plane black-screen fix. `45e90f4` is decisive.

### Intro video frame order

- `77e13a9` ("intro video fix") says linear one-level R8 video planes always record their copy (`texture.rs`), so the ring's frames no longer show out of order. Its comments cite fxceless #489 "Fix stale frames in the opening video"/"Bink video flickering": the write guard on the sampled view missed decoder writes through another view; the `uploaded && !dirty` early-out copied only with the next sampling list, three frames later in a ring of three, luma/chroma on separate turns (A,B,C,A,B,C ghosts). It disabled that early-out for those planes, hashed them every check and raised the blind hot window 64 -> 1024 (`VICTORY_VIDEO_HOT_FRAMES`); `VICTORY_VIDEO_PLANES=0` reverts.
- Current tree keeps the form from `3bcc96f` ("smooth movie-plane uploads"): `texture.rs:844-858`/`1420-1432`, `Staging::movie_plane()` detects linear one-mip one-layer R8 planes; `upload_from` uses `list.plane_upload(...)` (`host.rs:7689-7701`), a dedicated per-list upload chunk, and always `record_upload`s (`texture.rs:856`). The chunk lives through the list's GPU fence, so decoder frame N+1 cannot overwrite frame N's source before its copy. This is per-list snapshotting, not a Bink reorder.

## 2. XCL present path and Bink

- `present.rs:52-67` `present_x` -> `present_x_frame` (`:116`) -> `present_now` (`:1072`). `PLANE_STRIDE=0x48` (`:67`); `extract_planes` (`:71-113`) reads count +8, resource list +0x10, optional source rect +0x18, up to 8 planes, preserving order.
- `resolved` (`:1092-1119`) filters each plane with `backbuffer_like` (`:325`): 2D, one layer, single-sample, >=640x360, `swap_format` (`:315`) Some. Main logs nothing on a drop. With one survivor the fallback copies **that** plane (`:1230`), possibly plane 1 if plane 0 was lost.
- >1 plane (or `XCL_RENDER_SCALE`) uses `Compositor` (`:769`, `record` `:883`): plane 0 opaque, 1..N blend ONE/INV_SRC_ALPHA; test `compositor_blends_ui_plane_over_scene_plane` (`:1822`). A 2-plane PresentX is composed, unlike victory before `7997a20`.
- Remaining failure modes: (a) plane 1 not extracted (count/list unreadable); (b) format not in `swap_format` (victory's `view()` also accepts 13/23/31/67/87); (c) invalid SRV (`DENY_SHADER_RESOURCE`) while main still records the draw.
- Ordering: `PRESENTX_LOCK`, `PRESENTER` mutex, one list per present, synchronous `ExecuteCommandLists`+`Present`, fence per slot before reuse (`PRESENT_SLOTS=2`). Presents cannot swap. No wait on other title queues, so their work can be incomplete at PresentX - stale/black, not reordered.
- Bink HLE (`hle/bink.rs`) is opt-in (`XCL_SKIP_BINK`, default off). When on, `BinkWait` returns 0 and `fast_advance` (`:183`) sets `frame_num`/`last_frame_num` to the end; `BinkDoFrameAsync*` are forwarded (`:330-364`). No frame queue, no reorder. `1` skips non-looping movies; `all` also skips looping menu backgrounds.
- Video textures (`hle/d3d12x/title_textures.rs`): writes watched on the CPU view (`9bd76353`), `upload_all` (`:1091`) batches, `gpu/texture.rs:270-317` submits and waits for its fence. `XCL_TEXTURE_SKIP_UNCHANGED` (`:837-846`) skips only when bytes equal the last upload (correct for a duplicate frame); no victory-style deferred copy. No known out-of-order video present.

## 3. Diagnostic in the worktree

`D:\git\xcl-wt-ui`, `agent/ui`, `1041d843` (1 file, +65/-18):

- `present.rs:1092-1119`: under `XCL_TRACE_FRAME`, logs `present: N of M presented plane(s) resolved for the window` and per dropped plane `present: plane i <addr> left out ... (<desc>)`.
- `present.rs:1198-1222`: `present: compositing N planes into WxH <fmt> (plane 0: ..., plane 1: ...)` logs on the first composite, when the plane set changes, and every traced present. Main logged it once forever, so a later 2-plane frame could not be confirmed.
- `present.rs:1179-1191`: when `XCL_FRAME_DUMP` is due on a multi-plane frame, dumps `plane0_<n>.bmp`, `plane1_<n>.bmp` beside `frame_<n>.bmp` (composite) and `rt_<n>.bmp` (busiest single-sample RT), COMMON -> COPY_SOURCE -> COMMON. `plane*` tags leave `LAST_FRAME_DUMP` alone.
- `present.rs:181`: under `XCL_TRACE_FRAME`, `frame trace: PresentX #n plane i of <addr> <desc> - rt binds A, UAV views B, copy C, clears D`. The plane-0 line is unchanged for existing parsers.
- Run same save/camera: `XCL_TRACE_FRAME=1 XCL_FRAME_DUMP=60 XCL_ACTIVITY=1`. (1) `2 of 2 ... resolved` + `compositing 2 planes ... plane 1: 3840x2160 ...`; absent or `1 of 2` means a drop, and the `left out` line names why. (2) `frame trace: ... plane 1 ... rt binds A ... clears D`: A=0,D=0 means UI was never drawn this frame; A>0/D>0 means it drew something, possibly black. (3) `plane0/plane1/frame/rt` bmps; raw texels (`0x00000000` transparent, `0x000000ff` opaque black) tell empty from black.

## 4. UI plane missing vs world not drawn

| Observation | Meaning |
|---|---|
| plane 0 lit, plane 1 transparent, composite lit | normal interface over the world |
| plane 0 lit, plane 1 transparent, composite black | compositor/blend/target failure, not the world |
| plane 0 lit, plane 1 opaque black, composite black | UI cleared/drawn black and covering; UI sub-system |
| plane 0 black, plane 1 transparent, composite black | world not drawn (plane 0); UI legitimately empty |
| plane 0 and 1 lit, composite black | compositor output/format; check descriptors and `frame` format |
| only composite black, `rt` lit | presentation/composite; `rt` may be another target |

`rt` is the busiest single-sample render target, not necessarily the scene, so it alone cannot prove "world drawn"; per-plane dumps are unambiguous.

## 5. Recommendation

- Run the diagnostic. If `compositing 2 planes` is present and plane 1 is lit but `frame` is black, the fault is `Compositor`/presentation: port `a1ab3517` validation, then inspect blend/format. If plane 1 is opaque black, the UI draws are missing - a draw/pipeline problem.
- If plane 1 is dropped, extend `swap_format`/`view` for its logged format; the new line makes the drop loud.
- Do not copy victory code into XCL (GPL-3.0 ideas only, XCL GPL-2.0-only).
