# NIGHT-LOG — 2026-11-27/28

Append-only. One section per decision or gate. No game data, no paths inside the title.

## 2026-11-27 — Phase 0

- Preflight after restart: no `victory.exe`, GPU idle (8 MiB), 6.2 GB RAM free, D: 103.6 GB.
- Power scheme set to High Performance.
- Cloned `https://github.com/fxceless/victory-fork` to `D:\git\victory-fork`.
  - HEAD `4c60466` (2026-11-26 evening): "Pipelines: the pending-pipeline test expects a compute pipeline made at once now that dispatches wait for theirs (#1312)".
- Read fork README (2026-11-26 23:15 UTC): 7.5–8.5 fps at the first boat mission on RTX 4070 12 GB / 32 GB; card is the wall at ~80 ms/frame; memory 23–27 GB RAM and 9.2–9.6 GB VRAM.
- Fork already has wave64→32 forms: `VICTORY_WAVE_WIDE=1|last`, `VICTORY_WAVE_WIDE_ONLY=<hash>`, `VICTORY_LDS_FLAGS`. Diagnostics name our two water programs `5dc3b25986622949` and `6f225b641c5b0708`.
- `--console series-s` is a known black picture in the fork (diagnostics run 304). **Series X only tonight.**
- Decision: baseline the fresh fork before any Fix 2 work. Fix 2 becomes a targeted follow-up only if the fork still refuses compute pipelines.
- Created `D:\Gry\VItoriaBr-data\fork.toml` (game/cache/data outside the repo).
- Created `D:\Gry\VItoriaBr-data\night_harness_fork.py`: real keyboard input (`keybd_event`, not posted messages), screenshots, nvidia-smi CSV, GPU lock, RAM/VRAM gates, one JSON line per run.
- Preset A cuts the fork's 12 GB budgets for 8 GB VRAM / 16 GB RAM:
  `CARD_BUFFERS_MB=768`, `TEXTURE_BUDGET_MB=3072`, `INPLACE_MB=2048`,
  `STAGING_POOL_MB=128`, `SCRATCH_SPARE_MB=64`, `QUEUE2_LANDING_MB=64`,
  `CARD_FETCH_INFLIGHT_MB=32`.
- Build started: `cargo build --release -p victory -j 4`.

### Fresh-fork shader picture (from its own diagnostics)
- `diagnostics/run-283-2026-11-26-debug-layer.txt` shows only **two** 64-lane compute refusals in the intro:
  `2da4beb386509b77` and `369cbe906ea72764`. The older base refused all seven.
- The two water programs `5dc3b25986622949`, `6f225b641c5b0708` are not dispatched in the intro;
  `diagnostics/translate-water-5dc3-6f22-2026-11-26.txt` says `VICTORY_WAVE_WIDE=1` gives them
  colour but dark patches.
- Consequence: Fix 2 is now a **two-hash** follow-up, not a seven-hash project. Try
  `VICTORY_WAVE_WIDE=last` first; only if it fails, extend the emitter.

### Root cause found: the game was on the iGPU
- First fork run died at frame 3027 with `0x8007000E` (OOM) while `nvidia-smi` showed **8 MB / 0 %**
  on the RTX 4060 for the whole run.
- `dxdiag`: AMD Radeon 780M (shared 7837 MB) and NVIDIA RTX 4060 Laptop (dedicated 7956 MB).
- The registry `HKCU\Software\Microsoft\DirectX\UserGpuPreferences` had `GpuPreference=2` only for
  `D:\git\VItoriaBr\target\release\victory.exe`. The new binary at
  `D:\Gry\VItoriaBr-data\bin\victory-fork-plain.exe` had none, so DXGI gave it the iGPU.
- The layer's "budget 6962 MB" was the 780M's shared memory, not the RTX.
- Fix: `GpuPreference=2;` for the new binary and both `target\release\victory.exe` paths; fresh
  cache `fork-cache-rtx` (the iGPU cache is not reused).
- Also: `VICTORY_TEXTURE_BUDGET_MB=3072` bypasses the card-room test (the code returns
  `filled < limit`), which is why textures overran the budget. Preset A now leaves it unset and
  uses `VICTORY_TEXTURE_ROOM_PERCENT=85`.

### RTX verified — and the next wall: host RAM
- After `GpuPreference=2`, the RTX was used: 1.6 GB, 54 % busy, 46 °C, `draws=1176`.
- Series X then died at `victory-image-b99f876b74d4a77f.dll+0x23cf683` (`write 0x0`), after
  `this process has 15496 MB committed, the PC 1220 MB of memory free`.
- Series S died at the **same title address**, `memory.load_percent=92`, process 13.2 GB,
  PC as low as 16 MB free. Console profile does not cap what the title takes from the PC.
- The crash reporter's `system.memory.total=16050548` (KB) matches the PC's 16 GB.
- The title imports `api-ms-win-core-memory-l1-1-0.dll!GlobalMemoryStatusEx`; the layer had no
  override, so the title plans for the whole PC.
- Experiment: worktree `D:\git\victory-fork-memcap`, branch `fix/host-memory-cap`, adds
  `GlobalMemoryStatusEx` (cap physical + page file, leave virtual) behind
  `VICTORY_HOST_MEMORY_MB`; preset `memcap` also cuts the layer's own host copies
  (`INPLACE_MB=512`, `TEXTURE_BUDGET_MB=1024`, `CARD_BUFFERS_MB=256`, staging/scratch/queue small).
- Next run: `fork-s-memcap`, Series S, 1280×720, 10 GB cap.

### Memcap result: not enough
- `fork-s-memcap` (Series S, 10 GB reported, tight budgets) reached frame 3518 but stayed on the
  black loading screen at 9 draws/frame; process 11.5 GB committed, PC 0.3–0.6 GB free, then
  AppHangB1 and Windows closed it. No title AV this time.
- Layer host copies were down to ~1.05 GB (texture budget 1024 MB worked), so the rest is the
  title's own commit plus per-frame/list machinery.
- `EmptyWorkingSet` on the OpenCode UI processes freed ~0 GB (6.31 → 6.28 GB); the agent's pages
  are mostly shared/private and the game cannot reclaim enough that way.
- Next: `fork-s-lean`, the old SafeMem memory shape on the fresh fork (relay/async/queue2/
  back-own-view/gather/join/texture-back off, 2 GB texture budget, 1 GB in-place).

### Pivot: XCL
- Fork was stopped after the lean/Series S crash at the same title address; RAM is the wall on 16 GB.
- Cloned `https://github.com/xcl-dev/xcl` to `D:\git\xcl`, HEAD `8b957bec`, built
  `cargo build --release --workspace` in 2m13s → `target\release\xcl.exe`.
- XCL facts that matter: 26 698 / 26 698 shaders translate; wave64 runs as two 32-lane halves on
  NVIDIA; README reports ~5 fps in 3D on an RTX 5090, ~15 GB committed in the menus on a 32 GB
  machine; `XCL_RUN_SECONDS`, `XCL_ACTIVITY`, `XCL_DEVICE_TYPE=anaconda|lockhart`,
  `XCL_SKIP_BINK`, `XCL_FRAME_INTERVAL_US` are available.
- DXC 1.9.2602.17 in the Windows SDK; game has `shaders.rpf` (411 MB) and `MicrosoftGame.Config`.
- New harness `D:\Gry\VItoriaBr-data\night_harness_xcl.py`: runs `xcl run`, focuses the XCL
  window, sends Enter after 120 s, screenshots every 2 min, then reads
  `%LOCALAPPDATA%\XCL\<title>\logs\xcl.log` and computes fps from `activity (2 s): N presents`.
- First run: `--seconds 600 --device lockhart` (Series S memory), 40-min wall cap.

### Gate G0 (pending)
- [ ] release binary exists and runs `--help`
- [ ] harness smoke test: window, input, screenshot, lock
- [ ] first world entry on preset A

### Prekompilacja XCL: przyczyna stallu na 23 923 / 26 503
- Cache DXIL jest resumowalny: `%LOCALAPPDATA%\xcl\dxil`, klucz z (wersja pakietu,
  toolchain DXC, profil, entry, treść HLSL). Treść zależy od liczby okien pamięci
  i splitu wave64, więc CLI musi używać `--windows 4` jak gra — inaczej 100% chybień.
- Sonda `--precompile --windows 4 --limit 300`: `compiled 0, already cached 475`,
  czyli klucz trafia.
- Prawdziwa przyczyna stallu: `wait_for_memory` dopuszcza kompilacje DXC po wolnym
  **commit** (`ullAvailPageFile`), nie po fizycznej RAM. Rezerwa: 6 GB dla działającej
  gry, 2 GB dla `xcl shaders --precompile`. Przy 15 workerach i ~16 GB wolnego commit-u
  wchodzą wszystkie naraz (~0,7 GB każda) → ~10 GB commit, brak fizycznej RAM, plik
  wymiany, praca staje.
- Fix bez patcha: `XCL_DXC_THREADS=4`.
- Pomiar: 15 workerów — stall ~23 923, working set 5–6 GB, wolne 2–3 GB.
  4 workery — 24 000/26 503 w 36 s, working set 1,7–1,9 GB, wolne 4–5,5 GB.
- Wniosek: to nie był „zły shader”, tylko przeciążenie pamięci przy 15 równoległych
  kompilacjach. Dokument: `docs/XCL-TUNING-8GB-16GB.md`.

### Run 1: tytuł wszedł bez prekompilacji, ale padł na pamięci
- `xcl run` **zawsze** uruchamia okno „Shader preparation” i prekompiluje cały pakiet;
  zamknięcie okna anuluje start (host zwraca 2). Nie ma przełącznika.
- Lokalny patch w `D:\git\xcl` (GPL-2.0-only, poza tym repo): `XCL_SKIP_PREPARATION=1`
  pomija przygotowanie; brakujące programy tłumaczą się na żądanie i trafiają do
  tego samego cache. Build 1m20s.
- Run `xcl-lockhart-113146` (900 s, lockhart, RT off, `XCL_DXC_THREADS=6`):
  tytuł wystartował, **1500 klatek / 18,5 fps** po 80 s (menu/ładowanie),
  potem świat spadł do **1 fps** (41 próbek < 15 fps) i po 137 s proces zakończył się
  statusem `0x80000003` (własny handler OOM tytułu, Breakpad zdumpował minidump).
- Stan przed śmiercią: **commit 24 342 MB** przy 16 GB RAM, `memory.load_percent=94`,
  wolne 833 MB; video 13 655 MB local + 1 233 MB non-local na karcie 8 GB;
  target pages 7 423 MB, pools 7 552 MB, sparse 4 736 MB.
- Wniosek: shadery przestały być wąskim gardłem. Wąskim gardłem jest **pamięć hosta**:
  XCL trzyma zasoby tytułu w host-visible UMA („a texture lies in a GPU view of the
  title's CPU memory: kept in step”), więc commit rośnie razem z VRAM.
- Następny test: `XCL_COHERENT_HEAPS=0` + `XCL_UMA_MB=512` (mniej mirroringu w RAM).

### Run 2/3: to nie jest 3D — to loading z kolejką 57 488 PSO
- `XCL_COHERENT_HEAPS=0` + UMA 512: commit nadal 24,2 GB (pamięć tylko przesunięta
  z „target pages” do non-local). Świat 0,5 fps, crash po 116 s.
- `title_memory_mb=4096`: commit 21,2 GB, crash po 100 s. `XCL_HOST_MEMORY_MB=8192`
  (nowy patch: hook `GlobalMemoryStatusEx`) + UMA 1024: świat 3,0 fps, crash po 132 s.
- **Screenshot `shots/xcl-lockhart-114918-117.png`**: ekran „Loading Story Mode”,
  pasek XCL: `1.0 FPS | compiling shaders: 0 running, 0 done, 57488 pipelines queued`.
  Czyli tytuł nigdy nie wchodzi do 3D — stoi na ładowaniu i buduje pipeline'y.
- Tuż przed śmiercią: setki `CreatePlacedResourceX ... (0x8007000e)` = E_OUTOFMEMORY,
  potem `D3D12 device removed: 0x887a0005`. To wyczerpanie VRAM/hosta, nie zły shader.
- Wniosek: kolejka PSO XCL (preload „na zapas”, 57 488 pozycji) trzyma przetłumaczone
  shadery i buduje je równolegle; karta 8 GB i 16 GB RAM nie wyrabiają.
- Następny test: `XCL_PSO_PRELOAD=0` + `XCL_ASYNC_PSO=0` (buduj tylko to, czego
  tytuł faktycznie używa, po jednym).

### Run 4: stabilne 54 fps, ale czarny ekran — i prawdziwa ściana
- `XCL_PSO_PRELOAD=0` + `XCL_ASYNC_PSO=0`: **brak crashu**, pełne 420 s i 600 s,
  ~9 400–28 700 klatek, p50 21–54 fps. Tytuł żyje.
- Obraz czarny. Activity: **1 draw na 1 prezentację, 0 dispatchy**, DirectStorage
  0 requestów po 35 s. To nie świat 3D — tytuł stoi.
- `report.json`: 52 579 przetłumaczonych pipeline'ów, 0 failed, 0 fallback.
- Prawdziwa przyczyna z logu: **870 kompilacji sterownika**, najdłuższe:
  269 916 ms, 269 731 ms, 263 210 ms, 256 743 ms (DXIL 1,2–1,3 MB każdy),
  `huge, ungated here (a title thread's...)`. Tytuł czeka na te kompilacje.
- Dzielenie dużych compute na łańcuchy dispatchy (`XCL_DIRECT_SPLIT_INSTRUCTIONS`,
  domyślnie 12 500 instrukcji) istnieje **tylko w backendzie direct DXIL**.
  Bez `XCL_DIRECT_DXIL=1` program 1,2 MB idzie do sterownika w całości.
- Następny test: `XCL_DIRECT_DXIL=1` (compute przez direct, kawałki po ~12,5k
  instrukcji, każdy szybki do skompilowania).

### Run 5: direct DXIL zmniejszył kompilacje, ale nie dał obrazu
- `XCL_DIRECT_DXIL=1` + `PSO_PRELOAD=0` + `ASYNC_PSO=0`: 710 s bez crashu
  (okno zamknięte ręcznie na końcu), commit spadł do 17 GB.
- Direct zadziałał: **198 programów podzielonych na 1939 kawałków**; kompilacje
  sterownika spadły z **870 do 64**. Ale największe nadal 143 s (DXIL 1,8 MB —
  direct produkuje większy kod niż HLSL).
- Kluczowe: ostatnia kompilacja sterownika kończy się o **367 s**, a ekran do 693 s
  pozostaje czarny. Czyli po 367 s nic już nie kompiluje — tytuł po prostu nie
  submituje pracy świata: 1 draw/prezentację, **0 dispatchy**, DirectStorage 0.
- `compute split: 198 programs split, 1939 pieces built, 0 chained dispatches issued`
  — łańcuchy istnieją, ale tytuł nigdy ich nie wywołuje.
- Wniosek: ściana kompilacji jest realna, ale nie jest już jedyną. Po jej zejściu
  tytuł stoi w stanie „czekam” (czarny ekran). Następny trop: niewidzialne menu /
  brak inputu — test z przebiegiem Enter/Space/Esc/strzałki/kliknięcia.

### Run 6/7: async wraca do OOM; cap pamięci sam psuje unified memory
- `ASYNC_PSO` domyślne + `PSO_PRELOAD=0` + direct: ekran ładowania GTA VI renderuje
  się poprawnie (`shots/xcl-lockhart-123956-145.png`), pasek:
  `4.7 FPS | compiling shaders: 0 running, 0 done, 58731 pipelines queued`.
  Commit 24 280 MB, `memory.load_percent=96`, OOM po 145 s.
- `ASYNC_PSO=0`: stabilne, ale czarne (tytuł nie submituje świata).
- **Błąd własnego patcha**: `XCL_HOST_MEMORY_MB` sprawiał, że `uma.rs::free_commit`
  widział 4 GB zamiast 18 GB i XCL **wyłączał coherent window** (próg 17 GB):
  „the title's GPU heaps stay outside unified memory”. To mogło pogarszać commit.
  Poprawka: `uma.rs` czyta teraz prawdziwe wartości przez `memcap::system_memory`,
  tak jak `wait_for_memory`.
- Następny test: bez capa, przy 18,1 GB wolnego commit (> 17 GB), żeby unified
  memory w ogóle zadziałało.

### Run 8: 62 MB poniżej progu unified memory
- Bez capa: `UMA: 17346 MB of commit free, under 17408 MB` — **zabrakło 62 MB**.
  Coherent window zostało 512 MB, heaps GPU poza unified memory.
- Commit 24 314 MB, `memory.load_percent=98`, OOM po 172 s. Ekran ładowania nadal
  renderuje się poprawnie.
- Wniosek: albo większy plik wymiany / zamknięcie jednej aplikacji (żeby przekroczyć
  17 408 MB), albo `note_coherent_need` z poprzedniego runu powiększy okno.
- Poprawka `uma.rs` (czyta prawdziwy commit przez `memcap::system_memory`) jest
  zbudowana — cap pamięci nie będzie już wyłączał unified memory.

### Pięć agentów: co znalazły i co weszło na main
- **Pamięć** (`agent/mem`): 92% stron tekstur leżało puste przy ładowaniu świata —
  lazy level pages są teraz domyślne (`XCL_TEXTURE_LEVEL_PAGES=0` wraca do eager).
  Szacunek: **4,6–6,8 GB mniej commit-u** (~18–19 GB). Plus sweep+retry przy
  `CreateHeap` E_OUTOFMEMORY.
- **Kolejka PSO** (`agent/pso`): prawdziwy błąd w `wait_for_memory` — po 60 s
  wpuszczał *wszystkich* czekających naraz („thundering herd”), a preload był
  nieograniczony. Nowa reguła `admission()` z podłogą `XCL_DXC_MIN_FREE_GB=2`,
  cap preloadu `XCL_PSO_PRELOAD_CAP=2048`, licznik pokazuje realną pracę, nie
  stand-iny.
- **Dedup blobów** (`agent/pso`, 18291190): każdy z 58 731 pipeline'ów trzymał
  własną kopię blobów shaderów. Teraz content-addressed `Arc<[u8]>`; 4 testy.
- **Czarny ekran** (diagnoza): to **40 odrzuconych mesh PSO** (konsolowy MS sam
  w slocie AS) — zgodne z upstream #541; a HEAD i tak nie wykonuje przetłumaczonych
  MS/GS (brak #2092). Sam #541 nie wystarczy. To osobna, większa robota.
- **Rozdzielczość**: `XCL_RENDER_SCALE` (patch) — zmniejsza tylko powierzchnię
  prezentacji; obecny blit przy różnym rozmiarze robi crop, więc patch przechodzi
  przez Compositor. Nie zmniejsza renderu 4K tytułu.
- **Upstream**: weszły #1792 (strony sparse raz na run) i #1453 (wyciek allocatora
  przy Reset). #1329/#1517/#1184/#1766 kolidują — do ręcznego rebase'u później.

Zintegrowane na `main`: `c122d162` (lokalne), `4dc5ded3`, `7d16f5f6`, `d5a6a191`,
`ca43c24a`, `5441dabd`, `9b04264b`. Build 1m27s.

### Po integracji: dedup wycofany, pamięć stabilna, ściana = 16 s na compute PSO
- Pierwszy run z dedupem: `0xC0000005` po 76–96 s przy tworzeniu AS/PS. Dedup
  wycofany (`b75c0f30`); AV nie wróciło.
- Krok 1 (10 min): bez crashu, bez OOM, commit 21,4 GB.
- Krok 2 (50 min, 3008 s): bez crashu, commit stabilny 21,4 GB, VRAM 8,85 GB
  local + 4,26 GB non-local. Ale prezentacje ustały po ~116 s i do końca trwały
  kompilacje sterownika:
  `compute PSO, 897776 B DXIL, 16563 ms` — **16 s na jeden program**, tysięcy nie
  ubyło w 50 min.
- To nie DXC i nie pamięć: XCL dzieli compute tylko dla `numthreads == [32,1,1]`,
  a konsolowe grupy 64-wide idą do sterownika w całości.
- Krok 3: patch `XCL_DIRECT_SPLIT_ANY` (próg 256 KB DXIL) — dzielenie dowolnego
  compute, o ile remap `thread id` jest poprawny; inaczej agent ma stopować.

### View heap: nie gubimy drawów; stall to cykl fence
- Analiza porównawcza z VIctory-NVIDIA (GPL-3.0, tylko pomysły): ich fix dotyczy
  per-draw pooli deskryptorów i zwalniania tabel po zakończeniu GPU. XCL ma inną
  budowę: jeden współdzielony heap 1M deskryptorów, brak per-draw pooli i brak
  ścieżki gubienia drawów.
- Dowód z logu: `12812 draws ... (0 skipped, 0 with PC pipelines), 8192 dispatches
  (0 skipped)`; brak `shared heap (1000000) is full`. „1 draw/prezentację” to ekran
  ładowania, nie świat.
- `XCL_HEAP_WINDOWS=1` **nie jest** lekiem — dodaje okna UMA jako UAV, nie sloty view.
- Prawdziwy stall: `Wait64BitValueX ... >= 0xa32` (2610) przy 2606 prezentacjach —
  wait na wartość, która nie nadchodzi. To klasa błędu z upstream **#2052**
  („a wait an earlier signal covers does not make a signal a cycle”).
- Defensywny patch agenta: unplaced page wskazuje parę null SRV/UAV 0/1 zamiast
  aliasować `2k` (`agent/heap`, f419d1e3); drawów nie zmienia.
- W `origin/nvidia-dev` jest niezbudowana w main seria 2^21 + null fill
  (1088d4e0, 23336dd5, 02a834a3, f93c9cbc, 09cf0e3d) — tylko gdyby slotów brakło.

### #2052 + split any: fence naprawiony, zostały 4–5 molochów
- **#2052** („a wait an earlier signal covers does not make a signal a cycle”)
  wszedł na main (`0f4b36a5`). Po nim w logu **zero** linii cyklu fence i zero
  watchdogów; wait’y są normalnie mostkowane do `queue.Wait`.
- **`XCL_DIRECT_SPLIT_ANY=1`** (`7f1a617b`, próg 256 KB DXIL, domyślnie off):
  `compute split: 111 programs split, 1101 pieces built, 144 chained dispatches`.
- Pozostała ściana: 294 kompilacje sterownika na run, z czego **289 < 3 s**, ale
  **5 ≥ 10 s** (maks. 25,7 s). To programy z **LDS**, których splitter nie dzieli.
  Prezentacje stają na ~106–108 s, gdy te 5 wchodzi na ścieżkę krytyczną.
- Każdy run loguje dla nich `driver blob absent` — czyli ich bloby nie trafiają do
  cache. Agent sprawdza limit/połykanie błędu w `driver_cache`; jeśli naprawi,
  kompilują się raz i problem znika bez splitu LDS.

### Punkt odniesienia: pareto-residency (codec-d/cool_fox f4b48ad)
- Repack „Recomp-InsaneRamZes” to dokładnie ten build (`victory.exe` 9,5 MB);
  zbudowany z `Pavl3000/cgbj-fork` na `f4b48ad` — **identyczny rozmiar**.
- Uruchomiony na naszym dumpie: Series S, RAM 3,63 GB, wszystkie importy
  rozwiązane (`0 missing`), bez crashu przez 150 s.
- Ich słabość: `no wave32 lowering for this wave64 program` → gubione dispatche
  compute. XCL tłumaczy 26 698/26 698 — to nasza przewaga.
- Ich preset `pareto-residency` (LEVELS_ON_DEMAND, CARD_REHASH_RUNS, THIN,
  CARD_BUFFERS_MIN_KB=64, JOIN_PARTS=8, UPLOAD_AHEAD) potwierdza nasze kierunki:
  lazy mipy i porównania na karcie.
- Wniosek: XCL jako rekompilator + ich podejście do rezydencji; kod GPL-3.0
  trzymany osobno, bez przenoszenia.

## KOREKTA (21:5x-22:1x) - wycofanie 'tytul renderuje realna scene'
- Obserwacja usera na zywo + zrzuty okien: xcl-lockhart-203520-146.png = pelny kolorowy artwork 2D
  (okladka z Jasonem) przy 21 fps; 203520-177.png = calkowita czern; 213248-177.png = czern;
  215736-273.png = tesieczowy szum (smieci bufora po zatrzymaniu petli).
- METRYKA non_dark z frame dumpa liczyla piksele artworku 2D - NIE dowodzila sceny 3D.
  Scena 3D NIGDY nie pokazala widocznego piksela w zadnym runie.
- Nowa oś czasu: 2D (ladowanie) t=146 -> czern 3D t=150-177 -> park t=158-262.
  Park jest prawdopodobnie KONSEQWENCJA nieudanej próby wejscia w 3D, nie niezalezna usterka.
- Eksperymenty 1-4 (auth, host-RAM cap, network, inflated budget) - wszystkie opisane w
  research/xcl-agents/16-budget-gate.md; budget zwiekszyl zasob prezentacji o ~100s (korelacja
  slaba, ale kierunek zgodny z bramka budzetowa).
- Odpalone sciezki tla: (1) patch uczciwego ksiegowania TitleMemoryStatus (agent, xcl-wt-memacct),
  (2) diagnostyka 'dlaczego tylko 3D jest czarne' (agent read-only, raport 18-black-3d.md):
  tropy - lustrowanie IB spoza UMA przy kazdym drawie, translacja depth/reversed-Z,
  emisja outputu dwuprzebiegowego MS, kompozycja plane'ów (xcl-wt-ui 1041d843).

## PRZEŁOM 18-black-3d: przyczyna 'tylko 3D czarne' = commit gate okna UMA (agent, 21:xx)
- uma.rs:796/813: jezeli host ma < 17408 MB wolnego commitu, okno coherent spada do fallback
  512 MB i GPU-heaps tytułu laduja sie POZA UMA. W runach bylo 17291 MB — brakowalo ~117 MB.
- ind.rs:768 fail-closes ExecuteIndirect(DispatchMesh) z argumentami poza UMA:
  6498/19053 rysowan pominietych (WARNy capowane do 8, t=141.9/152.1 — tuz przed czernia).
- Skutek: plane0 (1920x1080) pusty, widoczny tylko artwork 2D; stall fence t=168 = park.
- Wyjasnia wszystkie wcześniejsze null-resulty: gate czyta maszyne z pominięciem capów
  (memcap::system_memory) — dlatego XCL_HOST_MEMORY_MB nic nie dal; a budżet 28672
  pogorszył run (więcej spillu → mniej wolnego commitu → gate łamie się szybciej).
- Nastepny krok (bez builda): powiekszyc pagefile tak, by FreeVirtualMemory ≥ 18874368 KB
  (~18.4 GB), run 300 s + XCL_TRACE_FRAME=1 XCL_FRAME_DUMP=20. Bramki: brak WARN UMA,
  (0 skipped) do t≈180. Jesli czern przy 0 skips → falsyfikacja C → merge xcl-wt-ui.

## Run 233509 (XCL_COHERENT_MB=4096): gate omijany, 0 skips - a 3D NADAL czarne
- uma.rs:788-790: z env XCL_COHERENT_MB branch wroaca bez sprawdzania free_commit - 0 WARN UMA,
  0 'outside unified memory', licznik console code so far: 37654 draws, **0 skipped**, coherent 3008/4095 MB.
- Park nie zniknal (onset ~184 s), fps srednie 7.7. Cover art Lucia pelnoekranowo WIDOCZNY w t=126
  (17.4 fps) - 2D OK; t=191 = pelna czern. non_dark=0 tylko w ostatnim dumpie (= klatka po parku).
- WNIOSK: teoria C (fail-closed draws) ODRZUCONA jako przyczyna czarnego 3D. Zgodnie z drzewem
  decyzji z 18: merge diagnostyki planow (1041d843 -> 5b77756f na main, ff-only, build 1m47s)
  i run z XCL_TRACE_FRAME=1: pytanko rozstrzygajace - czy plane0 (gra) jest PEŁNY (bug kompozycji)
  czy PUSTY (shadery 3D nic nie produkuja mimo wykonania).
