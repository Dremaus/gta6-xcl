# Stabilność, TDR, sterownik i zasilanie — 2026-11-25

Zakres: fxceless/victory na RTX 4060 Laptop 8 GB / 16 GB, Windows 11.
Dokument powstał **tylko z logów i zapytań systemowych**: nie zmieniano runtime'ów,
nie uruchamiano gry. Nie powtarza analizy wydajności z `PERF-DIAGNOSIS-2026-11-25.md`
i `EXPERIMENTS-2026-11-25.md`; skupia się na utracie urządzenia, sterowniku,
pamięci i zasilaniu.

## Skrót dla operatora

1. To **nie jest klasyczny TDR 2 s** w zarejestrowanym oczekiwaniu: ostatnie
   oczekiwanie trwało 15,9 ms, a kod wykrył utratę urządzenia przy robieniu
   tekstur, nie przy długim command liście.
2. `0x887A0007` to `DXGI_ERROR_DEVICE_RESET` (sterownik zresetował urządzenie),
   a `0x887A0004` to `DXGI_ERROR_UNSUPPORTED` z zapytania DRED — release build
   nie ma włączonego DRED, więc „brak breadcrumbs” nic nie mówi o przyczynie.
3. W tym samym runie **jedno submission się nie zakończyło** (18 164 started /
   18 163 finished). Nie można wykluczyć zawieszenia GPU; do rozstrzygnięcia
   potrzebny jest build diagnostyczny z DRED.
4. 7,7 GB VRAM na 8,0 GiB i 16 GB RAM to **wzmacniacze**, nie udowodniona
   przyczyna. VItoriaBr działa stabilnie przy 5,3–7,5 GB, więc sam VRAM nie
   wyjaśnia różnicy.
5. Nie podnoś `TdrDelay` jako pierwszego kroku. Najpierw DRED repro na
   konfiguracji crashującej (D1), potem profil bezpieczny (S1b), potem izolacje.
6. Nowe runy przenoszą korelację z VRAM/copy-back na ścieżkę równoległego
   wysyłania (relay/late/async/queue2): trzy utraty urządzenia miały `RELAY=1`
   lub `LATE_WAIT=1`; dwa runy 3D bez tej rodziny (safe-mem 22:06, dred 22:14)
   nie straciły urządzenia mimo copy-back 1637/2491 ms i VRAM aż do 53 MB free.
7. Crash 3 (21:56:58Z, opt+memory) padł przy **1 submission / 1 list** i
   `RELAY=1` — to nie jest głębokość kolejki ani timeout; to treść submission
   albo wyścig wokół niego. Nazwie go tylko build diag z DRED.
8. Run dred nie miał warstwy debug: `0x887A002D` — brakuje Graphics Tools
   (d3d12sdklayers.dll). DRED bez niej działa, ale page-fault info i GBV są
   martwe; zainstaluj ją przed D1.

## Dowody

| Fakt | Wartość | Źródło |
|---|---|---|
| GPU | NVIDIA GeForce RTX 4060 Laptop GPU, 8 188 MiB, 232 MiB reserved | `nvidia-smi` |
| Sterownik | 617.14, KMD 617.14, CUDA UMD 13.4, data 2026-09-17 | `nvidia-smi`, `Win32_VideoController` |
| Laptop | Lenovo Legion Slim 5 16AHP9 (83DH), BIOS NRCN24WW | `Win32_ComputerSystemProduct`, `Win32_BIOS` |
| OS | Windows 11 Home 10.0.26200 | `Win32_OperatingSystem` |
| Crash 1 | 22:05:11 lokalnie, PID 10016: `VICTORY_RELAY=1`, 11 listów, `0x887A0004` + `0x887A0007` | `crashes.log` |
| Crash 2 | 22:11:34 lokalnie, PID 9824: `VICTORY_LATE_WAIT=1`, 1 list, 15,9 ms, `0x887A0007` | `crashes.log`, `game-stderr.log` |
| Crash 2 kontekst | start logu 21:07:45, reset 21:11:34 (~3 min 49 s); frame 4112 o 21:10:44; wykryty w `draw.rs` przy „textures picked by index were made ready” | `game-stderr.log` |
| Crash 3 | 21:56:58Z, PID 32848: `VICTORY_RELAY=1` (z `LATE_WAIT=1`, `ASYNC_SUBMIT=1`, `QUEUE2=1`), 1 submission / 1 list, `0x887A0007`, breadcrumbs niedostępne (`0x887A0004`) | `crashes.log` |
| Crash 3 kontekst | run opt+memory od 21:54:12Z (~2 min 44 s); 3D przy 0,3–1,9 fps; heap buffers 13–272 ms; copies 189–1308 ms; copy-back 132–1613 ms | pomiar operatora (stderr zrotowany do nowego runu) |
| Safe-mem, bez crasza | 22:06:11–22:08:46Z: relay/join/async/queue2 wyłączone; 3D 0,3 fps; copies 230–467 ms (226–303 MB/klatkę), copy-back 380–1637 ms; karta 5081 MB / budżet 7188 MB; okno zamknięte ręcznie | `safe-mem-stderr.log` |
| DRED diag, bez crasza | 22:14:12–22:19:16Z: build diag, `DRED=1 DEBUG=1`; **brak debug layer `0x887A002D`**; menu 30 fps, potem 3D 0,2 fps; copy-back 2436–2491 ms; VRAM free 53 MB; zatrzymany ręcznie | `dred-stderr.log` |
| Ostatni list | 18 164 started / 18 163 finished — jedno submission nie wróciło | `game-stderr.log` |
| VRAM w crashu | 7,7 GB / 8,0 GiB (8 188 MiB, ~94%) | pomiar operatora |
| RAM | 16 GB, wolne 4,37 GB w idle, pagefile 34 466 MB, peak 10 569 MB | `Win32_OperatingSystem`, `Win32_PageFileUsage` |
| TDR | brak `TdrDelay`/`TdrDdiDelay`/`TdrLevel` w rejestrze → domyślne 2 s | `HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers` |
| Zdarzenia | brak `Display` 4101/4102 i `nvlddmkm` w czytelnym System log | `Get-WinEvent` |
| DxgKrnl | `Microsoft-Windows-DxgKrnl-Operational` wymaga administratora; nie odczytano | `wevtutil` → „Odmowa dostępu” |
| DRED | `GetAutoBreadcrumbsOutput()` → `0x887A0004`; release build nie ma feature `diagnostics` | kod `host.rs`, `build.log` |
| Pipeline library | 211,8 MB; save 219 148 916 i 222 120 098 B; część PSO „did not load: 0x80070057” po 13–14 s | `game-stderr.log` |
| Zasilanie | Balanced, AC, bateria 100%, ASPM = maximum power savings (AC/DC), CPU min 80% AC | `powercfg` |
| GPU idle | 43 °C, 1,7 W, P8, 210 MHz, PCIe Gen1 x8 (max Gen4 x8) | `nvidia-smi` |
| GPU pod obciążeniem | 42–52 °C, 0–46%, brak HW thermal throttle; SW power cap 63,6 ms łącznie | pomiar operatora, `nvidia-smi -q` |
| Hybryda | dGPU `Display Active: Disabled`; panel na Radeon 780M | `nvidia-smi -q`, `Win32_VideoController` |
| VItoriaBr | inne sygnatury: panic na zamkniętym stderr (os error 232), `0x80000003` w `victory-image-*.dll`; brak device removed | `VItoriaBr\...\crashes.log` |

Uwaga: logi gry są w UTC (`21:11:34Z`), a log zdarzeń Windows i znaczniki plików
są lokalne (`22:11:34`). Nie mieszaj tych czasów przy korelacji.

Crash 1 ma tylko wiersz zbiorczy w `crashes.log`; jego `game-stderr.log` nie
jest w obecnym pliku (log zaczyna się 21:07:45 UTC, już po crashu 1). Szczegóły
„textures picked by index were made ready” dotyczą **wyłącznie crashu 2**.
Nie przenoś ich na crash 1 bez dowodu.

## Triage

### 1. Długość command listów

`of 11 lists` i `of 1 lists` to **liczba host listów w flightach** (`runs.len()`),
nie liczba komend w jednym liście. Release log nie podaje liczby komend.
Ostatnie oczekiwanie w crashu 2 trwało 15,9 ms, więc **ten** wait nie był TDR-em.
Ale jedno submission nie wróciło, więc zawieszenie GPU wcześniejszego listu
jest nadal możliwe. Rozstrzygnięcie: DRED + debug layer w buildzie diagnostycznym
(`VICTORY_D3D12_DRED=1`, `VICTORY_D3D12_DEBUG=1`).

### 2. Ciśnienie VRAM

7,7 GB z 8,0 GiB (8 188 MiB) to ~94%; 232 MiB jest reserved, a WDDM budget jest niższy
niż fizyczne 8 GB. Runtime zwolnił w tym runie 818 563 obiekty od razu i
1 652 245 po running submission (to liczniki obiektów, nie bajty). W logu są
też setki „texture picked by index changed after its upload” i jeden
„fill ... ahead of a flight”, po którym runtime sam przeszedł na zachowanie
`VICTORY_FILL_WAIT=1`.
To dowód dużego churnu, nie dowód wycieku. 7,7 GB jest na granicy; profil
bezpieczny ma zejść poniżej ~7,2 GB i mierzyć to, a nie zakładać.

Nowe runy **osłabiają H3**: safe-mem wszedł w 3D przy 5,1 GB na karcie (budżet
7188 MB) bez utraty urządzenia, a dred doszedł do 53 MB wolnego VRAM bez utraty
urządzenia. VRAM jest wzmacniaczem, nie prognozatorem resetu.

`BAR1` (8 163/8 192 MiB w idle) to aperture/resizable BAR, **nie** wolny VRAM.
Nie używaj `BAR1 free` jako wskaźnika headroomu.

### 3. Relay / join / gather

Trzy utraty urządzenia mają jeden wspólny mianownik: crash 1 `RELAY=1`
(11 listów), crash 2 `LATE_WAIT=1` (1 list), crash 3 `RELAY=1` + `LATE_WAIT=1`
+ `ASYNC_SUBMIT=1` + `QUEUE2=1` (1 submission / 1 list). Dwa runy 3D bez tej
rodziny przełączników (safe-mem 22:06, dred 22:14) przetrwały **gorsze**
copy-back (1637/2491 ms) i niższy VRAM (53 MB free) bez utraty urządzenia.
To podnosi H5 z „niska” do „średnia-wysoka”: podejrzana jest ścieżka
równoległego wysyłania i kopiowania wstecz (relay/late/async/queue2), a nie
sama objętość kopii. Crash 3 padł przy 1 submission w locie, więc to nie
głębokość kolejki — tylko treść submission albo wyścig wątku relay z submitem.
Profil bezpieczny nadal wyłącza `RELAY`, `LATE_WAIT`, `ASYNC_SUBMIT`, `QUEUE2`,
`JOIN_PARTS`, `INDIRECT_GATHER`, `BACK_OWN_VIEW`; `JOIN_COPIES` i
`CARD_REHASH_RUNS` wracają do 1 (patrz S1b) — łączą kopie/passy, nie dodają
wątków.

„Stabilny profil” z `EXPERIMENTS-2026-11-25.md` (relay=0, join/gather/back off,
library map off, texture 4096, card 768) przetrwał 150 s przy 7,7 GB. To za krótko:
crash 2 wystąpił ~3 min 49 s po starcie logu, po klatce 4112, więc 150 s nie jest
bramką stabilności.

### 4. Pipeline library / mapowanie

Biblioteka ma 211,8 MB; runtime zapisał 219 MB i 222 MB, a część PSO nie ładowała
się z biblioteki (`0x80070057` = `E_INVALIDARG`) i była kompilowana od nowa
(13–14 s na compute, 3,1 s na mesh). W chwili crashu „its file is not mapped”,
więc mapowanie **nie było aktywne** w tym momencie. To osłabia hipotezę, że
mapowanie biblioteki jest bezpośrednią przyczyną, ale biblioteka jest nadal
ryzykiem stabilności/wydajności: duży plik, częste save'y, długie kompilacje.
Test: `VICTORY_LIBRARY_MAP=0`, `VICTORY_LIBRARY_LOCK=1`; opcjonalnie odłóż
`host-pipelines.bin` (runtime odbuduje) i sprawdź, czy `0x80070057` zniknie.

`0x80070057` nie jest utratą urządzenia. Nie myl go z `0x887A0007`.

### 5. Wersja sterownika

617.14 (2026-09-17) jest nowszy niż typowy OEM driver Legion. W System log
**nie ma** wpisów `nvlddmkm` ani `Display` w okolicy obu crashy; `Get-WinEvent
-ProviderName nvlddmkm` nie zwrócił żadnego zdarzenia. To oznacza, że wbudowany
`drvwatch` (który w innych runach widział `nvlddmkm` 153 na 2,7–6,3 s przed
utratą) **nie miał czego złapać** na tym systemie. Nie traktuj braku wpisów
jako dowodu braku błędu sterownika — DxgKrnl-Operational wymaga admina.

A/B sterownika to ostatni krok, nie pierwszy: czysta instalacja / OEM driver
może cofnąć inne poprawki. Najpierw DRED i profil bezpieczny.

### 6. TDR delay

`TdrDelay`, `TdrDdiDelay`, `TdrLevel` nie są ustawione → obowiązuje domyślne
2 s. W czytelnym System log nie ma 4101/4102, ale DxgKrnl-Operational jest
niedostępny bez podniesienia uprawnień. `0x887A0007` to DEVICE_RESET, nie
DEVICE_HUNG; reset mógł nastąpić od razu po błędnym poleceniu/view albo po
wcześniejszym zawieszeniu. Podnoszenie `TdrDelay` tylko wydłuża ewentualny
hang i maskuje problem; nie jest fixem.

### 7. Zasilanie, termika, hybryda

Brak dowodów throttlingu: 42–52 °C, 0–46%, `HW Thermal Slowdown: Not Active`,
`SW Power Capping` 63,6 ms łącznie. To nie jest problem termiczny.

Są dwa realne czynniki systemowe:

- **ASPM = maximum power savings** na AC i DC; w idle PCIe zchodzi do Gen1 x8
  (max Gen4 x8). To może dodawać latencję linku przy intensywnych uploadach.
  Test: ASPM Off + High Performance.
- **Hybryda**: dGPU ma `Display Active: Disabled`, panel obsługuje Radeon 780M.
  Render idzie przez dGPU, prezent przez iGPU; to dodatkowa kopja i inne
  zarządzanie pamięcią. Jeśli Legion Space/Vantage ma MUX, test „dGPU only”
  jest wart osobnego A/B (wymaga restartu), ale nie jest pierwszym krokiem.

## Hipotezy i testy rozstrzygające

| ID | Hipoteza | Pewność | Dowód | Test rozstrzygający |
|---|---|---|---|---|
| H1 | Nieobsługiwany/błędny view tekstury w `draw.rs::heap_textures` resetuje device | średnia (niżej niż wcześniej: safe-mem prowadził pass tekstur 2,5 min bez resetu) | crash 2 wykryty dokładnie w tej pętli; ostatni view to placed 2D BC1 1024×1024; komentarz w kodzie „a texture view the host refuses removes the device” | `VICTORY_HEAP_TEXTURES=0` na 15 min: brak resetu = H1; obraz będzie niekompletny |
| H2 | Wcześniejsze submission zawiesiło GPU i sterownik zresetował device | średnia-wysoka | 18 164 started / 18 163 finished; crash 3 przy 1 submission/1 list; brak 4101 w czytelnym logu; DxgKrnl niedostępny | D1: build diag + DRED + debug layer na konfiguracji crashu 3; GBV off |
| H3 | VRAM/commit na 8 GB/16 GB powoduje failed allocation/view i reset | niska-średnia (spadła) | 7,7 GB / 8,0 GiB w crashu 2, ale safe-mem 5,1 GB i dred 53 MB free bez utraty urządzenia | S2/S3: VRAM <7,2/<6,5 GB; jeśli reset znika dopiero poniżej progu = H3 |
| H4 | Regresja sterownika 617.14 (placed/BC1/library) | średnia-niska | nowy driver; brak `nvlddmkm`; library `0x80070057` | A/B clean install / OEM/previous driver, 2×30 min |
| H5 | Wyścig relay/queue2/late/async wokół wysyłania i copy-back | **średnia-wysoka (nowa najwyższa)** | 3/3 utraty z `RELAY=1` lub `LATE_WAIT=1`; 2/2 runy 3D bez tej rodziny przeżyły większe copy-back (1637/2491 ms) i niższy VRAM (53 MB free) | D1 (DRED repro na konfiguracji crashu 3) + bisect D1a/D1b/D1c: `RELAY`, `QUEUE2`, `LATE_WAIT` pojedynczo |
| H6 | ASPM/termika/hybryda | niska | brak thermal throttle; ASPM max; Gen1 w idle | ASPM Off + High Performance + (opcjonalnie) dGPU-only; 30 min |

Kolejność: **H5 przez D1** (DRED repro na konfiguracji crashu 3) → **H2**
(ta sama faza: breadcrumbs nazwą komendę/list) → **H1** (S1-H) → **H3** (S2) →
**H4** (S3) → **H6**. Nie łącz kilku hipotez w jednym runie, bo tracisz
możliwość przypisania wyniku.

## Macierz stabilności

| ID | Profil | Kluczowe ustawienia | Oczekiwany efekt | Ryzyko | Bramka zaliczenia |
|---|---|---|---|---|---|
| S0 | referencja agresywna (to, co crashuje) | `RELAY=1`/`LATE_WAIT=1`, join/gather/back wg runu, library map=1, texture 4096, card 768 | odtwarza reset w ≥2 runach | wysoki | crash oczekiwany; nie powtarzać bez potrzeby |
| S1 | **bezpieczny 8 GB** | relay/late=0, join/gather/back=0, async/queue2=0, library map=0/lock=1, texture 3072, card 512, staging 256, inplace 2048, levels=1, fill_wait=1 | cel 6,8–7,2 GB; wolniej; mniej kopii w locie; jeśli >7,4 GB → S2 | brakujące tekstury, dłuższe streamingi | 30 min bez resetu, VRAM p95 <7,2 GB, brak nowego `nvlddmkm`/4101, frame log ciągły |
| S1b | **bezpieczny 8 GB v2 (nowy baseline)** | jak S1, ale `JOIN_COPIES=1`, `CARD_REHASH_RUNS=1`; relay/late/async/queue2 nadal 0 | ogranicza liczbę kopii i passów hashowych bez dodawania wątków; w safe-mem przy obu off było 10 171 kopii / 303 MB na klatkę i 685 passów hash | `JOIN_COPIES` był kiedyś podejrzany; jeśli S1b crashuje, wróć do S1 i bisect sam join | 30 min bez resetu; usual-frame copies <50 ms, copy-back <100 ms; VRAM p95 <7,2 GB |
| D1 | **DRED repro crasher (celowy crash)** | dokładna konfiguracja crashu 3: `RELAY=1`, `LATE_WAIT=1`, `ASYNC_SUBMIT=1`, `QUEUE2=1` + te same limity pamięci co run opt+memory; build diag, `D3D12_DEBUG=1`, `D3D12_DRED=1`, `CARD_METER=1`, GBV=0 | przy utracie breadcrumbs/debug layer nazwie komendę i list; card meter pokaże, który list zawisł | wysoki (celowy crash) | crash w ≤15 min z nazwaną komendą; brak crasza = konfiguracja nie deterministyczna, przejdź do bisectu D1a/D1b/D1c |
| D1a/D1b/D1c | bisect rodziny relay | pojedynczo: D1a `RELAY=1`; D1b `QUEUE2=1`; D1c `LATE_WAIT=1` — reszta off | izoluje, który przełącznik odtwarza reset | średni | 15 min na wariant; crash = winowajca |
| S1-H | S1 + wyłączona pętla tekstur | `HEAP_TEXTURES=0` | jeśli brak resetu, H1 potwierdzona; obraz niekompletny | tylko diagnostyka | 15 min bez resetu |
| S2 | S1 + twardy headroom | texture 2560, card 256, targets 2560, inplace 1024, staging 128, reupload_when_full=0 | VRAM <6,5 GB; więcej odmów tekstur | brakujące tekstury, możliwe braki targetów | 30 min bez resetu; akceptacja wizualna |
| S3 | S1 + izolacja biblioteki | `LIBRARY_MAP=0`, `LIBRARY_HANDLE=0`, `LIBRARY_LOCK=1`, `PIPELINE_WAIT_MS=1000` | mniej wyścigów mapowania; wolniejsze PSO | dłuższe ładowanie | 30 min bez resetu; brak burzy `did not load` |
| S4 | S1 + host/zasilanie | High Performance, ASPM Off, NVIDIA Overlay off, Avast exclusions, zamknięte tło | mniej stallów linku/prezentu | brak | 30 min bez resetu; PCIe Gen≥3 pod obciążeniem |
| S5 | diagnostyka TDR (nie fix) | `TdrDelay=10` | zamienia reset w dłuższy hang, jeśli to timeout | systemowy; nie zostawiać | tylko gdy wait >2 s; revert po teście |
| S6 | A/B sterownika | clean 617.14 vs OEM/previous | jeśli regresja, brak resetu | czas, inne regresje | 2×30 min na wersję |

S1b jest profilem wyjściowym; S1 zostaje jako fallback (bisect `JOIN_COPIES`).
S1-H i S2 są do rozstrzygnięcia H1/H3, nie do normalnej gry. S3/S4 są do
odseparowania biblioteki i zasilania. D1 i D1a–c to diagnostyka TDR, nie gra.
S5 nie jest rozwiązaniem.

## Profil bezpieczny 8 GB (S1b)

Ustaw w tej samej sesji PowerShell, w której uruchamiasz dotychczasową komendę
gry. Nie zmieniamy runtime'u ani argumentów; wklej swoją zwykłą komendę po
ustawieniu zmiennych. S1b = S1 z `JOIN_COPIES=1` i `CARD_REHASH_RUNS=1`: obie
flagi **łączą** pracę (kopie tytułu, passy hash na karcie), nie dodają wątków
ani submission; w safe-mem przy obu off kopie dobiły do 10 171 / 303 MB na
klatkę i 685 passów hash. Jeśli S1b crashuje, wróć do `JOIN_COPIES='0'`
(S1) i sprawdź, czy to join jest winny.

```powershell
$env:VICTORY_RELAY='0'
$env:VICTORY_LATE_WAIT='0'
$env:VICTORY_JOIN_PARTS='0'
$env:VICTORY_JOIN_COPIES='1'       # S1b: łączy kolejne kopie tytułu (S1: '0')
$env:VICTORY_INDIRECT_GATHER='0'
$env:VICTORY_BACK_OWN_VIEW='0'
$env:VICTORY_ASYNC_SUBMIT='0'
$env:VICTORY_QUEUE2='0'
$env:VICTORY_CARD_REHASH_RUNS='1'  # S1b: łączy passy hash na karcie (S1: bez flagi = off)

$env:VICTORY_LIBRARY_MAP='0'
$env:VICTORY_LIBRARY_LOCK='1'

$env:VICTORY_TEXTURE_BUDGET_MB='3072'
$env:VICTORY_CARD_BUFFERS_MB='512'
$env:VICTORY_CARD_BUFFERS_MIN_MB='1'
$env:VICTORY_STAGING_POOL_MB='256'
$env:VICTORY_INPLACE_MB='2048'

$env:VICTORY_LEVELS_ON_DEMAND='1'
$env:VICTORY_FILL_WAIT='1'
$env:VICTORY_DRIVER_WATCH='1'
$env:VICTORY_FRAME_LOG='1'

# Tu wklej dotychczasową komendę uruchomienia, np.:
# & 'D:\git\fxceless-victory\target\release\victory.exe' <argumenty>
```

Ustawienia gry: 720p, ambient 0, okno (nie fullscreen), tekstury nisko, bez RT.
To nie jest profil wydajnościowy; to profil przeżycia 30 min.

`TEXTURE_BUDGET_MB`, `CARD_BUFFERS_MB` i `CARD_ROOM_FOR_TARGETS_MB` to **limity**,
nie rezerwacje — mierz `nvidia-smi`, nie sumuj ich. `TEXTURE_ROOM_PERCENT` ma
efekt tylko wtedy, gdy `TEXTURE_BUDGET_MB` nie jest ustawione; w S1 limit
3072 MB ma pierwszeństwo. `INPLACE_MB` i `STAGING_POOL_MB` dotyczą RAM (16 GB),
nie VRAM; ich obniżenie zmniejsza ciśnienie na commit/pagefile, ale może
zwiększyć liczbę remapów.

Jeśli S1 dalej dobija do 7,7 GB, przejdź do S2 (twardy headroom). Jeśli S1
gubi zbyt wiele tekstur, podnieś `TEXTURE_BUDGET_MB` do 3584 i `CARD_BUFFERS_MB`
do 768, ale wtedy zmierz VRAM i traktuj jako eksperyment, nie jako bezpieczny.

## Zbieranie dowodów — dokładne komendy

### Snapshot przed runem

```powershell
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$dir = "D:\Gry\fxceless-data\logs\stability-$stamp"
New-Item -ItemType Directory -Force $dir | Out-Null

nvidia-smi -q > "$dir\nvidia-smi.txt"
nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used,memory.free,temperature.gpu,power.draw,clocks.sm,pstate,pcie.link.gen.current,pcie.link.width.current --format=csv > "$dir\gpu.csv"
Get-CimInstance Win32_VideoController | Format-List > "$dir\video.txt"
Get-CimInstance Win32_OperatingSystem | Format-List > "$dir\os.txt"
Get-CimInstance Win32_PageFileUsage | Format-List > "$dir\pagefile.txt"
dxdiag /t "$dir\dxdiag.txt"

powercfg /getactivescheme > "$dir\power.txt"
powercfg /query SCHEME_CURRENT SUB_PCIEXPRESS >> "$dir\power.txt"
powercfg /query SCHEME_CURRENT SUB_PROCESSOR >> "$dir\power.txt"

Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\GraphicsDrivers' `
  -ErrorAction SilentlyContinue > "$dir\graphicsdrivers.txt"
reg query "HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers" /v HwSchMode `
  >> "$dir\graphicsdrivers.txt" 2>&1

Get-Content 'D:\Gry\fxceless-data\logs\game-stderr.log' -Tail 200 > "$dir\stderr-tail.txt"
Copy-Item 'D:\Gry\fxceless-data\data\7952987A\crashes.log' "$dir\crashes.log"
```

### Logi crashu i kontekst

```powershell
Get-Content 'D:\Gry\fxceless-data\data\7952987A\crashes.log' -Tail 80

$pattern = 'device removed|host GPU failure|when the host device went|no breadcrumbs|' +
           'graphics driver reported|pipeline library|textures picked by index|' +
           'frame times|submissions started'

Select-String 'D:\Gry\fxceless-data\logs\game-stderr.log' -Pattern $pattern |
  Select-Object -Last 80 |
  ForEach-Object { "$($_.LineNumber): $($_.Line)" }
```

### Zdarzenia systemowe

```powershell
Get-WinEvent -FilterHashtable @{
  LogName='System'; StartTime=(Get-Date).AddHours(-4)
} -MaxEvents 5000 |
  Where-Object {
    $_.ProviderName -in @('Display','nvlddmkm') -or
    $_.Id -in @(4101,4102,153,14)
  } |
  Format-List TimeCreated,Id,ProviderName,LevelDisplayName,Message |
  Out-File "$dir\events.txt"
```

`Microsoft-Windows-DxgKrnl-Operational` wymaga elevation:

```powershell
# Uruchom w PowerShell jako administrator
wevtutil qe Microsoft-Windows-DxgKrnl-Operational /c:200 /rd:true /f:text > "$dir\dxgkrnl.txt"
wevtutil qe System "/q:*[System[Provider[@Name='nvlddmkm' or @Name='Display']]]" /c:100 /rd:true /f:text > "$dir\gpu-events.txt"
```

### VRAM, link, throttling

```powershell
nvidia-smi --query-gpu=memory.total,memory.used,memory.free,temperature.gpu,power.draw,power.limit,clocks.sm,pstate,pcie.link.gen.current,pcie.link.width.current --format=csv
nvidia-smi -q -d MEMORY,PERFORMANCE,POWER,CLOCK
```

### Sampler 30 min

```powershell
nvidia-smi dmon -s pucvmet -d 1 -c 1800 |
  Tee-Object -FilePath "$dir\dmon.csv"
```

Jeśli `dmon` nie działa na tej wersji, użyj pętli:

```powershell
1..1800 | ForEach-Object {
  $line = (Get-Date -Format o) + ',' +
    ((nvidia-smi --query-gpu=memory.used,memory.free,temperature.gpu,utilization.gpu,pcie.link.gen.current --format=csv,noheader,nounits) -join ',')
  Add-Content "$dir\gpu-samples.csv" $line
  Start-Sleep -Seconds 1
}
```

### Frame log i commit

```powershell
$env:VICTORY_FRAME_LOG='1'   # ustaw przed startem gry

Select-String 'D:\Gry\fxceless-data\logs\game-stderr.log' -Pattern 'frame times:' |
  Select-Object -Last 12 |
  ForEach-Object { $_.Line }

Get-CimInstance Win32_OperatingSystem |
  Select-Object FreePhysicalMemory,FreeVirtualMemory,TotalVirtualMemorySize
Get-CimInstance Win32_PageFileUsage |
  Select-Object AllocatedBaseSize,CurrentUsage,PeakUsage
```

### Watchdog: VRAM + frame + zdarzenia

Uruchom w osobnym oknie podczas testu. To nie zatrzyma gry automatycznie;
przy ostrzeżeniu przerwij run i zapisz snapshot.

```powershell
$log = 'D:\Gry\fxceless-data\logs\game-stderr.log'
$start = Get-Date
$n = 0

while ($true) {
  $n++
  $g = (nvidia-smi --query-gpu=memory.used,memory.free,temperature.gpu,utilization.gpu,pcie.link.gen.current --format=csv,noheader,nounits) -split ',' |
        ForEach-Object { $_.Trim() }
  $used = [int]$g[0]; $free = [int]$g[1]; $temp = [int]$g[2]
  $util = [int]$g[3]; $gen  = [int]$g[4]

  "{0:HH:mm:ss} VRAM={1} MiB free={2} temp={3}C util={4}% PCIe=Gen{5}" -f `
    (Get-Date), $used, $free, $temp, $util, $gen | Write-Host

  if ($used -ge 7300) { Write-Warning "VRAM >= 7300 MiB ($used): przerwij / obniż budżet" }
  if ($free  -le 500)  { Write-Warning "VRAM free <= 500 MiB: przerwij" }
  if ($temp  -ge 80)   { Write-Warning "GPU >= 80C: przerwij" }
  if ($gen -lt 3 -and $util -ge 20) { Write-Warning "PCIe Gen$gen pod obciążeniem: sprawdź ASPM" }

  if (Select-String -Path $log -Pattern 'device removed|host GPU failure' -Quiet) {
    Write-Warning "device loss w logu"; break
  }

  if (((Get-Date) - (Get-Item $log).LastWriteTime).TotalSeconds -gt 30) {
    Write-Warning "brak nowego logu przez 30 s: możliwy hang"
  }

  if (($n % 5) -eq 0) {
    $ev = Get-WinEvent -FilterHashtable @{
      LogName='System'; ProviderName='nvlddmkm'; StartTime=$start
    } -MaxEvents 1 -ErrorAction SilentlyContinue
    if ($ev) { Write-Warning "nvlddmkm event $($ev.Id): przerwij"; break }
  }

  Start-Sleep -Seconds 2
}
```

### Build diagnostyczny (DRED + debug layer)

To osobny profil, nie zmiana źródła ani głównego runtime'u. Release build nie
ma feature `diagnostics`, dlatego `VICTORY_D3D12_DRED=1` w release nic nie da.

```powershell
Set-Location 'D:\git\fxceless-victory'
cargo build --profile diag -p victory --features diagnostics
```

Istnieje już build diag (`build-diag.log`); jeśli nie był zmieniany, nie musisz
budować od nowa. **Krok 0 (jednorazowo, administrator PowerShell):** run dred
22:14 logował `0x887A002D` = brak warstwy debug (`d3d12sdklayers.dll`).
Zainstaluj Graphics Tools i zrestartuj; bez tego page-fault info i GBV nie
działają:

```powershell
Get-WindowsCapability -Online -Name 'Tools.Graphics.DirectX*' | Select Name, State
Add-WindowsCapability -Online -Name 'Tools.Graphics.DirectX~~~~0.0.1.0'
# po restarcie: w logu runu nie może być "no D3D12 debug layer"
```

### D1 — DRED repro na konfiguracji crashu 3 (celowy crash)

Replikuj dokładnie run opt+memory, który padł o 21:56:58Z: `RELAY=1` +
`LATE_WAIT=1` + `ASYNC_SUBMIT=1` + `QUEUE2=1` plus te same limity pamięci.
GBV zostaw wyłączone — przy 0,3 fps nie dojedzie do 3D; DRED + debug layer
wystarczą, żeby nazwać komendę. `CARD_METER=1` da timestamps listów na karcie
i pokaże, który list zawisł, nawet gdyby breadcrumbs były puste.

```powershell
$env:VICTORY_RELAY='1'
$env:VICTORY_LATE_WAIT='1'
$env:VICTORY_ASYNC_SUBMIT='1'
$env:VICTORY_QUEUE2='1'
# + TE SAME limity pamięci co w runie opt+memory (nie profil S1b):
#   wklej blok TEXTURE/CARD/STAGING/INPLACE z tamtego runu.
$env:VICTORY_D3D12_DEBUG='1'
$env:VICTORY_D3D12_DRED='1'
$env:VICTORY_D3D12_GBV='0'
$env:VICTORY_CARD_METER='1'
$env:VICTORY_DRIVER_WATCH='1'
$env:VICTORY_FRAME_LOG='1'

# Uruchom target\diag\victory.exe z dotychczasowymi argumentami.
# Granica: 15 min albo pierwszy 0x887A0007. Cel to crash z nazwaną komendą.
```

Jeśli D1 nie crashuje w 15 min — konfiguracja nie jest deterministyczna;
bisectuj pojedynczo (reszta off, po 15 min na wariant):

```powershell
# D1a: $env:VICTORY_RELAY='1'       # D1b: $env:VICTORY_QUEUE2='1'
# D1c: $env:VICTORY_LATE_WAIT='1'   # (ASYNC_SUBMIT jako D1d, jeśli wyżej czysto)
```

W logu szukaj:

```powershell
$pattern = 'page fault|breadcrumbs|a list stopped at command|debug layer|' +
           'GPU-based validation|textures picked by index|device removed'

Select-String 'D:\Gry\fxceless-data\logs\game-stderr.log' -Pattern $pattern |
  Select-Object -Last 60 |
  ForEach-Object { "$($_.LineNumber): $($_.Line)" }
```

`VICTORY_D3D12_WARP=1` (tylko diag) to ostateczność: software adapter zamienia
GPU fault na CPU access violation, ale jest bardzo wolny i nie odtwarza
wszystkiego. Użyj do minimalnego repro, nie do normalnej gry.

### Izolacje szczegółowe

```powershell
# H1: wyłącz dokładnie tę pętlę, która była w crashu (obraz będzie niekompletny)
$env:VICTORY_HEAP_TEXTURES='0'

# H4: biblioteka bez mapowania i bez równoległych calls
$env:VICTORY_LIBRARY_MAP='0'
$env:VICTORY_LIBRARY_HANDLE='0'
$env:VICTORY_LIBRARY_LOCK='1'
$env:VICTORY_PIPELINE_WAIT_MS='1000'

# H3: twardy headroom
$env:VICTORY_TEXTURE_BUDGET_MB='2560'
$env:VICTORY_CARD_BUFFERS_MB='256'
$env:VICTORY_CARD_ROOM_FOR_TARGETS_MB='2560'
$env:VICTORY_INPLACE_MB='1024'
$env:VICTORY_STAGING_POOL_MB='128'
$env:VICTORY_REUPLOAD_WHEN_FULL='0'
```

### Zasilanie / ASPM (test odwracalny)

```powershell
powercfg /list
# High Performance (jeśli jest na liście):
powercfg /setactive 8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c

# ASPM Off na AC i DC:
powercfg /setacvalueindex SCHEME_CURRENT SUB_PCIEXPRESS ee12f906-d277-404b-b6da-e5fa1a576df5 0
powercfg /setdcvalueindex SCHEME_CURRENT SUB_PCIEXPRESS ee12f906-d277-404b-b6da-e5fa1a576df5 0
powercfg /setactive SCHEME_CURRENT

# Powrót do maximum power savings:
# powercfg /setacvalueindex SCHEME_CURRENT SUB_PCIEXPRESS ee12f906-d277-404b-b6da-e5fa1a576df5 2
# powercfg /setdcvalueindex SCHEME_CURRENT SUB_PCIEXPRESS ee12f906-d277-404b-b6da-e5fa1a576df5 2
# powercfg /setactive SCHEME_CURRENT
```

### TDR delay — tylko diagnostyka, nie fix

Jeśli chcesz odróżnić „reset natychmiast” od „timeout 2 s”, podnieś delay
**na jeden test** i wróć do defaultu. To nie jest rozwiązanie.

```powershell
# W PowerShell jako administrator; wymaga restartu.
reg add "HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers" /v TdrDelay /t REG_DWORD /d 10 /f
# Po teście:
reg delete "HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers" /v TdrDelay /f
```

Jeśli po `TdrDelay=10` objaw zmienia się z resetu w długi hang, to był timeout;
jeśli reset zostaje natychmiast, to nie TDR — wróć do H1/H2.

## Wczesne ostrzeganie — progi

| Sygnał | Próg | Akcja |
|---|---|---|
| `nvlddmkm` 153 / `Display` 4101/4102 | pierwsze zdarzenie | przerwij natychmiast; w innych runach utrata następowała 2,7–6,3 s później |
| VRAM used | ≥7 300 MiB przez 3 próbki (6 s) | przerwij / obniż texture budget |
| VRAM free | ≤500 MiB | przerwij |
| Brak nowej linii `frame times:` | >30 s przy działającym procesie | możliwy hang; przerwij |
| PCIe link | Gen<3 przy util ≥20% przez 10 s | sprawdź ASPM / plan zasilania |
| Temperatura | ≥80 °C lub `HW Thermal Slowdown: Active` | przerwij; to nie jest obecny przypadek |
| Frame log | `longest` >3× median w dwóch odczytach | obniż ustawienia / zbierz trace |
| Commit | wolne <1 GB | zamknij tło, zmniejsz `INPLACE_MB`/staging |

Na tym systemie **nie ma** `nvlddmkm`/`Display` events, więc pierwszy wiersz
może nie zadziałać. Wtedy podstawą są VRAM, frame log i brak postępu. Nie
wyłączaj `VICTORY_DRIVER_WATCH` — jeśli driver zacznie logować, to najszybszy
sygnał.

## Czego nie robić

- Nie podnoś `TdrDelay` „na stałe” i nie ogłaszaj stabilności po 150 s.
- Nie dodawaj `QUEUE2`, `ASYNC_SUBMIT`, `JOIN_*`, `GATHER`, `BACK_OWN_VIEW`
  podczas debugowania resetu; to zwiększa liczbę zmiennych.
- Nie używaj `BAR1 free` jako wolnego VRAM.
- Nie uruchamiaj D1 z `GBV=1`: przy 0,3 fps nie dojedzie do 3D; DRED + debug
  layer wystarczą, żeby nazwać komendę.
- Nie wyciągaj z safe-mem/dred wniosku „VRAM wykluczony”: wykluczone jest tylko
  to, że sam VRAM wystarcza do resetu; mierz go dalej w każdym runie.
- Nie traktuj braku crashey w safe-mem/dred jako dowodu stabilności profilu:
  oba runy trwały ≤5 min, a crash 3 wystąpił po ~2 min 44 s.
- Nie obwiniaj termiki: 42–52 °C, brak HW thermal throttle.
- Nie rób clean install sterownika przed DRED; najpierw dowiedz się, czy to
  page fault, błędny view, czy timeout.
- Nie usuwaj `host-pipelines.bin` bez backupu; odbudowa jest długa, a plik
  może być potrzebny do A/B.
- Nie traktuj `0x80070057` z biblioteki jako device loss; to `E_INVALIDARG`
  ładowania PSO.
- Nie traktuj `0x887A0004` jako błędu urządzenia; to `DXGI_ERROR_UNSUPPORTED`
  z zapytania DRED w release buildzie.

## Następne kroki

1. **D1 (DRED repro, celowy crash)** na konfiguracji crashu 3 — po instalacji
   Graphics Tools (`0x887A002D`). Cel: breadcrumb/nazwana komenda przy
   utracie; granica 15 min. To rozstrzyga H2/H5 jednym runem.
2. **S1b, 30 min** — nowy baseline bezpieczny (`JOIN_COPIES=1`,
   `CARD_REHASH_RUNS=1`, relay/late/async/queue2 off), snapshot + dmon +
   frame log. Bramka: brak resetu, usual-frame copies <50 ms, copy-back
   <100 ms, VRAM p95 <7,2 GB.
3. Jeśli D1 nazwał komendę/view → fix w kodzie i powtórz D1. Jeśli nie
   crashuje → **bisect D1a/D1b/D1c** (`RELAY` / `QUEUE2` / `LATE_WAIT`
   pojedynczo, 15 min na wariant).
4. Jeśli S1b crashuje: wróć do `JOIN_COPIES='0'` (S1); jeśli nadal crashuje:
   **S1-H** (`HEAP_TEXTURES=0`) 15 min → H1.
5. Jeśli S1-H crashuje: **S2** (twardy headroom) 30 min → H3; zmierz, przy
   jakim VRAM znika.
6. Jeśli S2 crashuje: **S3** (library isolation) 30 min → H4.
7. Jeśli S3 crashuje: **S4** (ASPM Off/High Performance, ewentualnie MUX
   dGPU-only) 30 min → H6.
8. Jeśli nadal crashuje: **S6** A/B sterownika (clean 617.14 vs OEM/previous),
   po 30 min na wersję.
9. Dopiero po D1 zmieniaj kod runtime'u. Do tego czasu nie „naprawiaj”
   przez kolejne flagi wydajnościowe.

## Otwarte pytania

- Czy D1 (DRED na konfiguracji crashu 3) nazwie komendę/list? (H2/H5)
- Czy `RELAY`, `QUEUE2` lub `LATE_WAIT` pojedynczo odtwarzają reset? (D1a–c)
- Czy S1b (join copies + card rehash) trzyma 30 min i sprowadza
  copies <50 ms / copy-back <100 ms w usual frame?
- Czy `VICTORY_HEAP_TEXTURES=0` zmienia cokolwiek przy wyłączonej rodzinie
  relay? (H1)
- Czy `0x887A002D` znika po instalacji Graphics Tools? (warunek wstępny D1)
- Czy reset występuje tylko powyżej ~7,3 GB VRAM? (H3, osłabione: 53 MB free
  bez resetu)
- Czy `0x80070057` z biblioteki znika po odbudowie cache? (H4)
- Czy `nvlddmkm` 153 jest w DxgKrnl-Operational, mimo braku w System? (wymaga admina)
- Czy MUX dGPU-only zmienia cokolwiek? (H6, opcjonalnie)
