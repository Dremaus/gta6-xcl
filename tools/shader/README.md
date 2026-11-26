# Shader tools

## `analyze_unsupported.py`

Groups the translator's failures by stage and reason, so the 254 warm-up
failures can be triaged instead of guessed at. It reads only metadata; it never
prints or copies shader code.

```powershell
# victory warm --list
python tools\shader\analyze_unsupported.py out\warm.txt --markdown

# victory translate --list (hashes + stages)
python tools\shader\analyze_unsupported.py out\translate.txt --json out\report.json

# VICTORY_FAIL_DUMP=<dir> dumps: FSSM slots, PAL stages, code sizes, wave64
python tools\shader\analyze_unsupported.py --dumps out\fail --markdown

# join failures with a run's "first bind" counts
python tools\shader\analyze_unsupported.py out\translate.txt `
    --game-log game-stderr.log --json out\report.json

# no game data needed
python tools\shader\analyze_unsupported.py --self-test
```

Categories: `geometry_stage`, `ps_hw_sgpr`, `cs_hw_sgpr`, `cs_lane_mask`,
`image_gather4_l`, `unknown_stride`, `root_address`, `descriptor`,
`image_atomic64`, `other`.

The impact labels are triage hints, not measurements. A compute failure that
produces data for draws is more important than a voxelisation GS used only for
indirect lighting. `first bind` / `DROPPED` lines from a run settle that.

### Input formats

- `victory warm --list`:
  `does not translate: <file>: <reason>`
- `victory translate --list`:
  `<file> <stage> ... #<hash>  <reason>`
- `game-stderr.log`:
  `stage="..." hash=... error=...` and `first bind` lines.

Failure dumps are game data: keep them outside the repository.
