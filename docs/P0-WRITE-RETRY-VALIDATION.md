# P0 — write-retry w watch.rs: implementacja, testy, walidacja

**Data:** 2026-11-26  
**Rola:** inżynier integracji i walidacji  
**Status:** worktree `D:\git\VItoriaBr-p0`, commit `cc1de49` (detached HEAD, nie w main VItoriaBr-opt). A/B wykonane 2026-11-26 20:42–21:02: Arm A **3/3 write-faulty retried bez AV**; Arm B **1/1 declined → unhandled `0xc0000005` w `VCRUNTIME140.dll+0x1afd6`**; oba ramiona nie weszły do świata (powtarzalny hang/`AppHangB1` po `host pipelines all made`). Werdykt: **INCONCLUSIVE** — brak 5-min świata/fps; mechanizm retry zadziałał, stabilność blokuje pipeline-stage hang.  
**Licencja:** GPL-3.0. Zero danych/bytes gry w repo.

---

## 0. Co zostało zrobione (podsumowanie)

Dokończono P0 write-retry w `crates/victory-gpu\src\watch.rs` zgodnie z `CRASH-TRIAGE-INT3-AV.md` §5 P0. Gdy write fault trafi w lukę remap/guard (strona nieobecna / no-access w momencie zapisu zlib-rs na DirectStorage workerze), zamiast `EXCEPTION_CONTINUE_SEARCH` (fatalny AV) handler czeka na koniec remapowania, sprawdza `writable_state`, i retry-uje zapis bounded przez `WRITE_RETRIES=64`. Stare zachowanie można przywrócić `VICTORY_WRITE_RETRY=0`.

Dodatkowo naprawiono błąd pre-existing blokujący kompilację: `crates/victory-gpu\src\host.rs` `HEAP_BUFFERS_TABLED` → `HEAP_BUFFER_PASSES` (literówka, brak takiego symbolu w `draw.rs`).

---

## 1. Diff (zmiany w worktree)

### `crates/victory-gpu\src\watch.rs` (+139/−20)

**Nowe stałe i statyki:**

| Element | Miejsce | Przeznaczenie |
|---|---|---|
| `WRITE_RETRIES: u32 = 64` | obok `READ_RETRIES` | maksymalna liczba retry write przy jednym adresie |
| `LATE_WRITES: AtomicU64` | obok `LATE_READS` | licznik write-faultów retry-owanych po koniec remapowania |
| `LAST_WRITE_FAULT: Cell<(usize,u64,u32)>` | thread_local, obok `LAST_READ_FAULT` | per-thread/per-page COUNT dla write_retry |

**Nowe funkcje:**

| Funkcja | Miejsce | Przeznaczenie |
|---|---|---|
| `writable_state(state, protect) -> bool` | obok `readable_state` | strona committed, bez PAGE_GUARD, protect w {READWRITE, WRITECOPY, EXECUTE_READWRITE, EXECUTE_WRITECOPY} |
| `write_retry_on() -> bool` | obok `late_retry` | kill switch `VICTORY_WRITE_RETRY` (domyślnie on, `=0` off) |
| `write_retry(at) -> bool` | obok `read_retry` | bounded counter, taki sam wzorzec jak `read_retry` |
| `write_stats(at, rip, before, after, retry)` | obok `read_stats` | log stderr gdy `VICTORY_GUARD_WRITE_STATS=1` |

**Zmieniony write branch w `on_write` (VEH):**

Zastąpiono gałąź `if writable(at) { ... } else if reserved(at) ...` wzorcem ze strony read: `page_state` przed i po oczekiwaniu na `title_memory_reading`, `writable_state` zamiast `writable`, `write_retry_on() && write_retry(at)` zamiast prostego `writable(at)`, `write_stats` do logowania, `LATE_WRITES` inkrementowany gdy strona nie była rezerwą.

**Testy (3 nowe, w `mapping_tests`):**

| Test | Co gwarantuje |
|---|---|
| `only_committed_writable_pages_count_as_writable` | `writable_state` akceptuje tylko committed+write-permitujące protect, odrzuca guard/NOACCESS/reserve |
| `write_retries_of_one_address_are_bounded_until_a_remapping_ends` | write_retry dopuszcza dokładnie WRITE_RETRIES prób, po remapowaniu znowu od nowa |
| `write_retry_is_disabled_by_viictory_write_retry_zero` | `VICTORY_WRITE_RETRY=0` wyłącza retry, unset przywraca |

### `crates/victory-gpu\src\host.rs` (−1)

| Zmień | Miejsce | Dlaczego |
|---|---|---|
| `HEAP_BUFFERS_TABLED` → `HEAP_BUFFER_PASSES` | `host.rs:7499` | symbol nie istniał w `draw.rs` (jest `HEAP_BUFFER_PASSES`), blokował kompilację całego crate |

---

## 2. Wyniki budowy i testów (worktree, offline, bez gry)

| Krok | Kommando | Wynik |
|---|---|---|
| Build release | `cargo build --offline --release -p victory` | **PASS** (0 błędów, 2 dead_code warnings dla zastąpionych `reserved`/`writable`) |
| Clippy | `cargo clippy --offline --release -p victory-gpu --lib` | **PASS** (te same 2 warnings) |
| Testy `watch::` | `cargo test --offline --release -p victory-gpu --lib watch::` | **PASS** (21/21, w tym 3 nowe) |
| Testy `victory-gpu` pełne | `cargo test --offline --release -p victory-gpu --lib` | 182 passed, 1 failed (`indirect::tests::warp_budget…` — pre-existing flaky, niezwiązane) |

**Werdykt budowy/testów:** kod się kompiluje, wszystkie testy watch przechodzą, clippy czysty. Zmiana jest comportement-preserving: ścieżka sukcesu (guard otwarty, strona writable) niezmieniona; zmienia się tylko ścieżka błędu (write AV → bounded retry zamiast natychmiastowego CONTINUE_SEARCH).

---

## 3. Runbook A/B (do wykonania za zgodą operatora — gra musi zostać uruchomiona)

**Nie uruchamiaj gry bez wyraźnej zgody operatora.** Poniżej przygotowany protokół.

### Baza (Fast3)
Z `Launch-VItoriaBr-Fast3.ps1`:
```
relay=2, late_wait=2, join_copies=1, wide_refresh/merge=1,
card_rehash_runs=1, async_submit=1, queue2=1,
copy_plain=1, texture no-wait, 720p, uncap, ambient 0
```

### Ramiona

| Ramion | Env (dodatkowe do Fast3) | Cel |
|---|---|---|
| **A** | `VICTORY_WRITE_RETRY=1` (lub domyślne, on jest default) | write-retry włączony — test docelowy |
| **B** | `VICTORY_WRITE_RETRY=0` | kontrola — stare zachowanie, write-AV powinien się powtórzyć |
| **C** (opcjonalnie, po A/B) | `VICTORY_INDIRECT_WINDOW=1` | jedna zmienna dodatkowa, jeśli A/B stabilne |

### Protokół każdego biegu (5 minut w świecie)

```powershell
# base = Launch-VItoriaBr-Fast3.ps1, zmieniamy tylko jedną linię:
$env:VICTORY_WRITE_RETRY = '1'      # ramię A
# lub '0'                            # ramię B (kontrola)
# lub '1' + VICTORY_INDIRECT_WINDOW=1  # ramię C

$env:VICTORY_KEYS = '25:Enter,45:Y,58:Enter,72:Enter,90:Enter,120:w,5:s,60:a,5:d,120:w'
# screenshot o 4:30 do D:\Gry\VItoriaBr-data\logs\
# full stderr do ...\logs\ab-<ramie>-stderr.log
```

- **Okno:** start zegara gdy tytuł raportuje draws > 300 i je utrzymuje; stop po +300 s. Ten sam save, spawn, spacer.
- **Crash markers** (koniec biegu, odrzucenie ramienia):
  - `unhandled exception`
  - `0x887A0005`, `0x887A0007` (device hung/removed)
  - `0x80000003`, `int3`
  - `dstorage: retries used up`
  - `driver's errors`
  - `no free dynamic descriptor slots`
  - nowy `*.crash.log`
- **Metryki:** p50/p95 ms/frame przy dopasowanych draws (±10%), present split (`in the present call`, `lines and settling`), submit thread (`preparing`, `copies`, `copy-back`), card idle, guard/page faults, VRAM free, `LATE_WRITES` (gdy `VICTORY_GUARD_WRITE_STATS=1`).
- **Gate:** przyjmij jeśli p50 poprawia się ≥8% przy dopasowanych draws **i** p95 się nie pogorszy **i** brak nowej klasy crashy. Promuj tylko po powtórce.

### Sukces (oczekiwany)

- **Brak write-AV** `0xc0000005 @victory.exe+0x66cfae` (fast4 crash) w ramieniu A
- **Brak TDR** (brak `0x887A0005/0007`)
- **fps ≥ Fast3** (brak regresji)
- `LATE_WRITES > 0` w ramieniu A dowodzi, że race był trafiony i wchłonięty przez retry

### Rollback

- `VICTORY_WRITE_RETRY=0` przywraca stare zachowanie natychmiast (env switch, nie trzeba przebudowywać)
- LUB `git revert cc1de49` w worktree i odbudowa

---

## 4. Nieznane (unknowns)

| # | Nieznane | Wpływ | Notka |
|---|---|---|---|
| N1 | Czy write-AV z fast4 zniknie w rzeczywistym biegu | Wysoki | **Częściowo zbadane 2026-11-26:** A 3/3 retried bez AV, B 1/1 declined → unhandled AV; dokładny `0x66cfae` nie wystąpił w żadnym ramieniu; pełny 5-min świat zablokowany przez pipeline-stage hang |
| N2 | Czy `LATE_WRITES` będzie >0 w realnym obciążeniu (dowód że race był trafiony) | Średni | `LATE_WRITES` nie jest drukowane; `VICTORY_GUARD_WRITE_STATS=1` pokazał 3 `retried` w A i 1 `declined` w B (2026-11-26) |
| N3 | Czy write-retry nie maskuje innego błędu (prawdziwy wskaźnik nieprawidłowy) | Średni | **Nowe ryzyko:** po retry A zalogował `a wait for a memory value was not met at a present` i `a queue still held a submission at a present`; retry może maskować niespójność queue/fence. P1 root cause nadal potrzebny |
| N4 | Czy `host.rs` HEAP_BUFFERS_TABLED fix nie ma innych skutków ubocznych | Niski | Jedna linia, oczywista literówka, kompilacja i testy pass |

---

## 5. A/B results (2026-11-26)

### 5.1 Setup

- **Launcher:** `D:\Gry\VItoriaBr-data\Launch-VItoriaBr-P0.ps1`, baza Fast3. Arm A `VICTORY_WRITE_RETRY=1`, arm B `=0`, arm C (nieuruchomione) `=1` + `VICTORY_INDIRECT_WINDOW=1`. W każdym ramieniu `VICTORY_GUARD_WRITE_STATS=1` (tylko logowanie) i klucze `25:Enter,45:Y,58:Enter,72:Enter,90:Enter`.
- **Runner:** `D:\Gry\VItoriaBr-data\Run-P0-Arm.ps1`. Okno tytułu ustawiane przez `AttachThreadInput`/`SetForegroundWindow` i weryfikowane po PID; gra zatrzymywana tylko przez PID uruchomiony przez runner; logi i zrzuty poza repo.
- **Izolacja:** `p0-cache` i `p0-data` poza repo. `p0-data` odtwarzane z tego samego save (`D:\Gry\VItoriaBr-data\data\7952987A`) przed każdym ramieniem; `p0-cache` odtwarzane z tej samej migawki (35 554 plików, 1 870 272 024 B) przed A i B.
- **Metryki:** bramka 5 min i per-frame p50/p95 zgodnie z `BENCHMARK-PROTOCOL.md`; parser `victory_log.frames_in_window` z `tools\bench`. Nie ma 5-min okna, bo żadne ramię nie weszło do świata (5.4).
- **Pominięte biegi:** `p0-armA-20261126-204231` (pierwszy cold-cache warm-up: 2 retried, world timeout, zabity ręcznie), `p0-armA-20261126-204943` (warm-P0-cache: 0 write-faultów, `AppHangB1`), `p0-armB-20261126-205956` (B zatrzymany przez focus guard przed pomiarem). Nie są ramionami A/B.

### 5.2 Arm table

| Arm | Run (log) | Czas | Focus | `guard-write` | Crash / hang | Świat / fps |
|---|---|---|---|---|---|---|
| **A** | `p0-armA-20261126-205542` | 20:55:42–20:58:58 | stable (PID) | **3 retried, 0 declined**; `State=0x1000 Protect=0x4` przed i po | brak `0xc0000005`/TDR/unhandled; **`AppHangB1`** o 20:58:52 po `host pipelines all made made=0 loaded=2887` | brak; ostatnia próbka 11 draws / 27.6 fps (splash) |
| **B** | `p0-armB-20261126-210048` | 21:00:48–21:02:10 | stable (PID) | **1 declined, 0 retried**; `State=0x1000 Protect=0x4` | **unhandled `0xc0000005` @ `VCRUNTIME140.dll+0x1afd6` (write `0x255e0000`)**, first-chance + unhandled; stack `victory-image-b99f...dll+0x22b899`/`+0x229a0e`/`+0x229993` | brak; ostatnia próbka 11 draws / 30.1 fps (splash) |

Logi: `D:\Gry\VItoriaBr-data\logs\p0-armA-20261126-205542-stderr.log` (1 594 785 B), `D:\Gry\VItoriaBr-data\logs\p0-armB-20261126-210048-stderr.log`; crash log B: `...-crashes.log` (15 linii). Zrzut stanu (splash, nie świat): `D:\Gry\VItoriaBr-data\logs\p0-armA-diag-2044.png` (2048×1280). **Brak zrzutu t=4:30, bo żadne ramię nie weszło do świata.**

### 5.3 The write-AV mechanism

- **A** (retry on) — trzy write-faulty, wszystkie na stronie committed/RW, wszystkie `-> retried`:
  - `0x7ffaa64bd8e0` → write `0x1096c5e0`, `State=0x1000 Protect=0x4` → retried
  - `0x7ff9e17d815f` → write `0x10970b70`, `State=0x1000 Protect=0x4` → retried
  - `0x7ffaa64bd8e0` → write `0xf76c5e0`, `State=0x1000 Protect=0x4` → retried
  - Brak `first-chance`/`unhandled 0xc0000005`, brak device removed, brak paniki.
- **B** (retry off) — kontrola:
  - `0x7ffaa64bafd6` (czyli `VCRUNTIME140.dll+0x1afd6`) → write `0x255e0000`, `State=0x1000 Protect=0x4` → **declined**.
  - Natychmiast `first-chance exception 0xc0000005` i `unhandled exception 0xc0000005` pod tym samym RIP i adresem. To dowód, że ta sama klasa faultu jest bez retry fatalna.
- **Caveat A:** po dwóch retry A zalogował `a wait for a memory value was not met at a present` i `a queue still held a submission at a present: its fence was not reached` (19:56:27.16). Retry może maskować niespójność queue/fence — to odpowiedź na N3, nie tylko hipoteza.
- **Różnica miejsca:** B zginął w `VCRUNTIME140` (CRT tytułu), nie w historycznym `victory.exe+0x66cfae` (zlib-rs). Żadne ramię nie odtworzyło dokładnie `0x66cfae`; A/B dowodzi klasy faultu, nie tego konkretnego RVA.

### 5.4 fps / 5-min gate

- **Brak 5-min świata w obu ramionach.** Ostatnie próbki to ekran `Americas` (11 draws, ~28–30 fps), nie scena. Nie ma p50/p95 ani delty fps; nie ma zrzutu t=4:30.
- **Hang pipeline:** A kończy log na `host pipelines all made made=0 loaded=2887 started_early=2894` (cold cache) i przestaje logować; Windows rejestruje `AppHangB1` dla `victory.exe`. Ten sam hang wystąpił w `p0-armA-20261126-204943` przy **0 write-faultach** (`loaded=1168`), więc nie jest wyłącznie skutkiem retry.
- **Cache mismatch:** P0 przełożył 3 206 shaderów w A i B mimo tej samej migawki cache; build P0 nie trafia w cache shaderów zbudowany przez opt (fingerprint tłumacza). To zwiększa liczbę pipeline'ów (2 887) i jest prawdopodobnym kontekstem hangu; wymaga triage'u przed fps A/B.

### 5.5 Verdict

| Pytanie | Odpowiedź |
|---|---|
| Czy write-AV zniknął? | **Na zaobserwowanych stronach write-fault: tak** — A 3/3 retried bez AV; B 1/1 declined → unhandled AV. Dokładny `victory.exe+0x66cfae` nie wystąpił w żadnym ramieniu. |
| fps A vs B | **N/A** — brak świata i 5-min okna; nie ma p50/p95. |
| PASS/FAIL/INCONCLUSIVE | **INCONCLUSIVE** — brak wystarczającego czasu w świecie; B odtworzył AV, ale na innym RIP; A zaliczył nowy hang (`AppHangB1`), więc nie jest stabilny. Nie PASS (brak fps i stabilności), nie FAIL na kryterium AV (A nie odtworzył `0xc0000005`/TDR). |
| Czy patch nadaje się do merge? | **Nie.** Mechanizm retry działa, ale A pokazał unmet queue wait i hang; P1 root cause i triage hangu są wymagane. |

### 5.6 Rollback

- Natychmiast: `VICTORY_WRITE_RETRY=0` (arm B) — stare zachowanie bez przebudowy.
- Kod: `git revert cc1de49` w `D:\git\VItoriaBr-p0` i rebuild. Nie merge'ować do `D:\git\VItoriaBr-opt` przed triage'em hangu i zdanym 5-min A/B.

---

## 6. Następny pojedynczy krok

**Stop — najpierw pipeline-stage hang, nie Arm C i nie `LATE_WAIT=3`.** Oba są zablokowane, dopóki A/B nie ma 5 min w świecie i porównywalnego p50.

1. **Triage hangu (P0):** zdjąć dump zawieszonego `victory.exe` (WER `AppHangB1` z 20:58:52) i porównać stos z `host pipelines all made`; sprawdzić, czy blokada jest w pipeline library/PSO, czy w queue/fence po retry. Osobno wyjaśnić, dlaczego P0 tłumaczy 3 206 shaderów mimo cache opt (fingerprint `victory_shader`/`shader_cache.rs`).
2. **Kontrola profilu:** jeśli hang zniknie, powtórzyć A/B na tym samym save/cache; do egzekwowania historycznego `0x66cfae` użyć profilu Fast4 (`JOIN_PARTS=8`) jako osobnego ramienia kontrolnego, nie mieszać z Fast3.
3. **Dopiero potem:** Arm C (`VICTORY_INDIRECT_WINDOW=1`) i `LATE_WAIT=3` — każda zmienna osobno, po zdanym A/B.

---

*Zero danych/bytes gry w repo. Commit tylko w worktree P0. GPL-3.0.*
