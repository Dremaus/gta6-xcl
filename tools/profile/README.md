# Profiler (VItoriaBr diag)

VItoriaBr's diagnostics build has a sampling profiler (`VICTORY_PROFILE=1`).
It writes `profile.txt` and `profile.txt.folded` (stacks in microseconds).

## Run

```powershell
# 1. Build the diag binary once (1-2 min)
cd D:\git\VItoriaBr
cargo build --profile diag -p victory --features diagnostics

# 2. Optional but recommended: warm the diag shader cache with the same VICTORY_* settings
powershell -File "D:\Gry\VItoriaBr-data\Launch-VItoriaBr-Profile.ps1" -Warm

# 3. When the profile launcher starts the game, press Enter as usual, reach 3D,
#    let it run ~60 s, then close the game.

# 4. Summarise the stacks
python D:\git\gta6-30fps\tools\profile\parse_victory_profile.py `
  "D:\Gry\VItoriaBr-data\logs\profile.txt.folded"
```

The parser prints, per role (SUBMITTING, RECORDING, TITLE, BUSY):
- **self** time: the innermost frame (where the CPU actually was),
- **inclusive** time: the function anywhere in the stack.

Use `--csv` for a per-function CSV and `--json` for machine-readable output.

## Why diag

The release build has no profiler. The diag build has `debug_assertions` and the
`diagnostics` feature, so its shader cache key is separate from release; warm it
once with the same settings to avoid profiling shader translation.

## Notes

- 500 looks/s (`VICTORY_PROFILE_HZ=500`), 1 s window every 5 s, report at exit.
- The profiler adds overhead; use it for relative hot paths, not FPS numbers.
- Do not run heavy builds or several games at the same time; samples get noisy.
