# Diagnoza wydajności — Skills 01–10

Data: 2026-11-25. Źródła: `game-stderr.log` VItoriaBr, `benchmarks/`, README
fxceless/AnyXboxX, kontrolny odczyt systemu. Celem jest znalezienie hamulca,
nie obiecanie 30 fps.

## 01. Frame-time breakdown

- 3D: **1 317–4 017 ms/klatkę** (0,2–1 fps), 1 011–3 504 draws.
- Rozbicie z logu: kopie **250–760 ms**, tekstury **100–270 ms**, copy-back
  **93–443 ms**, heap/descriptor pass **0–2 708 ms**, GPU **~8 ms**.
- Menu: 30 fps (cap gry), 41 draws — nie jest problemem.

**Wniosek:** to nie jest „GPU za wolne”. Większość klatki to CPU-side
przygotowanie, kopie i synchronizacja; GPU bywa bezczynne.

## 02. CPU/GPU bound classifier

- CPU: ~100% (8C/16T), submit/render thread przeciążony.
- GPU: 34–46%, 600–1 890 MHz, często 0% w momentach stall.
- **2 844 draws dropped** bez host pipeline (253 w budowie) w jednej klatce.

**Wniosek:** CPU/submit-bound + pipeline miss, nie GPU-bound.

## 03. Stall / spinlock detector

- Klatki 4 s, 23 000 tekstur czeka, pipeline'y w budowie.
- fxceless mierzy title wait przez `monitorx`/`mwaitx`: ~280k emulowanych
  wyjątków/s na Intelu; u nas CPU-side waits też są widoczne.
- Streaming frame: ~850 remapów, 260 uploadów, 450 odczytów dysku (fxceless).

**Wniosek:** duże, nieregularne przestoje na streamingu i pipeline'ach.

## 04. Cold start vs steady state

- Zimny cache: 0,2 fps, 2 844 dropped, 0,11 GB shader cache, 166 MB pipelines.
- Rozgrzanie może podnieść fps, ale nie 30×: fxceless/AnyXboxX nadal 2–5 fps.
- AnyXboxX prekompilacja: 25 689 shaderów ~4,5 min, cache 13 GB.

**Wniosek:** prekompilacja jest konieczna, ale to warunek wstępny, nie cel.

## 05. UI/subtitles tick

- Menu 30 fps, 41 draws; cutscene 3 504 draws.
- Napisy/HUD nie są głównym kosztem; nie widać osobnego „UI spike”.

**Wniosek:** depriorytetyzować; wrócić, jeśli menu zacznie spadać.

## 06. I/O / decompression

- 6,8–7,1 GB tekstur wysłanych, **23 000 czeka**, 8 GB VRAM.
- BCPack/BC7, mip tails, tiled layouts; uploady i kopie dominują.
- 16 GB RAM: commit free bywał 1,4 GB; system zamykał aplikacje.

**Wniosek:** streaming/VRAM to drugi największy hamulec po submit/pipeline.

## 07. Shim overhead

- 2 973 draws przy ~4 017 ms → **1,35 ms/draw** all-in (zimny, z dropami).
- fxceless: 104 ms / 3 850 draws = **27 µs/draw**; cel 30 fps = **8,65 µs/draw**.
- Per-frame deskryptory: 3,2 zmienionych stron, 2 189 slotów, ~2,7–3,05 ms
  (to tylko jeden z passów; heap pass bywa 950–2 708 ms).

**Wniosek:** potrzebne ~3× mniej na draw; bez tego 30 fps niemożliwe.

## 08. Present / flip latency

- Gra w oknie z paskiem Windows; DWM/kompozytor może dokładać kilka ms.
- To nie wyjaśnia 1,3–4,0 s: DWM to <1% klatki.
- Warto przetestować borderless/fullscreen i `VICTORY_ASYNC_PRESENT`, ale to
  mikro-optymalizacja.

**Wniosek:** sprawdzić, nie priorytetyzować.

## 09. Thermal / power

Kontrolny odczyt (gra nie działa):
- plan zasilania: **Zrównoważony** (nie High Performance),
- CPU: 3 801 / 3 801 MHz, 12% idle,
- GPU: 42°C, 1,53 W, 210/3 105 MHz, 130 MiB,
- RAM: 2,7 GB wolne, commit 12,1 GB wolne, pagefile 21,8 GB,
- bateria: 100% (AC).

**Wniosek:** brak dowodu throttlingu w idle; pod obciążeniem CPU 100%, GPU
34–46%. Ustawić High Performance i monitorować temperatury/takty; to może dać
kilka–kilkanaście procent, nie 30×.

## 10. Regression harness

- `tools/bench/parse_victory_log.py` + `benchmarks/baseline-vitoriabr-2026-11-25.csv`.
- Brakuje deterministycznego save/sceny i 3 przebiegów; to pierwszy krok M1.

## Pareto — co daje najwięcej

1. **Prekompilacja shaderów/PSO** — usunąć 2 844 dropped draws; cache 13 GB;
   `-Precompile` w AnyXboxX lub `victory translate --warm all`.
2. **Streaming/VRAM** — `VICTORY_LEVELS_ON_DEMAND=1`,
   `VICTORY_STAGING_POOL_MB=1024`, `VICTORY_CARD_BUFFERS_MIN_MB=1`,
   `VICTORY_CARD_BUFFERS_MB=1024`; 8 GB budżet.
3. **CPU submit/draw** — `VICTORY_INDIRECT_GATHER=1`,
   `VICTORY_JOIN_PARTS=1`, `VICTORY_BACK_OWN_VIEW=1`,
   `VICTORY_ASYNC_SUBMIT=1`, `VICTORY_QUEUE2=1`; cel <50 ms submit.
4. **Host** — High Performance, fullscreen, 720p/ambient 0, zamknięte aplikacje,
   pagefile 32 GB na D:.

## Realny wynik

- 30 fps = 33,3 ms; obecnie 1 317–4 017 ms → **40–120× za wolno**.
- Najlepszy znany projekt (AnyXboxX) na RTX 4070 Super: ~185–208 ms → **5,5–6×
  za wolno**.
- Nawet po wszystkich 100 skillach na tym laptopie realny sufit to **2–5 fps**,
  nie 30. 30 fps wymaga natywnego portu/renderera i prawdopodobnie 16 GB VRAM /
  32 GB RAM; warstwa translacji na 8 GB/16 GB tego nie dowiezie.

## Następny eksperyment (Skills 91–100)

- **E1:** prekompilacja shaderów/PSO (AnyXboxX `-Precompile` lub VItoriaBr
  `translate --warm all`), 3 przebiegi, p50/p95, dropped draws.
- **E2:** streaming/VRAM (levels on demand, staging pool, card buffers).
- **E3:** submit/draw (indirect gather, join parts, back own view, async submit).
- **E4:** High Performance + fullscreen + 720p/ambient 0.
- Po każdej zmianie: visual diff, stability, soak, changelog.
