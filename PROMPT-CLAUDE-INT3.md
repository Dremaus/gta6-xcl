# Prompt dla Claude #2 — czwarta klasa: int3 w zapatchowanym miejscu (thunk padding)

Paste poniżej linii --- do Claude Code na tej maszynie:

---

You are continuing on the GTA VI compat-layer project. Previous task (read-fault VEH retry) shipped as
commit 1944123 in D:\git\VItoriaBr-opt — its fix is CONFIRMED working (game now survives the old class
into 3D and dies from OTHER classes). New task: FOURTH crash class, which I (orchestrator) have
partially root-caused. You work ONLY in D:\git\VItoriaBr-tdr (an isolated copy of the main tree at
HEAD 5a84eb4; the loader code there is byte-identical to opt and to main). DO NOT touch
D:\git\VItoriaBr-opt or VItoriaBr-opt-hle — other agents are editing those. D:\git\VItoriaBr-tdr
belongs to you; its release build exists (D3D diag build may not — rebuild as needed).

## Evidence gathered for you

Two crash signatures, both EXCEPTION_BREAKPOINT 0x80000003 (int3) in guest code:
- NEW (run C, survived 7m40s in 3D): at victory-image+0x5149aec
- OLD (run 27620, pre-AV-fix): at victory-image+0xf2cc4b

File bytes at those RVAs contain NO 0xCC (they are `85 ed` test ebp,ebp and `21 44 8d...`).
So the executed int3 exists only in MEMORY — the layer (or the game) patched code at runtime.
Disassembly around 0x5149aec (original code, aligned, verified with capstone):

    0x145149ac1: vmovaps xmm7, [r8]
    0x145149ac6: mov ebp, [rcx+0x44]
    ...
    0x145149ae2: call 0x144e63680        <- 5-byte E8 rel32; target is a REAL function
    0x145149ae7: vxorps xmm11,xmm11,xmm11 <- 5-byte VEX3, ends at 0x145149aec
    0x145149aec: test ebp,ebp             <- fault RIP: int3 ONLY IN MEMORY
    0x145149aee: jle ...

The prime suspect is the loader's own import/call-site patcher:
crates/victory-loader/src/thunks.rs — around line 122 it builds a 20-byte patch buffer
(`code[12..20].copy_from_slice(&(handler as *const () as u64))`) — a 6-byte `FF 25 00 00 00 00`
jmp + 8-byte absolute (14 total) written into guest code; a 5-byte original `call` cannot hold a
14-byte patch. Two failure modes to check in the actual code (read thunks.rs and everything that
writes into guest .text — grep for VirtualProtect + write around the image base):
(a) the patch is written but the overwritten victim bytes that followed the 5-byte call are NOT
    relocated, so after the callee returns, RIP=call+5 executes garbage or padding (CC);
(b) the padding of the patch buffer (bytes 14..20) is 0xCC and gets written into the following
    guest code — and the return lands exactly there.
Both = classic detour-length bug. Note the layer maps the image; guest imports are bound by the
HLE — find WHICH patcher writes into .text at these call sites at all (the layer may only patch
IAT entries, in which case the culprit could be the GAME patching itself — determine from code
which runtime writers exist; also check victory-hle for 'hook'/'patch'/trampoline code).

## Tasks
1. Read victory-loader/src/thunks.rs + its callers (import binding path, loader) and all sites
   that write into the mapped image's .text. Map the exact patch layout(s) and lengths.
2. Correlate: does the patcher's guest-address log (any tracing:: of patched sites) cover
   RVA 0x5149ae2 / 0xf2cc4b? If no log exists, add one behind diagnostics (feature-gated,
   cheap: tracing::debug! file name+RVA+old first bytes).
3. Root-cause for real: either reproduce in a unit/integration test WITHOUT the game (map a
   fake image page, run the patcher over a crafted 5-byte-call function, assert what lands
   where; then assert execution flow via your own tiny hand-decode or the existing unwind),
   or if the writer is NOT the layer, identify the mechanism (hardware breakpoint? RaiseException?
   a self-patching game system) from the registers and stack and hand back with proof.
4. If it IS the layer's detour: fix properly — relocate the overwritten victim instructions to
   a trampoline (standard detour fixup: decode instruction boundaries, move exactly n bytes),
   or when the patch cannot fit, use a 5-byte patch form that fits (call rel32 -> jmp rel32 to a
   trampoline stub; the stub holds FF25+abs). Keep the int3 padding rule ONLY for genuinely dead
   bytes, never in an instruction stream a return could reach. Add tests proving: after patching
   any call site, the byte at every possible return address is a valid instruction boundary
   belonging to the relocated victim (assert no 0xCC reachable).
5. cargo test --offline -p victory-loader (and the whole -p victory-gpu/-hle if files shared),
   cargo build --offline --release -p victory --features diagnostics in D:\git\VItoriaBr-tdr.
6. Verify with the game (you have launch authority; one run at a time, kill between):
   use D:\Gry\VItoriaBr-data\Launch-TDR-Gate.ps1 -Gate on (it runs the TDR tree when Gate=on —
   that is YOUR fixed tree now) — plus a quick no-fix control if cheap (previous 'on' data:
   died ~3 min with device removed; int3 class appeared on SafeMem+keys runs; to reproduce the
   int3 class specifically use the SafeMem profile with the tdr binary: copy
   Launch-VItoriaBr-SafeMem.ps1 -> Launch-SafeMem-TDR.ps1, only changing $repo/exe to the tdr
   tree; keep -Keys). Goal is NOT full stability (device-removal is another agent's D2 axis) —
   goal: NO 0x80000003 anywhere and strictly more long-3D minutes than before; int3 records:
   D:\Gry\VItoriaBr-data\data\7952987A\crashes.log.
7. Commit in VItoriaBr-tdr (concise message), append findings in Polish as new section
   '## Czwarta klasa: int3 w śladzie patchowania (Claude #2)' to
   D:\git\gta6-30fps\docs\EXPERIMENTS-2026-11-25.md (read the file's style first), commit gta6-30fps
   with ONLY that file staged.

## Rules (unchanged)
- no game bytes/data into any repo; GPL-3.0; no DRM bypass — runtime code patching here is the
  LAYER'S OWN interop machinery, fixing its bug is interoperability work;
- PowerShell 5.1 quirks; cargo --offline; PATH %USERPROFILE%\.cargo\bin;
- if a rebuild of D:\git\VItoriaBr-opt is ever needed — STOP and report instead (agent P owns it).

Report: which writer placed the int3, patch layout(s) found, the fix, test counts, run timings
before/after, commit hashes.
