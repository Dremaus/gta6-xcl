# 20 - ScarlettPort: ten sam tytul, ten sam sprzet, inny runtime

Data: 2026-11-28. Zrodlo: github.com/ZigZagBoi1/ScarlettPort (v0.5.7, wydane 2026-11-28).
ECC: research-ops + market-research (analiza konkurencyjnego runtime'u), agent-introspection-debugging
(diagnostyka hold/VRAM w XCL). REA: nie dotyczy (analiza cudzego zrodla i logow; cel REA
game_scarlett_master.exe nadal bez providera Ghidra).

## 1. Co to jest i jakie ma licencje
- `engine/` = fork VIctory (GPL-3.0-or-later), wlasny runtime "World engine" (`ScarlettPort-Runtime.exe`).
- `runtime/xcl` = drzewo XCL (GPL-2.0-only) + `patches/xcl-stack.patch` (1,19 MB).
- `patches/`, `scripts/`, `docs/` zadeklarowane w ich LICENSE jako GPL-3.0-or-later.
- Zasada projektu: GPL-3.0 to **tylko idee**, nigdy kod do XCL (GPL-2.0-only). Samo uruchomienie
  ich binarium to osobny program - dozwolone i nie laczy sie z XCL.

## 2. Kluczowy fakt: ich XCL ma te sama sciane co nasz
Ich `docs/STATUS.md`:
- "XCL: world reached, survives 7+ minutes" - czyli ich patch XCL doprowadza gre do swiata,
- "the final image is black" - 3D nadal czarne,
- "two-pass mesh draws (`XCL_TWO_PASS_INDIRECT=1`) can reset the GPU" - ich two-pass jest
  domyslnie WYLACZONY, bo resetuje GPU.
Wniosek: XCL u nich nie przeszedl problemu, ktory nas blokuje. Swiat renderuje tylko ich engine.

## 3. Ich engine (VIctory) - zmierzone przez nich
- RTX 3060 12 GB + Ryzen 5 5600X, Series S, RT off: swiat osiagniety w 178 s (0.5.0),
  ~4 fps w prologu (0.5.0), 7-8 fps po rozgrzaniu (0.5.2), 12-13 fps po `SCARLETT_BVH_INPUT_SKIP`
  (0.5.6, +60%, bo gra przygotowuje geometrie BVH mimo wylaczonego RT).
- RTX 4060 Laptop 8 GB + i9-13980HX (v0.5.1, raport #68): 5-7 fps w celi, 3-4 w ruchu;
  215 z 275 ms na GPU.
- Obraz: oswietlone pomieszczenia, ambient + sky light, pelne tekstury. 25 200 z 25 471
  pipeline'ow graficznych prebudowanych; 71 mesh shaderow >32 KiB waliduje sie tylko
  w parze z PS (`SCARLETT_LINK_PAIRS`).
- Wymagania: 32 GB RAM zalecane; przy 16 GB staly pagefile 32-48 GB (mamy 48 GB na D:).

## 4. Idee przenoszone do XCL (bez kodu)
1. **Rozmiar buforow rekordu two-pass** - nasz `execute_indirect` zadawal stale 32 MB na liste;
   przy `max=1` to tysiace razy wiecej niz potrzeba. 63 listy zrobily 952 MB VRAM w 20 s
   (181-201 s) na karcie zajetej po ~9 GB z 8 GB - dokladnie w sekundzie impasu.
   Poprawka: `max * mesh_groups_per_record * record_bytes` (reszta przez `ensure_res_buffer`).
2. **`SCARLETT_PIPELINE_WAIT_MS=0`** - klatka nie czeka na pipeline w budowie, pomija draw.
   Nasz impas to `pc_call` (submit/placement) >45 s, nie bind - najpierw etykieta `pc_call`,
   potem decyzja.
3. **`SCARLETT_BVH_INPUT_SKIP`** - pomija przygotowanie wejscia BVH przy RT off. W XCL
   `XboxBvhBuilder.dll` jest zwyklym compute, wiec trzeba znac hashe tych shaderow.
4. **`SCARLETT_LINK_PAIRS`** - mesh >32 KiB laczy sie z PS zamiast odrzucac.
5. **Pamiec (0.5.7)**: OOM backoff, commit gate, czyszczenie tabeli tekstur.

## 5. Przebieg referencyjny na tej maszynie (w toku)
- Pobrane `ScarlettPort-v0.5.7-win64.zip` (13 979 811 B), SHA-256 zgodny z release.
- `prepare --jobs 8`: exit 0 w 240 s, shadery przetlumaczone (1 malformed, niekrytyczny).
- Pierwszy `run --console series-s --execute`: po 420 s nadal budowal pipeline'y mesh na zywo
  (bez `--all` prepare nie prebudowuje grafiki) - zatrzymany, do swiata nie doszedl.
- Nastepnie: `prepare --all --jobs 8`, potem run z dluzszym oknem i pomiarem fps.
- Uwaga: `SCARLETT_CAPTURE_LOG`/`frames.csv` dziala w buildach diagnostycznych; release
  moze nie pisac CSV - fps trzeba zmierzyc z okna/ETY lub ich logu.

## 6. Decyzja
Hybryda: ich engine jako dzialajacy wzorzec i pomiar fps na tej karcie; XCL dalej jako nasz
runtime, z wdrozonymi ideami (bez kodu GPL-3.0).

## 7. Pierwszy dzialajacy obraz na tej maszynie (referencja)
- v0.5.7, Series S, RT off, ustawienia z `play-scarlett.ps1` + `SCARLETT_FAST_BOOT=1`
  + `SCARLETT_PIPELINE_BOOK=1`. Przebieg rejestrujacy trwal ~20 min (zabity po 900 s),
  gra doszla do swiata i byla w celi z Lucia.
- Zrzut ekranu (12:03 lokalnie): "Americas | ScarlettPort | **4 fps 238.6 ms/frame
  2551 draws/frame**". To dolna granica: pipeline'y budowane na zywo.
- `prepare` z ksiedze: 2147 pipeline'ow w 37 s (4 bez host pipeline). To nie jest pelne
  25 200 - te ida z wlasnego cache gry przez `pipeline-cache --fill`.
- W logu widac ich wlasne statystyki per-frame (np. 27,4 ms oczekiwania na karte,
  24,7 MB wysylane, 43,3 MB ladowane, 5,1 ms odswiezania tekstur) - do porownania z naszym
  `hold:`/`memory:`.

## 8. Wniosek dla celu 10 fps
- Na RTX 4060 Laptop 8 GB ich engine daje 4 fps w celi bez pelnej prekompilacji; ich wlasny
  raport dla tej karty (v0.5.1) to 5-7 fps, a 12-13 fps mialo miejsce na RTX 3060 12 GB
  po pominięciu BVH. Czyli 10 fps na tej karcie nie jest jeszcze osiagniete przez nikogo.
- XCL: nasz bloker to nie shader, tylko VRAM/eviction (bufory two-pass) i jeden `pc_call`
  trzymajacy tytol; test po poprawce buforow w toku.
