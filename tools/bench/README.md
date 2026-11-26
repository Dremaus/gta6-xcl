# Benchmark tools

Harness pomiarowy: parsowanie logów, zbieranie przebiegu, wykrywanie
crash/TDR, raport i bramka 30 fps. Protokół: `docs/BENCHMARK-PROTOCOL.md`.

## Moduły

| plik | rola |
|---|---|
| `victory_log.py` | parser obu rekordów (`N fps, …` i `frame times: … each: …`), percentyle |
| `bench_gate.py` | cel 33,3 ms, bramki G1–G4, werdykt |
| `bench_guard.py` | `crashes.log`, Event Log, dumpy telemetrii |
| `bench_collect.py` | jedno okno → `run.json` |
| `bench_run.py` | kampania 3 przebiegów (interaktywna, nie startuje gry) |
| `bench_report.py` | agregacja 3 przebiegów → raport i werdykt |
| `parse_victory_log.py` | CLI parsera, zgodne z poprzednią wersją |
| `settings_xml.py` | parser pól cap/present z `settings.xml` (desiredFPS, frameRateLimit, vSync, refresh, rozdzielczość) + backup `.cap-bak` |

## Szybki start

```powershell
# jeden przebieg z gotowego okna czasowego
python tools\bench\bench_collect.py --runtime vitoriabr --variant e3b --cache warm `
  --run-id r01 --start 2026-11-25T21:00:00Z --end 2026-11-25T21:01:00Z `
  --out benchmarks\runs\e3b\r01\run.json

# kampania 3 przebiegów
python tools\bench\bench_run.py --runtime vitoriabr --variant baseline --cache warm `
  --runs 3 --window 60 --out benchmarks\runs\2026-11-25-baseline-warm

# raport
python tools\bench\bench_report.py --runs <r01> <r02> <r03> --variant baseline --out report.md

# kalibracja na istniejącym logu (wykrywa brak VICTORY_LOG=info)
python tools\bench\bench_collect.py --runtime vitoriabr --run-id calibrate --whole-log --out "$env:TEMP\calibrate.json"

# parser wprost
python tools\bench\parse_victory_log.py LOG --frames --gate-fps 30
python tools\bench\parse_victory_log.py LOG --min-draws 1000 --min-ms 100 --csv out.csv

# settings.xml (A/B ramiona)
python tools\bench\settings_xml.py --data-root D:\Gry\VItoriaBr-data --expect-cap removed
python tools\bench\settings_xml.py PATH --with-backup
```

## Wymagania

- Python 3.11+ (testowane na 3.13).
- `nvidia-smi` w `PATH` dla VRAM i temperatury.
- Log pomiarowy: `VICTORY_LOG='victory_gpu::host=info,victory_gpu::framelog=info,warn'`
  i `VICTORY_FRAME_LOG=1` — ustawia je `benchmarks\launch-bench.ps1`.
- Gra zamknięta przed startem przebiegu; `bench_run.py` odmawia, jeśli działa.
- Bramka START w `bench_run.py` czyta Enter globalnie (`GetAsyncKeyState`),
  więc operator może kliknąć okno gry (zostaje na pierwszym planie) i dopiero
  potem nacisnąć Enter — patrz „Runbook" w `docs/BENCHMARK-PROTOCOL.md`.
- A/B: `benchmarks\launch-bench-ab.ps1` (patrz nagłówek skryptu).

## Baseline discipline

- Ta sama scena, ten sam save, ta sama kamera, trzy przebiegi.
- Zapisany host, sterownik, plan zasilania, stan cache i pełne env `VICTORY_*`.
- Wariant promowany dopiero po powtórzonej delcie > 5%, correctness gate i
  rollbacku.
