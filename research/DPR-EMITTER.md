# DPR emitter — the layer side of the S0 capture seam

Spec: `D:\git\gta6-native-proto\S0-REPLAY.md` §3 (record format) and §5
(emission points). Implemented in `VItoriaBr-opt`, commit `d93d263`
("dpr emitter", parent `1944123`), branch `main`.

## Emitter status

### What emits

`crates/victory-gpu/src/dpr.rs` (new module, `#[cfg(all(windows,
feature = "diagnostics"))]`). One record per drawn state, serialized to
the DPR v1 shape (`record.json` + `buffers/*.bin` + `shaders/*.dxil`,
every blob pinned by SHA-256, the crate's own implementation — FIPS
vectors covered in the unit tests).

The seam sits exactly where S0-REPLAY.md §5 names it:

| §5 point | Code |
|---|---|
| emission point | `State::draw` / `State::draw_indexed` in `draw.rs`, the `#[cfg(feature = "diagnostics")]` block right after each `list.note_op(...)` call — post-`prepare`, at the submission point, only for draws the host actually ran |
| host DXIL bytes | `pipeline::host_pipeline(...)` stages' `translated().host.dxil` — the exact bytes the host PSO was made from; written whole into `shaders/vs-<hash>.dxil` / `ps-<hash>.dxil` |
| `VertexView`/`IndexView` host ranges | `shadow::find_any(guest_va, len)` → the shadow's span, gated on `!carded && !writes_pending && !stale_under_writes`; bytes read under `watch::title_memory_reading()` (the same discipline as the rectangle expansion) |
| `Root::Constants` dwords | the values `State::bind` packs for the host's `SetGraphicsRoot32BitConstants`, stashed into `State::dpr_user_data` (diagnostics builds, env-gated) and emitted as `draw.root_constants` + declarative `constants` root params (space `USER_DATA_SPACE`, register 0) |
| input layout | `HostPipeline::inputs` (slot/offset/format) paired positionally with the host VS's `ISG1` part (name/index/comp parsed back out of the emitted container — same rows `emit::container::signature` writes); mismatch in count or component type fails closed |
| rasterizer / depth / blend | the `HostPipeline::state` summary the frame listing prints (host values); fill=solid and non-conservative are assumed and said so in `source.notes` (windows-rs 0.62 exposes no `GetDesc` on PSO/root signature; see S1) |
| frame pin | `source.frame = queue::presented() + 1`, `source.draw` = ordinal of executed graphics draws in that frame; marker via new `capture::world_frame()` accessor |

`cargo build --offline --release -p victory --features diagnostics`:
pass. `cargo test --offline -p victory-gpu`: 181 pass. The emitter's own
12 tests (`--lib dpr::`) pass, including the byte-for-byte shape test:
`record_json()` reproduces the proto's committed
`s0/records/synthetic-triangle/record.json` (modulo its missing final
newline) from a hand-built record — keep the two in step when the
format moves to v2.

### When it emits

Only with `VICTORY_CAPTURE_DPR=1` (or `VICTORY_CAPTURE_DPR=<dir>`, which
also moves the output). Otherwise zero behaviour change: the field,
snapshot and calls are all `#[cfg(feature = "diagnostics")]`, and every
runtime path behind `dpr::on() == false` is a single OnceLock read.

Per session: the first `VICTORY_CAPTURE_DPR_LIMIT` (default **12**)
distinct host pipelines, **one draw each**. Candidate frames: every
frame past the world-entry marker (`VICTORY_CAPTURE_WORLD` sets it), or
every 64th presented frame while the marker is unknown. At most 6
serialization attempts per pipeline; the first success claims it.

### Where files land

Never the repository, never the game folders (S0-REPLAY.md §7):

```
%TEMP%\gta6-dpr\frame-<n>\draw<ordinal>-<pipeline>\record.json
%TEMP%\gta6-dpr\frame-<n>\draw<ordinal>-<pipeline>\buffers\{vb0.bin,ib.bin}
%TEMP%\gta6-dpr\frame-<n>\draw<ordinal>-<pipeline>\shaders\{vs-*.dxil,ps-*.dxil}
%TEMP%\gta6-dpr\index.json
```

`index.json` is the manifest the mission asked for: every record with
its frame, draw ordinal, pipeline, and a one-line summary, plus every
skip with its reason (`"the shader uses a root view (S1)"`, `"the colour
target is DXGI format …"`, `"a buffer of the card's own memory (S1
readback)"`, …). Fail-closed: a record with any missing piece is not
written at all — only the index line is.

### What a real capture will look like (and why nothing may land yet)

The v1 record support set is what the s0 loader validates: constants-
only bindings, one RGBA8 target, D32 depth, triangle list, no instances.
GTA VI's world draws overwhelmingly bind descriptor tables, root views
and samplers, and their buffers live in card memory — those are skipped
**with a reason in the index**, by design. A first successful record is
therefore likely a simple opaque/decoration draw; the index's `skips`
array is the real inventory of what S1 must carry.

### What remains for a full frame capture (S1)

1. **Multi-draw frame records**: the `g6n-dpr-frame` v2 shape the proto
   already sketches (shared targets, ordered draws) — emit all draws of
   the captured pipeline set into one frame directory.
2. **Bindings**: descriptor tables / root CBV-SRV-UAV / samplers in the
   root signature kinds (schema reserved), CBV/SRV range bytes and
   texture blobs (PNG/BCn) per §5.3, descriptor heaps at replay time.
3. **Card-memory buffers**: GPU readback at record time for copies the
   shaders see on the card (`Shadow::carded()`), instead of skipping.
4. **PSO-descriptor words**: expose `GraphicsState`/`D3D12_ROOT_PARAMS`
   to the seam (or a diagnostics getter in the pipeline module) so
   fill/conservative/root-signature-table params are read, not inferred
   from the state summary; the two assumptions the notes advertise.
5. **Pass clears**: `targets.clear_*` are replay defaults today; hooking
   `list.rs`'s clear recording (or reading the pass op lines) makes S0a
   PNG comparison pixel-honest.
6. **Oracle fill**: captured records carry `expected.mode =
   "pending-oracle"`; today's s0 `validate()` rejects that mode — S0a
   extends the loader with `reference-png` (RenderDoc/PIX or the layer's
   own `VICTORY_CAPTURE` PNG at the same frame pin), then fills
   vertices/color or swaps in the translated DXIL pair for S0b.
7. **Wider support**: strips, blend/stencil, multi-RT, `base_vertex`,
   instances, >24-dword user-data blocks (the loader's current cap).

Known coordination note: base commit `1944123` on its own does **not**
compile — `host.rs:7499` reads `crate::draw::HEAP_BUFFERS_TABLED`, which
lives in the heap-buffers agent's still-uncommitted `draw.rs` WIP. The
emitter commit was verified by adding that one static in a throwaway
worktree (clean `cargo check`); once the WIP lands, the branch builds
whole again.

### Exact run for the first real capture (once AV3/reset are fixed)

```powershell
# build (already done at d93d263):
$env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
cd D:\git\VItoriaBr-opt
cargo build --offline --release -p victory --features diagnostics

# capture: DPR on; the world marker makes frames after world-entry the
# candidate set; VICTORY_CAPTURE keeps the PNG ops oracle S0a needs.
$env:VICTORY_CAPTURE_DPR = '1'          # records -> %TEMP%\gta6-dpr
$env:VICTORY_CAPTURE_DPR_LIMIT = '12'   # optional
$env:VICTORY_CAPTURE_WORLD = '1'        # optional but recommended
$env:VICTORY_CAPTURE = 'D:\Gry\VItoriaBr-data\captures\dpr'  # oracle, optional
powershell -File D:\Gry\VItoriaBr-data\Launch-VItoriaBr-SafeMem.ps1 -Keys
```

(`Launch-VItoriaBr-SafeMem.ps1 -Keys` inherits the caller's environment;
it sets its own safe-profile `VICTORY_*` vars but never clears
`VICTORY_CAPTURE_DPR`. The game is run by the game-agent, not here.)

After the run: read `%TEMP%\gta6-dpr\index.json`. Each `records[]` entry
is a directory that `s0 replay` accepts once the pending-oracle mode
lands (item 6); each `skips[]` reason maps to an S1 item above.
