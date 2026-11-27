# NOCNA MISJA 2026-11-27/28 — GTA VI na RTX 4060 Laptop 8 GB / 16 GB: 5 fps do rana

> Ten dokument jest jednocześnie **promptem startowym** i **runbookiem**. Wklej go jako pierwszą wiadomość nowej sesji (albo wczytaj jako instrukcję). Jest napisany tak, żeby agent mógł działać bez operatora przez 7–8 godzin i rano oddać mierzalny wynik.

---

## 0. TL;DR — co masz zrobić

1. **Faza 0:** preflight, klon świeżego `fxceless/victory-fork`, build release + release/diagnostics, naprawa harnessu (SendInput, screenshoty, nvidia-smi, lock GPU).
2. **Faza 1:** baseline świeżej bazy z presetem 8 GB, Series X, 1280×720, 5 min w świecie. To jedyny publiczny zestaw, który na RTX 4070 12 GB daje 8–9,5 fps; na 4060 Laptop 8 GB/16 GB realnie 4–6 fps.
3. **Faza 2:** drabinka presetów (max 4 warianty), tylko jeśli baseline < 5 fps.
4. **Faza 3 (równolegle, CPU):** Fix 2 wave64→32 w osobnym worktree, za flagą `VICTORY_WAVE64_EMUL=1`, z LDS exchange i arrival counters.
5. **Faza 4:** A/B Fix 2 na najlepszej bazie (5 min + 5 min).
6. **Faza 5:** jeden diagnostyczny world run z `VICTORY_DROP_MAP=1` (U2: który compute karmi widoczną geometrię).
7. **Faza 6:** raport, commit docs, handoff na rano.

**Nie rób:** P0 write-retry, Port 5, BVH builder, patchowania anti-tamper, dwóch runów GPU naraz, commitów do main, wrzucania danych gry do repo.

---

## 1. Cel i Definition of Done

### Cel główny
**≥ 5,0 fps p50** w świecie, 1280×720, Series X, ten sam punkt/cutscena, pomiar 5 min, na RTX 4060 Laptop 8 GB VRAM / 16 GB RAM.

### Cele alternatywne (też zaliczone)
- Udowodnić liczbami, że sufit na tym sprzęcie jest < 5 fps, wskazać wąskie gardło i oddać najlepszy osiągnięty config + dokładne komendy.
- Domknąć Fix 2: 7/7 compute pipelines tworzy się z `WaveSize=32`, 0 `compute_refused`, brak TDR/AV, brak regresji wizualnej.
- Odpowiedzieć na U2: które z 7 compute są potrzebne do widocznej geometrii (DROP_MAP).

### Definition of Done na rano (07:00)
- [ ] `docs/OVERNIGHT-2026-11-27.md` w `D:\git\gta6-30fps` z tabelą wszystkich runów i werdyktem.
- [ ] `D:\Gry\VItoriaBr-data\night-results.jsonl` — jedna linia JSON per run, bez nadpisywania.
- [ ] Screenshoty w `D:\Gry\VItoriaBr-data\shots\` (start/śród/koniec każdego runu).
- [ ] Fix 2 w worktree `D:\git\victory-fork-wave64`, commit + testy, flaga domyślnie **off**.
- [ ] `NIGHT-LOG.md` — append-only log decyzji i bramek.
- [ ] Zero danych gry w repo, zero commitów w main, zero nieautoryzowanych akcji.

---

## 2. Autoryzacja operatora (pre-autoryzacja na noc)

Operator zatwierdził **dokładnie** poniższe i nic więcej:

- [x] Zatrzymanie każdego działającego `victory.exe` / `game_scarlett_master.exe` (w tym PID 30212, jeśli wróci).
- [x] Maksymalnie **12 runów GPU**, każdy ≤ 30 min wall (load + pomiar), **jeden proces GPU na raz**.
- [x] Klonowanie i budowanie `fxceless/victory-fork` oraz `uiliannn/VItoriaBr` do `D:\git\`.
- [x] Zapisywanie cache/logów w `D:\Gry\VItoriaBr-data` (poza repo).
- [x] Włączanie presetów i flag performance, w tym `VICTORY_WAVE64_EMUL=1`.
- [x] **Jeden** run diagnostyczny z `VICTORY_DROP_MAP=1` w Fazie 5, maks. 5 min, po Fix 2.
- [x] Budowanie release+diagnostics i używanie `VICTORY_KEYS` tylko do automatyzacji startu.

**NIE autoryzowano:**
- `VICTORY_BVH_BUILDER=1` (dopiero po U2 i osobnej zgodzie),
- jakichkolwiek patchy DRM/anti-tamper (w tym INT3 `0xCC` pod plikowym offsetem `0x5148eec`),
- edycji `D:\git\VItoriaBr-opt` (źródło binarne 06:44),
- merge do main, force-push, kasowania worktree,
- pobierania prebuilt binarek, kodu CGBJ/ad3lre, prywatnych forkóœ,
- publikowania czegokolwiek na zewnątrz (forum/Discord/PR) bez zgody,
- instalowania nowych sterowników/Windows Update w nocy.

Jeśli operator wróci w trakcie: **zatrzymaj eksperyment, pokaż stan, zapytaj**.

---

## 3. Zasady twarde (nienegocjowalne)

1. **Jeden GPU na raz.** Przed każdym runem: `tasklist` + `nvidia-smi`; jeśli cokolwiek używa GPU — czekaj lub pomiń. Lock: `D:\Gry\VItoriaBr-data\.gpu-lock` (PID + timestamp); martwy PID czyść.
2. **Zero danych gry w repo.** Cache, logi, screenshoty, dumpy — tylko `D:\Gry\VItoriaBr-data`. Nie kopiuj `.exe`, assetów, paczek.
3. **Licencje:** projekt GPL-3.0; XCL jest GPL-2.0-only — **tylko opis algorytmu**, zero kopiowania kodu. W komentarzach cytuj `docs/wave64-on-wave32.md`, nie pliki źródłowe XCL.
4. **Zero DRM/anti-tamper.** Nie patchuj warstwy, nie obchodź zabezpieczeń, nie modyfikuj tytułu.
5. **Nie ruszaj:** `D:\git\VItoriaBr-opt` (brudne drzewo, źródło main 06:44), gałęzi main w żadnym repo, worktree `VItoriaBr-port5-p0` (chyba że tylko czytasz).
6. **Każdy eksperyment = hipoteza → komenda → liczby → werdykt.** Zakaz „wydaje się szybciej”.
7. **Timebox.** Dwa kolejne niepowodzenia o tym samym signature → zamknij wątek, opisz, idź dalej.
8. **Pamięć:** przed startem ≥ 6 GB wolnego RAM; w trakcie VRAM ≤ 7,4 GB, RAM nie schodź poniżej 1,5 GB. Jeśli naruszone — zabij run, obniż preset. Przy 4 GB wolnego RAM i braku procesu → restart (standby cache).
9. **Termika:** laptop na zasilaniu, plan wysokiej wydajności; temp ≤ 85 °C; jeśli throttle — zanotuj i obniż preset.
10. **Podczas pomiaru nic nie obciąża CPU:** żadnego `cargo build`, testów, przeglądarki, indeksowania. Buildy i testy tylko między runami.
11. **Raport po polsku**, kod/komentarze po angielsku zgodnie ze stylem repo.
12. **Nie zgaduj nazw env.** Każdą flagę sprawdź `rg "VICTORY_..."` w źródłach; nieznane flagi loguj jako `UNKNOWN_ENV`.

---

## 4. Środowisko (stan na start nocy)

| Element | Wartość |
|---|---|
| GPU | NVIDIA RTX 4060 Laptop, 8188 MiB, driver 617.14 |
| RAM | 15,3 GB (na starcie ~4,1 GB free — patrz Faza 0) |
| Dysk | D: 103,5 GB free |
| Gra | `D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\game_scarlett_master.exe` |
| Main 06:44 | `D:\git\VItoriaBr-opt\target\release\victory.exe`, 9 970 176 B, SHA-256 `bf12251edb95f1c47a22c06a210c76bcb1d169c8f2ffeb3f7d3744f2a9638df0` |
| Baza publiczna | `https://github.com/fxceless/victory-fork` (GPL-3.0-or-later) — **nieklonowana lokalnie** |
| Alternatywa | `https://github.com/uiliannn/VItoriaBr` (main 4–6 fps na RTX 5060 Ti 16 GB) |
| Referencja | `https://github.com/xcl-dev/xcl` (GPL-2.0-only; `docs/wave64-on-wave32.md`) |
| Harness | `D:\Gry\VItoriaBr-data\night_harness.py` (wymaga poprawek — Faza 0) |
| Logi | `D:\Gry\VItoriaBr-data\logs\` |
| Wyniki | `D:\Gry\VItoriaBr-data\night-results.jsonl` |
| Pada | DS4 v2 przez DS4Windows, Bluetooth, <10 ms |
| Narzędzia | Rust/cargo, Python 3 (`D:\git\gta6-native-proto\.venv`), dxc (`C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\dxc.exe`), Firecrawl MCP keyless, REA MCP |

### Worktree — mapa
```
D:\git\VItoriaBr-opt        # main 06:44, NIE MODYFIKOWAĆ
D:\git\VItoriaBr-p0         # P0 write-retry cc1de49 — PARKED
D:\git\VItoriaBr-port5      # Port 5 db189b5 — PARKED
D:\git\VItoriaBr-port5-p0   # 186c7a8, P0+Port5 — PARKED
D:\git\gta6-30fps           # tylko docs/reporty
D:\git\gta6-native-proto    # replay/emitter, CPU only
D:\git\victory-fork         # DO SKLONOWANIA — baza nocy
D:\git\victory-fork-wave64  # DO UTWORZENIA — Fix 2
```

---

## 5. Stan wiedzy — nie odkrywaj od nowa

### Potwierdzone
- **Wave64 to przyczyna `0x80070057`** dla 7 compute PSO. Instrumentowany build pokazał `emitted_wave=Some(64)` dla wszystkich 7 hashy; retry w `emit/mod.rs:367–395` nie konwertuje emitted DXIL.
- Hashe: `02384a60fda6f2d0`, `369cbe906ea72764`, `2cc4c197ee29e291`, `2da4beb386509b77`, `6b82bc7d22016cb5`, `5dc3b25986622949`, `6f225b641c5b0708`.
- `6b82bc7d22016cb5`: group=1024, lds_dwords=8192 → **16 fal konsoli na grupę** (najgorszy przypadek, wymaga arrival counters). `2da4beb386509b77`: group=256 (4 fale).
- XCL: 26 698/26 698 shaderów transluje; wave64→32 przez dwie połowy wave32 + LDS exchange/arrival counters; koszt 1 exchange/8 instr = 1,3–2,2×, cztery fale/group = 4,6–5×.
- Main SafeMem 06:44 **renderuje** cutscenę Lucii poprawnie, ale 0,2–0,3 fps: 5000–6599 drawów, preparing 489–1574 ms, copies 298–1253 ms (262–363 MB), copy-back 2132–2303 ms (72–80 MB), **3490–5523 drawów dropped bez host pipeline (0 being made)**.
- P0 release+diagnostics: czarny ekran / hang na 3 drawach — **P0 nie jest shippable**.
- Port 5: aktywny (`twinned>0`), ale A/B INCONCLUSIVE (Arm B crash w `victory.exe+0x532b6e`, write `0x54319fc00`).
- `VICTORY_KEYS` działa tylko z `#[cfg(feature = "diagnostics")]`; release bez diagnostics ignoruje klawisze — to była główna przyczyna „menu na zawsze”.
- DS4 działa; pada używać, gdy operator jest obecny. Nocą: SendInput na plain release jako primary, diag build jako fallback.

### Parked (nie ruszać bez nowych danych)
- P0 write-retry (`cc1de49`) — A/B INCONCLUSIVE.
- Port 5 (`db189b5`) + root-CBV (`186c7a8`) — A/B INCONCLUSIVE.
- `VICTORY_BVH_BUILDER=1` — zakaz do U2.
- `VICTORY_DROP_MAP=1` — tylko Faza 5.

### Otwarte pytania
- **U2:** który compute karmi widoczną geometrię? (DROP_MAP)
- Czy 3490+ dropped drawów to brakujące pipeline'y graficzne, compute, czy limit pętli shaderów?
- Czy Fix 2 poprawia fps, czy tylko kompletność obrazu (może kosztować fps)?
- Czy 6b82 (1024 group) jest w ogóle potrzebny do widocznej geometrii?

---

## 6. Plan nocy — fazy, bramki, timeboxy

### Faza 0 — preflight i build (30–45 min)

- [ ] Sprawdź procesy: `Get-Process victory,game_scarlett_master -EA SilentlyContinue`. Jeśli są — zatrzymaj (`taskkill /T /F`), odczekaj 10 s.
- [ ] RAM: jeśli < 6 GB free i żaden proces nie trzyma — restart. Po restarcie NIE otwieraj przeglądarki/IDE.
- [ ] Dysk D: ≥ 40 GB.
- [ ] Zasilanie + plan wysokiej wydajności: `powercfg /getactivescheme`; ustaw High Performance.
- [ ] Pagefile systemowy ≥ 16 GB: `Get-CimInstance Win32_PageFileUsage`.
- [ ] Sklonuj bazę:
```powershell
git clone https://github.com/fxceless/victory-fork D:\git\victory-fork
cd D:\git\victory-fork
git log --oneline -8
```
- [ ] Przeczytaj README i `docs/` forkа; wypisz wszystkie `VICTORY_*` i ich znaczenie:
```powershell
rg -o "VICTORY_[A-Z0-9_]+" -N crates | Sort-Object -Unique
```
- [ ] Zbuduj **plain release** (to będzie binarka pomiarowa):
```powershell
cargo build --release -j 4
New-Item -ItemType Directory -Force D:\Gry\VItoriaBr-data\bin | Out-Null
Copy-Item target\release\victory.exe D:\Gry\VItoriaBr-data\bin\victory-fork-plain.exe -Force
```
- [ ] Zbuduj **release+diagnostics** (fallback startu):
```powershell
cargo build --release --features diagnostics -j 4
Copy-Item target\release\victory.exe D:\Gry\VItoriaBr-data\bin\victory-fork-diag.exe -Force
```
- [ ] Odtwórz plain w `target\release` (żeby ewentualne skrypty repo nie użyły diag):
```powershell
Copy-Item D:\Gry\VItoriaBr-data\bin\victory-fork-plain.exe target\release\victory.exe -Force
```
- [ ] **Napraw harness** `night_harness.py`:
  - `SendInput`/`keybd_event` (nie `PostMessage`) dla Enter/Space/Escape; schedule 60, 75, 90, 105, 120, 150, 180, 210, 240 s.
  - Weryfikacja foreground: `GetForegroundWindow()==hwnd`; jeśli nie — AttachThreadInput + SetForegroundWindow + BringWindowToTop.
  - Screenshoty: world+0 s, +150 s, +300 s → `D:\Gry\VItoriaBr-data\shots\<run>-<t>.png` (PowerShell + System.Drawing jako fallback, jeśli brak Pillow).
  - Logger `nvidia-smi --query-gpu=utilization.gpu,memory.used,temperature.gpu,power.draw --format=csv,noheader,nounits -l 5` → CSV per run.
  - Lock `.gpu-lock` z PID gry; czyszczenie po runie.
  - Detekcja świata: `draws > 300` w 3 kolejnych próbkach (co 10 s), max 15 min.
  - Zapis pełnego JSON per run (schemat w §7).
  - Twarde zabicie drzewa procesów po pomiarze; WER signature do raportu.
- [ ] Smoke test harnessu **bez pomiaru** (3 min): czy okno wstaje, czy SendInput przechodzi, czy screenshot się zapisuje.

**Bramka G0:** binarki istnieją, harness robi screenshot i wysyła klawisz, lock działa. Jeśli nie — napraw harness, nie zaczynaj pomiarów.

---

### Faza 1 — baseline świeżej bazy (60–90 min)

Uruchom **preset A** (§8), Series X, 1280×720, 5 min pomiaru.

```powershell
$env:VICTORY_DISPLAY_MODE='1280x720'
# + cały preset A z §8
D:\Gry\VItoriaBr-data\bin\victory-fork-plain.exe run "D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\game_scarlett_master.exe" --execute --console series-x
```

Albo przez harness:
```powershell
& D:\git\gta6-native-proto\.venv\Scripts\python.exe D:\Gry\VItoriaBr-data\night_harness.py --only fork-a-720 --measure 300
```

**Bramka G1:**
- ≥ 5,0 fps → **cel osiągnięty**; przejdź do stabilizacji (2 powtórki), Fix 2 tylko jeśli chcesz kompletności, raport.
- 4,0–4,99 fps → Faza 2 (max 4 warianty), potem Fix 2.
- 3,0–3,99 fps → Faza 2 + Fix 2 + rozważ 960×540.
- < 3,0 fps → najpierw diagnoza: co dominuje (preparing/copies/copy-back/GPU/dropped); nie licz na preset.

**Jeśli brak świata w 15 min:**
1. Zobacz screenshot — menu, czarny ekran, cutscena?
2. Spróbuj diag build + `VICTORY_KEYS="60:Enter,90:Enter,120:Enter,150:Enter"`.
3. Spróbuj `--console series-s` i 960×540.
4. Max 2 próby startu; potem fallback na `VItoriaBr` main (Faza 1b).

**Faza 1b (fallback):** klon `uiliannn/VItoriaBr`, build release, preset B, ten sam protokół. Nie mieszaj binarek.

---

### Faza 2 — drabinka presetów (max 4 warianty, 90–120 min)

Zasada: **jeden zmieniony czynnik na wariant**, względem najlepszego dotychczas.

| Wariant | Zmiana | Hipoteza |
|---|---|---|
| B | `TABLE_BUFFERS=1`, `TEXTURE_BACK=1`, `CARD_BUFFERS_MB=1024`, `TEXTURE_BUDGET_MB=4096` | mniej copy-back, mniejszy VRAM |
| C | 960×540, `TEXTURE_BUDGET_MB=3072`, `CARD_BUFFERS_MB=512` | rozdzielczość + budżety |
| D | `AMBIENT=0`, `INPLACE_MB=1024`, `WIDE_MERGE=0` | mniej pracy na klatkę |
| E | `SHADER_LOOP_LIMIT=512` lub 1024 | jeśli log pokazuje cięcia pętli |

Każdy wariant: 1 run, 5 min, ten sam spot. Jeśli crash/OOM — obniż budżet i oznacz FAIL, nie powtarzaj identycznie.
**Bramka G2:** najlepszy wariant ≥ 5 fps → stop, raport. Inaczej przejdź do Fazy 4 z najlepszym wariantem.

---

### Faza 3 — Fix 2 wave64 (równolegle, CPU, 2–3 h)

Worktree:
```powershell
cd D:\git\victory-fork
git worktree add ..\victory-fork-wave64 -b fix/wave64-emulation
cd ..\victory-fork-wave64
```

**Wymagania implementacyjne:**
- Flaga `VICTORY_WAVE64_EMUL` (default **0**), opcjonalnie `VICTORY_WAVE64_EMUL_HASHES=hash1,hash2,...` (default: wszystkie 7).
- Rozszerz retry wave64→32 w `emit/mod.rs` (okolice 367–395; sprawdź aktualne linie).
- Emisja `[WaveSize(32)]`; konwersja cross-lane:
  - `ballot` → 32-bit per half + LDS exchange maski (obie połówki dostają 64-bit),
  - `readlane`/`readfirstlane` → 1 słowo,
  - `ds_bpermute`/dowolny lane → 32 słowa,
  - DPP16/DPP8/swizzle/permlane16 → bez exchange (lokalne),
  - `s_load*`/`s_buffer_load*` z GLC → do 16 słów.
- Synchronizacja:
  - jedna fala konsoli na grupę (group ≤ 64): `GroupMemoryBarrierWithGroupSync` między zapisem a odczytem,
  - wiele fal na grupę (256/1024): **arrival counters**, double-buffer slotów po parzystości `k`, spin limit 2^20, po wyczerpaniu `dead` → wartości pół-lokalne (bez zawieszenia GPU).
- `with_local_waves(local_ok=true)` dla operacji wewnątrz połówki.
- Nie kopiuj kodu XCL; implementacja z opisu, cytat w komentarzu.

**Testy (CPU, bez GPU):**
- mask exchange, arrival counter (2 i 4 fale), double-buffer parity, dead-pair fallback,
- emitter na 7 hashe: emitted DXIL zawiera `WaveSize=32` (dxc `-dumpbin` lub parser metadanych),
- brak paniki przy group=1024/lds=8192.

**Bramka G3:** `cargo test` zielone, 7/7 emituje WaveSize=32, 0 refused w offline emitterze. Jeśli nie — nie idź do Fazy 4.

**Koordynacja:** sesja shader działa **tylko CPU**; nie uruchamia gry; nie buduje podczas pomiarów. Zapisuje stan w `docs/NIGHT-LOG.md` (sekcja „shader”).

---

### Faza 4 — A/B Fix 2 (60–75 min)

Na najlepszym wariancie z Fazy 1/2:

| Armia | `WAVE64_EMUL` | Uwagi |
|---|---|---|
| A | 0 | re-baseline, matched draws/scene |
| B | 1 (all 7) | pełna emulacja |
| B2 (opcjonalnie) | 1 bez `6b82bc7d22016cb5` | jeśli B traci > 20% fps |
| B3 (opcjonalnie) | 1 bez `6b82` i `2da4beb386509b77` | jeśli B2 dalej za wolno |

Kryteria:
- **Sukces:** 7/7 (lub świadomy subset) pipeline created, 0 refused, brak TDR/AV, fps w granicach ±10% A, obraz bez regresji.
- **Kill:** TDR, AV, fps −> 20%, obraz gorszy → flaga off, raport, bez trzeciej próby bez zmiany.
- **Uwaga:** naprawa compute może **zwiększyć** liczbę drawów (mniej dropped) i **obniżyć** fps — to nie porażka, to kompletność. Oddziel „fps” od „poprawności”.

**Bramka G4:** wiesz, czy Fix 2 daje fps, kompletność, czy jedno i drugie.

---

### Faza 5 — DROP_MAP / U2 (30–45 min, jeden run)

Tylko po Fazie 4 i tylko jeśli GPU wolne. Jeden run, 5 min:

```powershell
$env:VICTORY_DROP_MAP='1'
# + najlepszy preset + WAVE64_EMUL wg G4
```

Zbierz: draws/frame, fps, screenshot, listę shaderów compute, które nadal są refused/nieobecne. Porównaj z runem bez DROP_MAP (te same 5 min).
**Bramka G5:** wiesz, które compute są geometry-critical; jeśli `6b82` nie jest — zostaw je refused i zyskaj fps.

Po runie **natychmiast** usuń `VICTORY_DROP_MAP`.

---

### Faza 6 — raport i commit (45–60 min)

- [ ] `docs/OVERNIGHT-2026-11-27.md` wg szablonu (§10).
- [ ] Commit docs w `gta6-30fps` (`docs: overnight 2026-11-27 ...`).
- [ ] Commit Fix 2 w `victory-fork-wave64` (jeśli G3/G4 zaliczone): `perf: wave64-on-wave32 emulation behind VICTORY_WAVE64_EMUL`.
- [ ] `NIGHT-LOG.md` — decyzje, bramki, odrzucone warianty.
- [ ] Handoff: 3 następne kroki z dokładnymi komendami.
- [ ] Uruchom skill `verification-loop` przed commitem; `agent-self-evaluation` do oceny raportu.

---

## 7. Protokół pomiarowy (obowiązkowy)

### Run
1. Preflight: brak procesów GPU, ≥ 6 GB RAM, temp < 80 °C, lock założony.
2. Start: plain release (albo diag, jeśli start wymaga klawiszy).
3. Ładowanie: do `draws > 300` w 3 kolejnych próbkach co 10 s; max 15 min.
4. Warmup: 60 s.
5. Pomiar: 300 s; próbki co 10 s z logu (`fps, ms/frame`, `draws/frame`, preparing/copies/copy-back/GPU, dropped).
6. Screenshoty: +0, +150, +300 s.
7. Kill drzewa procesów; zapis JSON; zwolnij lock; 10 s przerwy.

### Pola JSON (jedna linia na run)
```json
{
  "run": 1,
  "phase": "baseline",
  "arm": "fork-a-720",
  "exe": "victory-fork-plain.exe",
  "exe_sha256": "...",
  "preset": {"RELAY": 2, "TEXTURE_BUDGET_MB": 5120},
  "console": "series-x",
  "res": "1280x720",
  "status": "measured",
  "world_secs": 214.0,
  "samples": 30,
  "fps_p50": 0.0,
  "fps_p95": 0.0,
  "fps_low1": 0.0,
  "ms_p50": 0.0,
  "draws_p50": 0,
  "preparing_ms": 0.0,
  "copies_ms": 0.0,
  "copy_mb": 0.0,
  "copyback_ms": 0.0,
  "copyback_mb": 0.0,
  "gpu_ms": 0.0,
  "dropped_p50": 0,
  "vram_max_mb": 0,
  "ram_min_gb": 0.0,
  "temp_max_c": 0,
  "scene": "cutscene|gameplay|menu|black",
  "crash_markers": [],
  "screenshots": ["..."],
  "log": "...",
  "verdict": "pass|fail|invalid"
}
```

### Ważność
- Ten sam spot: draws p50 w granicach ±25% i podobny screenshot; inaczej `invalid` + **jeden** rerun.
- Nie porównuj menu z cutsceną; nie porównuj różnych rozdzielczości.
- Raportuj medianę, p95 i 1% low; nie średnią.

---

## 8. Presety

### Preset A — świeży fork, 8 GB (start)
```powershell
$env:VICTORY_RELAY='2'
$env:VICTORY_QUEUE2='1'
$env:VICTORY_ASYNC_SUBMIT='1'
$env:VICTORY_COPY_PLAIN='1'
$env:VICTORY_HEAP_WORKER='1'
$env:VICTORY_PARALLEL_REFRESH='1'
$env:VICTORY_SETTLE_ROOM='1'
$env:VICTORY_LOOKUP_CACHE='1'
$env:VICTORY_BACK_OWN_VIEW='1'
$env:VICTORY_INDIRECT_GATHER='1'
$env:VICTORY_JOIN_COPIES='1'
$env:VICTORY_WIDE_REFRESH='1'
$env:VICTORY_WIDE_MERGE='1'
$env:VICTORY_CARD_BUFFERS_MIN_KB='64'
$env:VICTORY_CARD_BUFFERS_MB='1024'
$env:VICTORY_TEXTURE_BUDGET_MB='5120'
$env:VICTORY_PAGE_WRITES='slots'
$env:VICTORY_TEXTURE_NO_WAIT='1'
$env:VICTORY_AMBIENT='0.6'
$env:VICTORY_FRAME_LOG='1'
$env:VICTORY_CARD_ACCOUNTING='1'
$env:VICTORY_LOG='info'
$env:VICTORY_DRIVER_WATCH='1'
$env:VICTORY_UNCAP='1'
$env:VICTORY_BORDERLESS='1'
$env:VICTORY_DISPLAY_MODE='1280x720'
```

### Preset B — mniej copy-back
```
TABLE_BUFFERS=1
TEXTURE_BACK=1
CARD_BUFFERS_MB=1024
TEXTURE_BUDGET_MB=4096
```

### Preset C — 540p
```
DISPLAY_MODE=960x540
TEXTURE_BUDGET_MB=3072
CARD_BUFFERS_MB=512
```

### Preset D — minimalny
```
AMBIENT=0
INPLACE_MB=1024
WIDE_MERGE=0
```

### Preset E — pętla shaderów
```
SHADER_LOOP_LIMIT=512   # lub 1024, tylko jeśli log pokazuje cięcia
```

**Zasada:** każdą flagę najpierw potwierdź w źródłach; jeśli fork jej nie zna — usuń i zanotuj.

---

## 9. Fix 2 — szczegóły, które musisz znać

### Dlaczego
7 compute PSO dostaje `0x80070057`, bo emitted DXIL ma `WaveSize=64`, a RTX 4060 ma fale 32. Retry w emitterze tłumaczy shader, ale nie zmienia fali. To potwierdzone, nie hipoteza.

### Algorytm (z opisu XCL, bez kodu)
- Jedna fala konsoli = dwie połowy wave32 tej samej grupy.
- Obie połowy trzymają pełną 64-bitową maskę (EXEC/VCC/ballot) i identyczne SGPRy; gałęzie brane tak samo.
- Exchange przez LDS tylko tam, gdzie wartość musi być całej fali:
  - ballot: 1 słowo na połówkę → 64-bit,
  - readlane/readfirstlane: 1 słowo,
  - bpermute: 32 słowa,
  - DPP/swizzle/permlane16: 0,
  - s_load z GLC: do 16 słów.
- Jedna fala/group: bariera grupowa.
- Wiele fal/group: arrival counters, double-buffer, spin 2^20, dead-pair fallback.
- Koszt referencyjny: 1 exchange/8 instr = 1,3–2,2×; 4 fale/group = 4,6–5×. Dlatego **flag + per-hash subset**.

### Kryteria akceptacji
- 7/7 (lub uzasadniony subset) `CreateComputePipelineState` OK, 0 `compute_refused`.
- DXIL `WaveSize=32` potwierdzone narzędziem, nie „na oko”.
- Brak TDR/AV w 2 kolejnych runach.
- Obraz: ten sam scene, brak czarnych/rozjechanych passów; screenshoty A/B.
- Wydajność: raportuj delta fps i delta draws; jeśli > 20% straty — subset.

### Czego nie robić
- Nie zmieniaj group size w shaderze (semantyka).
- Nie patchuj tytułu ani warstwy pod INT3.
- Nie kopiuj XCL; nie włączaj BVH.

---

## 10. Szablon raportu `docs/OVERNIGHT-2026-11-27.md`

```markdown
# Noc 2026-11-27/28 — wyniki

## Werdykt
- Najlepszy fps p50: **X,XX** (config: ...)
- Czy 5 fps: **TAK/NIE**
- Wąskie gardło: ...
- Fix 2: **wdrożony / za flagą / odrzucony** — dlaczego

## Tabela runów
| # | faza | arm | exe | fps p50 | p95 | 1% low | draws | preparing | copies | copy-back | GPU | VRAM max | RAM min | status |
|---|------|-----|-----|--------:|----:|-------:|------:|----------:|-------:|----------:|----:|---------:|--------:|--------|

## Przebieg
### Faza 1 — baseline
### Faza 2 — presety
### Faza 3/4 — Fix 2
### Faza 5 — DROP_MAP / U2

## Odrzucone warianty (i dlaczego)
## Co dalej — 3 kroki z komendami
## Załączniki
- JSONL, screenshoty, logi, SHA-256 binarek
```

---

## 11. Stop conditions i eskalacja

**Natychmiast przerwij run, jeśli:**
- free RAM < 1,5 GB lub VRAM > 7,6 GB,
- TDR (`device removed`) — odczekaj 2 min, jedna próba z niższym presetem; drugi TDR = koniec linii GPU,
- ten sam crash signature dwa razy,
- anti-tamper/DRM cokolwiek zgłosi,
- temperatura > 88 °C,
- gra próbuje pobrać/zweryfikować dane (network) — odetnij, zanotuj.

**Zakończ noc bez wyniku, jeśli:**
- 3 runy z rzędu nie wchodzą do świata i start nie jest naprawialny w 30 min,
- brak postępu przez 90 min przy dwóch różnych hipotezach,
- 06:30 — koniec eksperymentów, tylko raport.

**Eskalacja (gdy operator wróci):**
1. Jedno zdanie: co osiągnięto.
2. Jedna tabela: runy i fps.
3. Jedna decyzja do podjęcia (jeśli potrzebna).
4. Linki do raportu/logów/screenshotów.

**Log na żywo:** dopisuj do `docs/NIGHT-LOG.md` co 30 min: czas, faza, bramka, wynik, następny krok.

---

## 12. Szybkie komendy

```powershell
# stan
Get-Process victory,game_scarlett_master -EA SilentlyContinue
nvidia-smi --query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu --format=csv
$os=Get-CimInstance Win32_OperatingSystem; [math]::Round($os.FreePhysicalMemory/1MB,1)

# lock
$lock='D:\Gry\VItoriaBr-data\.gpu-lock'
if (Test-Path $lock) { $p=[int](Get-Content $lock); if (Get-Process -Id $p -EA SilentlyContinue) { throw "GPU busy: $p" } else { Remove-Item $lock } }

# kill
Get-Process victory,game_scarlett_master -EA SilentlyContinue | ForEach-Object { taskkill /T /F /PID $_.Id }

# log tail bez ANSI
Get-Content D:\Gry\VItoriaBr-data\logs\<run>.log -Tail 40 | ForEach-Object { $_ -replace '\x1b\[[0-9;]*m','' }

# frame lines
Select-String -Path D:\Gry\VItoriaBr-data\logs\<run>.log -Pattern 'fps, .*ms/frame' | Select-Object -Last 40

# dxc wave size
& 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64\dxc.exe' -dumpbin <file.dxil> | Select-String 'WaveSize|NumThreads'
```

---

## 13. Załączniki

### 7 compute hashy
| hash | group | lds_dwords | uwaga |
|---|---:|---:|---|
| `02384a60fda6f2d0` | ? | ? | DefragHeap ComputeRelocations (z dumpu) |
| `369cbe906ea72764` | ? | ? | |
| `2cc4c197ee29e291` | ? | ? | |
| `2da4beb386509b77` | 256 | ? | 4 fale/group |
| `6b82bc7d22016cb5` | 1024 | 8192 | 16 fal/group, najdroższy |
| `5dc3b25986622949` | ? | ? | |
| `6f225b641c5b0708` | ? | ? | |

### Znane sygnatury awarii
- `0x80070057` — compute PSO refused (wave64).
- `victory.exe+0x532b6e`, write `0x54319fc00` — Port5 Arm A.
- `victory.exe+0x66cfae`, write `0x54311ac00` — historyczny write-AV.
- `0xc0000005` @ `VCRUNTIME140+0x1afd6`, write `0x255e0000` — P0 Arm B.
- AppHangB1 na splashu/menu — P0 release bez diagnostics / memory pressure.
- `nvwgf2umx.dll` first-chance + OOM — za mało RAM.

### Linki
- https://github.com/fxceless/victory-fork
- https://github.com/uiliannn/VItoriaBr
- https://github.com/xcl-dev/xcl/blob/main/docs/wave64-on-wave32.md
- https://portwatch-vi.xyz/#top
- https://github.com/Marvisak/VIctory

### Dokumenty w `D:\git\gta6-30fps\docs`
`SHADER-FAILURES.md`, `SHADER-WAVE64-FIX.md`, `PORT5-IMPLEMENTATION.md`, `P0-WRITE-RETRY-VALIDATION.md`, `P0-HANG-TRIAGE.md`, `COPY-LOOP-MATRIX.md`, `SCENE-INTEL-2026-11-26.md`, `GLM-AUDIT-SHADER-GAP.md`, `TEXTURE-RESIDENCY-PORT.md`, `PERF-PORT-PLAN.md`.

---

## 14. Pierwsze 10 minut — dosłownie

1. `Get-Process victory,game_scarlett_master` → jeśli są, kill.
2. RAM/VRAM/temp → jeśli < 6 GB free, restart i wróć.
3. `git clone https://github.com/fxceless/victory-fork D:\git\victory-fork`.
4. `cargo build --release -j 4` → skopiuj binarkę do `D:\Gry\VItoriaBr-data\bin\victory-fork-plain.exe`.
5. Uruchom harness w trybie smoke (3 min, bez pomiaru); sprawdź screenshot i SendInput.
6. Jeśli okno wstaje i klawisz przechodzi → Faza 1, preset A, 5 min.
7. Jeśli nie → diag build + `VICTORY_KEYS`, max 2 próby, potem fallback VItoriaBr.
8. Zapisz pierwszą linię JSON i pierwszą sekcję `NIGHT-LOG.md`.

Powodzenia. Cel: **5 fps albo uczciwy, zmierzony sufit**.
