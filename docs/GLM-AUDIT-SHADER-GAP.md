# GLM — audyt niezależny + luka shader/pipeline (VItoriaBr-opt)

**Data:** 2026-11-26  
**Rola:** niezależny senior reverse-engineering / shader engineer  
**Status:** read-only — żadnych zmian w `D:\git\VItoriaBr-opt` (drzewo BRUDNE: watch.rs P0, draw.rs, descriptor/host.rs — inny agent), gra ZAMKNIĘTA (PID 21992 może być w użyciu przez agenta P0), żadnych danych gry w repo.  
**Worktree diagnostyczny:** `D:\git\VItoriaBr-shader-diag` (HEAD, czysty).  
**Licencja:** GPL-3.0.

> **Korekta 2026-11-26 (po sesji):** w worktree `shader-diag` nie ma flagi
> `--translate-only`. Diagnostyka używa `$env:VICTORY_TRANSLATE_ONLY='<hash>'`
> + `victory translate ... --pipelines`, a `pipeline/host.rs:607` loguje
> `VICTORY_DIAG compute_refused hash=... hr=... wave=... root_params=...
> samplers=... user_data_dwords=...`. Raporty 5 agentów, wcześniej opisane
> jako brakujące, istnieją teraz w `D:\git\gta6-30fps\docs` (commit 9df3612).

---

## 0. Zakres i źródła dowodów

| Element | Ścieżka / identyfikator | Uwaga |
|---|---|---|
| Warstwa VItoriaBr-opt | `D:\git\VItoriaBr-opt\` | Rust, GPL-3.0, `target\release\victory.exe` SHA-256 bf12251e… (czysty HEAD w worktree) |
| Worktree diag | `D:\git\VItoriaBr-shader-diag\` | HEAD d93d263, użyty do odczytu źródeł |
| Logi | `D:\Gry\VItoriaBr-data\logs\ab-d2*-stderr.log`, `safe-mem-stderr.log`, `fast2/3/4-stderr.log` | Read-only |
| Raport wejściowy | `D:\git\gta6-30fps\docs\GLM-AUDIT-SHADER-GAP.md` (poprzednia sesja) | Podstawowy audyt INT3/AV |
| CSV 실패 | `D:\git\gta6-30fps\docs\shader-failures.csv` | Ten dokument — wszystkie porażki shader/pipeline |

Dowody: wyłącznie logi stderr/stdout oraz źródła VItoriaBr-opt w worktree diag. Nie otwierano 120 MB exe gry (Ghidra niedostępny, gra zamknięta). REA użyte tylko na victory.exe (warstwa) w poprzedniej sesji — evidencia ev_a13c0070…, ev_020c0681…, ev_8b7c5e72….

---

## 1. Faza A — audyt raportów agentów

### 1.1 Tabela tez z raportów vs dowody

| Teza z raportu | Status | Dowód (log / źródło / plik:linia) |
|---|---|---|
| INT3 `image+0x5149aec` (mem vs file) | **Potwierdzone i rozstrzygnięte** | `0xCC` jest w pliku pod offsetem `0x5148eec` (RVA `0x5149aec − 0xC00`). Title-side assert z graceful fallback (`xor edi,edi; mov rax,rdi; ret` → caller `test rax,rax; je`). Nie patchować warstwy. |
| write-AV `victory.exe+0x66cfae` | **Potwierdzone** | `fast4-stderr.log:605-622`: `0xc0000005 (write 0x54311ac00: read-write)`. zlib-rs literal store w pamięci tytułu na wątku DirectStorage (dstorage.rs:511→918→inflate.rs:1901). VEH write branch nie ma retry — patrz P0 write-retry (inny agent, worktree P0). |
| Compute `02384a60fda6f2d0` odrzucany (0x80070057) | **Potwierdzone** | `ab-d2baseline:2870/2884`, `ab-d2D2-0:2870/2884`, `ab-d2D2-1:2601/2607`, `ab-d2D2-2r:2649/2653`, `ab-d2D2-3:2642/2658`, `ab-d2D2-3b:2666/2672`, `ab-d2D2-5:2672/2680`, `ab-d2D2-0r:2634/2641`, `fast2/3/4`: `host pipeline refused ... (0x80070057) shaders=[compute 02384a60fda6f2d0]` |
| Compute `369cbe906ea72764` odrzucany (0x80070057) | **Potwierdzone** | Wszystkie logi powyżej, identyczny wzorzec (translated, potem refused) |
| Compute `2cc4c197ee29e291`, `2da4beb386509b77`, `6b82bc7d22016cb5`, `5dc3b25986622949` odrzucane | **Potwierdzone** | Wszystkie logi powyżej — każdy hash ma parę `shader translated` → `host pipeline refused (0x80070057)` |
| `dropped N without a host pipeline: refused [...]` | **Potwierdzone** | `ab-d2baseline:8940-12011`, `ab-d2D2-0r:9030-14416`, `ab-d2D2-5:9560-17345`, `fast-stderr.log:8572-16999` — tysiące dropów/frame |
| `dropped ... a stage of the ray-tracing structure builder, which is off` | **Potwierdzone** | `ab-d2baseline:8939`, `fast-stderr.log:8572` — tysiące dropów/frame, builder wyłączony (`VICTORY_BVH_BUILDER=1` nie ustawione) |
| Texture residency (dedykowana metryka „resident”) | **Niepotwierdzone** | Brak linii z dosłownym słowem „residency” w żadnym logu. Są jedynie liczniki: `texture slots ... waiting` (128 waiting, safe-mem:1495), `host copies ... placed in title memory` (safe-mem:1518,2345,2708: 623 alive 919 MB, 540 placed). To dane residency, ale pod inną nazwą. |
| Copy-loop (pętla kopii) jako przyczyna | **Niepotwierdzone jako przyczyna** | `safe-mem:487/751/990/1492/1603/2327/2690`: `plaincopy VICTORY_COPY_PLAIN=1` — kopie maleją z czasem (38×11.3 MB → 21×0.4 MB), nie pętla zamknięta; `copystat refreshes 172-181 MB/klatkę` — churn, nie pętla. |
| 254 nieobsługiwane shadery (195 GS + 10 PS + 1 CS + 48 nieznane) | **Niepotwierdzone** | Brak `--list` z aktualnego runu; liczba 254 z `SHADER-PIPELINE.md` (poprzednia sesja E1), nie z logów fast/safe. |
| 4 compute PSO `0x80070057` = wave64 na NVIDIA | **Nieprawdopodobne / niezalogowane** | Logi pokazują `user_data=1..3, samplers=0..2` — brak `WaveSize` w rifi. Przyczyna `0x80070057` nie rozstrzygnięta (wave64 vs root signature vs DXIL features — nigdzie nie zalogowane). |
| GS = główny problem geometryczny (czarne/lecące trójkąty) | **Nieprawdopodobne** | `SHADER-PIPELINE.md:186-192`: 195 GS to wokselizacja/GI, nie główna geometria (9 282 MS + 14 248 VS/PS rysuje świat). Brak `first bind` dla GS w logach — nie można przypisać do widocznych artefaktów. |

### 1.2 Sprzeczności i luki w raportach

1. **Raporty agentów z briefu nie istnieją** pod ścieżkami `CRASH-TRIAGE-INT3-AV.md`, `TEXTURE-RESIDENCY-PORT.md`, `COPY-LOOP-MATRIX.md`, `SCENE-INTEL-2026-11-26.md` w `D:\git\gta6-30fps\docs\`. Istnieje tylko `GLM-AUDIT-SHADER-GAP.md` z poprzedniej sesji.
2. **Liczba 254 shaderów** nie jest potwierdzona żadnym `--list` z aktualnego runu — pochodzi z poprzedniej sesji (E1), nie z logów fast/safe.
3. **Twierdzenie o wave64** jako przyczynie `0x80070057` nie ma pokrycia w logach — brak słowa `WaveSize` w rifi żadnego z 6 compute hashy.
4. **Brak metryki texture residency** — twierdzenia o „texture residency port” nie mają dedykowanej linii w logach; dane są pod licznikami `host copies / placed in title memory`.

### 1.3 Ocena bezpieczeństwa (16 GB RAM / 8 GB VRAM)

| Rekomendacja | Bezpieczna? | Ryzyko TDR/AV |
|---|---|---|
| Obniżenie `TEXTURE_BUDGET_MB` do 2560 / `CARD_BUFFERS_MB` 256 | Tak | Niskie — mniej tekstur, mniej churnu; może brakować tekstur |
| `VICTORY_LIBRARY_MAP=0`, `LIBRARY_LOCK=1` | Tak | Niskie — wolniejsze ładowanie PSO, brak wyścigów mapowania |
| `HEAP_TEXTURES=0` (diagnostyka H1) | Tylko diagnostyka | Obraz niekompletny; nie do gry |
| `TdrDelay=10` | Nie | Maskuje hang, nie naprawia; wydłuża ewentualny TDR |
| Włączenie `QUEUE2`/`ASYNC_SUBMIT`/`JOIN_*` | Nie | Zwiększa zmienną bez korzyści (H5 odrzucona w poprzedniej sesji) |
| Naprawa shaderów (PS SGPR, CS mask, RT builder) | Tak po triage | Ryzyko regresji obrazu; wymaga testu regresyjnego (pixel compare) |

---

## 2. Faza B — luka shader/pipeline

### 2.1 Top failing shaderów (z logów + CSV)

Szczegółowe dane w `D:\git\gta6-30fps\docs\shader-failures.csv`.

| Hash | Stage | Powód (źródło kodu) | Wpływ na obraz | Fix | Test |
|---|---|---|---|---|---|
| `02384a60fda6f2d0` | compute | `host pipeline refused 0x80070057` (`pipeline/host.rs:585-606`, `CreateComputePipelineState` E_INVALIDARG) | Brak dispatchu — jeśli producent lighting/BVH/culling → złe dane lub brak efektu | Rozbić przyczynę: `VICTORY_D3D12_DEBUG=1` + debug layer; sprawdzić wave64, root signature, DXIL features | `translate --pipelines --translate-only 02384a60fda6f2d0`; pierwszy bind bez rifi; brak `dropped ... refused` |
| `369cbe906ea72764` | compute | idem | idem | idem | idem |
| `2cc4c197ee29e291` | compute | idem (user_data=3, samplers=1) | idem | idem | idem |
| `2da4beb386509b77` | compute | idem (user_data=2, samplers=2) | idem | idem | idem |
| `6b82bc7d22016cb5` | compute | idem (tylko ab-d2baseline/fast) | idem | idem | idem |
| `5dc3b25986622949` | compute | idem (tylko ab-d2baseline) | idem | idem | idem |
| (ray-tracing builder) | compute (builder) | `a stage of the ray-tracing structure builder, which is off` (`pipeline.rs:431-425`, `builder_off`) | Tysiące dropów/frame → czarne/brakujące tekstury, lecące trójkąty (BVH niezbudowane) | `VICTORY_BVH_BUILDER=1` tylko gdy CAŁY builder ma host pipeline (all-or-none); inaczej `VICTORY_BVH_HOLD=1` i zaakceptować drop z metryką | `dropped ... ray-tracing structure builder` = 0 (jeśli on) lub stały zalogowany drop (jeśli off); obraz bez nowych artefaktów |

### 2.2 Dlaczego programy nie dostają host pipeline (źródło victory-shader / victory-gpu)

Wszystkie lokalizacje zweryfikowane w worktree diag `D:\git\VItoriaBr-shader-diag\`.

| Luka | Plik:linia | Mechanizm |
|---|---|---|
| Brak etapu GS w translatorze | `crates/victory-shader/src/emit/mod.rs:315-331` | `translate_plain` filtruje etapy: tylko `Vs/Ps/Cs/Ms` (linia 325 `HwStage::Vs | HwStage::Ps | HwStage::Cs | HwStage::Ms`). Kontener z samym GS kończy się `"a container without a vertex, pixel, compute or mesh program"` |
| Odrzucenie etapu w host pipeline | `crates/victory-gpu/src/pipeline/host.rs:413-421` | `compute.is_none() && shaders.iter().any(|s| !matches!(s.stage, "vertex" \| "pixel" \| "mesh"))` → `refuse("only vertex, mesh, pixel and compute stages are translated")` |
| Brak modelu systemowych SGPR dla PS | `crates/victory-shader/src/io.rs:335-340` | `initialized_sgprs` jest `Some(cs.initialized_sgprs())` TYLKO dla `StageIo::Cs`; dla PS/VS jest `None` → każdy SGPR spoza `params`/`io.inputs` kończy się `Val::Missing("a hardware SGPR input")` |
| `MASK_ELSEWHERE` dla CS | `crates/victory-shader/src/emit/lower.rs:3272-3331` | Maska zawiera bity lane'ów poza aktywnym blokiem (`!self.x.st.active.contains(&lo) && !whole`) → `Err(MASK_ELSEWHERE)` w linii 3289. Retry `widen`/`with_local_waves` nie wystarczają dla 1 CS |
| RT builder off | `crates/victory-gpu/src/pipeline.rs:431-425` | `builder_runs()` wymaga `VICTORY_BVH_BUILDER=1` i że WSZystkie etapy buildera mają host pipeline (all-or-none). W przeciwnym razie `builder_off()` i tysiące dropów/frame |

### 2.3 Które dropy odpowiadają za czarne/lecące trójkąty i brakujące tekstury

1. **Ray-tracing structure builder** (tysiące dropów/frame, np. `ab-d2baseline:8939` `dropped 6640.0/frame ... which is off`) — **najprawdopodobniejszy główny winowajca** brakujących tekstur i artefaktów. Struktury BVH niezbudowane, więc ray-traced cienie/odbloka/proby zwracają śmieci lub zera. Wpływ na obraz: **wysoki (P0)** jeśli builder karmi widoczne passy.

2. **Compute `02384a60fda6f2d0` / `369cbe906ea72764` / `2cc4c197ee29e291` / `2da4beb386509b77`** (1-2 dropy/frame, stale we wszystkich logach) — prawdopodobnie producery danych (lighting/culling/BVH). Wpływ: zależne od `first bind`; bez niego nie wiadomo czy karmią widoczną geometrię. Klasyfikacja **P0/P1** do czasu `first bind`.

3. **GS `GS_VoxelizeGeneric` (195)** — wokselizacja/GI, nie główna geometria. Brak = uboższe odbicia/ambient, nie czarne trójkąty głównego świata. Klasyfikacja **P1** do czasu `first bind`.

---

## 3. Minimalne fixy P0/P1/P2

Każdy z testem regresyjnym i kryterium akceptacji. Brak obejść DRM/anti-tamper.

### P0 — Ray-tracing structure builder: decide on/off

**Problem:** Tysiące dropów/frame (`which is off`). Builder wymaga wszystkich etapów z host pipeline (all-or-none).

**Zmiana:**
- Sprawdzić czy builder karmi widoczne passy (czy `first bind` programów ray-tracing, np. `CS_IrradianceCache_ShadowTrace_WithFar`, pojawia się w świecie).
- Jeśli tak: włączyć `VICTORY_BVH_BUILDER=1` tylko gdy WSZYSTKIE etapy buildera mają host pipeline (`pipeline.rs:403-434`).
- Jeśli nie: ustawić `VICTORY_BVH_HOLD=1` i zaakceptować drop z metryką `DROPPED ray-tracing structure builder`, nie cichym fallbackiem.

**Pliki:** `crates/victory-gpu/src/pipeline.rs` (logika buildera), może nowy env switch.

**Kryterium akceptacji:** `dropped ... ray-tracing structure builder` = 0 (jeśli on) lub stały, zalogowany drop (jeśli off); brak nowych artefaktów w teście regresyjnym (pixel compare, ten sam save/kamera, 3 przebiegi).

### P0 — Triage 6 compute hashy: ustalić przyczynę `0x80070057`

**Problem:** Wszystkie 6 compute mają `shader translated` → `host pipeline refused (0x80070057)`, ale przyczyna niezalogowana (brak WaveSize w rifi).

**Zmiana:**
- Uruchomić `victory translate --pipelines --translate-only <hash>` z `VICTORY_D3D12_DEBUG=1` dla każdego z 6 hashy.
- Zalogować `hr`, `WaveSize` z DXIL, pierwszy błąd debug layer (`host.rs:585-606`, `host.log_messages()`).
- Rozbić: wave64 na NVIDIA vs root signature vs DXIL features (64-bit atomics, typed UAV).

**Pliki:** `crates/victory-gpu/src/pipeline/host.rs` (dodać logowanie przy refusal), `apps/victory/src/translate.rs` (translata only).

**Kryterium akceptacji:** Każdy z 6 hashy ma zidentyfikowaną przyczynę odrzucenia w logu.

### P1 — PS hardware SGPR input (10 PS)

**Problem:** 10 PS odrzucane przez `Val::Missing("a hardware SGPR input")` (`lower.rs:2450`) bo `initialized_sgprs=None` dla PS/VS (`io.rs:335-340`).

**Zmiana:**
- Sparsować `SPI_SHADER_PGM_RSRC2_PS.user_sgpr` (FSSM stage data) i wyznaczyć pierwszy systemowy SGPR.
- Dodać `Input::PsSystem` dla `{bc_optimize, prim_mask, lds_offset}`.
- Jeśli wszystkie użycia to `s_mov_b32 m0, sN` → `v_interp*` (lowering i tak nie używa M0, `emit/lower.rs:9392-9507`), podstawić 0/undef; jeśli inne — odmów z precyzyjnym reason.

**Pliki:** `crates/victory-shader/src/native.rs`, `io.rs`, `emit/lower.rs:2426-2451`.

**Kryterium akceptacji:** 10/10 PS translation + validate + PSO; pixel compare dla próbki; brak regresji liczby PS.

### P1 — CS lane mask elsewhere (1 CS)

**Problem:** 1 CS odrzucany przez `MASK_ELSEWHERE` (`lower.rs:3289`).

**Zmiana:**
- Dla grup ≤64 lane: wymienić pełną maskę 64-bit przez LDS (`groupshared`).
- Dla grup wielo-wave: liczba masek per wave + suma.
- Rozszerzyć `widen` o przypadek `s_not_b64 exec`.

**Pliki:** `crates/victory-shader/src/emit/lower.rs:3272-3331`, `emit/mod.rs` (widen).

**Kryterium akceptacji:** 1/1 CS translation + validate + PSO; wynik bufora zgodny z referencją; brak device loss.

### P2 — Offline PSO precompile (największa dźwignia na stutter)

**Problem:** Pierwszy świat kompiluje >1 200 PSO w klatce.

**Zmiana:** Nowe `victory pso --library <shaders.rpf> --out <cache>`: parsuje rekordy pipeline'ów, mapuje po HASH, odtwarza `GraphicsState`, wywołuje `HostPipeline::new`, zapisuje `ID3D12PipelineLibrary1`.

**Pliki:** nowy `apps/victory/src/pso.rs`, `crates/victory-gpu/src/pipeline/library.rs`.

**Kryterium akceptacji:** Drugi run: `made=0`, `loaded>0` dla prekompilowanego zbioru; brak `host pipeline refused`; pierwsza klatka świata bez 1 200 kompilacji.

---

## 4. 3 najważniejsze działania na najbliższe 24 h + 1 eksperyment bez restartu

### Działanie 1 — Triage 6 compute hashy (P0)

Uruchomić `victory translate --pipelines --translate-only <hash>` z `VICTORY_D3D12_DEBUG=1` dla każdego z 6 hashy. Zalogować `hr`, `WaveSize`, pierwszy błąd debug layer. Cel: zamienić nieznaną przyczynę na named reason.

### Działanie 2 — Ray-tracing builder: on/off (P0)

Sprawdzić czy `first bind` programów ray-tracing pojawia się w świecie. Jeśli tak — `VICTORY_BVH_BUILDER=1` (tylko jeśli wszystkie etapy mają host pipeline). Jeśli nie — `VICTORY_BVH_HOLD=1` z metryką dropu.

### Działanie 3 — Fix PS SGPR + CS mask (P1)

Wdrożyć fixy PS hardware SGPR (10/10) i CS lane mask (1/1). Test regresyjny pixel compare.

### Eksperyment bez restartu gry

W tym samym procesie/środowisku ustawić `VICTORY_VIEW_OWN_COPY=1` (lub `VICTORY_HEAP_TEXTURES=0` jako diagnostykę) i obserwować w stderr: `frame times`, `dropped without a host pipeline`, `texture slots ... waiting`, brak `device removed`/`0x887A0005/0007`. Nie wymaga restartu gry ani przebudowy.

---

## 5. Nieznane (unknowns) i ryzyka

| # | Nieznane / ryzyko | Wpływ | Notka |
|---|---|---|---|
| U1 | Przyczyna `0x80070057` dla 6 compute nie rozstrzygnięta (wave64 vs root signature vs DXIL) | Wysoki | Fix może być błędny bez `VICTORY_D3D12_DEBUG=1` |
| U2 | Brak `first bind` przypisującego compute shadery do widocznej geometrii | Wysoki | Nie wiadomo które są P0 vs P1/P2 |
| U3 | Brak dedykowanej metryki „texture residency” w logach | Średni | Dane residency są pod „host copies / placed in title memory”, nie pod etykietą „residency” |
| U4 | Fix GS (ES+GS → compute + mesh passthrough) to duża zmiana | Wysoki (regresja) | Wymaga testu regresyjnego pixel compare; XCL GPL-2.0 — tylko reimplementacja z opisu |
| U5 | 16 GB RAM / 8 GB VRAM — profil bezpieczny nieznany | Średni (TDR) | 7,7 GB VRAM w crashu to wzmacniacz, nie udowodniona przyczyna |
| U6 | VICTORY_SHADER_WHY nie istnieje w drzewie | Średni | Tylko `VICTORY_FAIL_DUMP` i `--list`; brak precyzyjnego logu SGPR |
| U7 | INT3 `image+0x5149aec` i write-AV `victory.exe+0x66cfae` — osobny obwód | Średni | Mogą być osobnym crash triage; nie mieszać z luką shader/pipeline |

---

## 6. Krótka odpowiedź końcowa

**Co potwierdziłem:** Wszystkie 6 compute shaderów (`02384a60fda6f2d0`, `369cbe906ea72764`, `2cc4c197ee29e291`, `2da4beb386509b77`, `6b82bc7d22016cb5`, `5dc3b25986622949`) są tłumaczone (`shader translated`) ale odrzucane przez host pipeline (`0x80070057` przy `CreateComputePipelineState`) we wszystkich logach. Ray-tracing builder jest wyłączony (`which is off`) z tysiącami dropów/frame. Źródłowo potwierdzone: `emit/mod.rs:315-331` filtruje tylko Vs/Ps/Cs/Ms; `host.rs:413-421` odrzuca nie-vertex/pixel/mesh/compute; `io.rs:335-340` ustawia `initialized_sgprs` tylko dla CS; `lower.rs:2450` → `Val::Missing("a hardware SGPR input")`; `lower.rs:3289` → `MASK_ELSEWHERE`.

**Co odrzuciłem:** Twierdzenie, że GS są główną przyczyną czarnych/lecących trójkątów (195 GS to wokselizacja/GI). Twierdzenie, że `0x80070057` to na pewno wave64 na NVIDIA (przyczyna niezalogowana). Twierdzenie o dedykowanej metryce „texture residency” (brak w logach).

**Największy blocker jakości:** Nieznana przyczyna `0x80070057` dla 6 compute shaderów + brak `first bind` przypisującego je do widocznej geometrii — bez tego nie da się wyznaczyć P0 vs P1/P2.

**Następny pojedynczy krok:** Uruchomić `victory translate --pipelines --translate-only 02384a60fda6f2d0` z `VICTORY_D3D12_DEBUG=1` i zebrać `hr`, `WaveSize`, pierwszy błąd debug layer — to rozstrzygnie czy to wave64, root signature czy DXIL features, i wyznaczy pierwszy realny P0 fix.

---

*Zero danych/bytes gry w repo. Nie commituję w `gta6-30fps` — zapisano tylko pliki. GPL-3.0.*
