# P0 hang triage — 2026-11-26

Status: read-only triage of the P0 A/B logs and Windows events. No game was
launched for this note; no code changed. The game was later run by the operator
in the SafeMem profile, separately.

## 1. Evidence

### Windows events

`Get-WinEvent -FilterHashtable @{LogName='Application'; Id=1002}`:

| Time | Program | Event |
|---|---|---|
| 2026-11-26 20:58:52 | victory.exe 0.0.0.0 | AppHangB1, closed by Windows |
| 2026-11-26 20:53:58 | victory.exe 0.0.0.0 | AppHangB1, closed by Windows |

The two events line up with P0 arm A runs (`20:49:43` and `20:55:42`).

### Arm A — `p0-armA-20261126-205542-stderr.log`

- Last line (UTC 19:56:31, local 20:56:31):
  `host pipelines all made made=0 loaded=2887 started_early=2894`
- No frame line, no `0xc0000005`, no device-removed, no world. The process then
  hung until the AppHangB1 at 20:58:52.
- Earlier arm A `p0-armA-20261126-204943-stderr.log` ends the same way:
  `host pipelines all made made=0 loaded=1168 started_early=1175` at 19:50:28,
  then AppHangB1 at 20:53:58.
- Arm A `p0-armA-20261126-204231-stderr.log` ends mid-pipeline creation (no
  "all made") at 19:47:38 — an earlier cold-cache attempt.

### Arm B — `p0-armB-20261126-210048-stderr.log`

- `host pipelines all made made=0 loaded=2887 started_early=2894` at 20:02:05.
- Descriptor/submission accounting follows; at 20:02:06:
  `VItoriaBr: unhandled exception 0xc0000005 at VCRUNTIME140.dll+0x1afd6
  (write 0x255e0000: read-write)`.
- Breakpad context at the same moment:
  `memory.load_percent=97`, `system.memory.free=397012` KB (~388 MB),
  `system.memory.total=16050548` KB (~15.3 GB).
- This is a different RIP/page than the historical dstorage write AV
  (`victory.exe+0x66cfae`, write `0x54311ac00`), so it is **not** evidence for
  that exact path.

### Cache

- The P0 launcher uses `VICTORY_CACHE_DIR=D:\Gry\VItoriaBr-data\p0-cache`,
  separate from the main cache.
- The first P0 arm translated ~3206 shaders (cold cache); later arms load 2887
  pipelines from the pipeline library. The translation count is therefore not
  by itself a regression: it is a cold-cache cost, and later arms were warm.
- Memory pressure remains in the warm arms: arm B crashes at 388 MB free and
  97% load.

## 2. Reading

1. **The hang correlates with pipeline load + memory pressure, not with a
   proven write-retry defect.** Arm A's last line is the pipeline phase; the
   process then sits until AppHangB1. Arm B, with the same pipeline phase and
   the same memory pressure, crashes in the CRT before reaching the world.
2. **The write-retry evidence is still directional, not conclusive:** arm A
   retried 3/3 observed write faults, arm B declined 1/1; the exact historical
   `0x66cfae` did not occur in either arm. The class behaviour is consistent
   with the fix, but the end-to-end gate was not reached.
3. **The P0 patch is not mergeable yet.** A/B is INCONCLUSIVE: no world, no
   fps, and arm A adds a new hang whose cause is not isolated from memory
   pressure.
4. **3206 translations are cold cache**, not a code regression. Re-running with
   the now-warm `p0-cache` is the correct next attempt.

## 3. Next steps

1. Repeat arm A on a clean machine:
   - no `translate`, Port 5, shader-diag, `rustc`, or browser/agent load;
   - warm `p0-cache` from the previous runs;
   - wait longer than the previous ~2 minutes after `host pipelines all made`;
   - sample free memory; if free < 1 GB, stop and free memory before judging
     the hang.
2. If arm A reaches the world, run arm B (`VICTORY_WRITE_RETRY=0`) on the same
   save/scene. PASS only if A has no `0xc0000005`/`0x66cfae`, no TDR/hang, and
   fps p50 is not worse by >5%; B should reproduce a write AV (otherwise the
   result is INCONCLUSIVE).
3. Use the exact Fast4 profile only after a stable A/B, to try to force the
   historical `0x66cfae`. `VICTORY_JOIN_PARTS` does not exist (Fast4's
   `JOIN_PARTS=8` was a no-op); relay/queue2/async are the relevant switches.
4. Keep rollback: `VICTORY_WRITE_RETRY=0`, or revert `cc1de49` in
   `D:\git\VItoriaBr-p0`.

## 4. Files

- `D:\Gry\VItoriaBr-data\logs\p0-armA-20261126-205542-stderr.log`
- `D:\Gry\VItoriaBr-data\logs\p0-armA-20261126-204943-stderr.log`
- `D:\Gry\VItoriaBr-data\logs\p0-armA-20261126-204231-stderr.log`
- `D:\Gry\VItoriaBr-data\logs\p0-armB-20261126-210048-stderr.log`
- `D:\Gry\VItoriaBr-data\logs\p0-armB-20261126-210048-crashes.log`
- `D:\git\gta6-30fps\docs\P0-WRITE-RETRY-VALIDATION.md` §5 (A/B runbook and
  the agent's verdict).
