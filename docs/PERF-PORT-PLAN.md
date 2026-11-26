# PERF-PORT-PLAN — plan portu submission/copy + residency na 16 GB RAM / 8 GB VRAM

**Rola:** niezależny senior performance engineer (perf/submission/residency).
**Zakres:** read-only w `D:\git\VItoriaBr-opt`; brak uruchamiania gry; brak dotykania `watch.rs` (P0 write-retry w locie przez innego agenta); brak shaderów/GLM-AUDIT-SHADER-GAP.
**Dokumentacja wejściowa (przeczytane, nie nadpisane):** `SCENE-INTEL-2026-11-26.md`, `COPY-LOOP-MATRIX.md`, `CRASH-TRIAGE-INT3-AV.md`, `PER-DRAW-COST.md`, `PERFORMANCE_BUDGET.md`.
**Logi (read-only):** `safe-mem-stderr.log`, `fast*-stderr.log` w `D:\Gry\VItoriaBr-data\logs\`.
**Licencja:** drzewo `VItoriaBr-opt` jest GPL-3.0 — portowany kod musi pochodzić z GPL-3.0 (soldsawn, DoubleGhosty/cool_fox, fxceless/victory-fork, LNX-victory, kelvaroq). Zero danych/bytes gry w repo `gta6-30fps`.
**Status:** brak commitów w `gta6-30fps`; plik tylko zapisany.

---

## 0. Podsumowanie wykonane i odrzucone

**Co potwierdziłem:**
- Najlepszy publiczny wynik 8 GB: **8–10 fps @1080p** na `soldsawn/victory-nvidia-8gb` (commit `c09a44e9`), RTX 4060 Laptop 8 GB, **48 GB RAM**, Series X + `DROP_MIPS=2` + `COPY_PLAIN=1` + thin LTO, VRAM 6.6/7.0 GB, GPU 50–58 % zajęty, CPU 45–50 %.
- GPU nie jest ścianą w najlepszym wyniku 8 GB — ścianą jest wątek submit/copy (48 ms/frame w tej samej rodzinie kodu; ok. 5–14 ms praca GPU).
- `VICTORY_COPY_PLAIN=1` i `VICTORY_WRITE_RETRY=0/1` już istnieją w naszym drzewie (`plaincopy.rs`, `watch.rs:1142–1187`). Nie duplikuję.
- `JOIN_PARTS` nie istnieje w naszym drzewie (0 wystąpień w `crates/**/*.rs`) — Fast4 był no-opem i szumem.
- W naszym drzewie brakuje: `PORT_CBV`, `PORT_CONSTANTS`, `DROP_MIPS`, `HEAP_WORKER`, `DRAW_READY_CACHE` — wymagają portu kodu.

**Co odrzuciłem:**
- CGBJ 25 fps — to prywatny build na **16 GB VRAM**, nie reprodukowalny, repo `codec-d/cool_fox` jest 404; najbliższy publiczny kod z tej rodziny mierzy **2,40–2,70 fps @1080p** na RTX 4060 Laptop 8 GB. Nie budżetujemy gegen 25 fps.
- `ad3lre/victory-nvidia-8gb` z telemetrią włączoną (`rxnd.de/vi/v1`, hash exe, zrzuty ekranu, proces towarzyszący) — wyłączamy lub nie używamy.
- Binarne release'e, mirrory CGBJ, "installery" GTA VI — brak zaufania, ryzyko malware.
- Kelvaroq unified memory / ReBAR read-only copies — jedyny pomysł rzędu wielkości, ale **nierealizowalny na 16 GB RAM** (trzeba by zmapić cały ślad tytułu; pagefile thrash). Odkładamy jako argument za 32 GB RAM, nie jako zadanie na tym laptopie.
- Shadery/LOD (GLM-agent) — osobne zadanie, nie dotykam.

---

## 1. soldsawn `c09a44e9` — ile zależy od 48 GB RAM, a ile od kodu

### 1.1 Zmierzony wynik (soldsawn, [SR] [B])

| Metryka | Wartość |
|---|---|
| fps @1080p | 8–10 (103,9–129,1 ms) |
| Draws/frame | 3 005–5 027 |
| VRAM | 6,6 / 7,0 GB (z 8 GB) |
| GPU busy | 50–58 % |
| CPU busy | 45–50 % |
| RAM | **48 GB** |
| Switches | Series X + `1920x1080` + `DROP_MIPS=2` + `COPY_PLAIN=1` + thin LTO |
| 4K ladder | 6 fps, 153–172 ms, 7,4–7,6 / 8,0 GB VRAM |

### 1.2 Ile zależy od 48 GB RAM, a ile od kodu

Na 8 GB VRAM i 1080p świat mieści się w 6,6–7,0 GB **tylko dzięki** `DROP_MIPS=2` (zwalnia ~1,4–2,3 GB) oraz rozdzielczości 1080p zamiast 4K. Bez tego samego zestawu VRAM wskakuje do 7,4–7,6 / 8,0 GB i fps spada do ~6. Oznacza to:

- **Residency (kod + env):** `DROP_MIPS=2` + `COPY_PLAIN=1` + `HEAP_WORKER=1` + 1080p — to *kod*, który możemy przenieść. Odpowiada za to, że świat w ogóle się mieści i nie ma eviction thrashu.
- **RAM 48 GB vs 16 GB:** soldsawn nie miał presji commitowej. Nasz laptop ma 16 GB RAM i już przy bezpiecznym profilu (safe-mem) logarithmuje 7474 MB private commit, 5109 MB w pamięci, 2172 MB wolne, 25 GB do commit. Przy pełnym świecie 8 GB VRAM + tytuły + cache shaderów/pagefile presja RAM będzie znacznie wyższa niż u soldsawn. 48 GB RAM u soldsawn oznacza, że **eviction z powodu braku RAM nie� wystąpił** — u nas może, nawet jeśli VRAM się mieści.

### 1.3 Realistyczny przedział fps na 16 GB RAM / 8 GB VRAM

Uzasadnienie: najlepszy publiczny wynik to 8–10 fps, ale przy **48 GB RAM** i po pełnym portcie submission (Port 5 + Port 1 + descriptor deferral). Nasz laptop ma 16 GB RAM, więc commit pressure obniży stabilność i p95. Biorąc pod uwagę, że GPU stoi bezczynnie 50–58 % i submit/copy to sufit:

| Scenariusz | Oczekiwany fps | Uzasadnienie |
|---|---|---|
| Pesymistyczny (brak portu, tylko env) | 1–3 | Obecny sufit 16 GB/8 GB to ok. 120–200 ms (5–8 fps) optymistycznie po kopii; bez portu submit remaining |
| Realistyczny (Port 5 + Port 1 + deferral, 16 GB) | **3–6** | Submit-ms spada ≥30 %, ale RAM 16 GB i pagefile ograniczają p95; spójne z rekomendacją SCENE-INTEL §7 |
| Optymistyczny (pełny port + idealny save) | 6–8 | Tylko jeśli commit zostanie pod kontrolą i nie będzie thrashu |

**30 fps jest poza zasięgiem tej warstwy na tym sprzęcie.** Wymaga 8,65 µs/draw all-in przy 3 850 draws; jesteśmy na ~200–350 µs/draw (25–40× powyżej celu). To natywny renderer, nie warstwa tłumaczenia.

---

## 2. Analiza commitów do portu — pliki, funkcje, ryzyko, rollback

Dla każdego mécanismeu podaję: dokładne pliki/funkcje w naszym drzewie, szacunkowy rozmiar diffu, konflikty z naszymi zmianami, ryzyko TDR/AV/int3/vis, czy wystarczy env-switch czy trzeba portu kodu.

### 2.1 Port 5 — zero-copy CBV (`VICTORY_PORT_CBV=1`), commit `c7fff5410a`

| Pole | Wartość |
|---|---|
| Mechanizm | Stałe bufora (CBV) czytane jako raw bytes in place, eliminuje ~22 000 buffer copies/frame |
| Nasze pliki/funkcje | `crates/victory-gpu/src/host.rs` (`submit`, `execute`, `copy_back`), `crates/victory-gpu/src/descriptor/host.rs` (`HostHeap::mirror`, `table_entry`, `readable`), `crates/victory-gpu/src/shadow.rs` (`copy_back`, `copy_back_with`, `find_any`), `crates/victory-gpu/src/draw.rs` (`prepare_for`, `bind`, root constants) |
| Szac. diff | ~400–700 líneas (nowa ścieżka odczytu CBV in place + rework `HostHeap::mirror` dla constant bufferów) |
| Konflikty | `draw.rs` (per-draw cache Agent A — `VICTORY_DRAW_READY_CACHE`, memos `ready_copies`/`ready_buffers`); `watch.rs` (P0 write-retry — nie dotykamy, ale port CBV może zmienić co jest strzeżone); `shadow.rs` (copy-back) |
| Ryzyko TDR | Średnie — odczyt in place tytułu pomija remap/guard, ale jeśli tytuł zmapuje stronę podczas odczytu, mogą być ciche uszkodzenia danych (vis) lub TDR przy device removal |
| Ryzyko AV | Średnie — raw pointer do title memory bez guard-open; jeśli strona jest re-guardowana w trakcie `rep movsb`-equivalent → AV. Potrzebuje guard na czas odczytu lub retry |
| Ryzyko int3 | Niskie — int3 to title-side pool assert, niezwiązany z CBV |
| Ryzyko vis | Średnie — stale/niepełne CBV mogą dać czarne powierzchnje, brak tekstur, błędne stałe shadera |
| Env-switch czy port kodu? | **Trzeba portu kodu** — nie ma `VICTORY_PORT_CBV` w drzewie; env sam w sobie nic nie robi |

### 2.2 Port 1 — in-place 32-bit graphics heap (`VICTORY_PORT_CONSTANTS=1`), commity `c496640276` / `5e0c9ab01e`

| Pole | Wartość |
|---|---|
| Mechanizm | 32-bitowa sterta grafiki tytułu używana in place; strony dostają section slice po kolejności adresowej; usuwa kolejną ścieżkę kopii dla stałych |
| Nasze pliki/funkcje | `crates/victory-gpu/src/host.rs` (heap passes, `heap_buffers`), `crates/victory-gpu/src/inplace.rs` (`title_memory_view`, `views_of_section`, `place_for`), `crates/victory-gpu/src/memory.rs`, `crates/victory-gpu/src/descriptor/host.rs` (heap of constants) |
| Szac. diff | ~300–500 líneas (nowy typ heapu, section slicing, mapping tytułu in place) |
| Konflikty | `inplace.rs` (jest już, ale bez 32-bit graphics heap); `host.rs` heap pass; `watch.rs` remapping (section slicing może kolidować z remap placeholders) |
| Ryzyko TDR | Niskie — principalement CPU-side mapping |
| Ryzyko AV | Średnie — in-place access do title memory przy jednoczesnym remapie tytułu → AV na stronach nie-mapped |
| Ryzyko int3 | Niskie |
| Ryzyko vis | Niskie-średnie — uszkodzone stałe → błędy renderowania |
| Env-switch czy port kodu? | **Trzeba portu kodu** — brak `VICTORY_PORT_CONSTANTS` w drzewie |

### 2.3 Descriptor-record deferral (280 → 124 ms)

| Pole | Wartość |
|---|---|
| Mechanizm | Descriptor records z tabel rysunków odkładane do momentu drawa (przygotowanie wątek 48 ms to ściana); 18 kroków odświeżania + 7 kroków karty na klatkę |
| Źródło | `DoubleGhosty/cool_fox/docs/findings.md` (commit `f4b48ad`) |
| Nasze pliki/funkcje | `crates/victory-gpu/src/descriptor/host.rs` (`defer_refresh`, `defer_gpu_write`, `tables`, `table_entry`), `crates/victory-gpu/src/host.rs` (`execute`, `submit`), `crates/victory-gpu/src/draw.rs` (`tables()`, `bind`) |
| Szac. diff | ~200–400 líneas (odkładanie budowania recordów do drawa, nowa kolejka deferral) |
| Konflikty | `draw.rs` per-draw cache (oba dotykają `table_entry`/`readable`); `descriptor/host.rs` (ten sam plik co Port 5) |
| Ryzyko TDR | Niskie |
| Ryzyko AV | Niskie — to reorganizacja CPU-side, nie nowy dostęp do pamięci tytułu |
| Ryzyko int3 | Niskie |
| Ryzyko vis | Niskie — tylko timing, nie dane |
| Env-switch czy port kodu? | **Trzeba portu kodu** — brak w drzewie |

### 2.4 DROP_MIPS / TEXTURE_MAX_DIM / HEAP_WORKER / COPY_PLAIN

| Mechanizm | Status w naszym drzewie | Pliki | Uwagi |
|---|---|---|---|
| `DROP_MIPS` / `TEXTURE_DROP_MIPS` | **Brak** — trzeba portować (`texture.rs`, `tiles.rs`, `resource.rs`) | `texture.rs` (upload, mip levels), `tiles.rs` (tiled resources), `resource.rs` (mip_levels) | Residency enabler, nie speed switch sam w sobie |
| `TEXTURE_MAX_DIM` | **Brak** | `texture.rs` (cap top mips) | Alternatywa dla DROP_MIPS |
| `HEAP_WORKER=1` | **Brak** | `texture.rs`, `host.rs` (upload thread) | Async heap-indexed texture upload; +2 fps na 12 GB |
| `COPY_PLAIN=1` | **JEST** (`plaincopy.rs`, `VICTORY_COPY_PLAIN`) | `plaincopy.rs` | Już włączony w fast3/safe-mem; 4–8 ms + spike removal |
| `TEXTURE_SKIP_MIPS` / `LEVELS_ON_DEMAND` | Częściowo | `texture.rs`, `tiles.rs` | Już w użyciu; zostaje na stałe na 16 GB |

**Wniosek:** `COPY_PLAIN` mamy. Reszta wymaga portu. `DROP_MIPS=2` jest warunkiem wstępnym (residency), bez niego port submission nie ma sensu na 8 GB VRAM (eviction thrash).

---

## 3. Ranking 3 eksperymentów na 16 GB RAM / 8 GB VRAM

Każda eksperyment: jedna zmienna, protokół 5 minut (screenshot + log + crash markers), oczekiwany zysk ms/fps, kill criteria. Limit to wątek submit/copy, nie GPU (GPU 50–58 % u soldsawn).

### Protokoł wspólny (wszystkie 3 eksperymenty)

- Start zegara, gdy title raportuje draws > 300 i utrzymuje je; stop po +300 s w świecie.
- Ten sam save, ten sam spawn, ten sam spacer (klucze: `25:Enter,45:Y,58:Enter,72:Enter,90:Enter,120:w,5:s,60:a,5:d,120:w`).
- Screenshot o t=4:30 do `D:\Gry\VItoriaBr-data\logs\`, drugi o t=0:30 (ładowanie). Przyjmij ramię tylko jeśli obraz identyczny poza znanymi artefaktami.
- Pełny stderr do `...\logs\ab-<nazwa>-stderr.log`; framelog musi być ciągły (przerwa > 30 s przy żywym procesie = zawieszenie).
- Crash markers (koniec ramki i odrzucenie): `unhandled exception`, `0x887A0005`, `0x887A0007`, `0x80000003`, `int3`, `dstorage: retries used up`, `driver's errors`, `no free dynamic descriptor slots`, nowy `*.crash.log`.
- Metryki: p50/p95 3D ms/frame przy matched draws (±10 %); present split (`in the present call`, `lines and settling`); submit thread (`preparing`, `copies`, `copy-back`); card idle i "behind us"; guard/page faults; `N MB free`; clamp count; dropped draws.
- Bramka: przyjmij jeśli p50 poprawia się ≥8 % przy matched draws **i** p95 się nie pogarsza **i** brak nowej klasy craszy; promuj dopiero po powtórce; w przeciwnym razie rollback jednej linii.
- VRAM/RAM guard: przerwij jeśli VRAM free ≤ 500 MB przez 3 próbki lub commit free < 1 GB (16 GB box).

### Eksperyment 1 — 8 GB residency profile (najwyższe zaufanie, najtańszy)

| Pole | Wartość |
|---|---|
| Zmienna (jedna) | Pakiet env: `DROP_MIPS=2` + `RESOLUTION=1920x1080` + `COPY_PLAIN=1` + `HEAP_WORKER=1` + `--console series-x` (traktowane jako jedna zmienna "profil residency") |
| Hipoteza | Na 4060/16 GB VRAM spada z ~7,5 GB do ≤7,0 GB, texture-slot waiting poniżej ~2 000, fps z 1–2 na **4–6** |
| Oczekiwany zysk | +200–400 % fps względem bazy; VRAM −0,5–1,0 GB |
| Kill criteria | Jeśli fps nie rośnie przy stabilnym VRAM (jak w E2b) — przestań tuning residency, idź do Eksperymentu 2. Jeśli commit paging > 15 GB — wyłącz `HEAP_WORKER`, przetestuj ponownie. |
| Pliki do portu | `texture.rs` (DROP_MIPS, MAX_DIM), `tiles.rs` (tiled), `host.rs` (HEAP_WORKER upload) |
| Ryzyko | Vis (rozmycie distant textures), array/MSAA wyłączone z drop mips |

### Eksperyment 2 — Port submission: Port 5 + Port 1 + descriptor deferral (najwyższy upside)

| Pole | Wartość |
|---|---|
| Zmienna (jedna na ramię) | Ramię A: `VICTORY_PORT_CBV=1` (Port 5). Ramię B: `VICTORY_PORT_CONSTANTS=1` (Port 1). Ramię C: descriptor deferral. Każde za własnym `VICTORY_PORT_*` switch. |
| Hipoteza | Submit-thread time spada ≥30 %, copies/frame spada ~20 000, fps rośnie **+50–150 %** przy tym samym obrazie (cel 4–6 fps) |
| Oczekiwany zysk | −15–40 ms na submit thread na klatkę |
| Kill criteria | Jeśli submit-ms się nie ruszy — wąskie gardło jest gdzie indziej (write-watch / relay); fallback na `VICTORY_THIN`/`JOIN_PARTS` profiling i Neptune submit profiler. Jeśli nowe AV/TDR — rollback natychmiastowy. |
| Pliki do portu | `host.rs` (submit, copy_back), `descriptor/host.rs` (mirror, table_entry, deferral), `shadow.rs` (copy_back), `draw.rs` (bind, prepare_for), `inplace.rs` (heap sections) |
| Konflikty | `draw.rs` per-draw cache Agent A; `watch.rs` P0 (nie dotykamy, ale port CBV zmienia co jest strzeżone) |
| Ryzyko TDR/AV/vis | Średnie (szczególnie Port 5 — raw odczyt title memory) |

### Eksperyment 3 — Shader/LOD correctness gate (nie jest eksperymentem fps)

| Pole | Wartość |
|---|---|
| Zmienna (jedna na ramię) | `caec5030` (undefined LOD slot), `cbb00ee8` (voxel wave64), `db556df3` (`NAN_SCRUB`, off by default), `LDS_REGION_RACE=1` |
| Hipoteza | Pipeline refusals z ~245/26 599 do <50, dropped draws z ~7 % do <2 %, znikają czarne/śmieciowe twarze i liście |
| Oczekiwany zysk | Brak bezpośredniego fps; correctness gate przed dalszym portem |
| Kill criteria | Jeśli switch zmienia zachowanie konsoli (NaN scrub) lub crashuje RT builder — zostaw wyłączony, udokumentuj |
| Pliki | `dpr.rs`, `pipeline/host.rs`, `texture.rs` (LOD), shader cache key |

**Ranking ogólny:** 1 (residency, warunek wstępny) → 2 (submission, główny zysk) → 3 (correctness, brama jakościowa, nie fps).

---

## 4. Plan portu — kolejność, pliki, testy

### Krok 0 — baza i instrumentacja (przed portem)

- Zbuduj w osobnym worktree `D:\git\VItoriaBr-opt` (nigdy w `target\release` przy bieżącym procesie).
- `VICTORY_PROFILE=1` przez 5 min, aby rozbić `preparing` (515 ms) na texture staging / heap pass / clamp waits. Tylko do wyboru kierunku, nie jako pomiar.
- Potwierdź bazę: safe-mem / fast3 framelog — submit thread dominuje, card idle 50–58 %.

### Krok 1 — Residency (tylko env, brak portu kodu poza DROP_MIPS)

1. Portuj `DROP_MIPS` / `TEXTURE_MAX_DIM` do `texture.rs` + `tiles.rs` + `resource.rs` (switch `VICTORY_TEXTURE_DROP_MIPS=N`, 0–4).
2. Portuj `HEAP_WORKER=1` (async heap-indexed texture upload) do `texture.rs` + `host.rs`.
3. `COPY_PLAIN=1` już jest — włącz.
4. Uruchom Eksperyment 1. Jeśli vrAM ≤7,0 GB i fps 4–6 — idź do Kroku 2.

### Krok 2 — Port 5 zero-copy CBV (największy submit win)

1. Załóż switch `VICTORY_PORT_CBV=1` w `host.rs`/`descriptor/host.rs`.
2. Nowa ścieżka odczytu CBV in place w `HostHeap::mirror` / `table_entry` / `readable` dla constant bufferów — z guard-open na czas odczytu (unikaj AV jak w `watch.rs` read branch).
3. Ramię A Eksperymentu 2; zmierz submit-ms, copies/frame.
4. Testy: `cargo test --offline -p victory-gpu` (draw, descriptor, shadow); brak regresji `cargo build --offline --release`.

### Krok 3 — Port 1 in-place 32-bit heap

1. Załóż switch `VICTORY_PORT_CONSTANTS=1`.
2. Nowy typ heapu + section slicing po kolejności adresowej w `inplace.rs` + `memory.rs` + `host.rs` heap pass.
3. Ramię B Eksperymentu 2; A/B osobno od Port 5 (nie łącz od razu).
4. Testy: jak wyżej + `inplace.rs` unit tests (warp title buffer in place).

### Krok 4 — Descriptor-record deferral

1. Przenieś budowanie descriptor records z tabel rysunków do momentu drawa w `descriptor/host.rs` (`defer_refresh`, `defer_gpu_write`) + kolejka w `host.rs`.
2. Ramię C Eksperymentu 2.
3. Testy: descriptor tests; p50 preparing ms.

### Krok 5 — Shader/LOD correctness (Krok równoległy, nie blokuje)

1. Portuj `caec5030`, `cbb00ee8`, `db556df3`, `LDS_REGION_RACE=1` (off by default).
2. Eksperyment 3; nie oceniaj po fps.

### Testy akceptacyjne przed promu-cją

- p50 `render thread: ran` i p50 `recording, all threads` ms/3000 draws spadają ≥15 % (dla submission).
- `reused` ≫ `searched` w licznikach cache (jeśli dotyczy).
- Brak nowych crash markers; brak device loss.
- Screenshot spot identyczny.
- Rollback jest oczywisty (jedna env-lina lub jeden commit do wyłączenia `VICTORY_PORT_*=0`).

---

## 5. Tabela: mechanizm | commit/plik | expected ms/fps | ryzyko | evidence | rollback

| Mechanizm | Commit / plik w naszym drzewie | Expected ms/fps | Ryzyko | Evidence | Rollback |
|---|---|---|---|---|---|
| DROP_MIPS / TEXTURE_DROP_MIPS | `fcb4f71bbb` (cool-fox-12gb) → port do `texture.rs`, `tiles.rs`, `resource.rs` | Residency: VRAM −1,4–2,3 GB; bez tego fps stoi | Vis (blur distant textures) | soldsawn 6,6/7,0 GB @8–10 fps | `VICTORY_TEXTURE_DROP_MIPS=0` |
| COPY_PLAIN=1 | `plaincopy.rs` (już w drzewie) | −4–8 ms + spike removal | AV low | Kelvaroq 0044, fast3 log | `VICTORY_COPY_PLAIN=0` |
| HEAP_WORKER=1 | Port do `texture.rs` + `host.rs` | +2 fps (na 12 GB) | RAM pressure | fxceless #1007 | `VICTORY_HEAP_WORKER=0` |
| Port 5 zero-copy CBV | `c7fff5410a` → `host.rs`, `descriptor/host.rs`, `shadow.rs`, `draw.rs` | −15–25 ms submit; copies/frame −20k | TDR med, AV med, vis med | DoubleGhosty cool_fox | `VICTORY_PORT_CBV=0` |
| Port 1 in-place 32-bit heap | `c496640276` / `5e0c9ab01e` → `inplace.rs`, `memory.rs`, `host.rs` | −5–15 ms submit (constants) | AV med | DoubleGhosty cool_fox | `VICTORY_PORT_CONSTANTS=0` |
| Descriptor-record deferral | `f4b48ad` (cool_fox docs/findings.md) → `descriptor/host.rs`, `host.rs` | 280 → ~124 ms preparing | Low | DoubleGhosty findings | `VICTORY_PORT_DEFER=0` (nowy switch) |
| P0 write-retry | `watch.rs:1142–1187` (JEST, nie dotykać) | Absorbuje race AV | — | CRASH-TRIAGE-INT3-AV.md P0 | `VICTORY_WRITE_RETRY=0` |

---

## 6. Czego NIE robić

1. **Nie uruchamiaj gry / nie przebudowuj `D:\git\VItoriaBr-opt` w miejscu.** Pracuj read-only; build tylko w osobnym worktree.
2. **Nie dotykaj `watch.rs`.** P0 write-retry jest w locie przez innego agenta; port CBV może zmienić co jest strzeżone, ale sam `watch.rs` niech pozostaje nienaruszony.
3. **Nie używaj telemetrii ad3lre.** `VICTORY_TELEMETRY=0` / `--no-telemetry` lub `[telemetry] enabled=false`. Wysyła hash exe, zrzuty ekranu, timeline fps do `rxnd.de`.
4. **Nie pobieraj ani nie uruchamiaj binarnych release'ów.** Brak zaufania, ryzyko malware (Vidar, fake installery GTA VI).
5. **Nie używaj mirrorów CGBJ / `ztrx` / `codec-d/cool_fox`.** Repo 404, brak kanonicznego drzewa, kopie mogą zawierać zmodyfikowane build scripty.
6. **Nie budżetuj gegen 25 fps CGBJ.** To 16 GB VRAM, prywatny, nie reprodukowalny. Nasz sufity: ~3–6 fps na 16 GB RAM.
7. **Nie obiecuj 30 fps.** Wymaga 8,65 µs/draw all-in; jesteśmy na 200–350 µs/draw. To natywny renderer, nie warstwa.

---

## 7. Rekomendacja (jeden akapit)

Zastosuj profil residency soldsawn (1080p + `DROP_MIPS=2` + `COPY_PLAIN=1` + `HEAP_WORKER=1` + Series X) jako warunek wstępny, następnie portéuj kodowo Port 5 zero-copy CBV i Port 1 in-place 32-bit heap oraz descriptor-record deferral za własnymi `VICTORY_PORT_*` switchami, mierząc każdy osobno w 5-minutowych ramionach Eksperymentu 2. Oczekiwany realny wynik na 16 GB RAM / 8 GB VRAM to **3–6 fps** (nie 8–10, bo soldsawn miał 48 GB RAM), przy submicie/copy jako ścianie i GPU na 50–58 %. Nie obiecujemy 30 fps — to wymaga natywnego renderera i prawdopodobnie 16 GB VRAM / 32 GB RAM. Portuj tylko z GPL-3.0, tylko z commitów ze zwartym źródłem, bez mirrorów i bez telemetrii ad3lre.

---

Część 1 zapisana: wstęp, soldsawn/16 GB, analiza commitów, ranking eksperymentów, plan portu, tabela, czego nie robić, rekomendacja. Kontynuuję w następnej wiadomości — potrzebuję potwierdzenia, że część 1 została zapisana poprawnie, zanim przejdę do ewentualnych uzupełnień.