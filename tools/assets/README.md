# Asset tools

Offline'owy skan i planer budżetu dla tekstur GTA VI (`.ttpf`). Narzędzie jest
**tylko do odczytu** danych gry: parsuje nagłówki RDS5, tabelę chunków i indeks
ETPF, a zapisuje wyłącznie metadane (hashe, wymiary, formaty, rozmiary). Nie
kopiuje pikseli, nie dekoduje BCPack, nie rusza RPF9 TOC.

Projekt i liczby: `docs/ASSET-PIPELINE.md`.

## Moduły

| plik | rola |
|---|---|
| `ttpf_manifest.py scan` | 57 store'ów → `manifest.bin`, `stores.json`, `summary.json`, opcjonalnie `textures.csv` |
| `ttpf_manifest.py plan` | scenariusze dysk/VRAM: pełne łańcuchy, mip0, sufit 512/1024, BC7→BC1 |

## Szybki start

```powershell
# skan (wynik poza repo; narzędzie odmówi zapisu w repo)
python tools\assets\ttpf_manifest.py scan `
  "D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK" `
  --out "D:\Gry\gta6-bake\manifest"

# plan dla 8 GB VRAM (4,2 GB na tekstury) i 119 GB wolnego dysku
python tools\assets\ttpf_manifest.py plan "D:\Gry\gta6-bake\manifest" `
  --ceiling 1024 --bc1-share 0.6 --vram-gib 4.2 --disk-free-gb 119 --json

# CSV do arkusza (44 MiB manifestu, ~60 MiB CSV)
python tools\assets\ttpf_manifest.py scan <game_root> --out <dir> --csv
```

## Wynik na buildzie 1.0.2.1 (2026-11-25)

```text
stores       57
descriptors  357115  unique 357067  duplicates 48
full chains  134.74 GiB   mip0 107.25 GiB
store files  57.94 GiB
manifest     44.4 MiB
```

`plan --ceiling 1024 --bc1-share 0.6`:

```text
as-is full chain     134.72 GiB
mip0 only            107.23 GiB
ceiling 1024px       122.17 GiB
  BC7->BC1 60%      109.72 GiB  (saves 12.45)
VRAM budget 4.20 GiB -> 3.9% of mip0
on disk              100.1 GB raw x 0.85 compression
disk free            119.0 GB, keep 10% free -> fits (+7.0 GB margin)
```

## Manifest

`manifest.bin` (mmap, sortowany po hash):

| część | rozmiar | zawartość |
|---|---:|---|
| nagłówek | 64 B | `GT6AMF01`, wersja, liczba rekordów, rozmiar rekordu, liczba mipów, liczba pooli |
| rekord | 64 B | hash u64, pool, mip_index, baked_bytes, content_hash, wymiary, mipy, DXGI, tile, flagi, cell, priority, status |
| tabela mipów | 12 B × mips | offset u64, długość u32 |

`stores.json` ma 57 wpisów (ścieżka, rozmiar pliku i wirtualny, kodeki chunków).
`summary.json` ma agregaty formatów i klas.

## Zasady

- Zero danych gry w repo: output domyślnie poza repo, a `refuse_repo()` blokuje
  zapis w katalogu projektu.
- Zero odszyfrowywania: TOC RPF9 pozostaje nieczytelny; `.ttpf` jest luźny.
- Zero uruchamiania gry i zero modyfikacji runtime'ów.
- `manifest.bin` to metadane, nie asset: hash, wymiary i offsety, bez payloadu.

## Rozszerzenia (planowane)

- `bake_pool.py` — repack bit-exact per store (zlib/BCPack → detile → pool),
  potem sufit + BC1 dla wybranych klas.
- `usage_trace.py` — histogram użycia tekstur z przechwyconego strumienia
  drawów (priorytety zamiast zgadywania).
- `verify_pool.py` — sumy, `content_hash`, PSNR/SSIM vs mip sąsiedni.

## Wymagania

- Python 3.11+ (testowane 3.13), tylko biblioteka standardowa.
- Gra zamknięta; skan czyta nagłówki 57 plików (kilka sekund), nie payload.
