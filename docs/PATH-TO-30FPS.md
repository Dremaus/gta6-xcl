# Ścieżka do 30 fps — teza, architektura, bramki

## Teza

**30 fps jest osiągalne, ale nie przez obecną warstwę translacji.** Nie dlatego,
że Xbox Series X jest „za mocny”, ale dlatego, że warstwa dokłada 10–100× narzutu
na draw/submit/kopie. Konsola nie jest magiczna:

| | Xbox Series X | RTX 4060 Laptop |
|---|---|---|
| CPU | 8C/16T Zen2 ~3,8 GHz | 8C/16T Zen4 3,8–5,1 GHz |
| GPU | 52 CU RDNA2, ~12,15 TFLOPS | 3072 CUDA, ~15 TFLOPS |
| VRAM/RAM | 16 GB GDDR6 shared (10+6) | 8 GB GDDR6 + 16 GB RAM |
| Bandwidth | 560 GB/s (10 GB) / 336 GB/s | 256 GB/s |
| Feature | mesh shaders, VRS, RT | mesh shaders, VRS, RT, DLSS 3 |

Na papierze CPU mamy szybszy, GPU porównywalny; ograniczeniem jest 8 GB VRAM,
256 GB/s i split RAM/VRAM. Przy 720p i natywnym rendererze to nie musi blokować
30 fps. Blokuje nas **runtime translation**: per-draw deskryptory, kopie,
pipeline compile, HLE.

## Dlaczego obecne projekty mają 2–6 fps

- VItoriaBr/fxceless/AnyXboxX: D3D12.X→D3D12, per-draw translacja, 3 850–6 550
  draws, 27 µs/draw, setki ms kopii i heap passów.
- XCL: ~5 fps na RTX 5090; ten sam problem — warstwa, nie GPU.
- Leonida/Xbox2Windows: static recompilation, ale brak natywnego renderera
  świata; nie doszły do pierwszej klatki.
- Nikt nie połączył **native CPU + native renderer + pełny asset pipeline**.

## Architektura docelowa

1. **Static recompilation CPU** — gorące funkcje gry do C++/Rust (Leonida,
   Xbox2Windows, RAGE9-Recomp jako referencje). HLE zostaje tylko na granicy
   systemowej (XGameRuntime, xmem, pliki, input).
2. **Natywny renderer D3D12/Vulkan** — własny render graph zamiast translacji
   per draw: bindless descriptors, indirect batching, mesh shaders, wczesny
   culling/LOD, pre-baked PSO.
3. **Offline shader pipeline** — XBCH/FSSM → RDNA2 ISA → DXIL/SPIR-V, walidacja
   `dxil.dll`/`spirv-val`, cache po hashu; zero kompilacji w klatce.
4. **Asset pipeline** — RPF9 → natywne tekstury/mipy, BCPack pre-bake,
   DirectStorage, residency 8 GB; 16 GB RAM jako cache strumieniowania.
5. **Frame budget 33,3 ms** — 720p/30 first, FSR/DLSS do 1080p; 8 GB VRAM.

## Model wydajności (dlaczego 30 jest sensowne)

- 30 fps = 33,3 ms.
- 3 000 draws × 8 µs = **24 ms CPU** (po batching/culling) — mieści się.
- 6 550 draws × 27 µs = **177 ms** — nie mieści się; dlatego trzeba ciąć draws
  i koszt/draw, nie tylko „włączyć opcję”.
- GPU przy 720p: ~10–15 ms w natywnym rendererze; 4060 ~15 TFLOPS vs konsola
  ~12 TFLOPS — zapas jest, jeśli shadery nie są tłumaczone 1:1 z narzutem.
- VRAM: 8 GB to największe ryzyko; 720p + streaming + mipy muszą się zmieścić.

## Bramki

| Bramka | Cel | Co musi być prawdą |
|---|---|---|
| **G0** | baseline | 0,2–1 fps zmierzone; wiemy, co kosztuje klatkę |
| **G1** | 5 fps | prekompilacja shaderów/PSO, 720p, streaming ogarnięty |
| **G2** | 10 fps | CPU submit <80 ms, dropped <100, VRAM stabilny |
| **G3** | 20 fps | natywny render graph/batching, 3 000–4 000 draws |
| **G4** | 30 fps | p50 ≤33,3 ms, p95 ≤40 ms, brak device loss, obraz OK |
| **G5** | 1080p | FSR/DLSS + optymalizacja shaderów |

Jeśli po G2 nadal <10 fps, warstwa nie wystarczy — przechodzimy na static
recompilation/native renderer. Jeśli G2 >15 fps, kontynuujemy hybrydę.

## Pierwsze eksperymenty (E1–E4)

- **E1:** prekompilacja shaderów/PSO; usunąć 2 844 dropped draws.
- **E2:** 720p/ambient 0, levels on demand, staging pool, card buffers; VRAM.
- **E3:** indirect gather, join parts, back own view, async submit, queue2.
- **E4:** static recompilation jednego gorącego slice'a (Leonida/Xbox2Windows/
  RAGE9-Recomp) i porównanie z HLE.

## Ryzyka

- 8 GB VRAM i 16 GB RAM — największe ograniczenie sprzętowe.
- RAGE streaming i mesh/root-signature gaps.
- Czas: to projekt na miesiące, nie jedną sesję.
- Licencje: GPL-3.0 baza; XCL GPL-2.0-only tylko jako referencja.
- Żadnego obchodzenia DRM/anti-tamper; tylko własna, odszyfrowana kopia.

## Zasada

Nie ogłaszamy 30 fps bez G4. Ale **nie zakładamy porażki**: każda bramka jest
mierzalna, a architektura jest dobrana pod sprzęt, nie pod „inni nie dali rady”.
