# Baseline snapshot — baseline-vitoriabr-2026-11-25.csv

Single stored sample per variant. This is **not** the 3-run protocol:
a p95 and a 1% low need per-frame data, which this CSV does not have.
The gate column is indicative only.

| source | date | ms/frame | fps | draws | dropped | gate (indicative) | note |
|---|---|---:|---:|---:|---:|---|---|
| vitoriabr-4060-cold | 2026-11-25 | 4016.6 | 0.2 | 2973 | 2844 | below G1 | cutscene 3D; RTX 4060 8GB/16GB |
| vitoriabr-4060-cold | 2026-11-25 | 2985.1 | 0.3 | 3361 | 1504 | below G1 | cutscene 3D; pipelines being made |
| vitoriabr-4060-cold | 2026-11-25 | 1317.2 | 0.8 | 1011 | 1418 | below G1 | cutscene 3D; pipelines being made |
| vitoriabr-4060-open-world | 2026-11-25 | 1647.6 | 1.0 | 3504 | n/a | below G1 | opening cutscene; screenshot caption |
| anyxboxx-4070super | 2026-11-25 | 200.0 | 5.0 | 6550 | n/a | G1 | README; not this laptop |
| fxceless-4070 | 2026-11-25 | 104.0 | 9.6 | 3850 | n/a | G1 | README; first rooms with switches |
| vitoriabr-5060ti | 2026-11-25 | 167.0 | 6.0 | 3900 | n/a | G1 | README; stronger GPU |

## Reading

- Fastest stored sample: **fxceless-4070** at 104.0 ms (9.6 fps, 3850 draws, gate G1).
- That is **3.1x** the 33.3 ms budget on the hardware named in the note.
- To judge the 30 fps gate, run the 3-run protocol in `docs/BENCHMARK-PROTOCOL.md`; it produces per-frame times, p95 and 1% low.

_Generated 2026-11-25T22:03:40Z from `benchmarks\baseline-vitoriabr-2026-11-25.csv`._
