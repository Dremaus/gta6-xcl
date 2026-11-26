# Scena referencyjna

Jedna scena, jedno okno, trzy przebiegi. Bez tego pomiary różnych wariantów nie
są porównywalne.

## Tożsamość sceny (z zapisanego stanu)

| pole | wartość |
|---|---|
| TitleID | `7952987A` |
| Slot save | `0009000000000001` |
| Profil | `00000000-0000-0000-0000-00007952987a` |
| Misja | `fbk_stry000_FBK_STRY000_INTRO` (prolog) |
| Pozycja gracza | `<-619.79, 939.80, 3.00>` |
| Pozycja kamery | `<-619.80, 937.45, 3.75>` |
| Kierunek kamery | `<0.1739, 0.9717, -0.1598>` |
| Pools (typowe) | BUILDING 22 481, OBJECT 18 320, PED 61, VEHICLE 15, INSTANCE_LIST 45 000 |
| Draws (typowe) | 1 011–5 183 |

Wartości pochodzą z dumpu telemetrii `victory-*.crash.log` z tego samego save'a
(`docs/EXPERIMENTS-2026-11-25.md`, E1/E2b). Jeśli dump powstanie w trakcie
kampanii, porównaj `Camera Position` i `Player Position` — rozjazd > 2 m oznacza
inną scenę i kampanię trzeba powtórzyć.

## Protokół (użytkownik prowadzi grę)

1. Zamknij grę i wszystkie ciężkie aplikacje (przeglądarka, OBS, launchery).
2. Ustaw plan zasilania **High performance** (albo zapisz, jaki jest — trafia do
   raportu i różnica między kampaniami musi być świadoma).
3. Uruchom:
   ```powershell
   cd D:\git\gta6-30fps
   .\benchmarks\launch-bench.ps1 -Performance
   ```
   Dla fxceless: `.\benchmarks\launch-bench.ps1 -Fxceless`.
   `-Performance` (720p, ambient 0) jest profilem bramki 30 fps. `-Quality`
   (1080p, ambient 0.6) służy tylko do porównań ze starym baseline'em 1080p —
   nie mieszaj profili w jednej kampanii. Profil i pełne `VICTORY_*` trafiają
   do `run.json` (`env`, `launch.profile`).
4. Wybierz **Continue** na slocie `0009000000000001`.
5. Czekaj, aż streaming się uspokoi: zniknie wskaźnik ładowania, a scena stoi
   nieruchomo. Nie ruszaj się i nie ruszaj kamery.
6. Nie alt-tabuj, nie otwieraj menu, nie pauzuj. Cutscene → wczytaj save od nowa.
7. Wróć do terminala z `bench_run.py` i naciśnij Enter w momencie START; przez
   całe okno (domyślnie 60 s) nie dotykaj klawiatury ani myszy.
8. Po oknie naciśnij Enter. Przy crashu wpisz notatkę — trafi do raportu.

## Kontrola poprawności

Automatyczna (`bench_collect.py`, `bench_gate.py`):

- `draws >= 100` — poniżej tego to menu (41 draws) albo ekran ładowania,
- `frames >= 10` — mniej to za krótkie okno,
- VRAM peak `<= 7 800 MB` — powyżej karta zaczyna wyrzucać tekstury,
- brak TDR i braku fatalnego crasha w oknie.

Ręczna (na początku i na końcu okna):

- obraz jest obrazem gry, nie czarnym ekranem ani menu,
- HUD/subtitles są takie same jak w poprzednim przebiegu,
- rozdzielczość i ustawienia są takie same (`VICTORY_DISPLAY_MODE`, ambient).

## Czego nie mierzyć

- Menu i ekrany ładowania (30 fps cap, 41 draws) — to nie jest scena.
- Cutscene — inny zestaw draws i inny streaming.
- Pierwszych 10 s po wczytaniu — pipeline'y i tekstury jeszcze się budują.
- Okna, w którym zmieniłeś rozdzielczość, alt-tabowałeś albo włączyłeś tik
  Discorda/Steama.
