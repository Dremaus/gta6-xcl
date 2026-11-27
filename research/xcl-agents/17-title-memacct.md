# 17 — Title-memory accounting: `XCL_TITLE_MEM_USED=title` (worktree fix/title-memacct)

Branch `fix/title-memacct` @ `D:\git\xcl-wt-memacct`, base main `7318cf60`.
Commits: `ea318ef5` test (RED), `29446068` fix (GREEN). One file: `crates/xcl/src/hle/kernelx.rs` (+235/−17).

## Mechanism (replaces the `used = process_private_bytes().min(total)` line, research 15 §B/16)

`TitleMemoryStatus` and `XMemGetWorkingSetStatistics` keep the same limit
(`title_memory_budget_mb`); the `used` source switches per env:
- unset / `private` (default): byte-identical to `7318cf60`, bookkeeping fully off (hot
  paths only read one cached flag).
- `title`: `used = TITLE_MEM_HELD` — the bytes the title currently holds through XCL's HLE
  entries. Pointer/index-keyed `BTreeMap`s + an `AtomicU64` mirror; a charge is added once and
  removed once, so the counter cannot underflow or double-remove. Title mode reports the raw
  overdraw in `title_used` (avail saturates at 0) so a run log shows real excess.
- Resolution is once-per-process via `OnceLock`, wrapped in `keep_last_error` (a title must not
  see its `GetLastError` clobbered). Logs once (info):
  `TitleMemoryStatus: accounting=title (XCL_TITLE_MEM_USED), used/total follow title allocations`.

## Counted (+) and debited (−) paths

| Path | Charge | Debit |
|---|---|---|
| `VirtualAlloc` HLE entry (kernel32/kernelx alias routes here — resolver prefers kernelx exports) | new reservations and null-address commits, size rounded to 4 KiB | plain `MEM_RELEASE` in `VirtualFree`/`VirtualFreeEx` (current process) |
| `XMemVirtualAlloc` | via the same `VirtualAlloc` entry (its internals call the HLE wrapper) | via `VirtualFree` on the returned base |
| `XMemAllocDefault` (unhooked path; heap and graphics branches) | request rounded to 4 KiB / `xmem_graphics_layout` rounded size | `XMemFreeDefault(p,·)` by exact pointer |
| `AllocateTitlePhysicalPages` / `XMemAllocatePhysicalPages` | n × 64 KiB per page index | per page actually released in `Free*PhysicalPages` (idempotent) |

Placeholder protocol frees (`0x8001` coalesce, `0x8002` split/preserve) keep the charge (regions
survive them); `MEM_DECOMMIT` keeps it (the title still holds the reservation). A re-charge at a
seen base keeps the larger value (a replaced placeholder cannot shrink its reservation's charge).

## Provably missed (and the error direction)

- `runtime_alloc`/`runtime_free` slices are NOT charged: they are carved from the title's own
  hook arenas, which were already charged when the hook (title code) reserved them via the
  `VirtualAlloc`/`XMemVirtualAlloc` entries. Charging both = double-count = overcount = the
  exact failure direction this patch removes. Memory the hook answers from pools XCL never sees
  is missed → undercount (safe per task design: never re-park spuriously).
- `XMemMapPhysicalPages`/scatter commits at fixed addresses: mapping moves already-charged
  pages; no charge/debit (fixed-address commits add nothing).
- Title frees that bypass the HLE wrappers (a real kernel32 `VirtualFree` reached via native
  `GetProcAddress`, statically-linked CRT heap growth via `HeapAlloc`/real `kernelbase`) keep
  their charge → **overcount, bounded by the title's own footprint** (unlike the old host
  accounting, it is not ≥ XCL's ~15 GB from t≈6 s). Direction of misses: the *missed
  allocations* undercount (safe); only the *invisible frees* leak charges upward, and only
  after the title actually released memory it once allocated. Unknown pointers never debit
  (XCL-internal `VirtualFree` in `title_textures` is paired through the same HLE entries, so
  it nets out; `mem::VirtualFree` raw calls touch nothing).

## Deviations from design guidance (evidence-based)

1. Charge at the shared `VirtualAlloc` HLE wrapper instead of the `XMemVirtualAlloc` body —
   `XMemVirtualAlloc` delegates to the wrapper; charging both would double-count.
2. Guidance suggested charging `runtime_alloc`; not charged (double-count argument above).
3. Guidance's undercount caveat re VirtualFree: kernel32 aliasing resolves the title's
   `VirtualFree` to the HLE wrapper, so title frees ARE distinguishable from XCL-internal raw
   `mem::VirtualFree` (map-keyed debits). Residual gap: GetProcAddress-to-real-kernel32 frees.

## Test (TDD, ECC skill `tdd-workflow`)

RED: tests-only commit failed to compile (`E0425/E0433`: accounting API absent) — valid
compile-time RED. GREEN + full lib: `cargo test -p xcl --lib` → 1358 passed, 0 failed,
27 ignored; kernelx module: 48 passed (1 pre-existing ignored `scatter_timing`, also passes).
New tests (all pass):
- `title_mem_accounting_charges_xmem_alloc_default_and_debits_the_free`
- `title_mem_accounting_charges_virtual_alloc_and_releases_with_virtual_free`
- `title_mem_accounting_charges_physical_pages_per_page`
Exact per-pointer assertions (block maps) because module tests run concurrently; the existing
`title_memory_status_reports_budget` (private mode) is untouched and passes. Tests track blocks
via `cfg!(test)` without any env/global mode mutation → no inter-test races; mode passed to
`fill_title_memory_status` explicitly.

## Post-merge run (GTA VI, lockhart, budget restored to 8192 in xcl.toml)

```
set XCL_TITLE_MEM_USED=title
xcl run <GTA6\default.xex or game folder>
```
Expect one log line `TitleMemoryStatus: accounting=title ...`; if the park dissolves past
~158 s (experiment 4's shifted onset) with 8192 MB, the title-budget gate hypothesis is
confirmed with honest numbers. If avail again pins at 0, `title_used` shows which path holds it.

REA: not applicable — pure source work in a repository we own (XCL is a GPL-2.0 console
emulation fork whose full source is here); per `rea-evidence.md` §2/§3 REA is for artifact-only
targets, no binary claim is made here that needs bin-file evidence.
