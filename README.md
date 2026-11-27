# GTA VI — performance-first runtime research

Cel bieżący: **10 fps w rozgrywce** na laptopie RTX 4060 8 GB / 16 GB RAM / Ryzen 7
8845HS. Cel docelowy pozostaje 30 fps, ale 10 fps jest pierwszą bramką, która
odróżnia „działa” od „da się grać”.

Droga wykonawcza: **XCL** (`xcl-dev/xcl`, GPL-2.0-only) — warstwa zgodności, która
uruchamia binarkę tytułu natywnie i rekompiluje shadery RDNA2 do DXIL. Wybrana po
tym, jak zwykłe porty warstwy `victory` na tym sprzęcie zatrzymały się na ścianie
16 GB RAM.

Repo publiczne z tymi notatkami: <https://github.com/Dremaus/gta6-xcl>.

## Uczciwy stan wyjściowy

To **nie jest** projekt, który obiecuje 30 fps w tej sesji. Obecne warstwy zgodności
są nadal daleko od celu:

| Źródło | Sprzęt | Wynik 3D |
|---|---|---|
| VItoriaBr (ten laptop) | RTX 4060 8 GB / 16 GB | 0,2–1 fps, 1,3–4,0 s/klatkę |
| VItoriaBr (README) | RTX 5060 Ti 16 GB / 40 GB | do 6 fps |
| fxceless/victory-fork | RTX 4070 12 GB / 32 GB | 2–4 fps; 104 ms/klatkę przy 3 850 draws |
| AnyXboxX | RTX 4070 Super | 4,8–5,4 fps; 6 550 draws |
| XCL | RTX 5090 | ~5 fps w 3D |
| **XCL (ten laptop)** | RTX 4060 8 GB / 16 GB | prekompilacja 26 503 shaderów opanowana; fps w świecie — pomiar w toku |

10 fps = **100 ms/klatkę**. XCL ma na tym sprzęcie dwie przewagi, których nie miały
porty `victory`: tłumaczy 26 698/26 698 shaderów i ma gotowe wave64→32 (dwie połowy
po 32 lane'y) dla NVIDIA. Wąskim gardłem okazało się nie GPU, a pamięć hosta przy
prekompilacji — patrz `docs/XCL-TUNING-8GB-16GB.md`.

## Co ten projekt robi

1. **M0 (zrobione):** inwentaryzacja projektów, budżet wydajności, plan, harness
   pomiarowy.
2. **M1 (zrobione):** wybór bazy — XCL, po pomiarach `victory` na 16 GB RAM.
3. **M2 (w toku):** opanowanie pamięci prekompilacji i uruchomienie świata na
   8 GB VRAM / 16 GB RAM.
4. **M3:** cięcie kosztu GPU (PSO, rozdzielczość, wave64→32, cache shaderów).
5. **M4:** streaming i pamięć (8 GB VRAM / 16 GB RAM).
6. **M5:** bramka 10 fps, potem 30 fps albo udokumentowana ściana sprzętowa.

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

- **Baza wykonawcza:** `xcl-dev/xcl` — GPL-2.0-only. Uruchamiamy ją jako osobny
  projekt/binarkę; **nie kopiujemy jej kodu do tego repo**.
- **To repo jest tylko dokumentacją i narzędziami pomiarowymi:** GPL-3.0-or-later.
  Kod XCL pozostaje GPL-2.0-only, a kod tego repo GPL-3.0 — dwie osobne całości,
  bez mieszania.
- **Referencje, nie kopiowanie:** `fxceless/victory-fork`, `AnyXboxX`,
  Leonida (GPL-3.0), Xbox2Windows (MIT), omonkeyz (GPL-3.0), DexNom.
- Żadnych plików gry, binarek ani danych pochodnych w repo — patrz `.gitignore`.

## Struktura

```
docs/ARCHITECTURE.md        warstwy, decyzje, fakty o platformie
docs/XCL-TUNING-8GB-16GB.md przełączniki XCL, cache shaderów, przyczyna stallu
docs/NIGHT-LOG.md           dziennik decyzji i bramek (append-only)
docs/PERFORMANCE_BUDGET.md  budżet klatki i baseline
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
