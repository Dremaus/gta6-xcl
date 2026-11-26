# Protokół benchmarku — cel 30 fps

Harness pomiarowy dla VItoriaBr i fxceless. Nie uruchamia gry: użytkownik
prowadzi tytuł, narzędzie stempluje okno pomiarowe, czyta logi i próbkuje
sprzęt. Każdy przebieg to jeden `run.json`, kampania to trzy przebiegi i jeden
raport.

## Definicja celu

| | |
|---|---|
| 30 fps | **33,33 ms** na klatkę, p50 |
| p95 | **≤ 40 ms** |
| Bramki | G1 5 fps (200 ms), G2 10 fps (100 ms), G3 20 fps (50 ms), G4 30 fps (33,3 ms) |

Werdykt `PASS` wymaga jednocześnie: p50 ≤ 33,33 ms, p95 ≤ 40 ms, poprawnego
okna 3D (draws ≥ 100, ≥ 10 klatek), braku TDR i braku fatalnego crasha w oknie.
VRAM peak > 7 800 MB nie blokuje werdyktu, ale trafia do raportu jako ryzyko
(thrashing na 8 GB).

## Co mierzymy i skąd

| pole | źródło |
|---|---|
| p50 / p95 / p99 / 1% low | `frame times: … each:` z `framelog.rs` (prawdziwe czasy klatek) |
| draws, dropped, pipelines | linia `N fps, N ms/frame …` z `host.rs` |
| submit / card / prepare ms | linia `usual frame (the mean of N not long): …` |
| VRAM peak | `nvidia-smi`, próbka co 2 s |
| commit peak | `GlobalMemoryStatusEx` (`total pagefile − avail pagefile`), co 2 s |
| crash / TDR | `crashes.log`, Event Log, `temp\victory-*.crash.log` |
| cap / refresh / vsync / rozdzielczość | blok `settings` w `run.json` — `tools/bench/settings_xml.py` czyta `graphics.desiredFPS`, `video.frameRateLimit`, `video.vSync`, `video.refreshRate`, `video.resolutionFullscreen` |
| środowisko | `bench-env.json` zapisany przez `launch-bench.ps1` |

Bez `VICTORY_LOG=info` dla `victory_gpu::host` i `victory_gpu::framelog` log
zawiera tylko WARN i okno wychodzi puste. Dlatego benchmark uruchamia się przez
`benchmarks\launch-bench.ps1`, nie przez launcher projektowy (ten ustawia
`VICTORY_LOG=warn`).

## Scena i stan cache

- Scena: `benchmarks/scenes/reference-scene.md` (prolog, slot
  `0009000000000001`, kamera nieruchoma). Kontrola: draws w oknie ≥ 100.
- `--cache warm` — trzy przebiegi na istniejącym cache shaderów.
- `--cache cold-then-warm` — przebieg 1 po wyczyszczeniu cache, przebiegi 2–3 na
  cache, który zbudował przebieg 1. To jedyny uczciwy sposób porównania
  „zimny vs rozgrzany” bez czyszczenia cache trzy razy.

Wyczyszczenie cache (robi to użytkownik, harness nigdy nie usuwa danych gry):

```powershell
Remove-Item -Recurse -Force 'D:\Gry\VItoriaBr-data\cache\shaders'
```

Odtworzenie z logów tego projektu: VItoriaBr 146,6 s (23 815 tłumaczeń),
fxceless 199,8 s na 8 wątkach (25 635 tłumaczeń).

## Komendy

Wszystko z `D:\git\gta6-30fps`.

### Kampania: 3 przebiegi

```powershell
python tools\bench\bench_run.py --runtime vitoriabr --variant baseline --cache warm --runs 3 --window 60 --out benchmarks\runs\2026-11-25-baseline-warm
```

Przebieg interakcji (skrypt **nie** startuje gry — robisz to sam):

1. Skrypt sprawdza, że gra nie działa, cache nie jest pusty, a `nvidia-smi`
   odpowiada; wypisuje plan i protokół sceny.
2. Uruchamiasz tytuł przez `launch-bench.ps1`, wczytujesz save i czekasz, aż
   scena się ustabilizuje (`benchmarks/scenes/reference-scene.md`).
3. Enter → potwierdzenie, że scena jest gotowa.
4. Enter → START okna. Skrypt próbkuje VRAM/commit przez `--window` sekund;
   przez cały czas nie ruszasz kamery.
5. Enter → STOP, opcjonalna notatka. Powstaje `r01/run.json`.
6. Restart tytułu i powtórz kroki 2–5 dla `r02` i `r03`.
7. Na końcu powstaje `report.md` z werdyktem.

### Pojedynczy przebieg, ręcznie

```powershell
python tools\bench\bench_collect.py --runtime vitoriabr --variant e3b --cache warm --run-id r01 --start 2026-11-25T21:00:00Z --end 2026-11-25T21:01:00Z --out benchmarks\runs\e3b\r01\run.json
```

### Raport z trzech przebiegów

```powershell
python tools\bench\bench_report.py --runs benchmarks\runs\2026-11-25-baseline-warm\r01\run.json benchmarks\runs\2026-11-25-baseline-warm\r02\run.json benchmarks\runs\2026-11-25-baseline-warm\r03\run.json --variant baseline --out benchmarks\runs\2026-11-25-baseline-warm\report.md
```

### Kalibracja na istniejącym logu

```powershell
python tools\bench\bench_collect.py --runtime vitoriabr --run-id calibrate --whole-log --out "$env:TEMP\calibrate.json"
```

`--whole-log` bierze zakres czasu z samego logu i ogranicza do niego dowody
crash/TDR. Jeśli log powstał z `VICTORY_LOG=warn`, wynik to `BLOCKED` z powodem
`too few frames` — to oczekiwane i jest testem, że harness wykrywa brak danych.

### Snapshot zapisanego baseline'u

```powershell
python tools\bench\bench_report.py --from-csv benchmarks\baseline-vitoriabr-2026-11-25.csv --out benchmarks\sample-report-baseline.md
```

Pojedyncze próbki nie mają p95 ani 1% low, więc bramka jest tam orientacyjna.
Przykład: `benchmarks\sample-report-baseline.md`.

### Parser bezpośrednio

```powershell
python tools\bench\parse_victory_log.py "D:\Gry\VItoriaBr-data\logs\game-stderr.log" --frames --gate-fps 30
python tools\bench\parse_victory_log.py LOG --min-draws 1000 --min-ms 100 --csv benchmarks\vitoriabr-4060-3d.csv
```

## Eksperyment A/B: okno+cap30 vs borderless bez capa

Cel: rozdzielić wpływ prezentacji (okno vs borderless) od capa 30 fps z
`settings.xml`, na runtime `D:\git\VItoriaBr-opt` (patch heap-buffer Agenta A
+ staging bounds Arm B Agenta E). To T2 z `docs/PRESENT-LATENCY.md`, z capem
w obu stanach. Gra zamknięta przed startem każdego `bench_run.py`; launcher
i `bench_run.py` stoją w osobnych terminalach.

### Ramiona

| ramię | prezentacja | `settings.xml` |
|---|---|---|
| **A — windowed-cap30** | okno tytułu (`VICTORY_BORDERLESS` nieustawione) | backup `.cap-bak`: `desiredFPS=30`, `frameRateLimit=30`, `vSync=2`, refresh `60/1`, fullscreen `3840x2160` |
| **B — borderless-nocap** | `VICTORY_BORDERLESS=1` | spatchowane: `desiredFPS=60`, `frameRateLimit=0`, `vSync=0`, refresh `120/1`, fullscreen `1280x720` |

Stałe w obu ramionach: ten sam build opt, patch Agenta A aktywny — to domyślna
ścieżka builda, więc `VICTORY_HEAP_BUFFERS_TABLES` **musi pozostać
nieustawione** (`=1` przywraca starą ścieżkę mirror — nie używać w tym
eksperymencie), staging bounds Arm B (`VICTORY_TEXTURE_CATCHUP=0`,
`VICTORY_TEXTURE_STAGE_MS=24`, `VICTORY_TEXTURE_STAGE_MB=64`),
`VICTORY_REFRESH=120`, swapchain okna 1280x720
(`VICTORY_DISPLAY_MODE=1280x720`), warm cache, scena referencyjna.
`VICTORY_REFRESH=120` jest stałą w obu ramionach — refresh z `settings.xml`
(60/1 vs 120/1) różni ramiona i obie wartości trafiają do `run.json`. W
ramieniu A `resolutionFullscreen` (3840x2160) jest nieaktywne (okno 720p),
ale zapisujemy je, żeby ramię było wierne backupowi.

### Przygotowanie ramienia

```powershell
# A — przywróć cap z backupu
& 'D:\Gry\VItoriaBr-data\Patch-GameSettings.ps1' -Restore
python tools\bench\settings_xml.py --data-root D:\Gry\VItoriaBr-data --expect-cap active

# B — zdejmij cap
& 'D:\Gry\VItoriaBr-data\Patch-GameSettings.ps1'
python tools\bench\settings_xml.py --data-root D:\Gry\VItoriaBr-data --expect-cap removed
```

`--expect-cap` to twarda bramka (exit 1 przy niezgodności) — nie zaczynaj
kampanii z cudzym `settings.xml`. Skrypt patcha robi `.cap-bak` tylko przy
pierwszym patchowaniu, więc `-Restore` i ponowny patch są odwracalne.

### Kampania: dokładne komendy

Z `D:\git\gta6-30fps`:

```powershell
# ramię A — trzy przebiegi
python tools\bench\bench_run.py --runtime vitoriabr --variant windowed-cap30 `
  --cache warm --runs 3 --window 60 `
  --out benchmarks\runs\2026-11-25-ab\windowed-cap30

# ramię B — trzy przebiegi
python tools\bench\bench_run.py --runtime vitoriabr --variant borderless-nocap `
  --cache warm --runs 3 --window 60 `
  --out benchmarks\runs\2026-11-25-ab\borderless-nocap
```

Uruchomienie tytułu — raz na przebieg, z drugiego terminala (`bench_run.py`
nigdy nie startuje gry; w swoim terminalu czeka na Enter):

```powershell
# A
.\benchmarks\launch-bench-ab.ps1 -Memory
# B
.\benchmarks\launch-bench-ab.ps1 -Memory -Borderless
```

Launcher pisze `bench-env.json` i logi do standardowych ścieżek harnessu,
więc `bench_run.py` nie potrzebuje dodatkowych flag. Przed przebiegiem 1
sprawdź plan (`settings.xml: … cap=active|removed`) — musi zgadzać się
z ramieniem.

### Runbook: kliknij okno gry, potem Enter

Okno gry musi być oknem pierwszoplanowym, gdy zaczyna się okno pomiarowe —
okno w tle może mieć inny pacing/DWM. Harness czyta Enter globalnie
(`GetAsyncKeyState(VK_RETURN)`), więc bramka START działa także wtedy, gdy
focus ma gra:

1. Gdy `bench_run.py` wypisze `=== r0N/3 ===` i „START gate: 1) click the game
   window…": kliknij **raz** okno gry (ustaw focus; w scenie referencyjnej
   klik nic nie robi — bez przeciągania).
2. Naciśnij **Enter**. Trafia też do gry — w scenie prologu nic nie robi;
   gdyby otworzył się jakikolwiek ekran/menu, zamknij go i powtórz przebieg.
3. Harness stempluje START od razu po Enter; przez całe `--window` s nie
   dotykaj klawiatury ani myszy, nie alt-tabuj.
4. Po oknie wróć do terminala `bench_run.py`: Enter = zbierz przebieg,
   opcjonalna notatka (crash → opisz).
5. Zamknij grę, uruchom ponownie tymi samymi flagami ramienia, wczytaj save,
   poczekaj na scenę, powtórz kroki 1–4 dla `r02` i `r03`.

Bramki gotowości sceny i zbierania to zwykły Enter w terminalu (gra może wtedy
nie mieć focusa — pomiar jeszcze nie trwa).

### Pola settings.xml w run.json

`bench_collect.py` czyta `settings.xml` przy zbieraniu przebiegu; `bench_run.py`
zapisuje go też w planie i w `campaign.json`. Blok `settings` w `run.json`:

| pole | źródło w XML |
|---|---|
| `graphics.desiredFPS` | `graphics/desiredFPS/@value` |
| `video.frameRateLimit` | `video/frameRateLimit/@value` |
| `video.vSync` | `video/vSync/@value` |
| `video.refreshRate.numerator` / `denominator` | `video/refreshRate/*/@value` |
| `video.resolutionFullscreen.width` / `height` | `video/resolutionFullscreen/*/@value` |
| `refresh_hz` | `numerator/denominator` (pochodne) |
| `cap` | `active` (frameRateLimit ≠ 0), `removed` (0), `unknown` |
| `source`, `file_mtime_utc`, `found` | ścieżka pliku, czas modyfikacji, czy plik istniał |
| `backup` (gdy `.cap-bak` istnieje) | ten sam schemat dla backupu |

Raport dodaje do sekcji Method wiersz `settings.xml: …` i ostrzega
(`settings.xml differs between runs`), gdy trzy przebiegi kampanii mają różne
ustawienia — taką kampanię trzeba odrzucić i powtórzyć.

### Porównanie ramion

- Promocja tylko przy powtórzonej delcie > 5% przy tych samych draws i stanie
  cache („Reguły agregacji"); spread p50 w obrębie ramienia ≤ 1,10.
- Ten sam host, plan zasilania, scena i cache; `env` różni się tylko
  `VICTORY_BORDERLESS` i profilem `ab-*` z `bench-env.json`.
- Oczekiwanie z T2 (`docs/PRESENT-LATENCY.md`): windowed vs borderless p50
  różni się < 1% — ten eksperyment dokłada zdjęty cap, więc różnicę czyta się
  łącznie z `cap` i `refresh_hz` z bloku `settings`.
- Porównaj dwa `report.md` (`benchmarks\runs\2026-11-25-ab\<ramię>\report.md`);
  nie wrzucaj przebiegów z dwóch ramion do jednego wywołania `bench_report.py`
  — to osobne warianty.

## Reguły agregacji

- **p50** = mediana p50 z trzech przebiegów,
- **p95** = najgorszy p95 z przebiegów (konserwatywnie),
- **1% low** = najgorszy `1000/p99` z przebiegów,
- **spread** = max(p50) / min(p50); ≤ 1,10 stabilne, 1,10–1,25 powtórz
  kampanię, > 1,25 odrzuć (szum większy niż mierzony efekt),
- różnica między wariantami jest promowana tylko przy powtórzonej delcie > 5%
  przy tych samych draws i stanie cache.

## Crash i TDR

`bench_guard.py` czyta trzy źródła i liczy okno `[start, stop + 10 s]`
(handlery piszą chwilę po faultcie); dumpy telemetrii mają tolerancję 300 s.

| źródło | co daje |
|---|---|
| `crashes.log` | `device_removed` (`0x887A0007`, `0x887A0004`), `unhandled_exception`, `panic` |
| Event Log Application 1000/1002 | crash/hang procesu; moduł GPU (nvlddmkm, amdkmdag, dxgi, d3d12) → TDR |
| Event Log System 41/4101/1001/17/18/19 | TDR Display, bugcheck, WHEA, utrata zasilania |
| `temp\victory-*.crash.log` | frame, czas działania, `TileHeap used/total` |

`panic` z `failed printing to stderr` (os error 232) to zamknięcie potoku przy
wyjściu, nie crash — nie blokuje werdyktu. Crash tytułu w ciągu 30 s po takim
panice jest traktowany jako zejście procesu (`at_exit`) i też nie blokuje, bo
dzieje się po zamknięciu harnessu, nie w mierzonym oknie. Na tym laptopie nie ma
providera `Display` w Event Log, więc TDR opiera się na `crashes.log` i modułach
z Application 1000.

## Wyjście

```
benchmarks/runs/<kampania>/
  campaign.json          plan kampanii, host, stan cache
  r01/run.json           jeden przebieg (schema 1)
  r01/samples.jsonl      surowe próbki VRAM/commit (lokalne, nie do repo)
  r02/...
  report.md              werdykt + tabela bramek
```

`run.json` nie zawiera treści logów ani assetów gry — tylko liczby, ścieżkę do
logu, dowody crash/TDR oraz blok `settings` z pięciu pól cap/present
`settings.xml` (i backupu `.cap-bak`, jeśli istnieje). Katalog
`benchmarks/runs/` jest w `.gitignore`; do repo trafiają tylko raporty i
snapshoty CSV.

## Ograniczenia, które trzeba podać w raporcie

- Logging INFO dla `host`/`framelog` dokłada pracę; jest włączony w każdym
  wariancie, więc delty są porównywalne, ale absolutny fps może być minimalnie
  niższy niż przy `VICTORY_LOG=warn`.
- Czasy klatek w `frame times` są w ms (liczby całkowite), a przynależność do
  okna jest interpolowana w obrębie bucketa 5 s (błąd < 1 bucket).
- VRAM z `nvidia-smi` co 2 s może pominąć jednoklatkowy skok.
- Brak NVML/DirectX counters: „GPU util” to średnia z próbek, nie per-pass.
- 8 GB VRAM i 16 GB RAM to nadal twardy limit; `commit peak` blisko 15 GB
  oznacza, że system zaczął zamykać aplikacje i pomiar jest nieważny.

## Rozwiązywanie problemów

| objaw | przyczyna | naprawa |
|---|---|---|
| `0 frames`, werdykt `BLOCKED` | log bez INFO | uruchom przez `launch-bench.ps1` |
| `menu-level draws` | menu/ładowanie w oknie | wczytaj save, powtórz przebieg |
| `too few frames` | okno za krótkie przy 0,2 fps | `--window 120` |
| `REFUSING: still running` | gra nie zamknięta | zamknij grę przed przebiegiem |
| `REFUSING: cache is empty` | `--cache warm` bez cache | `-Warm` albo `--cache cold-then-warm` |
| brak VRAM/commit | `nvidia-smi` poza PATH | dodaj do PATH, sprawdź `nvidia-smi` |
| `event log unavailable` | brak uprawnień do dziennika | uruchom terminal jako użytkownik z prawem odczytu Event Log |
