# NEMOTRON — audyt wydajności + plan portu zero-copy/submission (VItoriaBr-opt)

**Data:** 2026-11-26  
**Rola:** niezależny senior performance engineer  
**Status:** read-only — żadnych zmian w `D:\git\VItoriaBr-opt`, gra zamknięta, żadnych binarek nie uruchamiam, żadnych danych gry w repo. Nie dotykam `crates/victory-gpu/src/watch.rs` (użytkownik zmienia, P0 write-retry).

## 0. Źródła i metoda

| Źródło | Ścieżka / identyfikator | Uwaga |
|---|---|---|
| Nasze drzewo | `D:\git\VItoriaBr-opt\` | Rust, GPL-3.0, `target\release\victory.exe` SHA-256 bf12251e… |
| Raporty wejściowe | `D:\git\gta6-30fps\docs\SCENE-INTEL-2026-11-26.md`, `COPY-LOOP-MATRIX.md`, `CRASH-TRIAGE-INT3-AV.md`, `GLM-AUDIT-SHADER-GAP.md`, `PER-DRAW-COST.md`, `PERFORMANCE_BUDGET.md` | Wszystkie istniały i zostały przeczytane |
| Logi | `D:\Gry\VItoriaBr-data\logs\safe-mem-stderr.log`, `fast*-stderr.log` | Read-only |
| soldsawn/victory-nvidia-8gb | GitHub README @ commit c09a44e97df4170ef0caa8cc236f7cb46fd1ce90 | websearch/webfetch, fallback Firecrawl niedostępny |
| CGBJ / DoubleGhosty/cool_fox | GitHub, commity c7fff5410a, c496640276, 5e0c9ab01e | websearch/webfetch, fallback |

**ECC użyte:** `change-impact` (mapa powierzchni zmian przed portem), `benchmark-methodology` (dyscyplina dowodów, brak średniej kompozytowej, asserted vs proven), `rust-patterns` (idiomy Rust, borrow zamiast clone, wynik kompilacji ≠ poprawność).  
**REA:** nie używane — nie potrzeba dowodu z binarki gry; dowód z victory.exe już zebrany w GLM-AUDIT (ev_8b7c5e72…, ev_020c0681…).

Każda liczba ma etykietę dowodu: `[SR]` = self-reported (właściciel fork-a), `[F]` = sourced fact (plik/log/commit), `[I]` = wniosek, `[R]` = rekomendacja. Brak dowodu = `unverified`, nie zgadywanie.

---

## 1. Weryfikacja wyniku soldsawn/victory-nvidia-8gb (commit c09a44e9)

### 1.1 Co jest potwierdzone (źródło: publiczny README @ c09a44e9)

| Fakty | Wartość | Źródło / etykieta |
|---|---|---|
| Repozytorium | `soldsawn/victory-nvidia-8gb`, fork `fxceless/victory-fork@f5c03f3` | [F] README |
| Commit HEAD | `c09a44e97df4170ef0caa8cc236f7cb46fd1ce90` (merge, 0 zmian — "chore: keep soldsawn/main history") | [F] GitHub API |
| Sprzęt | RTX 4060 Laptop 8 GB VRAM (Wave32), i5-12450H, **48 GB RAM**, Win 11 HAGS, Series X profile | [SR] README |
| Ustawienia | `VICTORY_RESOLUTION=1920x1080` + `VICTORY_TEXTURE_DROP_MIPS=2` + `VICTORY_COPY_PLAIN=1` + Thin LTO | [SR] README |
| Wynik 1080p | **8–10 FPS** (103.9–129.1 ms/frame @ 3 005–5 027 draws) | [SR] README |
| GPU busy | 50–58 % | [SR] README |
| CPU busy | 45–50 % | [SR] README |
| VRAM | **6.6 / 7.0 GB** z 8,0 GB | [SR] README |
| Wynik 4K ladder | 153–172 ms/frame (6 FPS) @ 4 600–6 836 draws, 96% GPU, ~7.4–7.6/8.0 GB VRAM | [SR] README |

**Kluczowe odczytanie z README:** `DROP_MIPS=2` zapobiega wyczerpaniu 8 GB VRAM (tekstury i sondy światła uploadują się czysto przy pierwszym uruchomieniu). `RESOLUTION=1920x1080` obniża obciążenie GPU z 96% do 50–58% i zwalnia ~1,4–2,3 GB VRAM.

### 1.2 Ile z wyniku zależy od 48 GB RAM, a ile od kodu

**48 GB RAM jest częścią wyniku, nie tylko kodem.** Dowody:

- soldsawn deklaruje 48 GB RAM w sprzęcie ([SR] README). To nie jest opcjonalny detail — na 16 GB RAM commit pressure jest gorszy (PERFORMANCE_BUDGET: 16 GB RAM, pagefile 32 GB na D:, unikać 1455).
- Niezależny punkt odniesienia: RTX 3070 desktop 8 GB, **16 GB RAM**, release build 7b7b952, Series X, 1080p cap, `TEXTURE_DROP_MIPS=2` → 148 ms median frame (~6,7 fps), copy-back 12–18 ms, bez błędów/device loss ([SR] soldsawn issue #4, GitHub).
- CGBJ-family na tym samym laptopie (miaohaixiang1-netizen/cool-fox-12gb, RTX 4060 Laptop 8 GB, i9-14900HX, 31,6 GB): **2,40–2,70 fps @1080p** ([SR] [A−] SCENE-INTEL §3.4).
- Nasze własne pomiary (COPY-LOOP-MATRIX): Fast3 = 418–535 ms/klatkę (1,9–2,4 fps) na 16 GB RAM / 8 GB VRAM, submit thread 1 148 ms pracy na klatkę, GPU idle ~1 081 ms z 1 290 ms.

**Wniosek:** kod (DROP_MIPS=2, COPY_PLAIN=1, Thin LTO, 1080p) daje rzędu 5–8 fps na 8 GB VRAM, ale **48 GB RAM usuwa commit pressure jako tło**. Na 16 GB RAM ten sam kod będzie wolniejszy ze względu na pagowanie i mniejszy pagefile headroom.

### 1.3 Realistyczny przedział fps na naszym laptopie (16 GB RAM / 8 GB VRAM)

| Scenariusz | Przedział fps | Uzasadnienie |
|---|---|---|
| Kod soldsawn, 1080p + DROP_MIPS=2 + COPY_PLAIN=1, 16 GB RAM | **3–6 fps** | 8–10 fps soldsawn z 48 GB RAM; 6,7 fps na RTX 3070 8 GB / 16 GB RAM z DROP_MIPS=2; nasze Fast3 1,9–2,4 fps bez portu submission |
| 4K ladder (bez 1080p) | ~0,5–1 fps | soldsawn 4K = 6 fps na 4060 Laptop z DROP_MIPS=2, ale 96% GPU i 7,4–7,6/8 GB VRAM — na 16 GB RAM pagowanie obetnie dalej |
| 30 fps | **nieosiągalne przez warstwę** | PERFORMANCE_BUDGET: "3D: 1–6 fps na tym laptopie; 30 fps wymaga natywnego portu/renderera i prawdopodobnie 16 GB VRAM / 32 GB RAM. To nie jest obietnica; to hipoteza do obalenia." |

**Hard fact:** GPU w soldsawn jest zajęty tylko 50–58%, CPU 45–50% — **submit/copy thread jest sufitem, nie GPU**. Na 16 GB RAM ten sufite obniża się jeszcze przez pagowanie commit.

---

## 2. Tabela mechanizmów CGBJ / soldsawn vs nasze drzewo

Status: pliki/funkcje w naszym drzewie oznaczone `unverified` — wymagają `git grep` przed portem. Nie dotykam `watch.rs`.

| Mechanizm | Commit / plik w obcym drzewie | Expected ms / fps | Ryzyko | Evidence | Rollback |
|---|---|---|---|---|---|
| **Port 5: zero-copy CBV** (`VICTORY_PORT_CBV=1`) | `c7fff5410a` (DoubleGhosty/cool_fox); stałe buforów odczytywane jako surowe bajty w miejscu, ~22 000 kopii buforów/frame mniej | −60…−150 ms submit; +50–150% fps przy tym samym obrazie | `TDR` nisk-med; `AV` nisk-med (raw slice do title pamięci — TOCTOU jak w CRASH-TRIAGE §3.3); `vis` nisk-med | [SR] SCENE-INTEL §4.1; COPY-LOOP-MATRIX B1/B3 | `VICTORY_PORT_CBV=0` lub revert commitu |
| **Port 1: in-place 32-bit graphics heap** (`VICTORY_PORT_CONSTANTS=1`) | `c496640276` + `5e0c9ab01e` (DoubleGhosty); strony tytułu jako sekcje w kolejności adresowej, bufory używane w miejscu zamiast kopiowane | −20…−60 ms | `TDR` nisk; `AV` nisk-med; `vis` nisk | [SR] SCENE-INTEL §4.1 | `VICTORY_PORT_CONSTANTS=0` |
| **Deskriptor-record deferral** | `f4b48ad` (DoubleGhosty/docs/findings.md): 280 ms → ~124 ms; preparing thread 48 ms jest sufitem; 18 refresh kroków + 7 card kroków/frame | −156 ms preparing | `TDR` nisk; `AV` nisk | [SR] SCENE-INTEL §4.2 (RX 7900 XTX, mechanizm karta-agnostyczny) | env switch lub revert |
| **`VICTORY_TEXTURE_DROP_MIPS=2`** | `fcb4f71bbb` (miaohaixiang), PR fxceless#610 (otwarty, nie scalony) | residency enabler: 6.6/7.0 GB zamiast 7.4–7.6/8.0 GB; sama przez siebie **brak zysku fps** | `vis` med (rozmycie odległych tekstur, array/MSAA wyłączone) | [F] SCENE-INTEL §4.1; [SR] soldsawn README | `=0` lub `=1` |
| **`VICTORY_COPY_PLAIN=1`** | fxceless#1032; rep movsb in-process, fallback kernel na brakującą stronę | −4…−8 ms + spike >1 s usunięte | `AV` nisk | [F] COPY-LOOP-MATRIX A10; [B] Kelvaroq 0044 | `=0` |
| **`VICTORY_HEAP_WORKER=1`** | fxceless#1007; async heap-indexed texture upload | 6,2–6,7 → 8,2–8,6 fps (RTX 4070 12 GB) | `TDR` nisk-med (wątek uploadu) | [F] SCENE-INTEL §4.2 | `=0` |
| **`VICTORY_INDIRECT_WINDOW=1`** | fxceless#812/#979/#987; clamp rekordów indirect w jednym pasmie | −60…−150 ms (expected) | `vis` low-med | [F] COPY-LOOP-MATRIX A1; [B] Kelvaroq 0041 | unset env |

**Uwaga co do rozmiaru diffu:** nie pobieram ani nie uruchamiam binarek; rozmiar diffu (liczba linii/plików) wymaga `git show --stat <commit>` na obcym repo — oznaczam jako `unverified` i wskazuję do potwierdzenia przed portem.

### 2.1 Mapowanie na nasze drzewo (do weryfikacji `git grep`)

| Obszar w obcym drzewie | Prawdopodobny odpowiednik w `D:\git\VItoriaBr-opt` | Status |
|---|---|---|
| CBV / root descriptors | `crates/victory-gpu/src/root.rs`, `crates/victory-gpu/src/descriptor/host.rs` | unverified |
| Per-draw state, Root enum (Table/Constants/View) | `crates/victory-gpu/src/draw.rs` (czytane: Root, VertexView, IndexView) | unverified |
| Submit thread, copies, copy-back | `crates/victory-gpu/src/host.rs`, `queue.rs`, `queue2.rs`, `shadow.rs` | unverified |
| Write-retry / guard (P0, użytkownik) | `crates/victory-gpu/src/watch.rs` — **nie dotykać** | n/a |
| Per-draw cache | `crates/victory-gpu/src/draw.rs` (VICTORY_DRAW_READY_CACHE=1, commit 02f224f, PER-DRAW-COST.md) | istnieje |

Konflikty z naszymi zmianami: Port 5 i Port 1 modyfikują ścieżkę kopii buforów/stałych — może nakładać się na `draw.rs` per-draw cache i `watch.rs` write-retry. Każdy port musi być testowany osobno (jedna zmienna), nie jako pakiet.

---

## 3. Dokładny plan portu (kolejność, pliki, testy)

Zasada: **jedna zmienna na raz**, każdy port za `VICTORY_PORT_*` switch (env, nie code-only), rollback jednej linią. Nie portujemy jako pakiet.

### Krok 0 — Instrumentacja (raz, nie jest A/B)
Ustawić `VICTORY_PROFILE=1` na 5 min, żeby podzielić `preparing` (515 ms w Fast3) na texture staging / heap pass / clamp waits. Zmienia timing — użyć tylko do wyboru miejsca, nie jako pomiar.

### Krok 1 — Port 5 zero-copy CBV (najwyższy zysk CPU)
1. Zidentyfikować w naszym drzewie: gdzie CBV/root descriptors są kopiowane (`root.rs`, `descriptor/host.rs`, `draw.rs` `Root::Constants`/`Root::View`).
2. Dodać `VICTORY_PORT_CBV=1` — odczytywanie stałych buforów jako surowe bajty w miejscu zamiast kopii.
3. Zablokować za flagą env (off domyślnie).
4. Test: 5-min A/B przeciw Fast3, 매trica: submit ms, copies MB/frame, draws, fps, crash markers.
5. Kryterium akceptacji: submit-thread czas spada ≥30%, copies/frame spada ~20k, brak nowych crashy.

### Krok 2 — Port 1 in-place 32-bit graphics heap (osobno od Port 5)
1. Zidentyfikować: gdzie grafika 32-bit jest kopiowana zamiast używana w miejscu (`descriptor/host.rs`, `host.rs` card buffers).
2. Dodać `VICTORY_PORT_CONSTANTS=1` — strony tytułu jako sekcje w kolejności adresowej.
3. A/B osobno od Port 5 (nie mierzyć pakietu).
4. Kryterium akceptacji: −20…−60 ms, brak regresji obrazu.

### Krok 3 — Deskriptor-record deferral
1. Zidentyfikować: gdzie deskryptory tabel draw są przetwarzane per submission (`host.rs`, `draw.rs` tables).
2. Odroczyć deskryptorowe rekordy do samych drawów (280 → ~124 ms preparing).
3. Kryterium akceptacji: preparing thread spada poniżej 48 ms/frame, brak device loss.

### Krok 4 — 8 GB residency profile (env only, bez portu kodu)
`VICTORY_RESOLUTION=1920x1080` + `VICTORY_TEXTURE_DROP_MIPS=2` + `VICTORY_COPY_PLAIN=1` + `--console series-x` + `VICTORY_HEAP_WORKER=1`.

Testy regresyjne: ten sam save, ta sama kamera, 3 przebiegi, pixel compare (brak nowych czarnych/lecących trójkątów), brak `device removed`/`0x887A0005/0007`.

---

## 4. Ranking 3 eksperymentów na 16 GB RAM / 8 GB VRAM

Każdy z jedną zmienną, 5-minutowy protokół (screenshot + log + crash markers), oczekiwany zysk i kill criteria. Base = Fast3 (relay=2, late=2, join_copies=1, wide_refresh/merge=1, card_rehash_runs=1, async_submit=1, queue2=1, copy_plain=1, texture no-wait, 720p, uncap, ambient 0). 5 minut **w świecie**, nie od launchu.

### Eksperyment 1 — 8 GB residency profile (najwyższa pewność, najtańszy)
- **Zmienna (jedna):** pakiet env `VICTORY_RESOLUTION=1920x1080` + `VICTORY_TEXTURE_DROP_MIPS=2` + `VICTORY_COPY_PLAIN=1` + `VICTORY_HEAP_WORKER=1` + `--console series-x` (traktowane jako jedna zmienna "profil residency", bo bez DROP_MIPS nie mieści się w VRAM).
- **Hipoteza:** VRAM spada z ~7,5 GB do ≤7,0 GB, texture-slot waiting spada poniżej ~2 000, fps z 1–2 do **4–6**. [I]
- **Mierzone:** VRAM/commit, `textures waiting`, submit ms, copy-back ms, fps. A/B każdego switcha osobno, nie bundle.
- **Kill criteria:** jeśli fps nie zmienia się przy stabilnym VRAM (jak w naszym E2b) — przestać dopasowywać residency, przejść do E-B. Jeśli commit paging powyżej ~15 GB — wyłączyć `HEAP_WORKER` i przetestować ponownie.
- **Ryzyko:** `vis` med (rozmycie tekstur), `TDR` nisk.

### Eksperyment 2 — Port 5 zero-copy CBV (najwyższy upside)
- **Zmienna (jedna):** `VICTORY_PORT_CBV=1` (kod portu, za flagą env).
- **Hipoteza:** submit-thread czas spada ≥30%, copies/frame spada ~20 000, fps rośnie **+50–150%** przy tym samym obrazie (cel 4–6 fps). [I]
- **Mierzone:** submit ms, `after_present`/`until_submit`, copies MB/frame, draws, fps. A/B Port 5 osobno od Port 1.
- **Kill criteria:** jeśli submit ms się nie ruszy — wąskie gardło jest gdzie indziej (write-watch / relay); fallback do profilowania `VICTORY_THIN`/`JOIN_PARTS` i Neptune submit profiler.
- **Ryzyko:** `TDR` nisk-med, `AV` nisk-med (raw slice do title pamięci).

### Eksperyment 3 — Shader/LOD correctness gate (nie eksperyment fps)
- **Zmienna (jedna):** paczka shader-correctness: `caec5030` (undefined LOD slot), `cbb00ee8` (voxel wave64), `db556df3` (NAN_SCRUB, off domyślnie), `LNX` `LDS_REGION_RACE=1` + `LDS_BOUNDS` default.
- **Hipoteza:** pipeline refusals spadają z ~245/26 599 do <50, dropped draws z ~7% do <2%, znikają czarne/śmieciowe twarze i roślinność. [I]
- **Mierzone:** refusal count, dropped-draw reasons, 10 zrzutów ekranu, crash log. **Nie oceniać po fps.**
- **Kill criteria:** jeśli switch zmienia zachowanie konsoli (NaN scrub) lub crashuje RT builder — zostawić wyłączone i udokumentować.
- **Ryzyko:** `vis` wysoki (obraz się zmienia), `int3` nisk (shader assertions).

**Protokół każdego biegu (5 min, porównywalny):** start zegara gdy tytuł raportuje draws > 300 i je utrzymuje; stop po +300 s. Ten sam save, ten sam spawn, ten sam spacer. Screenshot o 4:30. Log pełny stderr. Crash markers (koniec biegu, odrzucenie ramienia): `unhandled exception`, `0x887A0005`, `0x887A0007`, `0x80000003`, `int3`, `dstorage: retries used up`, `driver's errors`, `no free dynamic descriptor slots`. Gate: przyjmij jeśli p50 poprawia się ≥8% przy dopasowanych draws **i** p95 się nie pogorszy **i** brak nowej klasy crashy; promuj tylko po powtórce.

---

## 5. Twarda ściana 16 GB RAM i czego nie obiecujemy

**Twarda ściana 16 GB RAM:** Kelvaroq własny 36-minutowy test Spielzeit osiągnął **15,5 GB** RSS na 32 GB maszynie; ich build przed unified pamięcią zostawiał ~19 GB za sobą na sesję. Każda warstwa unified/shared-memory musi mapować cały ślad pamięci tytułu; na 16 GB z 34–63 GB pagefile to pagowanie commit. Nasze własne pomiary (COPY-LOOP-MATRIX §6): Fast3 ma 112–273 MB wolnego VRAM, 528 619 page + 546 guard faultów na klatkę, proces kernel 2 750 ms, 194 MB/frame streamingu z dysku. **16 GB RAM to nie 48 GB soldsawn — commit pressure jest realne i obniża fps.**

**Czego nie obiecujemy:**
- **30 fps to problem natywnego renderera, nie warstwy.** PERFORMANCE_BUDGET: "3D: 1–6 fps na tym laptopie; 30 fps wymaga natywnego portu/renderera i prawdopodobnie 16 GB VRAM / 32 GB RAM. To nie jest obietnica; to hipoteza do obalenia w M5."
- Najlepszy publiczny wynik 8 GB to **8–10 fps @1080p** (soldsawn, 48 GB RAM). Na 16 GB RAM realistycznie **3–6 fps**.
- GPU w soldsawn занято 50–58% — submit/copy thread to sufit, nie GPU. Port zero-copy atakuje to, ale nie usuwa suffitu całkowicie.

---

## 6. Czego NIE robić

| Czego | Dlaczego | Evidence |
|---|---|---|
| **Uruchamiać `ad3lre/victory-nvidia-8gb` z telemetry włączoną** | Telemetry ON domyślnie: raport per `victory run` do `https://rxnd.de/vi/v1`,包括 GPU/driver/VRAM, CPU, RAM, **BLAKE3 hash executables tytułu**, timeline fps, CPU/GPU load/temps, logi, **zrzuty ekranu**; sibling recorder proces przeżywa TDR lub hard kill | [F] SCENE-INTEL §6.1 |
| **Pobierać/binarne release'e CGBJ** | `codec-d/cool_fox` HTTP 404; żadna canonical CGBJ tree nie istnieje; mirrors to sibling branches z `f4b48ad`, nie łańcuch weryfikowalny; zipy mogą zawierać zmodyfikowane skrypty build | [F] SCENE-INTEL §3.2, §6.2-B |
| **Używać mirrory CGBJ poza trzema pinned siblingami** | Brak canonical tree; `kitotake`, `DoubleGhosty`, `miaohaixiang` to sibling branches, nie można udowodnić linii poza wspólnym `f4b48ad` | [F] [I] SCENE-INTEL §3.2 |
| **Używać `ztrx` ani jego re-uploadów** | Repo i konto 404; cached links/reuploads nie można wyśledzić; możliwe ponowne użycie nazwy | [F] SCENE-INTEL §6.2-B |
| **Uruchamiać jakiekolwiek "GTA VI PC installer"** | 355 domen fake-launcher, 27 000+ detekcji GTA VI-themed; ESET znalazło `gta6_installer.exe` z Vidar infostealer | [F] SCENE-INTEL §6.2-A |
| **Mieszać porty jako pakiet** | Każdy port za własnym switch; pakiet uniemożliwia przypisanie zysku i kill criteria | [R] change-impact |
| **Dotknąć `watch.rs`** | Użytkownik zmienia ten plik równolegle (P0 write-retry); konflikt | [R] kontekst zadania |

---

## 7. Jednoakapitowa rekomendacja

Użyć profilu 8 GB soldsawn jako referencji, nie CGBJ: publiczny, reprodukowalny sufite to **8–10 fps @1080p** na RTX 4060 Laptop z 48 GB RAM, osiągnięty przez **1080p + `DROP_MIPS=2`** (mieści świat w 6,6–7,0 GB VRAM), **Series X** (poprawne mesh głowy/skóry) i **async texture upload** (`HEAP_WORKER=1`); CGBJ 25 fps to 16 GB-VRAM, prywatny, nieniezależnie reprodukowany numer, który na tym samym laptopie mierzy **2,4–2,7 fps @1080p** — nie może wyznaczać celu. Najwyższy dźwig nowego kodu to **submission CGBJ**: Port 5 zero-copy CBV (~22 000 kopii buforów/frame), Port 1 in-place 32-bit heap i deskryptor-record deferral (280→124 ms), bo nasz własny E2b już pokazał, że VRAM nie jest ograniczającym gdy świat się mieści — submit/copy thread jest. Portować na drzewo pinowane po jednym switchu z `VICTORY_PORT_*`, trzymać profil residency 8 GB, mierzyć istniejącym protokołem; oczekiwać **3–6 fps na 16 GB RAM**, nie 8–10, bo soldsawn miał 48 GB a nasz commit pressure jest gorszy. Traktować 30 fps jako problem natywnego renderera; najlepszy publiczny wynik 8 GB warstwy to ~10 fps z GPU połowicznie bezczynnym.

---

## 8. Nieznane (unknowns)

| # | Nieznane | Wpływ | Notka |
|---|---|---|---|
| N1 | Rozmiar diffu (linie/pliki) commity c7fff5410a, c496640276, 5e0c9ab01e | Średni | Wymaga `git show --stat` na obcym repo przed portem; nie pobieram binarek |
| N2 | Dokładne pliki/funkcje Port 5/Port 1 w naszym drzewie | Średni | Wymaga `git grep` w `D:\git\VItoriaBr-opt` przed portem |
| N3 | Czy Port 5/Port 1 konfliktują z per-draw cache (`draw.rs`, commit 02f224f) | Wysoki | Oba modyfikują ścieżkę kopii buforów/stałych |
| N4 | Czy Port 5/Port 1 conflitują z watch.rs write-retry | Wysoki | Użytkownik zmienia watch.rs równolegle; nie dotykać |
| N5 | Realny zysk na 16 GB RAM (vs 48 GB soldsawn) | Wysoki | Brak pomiaru na 16 GB; szacunek 3–6 fps to wniosek, nie pomiar |

---

*Zero danych/bytes gry w repo. GPL-3.0. Nie commituję w `gta6-30fps` — zapisano tylko plik.*
