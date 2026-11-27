# REA — dowody i granice narzędzia

Narzędzie: REA MCP (`rea-agents`), skill ECC `reverse-engineer-anything`.
Cel: rozdzielić twierdzenia, które mają dowód z binarki, od tych, których REA
nie może rozstrzygnąć.

## 1. Gdzie REA dowodzi

`inspect_pe_imports` (target-free, bez silnika) na tytułowych DLL:

| Artefakt | SHA-256 | Bajtów | Importy (kolejność z tabeli) |
|---|---|---|---|
| `xboxbvhbuilder.dll` | `99f803ac22c01ef329dddb1d40be67238d2a812d01e8d040b3cb5135bc23707e` | 884 224 | pierwsza DLL: **`d3d12_xs.dll`** |
| `amd_fidelityfx_upscaler_xbox.dll` | `faff02f294a7e9149ce079dffe3dedbcabe99b1f180ab14222aa8689e00a75fa` | 786 432 | `MSVCP140.dll` i dalsze |

ID Evidence: `ev_53b530ac36099a2d12f3848301306cbebf72a078b01bdbb03a60490d2f1ddc2c`,
`ev_2c4b74a39d12370d24c19845bbedbac21f95d6a1f40719e64b9333fe5f3c61f0`.
Format: PE32+ (machine 34404), amd64.

### Co z tego wynika
- Builder BVH **rozmawia z konsolowym D3D12** (`d3d12_xs.dll` to moduł HLE XCL).
  Zatem fakt, że w naszych runach `#146/#148` nie są wołane, **nie bierze się z
  brakującego importu**, tylko z decyzji tytułu (wyłączony RT). To wzmacnia
  werdykt agenta RT: `XCL_RAYTRACING=off` nie odcina drogi, której tytuł i tak
  nie używa w tych scenach.
- Identyfikatory SHA-256 pozwalają powiązać każdy przyszły wniosek z dokładnie
  tym samym plikiem, nie „DLL-em z folderu gry”.

## 2. Gdzie REA NIE dowodzi (i nie będzie używane)

| Twierdzenie | Dlaczego nie REA | Czym instead |
|---|---|---|
| Które SGPR (np. `s23/s24`) trzymają bazy heapów w programie mesh | REA nie dekoduje ISA GFX10/RDNA2; to dane z `shaders.rpf`, nie PE | `xcl disasm` (własny dekoder XCL), PR #1803/#2092 |
| Czy dany program to MS/CS/PS i jaki ma layout | j.w. | `xcl shaders` / `--recomp` |
| Zachowanie tytułu przy tworzeniu pipeline'ów | wymaga uruchomienia | run + `XCL_PSO_TRACE`, `XCL_TRACE_FRAME` |

Zgodnie z regułą skillu: dla kompletnego źródła (XCL, VIctory) używamy zwykłych
narzędzi repo, nie REA. REA wchodzi tam, gdzie mamy tylko artefakt.

## 3. Wymaganie wobec kolejnych zadań

Każdy raport agenta musi zawierać jedną z dwóch rzeczy:
1. **użyty skill ECC + narzędzie REA z ID Evidence**, jeśli twierdzenie dotyczy
   binarki bez źródła, albo
2. **jawne „REA nie dotyczy”** z uzasadnieniem (jak w sekcji 2).

Samochwalstwo w stylu „jeśli przydatne” nie jest przyjmowane.
