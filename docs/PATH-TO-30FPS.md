# ÅšcieÅ¼ka do 30 fps â€” teza, architektura, bramki

## Teza

**30 fps jest osiÄ…galne, ale nie przez obecnÄ… warstwÄ™ translacji.** Nie dlatego,
Å¼e Xbox Series X jest â€za mocnyâ€, ale dlatego, Å¼e warstwa dokÅ‚ada 10â€“100Ã— narzutu
na draw/submit/kopie. Konsola nie jest magiczna:

| | Xbox Series X | RTX 4060 Laptop |
|---|---|---|
| CPU | 8C/16T Zen2 ~3,8 GHz | 8C/16T Zen4 3,8â€“5,1 GHz |
| GPU | 52 CU RDNA2, ~12,15 TFLOPS | 3072 CUDA, ~15 TFLOPS |
| VRAM/RAM | 16 GB GDDR6 shared (10+6) | 8 GB GDDR6 + 16 GB RAM |
| Bandwidth | 560 GB/s (10 GB) / 336 GB/s | 256 GB/s |
| Feature | mesh shaders, VRS, RT | mesh shaders, VRS, RT, DLSS 3 |

Na papierze CPU mamy szybszy, GPU porÃ³wnywalny; ograniczeniem jest 8 GB VRAM,
256 GB/s i split RAM/VRAM. Przy 720p i natywnym rendererze to nie musi blokowaÄ‡
30 fps. Blokuje nas **runtime translation**: per-draw deskryptory, kopie,
pipeline compile, HLE.

## Dlaczego obecne projekty majÄ… 2â€“6 fps

- VItoriaBr/fxceless/AnyXboxX: D3D12.Xâ†’D3D12, per-draw translacja, 3 850â€“6 550
  draws, 27 Âµs/draw, setki ms kopii i heap passÃ³w.
- XCL: ~5 fps na RTX 5090; ten sam problem â€” warstwa, nie GPU.
- Leonida/Xbox2Windows: static recompilation, ale brak natywnego renderera
  Å›wiata; nie doszÅ‚y do pierwszej klatki.
- Nikt nie poÅ‚Ä…czyÅ‚ **native CPU + native renderer + peÅ‚ny asset pipeline**.

## Architektura docelowa

1. **Static recompilation CPU** â€” gorÄ…ce funkcje gry do C++/Rust (Leonida,
   Xbox2Windows, RAGE9-Recomp jako referencje). HLE zostaje tylko na granicy
   systemowej (XGameRuntime, xmem, pliki, input).
2. **Natywny renderer D3D12/Vulkan** â€” wÅ‚asny render graph zamiast translacji
   per draw: bindless descriptors, indirect batching, mesh shaders, wczesny
   culling/LOD, pre-baked PSO.
3. **Offline shader pipeline** â€” XBCH/FSSM â†’ RDNA2 ISA â†’ DXIL/SPIR-V, walidacja
   `dxil.dll`/`spirv-val`, cache po hashu; zero kompilacji w klatce.
4. **Asset pipeline** â€” RPF9 â†’ natywne tekstury/mipy, BCPack pre-bake,
   DirectStorage, residency 8 GB; 16 GB RAM jako cache strumieniowania.
5. **Frame budget 33,3 ms** â€” 720p/30 first, FSR/DLSS do 1080p; 8 GB VRAM.

## Model wydajnoÅ›ci (dlaczego 30 jest sensowne)

- 30 fps = 33,3 ms.
- 3 000 draws Ã— 8 Âµs = **24 ms CPU** (po batching/culling) â€” mieÅ›ci siÄ™.
- 6 550 draws Ã— 27 Âµs = **177 ms** â€” nie mieÅ›ci siÄ™; dlatego trzeba ciÄ…Ä‡ draws
  i koszt/draw, nie tylko â€wÅ‚Ä…czyÄ‡ opcjÄ™â€.
- GPU przy 720p: ~10â€“15 ms w natywnym rendererze; 4060 ~15 TFLOPS vs konsola
  ~12 TFLOPS â€” zapas jest, jeÅ›li shadery nie sÄ… tÅ‚umaczone 1:1 z narzutem.
- VRAM: 8 GB to najwiÄ™ksze ryzyko; 720p + streaming + mipy muszÄ… siÄ™ zmieÅ›ciÄ‡.

## Bramki

| Bramka | Cel | Co musi byÄ‡ prawdÄ… |
|---|---|---|
| **G0** | baseline | 0,2â€“1 fps zmierzone; wiemy, co kosztuje klatkÄ™ |
| **G1** | 5 fps | prekompilacja shaderÃ³w/PSO, 720p, streaming ogarniÄ™ty |
| **G2** | 10 fps | CPU submit <80 ms, dropped <100, VRAM stabilny |
| **G3** | 20 fps | natywny render graph/batching, 3 000â€“4 000 draws |
| **G4** | 30 fps | p50 â‰¤33,3 ms, p95 â‰¤40 ms, brak device loss, obraz OK |
| **G5** | 1080p | FSR/DLSS + optymalizacja shaderÃ³w |

JeÅ›li po G2 nadal <10 fps, warstwa nie wystarczy â€” przechodzimy na static
recompilation/native renderer. JeÅ›li G2 >15 fps, kontynuujemy hybrydÄ™.

## Pierwsze eksperymenty (E1â€“E4)

- **E1:** prekompilacja shaderÃ³w/PSO; usunÄ…Ä‡ 2 844 dropped draws.
- **E2:** 720p/ambient 0, levels on demand, staging pool, card buffers; VRAM.
- **E3:** indirect gather, join parts, back own view, async submit, queue2.
- **E4:** static recompilation jednego gorÄ…cego slice'a (Leonida/Xbox2Windows/
  RAGE9-Recomp) i porÃ³wnanie z HLE.

## Ryzyka

- 8 GB VRAM i 16 GB RAM â€” najwiÄ™ksze ograniczenie sprzÄ™towe.
- RAGE streaming i mesh/root-signature gaps.
- Czas: to projekt na miesiÄ…ce, nie jednÄ… sesjÄ™.
- Licencje: GPL-3.0 baza; XCL GPL-2.0-only tylko jako referencja.
- Å»adnego obchodzenia DRM/anti-tamper; tylko wÅ‚asna, odszyfrowana kopia.

## Zasada

Nie ogÅ‚aszamy 30 fps bez G4. Ale **nie zakÅ‚adamy poraÅ¼ki**: kaÅ¼da bramka jest
mierzalna, a architektura jest dobrana pod sprzÄ™t, nie pod â€inni nie dali radyâ€.

## Dodatek nocny 26.11 01:40 — wspólny mianownik crashy: pula pamiêci tytu³u

Dwie sygnatury zgonu: (A) device reset ~2,5 min w 3D ( niezaleznie od relay family i od gate
Agent M), (B) deterministyczny AV gracza +0x11170ae ~60 s w menu SafeMem. Wspólna poszlaka z
w³asnych dumpów breakpad gry: 'Game Physical: 2143484240/2305818624' (93 % puli 2199 MiB),
'Unused: 0', TileHeap 968/6236 Mb przy Frame 948. Gra w tym momencie NIE ma ju¿ sk¹d braæ
stron; wskazania obiektów w jej globalnej tablicy (entry stride 80, [entry+0x20] › obiekt+0x78)
trafiaj¹ na strony 'reserved, never committed'. Linia unhandled pokazuje tê sam¹ stronê jako
'read-write' — filtr warstwy doci¹³ stronê PO pierwszym przejœciu (breakpad zd¹¿y³ z³apaæ first-chance).

Hipoteza H6 (nowa, g³ówna): pula fizyczna tytu³u (2199 MiB) jest za ma³a DLA TEGO BUDOWANIA ŒWIEATA
albo warstwa nie dowozi mapowañ tile/xmem na czas › odmowy alokacji w grze › (A) przez œmieciowe
GPU-komendy, (B) przez dereferencjê niestworzonych obiektów. Agent A szuka Ÿród³a liczby 2199 MiB
(herbata: console.rs title_memory() = 10 GiB + 3,5 GiB dla Series X; 2199 MiB nie st¹d — chyba ¿e
gra sama prosi o tyle przy starcie i tyle ma te¿ na prawdziwej konsoli).

Realny sufit œcie¿ki layerowej bez naprawy pamiêci: dalej 1-2 fps w 3D. Naprawa pamiêci nie da
30 fps, ale bez niej ¿adna optymalizacja nie utrzyma œwiata przy ¿yciu d³u¿ej ni¿ 2-3 minuty.
Priorytet do rana: (1) H6, (2) PER-DRAW cost (Agent K), (3) replay-native S0 jako droga tygodnia.
