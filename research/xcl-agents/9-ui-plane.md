# 9 - UI plane and video frame order: VIctory-NVIDIA vs XCL

Scope: ideas only from the GPL-3.0 clone `D:\git\victory-nvidia` (no code copied); XCL at
`main` b75c0f30. Worktree `D:\git\xcl-wt-ui`, branch `agent/ui`, commit 1041d843 (diagnostics
only, not on main). No game launched, no game data. Build/test done under
`D:\git\.xcl-build.lock` with the shared release target; `cargo check -p xcl --lib --release`
OK, `cargo test -p xcl --lib --release -- present::` = 13 passed.

## Verdict

- XCL main does **not** ignore a PresentX UI plane by design: since #615 (`2ca749ab`) it parses
  every plane at 0x48 stride and composites planes 1..N over plane 0 with premultiplied alpha.
- It can still lose plane 1 silently: `extract_planes` skips malformed planes and
  `backbuffer_like` drops formats/sizes without a log; `Compositor::record` in main also lacks
  the upstream hardening that rejects invalid planes (`a1ab3517`, not on main).
- XCL does not present frames out of order: presents are locked and executed one at a time.
  Its Bink HLE only skips or forwards; victory's video bug was texture-upload staging/order,
  not Bink, and XCL's upload path does not have victory's ring replay.

## 1. The two victory fixes

### Interface plane (menus/loading/subtitles)

- `7997a20` added `crates/victory-gpu/src/compose.rs`, ported from fxceless #1189.
  `compose.rs:13-31`: scene = t0, interface = t1; pixel shader returns
  `float4(saturate(o.rgb + s.rgb * (1 - saturate(o.a))), 1)` -- the interface target is
  premultiplied and is laid over the game with a full-screen triangle.
  `compose.rs:34-190`: `Composer` (root signature, PSO per output format, SRV pair per present
  slot); `compose.rs:195` `view()` picks an SRV format.
- `crates/victory-gpu/src/host.rs:9747` `present_planes`: builds `planes` from the base plus
  optional overlay at `host.rs:9756`, creates the composer at `9788`/`9828`, and at `9870`
  transitions **both** source planes to `PIXEL_SHADER_RESOURCE` (`9874-9881`), draws, then
  transitions them back (`9905-9915`) and the back buffer to PRESENT/COPY_SOURCE. Failure warns
  "two-plane composer not made ... showing base plane only" and falls back to a plain copy.
- `crates/victory-gpu/src/queue.rs:672` `Plane` is the 0x18 prefix (token, count, resource**).
  `queue.rs:684` `RetailPlane` appends source rect, destination, colour space and 7 option
  words: the retail stride is **72 (0x48)**, asserted at `queue.rs:692`.
  `overlay_resource` (`queue.rs:695-713`) reads the second plane's prefix at that 72-byte
  stride, only after validating the resource; before `45e90f4` it used
  `plane_parameters.add(1)` (sizeof(Plane) = 24), read garbage as plane 1 and presented plane 0
  only -- the "two-plane black screen" fix. `45e90f4` is the decisive commit.
- `7940a...`/`a1849fa` only made the launcher select it; the mechanism is the above.

### Intro video frame order

- `77e13a9` ("intro video fix") says: linear one-level R8 video planes always record their
  copy (`texture.rs`), so frames of the ring no longer show out of order. Its source comments
  cite fxceless #489 "Fix stale frames in the opening video" and "Bink video flickering": the
  write guard on the sampled view did not see the decoder writing through another view; the
  `uploaded && !dirty` early-out then copied only with the next sampling list, three frames
  later in the video's ring of three, luma/chroma on separate turns (A,B,C,A,B,C ghosts). It
  disabled that early-out for those planes, hashed them at every check and raised the blind
  hot-frame window 64 -> 1024 (`VICTORY_VIDEO_HOT_FRAMES`); `VICTORY_VIDEO_PLANES=0` reverts.
- Current tree keeps the final form in `3bcc96f` ("smooth movie-plane uploads"):
  `crates/victory-gpu/src/texture.rs:844-858` and `1420-1432`. `Staging::movie_plane()` detects
  linear, one-mip, one-layer R8 planes; `upload_from` routes them to
  `list.plane_upload(...)` (`host.rs:7689-7701`), a dedicated per-list upload chunk, and always
  calls `record_upload` (`texture.rs:856`). The chunk lives through the list's GPU fence, so
  decoder frame N+1 cannot overwrite the source of frame N before frame N's copy has run.
  This is the ordering mechanism: per-list snapshot, not a reorder in Bink.

## 2. XCL present path and Bink

- `present.rs:52-67` `present_x` -> `present_x_frame` (`:116`) -> `present_now` (`:1072`).
- `PLANE_STRIDE = 0x48` at `:67`; `extract_planes` (`:71-113`) reads count at +8 and
  resource list at +0x10, optional source rect at +0x18, up to 8 planes, preserving order.
- `resolved` at `:1092-1119` filters each plane with `backbuffer_like` (`:325`): 2D,
  `DepthOrArraySize == 1`, single-sample, at least 640x360, and `swap_format` (`:315`) Some.
  A filter miss is silent in main (our patch logs it). With one surviving plane the fallback
  copies **that** plane (`:1230`), which may be plane 1 if plane 0 was dropped.
- More than one plane (or `XCL_RENDER_SCALE`) uses `Compositor` (`:769`, `record` `:883`):
  plane 0 opaque, planes 1..N with blend ONE / INV_SRC_ALPHA; test
  `compositor_blends_ui_plane_over_scene_plane` (`:1822`) covers transparent/opaque/half UI.
  So on main a 2-plane PresentX is composed in software, unlike victory before `7997a20`.
- Remaining UI-plane failure modes in main: (a) the title's plane 1 is not extracted at all
  (bad count/list/readable), (b) its format is not in `swap_format` (victory's `view()` also
  accepts 13/23/31/67/87, XCL does not), or (c) it is invalid for an SRV
  (`DENY_SHADER_RESOURCE`) and main still records the draw; `a1ab3517` adds the validation and
  fallback but is not on main.
- Ordering: `PRESENTX_LOCK`, the `PRESENTER` mutex, one command list per present,
  `ExecuteCommandLists` + `SwapChain::Present` synchronously, and fence-per-slot before buffer
  reuse (`PRESENT_SLOTS = 2`). Presents cannot be reordered. There is no wait on other title
  queues, so work on another queue can still be incomplete at PresentX -- a stale/black frame,
  not swapped frames.
- Bink HLE (`crates/xcl/src/hle/bink.rs`) is opt-in (`XCL_SKIP_BINK`, default off). When on,
  `BinkWait` returns 0 and `fast_advance` (`:183`) sets `frame_num`/`last_frame_num` to the last
  frame; `BinkDoFrameAsync*` are forwarded unchanged (`:330-364`). It has no frame queue and
  cannot reorder decoded frames. `XCL_SKIP_BINK=1` ends a non-looping movie at once; `all`
  also skips looping menu backgrounds.
- XCL's video-texture path (`hle/d3d12x/title_textures.rs`) watches writes on the CPU view
  (commit `9bd76353` for GPU views of CPU memory), then `upload_all` (`:1091`) batches uploads;
  `gpu/texture.rs:270-317` submits and waits for the upload fence. `XCL_TEXTURE_SKIP_UNCHANGED`
  (`:837-846`) can skip a texture when its bytes equal its last upload; that is correct for a
  duplicate video frame, and there is no victory-style `uploaded && !dirty` early-out. There is
  therefore no known out-of-order Bink/video present in XCL.

## 3. Diagnostic implemented in the worktree

`D:\git\xcl-wt-ui`, branch `agent/ui`, commit `1041d843` (1 file, +65/-18):

- `present.rs:1092-1119`: under `XCL_TRACE_FRAME`, logs
  `present: N of M presented plane(s) resolved for the window` and, per dropped plane,
  `present: plane i <addr> left out of the frame - not a 2D ... presentable format (<desc>)`.
  This separates "plane 1 was never presented" from "plane 1 was presented but dropped".
- `present.rs:1198-1222`: `present: compositing N planes into WxH <fmt> (plane 0: WxH fmt uv ...,
  plane 1: ...)` is now logged on the first composite, whenever the plane set changes, and on
  every present under `XCL_TRACE_FRAME` (main logged it exactly once, so a later 2-plane frame
  could not be confirmed).
- `present.rs:1179-1191`: when `XCL_FRAME_DUMP` is due on a multi-plane frame, dumps
  `plane0_<n>.bmp`, `plane1_<n>.bmp` beside the existing `frame_<n>.bmp` (composite) and
  `rt_<n>.bmp` (busiest single-sample render target), with COMMON -> COPY_SOURCE -> COMMON
  barriers. `plane*` tags do not overwrite `LAST_FRAME_DUMP`, so report.json still describes
  the composite.
- `present.rs:181`: under `XCL_TRACE_FRAME`, one line per extra plane:
  `frame trace: PresentX #n plane i of <addr> <desc> - rt binds A, UAV views B, copy C, clears D`.
  The existing plane-0 line is unchanged for existing log parsers.

Suggested run (same save/camera, no game data in the repo):

```
XCL_TRACE_FRAME=1 XCL_FRAME_DUMP=60 XCL_ACTIVITY=1
```

Read in this order:
1. `present: 2 of 2 ... resolved` plus `compositing 2 planes ... plane 1: 3840x2160 ...`.
   Absent or "1 of 2" -> a plane was dropped; the `left out` line names the reason. That is
   "UI plane missing" at the presentation layer.
2. `frame trace: PresentX #n plane 1 ... rt binds A ... clears D`: A=0 and D=0 means the title
   never drew into the UI plane this frame; A>0 or D>0 means it drew something (possibly black).
3. `plane0_*.bmp`, `plane1_*.bmp`, `frame_*.bmp`, `rt_*.bmp`: the raw-texel line for each bmp
   (e.g. `0x00000000` = transparent, `0x000000ff` = opaque black) distinguishes an empty UI
   plane from a black-drawn one.

## 4. UI plane missing vs world not drawn

| Observation | Meaning |
|---|---|
| plane 0 lit, plane 1 transparent (`0x00000000`), composite lit | normal interface over the world |
| plane 0 lit, plane 1 transparent, composite black | compositor/blend/target failure, not the world |
| plane 0 lit, plane 1 opaque black (`0x000000ff`), composite black | UI plane cleared/drawn black and covering the world; UI sub-system, not the compositor |
| plane 0 black, plane 1 transparent, composite black | world not drawn (plane 0); the UI plane is legitimately empty |
| plane 0 and plane 1 lit, composite black | compositor output/format/ordering; check the `compositing` descriptors and `frame` dump format |
| only composite black, `rt` lit | presentation/composite; `rt` may be another target, so confirm with plane dumps |

`rt` is the busiest single-sample render target, not necessarily the scene, so it cannot by
itself prove "world drawn"; per-plane dumps are the unambiguous evidence.

## 5. Recommendation

- Run the diagnostic on the current black frame. If `compositing 2 planes` is present and
  `plane1` is lit but `frame` is black, the fault is in `Compositor`/presentation; then port
  the `a1ab3517` plane validation and inspect the blend/format. If `plane1` is opaque black,
  the UI draws are missing; that is a draw/pipeline problem, not PresentX.
- If plane 1 is dropped, extend `swap_format`/`view` for its logged format, or make the drop
  loud (the new `left out` line already does this).
- Do not port victory code into XCL; use the mechanism above only (GPL-3.0 vs GPL-2.0-only).
