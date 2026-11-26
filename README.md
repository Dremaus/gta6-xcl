# GTA VI 30 fps — performance-first runtime research

Cel: uruchomić świat GTA VI (Xbox Series, build 1.0.2.1) na Windows w **min. 30 fps
w rozgrywce** na laptopie RTX 4060 8 GB / 16 GB RAM / Ryzen 7 8845HS.

## Uczciwy stan wyjściowy

To **nie jest** projekt, który obiecuje 30 fps w tej sesji. Obecne warstwy zgodności
są 5–150× poniżej celu:

| Źródło | Sprzęt | Wynik 3D |
|---|---|---|
| VItoriaBr (ten laptop) | RTX 4060 8 GB / 16 GB | 0,2–1 fps, 1,3–4,0 s/klatkę |
| VItoriaBr (README) | RTX 5060 Ti 16 GB / 40 GB | do 6 fps |
| fxceless/victory-fork | RTX 4070 12 GB / 32 GB | 2–4 fps; 104 ms/klatkę przy 3 850 draws |
| AnyXboxX | RTX 4070 Super | 4,8–5,4 fps; 6 550 draws |
| XCL | RTX 5090 | ~5 fps w 3D |

30 fps = **33,3 ms/klatkę**. Najlepszy znany wynik na mocniejszym GPU to ~5–6 fps
(167–200 ms). Na tym laptopie potrzebujemy ~5–10× więcej niż najlepszy projekt na
mocniejszym sprzęcie. To nie jest kwestia jednego przełącznika.

## Co ten projekt robi

1. **M0 (ten etap):** inwentaryzacja projektów, budżet wydajności, plan, harness
   pomiarowy. Bez obiecywania 30 fps.
2. **M1:** wybór bazy (AnyXboxX `third_party/victory` lub fxceless/victory-fork)
   i powtarzalny pomiar sceny.
3. **M2:** cięcie kosztu CPU na draw (deskryptory, heaps, indirect, submit).
4. **M3:** cięcie kosztu GPU (shadery, PSO, rozdzielczość, VRAM).
5. **M4:** streaming i pamięć (8 GB VRAM / 16 GB RAM).
6. **M5:** bramka 720p/30 fps albo udokumentowana ściana sprzętowa.

## Native path — decyzja architektoniczna

`docs/NATIVE-VERTICAL-SLICE.md` (Agent B) wybiera:

- **D3D12 pierwszy**, Vulkan dopiero po G4 (ADR-0001),
- **replay-first**: jedna klatka z obecnej warstwy → natywny render graph → parity,
- **selective AOT** jednej gorącej funkcji (draw-packet/constant packer), nie pełna
  rekompilacja (ADR-0003),
- G4 mierzone: p50 ≤33,3 ms, p95 ≤40 ms, 3×600 klatek, soak 30 min, brak TDR.

Uczciwa ocena planu: G2/G3 realistyczne, **G4 live 30 fps to 10–15%**, pełna gra
<5% na 8 GB VRAM / 16 GB RAM. Plan jest zaprojektowany tak, żeby tanio dać
mierzone „tak/nie”, a nie deklarację bez pokrycia.

## Baza i licencje

- **Baza wykonawcza:** `AnyXboxX/third_party/victory` (najlepszy zmierzony świat:
  4,8–5,4 fps na RTX 4070 Super) albo `fxceless/victory-fork` (najlepiej
  udokumentowane optymalizacje: 104 ms/klatkę, 3 850 draws).
- **Referencje, nie kopiowanie:** XCL (GPL-2.0-only — nie wolno kopiować kodu do
  GPL-3.0), Leonida (GPL-3.0, static recompilation/SPIR-V), Xbox2Windows (MIT,
  rekompilacja CPU/DXIL), omonkeyz (GPL-3.0, ogólny runtime), DexNom (Radeon).
- Ten projekt: **GPL-3.0-or-later**.

## Struktura

```
docs/ARCHITECTURE.md        warstwy, decyzje, fakty o platformie
docs/PERFORMANCE_BUDGET.md  budżet 33,3 ms i baseline
docs/NATIVE-VERTICAL-SLICE.md  plan native: replay-first, D3D12, selective AOT
docs/PATH-TO-30FPS.md       bramki G1 5 -> G2 10 -> G3 20 -> G4 30
docs/PROJECTS.md            porównanie projektów + skan topicu
plans/                      plan wieloetapowy (blueprint)
research/                   inwentaryzacja 66 repo z topicu
tools/bench/                parser logów VItoriaBr/fxceless
tools/profile/              profiler diag + parser .folded
benchmarks/                 zapisane baseline'y
```

## Zasady

- Żadnych plików gry w repo; użytkownik dostarcza własną kopię.
- Bez kluczy, deszyfrowania i obchodzenia DRM.
- Każda zmiana wydajności ma correctness gate i powtarzalny pomiar.
- Nie ogłaszamy 30 fps bez p50/p95 i porównania sceny.

## Pomiar

- Protokol i bramka 30 fps: `docs/BENCHMARK-PROTOCOL.md`
- Launcher pomiarowy (log INFO dla frame logu): `benchmarks/launch-bench.ps1`
- Scena referencyjna: `benchmarks/scenes/reference-scene.md`
- Przykladowy raport: `benchmarks/sample-report-baseline.md`
