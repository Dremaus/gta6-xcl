# Pipeline shaderów — pokrycie, brakujące przypadki, plan offline

Data: 2026-11-25
Zakres: GTA VI Xbox Series **1.0.2.1**, VItoriaBr / fxceless-victory, RTX 4060 Laptop 8 GB,
cel 1280×720 / 30 fps.
Dokument jest analizą kodu i pomiarem z logów; **nie zawiera shaderów ani danych gry**.
Wszystkie ścieżki gier, cache i dumpy muszą zostać poza repozytorium
(`docs/asset-policy.md`).

---

## 0. Wnioski w skrócie

1. **254 to nie jest jedna rodzina.** 195 GS + 10 PS + 1 CS = **206**; brakuje wyjaśnienia
   **48** kontenerów. Wcześniejszy przebieg E1 miał dokładnie 206, więc 48 to albo nowe
   regresje, albo inna kategoria niż trzy nazwane. To pierwszy punkt do triage'u.
2. **195 GS to nie „dowolna geometria”, lecz rodzina `GS_VoxelizeGeneric`** (XCL zmierzył
   195 GS + 195 wariantów ES `VS_*`). To ścieżka wokselizacji/GI, nie główny rasteryzowany
   świat. Brak pipeline'u GS usuwa jednak cały draw/dispatch, więc jest to problem
   poprawności oświetlenia, nie tylko kosmetyka.
3. **10 PS z „hardware SGPR input” to najprawdopodobniej odczyt systemowego SGPR PS**
   (`{bc_optimize, prim_mask, lds_offset}`) albo SGPR nieinicjalizowanego na ścieżce,
   której translator nie modeluje. Compute ma już zerowanie powyżej
   `initialized_sgprs`; PS/VS nie mają odpowiednika.
4. **1 CS z „lane mask holding lanes elsewhere read as data”** to twarda odmowa
   `MASK_ELSEWHERE`: ballot obejmuje tylko lane'y, które docierają do bloku, a maska ma
   bity lane'ów „gdzie indziej”. Retry `widen` / `with_local_waves` ratują większość
   przypadków; ten jeden wymaga wymiany maski przez LDS albo natywnego wave64.
5. **GS nie da się naprawić jednym `match` w translatorze.** Konsolowy GS to stary
   on-chip ES+GS: ES pisze do LDS/ringu, `s_setpc_b64` przekazuje sterowanie do GS,
   GS czyta offsety wierzchołków, pisze verty do ringu i wysyła `s_sendmsg`
   (`GS_ALLOC_REQ`/emit/cut/done). To nie jest „jeden primitive na invocation”, więc
   bezpośredni DXIL GS nie jest 1:1. Sprawdzona droga (XCL) to **ES+GS → jeden compute
   `[WaveSize(64)]` → rekordy → mesh passthrough**.
6. **PSO offline to nadal największa dźwignia na stutter**, ale nie na 30 fps.
   25 471 rekordów graphics + 2 693 compute jest w bibliotece pipeline'ów w `shaders.rpf`;
   można je odtworzyć bez zgadywania stanu. To eliminuje kompilacje w klatce, nie
   koszt CPU per draw.
7. **Kolejność napraw:** triage 254/48 i 4 compute PSO → GS (CS+MS) → PS SGPR →
   lane-mask CS → offline PSO. Reszta (48) może zmienić priorytety, dlatego jest pierwsza.

---

## 1. Pokrycie — co jest zmierzone

### 1.1 Pełny pakiet

| Miara | Wartość | Źródło |
|---|---:|---|
| Kontenery DXBC w `shaders.rpf` | **26 503** | Leonida `docs/shader_library.md`, XCL `HANDOFF.md` |
| Payloady XBCH/FSSM (tag 0x0D) | **26 698** | 195 kontenerów VS ma dwa payloady (ES + VS) |
| VS / PS / CS / MS / GS | 2 236 / 12 101 / 2 689 / 9 282 / **195** | Leonida, stage index |
| Programy GS + ES | **195 + 195 = 390** | XCL: 195 `GS_VoxelizeGeneric` + 195 ES `VS_*` |
| Kontenery VS z dwoma payloadami | **195** | Leonida: ES variant + VS copy |

### 1.2 `victory translate --validate --pipelines` (VItoriaBr README, RTX 5060 Ti)

| Etap | DXIL emitted | `dxil.dll` | PSO | Uwaga |
|---|---:|---:|---:|---|
| Vertex + Pixel | 14 248 / 14 259 | 14 248 | 14 248 | 11 programów bez emisji |
| Mesh | 8 765 / 8 765 | 8 694 | 8 765 | 71 walidacji mniej niż emisji |
| Compute | 2 728 / 2 734 | 2 728 | **2 331** | 397 PSO odmówione (wave64 na NVIDIA) |
| **Razem** | **25 741 / 25 758 (99,9%)** | **25 670** | **25 344 (98,5%)** | bez GS |

GS nie występuje w tej tabeli, bo `translate_plain` wybiera tylko `Vs/Ps/Cs/Ms`
(`crates/victory-shader/src/emit/mod.rs:315-331`). 195 GS jest poza tabelą
etapów, a nie „przetłumaczone inaczej”.

### 1.3 `victory warm` (VItoriaBr / fxceless)

| Miara | Wartość |
|---|---:|
| Kontenery znalezione przez skan plików | **25 889** |
| Przetłumaczone (w tym cache hits) | **25 635** |
| Nie tłumaczą się | **254** |
| Czas fxceless | 3,8 min |

25 889 ≠ 26 503: skan `sources()` widzi surowe DXBC i rekordy SGD5, a nie każdy
kontener z archiwum RPF. **To osobna luka ingestu** — 614 kontenerów nie jest w ogóle
rozważanych przez `warm`.

### 1.4 Rozkład 254

| Kategoria | Liczba | Jak powstaje |
|---|---:|---|
| GS (`GS_VoxelizeGeneric`, `GS_*`) | **195** | brak etapu GS w `translate_plain`; `io::raise` odmawia |
| PS „hardware SGPR input” | **10** | `lower::inputs` nie ma wartości dla SGPR |
| CS „lane mask holding lanes elsewhere read as data” | **1** | `MASK_ELSEWHERE` w `mask_dword` |
| **Niesklasyfikowane** | **48** | **do triage'u** — patrz §2.4 |
| **Razem** | **254** | 206 nazwane + 48 |

To nie jest kosmetyczna różnica: 48 może zawierać compute'owe producery danych,
które są ważniejsze niż 195 GS.

---

## 2. Dlaczego te shadery nie tłumaczą się

### 2.1 195 GS — `GS_VoxelizeGeneric`

#### Co to jest

Konsolowy GS w tym tytule to **stary, on-chip GS**, nie „nowoczesny” GS per primitive:

- VS działa jako **ES** (export shader) i pisze wyjścia do LDS/off-chip parameter cache.
- ES kończy się `s_setpc_b64` do kodu GS (handover w tym samym wave).
- GS dostaje w `v0/v1` offsety wierzchołków (16-bit packed), w `s3` liczbę
  vertices | primitives << 8, w `s2` obszar wyjściowy za 64 elementami ES.
- GS czyta wierzchołki z ringu (64 B/vertex). XCL session 4 opisał base jako
  `s2 + ([s8+0xB8] << 8)`, a session 5 poprawiła to na **najniższy adres
  zapisany przez wątek** (niezależny od `[s8+0xB8]`). Traktuj to jako
  assumption do sprawdzenia na parze z paczki.
- `s_sendmsg` (alloc/emit/cut/done; w NGG `GS_ALLOC_REQ` z
  m0 = vertices | primitives << 12), `exp prim`.
- Wszystkie 195 GS są **wave64**; wszystkie zawierają `v_mbcnt_hi` przy liczeniu
  bazy GSVS.

To opisuje XCL (`HANDOFF.md`, sekcja „GS emulation”) na podstawie 195 par
`GS_VoxelizeGeneric` + `VS_*`. Leonida potwierdza 195 GS i 100% tłumaczeń do SPIR-V,
ale nie twierdzi, że są one uruchamiane w pipeline.

#### Gdzie VItoriaBr odmawia

1. **Wybór programu** — `translate_plain` filtruje etapy:
   `crates/victory-shader/src/emit/mod.rs:315-331`.
   Kontener, który ma tylko GS, kończy się
   `"a container without a vertex, pixel, compute or mesh program"`.
2. **I/O etapu** — `io::raise` ma gałęzie tylko dla `Ps/Vs/Cs/Ms`;
   `_ => Err("I/O of this stage")`:
   `crates/victory-shader/src/io.rs:197-306` (odmowa w linii 305).
3. **Dane etapu** — `native_programs` czyta rekordy FSSM dla `Ls/Hs/Es/Gs/Vs/Ps/Ms/Cs`,
   ale dla `Gs`/`Es` ustawia `StageIo::None`:
   `crates/victory-shader/src/native.rs:578-591`.
   Nie ma parsera `VGT_GS_OUT_PRIM_TYPE`, `VGT_GS_INSTANCE_CNT`, max vertices,
   ani wejść/wyjść GS.
4. **IR** — `s_setpc_b64` jest traktowane jako `Exit::Indirect`:
   `crates/victory-shader/src/ir.rs:68-80`, a lower odmawia
   `"an indirect jump"`: `crates/victory-shader/src/emit/lower.rs:10589`.
   To dokładnie handover ES → GS.
5. **Emisja** — `GS_ALLOC_REQ` i `s_sendmsg` są obsługiwane tylko dla mesh:
   `crates/victory-shader/src/emit/lower.rs:129-130`,
   `crates/victory-shader/src/emit/lower.rs:1549-1550`,
   `crates/victory-shader/src/emit/lower.rs:4317+` (`mesh_prologue`, `exp prim`).
   Nie ma GSVS ringu, `exp prim` dla GS ani stream outputu.
6. **Pipeline** — `HostPipeline::new` odrzuca każdy etap spoza
   `vertex/pixel/mesh`:
   
   ```rust
   // crates/victory-gpu/src/pipeline/host.rs:413-421
   if compute.is_none()
       && shaders.iter().any(|s| !matches!(s.stage, "vertex" | "pixel" | "mesh"))
   {
       return refuse("only vertex, mesh, pixel and compute stages are translated", shaders);
   }
   ```
   
   `pipeline.rs:12-16` mówi wprost: tylko VS+PS i compute dostają host pipeline;
   geometry/tessellation/mesh zachowują kontener. Komentarz jest nieaktualny dla
   mesh (mesh ma osobny `mesh_pipeline`), ale aktualny dla GS.
7. **Jedyny syntetyczny GS** — `emit/rect.rs:43-64` tworzy DXIL GS tylko dla
   list prostokątów (topologia 19), żeby dorysować czwarty wierzchołek.
   To nie jest translator konsolowego GS.

#### Dlaczego nie „po prostu DXIL GS”

D3D12 nadal wspiera GS (SM 5+), więc host nie jest przeszkodą. Problemem jest
**model wykonania**:

- DXIL GS dostaje jeden primitive na invocation i `TriangleStream`; konsolowy GS
  dostaje **grupę do 21 trójkątów / 63 wierzchołków ES** i współdzieli LDS/ring.
- Konsolowy ES i GS to dwa etapy sprzętowe w jednym wave; DXIL rozdziela VS i GS
  na osobne stage'e z innym ABI (input array, `SV_PrimitiveID`, stream output).
- `s_setpc_b64` i `s_sendmsg` nie mają odpowiednika w DXIL GS.
- GS stage data nie jest sparsowane, więc nie ma nawet wejściowej sygnatury.

Dla 195 **batchowych wokselizatorów** właściwa droga to nie DXIL GS, lecz
**ES+GS → compute → mesh passthrough** (patrz §3.8). Dla pojedynczego,
per-prymitywowego GS (gdyby taki był) bezpośredni DXIL GS byłby prostszy.

#### Wpływ na poprawność

VItoriaBr tłumaczy kopię VS z 195 kontenerów VS, ale **nie tłumaczy wariantu ES**
ani żadnego z 195 GS. W praktyce 195 GS + 195 ES (390 programów) jest poza
host pipeline'em; XCL ma 390/390.

- To **nie jest główna geometria świata** (9 282 MS + 14 248 VS/PS ją rysują).
- To wokselizacja/GI: brak = uboższe odbicia/ambient, czasem ciemniejsze lub
  płaskie powierzchnie; istniejący fallback ambient (`VICTORY_AMBIENT`) to maskuje.
- Każdy pipeline z GS jest jednak odrzucany w całości, więc jeśli ten sam GS
  obsługuje też inne efekty (cienie cząstek, dekale), draw znika.
- **Klasyfikacja: P1**, dopóki `first bind` / `DROPPED` nie pokaże, że któryś GS
  karmi widoczną geometrię. Wtedy P0.

### 2.2 10 PS — „a hardware SGPR input”

#### Co znaczy ten komunikat

`lower::inputs` mapuje każdy odczytany rejestr na wartość:

- `Reg::S(n)` może być parametrem root signature (`self.params`),
- wejściem systemowym z `io.inputs`,
- albo — dla compute — zerem powyżej `initialized_sgprs`.

Dla PS/VS `initialized_sgprs` jest `None` (`io.rs:335-340` ustawia je tylko dla CS),
więc każdy SGPR, którego nie ma w `params` ani w `io.inputs`, kończy się:

```rust
// crates/victory-shader/src/emit/lower.rs:2436-2451
Reg::S(n) => match io_inputs.get(&v) {
    Some(&input) => self.input(input),
    None if n <= 105 && self.x.io.initialized_sgprs.is_some_and(|k| n >= k) => {
        Val::I32(self.s.m.i32(0))
    }
    None if n >= crate::ir::PARKED => Val::I32(self.s.m.i32(0)),
    None => Val::Missing("a hardware SGPR input"),
},
```

Czyli: **SGPR, który hardware inicjalizuje, a translator go nie modeluje** (albo
SGPR, którego poprawny program nie powinien czytać, a czyta go tylko na ścieżce
pozornie niemożliwej).

#### Które SGPR inicjalizuje PS na RDNA2

Wg RDNA2 ISA §3.12.2, po user SGPR-ach (`SPI_SHADER_PGM_RSRC2_PS.user_sgpr`)
sprzęt dokłada:

1. `{bc_optimize, prim_mask[14:0], lds_offset[15:0]}` — **zawsze**,
2. `{ps_wave_id[9:0], ps_wave_index[2:0]}` — jeśli `wave_cnt_en`,
3. POPS collision wave ID — jeśli włączone,
4. `{16'b0, Intra-Wave Quad Overlap[15:0]}` — jeśli włączone,
5. Provoking Vertex — jeśli `load_provoking_vtx`,
6. Scratch offset — jeśli `scratch_en`.

VItoriaBr nie parsuje `SPI_SHADER_PGM_RSRC2_PS.user_sgpr` i nie modeluje
`prim_mask/lds_offset`. Typowy przypadek to:

```asm
s_mov_b32 m0, s2          ; s2 = {bc_optimize, prim_mask, lds_offset}
v_interp_p1_f32 v0, v0, attr0.x
v_interp_p2_f32 v0, v1, attr0.x
```

`v_interp` w IR czyta M0 (`ir.rs:1336-1344`), ale lowering `interp`
(`emit/lower.rs:9392-9507`) **nie używa M0** — interpolację bierze z tabeli
atrybutów i barycentryków. Odczyt `s2` jest więc tylko po to, by ustawić M0;
dla translatora jest zbędny. To czyni przypadek naprawialnym bez modelowania
całego `prim_mask`.

#### Co może pójść źle przy „zeruj”

- Jeśli PS czyta `prim_mask` **jako dane** (np. ręczna interpolacja LDS,
  pull-model), zero da złe piksele.
- Jeśli PS czyta niezainicjalizowany SGPR tylko na ścieżce, która nie powinna go
  czytać (artefakt CFG), zero jest poprawne — tak jak w compute (#432).
- Bez liczby user SGPR-ów nie wiadomo, gdzie kończy się user data, a zaczyna
  systemowy `prim_mask`.

Dlatego potrzebny jest **precyzyjny log brakującego numeru SGPR** i rozdzielenie:
„tylko M0 dla `v_interp`” vs „inne użycie”.

#### Wpływ

10 PS to prawdopodobnie warianty materiałów/efektów. Jeśli któryś jest
full-screen/postprocessing, brak = widoczny artefakt lub czarny pass; jeśli to
wariant ubrania, różnica jest lokalna. **P1** do czasu `first bind`.

### 2.3 1 CS — „a lane mask holding lanes elsewhere read as data”

To nie jest zwykłe „lane mask read as data” (`LANE_MASK`), które ma retry.
To `MASK_ELSEWHERE`:

```rust
// crates/victory-shader/src/emit/lower.rs:354-358
pub(super) const LANE_MASK: Why = "a lane mask read as data";
pub(super) const MASK_ELSEWHERE: Why = "a lane mask holding lanes elsewhere read as data";
```

`mask_dword` (`lower.rs:3272-3331`) buduje maskę jako ballot lane'ów, które
**docierają do bloku**, w którym maska jest zapisana. To jest poprawne tylko
wtedy, gdy zbiór lane'ów maski jest dokładnie zbiorem aktywnych lane'ów:

- `s_not_b64 s[0:1], exec` — maska lane'ów **nieaktywnych**; ballot aktywnych
  nigdy nie odtworzy jedynek w lane'ach, których nie ma.
- `s_andn2_b64` z EXEC, uzupełnienia, maski z drugiej połowy wave64.

`st.active` (structurisation) śledzi maski, które są dokładnie aktywne.
Jeśli maska nie jest w `active`, a blok nie jest „whole” (wszystkie lane'y
wykonują), `mask_dword` zwraca `MASK_ELSEWHERE` (`lower.rs:3285-3289`).
Retry:

- `widen` (`emit/mod.rs:511-609`) próbuje rozszerzyć per-lane branche wokół
  użycia, żeby wszystkie lane'y przeszły przez blok,
- `with_local_waves` (`lower.rs:1047-1068`) traktuje każdą połowę hosta jako
  osobny wave,
- `with_local_waves_any` (`lower.rs:1033-1045`) to ostatnia, przybliżona forma.

Ten jeden CS nadal nie przechodzi, czyli ma grupę z więcej niż jednym wave,
`Exit::Indirect`, albo maskę, której wartość jest potrzebna do zbudowania
własnego bitu („a lane mask whose lanes depend on its own value”).

#### Wpływ

Maska steruje zwykle:

- licznikiem/kompakcją slotów (atomic add, prefix),
- predykatem cullingu lub wyborem deskryptora,
- sumą/redukcją.

Błędna maska = **złe dane**, nie tylko zły piksel. Jeśli ten CS jest producerem
dla drawów (culling, lighting, BVH), to **P0**. Jeśli to opcjonalny efekt —
P2. Jeden shader, więc warto go zidentyfikować i naprawić punktowo.

### 2.4 48 niesklasyfikowanych

Arytmetyka z briefu:

```
195 GS + 10 PS + 1 CS = 206
254 - 206 = 48
```

E1 (`EXPERIMENTS-2026-11-25.md`) miał **dokładnie 206** nieobsługiwanych.
Najprawdopodobniejsze wyjaśnienia:

1. Nowy build / inne `VICTORY_*` (np. `VICTORY_HOST_WAVE`, `VICTORY_SHADER_OPT`,
   `VICTORY_WAVE_LOCAL`) zmienił wynik dla 48 shaderów.
2. 48 to inne reason'y translatora (np. `a select on an untracked mask`,
   `an address in an SGPR that is no root parameter`, `image_gather4_l`,
   `a structured buffer of unknown stride`) — w briefie ich nie nazwano.
3. 48 to kontenery, które w E1 były cache hitami, a teraz zostały
   przetłumaczone od nowa i failują (zmiana klucza cache / źródła).

**To trzeba zmierzyć, nie zgadywać.** `victory warm --list` wypisuje każdy
failure; `--dumps` + `tools/shader/analyze_unsupported.py` grupuje je.
Dopóki 48 nie ma nazw, każda lista priorytetów jest niepełna.

### 2.5 Compute PSO `0x80070057` — to nie translation failure

Cztery hashe z briefu:

- `02384a60fda6f2d0`
- `2cc4c197ee29e291`
- `6b82bc7d22016cb5`
- `5dc3b25986622949`

Translator je emituje, ale `CreateComputePipelineState` zwraca `E_INVALIDARG`
(`0x80070057`). Kod:

- root signature: `crates/victory-gpu/src/pipeline/host.rs:1000-1045`,
- compute PSO: `crates/victory-gpu/src/pipeline/host.rs:585-606`,
- log debug layer: `host.log_messages()` w linii 604.

Najczęstsza znana przyczyna w tym projekcie to **`WaveSize(64)` na NVIDIA**
(397 compute PSO odmówionych w README). Jeśli te cztery nie są wave64, sprawdź:

- static samplery / root signature (limit 64 DWORD-ów, 2 032 samplerów),
- descriptor table ranges i `CBV_SRV_UAV_HEAP_DIRECTLY_INDEXED`,
- `SV_DispatchThreadID` / `numthreads` > 1024,
- DXIL features (np. 64-bit atomics, typed UAV) nieobsługiwane przez sterownik.

Wpływ: jeśli te dispatche produkują lighting/BVH/culling, brak = złe dane lub
brak efektu. **P0/P1 zależnie od `first bind`.**

### 2.6 Correctness-critical vs cosmetic

| Przypadek | Liczba | Co znika | Klasyfikacja |
|---|---:|---|---|
| CS lane mask | 1 | dane produkowane dla drawów (culling/lighting/BVH), jeśli to producer | **P0**; P2 tylko jeśli efekt opcjonalny |
| Compute PSO `0x80070057` | 4 | dispatch, który może karmić lighting/BVH | **P0/P1** zależnie od `first bind` |
| 48 niesklasyfikowanych | 48 | nieznane; mogą być producery danych | **P0 triage** |
| GS `GS_VoxelizeGeneric` | 195 | wokselizacja/GI, nie główna geometria | **P1**; P0 jeśli któryś rysuje widoczną geometrię |
| PS „hardware SGPR” | 10 | materiał/postprocessing; zależy od użycia | **P1**; P0 jeśli full-screen/post |
| GS/ES nieużywane w danym save | ? | nic w tym save | **P2** — zmierzyć `first bind` |

Bez `first bind` / `DROPPED` z runu nie da się uczciwie powiedzieć, które z 48
są „kosmetyczne”. Dlatego triage jest przed implementacją.

---

## 3. Docelowy pipeline offline

Cel: **żadnej translacji ani kompilacji PSO w klatce**. Wejście: własna kopia gry.
Wyjście: cache poza repo, ważny dla danego tłumacza, backendu i adaptera.

```
shaders.rpf / *.cdxil
  └─ DXBC (Container::parse)
       └─ DXIL part → XDAT → XBCH → FSSM
            ├─ PAL stage descriptors (0x100 + 0x88*k)
            ├─ FSSM slot records (Ls/Hs/Es/Gs/Vs/Ps/Ms/Cs)
            └─ code + root layout + used resources
                 └─ gfx10::decode → ir::build → structure::structure
                      → resource::track → io::raise → spill::build
                           ├─ DXIL (SM 6.6)  → dxil.dll → D3D12 PSO
                           └─ SPIR-V          → spirv-val → vkCreate*Pipelines
```

### 3.1 Ingestion — czego dziś brakuje

- `victory warm` znajduje 25 889 z 26 503 kontenerów. Rozszerz `sources()` /
  dodaj carver RPF9, żeby **każdy** kontener z `shaders.rpf` trafił do cache.
  Wzorzec: Leonida `tools/shader_carve.py` (GPL-3.0, referencja).
- `Container::bytes_of` (`crates/victory-shader/src/dxbc.rs:109-116`) musi ciąć
  dokładnie tyle, ile gra podaje w `Create*PipelineState`; inaczej klucz cache
  nie trafi.
- `native_programs` (`native.rs:412-433`) skleja **wszystkie** payloady 0x0D.
  Dla 195 kontenerów VS oznacza to ES + VS; publiczny `translate` wybiera VS.
  ES jest nadal nieprzetłumaczony — to ukryta luka, nie dodatkowy failure.
- Dla GS kontener ma PAL wpis GS + „VS copy”; nie traktuj tego copy jako
  pełnego VS do pipeline'u bez sprawdzenia sygnatur.

### 3.2 Decode/lift — co dodać

Istniejący łańcuch:

```rust
// crates/victory-shader/src/emit/mod.rs:315-340
let native = native_programs(dxil)?.find(stage in Vs|Ps|Cs|Ms)?;
let p = spill::build(&native)?;
let st = structure::structure(&p);
let res = resource::track(&p, &native.layout, native.stage, st.as_ok())?;
let io = io::raise(&p, &native)?;
emit(&c, &native, &p, &st?, &io, &res)
```

Dodać:

1. **`HwStage::Es` / `HwStage::Gs`** do `StageIo` i `io::raise`.
2. **GS stage data**: `VGT_GS_OUT_PRIM_TYPE`, `VGT_GS_INSTANCE_CNT`,
   max vertices/primitives, wejścia ES (OSG1) i wyjścia GS.
3. **`s_setpc_b64`**: rozwiąż cel, jeśli jest stały (trampolina);
   w przeciwnym razie zbuduj wspólny CFG ES+GS z flagą etapu.
4. **`s_sendmsg`**: alloc/emit/cut/done; w NGG `GS_ALLOC_REQ`
   (m0 = vertices | primitives << 12); dla GS strip → trójkąty
   (parzyste/nieparzyste zamienione).
5. **GSVS ring**: 64 B/vertex; base według XCL session 5 to **najniższy adres
   zapisany przez wątek** (session 4 podawał `s2 + ([s8+0xB8] << 8)` — to jest
   assumption do sprawdzenia). LDS jako `groupshared` w compute.
6. **`exp prim`** dla GS: indeksy trójkątów, bit 31 = cull; dla mesh już jest
   (`lower.rs:10431+`).

### 3.3 Emisja DXIL — kształt etapów

| Etap | Host | Uwagi |
|---|---|---|
| VS | `D3D12_SHADER_VISIBILITY_VERTEX` | input layout z tytułu; vertex fetch often in shader |
| PS | `..._PIXEL` | barycentryki, interpolacja, export patch |
| MS | `..._MESH` | bez input layoutu; `DispatchMesh(x,1,1)`; tylko trójkąty |
| CS | compute PSO | `[numthreads]` konsoli; `WaveSize` tylko gdy potrzebne |
| GS | `..._GEOMETRY` (jeśli bezpośredni) **albo** CS+MS | patrz §3.8 |
| ES | część CS+MS | nie jest osobnym etapem hosta |

Dla bezpośredniego GS (gdyby był per-prymitywowy):

```hlsl
[maxvertexcount(N)]
void main(triangle In v[3], uint prim : SV_PrimitiveID,
          inout TriangleStream<Out> stream) { ... }
```

Dla 195 batchowych wokselizatorów to nie zadziała 1:1 — patrz §3.8.

### 3.4 Walidacja

1. **DXIL**: `dxil.dll` (`IDxcValidator`) — `emit/validator.rs:120-213`;
   `victory translate --validate` (`apps/victory/src/translate.rs:249-257`,
   `651-687`). `VICTORY_DXIL` wskazuje DLL.
2. **PSO**: `D3D12CreateDevice` + `CreateGraphicsPipelineState` /
   `CreateComputePipelineState` z **prawdziwym** stanem i parą shaderów.
   Obecne `--pipelines` używa stub VS/PS (`translate.rs:634-649`), więc nie
   sprawdza linkowania sygnatur; dla par użyj `VICTORY_PAIRS=vs+ps` albo
   nowego manifestu.
3. **SPIR-V** (ścieżka Leonida): `spirv-val --target-env vulkan1.3`,
   potem `vkCreateGraphicsPipelines` / `vkCreateComputePipelines`
   (`vk_pipeline_check`). To sprawdza to, czego `spirv-val` nie wie:
   limity urządzenia, subgroup size, descriptor layout.
4. **Semantyka**: nie da się zwalidować całego korpusu bez referencji.
   minimum: testy GPU per instrukcja (Leonida/XCL mają takie harnessy) +
   porównanie pikseli dla reprezentatywnych par VS/PS/GS.

### 3.5 PSO precompile — źródło prawdy

W `shaders.rpf` jest biblioteka pipeline'ów (Leonida `docs/shader_library.md`):

- **25 471** rekordów graphics, **2 693** compute,
- 54 576 blobów, 21 522 programów,
- graphics: VS+PS 13 383, MS+PS 10 726, MS only 1 336, VS only 24, slot6 2,
- rekord graphics ma hash, state blob (388–472 B), pipeline blob (input layout)
  i 7 par `(program, stage blob)`.

Dwie drogi:

**A. Replay biblioteki (docelowa).** Sparsuj rekordy, zmapuj programy na
kontenery po `HASH`, odtwórz `GraphicsState` ze state blobu, wywołaj
`HostPipeline::new` (`pipeline/host.rs:404+`) i zapisz PSO w
`ID3D12PipelineLibrary1` (`pipeline/library.rs:512-565`). To daje PSO bez
pierwszego uruchomienia gry.

**B. Capture z runu (już jest).** `host-pipelines.bin` + `early-pipelines.txt`
(`pipeline/library.rs:431-438`, `pipeline/make.rs:142-147`). Pierwszy run
kompiluje, drugi ładuje. Wada: pierwszy run nadal ma stutter i musi dojść do
danej sceny.

Rekomendacja: A dla compute i screen-passów, B jako fallback dla scen
generowanych/streamowanych.

### 3.6 Root signature, mesh, GS

- **Root signature jest nasza, nie tytułu.** `HostPipeline::new` składa ją
  z bindingów przetłumaczonych shaderów: root constants `b0 space0` (user data),
  root CBV/SRV/UAV, static samplery, flagi
  `CBV_SRV_UAV_HEAP_DIRECTLY_INDEXED` + `SAMPLER_HEAP_DIRECTLY_INDEXED`
  (`pipeline/host.rs:444-575`, `1000-1045`).
  Subobject root signature z tytułu (stream kind 0) jest ignorowany —
  nie podawaj go przetłumaczonym shaderom.
- **Widoczność**: każdy etap ma własny `ShaderVisibility`
  (`VERTEX`/`PIXEL`/`GEOMETRY`/`MESH`); te same rejestry mogą wystąpić
  w kilku etapach z różną widocznością.
- **Mesh**: `D3D12_PIPELINE_STATE_STREAM` z MS+PS, topologia triangle,
  bez input layoutu (`pipeline/host.rs:919-988`). `DispatchMesh(x,1,1)`;
  brak `SV_PrimitiveID`/`SV_CullPrimitive` w PSG1.
- **GS**: `D3D12_GRAPHICS_PIPELINE_STATE_DESC.GS` albo stream GS; input layout
  z VS; sygnatury wejścia/wyjścia GS muszą się zgadzać z VS/PS; maxvertexcount.
  Jeśli GS jest syntetyczny (rect), obecny fallback `rect_list_gs`
  (`emit/rect.rs`, `host.rs:677-700`) zostaje.

### 3.7 Klucze cache

**Shader (DXIL):**

```
BLAKE3(
  "victory shader cache key 2"
  || translation_fingerprint()
  || bytes_of(shader_cache.rs)
  || container_bytes
)
```

`translation_fingerprint()` (`emit/mod.rs:192-211`) zawiera:

- hash źródeł `victory-shader` (build.rs),
- `diagnostics` / `debug_assertions`,
- wartości wszystkich `VICTORY_*` czytanych przez translator,
- `host_max_wave()`, `view_heap_limit()`, `loop_limit()`, `group_sync()`,
  `shader_opt()`.

To jest aktualny klucz (`shader_cache.rs:50-78`, `145-175`). Nie dodawaj
`stage` — kontener już go niesie; nie dodawaj całego EXE (chyba że
`VICTORY_SHADER_CACHE_KEY=exe`).

**PSO:**

```rust
// pipeline/library.rs:499-508
BLAKE3(kind || root_blob || DXIL(stages) || state.describe())[..32]
```

`kind` rozróżnia `graphics`, `mesh`, `graphics rectangles`, `compute`.
`state.describe()` (`pipeline/host.rs:242-271`) zawiera blend, rasterizer,
depth/stencil, sample mask, topology, formaty RT/DS, samples, input layout.
To jest właściwy klucz dla `host-pipelines.bin`.

**Manifest offline:**

```
BLAKE3(
  title_build_id
  || translator_fingerprint
  || adapter_luid || driver_version
  || pipeline_library_hash
  || backend ("dxil" | "spirv")
)
```

Adapter/driver w kluczu manifestu, bo `ID3D12PipelineLibrary1` i tak odrzuca
bibliotekę innego adaptera/sterownika (`library.rs:455-497`). Dla SPIR-V dodaj
Vulkan API version, pipeline layout, render pass/subpass, specialization
constants, subgroup size i tryb wave64.

### 3.8 Fallback dla GS

Kolejność:

1. **ES+GS → compute + mesh passthrough (docelowo).**
   - Jeden compute `[numthreads(64,1,1)]` (na NVIDIA: dwie połowy 32 + LDS),
     grupa = do 21 trójkątów / 63 wierzchołków ES.
   - ES pisze 16 B na rejestr OSG1 do `groupshared`; GS czyta offsety,
     `s3` = vertices | primitives << 8, `s2` = obszar wyjściowy.
   - `s_sendmsg` emit/cut → strip → trójkąty; output base = najniższy
     zapisany adres.
   - Wynik → rekord mesh (vertices/primitives) → `mesh_passthrough`
     (VItoriaBr ma mesh pipeline, `pipeline/host.rs:919+`).
   - To jest sprawdzone przez XCL na parze `GS_VoxelizeGeneric` + ES
     (`HANDOFF.md`, test `retail_es_gs_voxelize_geometry_mode`).
   - **Licencja:** XCL jest GPL-2.0-only; nie kopiuj kodu. Reimplementuj
     z opisu i własnych testów.
2. **Pass-through GS** dla GS, który tylko przepisuje wierzchołki (brak
   ekspansji, brak stream output): `triangle In[3] → TriangleStream<Out>`
   z tymi samymi wartościami. To tanie i dokładne, jeśli taki GS istnieje.
3. **Rect GS** — już jest (`emit/rect.rs`); nie dotyczy 195 GS.
4. **Skip z metryką** — jeśli GS jest tylko wokselizacją, a obraz bez niej
   przechodzi correctness gate, oznacz go jako świadomą lukę:
   `DROPPED geometry stage <hash>` i osobny licznik. Nie zero i nie cichy
   fallback.
5. **Bezpośredni DXIL GS** — tylko dla prostego per-prymitywowego GS;
   nie dla batchowego wokselizatora.

---

## 4. Lista napraw (max 5)

### P0 — 1. Triaging: 254 → dokładne kategorie, 48, 4 compute PSO

**Problem:** 48/254 nie ma nazwy; „hardware SGPR” nie mówi, który to SGPR;
`0x80070057` nie mówi, czy to wave64, root signature czy DXIL.

**Zmiana:**

- `warm --list` + `translate --list` do pliku; `VICTORY_FAIL_DUMP` dla
  pierwszych 3 kontenerów na reason (translate już to robi,
  `apps/victory/src/translate.rs:460-474`; dodaj to samo do `warm`).
- W `lower.rs:2450` zaloguj `stage`, numer SGPR, offset i to, czy SGPR jest
  w `params`/`io.inputs`. Nowy `VICTORY_SHADER_WHY=1`.
- W `host.rs:603-605` / `761-764` zaloguj `hr`, `WaveSize` z DXIL i pierwszy
  błąd debug layer.
- `translate.rs:382-386` wypisuje wszystkie reason'y, ale `warm.rs:131`
  tylko top 20; wypisz **wszystkie** w `warm` i dodaj agregację per stage.

**Pliki:** `apps/victory/src/warm.rs`, `apps/victory/src/translate.rs`,
`crates/victory-shader/src/emit/lower.rs`, `crates/victory-gpu/src/pipeline/host.rs`.

**Akceptacja:** CSV 254 wierszy z `stage`, `hash`, `reason`, `category`;
0 `unknown`; 4 compute PSO mają przyczynę.

**Weryfikacja:** §5.1–5.5.

### P0 — 2. GS: ES+GS → compute + mesh passthrough

**Problem:** 195 GS + 195 ES nie tłumaczą się; każdy pipeline z GS jest
odrzucany (`pipeline/host.rs:413-421`).

**Zmiana:**

- `native.rs`: parser GS/ES stage data; `StageIo::Gs`/`Es`.
- `io.rs`: wejścia/wyjścia GS/ES; `s_setpc_b64` → wspólny CFG; GSVS ring;
  `s_sendmsg`; `exp prim`.
- `emit`: compute `[WaveSize(64)]` (NVIDIA: dwie połowy + LDS) + rekordy;
  `mesh_passthrough` (compute PSO + mesh PSO).
- `pipeline/host.rs`: dla bezpośredniego GS zezwól na `"geometry"`, dodaj
  widoczność `D3D12_SHADER_VISIBILITY_GEOMETRY`, `GS` w PSO; dla CS+MS
  dodaj compute + mesh pipeline.
- `pipeline.rs:12-16`: zaktualizuj „shortcut”; GS nie jest już „container only”.

**Pliki:** `crates/victory-shader/src/native.rs`, `io.rs`, `emit/lower.rs`,
`emit/mod.rs`, `crates/victory-gpu/src/pipeline/host.rs`,
`crates/victory-gpu/src/pipeline.rs`, `draw.rs` (dispatch CS + mesh draw).

**Akceptacja:** 195 GS + 195 ES translation + `dxil.dll` + compute/mesh PSO;
para `GS_VoxelizeGeneric` + ES daje ten sam obraz co referencja; brak
`DROPPED geometry stage` dla tej pary.

**Weryfikacja:** §5.6–5.7.

### P1 — 3. PS „hardware SGPR input”

**Problem:** 10 PS czyta SGPR, którego translator nie modeluje.

**Zmiana:**

- Sparsuj `SPI_SHADER_PGM_RSRC2_PS.user_sgpr` (FSSM stage data; XCL widzi
  RSRC2 pod +0x110) i wyznacz pierwszy systemowy SGPR.
- Dodaj `Input::PsSystem` dla `{bc_optimize, prim_mask, lds_offset}`.
- Jeśli wszystkie użycia to `s_mov_b32 m0, sN` → `v_interp*` (lowering i tak
  nie używa M0), podstaw 0/undef; jeśli inne — odmów z precyzyjnym reason.
- Dla PS-ów z ścieżki „niezainicjalizowany SGPR” zastosuj regułę #432:
  zero tylko wtedy, gdy rejestr jest gdzieś zapisany; inaczej log i odmowa.

**Pliki:** `crates/victory-shader/src/native.rs`, `io.rs`,
`emit/lower.rs:2426-2451`, `emit/lower.rs:9392-9507`.

**Akceptacja:** 10/10 translation + validate + PSO; pixel compare dla
próbki; brak regresji liczby PS.

**Weryfikacja:** §5.8.

### P1 — 4. CS „lane mask holding lanes elsewhere”

**Problem:** 1 CS; maska ma bity lane'ów poza blokiem, ballot ich nie odtworzy.

**Zmiana:**

- Dla grup jedno-wave (`threads <= 64`): wymiana pełnej maski 64-bit przez
  LDS (`groupshared`), tak jak `exchange` w `lower.rs`; ballot + OR z drugą
  połową.
- Dla grup wielo-wave: liczba maski per wave + suma; jeśli kod używa tylko
  count/prefix, `with_local_waves` może być dokładne.
- Rozszerz `widen` / `structure_wide` o przypadek `s_not_b64 exec`.
- Dodaj test synthetic: `s_not_b64` → `s_bcnt1` → store; porównaj 64 vs 2×32.

**Pliki:** `crates/victory-shader/src/emit/lower.rs:3272-3331`,
`emit/mod.rs:555-609` (`widen`), `emit/mod.rs:359-523`, `structure.rs`.

**Akceptacja:** 1/1 translation + validate + PSO; wynik bufora zgodny
z referencją; brak device loss.

**Weryfikacja:** §5.9.

### P2 — 5. Offline PSO precompile + walidacja par

**Problem:** pierwszy świat kompiluje >1 200 PSO w klatce; `--pipelines`
używa stubów, więc nie sprawdza prawdziwych par.

**Zmiana:**

- Nowe `victory pso --library <shaders.rpf> --out <cache>`:
  parsuje 25 471 graphics + 2 693 compute, mapuje po `HASH`, odtwarza
  `GraphicsState`, wywołuje `HostPipeline::new`, zapisuje
  `ID3D12PipelineLibrary1`.
- Alternatywnie/rezerwowo: capture z runu (`host-pipelines.bin`).
- `warm` dostaje `--validate` (dxil.dll) i `--pairs` (real VS/PS, nie stub).
- Cache key: §3.7; manifest zapisuje adapter/driver/title build.
- Limity: PSO > 8 MiB / kompilacje > 30 s osobno, z raportem.

**Pliki:** nowy `apps/victory/src/pso.rs`, `crates/victory-gpu/src/pipeline/library.rs`,
`pipeline/make.rs`, `pipeline/host.rs`.

**Akceptacja:** drugi run: `made=0`, `loaded>0` dla prekompilowanego zbioru;
brak `host pipeline refused`; pierwsza klatka świata bez 1 200 kompilacji;
rozmiar cache w budżecie (np. ≤ 4 GB).

**Weryfikacja:** §5.10–5.12.

---

## 5. Komendy weryfikacyjne

Wszystkie ścieżki gier/cache poza repo. Uruchamiaj z `D:\git\VItoriaBr`
(albo `D:\git\fxceless-victory`), z tym samym buildem i `VICTORY_*`, co run.

### 5.1 Build

```powershell
cargo build --release -p victory
# opcjonalnie: build z diagnostyką (inny klucz cache!)
cargo build --release -p victory --features diagnostics
```

### 5.2 Warm + pełna lista failure'ów

```powershell
$env:VICTORY_HOST_WAVE = "32"       # z logu: "host wave lanes ... max=32"
$env:VICTORY_VIEW_LIMIT = "999999"  # z logu: "host view heaps hold 1000000 views" → views-1
.\target\release\victory.exe warm <game_dir> --list 2>&1 | Tee-Object -FilePath out\warm.txt
# drugi raz: powinno być "0 translated now", prawie wszystko "already cached"
.\target\release\victory.exe warm <game_dir> --list 2>&1 | Tee-Object -FilePath out\warm2.txt
```

`warm` sam tworzy device D3D12 i sonduje `host_max_wave`/`view_heap_limit`
(`shader_cache.rs:100-110`, `descriptor/host.rs:850-878`). Wartości z env są
dla przebiegów bez device'a; wpisz je z logu, nie „1M” (to nie to samo co
`1 000 000 - 1`).

### 5.3 Translate + validate + pipelines

```powershell
.\target\release\victory.exe translate <game_dir> --validate --pipelines --list `
  2>&1 | Tee-Object -FilePath out\translate.txt
```

`--validate` ładuje `dxil.dll` (`VICTORY_DXIL` albo najnowszy Windows SDK).
`--pipelines` tworzy PSO dla każdego wyemitowanego programu (stub dla pary).

### 5.4 Dump failure'ów

```powershell
$env:VICTORY_FAIL_DUMP = "D:\gta6-30fps\out\fail"
.\target\release\victory.exe translate <game_dir> --list 2>&1 | Tee-Object out\translate-fail.txt
Remove-Item Env:VICTORY_FAIL_DUMP
```

Dumpy są danymi gry: trzymaj poza repo, nie commituj.

### 5.5 Klasyfikacja

```powershell
python tools\shader\analyze_unsupported.py out\warm.txt --markdown
python tools\shader\analyze_unsupported.py --dumps out\fail --markdown --json out\fail.json
python tools\shader\analyze_unsupported.py out\translate.txt `
    --game-log <game-stderr.log> --json out\report.json
```

Skrypt czyta tylko metadane (FSSM slot table, PAL, rozmiary kodu, wave64);
nie wypisuje ani nie kopiuje kodu shaderów.

### 5.6 Jeden shader (GS/PS/CS)

```powershell
$env:VICTORY_TRANSLATE_ONLY = "<16-cyfrowy hash>"
.\target\release\victory.exe translate <game_dir> --validate --pipelines --list
Remove-Item Env:VICTORY_TRANSLATE_ONLY
```

### 5.7 GS: dump i para

```powershell
$env:VICTORY_SHADER_SAVE = "D:\gta6-30fps\out\saved"
.\target\release\victory.exe run <exe> --execute   # tylko własna kopia; zbierz .cdxil
Remove-Item Env:VICTORY_SHADER_SAVE

# po implementacji: para GS+ES
$env:VICTORY_PAIRS = "GS_VoxelizeGeneric+VS_<hash>"
.\target\release\victory.exe translate <game_dir> --validate --pipelines --list
```

`VICTORY_PAIRS` szuka etykiet po substringu (`translate.rs:359-376`).

### 5.8 PS hardware SGPR

```powershell
$env:VICTORY_SHADER_WHY = "1"
$env:VICTORY_TRANSLATE_ONLY = "<ps hash>"
.\target\release\victory.exe translate <game_dir> --validate --pipelines --list
```

Oczekiwane w logu: numer SGPR, offset, stage, czy w `params`/`io.inputs`.

### 5.9 CS lane mask

```powershell
$env:VICTORY_WAVE_WHY = "1"
$env:VICTORY_WAVE_WIDE = "1"
$env:VICTORY_WAVE_LOCAL = "1"
.\target\release\victory.exe translate <game_dir> --validate --pipelines --list
```

`VICTORY_WAVE_WHY=1` pokazuje, które retry `widen`/local waves zostały podjęte
(`emit/mod.rs:367-505`).

### 5.10 Compute PSO `0x80070057`

```powershell
$env:VICTORY_D3D12_DEBUG = "1"
$env:VICTORY_TRANSLATE_ONLY = "02384a60fda6f2d0,2cc4c197ee29e291,6b82bc7d22016cb5,5dc3b25986622949"
.\target\release\victory.exe translate <game_dir> --pipelines --list
```

Szukaj w logu: `host pipeline refused`, `root signature`, `wave size`,
`CreateComputePipelineState`, komunikatów debug layer.

### 5.11 Cache shaderów

```powershell
# log: hits/misses
$env:VICTORY_LOG = "victory_gpu::shader_cache=debug,info"
.\target\release\victory.exe run <exe> --execute 2>&1 | Select-String `
  "shader from the cache|translated and cached|shaders from the cache"
```

Po poprawnym warm: `hits` dominują, `misses` blisko 0. `shader translated`
nie oznacza missa — to log każdego użycia (`pipeline.rs:169-181`).

### 5.12 Pipeline library / PSO

```powershell
Get-ChildItem <cache_dir>\pipelines | Format-Table Name, Length, LastWriteTime
$env:VICTORY_LOG = "victory_gpu::pipeline=info,victory_gpu::pipeline::library=info"
.\target\release\victory.exe run <exe> --execute 2>&1 | Select-String `
  "host pipeline library loaded|host pipelines all made|started_early|host pipeline refused"
```

Pliki: `host-pipelines.bin`, `host-pipelines.next`, `early-pipelines.txt`
(`pipeline/library.rs:431-438`).

### 5.13 SPIR-V (ścieżka referencyjna)

```powershell
spirv-val --target-env vulkan1.3 out.spv
# jeśli masz harness Leonida:
python -I tools/vk_pipeline_check.py <out>
```

### 5.14 Correctness gate

```powershell
python tools\bench\parse_victory_log.py <game-stderr.log> --min-draws 1000 --min-ms 100
```

Gate: ten sam save/scena/kamera, 3 przebiegi, brak device loss, brak
`DROPPED geometry stage` dla naprawionej pary, obraz bez nowych artefaktów.
Nie promuj wariantu tylko po FPS.

---

## 6. Mapa kodu

| Obszar | Plik:linia | Co |
|---|---|---|
| Wybór etapu | `crates/victory-shader/src/emit/mod.rs:315-331` | tylko Vs/Ps/Cs/Ms |
| I/O etapu | `crates/victory-shader/src/io.rs:197-306` | `_ => "I/O of this stage"` |
| Dane etapu | `crates/victory-shader/src/native.rs:578-591` | GS/ES → `StageIo::None` |
| Slot FSSM | `crates/victory-shader/src/native.rs:83-92` | LS/HS/ES/GS/VS/PS/MS/CS |
| `s_setpc` | `crates/victory-shader/src/ir.rs:68-80` | `Exit::Indirect` |
| Indirect jump | `crates/victory-shader/src/emit/lower.rs:10589` | odmowa |
| GS_ALLOC | `crates/victory-shader/src/emit/lower.rs:129-130` | mesh only |
| Mesh prologue | `crates/victory-shader/src/emit/lower.rs:4317+` | `exp prim`, counts |
| Rect GS | `crates/victory-shader/src/emit/rect.rs:43-64` | syntetyczny GS |
| PS/VS host pipeline | `crates/victory-gpu/src/pipeline.rs:12-16` | tylko VS+PS/CS |
| Odmowa etapu | `crates/victory-gpu/src/pipeline/host.rs:413-421` | `only vertex, mesh, pixel...` |
| GS w PSO | `crates/victory-gpu/src/pipeline/host.rs:677-700` | tylko rect |
| Root signature | `crates/victory-gpu/src/pipeline/host.rs:1000-1045` | nasza ABI |
| Mesh PSO | `crates/victory-gpu/src/pipeline/host.rs:919-988` | stream, triangle |
| Hardware SGPR | `crates/victory-shader/src/emit/lower.rs:2426-2451` | `Val::Missing` |
| Inicjalizacja CS | `crates/victory-shader/src/io.rs:335-340` | tylko CS |
| `v_interp`/M0 | `crates/victory-shader/src/ir.rs:1336-1344` | M0 read |
| Interp lowering | `crates/victory-shader/src/emit/lower.rs:9392-9507` | M0 nieużywane |
| Lane mask | `crates/victory-shader/src/emit/lower.rs:3272-3331` | `MASK_ELSEWHERE` |
| Wave retry | `crates/victory-shader/src/emit/mod.rs:359-609` | `widen`, local waves |
| Shader cache key | `crates/victory-gpu/src/shader_cache.rs:50-78` | `build()` |
| Translate key | `crates/victory-shader/src/emit/mod.rs:192-211` | fingerprint |
| PSO key | `crates/victory-gpu/src/pipeline/library.rs:499-508` | `name()` |
| Pending key | `crates/victory-gpu/src/pipeline/make.rs:44-60` | early list |
| PSO save | `crates/victory-gpu/src/pipeline/library.rs:512-565` | library |
| Walidator | `crates/victory-shader/src/emit/validator.rs:120-213` | dxil.dll |
| Warm | `apps/victory/src/warm.rs:22-135` | cache |
| Translate | `apps/victory/src/translate.rs:236-388` | raport |
| Warm CLI | `apps/victory/src/translate.rs:159-234` | `--warm` |

---

## 7. Referencje i licencje

- **VItoriaBr** (GPL-3.0): `crates/victory-shader`, `crates/victory-gpu`.
- **fxceless/victory-fork** (GPL-3.0): shader cache, PSO library, opt passes.
- **Leonida / Leonida Continued** (GPL-3.0): `docs/shader_library.md`,
  `docs/design.md`, `tools/fssm_unpack.py`, `tools/pal_stages.py`,
  `tools/rdna2spirv.py` — referencja formatu i SPIR-V. Nie kopiuj kodu bez
  zachowania licencji.
- **XCL** (GPL-2.0-only): `HANDOFF.md` — referencja GS/ES, PSO, D3D12.X.
  Zgodnie z `docs/ARCHITECTURE.md` **nie kopiujemy kodu XCL** do GPL-3.0;
  tylko idee/reimplementacja.
- **Xbox2Windows** (MIT): `tools/dxil_retarget.py`, `disasm_rdna2.py` —
  referencja XBCH/FSSM i DXIL.
- **AnyXboxX** (GPL-3.0): stan świata i pomiary 25 689 shaderów.
- **AMD RDNA2 ISA** (publiczna specyfikacja): §3.12.2 (SGPR init),
  §5 (SALU), instrukcje eksportu.
- **Microsoft D3D12**: mesh shader spec, root signature, `ID3D12PipelineLibrary1`,
  `IDxcValidator`.

---

## 8. Czego ten dokument nie twierdzi

- Nie twierdzi, że 254 shaderów to przyczyna 1 fps. Główny koszt to CPU/submit,
  kopie i streaming (`PERF-DIAGNOSIS-2026-11-25.md`).
- Nie twierdzi, że GS są nieużywane. 195 `GS_VoxelizeGeneric` to najpewniej
  GI/wokselizacja; trzeba to potwierdzić `first bind`/`DROPPED`.
- Nie twierdzi, że 48 da się naprawić jednym commitem. To triage.
- Nie zawiera shaderów, hashów kontenerów jako danych gry, ani kodu XCL/Leonida.
