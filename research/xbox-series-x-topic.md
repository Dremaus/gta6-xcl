# Skan topicu `xbox-series-x` — 2026-11-25

## Metoda

- `GET https://api.github.com/search/repositories?q=topic:xbox-series-x&per_page=100&sort=stars`
- `total_count = 66`, zwrócono 66. Strona topicu może pokazywać 74 (indeks GitHub
  bywa opóźniony / liczy inne wpisy); API jest źródłem tej inwentaryzacji.
- Pełne dane: `topic-xbox-series-x.csv` (66 wierszy) i `topic-xbox-series-x.json`.

## Kategorie

| Kategoria | Przykłady | Znaczenie dla 30 fps |
|---|---|---|
| Runtime/compat/emulator | AnyXboxX, XCL, Xbox2Windows, Leonida, VIPort, OpenScarlett, XPortPC, KestrelX, OpenEra, MizuBox, Oryx, scarlett-commons, xseries-wine, XSX-Compat, Dekubi-Ally-X, xvalkyrie, BSXbox | **kluczowe** — tylko one mogą uruchomić grę |
| Shader/GPU tools | RAGE9-Recomp, translatory RDNA2/DXIL/SPIR-V | pomocnicze |
| Launchery/orchestratory | Neonbridge, Game Vault, xbox_launcher | front-end, nie FPS |
| Hardware/poradniki/inne | cfxsx, xboxctl, GTA6 guide/tracker, moonlight-xbox | **nie dotyczy** |

## Top kandydaci (stan z README/opisu)

| Repo | Gwiazdki | Stan | Wniosek |
|---|---:|---|---|
| LooperSalty/AnyXboxX | 341 | świat 4,8–5,4 fps na RTX 4070 Super; 6 550 draws; cutscenes i pierwsze misje; Linux 3–5 fps na RX 9070 XT | **najlepszy znany świat; baza M1** |
| DesertGamer/VIPort | 134 | VIctory, pierwszy cutscene, niegrywalny | referencja |
| californiaAlmonds/OpenScarlett | 100 | D3D12/Vulkan, RDNA2 lifting, GDK shimy; wczesny | analiza |
| Its3rr0rsWRLD/XPortPC | 11 | native x64 + RDNA→HLSL/DXIL, bit-exact GPU | analiza |
| Batushn/KestrelX | 6 | clean-room, dual-wave RDNA2→SM6.6 DXIL, v0.9.0 | analiza |
| PlutonusDev/OpenEra | 45 | compat layer Xbox One/Series | analiza |
| Mizushi148/MizuBox | 8 | D3D12 SM6.6+DXR, fork AnyXboxSeries | analiza |
| NightFury-Supreme/Oryx | 2 | native x86-64 + GDK runtime | analiza |
| scarlett-commons/scarlett-commons | 1 | hybrydowy recompiler | analiza |
| ReverendOzmund/xseries-wine | 1 | boot harness GDK exe pod Wine/Proton | Linux |
| ProjectLeonidaL/leonida | 438 | kontynuacja Leonida, static recompilation | referencja |
| Steinkoloss/port-of-the-americas | 5 | press-start/setup/loading na Linux | referencja |
| R0Y00/Xbox2Windows | 1 948 | intro/loading, brak gameplayu | referencja |
| XCL | 8 248* | 30 fps menu, ~5 fps 3D na RTX 5090 | referencja (GPL-2.0-only) |
| sammwyy/xvalkyrie | 233 | eksperymentalny Xbox One/Series compat | niska priorytet |
| BSXbox/BSXbox | 11 | „Xbox Series X/S emulator*” | niska priorytet |

\* XCL nie musi mieć topicu; dane z jego repo.

## Werdykt

- **AnyXboxX** to jedyny nowy projekt, który renderuje świat i ma zmierzony FPS
  (4,8–5,4 na RTX 4070 Super). To najlepszy kandydat na bazę.
- Żaden projekt z topicu nie osiąga 30 fps w 3D. Najbliżej są AnyXboxX (5 fps) i
  VItoriaBr/fxceless (2–6 fps na mocniejszym sprzęcie).
- Reszta to wczesne warstwy, translatory, launchery lub projekty nie związane
  z GTA VI. Nie należy ich „sklejać” bez pomiaru.
