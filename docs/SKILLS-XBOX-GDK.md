# Katalog 50 skilli Xbox GDK — status w projekcie

Pełny, 50-wierszowy katalog z opisami i statusami:
`C:\Users\witek\.agents\skills\xbox-series-gdk-translation-expert\references\modules-1-8.md`.

## Podsumowanie

| Status | Liczba | Znaczenie |
|---|---:|---|
| **adopt** | 40 | wdrożone jako referencje/design patterns |
| **adapt** | 6 | tylko własne, już odszyfrowane pliki; bez DRM/kluczy |
| **optional** | 1 | streaming PC→Xbox; nie dotyczy FPS |
| **reject** | 3 | sandbox/DRM/anti-tamper bypass — **nie implementujemy** |

## Odrzucone (twarda polityka)

- `03 game_core_sandbox_bypass` — omijanie sandboxa/certyfikatów/DRM.
- `25 xex_to_pe_converter_v2` — `xex` to Xbox 360; Series X|S to PE/GDK; brak
  deszyfrowania i przebudowy chronionych kontenerów.
- `27 anti_tamper_hypervisor_bypass` — omijanie anti-tamper/hypervisora.

Alternatywy: lokalny profil offline dla **własnej** kopii, analiza **już
odszyfrowanych** plików, publiczne nagłówki GDK/SDK. Żadnych kluczy, deszyfrowania
ani obchodzenia zabezpieczeń.

## Adaptowane (6)

- `02 xbox_memory_topology_mapping` — model 16 GB UGDDR6 jako budżety RAM/VRAM,
  nie literalny podział 10+6 GB.
- `04 xvc_container_parser` — tylko metadane/manifesty odszyfrowanych dumpów.
- `09 xstore_license_emulator` — offline „owned” tylko dla własnej kopii.
- `18 esram_vram_unified_addressing` — Series X|S **nie ma eSRAM**; modeluj
  GDDR6/UMA i adresy GPU.
- `37 dynamic_code_patcher_jit` — tylko spin-locki/wydajność, nie anti-tamper.
- `48 firmware_dump_structure_extractor` — preferuj publiczne GDK; bez
  ekstrakcji/redystrybucji własnościowych DLL.

## Mapowanie na plan

- **M1 (baza, HLE, PE):** 01, 02, 05, 06, 07, 08, 10, 11, 15, 22.
- **M2 (CPU/draw):** 21, 26, 28, 32, 36, 37.
- **M3 (GPU/shader/PSO):** 16, 17, 19, 20, 33, 34, 35, 47.
- **M4 (pamięć/streaming):** 18, 29, 30, 31, 42.
- **M5 (telemetria/bramka):** 38, 39, 40, 41, 49, 50.

## Zasada użycia

Katalog jest **referencją projektową**, nie deklaracją, że wszystkie 50 modułów
jest już zaimplementowanych. Implementacja idzie krokami M1–M5, każdy z
correctness gate i pomiarem. Celem nadrzędnym pozostaje 30 fps; obecny stan
(0,2–1 fps na RTX 4060, 4,8–5,4 fps na RTX 4070 Super w AnyXboxX) pokazuje,
że to projekt wieloetapowy, nie jedna zmiana.
