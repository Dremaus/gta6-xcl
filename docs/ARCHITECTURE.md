# Architektura

## Cel i ograniczenia

- Cel: 30 fps (33,3 ms) w świecie 3D, najpierw 1280×720 low, potem 1080p.
- Sprzęt referencyjny: RTX 4060 Laptop 8 GB, 16 GB RAM, Ryzen 7 8845HS.
- Twarde ograniczenia: 8 GB VRAM (tekstury + targety + scratch), 16 GB RAM
  (commit), brak natywnego portu PC.
- Zasada: najpierw zmierzyć, potem ciąć. Każdy wariant ma correctness gate.

## Warstwy

### 1. Loader / CPU

- Mapowanie PE, importy, delay-importy, TLS, wyjątki, load-config, CFG.
- Kod gry x86-64 działa natywnie; nie emulujemy całego CPU.
- Emulujemy tylko instrukcje/zachowania konsoli: `monitorx`/`mwaitx`, `CLZERO`,
  SSE4a (`INSERTQ`/`EXTRQ`), `CLWB`, specyfikę stron/aliasingu.
- Raport brakujących importów; żadnego cichego zerowania.

### 2. GDK / HLE

- `xgameruntime.dll`: `XGameRuntimeInitialize`, `XUser*`, `XSystem*`, `XStore*`,
  `XGameSave*`, `XAsync*`, `XTaskQueue*`.
- `xmem.dll`: alokacje wirtualne/fizyczne, aliasing, commit, place/commit,
  `AllocateUploadMemory`, batch page mappings.
- `xg_xs.dll`: layout tekstur; `d3d12_xs.dll` (Series X|S), nie `d3d12_x.dll`
  (Xbox One).
- Pliki/pakiety: `MicrosoftGame.config`, storage, wirtualne dyski, saves, quota.
- Input/audio/media: GameInput/XInput, XAudio2/XMA, Bink2, HTTP/curl.
- Offline: brak Xbox Live/Store; lokalny profil; log decyzji.

### 3. GPU / D3D12.X

- Kontenery shaderów: XBCH → FSSM → natywny RDNA2 (gfx1013/gfx1030).
- Translacja do DXIL (D3D12) lub SPIR-V (Vulkan); cache po hashu treści.
- Root signatures, descriptor tables, static samplers, UAV/SRV, formaty RT/depth,
  tiled/packed tekstury.
- Mesh/amplification/geometry, wave64→wave32 na NVIDIA, cross-half lane ops.
- PSO offline + pipeline library; zero kompilacji w klatce.

### 4. Pamięć / streaming

- Emulacja title virtual memory: committed/placed heaps, guard pages, write watch.
- BCPack/BC1–BC7, tiling konsoli, mip tails, volume textures.
- Budżet VRAM: tekstury, targety, scratch; eviction/re-upload.
- 8 GB: nie zakładać, że cała scena się zmieści; liczyć residency.

### 5. Wydajność

Kolejność ataku:
1. CPU per draw: deskryptory, heap sync, indirect clamp, submit.
2. GPU: shadery, PSO, overdraw, rozdzielczość.
3. Streaming: uploady, kopie, page mapping.
4. Dopiero potem skalowanie rozdzielczości i upscaling.

### 6. Walidacja

- Frame log: p50/p95, draws, submit ms, card ms, copy/copy-back, VRAM, commit.
- Correctness: ta sama scena/save, screenshot/pixel compare, brak device loss.
- REA dla shipped binaries/pakietów; normalne narzędzia dla open-source.
- Bramka: correctness + powtarzalny delta + rollback + commit.

## Wybór bazy

**AnyXboxX `third_party/victory`** jest najlepszym znanym światem: 4,8–5,4 fps,
6 550 draws, cutscenes i pierwsze misje na RTX 4070 Super. Jego launcher ustawia
m.in. `VICTORY_SHADER_LOOP_LIMIT=256`, `VICTORY_LATE_WAIT=3`,
`VICTORY_WIDE_BACK=1`, `VICTORY_CARD_BUFFERS_MIN_MB=1`,
`VICTORY_CARD_BUFFERS_MB=1024`, `VICTORY_DSTORAGE_NOTIFY=1`,
`VICTORY_STAGING_POOL_MB=1024`; prekompilacja 25 689 shaderów ~4,5 min, cache 13 GB.

**fxceless/victory-fork** jest najlepiej udokumentowaną bazą optymalizacji
(104 ms/klatkę, 3 850 draws, podział submit/card). Wybór między nimi to pierwszy
eksperyment M1: ten sam save, ta sama scena, ten sam sprzęt.

## Czego nie robimy

- Nie kopiujemy kodu XCL (GPL-2.0-only) do GPL-3.0; tylko idee/reimplementacja.
- Nie budujemy CPU emulatora, jeśli natywne x86-64 wystarcza.
- Nie obiecujemy 30 fps, dopóki budżet nie jest zmierzony.
