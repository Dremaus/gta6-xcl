# Prompt dla Claude #2 (v2) — czwarta klasa: int3 w pamięci, którego nie ma w pliku

Paste poniżej linii --- do Claude Code na tej maszynie:

---

GTA VI compat-layer project, task #2 for you. Your previous fix (VEH read-retry, opt commit 1944123)
works: the game now survives the old classes and reaches 3D. New target: FOURTH crash class.
You work ONLY in D:\git\VItoriaBr-tdr (isolated copy of main HEAD 5a84eb4; loader/gpu code there is
identical to opt — fixes proven here will be forwarded later). DO NOT touch D:\git\VItoriaBr-opt
(Agent P edits draw.rs/host.rs there) or VItoriaBr-opt-hle. You have game-launch authority.

## The forensic fact (orchestrator-verified, trust it)

Two int3-class crashes: exception 0x80000003 (EXCEPTION_BREAKPOINT) at guest RVAs
+0x5149aec (run C, alive 7m40s, reached 3D, up to 14,096 draws) and +0xf2cc4b (older run, the one
once blamed on xmem — likely re-evaluate that attribution too).
At BOTH RVAs the FILE bytes are NOT 0xCC: 0x5149aec is `85 ed` (test ebp,ebp) in an aligned,
capstone-verified instruction stream; 0xf2cc4b is `21 44...`. The CPU executed an int3 that exists
only in MEMORY. Also ruled out by me: the import thunks (victory-loader/src/thunks.rs) are emitted
into a dedicated 22-byte-slot VirtualAlloc block (`48 B9 site / 48 B8 handler / FF E0`) — IAT data,
no .text patching; the guest call site 0x5149ae2 is a direct `E8` near call to a REAL internal
function at 0x144e63680 (prologue-verified), not to a stub.

So: either (1) some runtime writer corrupted the private image page holding 0x5149aec (wrote 0xCC
data over .text — e.g., a stale VA in a texture/DStorage/shader copy, a relocation fixup bug, a
wrong-base placeholder map), or (2) the GAME itself patches its .text (hotfix/detour machinery,
anti-tamper breakpoint placement). Distinguishing these is task #1.

## Tasks

1. INSTRUMENT (in tdr tree, diagnostics-feature-gated): in the VEH/filter path that reports
   0x80000003 in the GUEST image (crates/victory-loader/src/crash.rs or where the int3 record is
   built — the record already resolves victory-image+RVA): dump (a) 16 bytes at RIP from LIVE
   MEMORY, (b) 16 bytes at the corresponding file offset (the loader knows the file; or read via
   the image's mapped backing — keep it cheap, only when the code is 0x80000003), (c) VirtualQuery
   State/Protect at RIP, (d) first 8 bytes of the page before/after. Log as one line:
   'int3 forensics: mem=... file=... state=... protect=...'. If mem!=file at RIP => hypothesis (1)
   live corruption; equal => the CPU saw a different mapping (page swapped/mapped twice) => also
   (1)-adjacent. Record which of the two.
2. AUDIT writers into image pages: grep every place that can write into the guest image VA range:
   relocation/fixup application in victory-loader (does it write after mapping? base deltas?),
   DStorage queue destinations, DirectQueue 'writes into physical pages at addresses the title
   had mapped' machinery, victory_gpu inplace/shadow guarded copies that could target a stale VA,
   the placeholder-map path in xmem (map_warn can MapViewOfFile3 with MEM_REPLACE_PLACEHOLDER —
   verify a placeholder CANNOT exist inside an image-mapped range; an image range mapped as
   placeholder would swap page content between file-view and section — explain how). Fix or
   handoff precisely.
3. If (2) finds nothing, check (1)-game: search the exe for its own detour/pattern-writer by
   testing whether the fault pages stay corrupted AFTER a fresh boot with everything else off —
   i.e., extend instrumentation: at image load, hash the faulting PAGE (RVA 0x5149000..0x514A000)
   after mapping; re-hash every 60 s (a cheap background once-per-frame counter gated by env
   VICTORY_IMAGE_WATCH=<hexrva>); log first mutation with a stack capture of the writer thread if
   available (GetThreadContext of all threads is too heavy; at minimum timestamp + which subsystem
   is alive). Deterministic 7-8 min reproduction window (the int3 fires ~7m40s into SafeMem+Keys)
   makes this tractable.
4. Whatever the root cause: a minimal fix or the sharpest possible handoff doc. Tests for
   whatever code you touch (cargo test --offline -p victory-loader / -p victory-gpu / -p victory-hle
   as relevant; the WARP flake may fail; ignore indirect::tests::warp_budget...).
5. Build: PATH %USERPROFILE%\.cargo\bin; cargo build --offline --release -p victory --features
   diagnostics in tdr. Run: copy D:\Gry\VItoriaBr-data\Launch-VItoriaBr-SafeMem.ps1 to
   Launch-SafeMem-TDR.ps1 with $repo -> D:\git\VItoriaBr-tdr, keep -Keys, add
   VICTORY_IMAGE_WATCH etc. via the script. Runs: expect to see int3 again (~4-8 min) WITH your
   forensic line — that is SUCCESS for step 1 (one run is enough to classify; try twice).
   One game at a time; kill victory.exe between runs; crash records:
   D:\Gry\VItoriaBr-data\data\7952987A\crashes.log; stderr: D:\Gry\VItoriaBr-data\logs\*.
6. Commit in tdr (concise); append Polish section '## Czwarta klasa: int3-forensyka (Claude #2)'
   to D:\git\gta6-30fps\docs\EXPERIMENTS-2026-11-25.md, commit ONLY that file in gta6-30fps.

## Rules
GPL-3.0; no game data/bytes into repos (forensic LOGS with 16-byte windows are fine, keep them in
D:\Gry or the logs dir, not in the repo); no DRM bypass — this is the layer's own interop defect
hunting; PowerShell 5.1, cargo --offline; do not rebuild VItoriaBr-opt ever.

Report: mem-vs-file verdict (with the logged bytes), the writer identified or 'game-side, proven
via page-watch timeline', fix or handoff, test counts, run timings, commits.
