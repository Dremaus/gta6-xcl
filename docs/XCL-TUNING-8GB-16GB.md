# XCL na 8 GB VRAM / 16 GB RAM — ustalenia i przełączniki

Stan: XCL 0.1.0, `xcl-dev/xcl` HEAD `8b957bec`, binarka `target\release\xcl.exe`.
Tytuł: Xbox Series build 1.0.2.1, `shaders.rpf` 392,6 MB, 26 503 rekordy shaderów.
GPU: RTX 4060 Laptop 7956 MiB. Host: 16 GB RAM (15,31 GB widoczne dla systemu).

Ten dokument opisuje **zmierzone** zachowanie, nie zalecenia z README XCL.

## 1. Prekompilacja shaderów jest resumowalna

`xcl shaders <pakiet> --precompile` pomija programy już obecne w cache.
Cache: `%LOCALAPPDATA%\xcl\dxil` (nadpisywalny `XCL_DXIL_CACHE`), jeden plik `.dxil`
na skompilowany program.

Klucz cache to FNV-1a z: wersji pakietu, tożsamości toolchainu DXC, profilu,
punktu wejścia i **treści HLSL**. Treść zależy od `mem_windows` i `split wave64`,
więc parametry tłumaczenia muszą się zgadzać, inaczej wszystkie wpisy są chybione.

Praktyczny wniosek: prekompilacja w grze i z CLI muszą używać tego samego
`--windows`. Domyślnie gra loguje `4 memory windows`, więc:

```powershell
$env:XCL_DXC_DIR = 'C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64'
xcl.exe shaders '<gra>\shaders.rpf' --precompile --windows 4
```

Sonda kontrolna (300 rekordów, `--windows 4`): `compiled 0, already cached 475`
— czyli klucz trafia i cache nie jest marnowany.

## 2. Przyczyna „stoi na 23 923 / 26 503”

Nie był to pojedynczy zły shader. XCL dopuszcza kompilacje DXC według **wolnego
commit-u**, nie fizycznej RAM:

```
need = RESERVE_GB + (liczba trwających kompilacji × 1 GB)
plenty = ullAvailPageFile >= need
```

- Uruchomiona gra: `RESERVE_GB = 6`.
- `xcl shaders --precompile`: `set_memory_reserve(2)`.
- Domyślnie `compile_threads() = rdzenie − 1` (tu 15), każda kompilacja potrafi
  dojść do ~0,7 GB.

Na tym laptopie wolny commit to ~16 GB, więc przy 15 workerach **wszystkie**
wchodzą naraz: ~10 GB commit, fizycznej RAM brakuje, system zjeżdża na plik
wymiany. W logu wygląda to jak zawieszenie na kolejnym rekordzie, a working set
XCL rośnie do 5–6 GB.

## 3. Przełącznik, który to naprawia

`XCL_DXC_THREADS` (domyślnie `rdzenie − 1`, zakres 1–64) ustawia rozmiar puli DXC.

```powershell
$env:XCL_DXC_THREADS = '4'
```

Pomiar na tym samym cache i tym samym pakiecie:

| Wariant | Dojście do 24 000 | Working set XCL | Wolna RAM |
|---|---|---|---|
| 15 workerów (domyślnie) | stall na ~23 923 | 5–6 GB | 2–3 GB |
| 4 workery | 36 s | 1,7–1,9 GB | 4–5,5 GB |

To nie jest „wolniej, ale stabilnie”: 4 workery skończyły etap, na którym 15
workerów się dusiło.

## 4. Pozostałe przełączniki istotne dla 8/16 GB

| Zmienna | Domyślnie | Znaczenie |
|---|---|---|
| `XCL_DXC_THREADS` | rdzenie − 1 | liczba równoległych kompilacji DXC |
| `XCL_RECOMP_WINDOWS` | 1 (CLI), 4 (gra) | okna pamięci tłumaczenia; musi zgadzać się z cache |
| `XCL_HEAP_WINDOWS` | wył. | okna z deskryptora zamiast przełącznika po UAV |
| `XCL_PIPELINE_MAX_KB` | 8192 | górny rozmiar PSO; `0` = bez limitu (uwaga na RAM) |
| `XCL_DEVICE_TYPE` | `anaconda` | `lockhart` = 8192 MiB pamięci tytułu, `anaconda` = 13824 MiB |
| `XCL_SKIP_BINK` | — | pomija wideo Bink |
| `XCL_RUN_SECONDS` | — | zamyka tytuł po zadanym czasie |
| `XCL_ACTIVITY` | — | loguje `activity (2 s): N presents` — podstawa pomiaru fps |

Na 16 GB RAM `anaconda` (13,8 GB dla tytułu) nie ma szans; `lockhart` (8 GB) jest
jedynym sensownym presetem.

## 5. Co jeszcze nie jest zmierzone

- fps w świecie po pełnym cache — brak zamkniętego pomiaru.
- Wpływ `XCL_RECOMP_WINDOWS=1` na czas tłumaczenia w czasie gry.
- Czy pozostałe ~3 000 programów ogona to rzeczywiście najcięższe translacje.

Wpisy uzupełniane po każdym zamkniętym runie; patrz `NIGHT-LOG.md`.
