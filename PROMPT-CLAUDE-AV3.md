# Prompt for Claude — task: third AV class (read on committed page), VItoriaBr layer
# (paste everything below the line into Claude Code running on this machine)

---

You are joining an overnight project to run a leaked **GTA VI Xbox Series X|S dump (v1.0.2.1)**
on a Windows 11 laptop (Ryzen 7 8845HS, RTX 4060 Laptop 8 GB, 16 GB RAM) through the
**VItoriaBr** compatibility layer (a VIctory-fork, Rust, GPL-3.0). You work ONLY in
`D:\git\VItoriaBr-opt` (git worktree, branch `main`, HEAD `7ef1074`; same content on branch
`night-2026-11-26`). DO NOT touch `D:\git\VItoriaBr`, `D:\git\VItoriaBr-opt-hle`,
`D:\git\VItoriaBr-tdr`, or `D:\git\gta6-native-proto` — other agents own those.

## Your single task: kill the THIRD crash class

Timeline of crash classes already fixed (do not redo):
1. xmem Scatter coalescing bug (error 487) — fixed upstream, present in this tree.
2. Deterministic guest AV `victory-image+0x11170ae` and layer write AV `victory.exe+0x65709e`,
   both on pages **"reserved, never committed"** — fixed last night by the VEH retry in
   `crates/victory-gpu/src/watch.rs` (function `install()` → `on_write`, plus helpers
   `reserved()`, `writable()`, `this_thread_remapping()`, TLS `REMAPPING_THREAD`,
   and `install()` called from `title_memory_remapping()`). The race window: the layer's
   remap path `xmem.rs map_warn` does unmap→placeholder→MapViewOfFile3→commit while holding
   the MAPPING write guard; a reader (guest thread or layer writer) that faults inside the
   gap is now waited-out and resumed.

REMAINING BUG (yours): with the retry in place, the SafeMem+Keys repro now dies later
(~40-90 s) with a NEW signature:

```
VItoriaBr: first-chance exception 0xc0000005 at victory-image-b99f876b74a77f.dll+0x4e8b4b4
           (read 0x516a22ec0: read-write)
VItoriaBr: unhandled exception 0xc0000005 at victory-image-...+0x4e8b4b4 (read 0x516a22ec0: read-write)
  frames: +0x52479fb, +0x9dd0c2, +0x22a2a99, +0x63e78, +0x25703c4 (guest stack)
```

The faulting page is reported **read-write and committed** — a normal read cannot AV on such
a page. Prime suspect: the **PAGE_GUARD bit** (`Protect == PAGE_READWRITE | PAGE_GUARD`, or
PAGE_NOACCESS with guard semantics). The layer uses guard pages for its write-tracking
("guarded blocks", `g.protected` in watch.rs) — a guest READ of a guarded page raises an
access violation too, but `on_write` only special-cases writes; reads fall through to
CONTINUE_SEARCH and the game's breakpad kills the process. On console this never happens
because the title's own unmapping of the guard is different; under the layer the guard
lifecycle races the title's read.

Do:
1. Read `crates/victory-gpu/src/watch.rs` (`on_write`, `open()`, `open_here`, `guards()`,
   `writing()`, `protected/clean/absent/viewed/aliased` sets, BLOCK size) and
   `crates/victory-loader/src/crash.rs` `memory_at()` (it masks/prints Protect — see how
   "read-write" is derived; PAGE_GUARD may be hidden by a `& !PAGE_GUARD` style mask).
2. Reproduce and confirm: launch the repro below, wait for the crash, and instrument
   the VEH (temporarily, behind `#[cfg(feature="diagnostics")]` or an env switch
   `VICTORY_GUARD_READ_STATS=1`) to log `MEMORY_BASIC_INFORMATION.Protect` (raw hex!) and
   `State` for the faulting address on every AV read that the handler declines. One run
   tells you if it is PAGE_GUARD or something else (e.g. the page being a
   placeholder re-committed under another mapping, or a stale TLB-ish pattern).
3. Implement the real fix for the confirmed cause. If PAGE_GUARD: a guest READ of a
   guarded block should open the guard (clear protection, mark dirty via the existing
   `open()` machinery) and return EXCEPTION_CONTINUE_EXECUTION — same semantics the write
   path already has. Keep the deadlock guard (`this_thread_remapping`) and never hold
   `guards()` across MAPPING waits (lock order MAPPING → guards).
4. Tests: extend the unit tests in `watch.rs` (there are existing ones around writable /
   reserved, see `crash.rs:710` style). Run:
   `cargo test --offline -p victory-gpu` and `-p victory-hle` (expect ~177 and ~109 pass;
   one pre-existing WARP flake `indirect::tests::warp_budget_...` may fail — ignore).
5. Build: set PATH to include `%USERPROFILE%\.cargo\bin`, then
   `cargo build --offline --release -p victory --features diagnostics` in `D:\git\VItoriaBr-opt`.
6. Verify with the repro (you MAY launch the game — the user is asleep/away and expects
   autonomous runs):
   `powershell -NoProfile -ExecutionPolicy Bypass -File D:\Gry\VItoriaBr-data\Launch-VItoriaBr-SafeMem.ps1 -Keys`
   - scripted keys (25:Enter,45:Y,58:Enter,...) advance the menu automatically; someone
     must CLICK the game window before Enter-like focus actions are needed — the script
     already clicks first (`Click-GameWindow.ps1` behavior is built into the flow).
   - watch the process: previously died at 40-90 s with the new AV; success = alive
     > 6 min reaching free roam (window title shows fps/draws; 3D = draws > 1000).
   - stderr: `D:\Gry\VItoriaBr-data\logs\safe-mem-stderr.log`;
     crash records: `D:\Gry\VItoriaBr-data\data\7952987A\crashes.log`.
7. Commit in `D:\git\VItoriaBr-opt` (branch main) with a concise message, and append your
   findings to `D:\git\gta6-30fps\docs\EXPERIMENTS-2026-11-25.md` (new section "Claude 26.11
   morning"), in Polish, matching the file's style. Commit that file too:
   `git -C D:\git\gta6-30fps add docs/EXPERIMENTS-2026-11-25.md && git -C ... -c user.name=witek -c user.email=witek@local commit -m "..."`.

## Hard rules
- NEVER copy game data (or game bytes) into any repository.
- No DRM/decryption/anti-tamper bypass; memory/exception handling is for interoperability only.
- GPL-3.0 project. Do not commit `target/`, logs, or dumps.
- PowerShell here is 5.1 non-interactive: avoid `&&` at top level in your own probes,
  quote paths, cargo needs `--offline` (no network lockfile updates).
- If you must stop for any reason, leave the tree compiling and write a STATUS block at
  the end of the EXPERIMENTS doc section.

## Context you may need
- Docs: `D:\git\gta6-30fps\docs\` — EXPERIMENTS-2026-11-25.md (night log incl. §"05:55 —
  VEH retry"), STABILITY-TDR.md, BORDERLESS-AND-CAP.md, HLE-HOTPATHS.md, MEMORY-STREAMING.md.
- Known separate problem (NOT yours): in free roam the process dies with GPU device reset
  (~2.5 min) and runs 1-2 fps; relay/async switches were exonerated by an A/B last night.
- Game exe: `D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\game_scarlett_master.exe`; guest is native
  x64; layer maps it as `victory-image-b99f876b74d4a77f.dll` so guest RVAs = the exe's RVAs
  (image base 0x140000000; PE parsing helper exists: `D:\git\gta6-30fps\tools\pe_rva_dump.py`).

Report at the end: confirmed root cause (raw Protect value observed), the patch summary,
test counts, repro outcome (time alive / crash class change), commit hashes.
