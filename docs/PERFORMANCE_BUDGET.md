# Budżet wydajności — 30 fps

## Definicja

- 30 fps = **33,33 ms/klatkę** (p50), p95 ≤ 40 ms.
- 60 fps = 16,67 ms (poza celami tego etapu).
- Scena referencyjna: pierwszy pokój / prolog, ten sam save, ta sama kamera,
  bez cutscene, 3 przebiegi, mediana.

## Baseline (zmierzony / z README)

| Wariant | Sprzęt | ms/klatkę | fps | draws/frame |
|---|---|---:|---:|---:|
| VItoriaBr, RTX 4060 8 GB/16 GB | ten laptop | 1 317–4 017 | 0,2–1 | 1 011–3 504 |
| VItoriaBr, RTX 5060 Ti 16 GB/40 GB | README | ~167 | ~6 | 3 500–4 400 |
| fxceless, RTX 4070 12 GB/32 GB | README | 104 (97 z dodatkami) | 9,6–10,3 | 3 850 |
| AnyXboxX, RTX 4070 Super | README | ~185–208 | 4,8–5,4 | 6 550 |
| XCL, RTX 5090 | README | ~200 | ~5 | nie podano |

## Matematyka celu

Dla 3 850 draws i 33,3 ms:

- 33,3 ms / 3 850 = **8,65 µs/draw** all-in.
- fxceless: 104 ms / 3 850 = **27 µs/draw** → potrzebne **~3,1×** mniej.
- CPU submit w fxceless: ~81–95 ms/klatkę → musi zejść do **<20 ms** (~4–4,7×).
- GPU card w fxceless: ~87–102 ms → musi zejść do **<30 ms** (~3–3,4×).
- 50 ms z tego to własne passy gry przy 2560×1440; 720p obniża koszt pikseli,
  ale nie geometrię/compute.

Na RTX 4060 8 GB jesteśmy dodatkowo wolniejsi od RTX 4070 12 GB i mamy 8 GB VRAM
zamiast 12 GB. Dlatego 30 fps na tym laptopie wymaga **nowej ścieżki**, nie tylko
przełączników.

## Zakres poszukiwań (bounded loop)

- Max 12 wariantów, 2 tygodnie, bez zakupu sprzętu.
- Każdy wariant: jedna hipoteza, ten sam input, 3 przebiegi.
- Odrzucamy: brak poprawy > 5%, błąd correctness, device loss, niereprodukowalne.
- Promocja: correctness + powtórzona delta + rollback + commit + dokumentacja.

## Warianty M2 (CPU)

1. `VICTORY_INDIRECT_GATHER=1` + `VICTORY_CARD_REHASH_RUNS=1` (mniej clampów).
2. `VICTORY_JOIN_PARTS=1` (mniej submissions).
3. `VICTORY_BACK_OWN_VIEW=1` (mniej copy-back).
4. `VICTORY_ASYNC_SUBMIT=1` + `VICTORY_QUEUE2=1` (submit/copy poza render thread).
5. `VICTORY_COPY_PLAIN=1` + `VICTORY_TEXTURE_NO_WAIT=1`.
6. Własny batch descriptor/heap sync (poza przełącznikami).

## Warianty M3 (GPU)

1. Offline PSO cache + `--pipelines` (zero kompilacji w klatce).
2. `VICTORY_SHADER_OPT` (clean-up passy; fxceless: ~43% mniej instrukcji).
3. 720p / FSR; docelowo 1080p.
4. Redukcja overdraw/RT; wyłączenie RT/BVH (i tak off).
5. Shader translation fixes dla brakujących pipeline'ów.

## Warianty M4 (pamięć)

1. `VICTORY_LEVELS_ON_DEMAND=1` (mniej VRAM na poziomy).
2. `VICTORY_STAGING_POOL_MB=1024` (reuse staging).
3. `VICTORY_CARD_BUFFERS_MIN_MB=1`, `VICTORY_CARD_BUFFERS_MB=1024`.
4. 16 GB RAM: pagefile 32 GB na D:, zamknięte aplikacje; unikać 1455.
5. Prekompilacja shaderów/pipeline'ów przed grą (cache 13 GB).

## Bramka promocji

Wariant zostaje domyślny tylko jeśli:

- przechodzi correctness gate (obraz, brak device loss, postęp gry),
- delta jest powtórzona lub wyjaśniona,
- rollback jest oczywisty (env/commit),
- jest w repo/runbooku,
- raport zawiera dokładne komendy i pomiary.

## Realistyczny wynik

- Menu: 30 fps (cap gry).
- 3D: 1–6 fps na tym laptopie; 30 fps wymaga natywnego portu/renderera i
  prawdopodobnie 16 GB VRAM / 32 GB RAM. To nie jest obietnica; to hipoteza do
  obalenia w M5.
