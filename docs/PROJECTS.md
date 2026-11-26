# Projekty — co jest czym

## Główne runtime'y

| Projekt | Licencja | Stan | Rola w naszym projekcie |
|---|---|---|---|
| **VItoriaBr** | GPL-3.0 | Świat renderuje: 0,2–1 fps na RTX 4060 8 GB; 6 fps na RTX 5060 Ti 16 GB | baseline, obecny setup |
| **fxceless/victory-fork** | GPL-3.0 | 2–4 fps na RTX 4070 12 GB; 104 ms/klatkę, 3 850 draws | baza optymalizacji |
| **AnyXboxX** | GPL-3.0 | 4,8–5,4 fps na RTX 4070 Super; 6 550 draws; cutscenes + pierwsze misje | **najlepszy znany świat; kandydat na bazę** |
| **DexNom/VIctory** | GPL-3.0 | fork Radeon; 1,03 fps na RX 7900 XTX | tylko iGPU/RT na Radeonie |
| **XCL** | GPL-2.0-only | 30 fps menu, ~5 fps 3D na RTX 5090; 26 503 shadery | referencja; **nie kopiować kodu** |
| **Leonida** | GPL-3.0 | story load, brak pierwszej klatki świata | referencja static recompilation/SPIR-V |
| **Xbox2Windows** | MIT | intro/loading na zmodyfikowanym EXE; brak gameplayu | referencja CPU→C++/DXIL |
| **omonkeyz/xbox-emulator** | GPL-3.0 | GTA VI „not run”; mesh/root signature blockery | referencja ogólnego runtime'u |
| **VIPort** | GPL-3.0 | pierwszy cutscene, niegrywalny | referencja |
| **Port-of-the-Americas** | ? | press-start/setup/loading na Linux/Proton | referencja |
| **OpenScarlett** | MIT | D3D12/Vulkan 1.4, RDNA2 lifting, GDK shimy; wczesny | kandydat do analizy |
| **XPortPC** | ? | native x64 + RDNA→HLSL/DXIL, bit-exact GPU | kandydat do analizy |
| **KestrelX** | ? | clean-room, dual-wave RDNA2→SM6.6 DXIL, v0.9.0 | kandydat do analizy |
| **OpenEra** | ? | HLE/compat layer Xbox One/Series | kandydat do analizy |
| **MizuBox** | CPAL-1.0 | D3D12 SM6.6 + DXR, fork AnyXboxSeries | kandydat do analizy |
| **Oryx** | ? | native x86-64 + GDK runtime | kandydat do analizy |
| **scarlett-commons** | ? | hybrydowy recompiler | kandydat do analizy |
| **xseries-wine** | ? | boot harness GDK exe pod Wine/Proton | referencja Linux |
| **XSX-Compat** | ? | compat layer na Linux | referencja Linux |
| **Dekubi-Ally-X** | GPL-3.0 | Rust compat layer | kandydat do analizy |
| **xvalkyrie** | ? | eksperymentalny Xbox One/Series compat layer | niska priorytet |
| **BSXbox** | ? | „Xbox Series X/S emulator*” | niska priorytet |
| **moonlight-xbox** | GPL-3.0 | streaming PC→Xbox (Moonlight) | **nie dotyczy** GTA VI |

## Skan topicu `xbox-series-x`

- GitHub API: **66** repozytoriów (`total_count=66`); strona topicu może pokazywać
  łącznie 74 (indeks/forks). Pełna lista: `research/topic-xbox-series-x.csv`.
- Kategorie: runtime/compat/emulator (~25), narzędzia shader/GPU (~15), launchery/
  narzędzia konsolowe (~15), poradniki/hardware/inne (~11).
- Najważniejsze nowe znaleziska:
  - **AnyXboxX** — najlepszy zmierzony świat (4,8–5,4 fps, 6 550 draws) i meta-repo
    z `third_party/{victory,leonida,tombox,xbox2windows}`.
  - **VIPort** — VIctory, pierwszy cutscene.
  - **OpenScarlett**, **XPortPC**, **KestrelX**, **OpenEra**, **MizuBox**, **Oryx** —
    wczesne warstwy/shader translatory; kandydaci do readers, nie do 30 fps.
  - **Port-of-the-Americas**, **XSX-Compat**, **xseries-wine** — Linux/Proton.
  - **RAGE9-Recomp** — relinker/UMA/AOT dla RAGE; infrastruktura pod static
    recompilation.
  - **Neonbridge** — launcher/orchestrator runtime'ów; przydatny front-end.
  - **GTA6-windows-tracker**, **GTA6_PCPORT_INFO** — research/status, nie runtime.

## Werdykt

- **Do bazy:** AnyXboxX `third_party/victory` (najlepszy świat) vs fxceless
  (najlepsze udokumentowane optymalizacje). M1 rozstrzyga pomiarem.
- **Do referencji:** XCL (shadery/asset coverage), Leonida/Xbox2Windows (static
  recompilation), omonkeyz (HLE surface), OpenScarlett/XPortPC/KestrelX (DXIL).
- **Nie dotyczy:** moonlight-xbox (streaming), hardware/guides, launchery.
- **30 fps:** żaden projekt tego nie osiąga; najlepszy to 4,8–5,4 fps na RTX 4070
  Super. Na RTX 4060 8 GB/16 GB to nie jest kwestia wyboru repo.
