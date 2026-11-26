# benchmarks

Pomiary, nie dane gry. Nic z `D:\Gry` nie trafia do repo.

```
report-template.md              szablon raportu (renderowany przez bench_report.py)
sample-report-baseline.md       snapshot zapisanego baseline'u CSV
baseline-vitoriabr-2026-11-25.csv   historyczny baseline (1 próbka na wariant)
vitoriabr-4060-parsed.csv       ślad parsera z pierwszego pomiaru
launch-bench.ps1                launcher z logowaniem pomiarowym (INFO host/framelog)
scenes/reference-scene.md       protokół sceny referencyjnej
fixtures/                       SYNTHETYCZNE logi do testów parsera
runs/                           artefakty kampanii (lokalne, gitignored)
```

## Kampania

```powershell
cd D:\git\gta6-30fps
python tools\bench\bench_run.py --runtime vitoriabr --variant baseline --cache warm --runs 3 --window 60 --out benchmarks\runs\2026-11-25-baseline-warm
```

Pełny protokół, reguły bramek i ograniczenia: `docs/BENCHMARK-PROTOCOL.md`.

## Fixtures

`fixtures/log-synthetic-format.txt` i `fixtures/log-powershell-wrapped.txt` są
**zsyntetyzowane** z formatów w `crates/victory-gpu/src/host.rs` i `framelog.rs`.
Służą tylko do testu parsera (ANSI, zawijanie PowerShell, drugi rodzaj rekordu)
i nie są pomiarami. Pliki `crashes-*.txt` też są zanonimizowane.
