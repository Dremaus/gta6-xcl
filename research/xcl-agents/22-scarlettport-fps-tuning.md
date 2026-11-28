# 22 - ScarlettPort: strojenie fps na RTX 4060 Laptop 8 GB

Data: 2026-11-28. v0.5.7, Series S, RT off, biblioteka 29 607 pipeline'ow. Sesje z padem
(bez syntetycznych naciśnięc), zrzut ekranu co 10 s, fps z tytulu okna co 2 s.
ECC: benchmark-methodology + benchmark (pomiar przed/po, ten sam zakres drawow).
REA: nie dotyczy (pomiary wlasnego runtime'u; brak providera Ghidra dla tytulu).

## Metoda
- Kazda sesja: 600-900 s, gracz wczytuje ten sam save i stoi w celi ~90 s.
- Porownanie w pasmie drawow 3500-4600 (ten sam typ sceny) i szerzej 3000-6500.
- Dodatkowo ich wlasne rozbicie klatki z logu (`fps, ms/frame (preparing ... GPU ... copying back)`).

## Baseline (play1)
- Pasmo 3500-4600: 47 probek, **p50 5 fps / 205,4 ms**, p90 258,6.
- Szeroko 3000-6500: p50 245,3 ms, p90 660,5, srednia 361,3.
- Rozbicie klatki: **4,0 fps / 252,8 ms**: preparing 139,6 ms (kopie 33,4 ms / **71,2 MB**,
  tekstury 10,5 ms / 37,2 MB), **GPU 19,1 ms**, **copying back 63,5 ms / 24,4 MB**,
  5278 drawow, heap pass 17,3 ms.
- Obraz: cela z Lucia poprawna (oswietlenie, tekstury, rim light); cinematic 1 fps / 720 ms;
  menu 5 fps / 190 ms przy 4198 drawach.

## tune1 - pakiet ciec kopii/hashy: REGRESJA
`SCARLETT_KNOWN_WRITES=1; SCARLETT_FAST_HASH=1; SCARLETT_CARD_REHASH_RUNS=1; SCARLETT_TEXTURE_HASH_EVERY=0`
- Pasmo 3500-4600: p50 **4 fps / 281,7 ms** (gorzej niz baseline 205,4).
- Log: "a texture picked by index changed after its upload with nothing to tell of it:
  uploaded again" - wylaczenie ciaglego hashowania tekstur powoduje ponowne uploady.
- Wniosek: odrzucone.

## tune2 - `SCARLETT_TEX_SPAN_PCT=10`: NEUTRALNE
- Pasmo 3500-4600: p50 4 fps / 261,1 ms (16 probek), ale szeroko 3000-6500:
  p50 245,3 -> 247,1 ms, p90 660,5 -> 625,4, srednia 361,3 -> 340,1.
- Ich rozbicie: tekstury 10,5 -> **6,2 ms**, heap pass 17,3 -> **1,9 ms**, kopie 33,4 -> 30,4 ms,
  copy back 63,5 -> 56,6 ms; GPU 17,6 ms.
- Wniosek: nie szkodzi, ale nie przelamuje progu; zostawic jako opcje.

## Wniosek ogolny
- GPU to ~18-19 ms (53-55 fps), reszta to kopie i przygotowanie (~200 ms). Cel 10 fps (100 ms)
  wymaga ciecia ~2x pracy kopiujacej, nie rozdzielczosci.
- Kolejny test: `SCARLETT_REBAR=2` (kopie hosta i bufory tytulu w CPU-widocznej VRAM).

## tune3 - `SCARLETT_REBAR=2`: lepsza ogona, gorszy p50
- Szeroko 3000-6500: p50 240,4 ms, **p90 337,2** (baseline 660,5), srednia 300,4.
- Ich rozbicie: kopie 25,7 ms / 64,5 MB (bylo 33,4 / 71,2), tekstury 4,1 ms / 8,5 MB (bylo 10,5 / 37,2),
  GPU 8,3 ms (bylo 19,1), copy back 58,6 ms / 26,6 MB.
- Sesja: p50 4 fps. Wniosek: mniej dlugich zacieć, ale p50 bez zmiany.

## tune4 - `REBAR=2 + HELPER_PRIORITY=1 + TEX_SPAN_PCT=10`: NAJLEPSZY DOTAD
- Szeroko 3000-6500: p50 **219,3 ms** (baseline 245,3), p90 **306,9** (660,5), srednia **273,1** (361,3).
- Sesja: **p50 5 fps, p90 5, max 6** (168 probek).
- Zysk: ~11% na p50, ~54% na p90, ~24% na sredniej. To ogranicza zaciecia, ale nie przełamu je progu.

## Stan celu
- 10 fps = 100 ms/klatke. Najlepszy zestaw daje ~219 ms p50; GPU to 8-19 ms, reszta to kopie
  i przygotowanie. Bez zero-copy lub zmiany architektury kopii cel jest poza zasiegiem przelacznikow.
