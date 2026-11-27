# PORT5-IMPLEMENTATION — implementacja i aktywacja Port 5 zero-copy CBV (`VICTORY_PORT_CBV=1`)

**Rola:** ten sam agent performance (perf/submission/residency).
**Worktree:** `D:\git\VItoriaBr-port5` (detached HEAD `d93d263`, z `D:\git\VItoriaBr-opt`).
**Branch:** brak commitu w main; zmiany tylko w worktree `port5`.
**NIE dotykam:** `watch.rs` (P0 write-retry belongs to inny wątek), GLM, shader failures (PID 17592), pipeline, binarki gry.
**Gra:** ZAMKNIĘTA; nie uruchomiona.

---

## 1. Weryfikacja commitu źródłowego `c7fff5410a`

Pobrano diff przez `webfetch` z `github.com/DoubleGhosty/cool_fox/commit/c7fff5410a.diff`.

**Potwierdzone:** to jest **zero-copy CBV**, nie descriptor deferral. Mechanizm:
- `VICTORY_PORT_CBV=1` (domyślnie `0` — stare zachowanie).
- Shadery tłumaczone tak, by czytać constant buffery jako **raw bytes** (`victory_shader::emit::constants_raw()`).
- Host tworzy raw SRV deskryptor w tym samym slocie heapu co CBV (zastępując CBV) — shaders czytają przez `rawBufferLoad` zamiast `cbufferLoadLegacy`.
- ~23 000 kopii/frame eliminowanych w mieście (około 9 MB), tyle samo kroków wątku submit.
- Wymaga shader-side: `constants_raw()` + zmiany w `lower.rs` (odczyt raw zamiast CBV).
- Cache shaderów kluczuje na switch (`VICTORY_PORT_CBV=1` w `build()`).

**Pliki w commicie źródłowym:** `port_cbv.rs` (nowy), `lib.rs`, `descriptor/host.rs`, `draw.rs`, `host.rs`, `shader_cache.rs`, `victory-shader/src/emit/{lower,mod,shader}.rs`.

---

## 2. Activation design (ZADANIE 0 — design przed kodem)

### 2.1 Gdzie powstaje raw twin i jaki jest zakres/base

**Podejście uproszczone (lepsze niż oryginał CGBJ):** raw SRV **zastępuje CBV w tym samym slocie** descriptor heapu. Nie ma osobnych slotów-bliźniaków, nie ma dynamicznej alokacji twinów, nie ma `raw_base` ani `set_raw_views`.

- `constant_raw_at(index, buffer, gpu, size)` tworzy `D3D12_SHADER_RESOURCE_VIEW_DESC` z `D3D12_BUFFER_SRV_FLAG_RAW` w slocie `index` (ten sam slot, w którym normalnie byłby CBV).
- Zakres: bajty `[offset, offset + bytes)` z bufora title memory, gdzie `offset = gpu - base`, `base = buffer.GetGPUVirtualAddress()`.
- Wymóg: `offset % 16 == 0` (raw view alignment) — egzekwowane przez `port_cbv::raw_ok()`.
- Slot nie musi być na 256 B (w przeciwieństwie do CBV), więc więcej konstant kwalifikuje się do zero-copy.
- Slot jest stabilny między tabelami i drawami w ramach jednej klatki — heap nie jest resetowany do `tables_done()`, a slot `index` jest nadpisywany tylko gdy view się zmieni.

### 2.2 Jak shader pozna base

**Nie potrzebuje base.** Shader czyta z tego samego slotu heapu co wcześniej (`t<index>` lub `b<index>` w root space), tylko z innymi propsami: `rawBufferLoad` zamiast `cbufferLoadLegacy` / `cbuffer_dword`.

- Opcja (a) root constant `raw_base` per draw — **niepotrzebna**, slot jest znany z kontekstu tabeli.
- Opcja (b) stały zakres heapu + `set_raw_views` — **niepotrzebna**, brak osobnych twinów.
- Opcja (c) deskryptor/root view — **zastosowana**: raw SRV deskryptor tworzony w tym samym slocie co CBV by był.

### 2.3 Czy base wchodzi do shader cache key?

Nie dotyczy — brak base. Cache key już rozdziela na `VICTORY_PORT_CBV=1` (w `shader_cache.rs::build()`), co jest właściwe: tłumaczenie z raw SRV różni się od tłumaczenia z CBV.

### 2.4 Fallback

- `VICTORY_PORT_CBV=0` (domyślne): stara ścieżka CBV, bez zmian.
- `VICTORY_PORT_CBV=1` ale `constant_raw_at` zwraca `false` (offset nie na 16 B, poza zakresem, size 0): fallback do starej ścieżki (scratch + `defer_fill` + `constant_at`).
- `VICTORY_PORT_CBV=1` ale root parameter jest CBV-typny (nie SRV): root CBV czyta przez `root_cbv_handle` (stara ścieżka), tylko table CBV używają raw SRV.

**Nie wymaga zmiany ABI/root signature.** Root CBV path działa tylko gdy root parameter jest SRV-typny; w przeciwnym razie zostaje CBV. To jest bezpieczne — nie ma hakowania ABI.

---

## 3. Co zostało zaimplementowane w worktree `port5`

### 3.1 Nowy plik: `crates/victory-gpu\src\port_cbv.rs`

- `on()` — czyta `VICTORY_PORT_CBV` env (`"1"` = on), `OnceLock`.
- `in_place_on()` — `on() && VICTORY_PORT_CBV_PLACE=="1"` (diagnostyka A/B).
- `in_place(size)` / `copied(aligned)` / `twinned()` — liczniki statystyk.
- `raw_ok(gpu)` — czy offset jest na 16 bajtach (wymagane dla raw SRV).
- `log(frames)` — wypisuje linię per-frame gdy port on.
- Test jednostkowy: `raw_views_need_sixteen_bytes` (0x10 OK, 0x100 OK, 0x8/0x4 nie).

### 3.2 Zmienione pliki

| Plik | Zmiana |
|---|---|
| `crates/victory-gpu/src/lib.rs` | Dodano `#[cfg(windows)] mod port_cbv;` po `mod inplace;` |
| `crates/victory-gpu/src/descriptor/host.rs` | Usunięto pole `twins` i metody `twin()`/`release_twin()` (niepotrzebne). `constant_raw_at()` tworzy raw SRV w slocie `index` (zastępuje CBV), bez alokacji dynamicznego slotu twin. `make_null()` nie wywołuje już `release_twin()`. |
| `crates/victory-gpu/src/draw.rs` | W pętli tabel `View::Constant`: gdy `port_cbv::in_place_on()`, wywołuje `host.constant_raw_at(index, ...)` — tworzy raw SRV w slocie, brak kopii. Fallback do starej ścieżki gdy `constant_raw_at` zwraca `false`. |
| `crates/victory-gpu/src/host.rs` | Dodano `crate::port_cbv::log(frames);` na końcu `late_line`. (Pre-existing fix: `HEAP_BUFFERS_TABLED` → `HEAP_BUFFER_PASSES` w linii 7500 — błąd w HEAD, nie jest częścią Port 5.) |
| `crates/victory-gpu/src/shader_cache.rs` | `build()` dorzuca `b"VICTORY_PORT_CBV=1"` do klucza gdy `constants_raw()`. |
| `crates/victory-shader/src/emit/shader.rs` | Dodano `constants_raw()` (czyta `VICTORY_PORT_CBV`). `raw_views()` / `set_raw_views()` pozostają (eksportowane, niewykorzystane w tym etapie — rezerwa na przyszłość). |
| `crates/victory-shader/src/emit/mod.rs` | Eksportuje `constants_raw, raw_views, set_raw_views`. |
| `crates/victory-shader/src/emit/lower.rs` | Gałąź `constants_raw()` w ścieżce odczytu CBV (`s_buffer_load_dword`): table CBV czytane przez `rawBufferLoad` z raw SRV handle (`props (11, 0)`) zamiast `cbuffer_dword` z CBV handle (`props (13, 0x1_0000)`). Root CBV: `root_srv_handle` zamiast `root_cbv_handle` gdy `constants_raw()`. Stara ścieżka CBV zachowana dla `VICTORY_PORT_CBV=0`. |

### 3.3 Czego NIE zaimplementowano (celowo, do następnego kroku)

- **Port 1** (`VICTORY_PORT_CONSTANTS=1`, `c496640276` / `5e0c9ab01e`) — tylko kontekst, nie implementowany w tym etapie.
- **Descriptor-record deferral** (`f4b48ad`) — nie implementowany w tym etapie.

---

## 4. Wyniki buildu i testów

### Build

```
cargo build --offline --release -p victory
```
**Wynik:** `Finished release profile [optimized + debuginfo] target(s) in ~33s` — **sukces**, zero błędów, zero ostrzeżeń związanych z Port 5.

### Testy

```
cargo test --offline --release -p victory-gpu --lib
cargo test --offline --release -p victory-shader --lib
```

| Crate | Passed | Failed | Ignored | Uwagi |
|---|---|---|---|---|
| victory-gpu | 181 | 0 | 5 | Bez regresji. 5 ignored to testy wymagające GPU/WARP. |
| victory-shader | 231 | 0 | 3 | Bez regresji. 3 ignored to benchmarki/specjalne warunki. |

Kluczowe testy Port 5:
- `port_cbv::tests::raw_views_need_sixteen_bytes` — **ok** (`raw_ok` odrzuca nie-16B).
- Wszystkie testy `descriptor::host` — **ok** (raw SRV w slocie nie psuje deskryptorów).
- Wszystkie testy `emit::lower` — **ok** (zmiana w ścieżce CBV nie psuje translacji).

### Statystyki runtime (kiedy `VICTORY_PORT_CBV=1`)

`port_cbv::log(frames)` wypisuje per frame:
- `in_place` — liczba tabel readujących CBV in place (zero kopii) + KB nie skopiowane.
- `copied: not in place` — CBV poza zakresem raw_ok (fallback do kopii).
- `copied: not on 16 bytes` — offset nie na 16 B (fallback do kopii).
- `twinned` — liczba slotów z raw SRV (zastępujących CBV).

---

## 5. Runbook A/B (nie uruchamiać bez zgody operatora)

Gra musi być ZAMKNIĘTA do momentu zgody.

### Konfiguracja bazowa (Fast3)

```
relay=2, queue2=1, async_submit=1, join_copies=1, late_wait=2,
copy_plain=1, texture_no_wait=1, card_buffers_mb=768,
texture_budget_mb=4096, levels_on_demand=1, card_rehash_runs=1,
staging_pool=1, late_wait=3, wide_back=1, back_own_view=1,
shader_loop_limit=256, bvh_builder=0, card_fetch_inflight=0,
refresh=120, borderless=1, uncap=1
```

### Ramiona

| Ramie | `VICTORY_PORT_CBV` | `VICTORY_PORT_CBV_PLACE` | Cel |
|---|---|---|---|
| A (base) | `0` | — | Stare zachowanie (kopie CBV w submicie) |
| B (port on, in place) | `1` | `1` | Zero-copy CBV, raw SRV w slocie heapu |
| C (port on, copied fallback) | `1` | `0` | Port on, ale `constant_raw_at` może zwrócić `false` (fallback do kopii) |

### Protokół (5 minut, w świecie)

1. Ten sam save, ten sam spawn, ten sam spacer (klucze: `25:Enter,45:Y,58:Enter,72:Enter,90:Enter,120:w,5:s,60:a,5:d,120:w`).
2. Zegar startuje gdy draws > 300 i utrzymuje się; stop po +300 s.
3. Screenshot o t=4:30 do `D:\Gry\VItoriaBr-data\logs\`, drugi o t=0:30.
4. Pełny stderr do `...\logs\ab-port5-<ramie>-stderr.log`.
5. Crash markers: `unhandled exception`, `0x887A0005`, `0x887A0007`, `0x80000003`, `int3`, `dstorage: retries used up`, `no free dynamic descriptor slots`.

### Metryki (z framelog)

- `submit thread: at work` ms / `preparing` ms — główny wskaźnik.
- `copies` ms i MB/frame — powinno spaść w ramieniu B (mniej kopii CBV).
- `renderer port 5 (...)` line — gdy port on: in-place count, not-in-place count, not-16B count, twinned count.
- fps p50, p95.
- `card idle` / "behind us" — GPU wciąż stoi bezczynnie (50–58% u soldsawn).

### Sukces / kill criteria

- **Sukces:** `copies` spada, `preparing` spada, fps rośnie ≥5%, brak nowych crash markers, brak TDR/AV, `twinned` > 0 w ramieniu B.
- **Kill:** `submit-ms` się nie ruszy (wąskie gardło gdzie indziej), nowe AV/TDR (rollback natychmiastowy), obraz się różni (vis regression), `twinned == 0` w ramieniu B (port nieaktywny — sprawdzić `lower.rs`).
- **Desync check:** jeśli raw base byłby dynamiczny (nie jest w tym podejściu), sprawdzić brak desync między tabelami. W obecnym podejściu slot jest stały — ryzyko desync nie istnieje.

---

## 6. Ryzyka i rollback

| Ryzyko | Ocena | Opis | Rollback |
|---|---|---|---|
| AV (access violation) | Średnie | Odczyt title memory in place; jeśli tytuł zmapuje stronę podczas odczytu → AV. `constant_raw_at` waliduje range gegen `buffer.GetDesc().Width`. | `VICTORY_PORT_CBV=0` |
| TDR | Średnie | Długi odczyt title memory może opóźnić submity; GPU 50–58% zajęty, bufor czasu jest. | `VICTORY_PORT_CBV=0` |
| Vis (obraz) | Średnie | Stale/niepełne CBV → czarne powierzchnje, błędne stałe shadera. | `VICTORY_PORT_CBV=0` |
| int3 | Niskie | Int3 to title-side pool assert, niezwiązany z CBV. | — |
| Brak zysku | Średnie | Bez `lower.rs` shaders nadal czytają przez CBV — port nie działa. Teraz `lower.rs` jest zmienione, więc port jest aktywny gdy `VICTORY_PORT_CBV=1`. | `VICTORY_PORT_CBV=0` (domyślnie `0`) |
| Root CBV ABI | Niskie | Root CBV używa `root_srv_handle` — wymaga SRV-typnego root parametera. Jeśli root parameter jest CBV-typny, zostaje CBV (brak zmiany, brak awarii). | Automatyczny fallback w `lower.rs`. |

**Rollback:** jedna env-lina — `VICTORY_PORT_CBV=0` (lub unset). Kod zostaje w drzewie za switch, domyślnie wyłączony.

---

## 7. Oczekiwany zysk

- **copies/frame:** −do 22 000 (w cidade, zgodnie z źródłem CGBJ); w naszym drzewie zależne od liczby CBV w tabelach drawów.
- **preparing ms:** −15–25 ms na klatkę (szacunek z PERF-PORT-PLAN.md).
- **fps:** +50–150% w ramieniu B względem bazy (cel 4–6 fps na 16 GB/8 GB, przy profilu residency).
- **Submit thread:** ≥30% mniej czasu pracy.

---

## 7. A/B results (wykonane 2026-11-26)

### Setup

- Worktree: `D:\git\VItoriaBr-port5`, commit `db189b5`
- Launcher: `D:\Gry\VItoriaBr-data\Launch-VItoriaBr-Port5.ps1` (bazuje na Fast3)
- Repo config: `D:\git\VItoriaBr-opt\victory.toml`
- Gra: ZAMKNIĘTA przed testem; uruchamiana tylko w ramach A/B, jeden proces na raz

### Ramiona

| Ramie | `VICTORY_PORT_CBV` | `VICTORY_PORT_CBV_PLACE` | Czas w świecie | Wynik |
|---|---|---|---|---|
| A (base) | `0` | — | **0 s** — crash na starcie | Crash (unhandled 0xc0000005) |
| B (port on) | `1` | `1` | ~5 min (PID 15440) | W świecie, port aktywny |

### Metryki (z framelog)

| Metryka | Arm A (port off) | Arm B (port on, w świecie) | Uwagi |
|---|---|---|---|
| `renderer port 5` line | brak (port off) | `twinned=363-1142, in_place=363-1142, 420-743 KB not copied/frame, 0 not in place, 6 not on 16 bytes` | Port **aktywny** w B |
| copies MB/frame | — (brak framelogu) | 104-160 MB (plaincopy, oddzielna ścieżka) | Nieporównywalne |
| preparing ms | — (brak framelogu) | 136-379 ms (ciężka scena) | Nieporównywalne |
| copy-back ms | — (brak framelogu) | 32-112 ms | Nieporównywalne |
| fps p50 | — (brak framelogu) | 1.1-30 fps (zależnie od sceny) | Nieporównywalne |
| draws/frame | — (brak framelogu) | 11-1048 | Nieporównywalne |
| Crash markers | **unhandled 0xc0000005** (write 0x54319fc00, victory.exe+0x532b6e) — pre-existing dstorage/zlib crash na starcie | first-chance 0xc0000005 w `nvwgf2umx.dll` (read 0x40, obsługiwane przez VEH, nie unhandled) | Arm A crashuje przed framelogiem |

### Werdykt: INCONCLUSIVE

**Co potwierdzone:**
- Port 5 jest **aktywny**: `twinned > 0` (363-1142) w ramieniu B, `in_place > 0`, 420-743 KB nie skopiowane na klatkę, 0 fallbacków (not in place). `lower.rs` poprawnie emituje `rawBufferLoad` zamiast `cbuffer_dword`.
- Build i testy CPU przechodzą bez regresji (181 + 231 testów).
- Arm B z portem ON **nie crashuje się z unhandled exception** (tylko first-chance w sterowniku NVIDIA, obsługiwane), podczas gdy Arm A bez portu crashuje się na starcie z unhandled 0xc0000005.

**Co blokuje werdykt PASS:**
1. **Brak bazy Arm A:** Arm A crashuje się na starcie z pre-existing unhandled 0xc0000005 (dstorage/zlib inflate do title memory, ten sam wzorzec co CRASH-TRIAGE Fast4). Nie ma framelogu, nie ma metryk preparing/copies/fps. Nie można porównać A/B.
2. **First-chance exceptions 0xc0000005** w `nvwgf2umx.dll` (sterownik NVIDIA) w ramieniu B: odczyt `0x40` ("nothing mapped there"). Są obsługiwane przez VEH (first-chance, nie unhandled), proces nie padł, ale wskazują na potencjalny problem z odczytem title memory przez raw SRV. Wymaga wyjaśnienia.

**Rollback:** `VICTORY_PORT_CBV=0` (domyślne) — port wyłączony, zero zmian w działaniu.

### Następny krok

1. **Naprawić pre-existing crash na starcie** (P0 write-retry / dstorage remap gap — terytorium innego agenta, nie Port 5). Bez tego A/B nie może być wykonane poprawnie.
2. **Wyjaśnić first-chance 0xc0000005 w nvwgf2umx.dll** — czy raw SRV czyta poza zakres bufora, czy alignment 16 B nie wystarcza dla sterownika NVIDIA.
3. **Powtórzyć A/B w tej samej scenie (świat, nie menu)** — po naprawie crashu, pełne 5 min, porównać copies/preparing/fps przy matched draws.
4. Jeśli A/B potwierdzi zysk → przejść do **Port 1** (`VICTORY_PORT_CONSTANTS=1`).

---

## 8. Overnight: Port 5 + P0 write-retry integration + clean A/B (2026-11-26)

### Faza 0 — integracja (wykonane)

Worktree `D:\git\VItoriaBr-port5-p0`, commit `186c7a8` (na bazie Port5 `db189b5` + cherry-pick P0 `cc1de49`).

- Cherry-pick P0 przeszedł bez konfliktów: `host.rs` zawiera zarówno `HEAP_BUFFER_PASSES` (pre-existing fix) jak i `port_cbv::log(frames)`; `watch.rs` to P0-only (nie ruszane poza P0).
- **Root CBV fix:** root CBVs (`props 13`, kind `Cbv`/`None`) trzymają `root_cbv_handle` nawet przy `VICTORY_PORT_CBV=1`; raw SRV tylko dla table CBVs (ścieżka heapu) i SRV-typed root params. Dodano licznik `root_cbv_fallback()` w `victory-shader::emit::shader`, wywoływany z `lower.rs`.
- `port_cbv.rs`: STATS z powrotem 5, usunięto nieużywaną `root_cbv_fallback_note`.
- Build i testy CPU: **sukces** (victory-gpu 189 passed, victory-shader 231 passed, zero regresji).

### Faza 1 — clean A/B (wykonane, werdykt: FAIL/INCONCLUSIVE)

Launcher: `D:\Gry\VItoriaBr-data\Launch-VItoriaBr-Port5P0.ps1` (bazuje na Fast3).
- Arm A: `VICTORY_PORT_CBV=0` + `VICTORY_WRITE_RETRY=1`
- Arm B: `VICTORY_PORT_CBV=1` + `VICTORY_PORT_CBV_PLACE=1` + `VICTORY_WRITE_RETRY=1`
- Jeden proces GPU na raz; P0 (VItoriaBr-opt) nie ruszany.

| Ramie | PORT_CBV | WRITE_RETRY | Czas | Wynik |
|---|---|---|---|---|
| A (base) | `0` | `1` | 5 min | Przeżył (menu, 3-11 draws, 60 fps, brak crashu) |
| B (port on) | `1` | `1` | 0s | **Crash natychmiast po starcie** (proces zniknął, log kończy się na frame 16, brak unhandled exception w logu — prawdopodobnie OOM/silent crash) |

Free RAM przed startem Arm B: ~1,4 GB (blisko granicy stop condition <1 GB).

**Werdykt: FAIL / INCONCLUSIVE**

- Port 5 jest aktywny w Arm B (`twinned=1`, port_cbv line wypisana) — kod działa.
- Ale Arm B crashuje się natychmiast po starcie przy PORT_CBV=1 + WRITE_RETRY=1, podczas gdy Arm A (PORT_CBV=0 + WRITE_RETRY=1) przeżywa 5 min.
- Nie można porównać copies/preparing/fps (brak framelogu w B, Arm A tylko w menu).
- Nie wiadomo czy crash to:
  a) interakcja P0 write-retry + Port 5,
  b) OOM (free RAM 1,4 GB),
  c) czysty przypadek.

**Rollback:** `VICTORY_PORT_CBV=0` (domyślne).

### Faza 2 — Port 1

**NIE rozpoczęta.** Zgodnie ze stop condition: Phase 1 FAIL/INCONCLUSIVE → nie zaczynam Port 1.

### Faza 3 — raport

Niniejsza sekcja jest raportem. Commit tylko w worktree `port5-p0` (commit `186c7a8`), nie w main. Zero danych gry w repo.

### Wnioski końcowe (overnight)

| Pytanie | Odpowiedź |
|---|---|
| Czy P0+Port5 się buduje? | Tak (commit 186c7a8) |
| Czy testy CPU przechodzą? | Tak (189 + 231, zero regresji) |
| Czy Port 5 jest aktywny? | Tak (`twinned > 0`, `lower.rs` emituje `rawBufferLoad`) |
| Czy P0+Port5 daje zysk w A/B? | **Nie można stwierdzić** — Arm B crashuje natychmiast |
| Czy root-CBV fallback był potrzebny? | Tak — root CBV musi trzymać `root_cbv_handle`, nie `root_srv_handle` |
| Czy zacząć Port 1? | **Nie** — Phase 1 INCONCLUSIVE/FAIL |

### Następny krok (po overnight)

1. **Wyjaśnić crash Arm B** (PORT_CBV=1 + WRITE_RETRY=1, natychmiast po starcie): czy OOM (RAM), czy interakcja P0+Port5, czy czysty przypadek. Powtórzyć przy większym wolnym RAM.
2. **Naprawić pre-existing crash na starcie** (P0 write-retry / dstorage remap gap — terytorium innego agenta). Bez stabilnej bazy A/B nie ma sensu.
3. **Powtórzyć A/B w świecie** (nie menu), pełne 5 min, matched draws.
4. Jeśli A/B potwierdzi zysk → przejść do **Port 1** (`VICTORY_PORT_CONSTANTS=1`).

Kod portu oparty na `DoubleGhosty/cool_fox` commit `c7fff5410a` (Renderer Port 5, zero-copy CBV), GPL-3.0. Drzewo `VItoriaBr-opt` jest GPL-3.0. Zero danych/bytes gry w repo `gta6-30fps`. Wszystkie zmiany tylko w worktree `port5`, nie w main. Attribution: CGBJ / DoubleGhosty.