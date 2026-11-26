# Pipeline assetów — offline bake do DDS/KTX2 i manifest rezydencji

Data: 2026-11-25. Zakres: GTA VI Xbox Series `1.0.2.1`, RTX 4060 Laptop 8 GB /
16 GB RAM, D: 2 TB (119 GB wolnego). Dokument **nie uruchamia gry**, nie zmienia
runtime'ów A–H/J i nie kopiuje danych gry do repo.

Liczby oznaczone **zmierzone** pochodzą ze skanu 57 plików `.ttpf` w
`D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK` narzędziem
`tools/assets/ttpf_manifest.py` (deskryptory ETPF, bez dekodowania pikseli).
Liczby oznaczone **szacunek** to model, nie pomiar.

Zakres: ten dokument jest o **offline'owym assetcie** (bake, manifest, budżet
rezydencji). Warstwa wykonawcza runtime'u — staging, eviction, kolejka — jest
w `docs/MEMORY-STREAMING.md`; tu tylko tyle, ile trzeba do decyzji o formacie
i polityce mipów.

## 0. Wnioski

1. **Tekstury to 134,7 GiB surowych łańcuchów mip, 107,3 GiB samego mip0**, w
   357 115 deskryptorach (57 store'ów `.ttpf`). Na dysku zajmują 57,9 GiB, bo
   źródło jest zlib (2,33×). To jest cały świat — nie scena.
2. **4,2 GB VRAM to 3,9% mip0.** Nie da się trzymać „wszystkiego". Rezydencja
   musi być poziomami mip i komórkami streamingu, a nie kolejką „wszystko naraz".
3. Obecna ścieżka (DirectStorage HLE → zlib/BCPack → pamięć gościa w tiling
   konsoli → detile całej tekstury → upload) płaci dekodowanie i detile przy
   każdym użyciu oraz **re-upload po każdej zmianie pamięci tytułu**. 23 000
   tekstur czeka w kolejce, gdy karta jest pełna.
4. Offline bake usuwa z klatki: inflate, BCPack, detile i ponowne przeliczanie
   layoutu. Zostaje DMA + ewentualne zstd. To warunek konieczny, nie wystarczający
   — bez polityki rezydencji kolejka wróci.
5. **Cały świat w 1024 px nie mieści się bezpiecznie na 119 GB** (122,2 GiB raw,
   ~104 GiB po kompresji, limit z 10% zapasu to 107 GB). Bake musi być
   **per komórka** (globalne poole + 2×2 kafle = ~58,5 GiB raw) albo z niższym
   sufitem (512 px = 50,3 GiB).
6. Kolejność wdrożenia: (a) repack bit-exact bez re-encode, (b) poziom mip w
   manifeście i rezydencja, (c) resample/BC1 dla wybranych klas, (d) modele i
   audio osobnymi etapami.

## 1. Mapa formatów (zmierzona)

### 1.1 RPF9

- Magia `RPF9` (`39 46 50 52`, czyli `9FPR` little-endian). Nagłówek ma pola
  liczbowe, ale **tablica zawartości (TOC) jest zaszyfrowana** — nazwy, rozmiary
  i granice plików są niedostępne bez klucza.
- Obszar danych to głównie strumienie zlib; `audio.rpf` to w 99,9% surowe banki
  AWC, `movies.rpf` to Bink 2 (`KB2a`…).
- Konsekwencja dla pipeline'u: **`.ttpf` jest w pełni czytelny** (luźne pliki),
  a zasoby modeli i słowników tekstur wewnątrz `levels.rpf` wymagają carvowania
  (Leonida `rpf9dump`) albo przechwycenia odczytów działającego tytułu. Nie
  odszyfrowujemy TOC i nie szukamy kluczy.

### 1.2 TTPF (RDS5 + ETPF)

Nagłówek `RDS5`:

| offset | pole | znaczenie |
|---:|---|---|
| 0x00 | `RDS5` | magia |
| 0x04 | u32 | liczba wpisów tabeli chunków (ostatni to terminator) |
| 0x08 | u32 | rozmiar wirtualny (niski 32 bity) |
| 0x0C | u32 | górne bity rozmiaru / nieznane |
| 0x10 | u32 | offset sekcji ETPF / 256 |
| 0x18 | 8 B × n | tabela chunków: `(a, b)` |

Chunk: offset pliku `(a & 0xFFFFFF) << 8`, kodek w bitach 24–29 (`0x20` zlib,
`0x04` BC1 BCPack, `0x0C` BC3, `0x10` BC4, `0x14` BC5, `0x18` BC6H, `0x1C` BC7,
`0x00` stored). Offset wirtualny: `0x1000 + (b & 0xFFFFF) * 0x4000 + (a >> 30) * 0x1000`.

ETPF: `ETPF`, u32 wersja (0x27A), u32 liczba tekstur, u32 długość tabeli; dalej
`count` deskryptorów po 16 B i `count` posortowanych `u64` hashy.

Deskryptor:

| pole | bity | znaczenie |
|---|---|---|
| d0 0–13 | 14 | szerokość − 1 |
| d0 14–27 | 14 | wysokość − 1 |
| d0 28–31 | 4 | mipy − 1 |
| d1 0–2 | 3 | flagi (nieznane) |
| d1 3–10 | 8 | DXGI format; **bit 7 = cubemapa** |
| d1 10–19 | 10 | rozmiar tablicy − 1 |
| d1 20–23 | 4 | wymiar: 2 = 2D, 4 = cube, 6 = 3D, 10 = 2D array |
| d1 24–27 | 4 | tile mode: 0 = `SW_64KB_D`, 1–3 = `SW_4KB_S`, 9–12 = cube |
| d2 (u64) 0–20 | 21 | strona 4 KiB wirtualnego offsetu |

**Odkrycie przy skanie:** 598 deskryptorów ma w polu formatu bit 0x80; po jego
zamaskowaniu wszystkie 357 115 tekstur mają znany format DXGI (0 nieznanych).
To flaga cubemapy, nie format 199/223/224/226. Bez maskowania 598 tekstur
(cube mapy świateł/probe) wypada z budżetu.

Zmierzone sumy:

| metryka | wartość |
|---|---:|
| store'y | 57 |
| deskryptory | 357 115 |
| unikalne hashe | 357 067 (48 duplikatów, max 2×) |
| pełne łańcuchy mip | **134,74 GiB** |
| mip0 | **107,25 GiB** |
| pliki `.ttpf` na dysku | 57,94 GiB (2,33× mniej niż raw) |
| średnia mipów | 5,52 |
| tekstury 1-mip | 52 676 szt. = 24,68 GiB |
| tekstury ≥ 2048 px | 8 784 szt. = 26,69 GiB (mip0 21,60 GiB) |
| mip0 ≤ 32 KiB | 112 033 szt. = 2,68 GiB |

Rozkład mip (GiB): mip0 107,25 · mip1 20,57 · mip2 5,13 · mip3 1,28 · reszta 0,5.

Formaty (GiB / szt.): BC1 70,55 / 256 851 · BC7 52,33 / 77 838 · BC5 4,67 / 6 904 ·
BC3 2,04 / 6 925 · BC4 1,11 / 4 656 · RGBA8 3,21 / 1 776 · BC6H 0,72 / 1 025 ·
R16F 0,05 · A8 0,04 · BC2 0,001 / 2 · reszta < 0,01.

Chunki (szt.): zlib 918 272 · BC1 BCPack 102 732 · BC7 5 167 · BC5 334 ·
BC6H 268 · BC4 77 · BC3 35 · stored 5 · kodek `0x06` 3 (1,62 GiB — nieznany,
prawdopodobnie duży blok bez kompresji). BCPack to ~21% bajtów chunków.

### 1.3 Tiling i mipy

- Payload jest w layoutcie AMD Gfx10 (addrlib): bloki 64 KiB lub 4 KiB, mipy
  od najmniejszego, mip tail w jednym bloku, tablice poziom-poziomie, cube
  6 ścian na poziom.
- `victory-formats::texture::Layout` umie adresować tryby bez XOR
  (`SW_4KB_S`, `SW_64KB_D`), czyli dokładnie tryby 0–3 z TTPF; tryby `_X`/`_T`
  i MSAA nie są adresowane (konsola używa ich do render targetów).
- Mapowanie TTPF → addrlib do walidacji w bakerze: 0 → `SW_64KB_D` (10),
  1–3 → `SW_4KB_S` (5), 9–12 → `SW_4KB_S` z 6 ścianami. To mapowanie jest
  hipotezą opartą na opisie formatu, nie na pomiarze każdego kafla.

### 1.4 Audio, movies, modele

- `audio.rpf` 28,5 GB, 99,9% AWC; XMA2 dekodowane na osobnym wątku
  (`victory-hle/src/modules/audio.rs`), Opus przez APU. Poza ścieżką 33 ms.
- `movies.rpf` 8,8 GB, Bink 2 przez `Bink2Scarlett.dll` (CPU). Poza gameplayem.
- Modele: VItoriaBr **nie dekoduje** drawabli — geometrię buduje kod tytułu.
  Leonida raportuje 382 781 modeli z 10 archiwów (343 327 z `levels.rpf`).
  Offline bake modeli wymaga dekodera drawabli i jest etapem późniejszym.

### 1.5 Inne runtime'y (zakres mapowania)

- **fxceless/victory-fork** — ta sama linia `victory-formats` (`texture.rs`,
  `bcpack.rs`, `xma.rs`, ten sam `bcpack-tables.bin`), więc ścieżka dekodowania
  tekstur jest identyczna. Różnice fxceless są w submit/copy (104 ms/klatkę,
  3 850 draws), nie w assetach. Bake jest wspólny dla obu.
- **Leonida** — `tools/rpf9dump` (RPF9/TTPF, BCPack BC1/BC3/BC4/BC5 w strict
  mode) i clean-room `tools/bcpack.py` (BC1–BC7, z historią dopasowaną do
  sąsiednich mipów). To referencja dla dekodera BCPack i carvowania modeli;
  nie kopiujemy kodu, tylko zachowanie formatu.
- **Xbox2Windows** — MIT, rekompilacja CPU→C++/DXIL; jego narzędzia assetowe
  dotyczą statycznej rekompilacji, nie dekodowania tekstur. Referencja dla
  przyszłego bake geometrii (vertex/index), nie dla BCPack.

## 2. Obecna ścieżka dekodowania

### 2.1 Przepływ

```
tytuł → DirectStorage (HLE) → zlib → BCPack → pamięć gościa (tiled konsoli)
      → pierwsze próbkowanie → detile CAŁEJ tekstury → staging → CopyTextureRegion
      → write-watch: zmiana pamięci → detile i upload od nowa
```

- `victory-hle/src/modules/dstorage.rs`: kolejki, pule workerów
  (`available_parallelism()`), kolejność zlib → BCPack, wynik do pamięci gościa.
- `victory-formats/src/bcpack.rs`: dekoder rANS (12/16 lane'ów, 128 modeli,
  słowniki w `bcpack-tables.bin` 78 KB), tylko decode, BC2 nieużywane.
- `victory-formats/src/texture.rs`: addrlib Gfx10, `Layout::detile`, mip tail.
- `victory-gpu/src/texture.rs`: staging na teksturę, detile całej tekstury,
  upload; komentarz w pliku: „a change detiles the whole texture, not the pages
  written".
- `victory-gpu/src/tiles.rs`: `VICTORY_LEVELS_ON_DEMAND=1` — reserved resources
  i mapowanie kafli 64 KiB poziom po poziomie; **domyślnie wyłączone**, tylko
  2D single-layer > 1 MiB; poziomy bez pamięci czytają zera.
- `victory-gpu/src/resource.rs`: `room()` — 2 GiB zawsze, dalej do 90% budżetu
  karty albo `VICTORY_TEXTURE_BUDGET_MB`; `VICTORY_CARD_ROOM_FOR_TARGETS_MB`
  rezerwuje 3072 MB na render targety.
- `victory-gpu/src/draw.rs`: census kolejki `[slots, due, waiting for memory,
  partly uploaded, oldest due frames]`, 4096 due na pass, recheck po
  4/12/40/120/400 klatkach.

### 2.2 Wąskie gardła (z logów i komentarzy runtime'u)

- Staging/upload: stały budżet 250–750 ms na wątku nagrywania klatki, a każdy
  upload detile'uje całą teksturę (`docs/MEMORY-STREAMING.md`, C1–C2).
- 6,8–7,7 GB VRAM; **23 000 tekstur czeka** przy 4 s klatkach
  (`docs/PERF-DIAGNOSIS-2026-11-25.md`, sekcje 03 i 06).
- 7,3 GB tekstur przy pierwszej klatce świata; 2,3 GB zwolnione w 13 s
  (komentarz `resource.rs`, run 193).
- 2,2–3,0 GB z 4,3–5,5 GB kopii to poziomy, których pamięć tytułu nie jest
  zmapowana (`tiles.rs`, runy 188–189) — czyli VRAM trzyma dane, których nikt
  nie próbkuje.
- 1 245 184 widoków > limit heapu 1 000 000 (`game-stderr.log`).
- 201 ostrzeżeń „texture picked by index changed after its upload … uploaded
  again": tytuł reużywa pamięć, runtime detile'uje całą teksturę ponownie.

### 2.3 Czego brakuje

1. Brak rozróżnienia „poziom mip" od „cała tekstura" w polityce rezydencji.
2. Brak priorytetu (UI vs tło) — kolejka jest budżetowa, bez klas, więc 23k czeka.
3. Dekodowanie (zlib/BCPack) i detile są po stronie CPU w klatce.
4. Brak manifestu: runtime nie wie, co jest w plikach, dopóki tytuł nie poprosi.
5. Brak deduplikacji 48 hashy i brak wspólnego cache treści.

## 3. Co pre-bake'ować

Polityka formatów (na podstawie rozkładu z 1.2):

| format | decyzja | uzasadnienie |
|---|---|---|
| BC1 | **zostaw** | 70,5 GiB, 72% tekstur; opaque color, sRGB bez zmian |
| BC3 | **zostaw** | 2,0 GiB; alpha/cutout, nie ruszać |
| BC4 | **zostaw** | 1,1 GiB; jeden kanał (maski, wysokości) |
| BC5 | **zostaw** | 4,7 GiB; normalne, re-encode psuje wektory |
| BC6H | **zostaw** | 0,7 GiB; HDR, brak sensownego zamiennika |
| BC7 | **zostaw dla alpha/hero**; opcjonalnie BC1 dla opaque | 52,3 GiB; BC1 oszczędza 50%, gate SSIM |
| RGBA8 | **konwertuj do BC7** | 3,2 GiB → 0,8 GiB; 75% zysku, jakość wizualnie nierozróżnialna |
| BC2 | zostaw (2 szt.) | brak danych, nie warto |

Klasy assetów:

| klasa | decyzja | format docelowy | mipy | uwagi |
|---|---|---|---|---|
| tekstury `.ttpf` | **tak, etap 1** | BC1/BC3/BC4/BC5/BC6H/BC7 bez zmian | pełny łańcuch; generować tylko po walidacji 1-mip | detile do linear, bez re-encode w etapie 1 |
| cubemapy (598) | tak | jak źródło | tak | 6 ścian, `DDS_HEADER_DXT10.arraySize = 6` |
| tablice 2D | tak | jak źródło | tak | poziom-poziomie |
| 3D (3 szt.) | tak | jak źródło | tak | `ResourceDimension.TEXTURE3D` |
| UI | tak, pin | BC7/BC1 | mip0 (UI próbkuje 1:1) | nie schodzić poniżej 1024 px |
| terrain 1-mip | **ostrożnie** | BC1/BC7 | **nie generować bez testu** | prawdopodobnie strony virtual texturing; patrz ryzyko R2 |
| modele | nie w etapie 1–2 | — | — | brak dekodera w VItoriaBr; Leonida/rpf9dump później |
| audio AWC/XMA | etap 3 | Opus 96–128 kbps | — | poza 33 ms; zysk dysk/CPU |
| movies Bink2 | nie | — | — | poza gameplayem |

Czego **nie** robić: re-encode wszystkiego do BC7 (wolne, brak zysku),
half-res UI, mipy dla stron VT, kopiowanie payloadów do repo.

## 4. Pipeline offline

### 4.1 Etapy

```
scan      → manifest deskryptorów (hash, wymiary, format, tile, cell, bajty)
classify  → klasa/rezydencja, dedupe 48 hashy, wykrycie alpha/kanałów
decode    → zlib → BCPack (tylko 21% bajtów) → bufor tiled
detile    → linear wg addrlib (te same tryby co runtime)
resample  → opcjonalnie sufit 1024/512 (box filter; normalne renormalizowane)
mipgen    → tylko dla tekstur bez łańcucha, po walidacji
encode    → opcjonalnie BC7→BC1/BC4 (tylko opaque, gate SSIM)
pack      → pool: frame = jeden mip, zstd; offset 64 KiB dla mip0
manifest  → binarny rekord + tabela mipów + tabela pooli
verify    → sumy, hashe treści, PSNR/SSIM vs mip sąsiedni, brak zer
```

Etap 1 (repack) jest **bit-exact**: nie dekoduje bloków BC, tylko zdejmuje
zlib/BCPack i detile'uje. Etap 2 dodaje resample i re-encode tylko tam, gdzie
sufit albo BC1 jest jawnie wybrany.

### 4.2 Kontener pool

Jeden `.pool` na store (57 plików, nie 357 tys.):

| pole | rozmiar | znaczenie |
|---|---:|---|
| magic `GT6POOL1` | 8 B | wersja |
| header | 64 B | liczba tekstur, offset katalogu, offset danych, seed hashy |
| katalog | 32 B × n | hash, offset pierwszego mipu, liczba mipów, format, flagi |
| tabela mipów | 12 B × mips | offset u64, długość u32 (po kompresji) |
| dane | — | frame = jeden mip, zstd; mip0 wyrównany do 64 KiB |

Frame per mip jest kluczowy: dekodowanie 512 KiB mip0 to ~1 ms na rdzeniu, a
nie cała tekstura. Pomiar zlib na `ttdb_graphics.ttpf`: ramki 1 MiB dają ten
sam stosunek co cały strumień (5,13 vs 5,14), więc format ramkowy nie traci na
kompresji; dla zstd trzeba to powtórzyć (ryzyko R4).

### 4.3 DDS vs KTX2

- **DDS (DX10 header)** — kanoniczny eksport dla D3D12: `DXGI_FORMAT`,
  `resourceDimension`, `miscFlag.TEXTURECUBE`, `arraySize`, `miscFlags2`.
  Ładuje się przez `CreateCommittedResource` + `CopyTextureRegion` per
  subresource. Używany do debugowania i pierwszej integracji (pojedyncze
  tekstury), nie jako 357 tys. plików.
- **KTX2** — kanoniczny eksport dla Vulkan i przyszłego renderera: `vkFormat`
  BC*, `supercompressionScheme = 2` (zstd) per poziom, level index z
  `byteOffset/byteLength/uncompressedByteLength`. Poziomy w poolu są bajtowo
  tym, co KTX2 trzyma w level index, więc eksport to przepisanie nagłówka.
- **Pool** — format runtime'u: jeden plik na store, katalog + frame'y. DDS/KTX2
  to formaty wymiany i walidacji, nie ścieżka gorąca.

### 4.4 Manifest

`manifest.bin` (44,4 MiB dla 357 067 rekordów; mmap + binary search po hash):

| pole | typ | znaczenie |
|---|---|---|
| hash | u64 | hash tekstury z ETPF (klucz, którego używa shader) |
| pool | u32 | id store'a |
| mip_index | u32 | początek w tabeli mipów |
| baked_bytes | u32 | rozmiar po bake (0 = tylko deskryptor) |
| content_hash | u64 | BLAKE3-64 łańcucha (wykrywanie duplikatów/zmian) |
| width, height | u16 | mip0 |
| slices | u16 | array/cube/depth |
| mips | u8 | liczba poziomów |
| dxgi | u8 | format (bez bitu cube) |
| tile | u8 | tryb TTPF (0–3, 9–12) — do detile |
| flags | u8 | cube, sRGB, alpha, 1-mip, VT-podejrzenie |
| cell | u8 | komórka streamingu (maps 1–8, terrain 9–16, interiors 17–20, globalne 21–28) |
| priority | u8 | 0 = dystans, 1 = props, 2 = peds/vehicles/weapons, 3 = pin |
| status | u8 | 0 deskryptor, 1 strict, 2 BCPack, 3 fallback, 4 unsupported |
| mip table | u64+u32 | offset i długość każdego mipu |

Dodatkowo `stores.json` (57 wpisów: ścieżka, rozmiar, kodeki), `summary.json`
(agregaty) i opcjonalny `textures.csv`.

Hash ETPF nie jest kryptograficzny: 357 115 wpisów w 64-bit space daje ~48
realnych duplikatów (te same treści w `pack/` i `data/ttdb`). Manifest
deduplikuje po hash, a `content_hash` rozstrzyga, czy treść jest identyczna.

### 4.5 Weryfikacja

- Suma `baked_bytes` = rozmiar danych w poolu; brak dziur i nakładek.
- `content_hash` zgodny z ponownym odczytem; 48 duplikatów ma identyczny hash
  treści albo jawny konflikt.
- PSNR/SSIM zdecodekowanego mipu vs mip sąsiedni (jak SixNG: 27–47 dB dla
  BCPack BC3/BC7); próg odrzucenia < 30 dB dla koloru.
- Wizualny A/B na 20 scenach (miasto, wnętrze, pojazd, twarz, UI, teren).
- Brak zmiany pikseli w etapie 1 (repack bit-exact): porównanie bloków BC1/BC7
  przed i po detile+retile.

### 4.6 Wejście do runtime'u (bez zmiany main runtime'ów)

Manifest jest bezużyteczny, dopóki runtime nie wie, **który hash** odpowiada
zasobowi, który właśnie próbkuje. Tłumacz widzi tylko deskryptor D3D12 i adres
pamięci gościa, nie hash ETPF. Trzy seam'y, w kolejności wdrożenia:

1. **Content hash po pierwszym detile (najmniej inwazyjny).** Runtime robi
   dokładnie to, co dziś: detile'uje teksturę do linear. Liczy BLAKE3-64 z
   łańcucha i szuka w indeksie `content_hash → hash` z bake'u. Trafienie →
   odtąd upload z poolu; brak → dotychczasowa ścieżka. Wymaga etapu 1
   (bit-exact), bo hash musi być identyczny. Koszt: jedno detile na teksturę
   (już jest płacone), hash ~1–2 GB/s.
2. **Tagowanie w HLE DirectStorage.** HLE zna `(plik .ttpf, offset chunku,
   destination)`, a skan zna `(strona ETPF → hash)`. Przy inflate otaguj zakres
   pamięci gościa hashem; pierwszy upload omija detile. Wymaga mapy
   `page → hash` i dotknięcia HLE, ale zero zgadywania.
3. **Native renderer.** Pyta manifest wprost hashem z drawu — bez detile
   i bez HLE.

Wariant 1 jest domyślny dla obecnego runtime'u: nie zmienia API ani formatów,
a jedyny koszt to pierwszy detile, który i tak jest dziś wykonywany. Wariant 2
jest docelowy dla natywnego renderera. Fallback zawsze zostaje poprawny.

## 5. Budżety

### 5.1 Dysk

Surowe 134,7 GiB to metryka VRAM/working set, **nie** zajętość dysku. Pool jest
kompresowany per mip; źródło ma 57,9 GiB przy zlib 2,33×. Wstępny pomiar zlib na
`ttdb_graphics.ttpf` sugeruje, że ramki 1 MiB nie tracą stosunku (5,13 vs 5,14),
więc `disk_ratio` (skompresowane / raw) przyjmujemy **0,85** z zakresem
0,80–1,10 do zmierzenia po detile (ryzyko R4).

| scenariusz | raw GiB | dysk @0,85 | ocena |
|---|---:|---:|---|
| as-is, pełne łańcuchy | 134,7 | 114,5 GiB | nie na 119 GB |
| mip0 only | 107,3 | 91,2 GiB | bez mipów = aliasing |
| sufit 1024, pełne łańcuchy | 122,2 | 103,9 GiB | **nie** z 10% zapasu |
| sufit 1024 + BC7→BC1 60% | 109,7 | 93,3 GiB | granica (7 GB zapasu) |
| sufit 1024 + BC7→BC1 100% | 101,4 | 86,2 GiB | ryzyko jakości |
| sufit 512, pełne łańcuchy | 50,3 | 42,7 GiB | komfort, miękko |
| **globalne + 2×2 kafle @1024** | **58,5** | **49,7 GiB** | **rekomendacja** |

Rekomendacja: `globalne` (peds, props, vehicles, weapons, ui, vfx, lighting,
graphics) = 40,7 GiB raw + 2 kafle maps + 2 kafle terrain = 17,8 GiB raw.
Razem 58,5 GiB raw ≈ 50 GiB na dysku, ~62 GB z zapasem i scratchem. Reszta
świata dobake'owywana per komórka (LRU, łączny cap np. 90 GB).

### 5.2 VRAM (8 GB)

Budżet docelowy jest w `docs/NATIVE-VERTICAL-SLICE.md` 2.6: cap **7,2 GB**,
tekstury **4,2 GB**. Obecny runtime ma `VICTORY_TEXTURE_BUDGET_MB=5120`, ale to
nie jest budżet natywnego renderera — 5 GB tekstur wypycha geometrię i targety.
Dla natywnego celu przyjmujemy 4,2 GB.

| kategoria | GB | uwagi |
|---|---:|---|
| tekstury (BCn, mipy 0–3 + tail) | 4,20 | ten dokument |
| geometria / meshlety | 1,00 | osobny etap bake'u |
| render targety | 0,40 | 720p HDR + depth + motion |
| shadow mapy | 0,30 | jeden atlas |
| scratch / indirect / stałe | 0,30 | ring buffery |
| swapchain | 0,03 | 3 bufory |
| rezerwa | 0,37 | fragmentacja / spike |
| **razem** | **7,20** | cap, nie target |

Jedna komórka `maps` = 4,41 GiB raw (**105%** budżetu tekstur), więc mip0 **nie
może** być w całości rezydentny. Poziomy: mip≥1 = 1,10 GiB, mip≥2 = 0,28 GiB,
mip≥3 = 0,07 GiB. To jest cała dźwignia.

Przykładowy zestaw rezydencji na 4,2 GiB:

| składnik | GiB |
|---|---:|
| UI mip0 (pin) | 1,22 |
| globalne niskie mipy (peds/props/vehicles ≥3, reszta ≥2) | 0,61 |
| aktywna komórka: mip≥1 | 1,10 |
| aktywna komórka: selektywne mip0 (~200–350 tekstur near) | 0,90 |
| prefetch sąsiedniej komórki: mip≥2 | 0,28 |
| **razem** | **4,11** |

### 5.3 Czas bake (szacunek)

- Odczyt 57,9 GiB + inflate + BCPack + detile: 15–40 min na 8 rdzeniach
  (zlib ~200–400 MB/s/rdzeń, BCPack wolniejszy, detile memory-bound).
- Re-encode (etap 2): BC1 ~151 Gpx, BC7/BC5/BC6H ~64 Gpx; szybkie encodery
  10–40 min, jakościowe 3–8 h.
- Zapis 50–100 GiB: 1–2 min przy 1–2 GB/s.
- Per komórka (np. jedna `maps`): 4,4 GiB raw → 5–15 min.

## 6. Polityka streamingu

### 6.1 Ziarno

Etap 1: **poziom mip** (nie strona). Poziom 0 to 512 KiB dla 1024² BC1; poziom 3
to 8 KiB. Rezydencja `(hash, level)` w hash mapie; upload przez
`CopyTextureRegion` z poolu. To wykorzystuje istniejący pomysł `tiles.rs`, ale
na danych z bake, nie na pamięci tytułu.

Etap 2 (później): strony 64 KiB w mip0 (VT) dla terenu i atlasów miejskich.
Manifest już ma offset i długość per mip, więc strony można dodać bez zmiany
formatu rekordu.

### 6.2 Algorytm

1. **Żądanie:** dla każdego drawu policz texels-per-pixel z UV i ekranu;
   `wanted = clamp(floor(log2(tpp)), 0, mips-1)`.
2. **Trafienie:** jeśli `wanted` rezydentne — użyj. Jeśli nie, użyj najbliższego
   niższego poziomu i oznacz `mip_miss`.
3. **Podniesienie:** 3 klatki z rzędu `mip_miss` dla tego samego hasha →
   priorytet +1 (anti-thrash), ale nie ponad pin.
4. **Ewikcja:** watermark 85% (soft) / 92% (hard). Ewiktuj
   `(priority, level, last_used)`; nigdy UI/lighting; poziom 0 zachowaj, jeśli
   tekstura była użyta w ostatnich 2 klatkach.
5. **Prefetch:** na zmianę komórki wczytaj sąsiednią komórkę mip≥2 (0,28 GiB)
   i mip0 dla 200 tekstur o największym pokryciu ekranu.
6. **Budżet I/O:** 8–32 MiB/klatkę w steady state (240–960 MB/s), burst
   64 MiB przy ładowaniu; kolejka copy niezależna od renderu, fence per klatka.

### 6.3 Kompresja i CPU

- Pool per mip + zstd: dekodowanie 32 MiB/klatkę na jednym rdzeniu to 16–32 ms
  — za dużo. Użyć 4–8 workerów (jak dstorage) albo DirectStorage 1.2 z
  dekompresją GPU (GDeflate); wtedy 2–4 ms.
- Alternatywa dla gorącej komórki: mip0 **bez kompresji** (DMA wprost), zimne
  poziomy z zstd. Mierzyć stosunek zysku dysku do kosztu CPU.
- Nie dekodować w wątku renderu; upload przez copy queue i fence.

### 6.4 Bramki

- Po rozgrzaniu: `mip_miss` < 1% próbek na klatkę, p95 ≤ 2%.
- Brak stallu uploadu > 2 ms na wątku renderu; wiek kolejki < 3 klatki.
- VRAM < 95% budżetu przez 60 s; brak device loss.
- Pop-in: liczba tekstur pokazanych o > 1 poziom niżej niż `wanted` < 0,5%
  drawów na klatkę.
- Correctness: ten sam save/scena, screenshot diff, brak czarnych tekstur.

## 7. Komendy

Działa dziś (tylko odczyt danych gry, wynik poza repo):

```powershell
# 1. Skan 57 store'ów → manifest + agregaty (44 MiB, ~10 s)
python tools\assets\ttpf_manifest.py scan `
  "D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK" `
  --out "D:\Gry\gta6-bake\manifest"

# 2. Scenariusze dysk/VRAM dla sufitu 1024 i 60% BC7→BC1
python tools\assets\ttpf_manifest.py plan "D:\Gry\gta6-bake\manifest" `
  --ceiling 1024 --bc1-share 0.6 --vram-gib 4.2 --disk-free-gb 119 --json

# 3. CSV do arkusza (opcjonalnie)
python tools\assets\ttpf_manifest.py scan `
  "D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK" `
  --out "D:\Gry\gta6-bake\manifest" --csv
```

Planowane (nie zaimplementowane w tym etapie; wymaga dekodera BCPack i detile):

```powershell
# per komórka, etap 1 (bit-exact repack)
python tools\assets\bake_pool.py --manifest "D:\Gry\gta6-bake\manifest" `
  --store "data/ttdb/maps/ttdb_maps_0_7.ttpf" `
  --out "D:\Gry\gta6-bake\pools" --mode repack

# etap 2 (sufit + BC1)
python tools\assets\bake_pool.py ... --ceiling 1024 --bc1 opaque
```

## 8. Ryzyka

| # | ryzyko | wpływ | mitygacja |
|---|---|---|---|
| R1 | Pole mipów zaniża liczbę poziomów (SixNG: ~44,9k tekstur) | brakujące mipy, zaniżony budżet | walidacja łańcucha vs rozmiar wirtualny store'a; `status=unknown` |
| R2 | Terrain 1-mip to strony virtual texturing, nie tekstury | generowanie mipów psuje atlas | test: czy strony sąsiadują w UV; nie generować bez dowodu |
| R3 | BCPack BC6H/BC7 to dekodery społecznościowe, nie spec | artefakty, PSNR < 30 dB | gate PSNR/SSIM vs mip sąsiedni; fallback do niższego mipu |
| R4 | Detile psuje stosunek kompresji (tiling pomaga zlib) | dysk 0,85–1,1× | pomiar zstd na 3 store'ach przed commitmem budżetu |
| R5 | BC7→BC1 na gradientach/twarzach | widoczna utrata jakości | detekcja alpha, whitelist hero, SSIM gate, A/B 20 scen |
| R6 | 16 GB RAM przy bake | swap, 1455 | 6 workerów, 128–256 MB peak, streaming per tekstura |
| R7 | Tiled resources tier 2 na NVIDIA staje na `UpdateTileMappings` | stalle | etap 1 poziomami, nie stronami; mierzyć przed VT |
| R8 | 48 duplikatów hashy o różnej treści | zły cache | `content_hash` + jawny raport konfliktów |
| R9 | Brak informacji o użyciu w deskryptorach | zły priorytet | przechwycić strumień drawów i zbudować histogram użycia |
| R10 | File cache Windows zaśmiecony przez bake | wolny runtime | odczyty sekwencyjne, `FILE_FLAG_NO_BUFFERING`, ograniczyć workerów |
| R11 | Brak korelacji hash ETPF ↔ zasób runtime | manifest nieużyty | content hash po detile (4.6.1) jako domyślny; tagowanie HLE (4.6.2) |
| R12 | Pool i manifest na innym dysku niż gra | losowe I/O, stutter | oba na NVMe; prefetch sekwencyjny; sprawdzić kolejność plików |

## 9. Otwarte pytania

1. Czy 1-mip terrain (2 582 × 1024² BC1 w jednym kaflu) to strony VT?
2. Co to jest kodek `0x06` (3 chunki, 1,62 GiB)?
3. Czy 48 duplikatów hashy ma identyczne payloady?
4. Jaki jest realny stosunek zstd po detile (0,8? 1,0? 1,1?)
5. Które tekstury są próbkowane z explicit LOD (nie potrzebują mipów)?
6. Ile waży geometria w `levels.rpf` (343 327 modeli) po bake?
7. Czy shadery używają `SampleGrad`/`SampleLevel` na terrain (wtedy mipy
   mogą być zbędne, a VT obowiązkowe)?

## 10. Źródła

- `D:\git\VItoriaBr\crates\victory-formats\src\{texture,bcpack,xma}.rs`,
  `victory-hle\src\modules\dstorage.rs`, `victory-gpu\src\{texture,tiles,resource,draw}.rs`.
- `docs/PERF-DIAGNOSIS-2026-11-25.md` (23 000 tekstur, 6,8–7,1 GB).
- Leonida `docs/rpf.md`, `docs/textures.md`, `docs/textures_arrays.md`
  (357 115 deskryptorów, 382 781 modeli, BCPack BC1–BC7).
- SixNG `formats/05-ttpf.md` (RDS5/ETPF, kodeki chunków, mip tail, braki mipów).
- `paryzius/ttpf-viewer` (RDS5/ETPF, tile modes 0–3 i 9–12).
- `breadbbbb/rpf9-explorer` (RPF9/TTPF, BCPack BC1/BC3/BC4/BC5).
- `tools/assets/ttpf_manifest.py` — skan i plan (ten projekt).
