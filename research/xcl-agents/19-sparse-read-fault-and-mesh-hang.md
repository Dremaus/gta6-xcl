# 19 - sparse read fault (naprawiony) i zatrzymanie po pierwszej klatce 3D

Data: 2026-11-28. XCL branch `fix/sparse-read-fault` (cd367d57, 0aec80f9, 73199c9f).
ECC: agent-introspection-debugging (capture -> diagnoza -> izolacja). REA: nie dotyczy
(dowody z logu XCL, PDB xcl.exe i DRED; cel REA game_scarlett_master.exe dalej bez providera Ghidra).

## 1. Crash CPU 0xC0000005 przy ~85 s i ~101 s - NAPRAWIONY
- Symbolizacja (nowy `examples/sym.rs`, dbghelp przez windows-sys; dbghelp potrzebuje SizeOfImage
  z naglowka PE, bez niego ImageSize=0 i SymFromAddr daje err 126):
  `detile_level (tiling.rs:464)` <- `title_textures::subresources` <- `refresh_once`
  oraz `xg.rs::copy_from` -> `detile_level` (bez zadnego readable()).
- Przyczyna: tytul robi VirtualFree(MEM_DECOMMIT) na stronach okna sparse (kernelx.rs), a XCL
  czyta je przez wskaznik pozyczony (`title_bytes` -> `Cow::Borrowed`) lub bezposrednio.
  `readable()` sprawdza tylko chwile (TOCTOU), a okna sparse nie mialy obslugi faultu odczytu.
- Poprawka: (a) `title_bytes` nie pozycza wskaznika w oknie sparse; (b) VEH w `sparse.rs`
  commituje strone 4 KiB wypelniona zerami przy odczycie ze strony zdecommitowanej
  (zbior DECOMMITTED prowadzony w commit_range/decommit_tiles) - dziury czytaja sie jako zera,
  zgodnie z `readback_ranges`.
- Weryfikacja: run 085530 i 090140 (300 s): 0 unhandled exceptions, gra przechodzi 85 s i 101 s,
  fps_all_max 58-69. Commit procesu nie urosl przez VEH (18.4 GB przy 48-60 s jak przed).

## 2. Co dalej blokuje 3D (po naprawie)
- t~112 s: pierwszy `DispatchMesh`; t=120 s: `amd_fidelityfx_upscaler_xbox.dll` wola stub
  `ID3D12PipelineState(stand-in)::#11` -> 0 (pierwsza klatka 3D przez upscaler FSR).
- Prezentacje 23/2 s (100-120 s) -> 0 od ~140 s, submity 0. Zrzut 113 s = wygaszana okladka,
  145 s = czern, tytul okna "1274 built, 81 building".
- Kompilacje PSO w sterowniku: pojedyncze compute PSO 745-968 KB DXIL trwaja 18-29 s
  (160, 179, 211, 231 s). Jedyna niedokonczona kompilacja #5341 (MS PSO 452 KB) wystartowala 256.4 s,
  device removed 0x887a0005 o 257.7 s. DRED: page fault VA 0x0, brak alokacji, brak breadcrumbow
  -> prawdziwy hang, nie zly adres.
- VRAM "local" przekracza fizyczne 8 GB od ~84 s (8.9 -> 12.0 GB przy 181 s), commit 27 GB
  przy 16 GB RAM. Nadsubskrypcja WDDM jest kandydatem na degradacje, nie rozstrzygnieta.
- Izolacja z poprzedniego etapu nadal wazna: XCL_SKIP_TWO_PASS=mesh/compute/1 -> brak TDR;
  compute pass nie wisi, wisi dispatch mesh. Ale gra staje tez bez TDR (przebiegi ze skipem),
  wiec sa DWA problemy: (1) blokada na ogromnych PSO, (2) hang GPU w mesh.
- Ostrzezenia: `two-pass ExecuteIndirect(DispatchMesh) skipped: arguments not in a console buffer
  in unified memory` oraz RT AS "not in unified memory - writing empty BVH descriptor".

## 3. Nastepne kroki (kolejnosc)
1. Czy PSO 0.75-1 MB compute (nierozdzielone) mozna dzielic jak `compute split` (127 programow
   podzielonych) - to usuwa 20-30 s blokad.
2. Test nadsubskrypcji: ograniczyc VRAM (np. mniejszy pool sparse / title_memory_mb) i sprawdzic
   czy hang mesh znika.
3. DRED bez breadcrumbow: dodac `SetMarker` wokol two-pass (juz jest dla SetPipelineState)
   albo `XCL_SKIP_TWO_PASS` per-PSO (bisekcja po hashu MS) zeby wskazac konkretny shader.

## 4. Korekta: glowna bariera to commit systemu, nie sam shader (runy 092031, 092422)
- Cieply cache sterownika: graficzne PSO kompiluja sie w ~7 ms, huge compute PSO 29 s -> 199 ms
  (blob z dysku). Stall na kompilacji to koszt PIERWSZEGO uruchomienia, nie stan ustalony; `compute
  split` juz obejmuje te PSO (`chained true`). Punkt 1 z listy kolejnych krokow odpada.
- Run 092031: `command list Close -> 0x8007000e (E_OUTOFMEMORY)` o 162.79 s, potem 0x887a0005 i
  0x887a0001 (device removed). Pierwszy raz widac OOM przed TDR.
- Pomiar commitu systemu co 5 s (run 092422): limit 36.5 GB (RAM 15.7 + pagefile 20.8), przy
  starcie gry INNE procesy/system trzymaja 18.5 GB; commit 31.4 GB po 21 s, 35.5/36.5 GB po 41 s;
  pagefile rosnie na zadanie (limit 44.7 GB po ~180 s); wolny RAM ~300 MB przez caly przebieg.
  Proces gry: 18.5 GB (60 s) -> 24 GB (160 s); VRAM local 9.6 GB na karcie 8 GB.
- Wniosek: stall/OOM/TDR sa zgodne z ciaglym stronicowaniem przy commicie na limicie. Hang mesh
  NIE jest wykluczony (izolacja skip=mesh nadal prawdziwa), ale test jest niemiarodajny dopoki
  system nie ma zapasu commitu. Dzwignie: wiekszy staly pagefile (admin), mniej commitu bazowego,
  mniejszy commit XCL (coherent 3.4 GB od startu, kopie CPU okien sparse 4-5 GB, nonlocal 4 GB).
