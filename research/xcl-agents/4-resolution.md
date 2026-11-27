# 4 — Present resolution: who picks 3840x2160, and `XCL_RENDER_SCALE`

Branch `agent/res` (worktree `D:\git\xcl-wt-res`, based on HEAD `8b957bec`). Scope: `crates/xcl/src/hle/d3d12x/present.rs`;
line numbers are on that branch after the patch.

## 1. Who chooses 3840x2160
The **title's presented resource**, not XCL's window or the desktop:
1. `window_thread` (522) makes the 1280x720 client window from `xcl.toml` `window_width/height` (config.rs:57-58,
   default 184-185); the window is never used to size the swap chain.
2. Every `PresentX` → `present_x_frame` (116) → `present_now` (1060), which reads the presented resource with
   `GetDesc()` → `(w,h)` (1113-1119). For this title that is 3840x2160 (the `XCL_FRAME_DUMP` line:
   `width=3840 height=2160 format=28`).
3. `ensure_swapchain(p, hwnd, w, h, fmt)` (defined 1004, called 1144) creates
   `DXGI_SWAP_CHAIN_DESC1 { Width: w, Height: h, Scaling: DXGI_SCALING_STRETCH, SwapEffect: FLIP_DISCARD }`
   (1027-1037) via `CreateSwapChainForHwnd` (1042). The swap chain is *always* the title's size; DXGI stretches it
   into the 1280x720 window, and DWM stretches the window on the 4K desktop.
4. Blit: one plane and equal sizes → `CopyResource` (1198-1199). Different sizes → `CopyTextureRegion` with
   `cw = min(desc.Width, p.w)`, `ch = min(desc.Height, p.h)` (1201-1214) — a **top-left crop, no scaling**. That is
   the trap for any swap-chain shrink.
5. Multi-plane frames take the `Compositor` path (1157-1185), whose full-screen triangles use a linear sampler (it
   *can* scale), but it is only entered when `resolved.len() > 1`.

Places XCL already limits size: only `min(desc.Width, p.w)` / `min(desc.Height, p.h)` in the crop branch, plus the
`backbuffer_like` floor of 640x360 (319-330). Nothing caps the swap chain by window or monitor. `ResizeBuffers`
(1016-1025) only reacts to a changed presented size.

## 2. `XCL_RENDER_SCALE` design
`XCL_RENDER_SCALE=0.25..1.0` (or `25..100`, `%` suffix accepted; unset/invalid = 1.0):
`presented_size(w,h,scale) = (round(w*s), round(h*s))`, clamped to >= 1. Only applied when `resolved.len() == 1`;
multi-plane composite size is unchanged in this first version. The swap chain is created at the scaled size, and the
single plane is drawn into it by the existing `Compositor` (linear filter), then `DXGI_SCALING_STRETCH` stretches the
swap chain to the window.

**What the title observes: nothing.** XCL's swap chain is private to XCL (`CreateSwapChainForHwnd` on XCL's own HWND);
titles present their own resources through `PresentX` and never hold a pointer to our `IDXGISwapChain`. Therefore:
- swap-chain desc / back-buffer `GetDesc` / `ResizeBuffers`: title-visible state is unchanged (it cannot call them);
- viewport/scissor: the title's own 4K pass is untouched; the compositor sets its viewport/scissor to `p.w x p.h`
  for the blit only;
- `PresentX`'s `pSourceRect`: the baseline single-plane copy ignored it (copied the whole resource); the scaled path
  forces uv `[0,0,1,1]` to keep exactly that behaviour.

Honest caveat: this shrinks the **presented** surface (swap-chain VRAM 99.5 MB → 24.9 MB at 0.5; the per-frame 4K copy
becomes a 1080p draw + 4K texture read; DWM samples 1080p instead of 4K). It does **not** reduce the pixels the title
renders — its render targets are unchanged, and shrinking those needs resource-creation interception, outside
present.rs. Expect a present-side gain, not a 4x render gain.

## 3. Patch (only present.rs; default byte-identical when unset)
```rust
fn render_scale() -> f32 { /* OnceLock; env once; warns once if invalid; 1.0 if unset */ }
fn parse_render_scale(v: &str) -> Option<f32> { /* 0.25..=1.0, or 25..=100 / "50%" */ }
fn presented_size(w: u32, h: u32, scale: f32) -> (u32, u32) {
    if !(scale.is_finite() && (0.25..1.0).contains(&scale)) || w == 0 || h == 0 { return (w, h); }
    (((w as f32 * scale).round() as u32).max(1), ((h as f32 * scale).round() as u32).max(1))
}
// present_now:
let (pw, ph) = if resolved.len() == 1 { presented_size(w, h, render_scale()) } else { (w, h) };
let scaled = (pw, ph) != (w, h);
if scaled { resolved[0].2 = [0.0, 0.0, 1.0, 1.0]; }         // copy path ignored pSourceRect
if !ensure_swapchain(p, hwnd, pw, ph, fmt) { return; }
if resolved.len() > 1 || scaled { /* Compositor::record(..., p.w, p.h, ...) */ }
```
Unset: `pw,ph == w,h`, `scaled == false`, so `ensure_swapchain` gets the same arguments, `CopyResource` runs as before,
and the multi-plane condition is unchanged.

## 4. Failure modes and how to detect them
| failure | cause | detection |
|---|---|---|
| Cropped image (top-left quarter stretched) | `scaled` but `Compositor::new`/`record` fails → old crop branch (1198-1214) | log `present: compositor unavailable – falling back to plane 0` (1190) + frame dump missing right/bottom UI |
| No effect on a multi-plane title | scale is single-plane only | log `present: compositing 2 planes into 3840x2160` (full size) |
| Swap-chain churn / stutter | title alternates presented sizes; each `ResizeBuffers` drains the pipe (1016-1025) | repeated `present: swap chain WxH` lines; baseline has the same churn |
| Wrong viewport | compositor viewport is set from `p.w/p.h`, not a stale size | frame dump stretched/offset; `frame_<n>.bmp` dims != `present: swap chain` dims |
| Aspect distortion | baseline already maps source aspect to the 16:9 window with `DXGI_SCALING_STRETCH` | unchanged from A; equal scaling preserves the ratio |
| Low-quality UI text at 0.25 | 960x540 then linear upscale | expected; use 0.5 for UI-heavy checks |
| Env typo ignored | parser rejects 1.5 / 10 / 0.1 | one `XCL_RENDER_SCALE=... is not 0.25..1.0` warning |

No auto-recovery: a failed compositor keeps the cropped fallback (same as multi-plane today); the log line and the
missing half of the picture are the signal.

## 5. Test
`render_scale_sizes_the_presented_surface` in `present.rs` `mod tests` (1655): exact 4K @ 1.0 / 0.5 / 0.75, 1920x1080 @
0.25, 3840x2160 @ 0.3 (rounding), out-of-range and NaN unchanged, zero-size unchanged; parser accepts `0.5`, `" 50% "`,
`100`, `0.25` and rejects `1.5`, `10`, `0.1`, `101`, `""`, `nonsense`. Command (under the build lock, shared release
target): `cargo test -p xcl --lib render_scale --release`. Result: **1 passed; 0 failed; 0 ignored** (1345 filtered
out), private release target, 3m07s.

## 6. A/B verification plan (same scene; do not compare different saves)
Runs: A (unset) → B (`XCL_RENDER_SCALE=0.5`) → A again, 60 s each, same fixed camera/pause, both with
`XCL_FRAME_DUMP=120` (optionally `XCL_FRAME_DUMP_FULL=1` for one dump).
1. **Presented surface**: B must log `present: XCL_RENDER_SCALE=0.5`, `present: swap chain 1920x1080` and
   `present: compositing 1 planes into 1920x1080`; A logs `swap chain 3840x2160` and no scale line.
2. **Rate**: use the existing `D3D12.X: N frames presented, X fps over the last 300` (123); average the last 3 lines.
   Presentations/2 s = 2 x fps. Also compare the window-title FPS (454-458).
3. **Frame dump size**: A's `frame_<n>.bmp` is from the title's 4K frame (bmp 960x540 at step 4); B's is the scaled
   back buffer, 1920x1080 (bmp 480x270 at step 4). The size change proves the presented surface shrank.
4. **Scaled, not cropped**: in B all four HUD corners are present and the whole scene fills the 16:9 window; a crop
   would lose the right/bottom half (bottom-right minimap/HUD gone). Compare a corner marker with A, scaled by 2.
   Also screenshot the 1280x720 window: no black bands, no duplicated edge.
5. **No regressions**: no `present:` errors, no device-removed line, no repeated swap-chain logs. The unset run must
   match the pre-patch build's fps and dump within noise; the path is identical by construction and the unit test pins
   the maths.
