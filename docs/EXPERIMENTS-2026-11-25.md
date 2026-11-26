# Eksperymenty wydajności — 2026-11-25

Wszystkie pomiary na RTX 4060 Laptop 8 GB / 16 GB, ten sam build 1.0.2.1.
FPS/ms z title bara; VRAM z `nvidia-smi`; szczegóły z `game-stderr.log`.

| Wariant | Ustawienia | fps | ms/klatkę | draws | VRAM | Wniosek |
|---|---|---:|---:|---:|---:|---|
| **Baseline** | 1080p, ambient 0.6, cold cache | 0,2–1 | 1 317–4 017 | 1 011–3 504 | 7,5 GB | CPU/pipeline/VRAM bound |
| **E1** | warm 25 889 shaderów (`VICTORY_HOST_WAVE=32`, `VIEW_LIMIT=1M`) | — | — | — | cache 0,82 GB | 23 815 translated, 1 868 cached, **206 unsupported** (195 GS, 10 PS, 1 CS) |
| **E1+E2/E3** | 720p, ambient 0, levels on demand, late wait 3, wide back, back own view, shader loop 256 | **1–2** | 649–1 551 | 568–1 143 | 7,5 GB | ~2–4× poprawa, ale VRAM na limicie |
| **E2b** | + texture budget 4096 MB, card buffers 768 MB | **1** | 1 112–1 253 | 656–1 302 | **5,3 GB** | VRAM zwolniony, FPS bez zmian → **CPU/submit-bound** |

## Co to znaczy

- Warm cache + E2/E3 dały realną poprawę (0,2–1 → 1–2 fps), ale nie 30.
- E2b dowiódł, że VRAM nie jest już wąskim gardłem: 2,2 GB mniej, ten sam fps.
- GPU 0% w chwili pomiaru, CPU ~100%: klatkę blokuje CPU/submit/streaming.
- 30 fps = 33,3 ms; obecnie 1 112–1 253 ms → **~33–38× za wolno**.

## Następny cel code-level (E3b)

Logi wskazują **descriptor/heap sync** jako największy pojedynczy koszt:
- nasze: heap/descriptor pass **950–2 708 ms** na klatkę,
- fxceless: po tanim fingerprintcie **70–220 ms → ~3 ms**.

To jest realny cel: port taniego fingerprintu i pozostawienie slotów tablicy
drawom (z fxceless/AnyXboxX, GPL-3.0) do VItoriaBr. Potencjał: ~1–2,7 s/klatkę,
czyli z 1 fps do może 2–4 fps. Nadal nie 30, ale to właściwy kierunek.

## Bramki

- G1 5 fps: E3b + E2b + warm cache.
- G2 10 fps: redukcja kopii/streamingu i submit.
- G3 20 fps: natywny render graph/batching.
- G4 30 fps: static recompilation/native renderer, jeśli warstwa nie wystarczy.

## fxceless (E1-F) — nowa baza

- Build release: 1,4 min; pre-flight **0 missing**; ten sam build 1.0.2.1.
- Zimny 3D: **0–1 fps**, 1 055–3 647 ms, **1 311–4 992 draws**, VRAM 6,65 GB,
  GPU 0%, CPU ~100%. Optimizations z fxceless nie przenoszą 2–4 fps na 8 GB/16 GB.
- Patch: **`VICTORY_FULLSCREEN=1`** — borderless popup na primary monitor;
  swapchain zostaje 720p i jest stretchowany, bez paska/DWM.
- `--warm all`: **25 635** shaderów, 254 nieobsługiwane, 3,8 min.
- Fullscreen `VICTORY_FULLSCREEN=1`: czarny ekran (720p swapchain → 1080p popup);
  wyłączone, zostaje okno.
- Agresywny profil (relay=2, join parts, indirect gather): **GPU device removed
  (TDR)** po wejściu w 3D; `VICTORY_RELAY=1`, 11 list.
- Stabilny profil (relay=0, join/gather/back-own-view off, library map off,
  texture 4096, card 768): **0–1 fps**, 1 824–2 705 ms, 1 519–5 183 draws,
  VRAM 7,7 GB, GPU 0%, bez crasha w 150 s.

**Wniosek:** warstwa (VItoriaBr i fxceless) ma zmierzony sufit **1–2 fps** na
RTX 4060 8 GB / 16 GB. 30 fps wymaga native path, nie kolejnych przełączników.

## E3b + Arm B — opt build + staging 24 ms (2026-11-25 21:56)

- Agent A patch (VItoriaBr-opt, +140/−13): buffer table deferral; `heap_buffers`
  buffer slots 28k–70k, **870–1 606 left to draws**; descriptor sync already cheap.
- Agent E Arm B (`TEXTURE_CATCHUP=0`, `STAGE_MS=24`, `STAGE_MB=64`):
  **texture pass 759–1 561 ms → 13,8–29,5 ms** — fix działa.
- FPS nadal **0,3–1,9** (528–3 319 ms); teraz dominują **copies 189–1 308 ms**
  i **copy-back 132–324 ms**; textures 26–302 ms; GPU 0–37 ms.
- Po chwili: **GPU device removed** (21:56:58, 1 submission/1 list) — TDR nadal.
- Wniosek: staging fix jest realny, ale przesunął bottleneck na kopie/copy-back;
  stabilność wymaga safe profile + DRED. Patch A jest neutralny dla FPS, ale
  zmniejsza buffer pass; zostaje za flagą `VICTORY_HEAP_BUFFERS_TABLES=1`.

## Safe + Arm B (Agent J + E), 22:06

- 0–1 fps, 1,5–3,8 s, 510–2 603 draws; heap 130–272 ms; copies 347–545 ms;
  **copy-back 381–1 613 ms**; GPU 420–647 ms. Gra wyszła/TDR ponownie.
- Safe profile wyłączył relay/queue2/async — staging fix został, ale copy-back
  stał się głównym kosztem. Wniosek: nie ma darmowego profilu; potrzebny DRED,
  żeby zobaczyć, który command/resource zabija GPU.

## TDR triage (Agent J)

- `0x887A0007` = `DXGI_ERROR_DEVICE_RESET`; `0x887A0004` to DRED query w release
  bez `diagnostics`, więc „no breadcrumbs” nie jest wskazówką.
- Ostatni wait **15,9 ms** — to nie klasyczny 2 s TDR; device loss wykryty w
  `draw.rs` przy przygotowaniu tekstur. Jedna submission nie skończyła
  (18 164 started / 18 163 finished) → możliwy hang GPU.
- VRAM 7,7/8,0 GiB i 16 GB RAM to **wzmacniacze**, nie dowiedziony root cause
  (VItoriaBr stabilny przy 5,3–7,5 GB).
- Pipeline library 211,8 MB; część PSO nie ładuje się (`0x80070057`) i rekompiluje
  13–14 s. W chwili crasha **nie była mapowana** — mapowanie nie jest bezpośrednim
  triggerem.
- Brak `Display 4101/4102`/`nvlddmkm` w czytelnym System log; ASPM = maximum power
  savings; brak throttlingu (42–52 °C).
- Root cause wymaga **diag + DRED**: `VICTORY_D3D12_DEBUG=1`, `VICTORY_D3D12_DRED=1`,
  krótki repro; nie podnosić `TdrDelay` jako „fix”.

Safe 8 GB profile (launcher `D:\Gry\fxceless-data\Launch-Fxceless-Safe.ps1`):
relay/late/join/gather/back-own-view/async/queue2 off, library map off,
texture 3072 MB, card 512 MB, staging 256 MB, inplace 2048 MB, levels on demand,
frame log + driver watch. Kolejność: S1 30 min → S1-H `VICTORY_HEAP_TEXTURES=0`
15 min → S2 headroom → S3 library isolation → S4 ASPM/power → S6 driver A/B.

## Zasada

Nie ogłaszamy 30 fps bez G4. Ale nie zakładamy porażki: każdy wariant ma pomiar,
a E1–E2b dały pierwsze realne poprawy.

## Noc 26.11 00:00-01:20 � UNCAP, borderless, trzy nowe klasy crashy

| Run | Build/env | Efekt |
|---|---|---|
| PID 15444 | opt -Memory -Borderless | menu 30.0 fps stabilne 2 h, zero crash |
| PID 27620 | opt +DPI +AgentA modules +Uncap | xmem batch ON: assert 0x80000003 @image+0xf2cc4b po ~3 s (powodowany przez Scatter coalescing, bled 487) � naprawione przez Agent A (map_run split-back) |
| PID 25700 | opt +Uncap +NoXmemBatch | **menu 60.0 fps / 16.7 ms** � cap gracza zdjety |
| PID 34544/38384 | warianty input | SendKeys NIE dociera do gry (injectia odrzucana) � do sterowania menu dziala tylko VICTORY_KEYS (diagnostics) |
| PID 20920 | opt +Keys (skrypt Enter/Y/Enter) | wejscie do 3D! 868->5966 draws, 1 fps, device removed 0x887A0007 po ~90 s w swiecie |
| tdr-on 18372 | VICTORY_RELAY_SAFE=1 (Agent M gate) | gate uzbrojony, crash identyczny � H5 (kolejnosc na prostej kolejce) ODRZUCONA |
| tdr-safe 7420 | relay family OFF + Uncap | rowniez device removed po 2.5 min w 3D � rodzina relay NIE jest przyczyna |
| safe-mem-keys 27236/32356 | SafeMem + Keys | DETERMINISTYCZNY AV gracza 0xc0000005 @image+0x11170ae (2/2, ~60 s, ekran profilu): petla po tablicy punktorow (stride 80, entry+0x20 -> obiekt+0x78), obiekt w VA 'reserved, never committed' |

Wnioski: (1) cap 30 = game-side XBoxSystem set_interval 33333us, zdj�ty VICTORY_UNCAP; (2) 3D crash
wystepuje w kazalej kombinacji przelacznikow � dwa sygnaturowe sciezki (GPU reset w swiecie; AV
niezacommitowanych stron w menu) � prawdopodobnie wspolna przyczyna: uszkodzone/puste strony obiektow
tytulu; (3) borderless + DPI dzialaja (screenshot: pelny ekran bez ramki, 2560x1600 fizyczne).
Narzedzia: Click-At.ps1 (klik w wspolrzednych), Foreground-Check.ps1, Launch-TDR-Gate.ps1 (-Gate on/off/safe),
VICTORY_KEYS='25:Enter,45:Y,58:Enter,72:Enter,90:Enter' � protokol wejscia do swieta.

## 05:55 � VEH retry dla okien remapingu (watch.rs)

Dodane w VItoriaBr-opt branch night-2026-11-26 (commit na HEAD 5a84eb4):
on_write VEH obs�uguje teraz te� READ AV na stronie MEM_RESERVE: czeka na
title_memory_reading (zwolnienie guardu remapingu, kt�ry commituje pod tym
samym gwardelem w map_warn) i wznawia instrukcj�, je�li strona jest ju�
commitowana; WRITE AV na stra�y niechronionej bloku � ta sama �cie�ka po
drop(guards). this_thread_remapping (TLS) chroni przed deadlockiem.
Efekt na �ywo (SafeMem+Keys): znikn�y oba deterministyczne AV-y
('reserved, never committed' @image+0x11170ae/0x11171a8 i zapis warstwy
victory.exe+0x65709e). NOWY, trzeci objaw (ostatni stan nocny, do rana):
read 0x516a22ec0 'read-write' @image+0x4e8b4b4 � gra czyta stron�, kt�ra W
CHWILI FAULTU jest ju� commitowana i odczytywalna (wywiad VirtualQuery w
handlerze), a mimo to instrukcja AV � nast�pne podejrzenie: access
przez guard page (PAGE_GUARD bit w Protect) albo race protection-between-
pages; wymaga analizy Protect (nie tylko State) w reserved()/writable()
i logowania flagny. Testy victory-gpu 177/177 zielone, victory-hle 109/109.

## 06:00 � Anatomia kosztu klatki 3D (parse_frame_cost.py na trzech nocnych runach)

| Run (profil) | ms/frame 3D (mediana) | draws med | preparing med | copies med | render-ran med (user+kernel) | present med |
|---|---|---|---|---|---|---|
| tdr-on (relay family ON, gate) | 1881 | 3738 | 928 | 276 | 16 (8+16) | 358 |
| tdr-safe (relay OFF) | 1369 | 3058 | 414 | 218 | 618 (141+375) | 8 |
| opt-new (rodziny mix, uncap) | 631 | 3302 | 426 | 195 | 16 (0+16) | 308 |

Wnioski (co zjada klatk� 600-1900 ms przy ~3000 draw�w):
1. 'preparing' (stage'ing klatek Warstwy: kopie+tekstury+heaps) = 30-50 % czasu � 414-928 ms.
2. Czas GPU-na-karcie widziany jako 'present' 300-360 ms (relay ON) � karta realnie r�ki
   klatki d�u�ej ni� CPU warstwy; przy relay OFF w�druje do kernela (375 ms) render-threadu.
3. Per-draw ? 0,2-0,6 ms � nawet zerowanie kosztu per-draw (plan Agenta K) da co najwy�ej
   ~2x, a do 30 fps (33 ms) brakuje 20-50x � potwierdzenie sufitu layera; natywna �cie�ka (S0)
   pozostaje jedyn� drog� do celu, a warstwa przydaje si� jako capture-oracle (format DPR).
Narz�dzie: D:\git\gta6-30fps\tools\bench\parse_frame_cost.py <log...>.

## Claude 26.11 rano - trzecia klasa crasha (read AV na stronie "read-write")

Objaw: unhandled 0xc0000005 @image+0x4e8b4b4 (read 0x516a22ec0: 'read-write'), 40-90 s po starcie
SafeMem+Keys, juz z VEH retry z 05:55.
Przyczyna (potwierdzona): NIE PAGE_GUARD. Straze watch.rs to PAGE_READONLY (odczyt nie fauluje),
a crash.rs memory_at() nazywa guard page osobno ('a guard page'), nie maskuje bitu. To TOCTOU w
on_write: odczyt gosci fauluje w szczelinie remapingu (unmap -> placeholder -> MapViewOfFile3 ->
commit pod MAPPING), ale zanim VEH zapyta VirtualQuery, remaping juz sie skonczyl -> reserved(at)
== false -> CONTINUE_SEARCH -> breakpad. Crash reporter pyta jeszcze pozniej, stad 'read-write'
(te same 'read-write' maja w crashes.log stare AV-y klasy 2, o ktorych wiemy, ze byly w szczelinie).
Surowe wartosci z handlera (VICTORY_GUARD_READ_STATS=1), pierwsze spojrzenie VEH:
  State=0x1000 (MEM_COMMIT) Protect=0x4 (PAGE_READWRITE, bez 0x100 PAGE_GUARD) -> 'late' fault.
  Miejsca: image+0x1510c39 (read 0x6d6930010, 2x, ~65 s), image+0x4dd4005 (read 0x517a27474),
  image+0x55d3752 (read 0x525e9ae78). Zwykle (w szczelinie): State=0x2000 Protect=0x0 -> po czekaniu
  State=0x1000 Protect=0x4.
Fix (VItoriaBr-opt main 1944123, crates/victory-gpu/src/watch.rs): kazdy READ AV poza watkiem
remapingu czeka na remaping w toku (title_memory_reading; pomijane gdy watek juz trzyma MAPPING
shared - nowy licznik TLS READING_DEPTH, inaczej deadlock za czekajacym writerem) i wznawia
instrukcje, jesli strona jest teraz odczytywalna (MEM_COMMIT, bez PAGE_GUARD/NOACCESS). Limit 64
retry tej samej strony na watek bez zakonczonego remapingu pomiedzy (REMAPS_DONE), potem fault idzie
dalej. Kolejnosc lockow bez zmian (guards() nie trzymany w sciezce odczytu). Przelaczniki:
VICTORY_GUARD_READ_STATS=1 (linia na stderr na kazdy read fault, surowe State/Protect przed/po),
VICTORY_READ_RETRY=0 (stara regula: tylko gdy strona byla MEM_RESERVE przy pierwszym spojrzeniu).
Testy: victory-gpu 181/181 (177 + 4 nowe w watch::mapping_tests, m.in. odczyt, ktory fauluje na
stronie NOACCESS i wraca po remapingu -> LATE_READS), victory-hle 109/109. Flake WARP sie nie pojawil.
Runy (SafeMem+Keys, release+diagnostics):
| run | tryb | zyl | late faulty | koniec |
|---|---|---|---|---|
| A 04:56 | READ_RETRY=0 (stary) | ~9 min | 0 (21 w szczelinie, retried) | GPU device removed (znana klasa) |
| B 05:06 | fix | ~4:40 | 2 @+0x1510c39 retried | GPU device removed (znana klasa) |
| C 05:11 | fix | ~7:40, 3D do 14096 draws | 2 retried | NOWE: int3 0x80000003 @image+0x5149aec |
A nie odtworzyl AV (klasa 3 jest losowa, w A po prostu nie trafil late fault); B i C trafily po
2 late faulty kazdy - stary kod zabilby oba procesy, nowy przezyl. Klasa 3 zniknela.
Nastepne: czwarta klasa - assert tytulu int3 @image+0x5149aec (stos +0xa5db22, +0x5453ac7,
+0x23d0f9a), bez debug output tytulu; i nadal GPU reset w swiecie (nie moje).

## Czwarta klasa: int3-forensyka (Claude #2)

Drzewo: D:\git\VItoriaBr-tdr (bylo kopia bez .git -> `git init`, branch tdr-int3: 61bcf22 baseline
"as found" = main 5a84eb4 + lokalny host.rs (wybor adaptera high-performance, VICTORY_RELAY_SAFE);
cf0abd7 port fixow klas 2-3 z opt 1944123 (watch.rs + xmem.rs - tdr ich NIE mial, wbrew zalozeniu,
bez nich run nie dozylby int3); b19785a + ef2bde0 instrumentacja). Launcher:
D:\Gry\VItoriaBr-data\Launch-SafeMem-TDR.ps1 (TDR_NOWATCH=1 / pool przelacza watch).

WERDYKT mem-vs-file: int3 jest W PLIKU, to assert tytulu - zadnej korupcji .text.
- Zalozenie "w pliku nie ma 0xCC" bylo bledne: offset pliku = RVA - 0xC00 (.text va 0x1000, raw 0x400).
  Plik @+0x5149aec: `... 3d fe ff 01 00 | 74 60 | ...` (0x5149a85 cmp eax,0x1fffe; 0x5149a8a je
  0x5149aec) i pod 0x5149aec `cc 31 ff ...`. "85 ed" to bajty spod offsetu 0x5149aec (= RVA 0x514a6ec).
- Linia z handlera (run 4, 8m41s): `int3 forensics: rva=0x5149aec mem=cc 31 ff 48 89 f8 48 83 c4 28 5f 5e
  c3 89 f1 48 file=cc 31 ff 48 89 f8 48 83 c4 28 5f 5e c3 89 f1 48 verdict="the file has the int3"
  state=0x1000 protect=0x20 type=0x1000000 page_int3s_not_in_file=0 page_bytes_differing=0`.
- Run 1 (watch 64 KiB chunkow calego .text co 30 s, 5 min): zero zmian kodu, zero regionow
  zapisywalnych. Tytul nie importuje VirtualProtect/WriteProcessMemory/FlushInstructionCache, a przez
  GetProcAddress pyta tylko o CondVar, Api*Impl, XErrorReport, MiniDumpWriteDump.
- +0xf2cc4b (stara klasa) tez jest w pliku: `call 0x5f3fd20; test eax,eax; jnz +1; int3`, a 0x5f3fd20 =
  `jmp [IAT 0x6793a48]` = xmem.dll!XMemMapPhysicalPagesScatter -> stara atrybucja do xmem (klasa 1,
  blad 487) byla PRAWIDLOWA.

Co to za assert: wyczerpana lock-free pula obiektow stalej wielkosci. Funkcja alloc +0x5149980
(wirtualna, w 5 vtablach; druga kopia +0x2055960): head = [pool+0x20] (17-bitowy indeks + tag ABA
w gornej polowie), 0x1fffe = lista pusta -> int3. Rejestry we wszystkich rekordach: rax=...0001fffe,
rcx=0xdfcf8b420 (ta sama pula co run), edx=0xc. Globalny wskaznik puli: image+0xa9ec938.
Naglowek: base 0xdfcf8b480, element 0xe0 (224 B), pojemnosc 0x57e4 = 22 500, bitmapa 0xdfd459c10.
Krzywa (run 5, VICTORY_POOL_WATCH, 8m23s, int3 o 503 s):
| t | in_use | tag (=liczba zwolnien) | fps |
|---|---|---|---|
| 40 s | 0 | 0 | 30 (menu) |
| 70 s | 7 319 | 1 | 30 |
| 161 s | 9 220 | 0x136 | 0.2-0.6 (3D od ~95 s) |
| 312 s | 13 900 | 0x2c4 | 0.3 |
| 433 s | 18 530 | 0x35a | 0.4 |
| 493 s | 21 454 | 0x35a | 0.3 |
~34 alokacji/s (~90 na klatke 3D), zwolnien lacznie 858 i od ~430 s ZERO. Zwalnianie: jedyne miejsce
+0x51f2c80 (lock dec [pool+0x10] + push), wolane z +0x51f20f0 = flush listy odroczonych usuniec
(petla po tablicy wskaznikow: release do puli albo vtbl[0](obj,1)); flush wolany z +0x336879,
+0x9d9d15, +0x22a2374 (dwa ostatnie obok ramek glownej petli z klasy 3: +0x9dd0c2, +0x22a2a99).
Producenci: watki job-systemu (8 watkow trafilo assert naraz, wspolna ramka startowa +0x2215eca).

Wniosek: to nie korupcja ani zapis warstwy w obraz - tytul wycieka obiekty, bo odroczone usuwanie
prawie nie nastepuje. Na konsoli przy 30 fps 90/klatke zapelniloby pule w ~8 s, wiec flush musi tam isc
co klatke. Hipoteza do sprawdzenia (najostrzejsza): flush jest bramkowany postepem GPU (fence/EOP
"klatka N skonczona", ktory tytul czyta z pamieci) - zapis zwrotny fence'ow przez warstwe zostaje coraz
bardziej w tyle (przy 0.3 fps i ~850 ms "on the GPU"/klatke), az zwolnienia staja. Alternatywa: flush
jest per-klatka i limitowany, a producenci ida w czasie zegarowym - wtedy to po prostu skutek 0.3 fps.
HANDOFF (nastepny krok): w warstwie logowac na klatke ostatnia wartosc fence/EOP zapisana tytulowi vs
ostatnia zasubmitowana, obok `tag` puli (VICTORY_POOL_WATCH=ga9ec938 juz jest); jesli zwolnienia staja
razem z rosnaca luka fence -> fix w sciezce zapisu zwrotnego fence'ow; jesli fence nadaza -> problem
wydajnosci (0.3 fps), nie poprawnosci. Gdzie szukac w tytule: wejscie do +0x336740 / +0x9d9cc0 /
+0x22a2370 (warunek przed wywolaniem flush). Fixu w kodzie warstwy NIE ma (przyczyna po stronie tytulu,
wyzwalacz po stronie warstwy niepotwierdzony).

Runy (tdr, release+diagnostics, SafeMem+Keys):
| run | watch | zyl | koniec |
|---|---|---|---|
| 1 | obraz+kod | ~5 min, 3D 14062 draws | cichy koniec, brak WER (prawdopodobnie zabity z zewnatrz) |
| 2 | obraz+kod | ~80 s | cichy, brak WER |
| 3 | obraz+kod+pula | 56 s | exit 0xC0000409 (fail-fast), bez rekordu |
| 4 | brak (sama forensyka) | 8m41s, 3D 11674 | int3 +0x5149aec, linia forensyki j.w. |
| 5 | sama pula | 8m23s | int3 +0x5149aec, krzywa j.w. |
Uwaga: watek pelnego watchu kodu (hash 100 MB .text co 30 s + strony co 100 ms) jest podejrzany o
fail-fast w runach 2-3 (bez niego oba runy doszly do int3) - uzywac VICTORY_POOL_WATCH samego albo
VICTORY_IMAGE_WATCH tylko na krotko. Rownolegle chodzil tez run Agenta P (opt, PID 36028) - jeden run
mi przez to padl od razu; gry nie wolno odpalac rownolegle.
Testy tdr: victory-loader 29+3, victory-hle 109, victory-gpu 196 (z diagnostics) - zielone.
