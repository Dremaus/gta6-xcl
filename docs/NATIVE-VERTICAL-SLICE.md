# Native Vertical Slice — GTA VI 1.0.2.1, 720p30 on an RTX 4060 Laptop

| Field | Value |
|---|---|
| Status | **Proposed plan. Not executed.** No game was launched while writing this. |
| Date | 2026-11-25 |
| Target hardware | RTX 4060 Laptop 8 GB, 16 GB RAM, Ryzen 7 8845HS, NVMe |
| Target title | GTA VI Xbox Series X, build **1.0.2.1**, user-supplied copy |
| First milestone scene | `room01`: first interior room reachable from the prologue save |
| Output | 1280×720, low, native render, 30 fps p50 |
| Repo | `D:\git\gta6-30fps` |
| License | GPL-3.0-or-later (this project) |

## 0. Verdict in one page

The current translation layers are not 6× away from 30 fps; they are 20–120× away
on this laptop. The measured work is dominated by per-draw CPU setup, copies, heap
passes and pipeline misses, not by GPU arithmetic. A native renderer that removes
those costs is the only credible route to 33.3 ms. That does **not** make 30 fps in
30 days likely.

This plan therefore builds a **native vertical slice**, not a full port:

1. **Replay first.** Capture one real frame from the current layer, replay it through
   a native D3D12 render graph, and prove the image and draw list match. This isolates
   renderer cost from the game's runtime.
2. **Go live second.** Connect the same renderer to the running game for one room,
   with input and camera. This is the hard integration gate.
3. **Selective AOT, not full static recompilation.** The game's x64 code already runs
   natively. Recompile only hot render-submission functions, with a differential
   verifier and a kill switch. A full static recompilation is a multi-year project and
   is not on the critical path.
4. **Measure, then claim.** G4 is a measured gate: p50 ≤ 33.3 ms, p95 ≤ 40 ms,
   3 × 600 frames, 30-minute soak, image parity, no device loss, no dropped draws.

Subjective confidence before any experiment (replace with measurements at G0):

| Outcome | Confidence |
|---|---:|
| Synthetic 720p stress scene at 30 fps | 95% |
| One real game draw at 30 fps | 90% |
| `room01` replay at 5 fps | 75% |
| `room01` replay at 30 fps | 40% |
| Live `room01` at 10 fps | 50% |
| Live `room01` at 30 fps | 10–15% |
| Full game at 30 fps on this laptop | <5% |

The plan is designed to fail cheaply and produce a defensible answer if the hardware
or the 16 GB RAM ceiling is the wall.

---

## 1. Target, acceptance tests and gates

### 1.1 What "first playable room" means

`room01` is the first interior room reachable from the prologue save. It is chosen
because it is small enough to fit the asset budget, has no streaming boundary in the
middle, and contains both static and one or more mesh-shader draws.

| Property | Requirement |
|---|---|
| Save | User's `room01` autosave, copied outside the repo; SHA-256 pinned |
| Build | Xbox Series X 1.0.2.1, same executable hash every run |
| Camera | Deterministic 600-frame path, recorded from the current layer |
| Time/weather | Fixed by save; no cutscene, no mission transition |
| Visible draws | ≤ 2,000 after culling at G4 (≤2,500 at G3; capture tells the real number) |
| Textures resident | ≤ 4.2 GB |
| Output | 1280×720, 16:9, low, native render, no dynamic resolution |
| Upscaling / frame gen | **Off** for the gate; FSR/DLSS is a separate G5 experiment |
| Ray tracing | Off |
| TAA | Off for image-parity gates; optional after G4 |
| Audio/video | Out of scope; muted |
| UI | Out of scope for G1–G3; a static HUD overlay is required at G4 |

"Playable" for this slice means: load the save, look around, walk at least 3 m, open
the room's door, and play for 10 minutes without a crash, device loss or missing
geometry. It does **not** mean missions, combat, traffic, streaming across the city,
or a shippable port.

### 1.2 Frame budget at 30 fps

33.3 ms is the whole frame. CPU and GPU overlap, so the gate is
`max(CPU, GPU) + present + slack ≤ 33.3 ms`.

| Component | Budget |
|---|---:|
| CPU: game logic / camera / input | 5.0 ms |
| CPU: cull + build native draw list + record | 5.0 ms |
| CPU: submit + fence + present | 2.0 ms |
| **CPU total** | **12.0 ms** |
| GPU: depth / mesh / visibility | 6.0 ms |
| GPU: opaque base pass | 11.0 ms |
| GPU: shadows | 4.0 ms |
| GPU: post / tonemap | 4.0 ms |
| GPU: UI | 1.0 ms |
| GPU: overhead / barriers / queries | 2.0 ms |
| **GPU total** | **28.0 ms** |
| Present / DWM (borderless) | 2.5 ms |
| Slack | 2.8 ms |
| **End-to-end p50** | **33.3 ms** |

Draw arithmetic that makes this plausible:

```text
Current layer:  3,850 draws × 27 µs = 104 ms CPU   (fxceless measurement)
Target:         2,500 draws ×  5 µs =  12.5 ms CPU   (2,000 at G4 = 10.0 ms)
GPU at 720p:                       18–25 ms
Present:                            2.5 ms
max(CPU, GPU) + present:           27.5 ms  → 5.8 ms slack
```

At 3,850 draws the CPU alone is 19.3 ms at 5 µs/draw; still survivable, but it leaves
no room for a slow frame. G3 must cull/batch to ~2,500 draws and G4 to ~2,000, or
reach ~3 µs/draw. This is why a native renderer needs GPU-driven culling and indirect
draws, not just faster per-draw code.

### 1.3 Measurement protocol

All performance numbers in this document are targets, not measurements. The first
three days replace them with real numbers.

- **Frame time**: QPC from the start of `Present` to the start of the next `Present`,
  including the waitable-object wait. For replay-only gates (no swapchain), use
  render-thread start-to-end plus GPU timestamp, and label it `replay_ms`.
- **Warmup**: discard the first 120 frames; measure the next 600.
- **Current-layer baseline exception**: 120 measured frames, because 600 frames at
  1–2 fps would take 5–10 minutes per run. Native gates use 600.
- **Runs**: 3 independent runs; report the median of each run's p50 and p95.
- **p95**: 95th percentile of all measured frame times, not an average.
- **GPU time**: timestamp queries at pass boundaries; resolve into a readback ring.
  Do not infer GPU time from CPU present time.
- **Environment**: AC power, Windows High Performance, NVIDIA "Prefer maximum
  performance", vsync off, borderless 1280×720, no overlays (GeForce Experience,
  Discord, Steam, OBS), Windows Game Mode on. Log GPU clock and temperature; reject a
  run if the GPU sustains <90% of its maximum clock or exceeds 80 °C.
- **Driver/OS**: pin the NVIDIA driver and Windows build in the result JSON. A driver
  change invalidates the PSO library, not the shader translation cache.
- **Reporting**: one JSON per run in `benchmarks/`, plus logs and screenshots outside
  the repo. No game-derived pixels are committed.

### 1.4 Acceptance tests

Each test is a command or a script with a machine-readable result. "Artifact" is what
must exist after the test; artifacts containing game-derived data stay outside the repo.

| ID | Test | Method | Pass threshold | Artifact |
|---|---|---|---|---|
| T1 | Clean build | Fresh checkout, pinned toolchain, no network except crates | `cargo build --release`, CMake, `cargo test` all pass | CI log |
| T2 | Synthetic 720p30 stress | Own geometry/shaders: 2,000 instanced draws, 1M triangles, 4× overdraw, 600 frames | p50 ≤ 33.3 ms, p95 ≤ 40 ms, no device loss | `benchmarks/synthetic.json` |
| T3 | Capture import | RenderDoc/PIX capture of `room01` frame; import to IR | All resources/shaders/PSOs resolve; 0 unknown | `capture.json` + hash manifest |
| T4 | One-draw parity | S0a host DXIL vs S0b our DXIL, same inputs | S0a exact on covered pixels; S0b ≤1 LSB; depth p99 ≤ 1e-6 | `compare-s0.json` |
| T5 | Room replay parity | Native replay vs current layer, same frame/camera | SSIM ≥ 0.97; ΔE2000 p95 ≤ 3.0; silhouette IoU ≥ 0.995 | `compare-g1.json` |
| T6 | Live playable | Game + native renderer, same save, input enabled | 5 min play; no crash; camera/walk/door work | video + input log |
| T7 | Shader/PSO coverage | Warm all `room01` shaders and PSOs; replay | 0 misses and 0 in-frame compiles in measured frames | `warm.json` |
| T8 | Memory | 600 frames + 30 min soak | VRAM ≤ 7.2 GB; commit ≤ 14.5 GB; growth < 64 MB/10 min | `memory.json` |
| T9 | Stability | 30 min loop, alt-tab, resize, minimize/restore | No TDR, no `DXGI_ERROR_DEVICE_REMOVED`, no crash | `soak.json` |
| T10 | Performance gate | 3 × 600 frames at 720p | G4: p50 ≤ 33.3, p95 ≤ 40, p99 ≤ 50; 0 dropped draws | `benchmarks/g4.json` |
| T11 | AOT differential | 100k generated + 10k recorded invocations | GPR/XMM/flags/memory writes bit-exact; no OOB | `recomp-diff.json` |
| T12 | Determinism | Same save/camera path, 3 replays | Frame hashes identical; draw list hash identical | `determinism.json` |
| T13 | Asset/license policy | `cargo xtask check-assets`, `cargo deny` | No game files; no GPL-2.0-only code; notices present | CI log |
| T14 | Rollback | `G6N_RENDERER=layer`, `G6N_RECOMP=off` | Both return to last known-good path in one command | runbook + log |

### 1.5 Correctness thresholds

Pixel-perfect comparison is only expected when the same DXIL and the same state are
used (S0a/S0b). For a native renderer vs the current layer, the translation, root
signature and pass order differ, so use perceptual and structural metrics:

| Metric | Threshold | Notes |
|---|---:|---|
| SSIM (luma, 720p) | ≥ 0.97 | Compare HDR scene color before post if possible |
| CIEDE2000 p95 | ≤ 3.0 | On covered pixels; ignore UI and subtitles |
| Silhouette IoU | ≥ 0.995 | From depth/alpha mask, not color |
| Max ΔE in >0.1% pixels | ≤ 10 | A single bad object fails |
| Draw list hash | Equal | IDs, order, instance counts, index counts |
| Depth p99 delta | ≤ 1e-6 | Relative to depth range |
| NaN/Inf pixels | 0 | Scan HDR target |

For S0 (one draw), the bar is stricter: byte-identical color on covered pixels when
the same DXIL is used; if only our translated DXIL is used, allow ≤1 LSB per channel
and require identical silhouettes.

### 1.6 What the gate does not measure

- Input latency (measure separately at G4 with a 240 fps camera or LDAT).
- Frame pacing/jitter beyond p95/p99.
- Audio sync, cutscenes, missions, streaming across districts.
- 1080p, FSR/DLSS, ray tracing.
- Full-game stability. A room is not the game.

---

## 2. Architecture

### 2.1 Shape

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│ user's game copy (outside repo)                                            │
│  game.exe + DLLs + RPF9 archives + saves                                   │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │ native x64, no CPU emulation
┌───────────────▼─────────────────────────────────────────────────────────────┐
│ g6n-host                                                                    │
│  PE loader / imports / TLS / exceptions (reuse ideas from victory)          │
│  GDK HLE: XGameRuntime, XMem, files, input, XAudio2 (stubs)                 │
│  selective AOT: hot render-submission functions -> C++ -> native calls      │
│  draw-list tap: game's D3D12X calls -> FrameIR (no per-draw translation)    │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │ FrameIR + resource handles
┌───────────────▼─────────────────────────────────────────────────────────────┐
│ g6n-render (D3D12 primary)                                                  │
│  frame graph, transient aliasing, barriers                                 │
│  bindless descriptors, root constants, indirect draws                      │
│  depth/mesh -> opaque -> shadows -> post -> UI                              │
│  PSO library, timestamp queries, budget enforcement                        │
└───────────────┬─────────────────────────────────────────────────────────────┘
                │ DXIL (SM 6.6)
┌───────────────▼─────────────────────────────────────────────────────────────┐
│ D3D12 driver / RTX 4060                                                     │
└─────────────────────────────────────────────────────────────────────────────┘

offline:
  XBCH/FSSM -> RDNA2 disasm -> SSA IR -> DXIL (primary) / SPIR-V (validation)
  RPF9/TTPF/BCPack -> BCn textures + meshlets -> residency cache
  x64 hot function -> C++ -> differential verifier -> native module
```

### 2.2 CPU: native x64, HLE, selective AOT

The Xbox Series CPU is x86-64. The game's code already runs natively in the current
layers; the CPU is not emulated. We keep that property.

- **Host boundary**: implement only the console system surface the room needs:
  `XGameRuntime`, `XMem`, file/storage, input, timing, and the D3D12X entry points
  that produce draws. Everything else can trap with a named error.
- **No full static recompilation.** Recompiling the whole title is a multi-year effort
  (Leonida has all 26,503 shaders translated and still no verified world frame). It is
  also unnecessary for CPU compatibility.
- **Selective AOT** targets only hot render-submission code. The goal is to remove HLE
  crossings and per-draw packing overhead, not to replace the game's logic.
- **Trampoline policy**: function-pointer/vtable slots are preferred over patching
  arbitrary function prologues. If a prologue hook is used, it must be unwind-safe,
  hash-guarded and reversible. Any mismatch falls back to the original bytes.
- **Lifter toolchain**: `iced-x86` (MIT) for decode, a custom C++20 emitter, clang-cl
  or MSVC, CMake. No runtime JIT. Unsupported instructions reject the function at
  lift time; they are never guessed.
- **Generated code is local-only.** Lifted C++ is a derivative of the user's game
  binary. It is written to `native/recomp/generated/` (gitignored), built on the user's
  machine, and never committed or distributed.

What AOT can realistically buy:

| Case | Expected effect |
|---|---|
| Leaf constant/draw packet packer, 2,000 calls/frame | 0.5–2 ms/frame; measure before integrating |
| Whole per-draw submission path, HLE calls replaced by native calls | 20–60 ms/frame at 2,000–3,850 draws; high effort |
| Game logic/animation | Small; the game already runs natively |
| Shader translation | None; that is offline |

The 30 fps thesis is mostly renderer-side. AOT is an optimization with a kill switch,
not the foundation.

### 2.3 Renderer: native D3D12 render graph

**Decision: D3D12 first, Vulkan after G4.** The DXIL path is the most mature on
Windows/NVIDIA, the current layers already produce DXIL, PIX and DirectStorage are
available, and one backend is enough for 30 days. A Vulkan backend would double the
work and add wave64/subgroup risk. The offline SPIR-V path is still built and validated
as a cross-check for the shader translator.

The renderer sits behind a `g6n-gfx` trait from day 1: `g6n-d3d12` implements it now;
`g6n-vk` is a post-G4 backend. No Vulkan code is on the 30-day critical path, but the
interface prevents a D3D12-shaped dead end.

Core choices:

| Concern | Choice | Why |
|---|---|---|
| API | D3D12 + Agility SDK 1.615+ | DXIL, mesh shaders, DirectStorage, PIX |
| Binding | Bindless SRV/UAV heap + root constants; `ResourceDescriptorHeap` in SM 6.6 | No per-draw descriptor table churn |
| Samplers | Static samplers + small sampler heap | Avoid root signature changes per material |
| Draw submission | GPU-driven cull → `ExecuteIndirect` per PSO | CPU cost proportional to PSOs, not draws |
| Culling | Two-pass Hi-Z occlusion + frustum + LOD | Target ≤2,500 draws at G3, ≤2,000 at G4 |
| Geometry | Mesh shaders where available; compute + indirect fallback | Console uses 9,282 mesh shaders in one census |
| Transients | Frame graph with aliasing; enhanced barriers if supported | Cut VRAM and barrier count |
| PSO | Offline DXIL + driver PSO library, keyed by state | Zero compilation in measured frames |
| Present | Flip model, waitable object, tearing allowed, latency 1 | Low present overhead |
| Queries | Timestamp per pass + budget counters | Attribute every millisecond |

Frame graph passes for `room01`:

```text
1. mesh/depth prepass        (or compute cull -> indirect mesh)
2. shadow atlas              (optional at G1/G2; required at G3)
3. opaque base pass          (HDR RGBA16F + depth)
4. decals/forward extras     (optional)
5. post: exposure, tonemap   (G1: simple; G3: game-like)
6. UI/HUD                    (G4 only)
```

Not in the first slice: ray tracing, volumetrics, SSR, motion blur, TAA, DOF, bloom
chains that need multiple passes. Add them only after the opaque frame is under budget.

### 2.4 Shaders: offline XBCH/FSSM → DXIL / SPIR-V

Pipeline:

```text
shader container (XBCH) from user's archive
  -> carve exact container bytes
  -> unpack FSSM native RDNA2 program (gfx1013)
  -> disassemble (LLVM AMDGPU or in-house gfx10 decoder)
  -> SSA IR, structure control flow, trace resources
  -> DXIL SM 6.6 (primary) or SPIR-V 1.3+ (validation/backup)
  -> validate (dxil.dll / dxv, spirv-val)
  -> content-addressed cache
```

Rules:

- **Zero runtime translation.** All shaders used by `room01` are translated and
  validated before the first measured frame.
- **Fail closed.** If a descriptor, root parameter or resource cannot be traced, the
  PSO fails with a named diagnostic. No silent zero descriptors.
- **Cache key**:
  `BLAKE3("g6n-shader-v1" || container_sha256 || translator_git_sha || target ||
  dxc_version || host_wave_size || bindless_layout_version)`.
- **Wave64**: the console corpus is mostly wave64 (Leonida reports 23,841 of 26,503).
  On NVIDIA's 32-lane waves, compute/mesh can be exact with emulation; cross-half lane
  ops in VS/PS/GS may be approximate. For `room01`, select shaders without cross-half
  dependencies first; validate any approximate shader with a GPU differential test.
- **Mesh shaders**: translate NGG/primitive programs to amplification + mesh
  (`AS_6_6`/`MS_6_6`). If a program cannot be represented, fall back to compute culling
  + `ExecuteIndirect` indexed draw for that material, and record the fallback.
- **Root signature**: one bindless table + 16 DWORD root constants + static samplers.
  If the driver rejects a shader that uses `ResourceDescriptorHeap`, fall back to an
  explicit descriptor table for that PSO and log it.
- **Warm cache**: translating all 25,758 containers takes minutes and ~13 GB in the
  AnyXboxX report. `room01` needs only a few hundred; full-game warm is a G3/G4 task.

Existing translator use:

- `victory-shader` (VItoriaBr, GPL-3.0-or-later) is the strongest DXIL path measured
  on this title. In Phase 1 it is invoked as an **external tool** on a copy of the
  repo; no code is linked. If the slice proves out, vendor the needed crates with
  attribution under GPL-3.0.
- Leonida's SPIR-V corpus (26,503/26,503 validated) is the cross-check for the
  SPIR-V backend and for shader coverage. Do not copy code without a license review.
- Xbox2Windows (MIT) is the reference for gfx1013→DXIL lowering and CPU lifting; MIT
  code can be vendored with its notice.

### 2.5 Assets and streaming for 8 GB VRAM / 16 GB RAM

The native path reads the user's archives **in place**. It does not extract the whole
game, and it does not copy assets into the repo.

```text
RPF9 archive (read-only, memory-mapped)
  -> TOC / resource lookup
  -> TTPF texture pool or embedded texture
  -> BCPack decode -> BC1/BC3/BC4/BC5/BC6H/BC7 blocks
  -> console tiling -> linear blocks (or GPU detile)
  -> mip policy -> upload ring -> residency

RPF9 drawable
  -> vertex/index streams
  -> meshlet build (offline cache)
  -> bounds + material table
  -> GPU buffers
```

Policies:

- **Texture residency**: load mip 0–3 for visible materials; stream tails; prefer
  lower mips at distance. Keep BCn compressed on the GPU; do not decompress to RGBA.
- **Priority**: visible this frame > visible next frame > prefetch in 30 frames >
  background. Pin resources referenced by in-flight command lists.
- **Eviction**: at 90% of the 7.2 GB budget, evict lowest-priority unpinned resources.
  Never evict inside a frame's command list.
- **Uploads**: DirectStorage on NVMe, batched (64 requests, 1–4 MB each), 256 MB
  staging ring, copy queue. Fallback to overlapped file I/O if DirectStorage is not
  available. No blocking upload on the render thread.
- **Hitch budget**: ≤50 ms at G2, ≤16 ms at G4; ≤1% of frames may exceed 40 ms.
- **16 GB RAM**: cache compressed source blocks, not decoded textures. Hard cap
  process commit at 14.5 GB; if exceeded, evict and log. A 32 GB pagefile on NVMe is
  mandatory on this machine.

### 2.6 Memory budget

VRAM (7.2 GB hard cap, 8.0 GB physical):

| Category | VRAM | RAM | Notes |
|---|---:|---:|---|
| OS / desktop / driver | 600 MB | 2,500 MB | Measured, not assumed |
| Game logic / mapped image | 0 | 4,500 MB | Native x64, HLE |
| Asset source cache | 0 | 5,000 MB | Compressed blocks, not decoded |
| Textures resident | 4,200 MB | 0 | BCn, mips 0–3 + tails |
| Geometry / meshlets | 1,000 MB | 500 MB staging | Vertex/index/meshlet |
| Render targets | 400 MB | 0 | HDR, depth, normals, motion |
| Shadow maps | 300 MB | 0 | One atlas |
| Scratch / indirect / constants | 300 MB | 200 MB | Ring buffers |
| Swapchain | 30 MB | 0 | 3 buffers, 720p |
| Reserve | 370 MB | 1,800 MB | Fragmentation / spikes |
| **Total** | **7,200 MB** | **14,500 MB** | Caps, not targets |

Notes:

- `IDXGIAdapter3::QueryVideoMemoryInfo` reports the OS budget, which is often below
  8 GB after desktop composition. Treat 7.2 GB as the ceiling and 6.8 GB as the
  comfort zone.
- 16 GB RAM is the most likely hard wall, not VRAM. XCL reports ~15 GB committed in
  menus on a 32 GB machine. If the full game needs that before `room01`, this laptop
  cannot run the live gate. The replay gate can still succeed.
- Commit is measured with `PROCESS_MEMORY_COUNTERS_EX.PrivateUsage`; the system commit
  limit is logged with `GlobalMemoryStatusEx`.

### 2.7 Threads and frame loop

| Thread | Work | Budget |
|---|---|---:|
| Main | Game tick, camera, input | 5 ms |
| Render | Cull, build FrameIR, record command lists | 5 ms |
| Submit | Queue, fences, present | 2 ms |
| Streaming ×2 | DirectStorage / decode / upload | async |
| Compile | Offline only; background PSO warm for unseen state | not in frame |

Frame loop:

```text
input -> game tick (native x64) -> draw list tap -> GPU cull
      -> indirect args -> record -> submit -> present
```

No runtime shader compilation, no per-draw `Map/Unmap`, no per-draw descriptor
creation, no full-screen copy-back.

### 2.8 Capture/replay IR

The first slice needs a stable, testable boundary. `FrameIR` is that boundary.

```rust
pub struct FrameIR {
    pub frame_id: u64,
    pub camera: Camera,
    pub passes: Vec<PassIR>,
    pub resources: Vec<ResourceIR>,
    pub shaders: Vec<ShaderIR>,
    pub stats: SourceStats,
}

pub trait FrameSource { fn frame(&mut self) -> anyhow::Result<FrameIR>; }
pub trait AssetResolver {
    fn buffer(&self, id: ResourceId) -> anyhow::Result<&[u8]>;
    fn texture(&self, id: ResourceId) -> anyhow::Result<TextureView>;
}
pub trait PipelineProvider {
    fn pso(&self, key: PipelineKey) -> anyhow::Result<&Pipeline>;
}
pub trait RenderBackend {
    fn execute(&mut self, frame: &FrameIR) -> anyhow::Result<FrameStats>;
}
```

The on-disk capture is a JSON manifest plus blobs. The manifest contains IDs, sizes,
formats, hashes, pipeline state and shader references; blobs are game-derived and live
outside the repo.

```json
{
  "version": 1,
  "source": {
    "build": "1.0.2.1",
    "save_sha256": "…",
    "frame": 900,
    "draw_count": 2140,
    "camera_sha256": "…"
  },
  "resources": [
    {"id": "vb0", "kind": "buffer", "size": 1048576, "sha256": "…", "blob": "blobs/vb0.bin"}
  ],
  "shaders": [
    {"id": "vs0", "stage": "vs", "container_sha256": "…", "dxil_sha256": "…"}
  ],
  "draws": [
    {"id": 0, "pso": "pso0", "vb": ["vb0"], "ib": "ib0", "cb": "cb0",
     "srv": ["tex0"], "index_count": 1234, "topology": "trianglelist"}
  ]
}
```

### 2.9 Reuse and license boundaries

| Source | License | Use in this plan |
|---|---|---|
| VItoriaBr / fxceless / DexNom | GPL-3.0-or-later | Reference and external translator; code may be vendored with attribution |
| Leonida | GPL-3.0-or-later | SPIR-V corpus and asset-format reference; code only after review |
| Xbox2Windows | MIT | CPU lifter / gfx1013→DXIL reference; vendoring allowed with notice |
| XCL | **GPL-2.0-only** | **No code copying**; behavior/ideas only, clean-room notes |
| omonkeyz/xbox-emulator | GPL-3.0 | General runtime reference |
| RAGE9-Recomp | none (repo empty as of 2026-11-25) | **Do not rely on it** |
| RenderDoc / PIX | MIT / proprietary tool | Capture and validation |
| D3D12 Agility SDK / DXC | MIT | Build/runtime |

The project is GPL-3.0-or-later. GPL-2.0-only code is incompatible with GPL-3.0 for
code reuse; keep XCL as a black-box reference and document the separation in
`docs/licensing.md`. Generated recompiled code is a derivative of the user's game and
must stay local.

### 2.10 Decisions

- **ADR-0001: D3D12 primary, Vulkan post-G4.** One backend in 30 days; DXIL is the
  proven path on this title and NVIDIA.
- **ADR-0002: replay-first, live-second.** Renderer work must not be blocked by
  booting the full game. Capture is the contract; live integration is G2.
- **ADR-0003: selective AOT with fallback, not full static recompilation.** The CPU is
  already native; recompile only hot submission code.
- **ADR-0004: generated game-derived code and captures never enter git.** Manifests
  and metrics only.

---

## 3. Smallest first slice

### 3.1 S0: one draw

**Goal**: prove the native D3D12 renderer can consume one real game draw and produce
the same pixels as the current layer, before adding a second draw or a second pass.

The current layer's built-in `VICTORY_CAPTURE` writes screenshots and draw-op logs, not
full pipeline state. Use RenderDoc or PIX for the state capture; the built-in capture
is the visual/ops oracle.

Selection rule for draw `D0` from the `room01` capture:

- indexed, non-mesh first (reduces variables; mesh draw is S0c);
- opaque, no blending, no alpha test, no stream output, no MSAA, no RT;
- one VS + one PS, no geometry/amplification stage;
- one 64–256 B CBV, ≤4 SRVs, one sampler;
- ≤64k indices, 16-bit index buffer;
- depth test on, depth write on, single render target;
- viewport 1280×720 (or a 512×512 sub-rect for debugging).

If no draw matches, relax one criterion at a time and record which. Do not start with
a mesh or a blended draw. If the room's first valid unit is a compute dispatch (for
example a full-screen setup pass), use the same interface shape with `DispatchIR`
(one SRV, one UAV, 8×8 groups) and the same verification; prove one dispatch before a
full pass.

Inputs:

| Input | Source |
|---|---|
| Vertex/index buffers | Capture blobs, hashed |
| Constants | Captured CBV bytes, byte-exact |
| Textures/samplers | Capture textures, decoded to BCn/linear |
| VS/PS | S0a: host DXIL from capture; S0b: our XBCH→DXIL |
| Pipeline state | Captured blend/depth/raster/viewport/scissor |
| Render target | 1280×720 RGBA16F + D32, cleared to known values |

Outputs:

| Output | Format | Verification |
|---|---|---|
| Color | RGBA16F | Pixel compare on covered pixels |
| Depth | D32_FLOAT | p99 delta ≤1e-6 |
| Stats | JSON | draw args, PSO key, CPU/GPU time |
| Trace | JSONL | descriptor bindings, root constants |

Interfaces:

```rust
pub struct DrawIR {
    pub id: u32,
    pub pipeline: PipelineKey,
    pub vertex_buffers: Vec<BufferView>,
    pub index_buffer: Option<BufferView>,
    pub root_constants: Vec<u32>,
    pub srv: Vec<ResourceId>,
    pub uav: Vec<ResourceId>,
    pub viewport: Viewport,
    pub scissor: Rect,
    pub topology: Topology,
    pub index_count: u32,
}

pub trait OneDrawRenderer {
    fn render(&mut self, draw: &DrawIR, target: &RenderTargets) -> anyhow::Result<DrawStats>;
}
```

Same-scene/save contract: every reference and native run pins the save SHA-256, the
game executable hash, the camera-path hash and the frame serial. If frame numbering
differs between runs, use the first frame with ≥500 draws and pin its draw-list hash.
No comparison is valid across different saves, builds or camera paths.

Two-step proof:

- **S0a — renderer bring-up with host DXIL.** Render `D0` using the DXIL that the
  current layer already produced. This isolates the render graph, descriptors, root
  signature and state. Expected result: exact match to the layer's draw output.
- **S0b — native shader path.** Replace host DXIL with our offline XBCH→DXIL output
  for the same draw. Expected result: same pixels (≤1 LSB) and same silhouettes. A
  mismatch is a translator or binding-map bug; fix it before adding draws.

If S0a matches but S0b does not, the renderer is fine and the shader path is wrong.
If S0a does not match, stop and fix state/root signature/descriptors; do not blame the
translator.

### 3.2 S1: one room, replay

Render the entire `room01` frame from the capture, fixed camera, no game logic:

- all draws in the captured frame, including mesh and transparent (transparent last);
- passes: depth/mesh → opaque → simple tonemap; shadows optional;
- 600 frames, 3 runs, 720p;
- compare against the layer's HDR scene color and draw list.

Exit: p50 ≤ 200 ms (5 fps), p95 ≤ 240 ms, draw count parity ≥99%, 0 PSO misses,
VRAM ≤7.2 GB, image thresholds from §1.5. This is G1.

S1 is deliberately a replay. It proves the native renderer can render the room at
least as fast as the best known layer (5 fps) without the game runtime in the loop.

### 3.3 H1: one hot function

The first AOT unit is a **leaf draw-packet/constant packer** in the title's renderer
(working name `RDPack`). The exact function is selected by profiling, not guessed:

- Run the current layer with a sampling profiler for 30 s in `room01`.
- Rank functions by exclusive time × calls/frame.
- Pick the hottest function that:
  - is called ≥500×/frame;
  - writes only a bounded output buffer (or has clearly enumerable side effects);
  - uses only the supported x64 subset (no exceptions, no indirect jumps, no TLS,
    no syscalls, no x87);
  - has a stable byte hash for build 1.0.2.1.
- Record `module`, `rva`, `size`, `sha256(bytes)`, call count, inclusive ms and a
  recorded input corpus in `hot-functions.json`.

The document does not hard-code an RVA: the binary is user-supplied and relocated.
The manifest pins the bytes hash; a different build is rejected. If `RDPack` is not
liftable, the next candidates are, in order: a frustum/sphere visibility test, a
matrix-palette/skinning transform, and a draw-argument packer. The selection rule and
the differential harness stay the same.

Manifest:

```json
{
  "module": "game.exe",
  "rva": 0,
  "size": 0,
  "sha256": "…",
  "abi": "win64",
  "purity": "writes [out, out+cap)",
  "calls_per_frame": 0,
  "inclusive_ms": 0.0,
  "supported": true
}
```

Generated interface:

```cpp
// Microsoft x64 ABI; pointers are guest addresses in the same process.
extern "C" uint64_t g6n_h1_pack(const G6nPackArgs* args, uint8_t* out, size_t cap);
```

Verification:

- **Differential**: run original mapped bytes and lifted C++ on the same inputs;
  compare all GPRs, XMM registers, flags and written memory. 100k generated vectors +
  10k recorded invocations. Integer results bit-exact; floats bit-exact except NaN
  payloads; no out-of-bounds writes (guard pages).
- **Performance**: standalone lifted function must be within 1.2× of the original, or
  it is not worth integrating.
- **Frame-level**: `G6N_RECOMP=off|on` must produce identical draw-list hash and image.
  Integrate only if frame time improves ≥5%; otherwise keep it as a research result.

Expected gain: 0.5–2 ms/frame for a leaf packer. That is not 30 fps by itself. The
larger prize is H1b: lift the per-draw submission path and replace D3D12X HLE calls
with native `g6n::submit_draw` calls. H1b is a G3 stretch, not a G1 requirement.

Stop rule: if H1 is not bit-exact in 2 days, or is slower, shelve AOT and spend the
time on the renderer. The 30 fps thesis does not depend on it.

### 3.4 S2: live room

Connect the native renderer to the running game:

- game code runs natively through the host;
- input/camera/game logic run at the game's tick;
- the draw-list tap produces `FrameIR` per frame (no capture file);
- assets stream from the user's archives;
- AOT optional;
- 720p, 600 frames, deterministic camera path first, then human input.

Exit: 5 min playable, p50 ≤ 100 ms (10 fps), p95 ≤ 130 ms, 0 dropped draws, VRAM
≤7.2 GB, commit ≤14.5 GB, image parity. This is G2.

If S2 cannot be reached by D18, the plan stops claiming live 30 fps and reports the
replay result plus the integration blocker.

---

## 4. 30-day milestones

Day 0 = 2026-11-25; G4 target = 2026-12-25. Thirty calendar days, ~22 working days.
This assumes 2–3 people; a solo engineer should expect G2 in 30 days and G4 much later.

### 4.1 Gate ladder

| Gate | Day | Scope | FPS / p50 | p95 | Draws | Memory caps | Correctness | Artifact |
|---|---|---:|---|---:|---:|---|---|---|
| G0 | D2 | Truth baseline + synthetic 720p30 | synthetic 30 / 33.3 ms | 40 ms | synthetic | 7.2 GB / 14.5 GB | T1, T2 | `benchmarks/g0.json` |
| G1 | D9 | One draw + full room replay | 5 fps / 200 ms | 240 ms | parity | 7.2 / 14.5 | T3–T5, T7 | `benchmarks/g1.json` |
| G2 | D16 | Live room, input, native renderer | 10 fps / 100 ms | 130 ms | ≤3,500 | 7.2 / 14.5 | T6, T11, T12 | `benchmarks/g2.json` |
| G3 | D23 | Culling, batching, mesh, streaming | 20 fps / 50 ms | 65 ms | ≤2,500 | 7.2 / 14.5 | T8, T9 | `benchmarks/g3.json` |
| G4 | D30 | 720p30 playable room | 30 fps / 33.3 ms | 40 ms | ≤2,000 | 7.2 / 14.5 | all T1–T14 | `benchmarks/g4.json` |

G1/G2 frame times for replay-only runs are render-thread times, labeled `replay_ms`.
G2 live and later use present-to-present. Do not compare them directly without the
label. T11 is N/A only if AOT is explicitly shelved at G1; record the decision and
keep the kill switch tested.

### 4.2 Schedule by lane

| Days | Renderer | Shader | Assets/streaming | AOT | Measurement |
|---|---|---|---|---|---|
| D0–D2 | Device, swapchain, synthetic stress scene | Fixture DXIL validation | Budget harness | Profile current layer | Baseline 3 runs, room capture |
| D3–D5 | S0a one draw | Host DXIL import | Capture blobs → GPU | Hot-function manifest | Draw parity |
| D6–D9 | S1 room replay | S0b our DXIL | Texture/geometry upload | H1 lift + diff | G1 gate |
| D10–D12 | Live tap, frame loop | Room shader coverage | Archive reader | H1 integration (optional) | Live smoke |
| D13–D16 | Live room correctness | PSO warm | Residency v1 | H1 measurement | G2 gate |
| D17–D20 | GPU culling, indirect | Mesh path | Streaming scheduler | H1b decision | Pass timing |
| D21–D23 | Shadows/post, budget cuts | Wave64 fixes | Eviction/hitch | — | G3 gate |
| D24–D27 | 30 fps optimization | PSO/state tuning | Memory tuning | — | 3-run gate |
| D28–D30 | Soak, rollback, report | Final coverage | Final budgets | Report | G4 gate |

Parallelism is important: the shader lane can work from the capture while the
renderer lane builds the device/passes; the asset lane can decode textures while the
renderer uses synthetic placeholders.

### 4.3 G0 — truth baseline (D0–D2)

Work:

- Freeze build, save, driver, OS, GPU clocks.
- Reproduce the current layer 3× at 720p; record p50/p95, draws, VRAM, commit.
- Capture `room01` frame with RenderDoc or PIX; import to IR; count draws, mesh draws,
  textures, shaders, PSOs.
- Build the synthetic 720p30 stress scene (2,000 instanced draws, 1M triangles,
  4× overdraw) and validate the timing harness.
- Measure the actual 16 GB commit headroom before the game loads and at `room01`.

Exit criteria:

- baseline JSON with 3 runs; variance ≤10% between runs;
- synthetic p50 ≤33.3 ms, p95 ≤40 ms;
- capture resolves 100% of resources/shaders (or a named, bounded unknown list);
- no game data in `git status`.

Stop rule: if the baseline is not reproducible, fix the harness before any renderer
work. A 2× measurement error makes every later gate meaningless.

### 4.4 G1 — 5 fps replay (D3–D9)

Work:

- S0a: one draw with host DXIL, exact match.
- S0b: one draw with our DXIL, ≤1 LSB.
- S1: full room replay, fixed camera, 600 frames.
- Warm all room PSOs; second warm run must make 0 new PSOs.
- H1: lift one hot leaf, 100k differential vectors.

Exit criteria:

- p50 ≤200 ms, p95 ≤240 ms, 3 runs;
- draw count parity ≥99%; 0 PSO misses; 0 dropped draws;
- SSIM ≥0.97, ΔE p95 ≤3.0, IoU ≥0.995;
- VRAM ≤7.2 GB, commit ≤14.5 GB;
- H1 bit-exact (or explicitly shelved).

Why 5 fps: it matches the best known layer on a stronger GPU (AnyXboxX 4.8–5.4 fps on
RTX 4070 Super). If the native replay cannot match that, the problem is the renderer or
the capture, not the hardware.

### 4.5 G2 — 10 fps live (D10–D16)

Work:

- Draw-list tap from the running game to `FrameIR`; no capture file.
- Input/camera/game tick; native renderer presents.
- Archive reader/residency v1; no full-room preload beyond budget.
- PSO cache; zero in-frame compiles.
- H1 integration if it passed G1 and gives ≥5%.

Exit criteria:

- 5 min playable; walk 3 m; door opens; no crash;
- p50 ≤100 ms, p95 ≤130 ms, 3 runs;
- draws ≤3,500; 0 dropped; 0 in-frame PSO compiles;
- VRAM ≤7.2 GB, commit ≤14.5 GB;
- image parity thresholds; `G6N_RECOMP=off|on` identical.

Stop rule: if live integration is not working by D18, drop it and publish a replay-only
result. Do not claim "playable 30 fps" from a replay.

### 4.6 G3 — 20 fps (D17–D23)

Work:

- GPU-driven frustum + Hi-Z occlusion; indirect draws per PSO.
- Mesh shader path for mesh draws; compute+indirect fallback for failures.
- Shadows and a game-like tonemap; keep post cheap.
- Streaming scheduler: async uploads, eviction, hitch budget.
- Reduce draws to ≤2,500; cut overdraw; LOD/mip bias.
- 30-minute soak.

Exit criteria:

- p50 ≤50 ms, p95 ≤65 ms, 3 runs;
- CPU record ≤25 ms; GPU ≤45 ms; present ≤2.5 ms;
- draws ≤2,500; 0 dropped; 0 PSO misses;
- 30 min soak, no TDR/device loss; VRAM/commit stable;
- image parity thresholds.

### 4.7 G4 — 30 fps (D24–D30)

Work:

- Cut GPU to ≤28 ms: base pass, shadows, post, overdraw.
- Cut CPU to ≤12 ms: record, submit, culling.
- Hold 2,000 draws; keep 4.2 GB textures; no thrash.
- 3 × 600 frames; 30 min soak; 10 min play.
- Rollback test; final report.

Exit criteria:

- p50 ≤33.3 ms, p95 ≤40 ms, p99 ≤50 ms; 3 runs, median;
- 0 dropped draws; 0 in-frame compiles; 0 shader misses;
- VRAM ≤7.2 GB; commit ≤14.5 GB; growth <64 MB/10 min;
- no device loss/TDR; image parity; 10 min playable;
- T1–T14 pass.

If G4 fails, publish the wall report: per-pass GPU times, CPU record time, VRAM/commit
curves, draw counts, and the specific blocker. Do not round 25 fps up to 30.

### 4.8 Stop rules / decision tree

```text
G0 baseline not reproducible           -> stop, fix harness
S0a one draw not exact in 2 days       -> simplify draw / fix state, no new features
G1 replay < 5 fps after 3 passes       -> renderer/capture bug; do not go live
G2 live not working by D18             -> replay-only report; no 30 fps claim
Commit > 14.5 GB at G2                 -> 16 GB wall; require 32 GB before G3
VRAM > 7.2 GB or eviction thrash       -> cut texture pool/mips; if still, wall
GPU > 45 ms at 720p, no RT, simple pass-> hardware/driver wall; no 30 fps
p95 > 40 ms after 3 runs               -> no 30 fps claim
Any TDR/device loss                    -> fail; fix or stop
```

### 4.9 Effort

| Role | FTE | 30 days | Main deliverable |
|---|---:|---:|---|
| Graphics/renderer | 1.0 | 30 | D3D12 frame graph, passes, PSO, timing |
| Systems/AOT | 0.5–1.0 | 15–30 | Host tap, selective lift, differential |
| Shader/tools | 0.5 | 15 | Offline translation, coverage, validation |
| Assets/streaming | 0.5 | 15 | RPF9/TTPF/BCPack, residency |
| Measurement | 0.5 | 15 | Harness, gates, reports |
| **Total** | **3.0** | **90 person-days** | Vertical slice |

Solo estimate: 60–90 days to G2/G3; G4 likely 4–6 months. A full port is 9–18 months
with 4–6 FTE, plus 6+ months for a production asset pipeline. This plan is a probe,
not a product schedule.

---

## 5. Risks

### 5.1 Risk table

| ID | Risk | P | I | Trigger | Mitigation | Fallback / stop |
|---|---|---|---|---|---|---|
| R1 | 8 GB VRAM too small | High | High | >7.2 GB or eviction thrash | 4.2 GB texture pool, mips 0–3, BCn, 720p, no RT | Cut to 3.6 GB textures, lower mips; if still, wall |
| R2 | 16 GB RAM too small | High | High | commit >14.5 GB or Windows 1455 | 14.5 GB cap, compressed cache, pagefile 32 GB NVMe | Require 32 GB; replay-only on this laptop |
| R3 | 256 GB/s bandwidth | Medium | High | GPU >90% busy, <25 fps at 720p | Depth prepass, overdraw cuts, BCn, lower mips | FSR1/2 at lower internal res (separate gate) |
| R4 | Mesh/root signature gaps | High | High | PSO creation fails or wrong binds | Capture state, bindless root sig, fail closed, one-draw first | Compute+indirect fallback; skip effect |
| R5 | RAGE streaming hitches | High | High | >50 ms hitch, >5 evictions/frame | DirectStorage, priority, preload room, pin in-flight | Preload room, reduce view distance/mips |
| R6 | Wave64 on NVIDIA | High | Medium | Visual diffs in VS/PS/GS | Select non-cross-half shaders; emulate; validate | Compute path for that shader; accept visual delta only if ≤threshold |
| R7 | Shader coverage | Medium | High | Room shader fails translation/validation | Scope to room; fix translator; list failures | Fallback shader or skip object; no silent zero |
| R8 | PSO compile in frame | Medium | High | any `made` during measured frames | Warm 2×; PSO library; background only | Pre-warm more; reduce material variants |
| R9 | AOT wrong/slow | Medium | High | differential mismatch or <5% gain | Subset, hash guard, fallback, kill switch | Disable AOT; renderer-only path |
| R10 | Capture fidelity | Medium | High | missing mesh/indirect state | Non-mesh S0; PIX fallback; manual tap | Synthetic fixture + later live tap |
| R11 | Legal/licensing | Medium | High | code provenance unclear | No XCL code; notices; local-only generated code | Legal review; remove component |
| R12 | TDR/device loss | Medium | High | 4101 / `DEVICE_REMOVED` | Small workloads, debug layer, timeouts | Fail gate; fix shader/PSO |
| R13 | Laptop thermals | Medium | Medium | clock <90% or >80 °C | High Performance, AC, cooling | Cap frame rate/undervolt; report |
| R14 | Effort/time | High | High | gate slips >3 days | Cut scope, parallel lanes, stop rules | G2/G3 report, not 30 fps |

### 5.2 Deep dives

**8 GB VRAM.** The current layer uploads 6.8–7.1 GB of textures and still has 23,000
waits. A native renderer must not repeat that. The 4.2 GB texture pool is the single
largest budget line; it assumes 720p, low, and aggressive mips. If the room needs more,
the first cut is view distance and mip bias, not resolution. Monitor
`QueryVideoMemoryInfo` and log evictions per frame. A single 4K texture can blow the
budget; clamp source mips at load.

**16 GB RAM.** This is the most under-discussed wall. XCL's retail-game test reports
~15 GB committed in menus on a 32 GB machine. If GTA VI's `room01` needs 10–12 GB
before rendering, a 16 GB laptop will page or fail. The replay slice avoids the full
runtime and may fit; the live gate may not. Measure at G0, before writing renderer
code. If commit >14.5 GB, the honest answer is "32 GB required" for live 30 fps.

**Mesh and root signatures.** The game uses mesh shaders (9,282 in Leonida's census;
3,349 mesh records in one VItoriaBr frame). Console NGG/primitive shaders do not map
1:1 to D3D12 amplification/mesh. Vertex input, `SV_VertexID`, payload layout, and
cross-half wave ops are the usual failure points. Start with a non-mesh draw; add one
mesh draw with a scissor/debug mode that renders 1×1 pixel to catch hangs; then full
mesh. Root signatures: one bindless table + root constants; if a shader cannot be
remapped, fail the PSO and list the resource, never bind zero.

**RAGE streaming.** RPF9/TTPF/BCPack are complex; the current layer's 250–760 ms copies
and 846 ms lock waits show what happens when streaming is synchronous. The native path
must decode off-thread, upload on a copy queue, and never block the render thread.
For `room01`, preload the room; introduce streaming at G3. If a hitch >50 ms appears,
cut view distance before adding more cache.

**Legal/licensing.** The project is GPL-3.0-or-later. VItoriaBr/fxceless/Leonida are
GPL-3.0-compatible; Xbox2Windows is MIT; XCL is GPL-2.0-only and must not be copied.
Generated AOT code is derivative of the game; keep it local. Captures contain game
assets; keep them outside the repo. No keys, decryption, DRM bypass, or distribution
of game files. This is an engineering plan, not legal advice; consult counsel before
any distribution.

**Effort.** A native renderer for one room is 1–2 months of focused work even with a
capture. A full game port is a multi-year, multi-person project. The 30-day plan is
designed to produce evidence: either a playable room at 30 fps, or a measured wall
(VRAM, RAM, bandwidth, mesh/root signature, streaming) with numbers.

---

## 6. Build, run and file tree

### 6.1 Prerequisites (pin versions)

| Tool | Version | Notes |
|---|---|---|
| Windows | 11 23H2+ | 10 22H2 works with Agility SDK |
| Visual Studio 2022 Build Tools | 17.10+ | Desktop C++, Windows SDK 10.0.26100 |
| Rust | 1.88.0 MSVC | `rust-toolchain.toml` pins |
| CMake / Ninja | 3.24+ / 1.11+ | Native recomp module |
| DXC | 1.8.2502 | `dxc.exe`, `dxil.dll`; pin |
| D3D12 Agility SDK | 1.615.0+ | App-local `D3D12Core.dll` |
| RenderDoc | 1.37+ | Or PIX 2503+; capture tool |
| Python | 3.12 | Bench/image compare |
| Vulkan SDK | 1.3.296+ | Optional: `spirv-val` |
| NVIDIA driver | pinned | Log version in every run |

```powershell
winget install Microsoft.VisualStudio.2022.BuildTools
winget install Kitware.CMake
winget install Ninja-build.Ninja
winget install Rustlang.Rustup
winget install Python.Python.3.12
rustup default 1.88.0-x86_64-pc-windows-msvc
```

DXC, Agility SDK, RenderDoc and the Vulkan SDK are downloaded from their pinned
releases; do not use "latest" in a gate run. Add the policy tool once:

```powershell
cargo install cargo-deny --locked
```

The workspace defines `cargo xtask` in `.cargo/config.toml`:

```toml
[alias]
xtask = "run --package xtask --"
```

### 6.2 Environment (all paths outside the repo)

```powershell
$env:G6N_DATA    = 'D:\g6n-data'
$env:G6N_GAME    = 'D:\g6n-data\game'          # user's copy
$env:G6N_SAVE    = 'D:\g6n-data\saves\room01'
$env:G6N_CACHE   = 'D:\g6n-data\cache'
$env:G6N_REF     = 'D:\g6n-data\ref\room01'
$env:G6N_CAPTURE = 'D:\g6n-data\captures'
$env:G6N_OUT     = 'D:\g6n-data\out'
$env:G6N_DXC     = 'C:\tools\dxc\bin\x64\dxc.exe'
$env:G6N_VICTORY = 'D:\g6n-data\tools\VItoriaBr\target\diag\victory.exe'
```

`g6n` refuses to read game data from inside `D:\git\gta6-30fps`.

### 6.3 Build

```powershell
cd D:\git\gta6-30fps
cargo build --release --workspace
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings

cmake -S native/recomp -B out/native-recomp -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DG6N_DXC="$env:G6N_DXC"
cmake --build out/native-recomp
ctest --test-dir out/native-recomp --output-on-failure
```

### 6.4 Baseline with the current layer (read-only copy)

Never build in `D:\git\VItoriaBr`. Copy it outside the repo:

```powershell
robocopy D:\git\VItoriaBr D:\g6n-data\tools\VItoriaBr /E /XD target .git
cd D:\g6n-data\tools\VItoriaBr
cargo build --profile diag -p victory --features diagnostics
```

Three baseline runs (this launches the game; run it in the implementation phase, not
while writing this plan):

```powershell
cd D:\git\gta6-30fps
.\tools\bench\run-baseline.ps1 -Runs 3 -Frames 120 -Frame 900 -Out $env:G6N_REF
```

The script sets the VItoriaBr capture env vars, invokes `$env:G6N_VICTORY`, parses
`game-stderr.log` with `tools/bench/parse_victory_log.py`, and writes
`baseline.json`. It captures `frame-<n>.png` and `frame-<n>-ops.txt` only; no game
data is copied into the repo.

### 6.5 Capture, import, translate, warm

```powershell
# 1. External capture (RenderDoc/PIX) of the room01 frame.
.\tools\capture\capture-room.ps1 -Frame 900 -Out $env:G6N_CAPTURE\room01.rdc

# 2. Export one draw + the layer's HDR target to the IR folder.
python .\tools\capture\export-draw.py `
  --rdc $env:G6N_CAPTURE\room01.rdc `
  --frame 900 --draw 0 `
  --out $env:G6N_CAPTURE\room01.ir

# 3. Validate the IR: every resource, shader and PSO resolves.
.\target\release\g6n.exe capture validate --capture $env:G6N_CAPTURE\room01.ir

# 4. Import console containers + host DXIL for the one-draw comparison.
.\target\release\g6n.exe capture import `
  --src $env:G6N_CAPTURE\room01.ir `
  --game $env:G6N_GAME `
  --out $env:G6N_CAPTURE\room01.full

# 5. Translate room shaders offline (S0a uses host DXIL; S0b uses this cache).
.\target\release\g6n.exe shaders translate `
  --capture $env:G6N_CAPTURE\room01.full `
  --backend dxil --validate `
  --victory $env:G6N_VICTORY `
  --out $env:G6N_CACHE\shaders

# 6. Warm PSOs twice; the second run must make zero new PSOs.
.\target\release\g6n.exe pso warm `
  --capture $env:G6N_CAPTURE\room01.full `
  --cache $env:G6N_CACHE\pso `
  --adapter "RTX 4060" --repeat 2
```

Shader validation:

```powershell
& $env:G6N_DXC -T ps_6_6 -E main -Fo $env:G6N_OUT\fixtures\ps.dxil `
  .\tests\fixtures\shaders\ps.hlsl
& $env:G6N_DXC -T ms_6_6 -E main -Fo $env:G6N_OUT\fixtures\ms.dxil `
  .\tests\fixtures\shaders\ms.hlsl
spirv-val --target-env vulkan1.3 $env:G6N_OUT\fixtures\ps.spv
```

### 6.6 Replay, compare, gate

```powershell
# S0a: one draw with the layer's host DXIL (renderer bring-up).
.\target\release\g6n.exe replay `
  --capture $env:G6N_CAPTURE\room01.full --draw 0 --shader-source host `
  --width 1280 --height 720 --frames 600 --warmup 120 `
  --out $env:G6N_OUT\s0a --json $env:G6N_OUT\s0a\metrics.jsonl

# S0b: same draw with our offline XBCH->DXIL translation.
.\target\release\g6n.exe replay `
  --capture $env:G6N_CAPTURE\room01.full --draw 0 --shader-source native `
  --width 1280 --height 720 --frames 600 --warmup 120 `
  --out $env:G6N_OUT\s0b --json $env:G6N_OUT\s0b\metrics.jsonl

# S1: full room replay, fixed camera.
.\target\release\g6n.exe replay `
  --capture $env:G6N_CAPTURE\room01.full --frame 900 --shader-source native `
  --width 1280 --height 720 --frames 600 --warmup 120 `
  --out $env:G6N_OUT\s1 --json $env:G6N_OUT\s1\metrics.jsonl

# Image parity against the layer's HDR target (exported by export-draw.py).
python .\tools\bench\compare_images.py `
  --ref $env:G6N_REF\hdr --test $env:G6N_OUT\s1\hdr `
  --json $env:G6N_OUT\s1\compare.json `
  --ssim-min 0.97 --de2000-p95 3.0 --iou-min 0.995

# Gate evaluation.
python .\tools\bench\run_gate.py --gate g1 `
  --metrics $env:G6N_OUT\s1\metrics.jsonl `
  --compare $env:G6N_OUT\s1\compare.json `
  --json .\benchmarks\g1.json

# Final gate: 3 runs, 600 measured frames each, 30-minute soak.
python .\tools\bench\run_gate.py --gate g4 --runs 3 --frames 600 --warmup 120 `
  --soak-seconds 1800 `
  --metrics $env:G6N_OUT\g4\metrics.jsonl `
  --compare $env:G6N_OUT\g4\compare.json `
  --json .\benchmarks\g4.json
```

### 6.7 Live room

```powershell
.\target\release\g6n.exe live `
  --game $env:G6N_GAME --save $env:G6N_SAVE `
  --width 1280 --height 720 `
  --camera-path $env:G6N_REF\camera.json `
  --shader-cache $env:G6N_CACHE\shaders `
  --pso-cache $env:G6N_CACHE\pso `
  --frames 600 --warmup 120 `
  --json $env:G6N_OUT\g2\metrics.jsonl

# Rollback check.
$env:G6N_RENDERER = 'layer'; $env:G6N_RECOMP = 'off'
.\target\release\g6n.exe live --game $env:G6N_GAME --save $env:G6N_SAVE --frames 30
```

### 6.8 Selective AOT

```powershell
# Profile 30 s in room01; writes hot-functions.json (no game bytes).
.\target\release\g6n.exe recomp profile `
  --game $env:G6N_GAME --save $env:G6N_SAVE --seconds 30 `
  --out D:\g6n-data\recomp\hot-functions.json

# Lift the selected function to C++ (generated/ is gitignored).
.\target\release\g6n.exe recomp lift `
  --manifest D:\g6n-data\recomp\hot-functions.json `
  --game $env:G6N_GAME `
  --out native\recomp\generated

cmake --build out/native-recomp

# Differential verification: 100k generated + 10k recorded vectors.
.\target\release\g6n.exe recomp diff `
  --manifest D:\g6n-data\recomp\hot-functions.json `
  --vectors 100000 --recorded 10000 `
  --json D:\g6n-data\recomp\diff.json

# Frame-level check: off/on must be identical; gain must be >=5%.
.\target\release\g6n.exe live --game $env:G6N_GAME --save $env:G6N_SAVE `
  --recomp off --frames 600 --json $env:G6N_OUT\aot-off.jsonl
.\target\release\g6n.exe live --game $env:G6N_GAME --save $env:G6N_SAVE `
  --recomp on  --frames 600 --json $env:G6N_OUT\aot-on.jsonl
```

### 6.9 CI and policy

```powershell
cargo xtask ci                 # fmt, clippy, tests, shader fixtures, asset policy
cargo xtask check-assets       # fails on game extensions/large binaries
cargo deny check licenses      # deny.toml allowlist; XCL must not appear
git ls-files | Select-String -Pattern '\.(rpf|ttpf|dds|bk2|awc|xvc|msixvc|exe|dll)$'
```

Expected: no output from the `git ls-files` check. CI runs on a Windows runner with
WARP for synthetic tests; GPU gates run locally and upload JSON only.

Add these entries to `.gitignore` before the first capture (the existing policy already
covers most game extensions):

```gitignore
native/recomp/generated/
captures/
*.rdc
*.wpix
*.png
```

`deny.toml` allowlists GPL-3.0-compatible, MIT, Apache-2.0 and BSD licenses. XCL must
not appear in the dependency graph.

### 6.10 File tree

```text
D:\git\gta6-30fps\
├─ Cargo.toml
├─ rust-toolchain.toml                 # 1.88.0
├─ CMakeLists.txt
├─ deny.toml                           # license allowlist
├─ .cargo\config.toml                   # cargo xtask alias
├─ crates\
│  ├─ g6n-core\src\{lib,budget,clock,log,error}.rs
│  ├─ g6n-capture\src\{lib,schema,import_rdc,validate}.rs
│  ├─ g6n-asset\src\{lib,rpf9,texture,bcpack,meshlet,residency,stream}.rs
│  ├─ g6n-shader\src\{lib,manifest,container,dxil,spirv,cache}.rs
│  ├─ g6n-gfx\src\{lib,backend,frame,stats}.rs
│  ├─ g6n-d3d12\src\{lib,device,heap,pso,indirect,timestamp,present}.rs
│  ├─ g6n-render\src\{lib,graph,frame,replay}.rs
│  │  └─ passes\{depth,opaque,shadow,post,ui}.rs
│  ├─ g6n-recomp\src\{lib,manifest,lift,diff,profile}.rs
│  └─ g6n-cli\src\{main,cmd\{capture,shaders,pso,replay,live,bench,compare,recomp}}.rs
├─ native\recomp\
│  ├─ CMakeLists.txt
│  ├─ runtime\{guest_memory.cpp,guest_memory.h,abi.h,guard.cpp}
│  └─ generated\                     # gitignored, user-local
├─ tools\
│  ├─ capture\{capture-room.ps1,export-draw.py,README.md}
│  ├─ bench\{run-baseline.ps1,compare_images.py,run_gate.py,summarize.py,requirements.txt}
│  └─ shaders\{translate.ps1,validate.ps1}
├─ tests\
│  ├─ fixtures\synthetic_triangle\
│  ├─ fixtures\shaders\{ps.hlsl,ms.hlsl,as.hlsl}
│  ├─ fixtures\room01\               # manifests/hashes only, no blobs
│  └─ integration\
├─ docs\
│  ├─ NATIVE-VERTICAL-SLICE.md       # this file
│  ├─ decisions\{0001-d3d12-primary.md,0002-replay-first.md,0003-selective-aot.md}
│  ├─ licensing.md
│  └─ runbooks\{baseline,capture,g4}.md
├─ benchmarks\                       # JSON/CSV only; no screenshots
├─ xtask\src\main.rs
└─ out\                              # gitignored
```

Outside the repo:

```text
D:\g6n-data\
├─ game\                             # user's copy
├─ saves\room01\                     # user's save
├─ tools\VItoriaBr\                  # read-only reference copy
├─ ref\room01\                       # PNGs, HDR, ops logs, camera.json
├─ captures\room01.rdc
├─ captures\room01.ir\               # manifests + blobs
├─ cache\{shaders,pso}\
├─ recomp\{hot-functions.json,diff.json}
├─ out\
└─ logs\
```

### 6.11 Definition of done

- T1–T14 pass at G4, or a G4 stop report with per-pass evidence.
- `room01` runs at 720p, p50 ≤33.3 ms, p95 ≤40 ms, 3 × 600 frames.
- 30-minute soak; no TDR/device loss; memory stable.
- Image parity thresholds met; no dropped draws; no in-frame PSO compiles.
- Rollback works in one command.
- No game data, captures, generated code or screenshots in git.
- `cargo xtask ci`, `cargo deny`, and asset policy pass.
- All commands in this document are reproducible from a clean checkout.

---

## 7. Facts, assumptions and open questions

### 7.1 Facts used

| Fact | Source |
|---|---|
| Current layer 649–1,551 ms/frame, 1–2 fps (this task); repo diagnosis 1,317–4,017 ms | Task context; `docs/PERF-DIAGNOSIS-2026-11-25.md` |
| fxceless 0–1 fps, 1.8–2.7 s/frame, TDR (this task); 104 ms / 3,850 draws in another run | Task context; `docs/PERFORMANCE_BUDGET.md` |
| AnyXboxX 4.8–5.4 fps on RTX 4070 Super; 6,550 draws | `README.md`, `docs/PROJECTS.md` |
| XCL ~5 fps in 3D on RTX 5090; 26,698 shaders; ~15 GB commit in menus | XCL README, 2026-11-25 |
| DexNom City: 12,520 draws, 969 ms, 2,655 MB guest memory, 95 ms wait, 846 ms lock | DexNom `BENCHMARK.md` |
| VItoriaBr: 25,758 containers, 25,742 translated; 3,349 mesh records in one frame | `docs/precompilacao-shaders.md`; `victory-gpu/src/draw.rs` |
| Leonida: 26,503 shaders, 9,282 mesh, 23,841 wave64, no verified world frame | Leonida README, 2026-11-25 |
| Xbox2Windows: 26,500/26,503 DXIL route; startup unverified | Xbox2Windows README, 2026-11-25 |
| RAGE9-Recomp repo empty | GitHub fetch, 2026-11-25 |
| Xbox Series X: 52 CU, ~12.15 TFLOPS, 16 GB shared, 560/336 GB/s | `docs/PATH-TO-30FPS.md` |
| RTX 4060 Laptop: ~15 TFLOPS, 8 GB, 256 GB/s | Task context; `docs/PATH-TO-30FPS.md` |

### 7.2 Assumptions to validate at G0

- `room01` has ≤2,000 visible draws at G4 (≤2,500 at G3) and ≤4.2 GB of resident textures.
- A non-mesh opaque draw exists that matches the S0 selection rule.
- The room's shaders translate with the current DXIL path at ≥99% (ideally 100%).
- RenderDoc or PIX can capture the room's mesh/indirect draws without changing state.
- The game reaches `room01` with ≤14.5 GB commit on 16 GB.
- The 4060 sustains ≥90% clock in a 30-minute session.
- VRAM budget can stay ≤7.2 GB at 720p/low.
- A leaf draw-packet function can be lifted bit-exactly and gives ≥5% frame-time gain.

### 7.3 Open questions

1. What is the actual draw/mesh/texture/PSO count in `room01`?
2. What is the actual commit at `room01` on 16 GB?
3. Does the current layer's capture expose enough state for a full FrameIR?
4. Which room shaders are wave64 cross-half and how visible are the approximations?
5. Can a bindless root signature + `ResourceDescriptorHeap` compile all room shaders?
6. What is the real per-draw cost after native recording (target 4–5 µs)?
7. Is the hotspot the render-submission path, and can it be lifted without rewriting
   the world?
8. Is 16 GB a hard wall before 30 fps, independent of VRAM?

---

## 8. References

Local:

- `D:\git\gta6-30fps\docs\ARCHITECTURE.md`
- `D:\git\gta6-30fps\docs\PATH-TO-30FPS.md`
- `D:\git\gta6-30fps\docs\PERFORMANCE_BUDGET.md`
- `D:\git\gta6-30fps\docs\PERF-DIAGNOSIS-2026-11-25.md`
- `D:\git\gta6-30fps\docs\PROJECTS.md`
- `D:\git\VItoriaBr\docs\architecture.md`
- `D:\git\VItoriaBr\docs\precompilacao-shaders.md`
- `D:\git\DexNom-VIctory\BENCHMARK.md`

Remote (accessed 2026-11-25):

- Leonida: <https://github.com/ubiquitarianism/leonida>
- Xbox2Windows: <https://github.com/R0Y00/Xbox2Windows>
- XCL: <https://github.com/xcl-dev/xcl>
- RAGE9-Recomp: <https://github.com/r9-recomp/RAGE9-Recomp> (empty at access)
- omonkeyz/xbox-emulator: <https://github.com/omonkeyz/xbox-emulator>

---

*This is an engineering plan, not a promise of 30 fps and not legal advice. The plan
succeeds if it produces a measured, reproducible answer — including a well-evidenced
"this laptop cannot do it" — within 30 days.*

### 7.1 Measured: the native draw-cost ceiling (26.11, commit 08f39e2, evidence/g1-ceiling-*.json)

`s0-replay bench` replays the synthetic one-triangle draw 3500 times per
frame with a warm PSO cache, on the RTX 4060 Laptop (dGPU pinned through
DXGI enumeration � `CreateDevice(None)` silently picks the Radeon 780M,
the same iGPU trap the layer had to fix):

| variant | frame ms (median of 25) | us/draw | draws fitting 33 ms |
|---|---|---|---|
| warm, 1 PSO | 1.02 | 0.29 | 113 569 |
| + PSO switch x4 | 1.06 | 0.30 | 109 065 |
| + state churn (viewport+scissor per draw) | 1.02 | 0.29 | 112 903 |

Reading: the GPU+driver can absorb the game's observed 3 000�5 966
draws/frame at <1 % of a 33 ms budget *for command processing alone*.
The layer spends 631�1880 ms/frame � the delta is layer semantics
(per-draw host bookkeeping, staging, copy-back), not draw throughput.
The plan's premise (native path can reach 30 fps; the layer path cannot)
now has measured backing. Honest caveat: real draws add SRV/UAV binds,
large index ranges, and shader execution time; this is a ceiling, not a
forecast � G1's captured-room replay remains the real gate.
