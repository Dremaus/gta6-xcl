# 5 — Upstream PRs of `integration/nvidia-world` (#2057) against our HEAD

Baseline: `8b957bec` + our uncommitted local patches (XCL_SKIP_PREPARATION, `memcap.rs`, uma fix), captured as
`574a60f1` so the branch is reproducible. Worktree `D:\git\xcl-wt-up`, branch `agent/upstream` (`4f16f553`).
`D:\git\xcl` was not modified. Nothing here leaves the XCL repo (GPL-2.0-only); no upstream code is copied into
`D:\git\gta6-30fps`.

Classes: (a) already in HEAD, (b) perf/memory win, (c) risky/behavioural, (d) unavailable.

| PR | what it changes | in HEAD | class | applies | risk |
|----|-----------------|---------|-------|---------|------|
| #1329 | `XCL_UMA_SHADOW`: committed window gets a VRAM shadow | no | b/c | **no** — sparse.rs:501,590 | VRAM +host copy; 8 GB card must not default it on |
| #1850 | `globallycoherent` only when needed | **yes** (`83ad6a55`) | a | n/a (PR CLOSED) | landed; biggest NVIDIA win already ours |
| #1993 | copy-back after submit does not wait for title | no | b/c | yes (1058 l, 925 in sparse.rs) | changes submit/fence lifetime — needs smoke |
| #1766 | `XCL_GPU_PROFILE` (diagnostics only) | no | b | **no** — bind.rs:1020,1027, console_list.rs:915,921, real.rs:4477,4516 | none (log only) |
| #1983 | wait watchdog lists XCL's own waits | **yes** (`5760b899`) | a | n/a | — |
| #1599 | AutoSubmitDisabled queue waits for Submit | no | c | yes (163 l dstorage.rs) | ordering change, needs smoke |
| #929 | list #139 Reset via `title_list::reset` | **yes** (`06c9f550`) | a | n/a | — |
| #2052 | wait covered by earlier signal is not a cycle | no | c | yes (68 l list_x.rs) | false negative could hide a real cycle |
| #1517 | sparse tiles mapped together before next submit | no | b | **no** — sparse.rs:237/249,570/575,1594/1599,2100/2105,2201/2206 | low once rebased; the load-time lever |
| #1792 | a mapping call commits sparse pages once per run | no | b | **yes (clean)** | low; 1 file, additive |
| #1184 | scatter unmap commits home pages in runs | no | b | **no** — kernelx.rs:1525,1545 | low once rebased |
| #1453 | unpin retired split segments; release ABA guard | no | b | **yes (clean)** | low; leak fix + tests |
| #1422 | allocator put aside keeps recordings' memory (#1358) | no | b/c | yes (236 l, 5 files) | medium: allocator lifetime |
| #1747 | multi-heap UpdateTileMappings in vram::Pages | **yes** (`c4d37bec`) | a | n/a | — |
| #1791 | ExecuteIndirect reads earlier arguments | **yes** (`4e3515ee`) | a | n/a | — |
| #605 | R9G9B9E5 → R11G11B10 promote | **yes** (`177cd407`) | a | n/a | — |
| LOOK_SKIP | `XCL_LOOK_SKIP` in the look machinery (`7c18bc41`+) | no | c | n/a — needs ~10 look commits | coherence relaxed up to ~20 ms |
| PRECOMPILE_SLICE | `5ea55e2c`, 9 lines in `precompile` | no | b | **no** — shaders.rs:1706 | none, but redundant with XCL_SKIP_PREPARATION |

## Cherry-pick conflicts (recorded, not resolved)
- #1329: `sparse.rs:501`, `:590` (shadow window vs. our sparse layout).
- #1517: `sparse.rs:237`, `:249`, `:570`, `:575`, `:1594`, `:1599`, `:2100`, `:2105`, `:2201`, `:2206`.
- #1184: `kernelx.rs:1525`, `:1545`.
- #1766: `bind.rs:1020`, `:1027`; `console_list.rs:915`, `:921`; `real.rs:4477`, `:4516`.
- #1850: `emit.rs`, `tests.rs` — moot, the same change is already in HEAD.
- #5ea55e2c (PRECOMPILE_SLICE): `shaders.rs:1706` — `precompile` moved by HEAD's startup-preparation merge.

## Branch `agent/upstream` (4f16f553)
```
4f16f553 D3D12.X: unpin retired split segments from alloc_pool and guard title_list::release ABA  (#1453)
1b7da651 kernelx: commit a mapping call's sparse pages once per run, not per page             (#1792)
574a60f1 local: XCL_SKIP_PREPARATION, memcap, uma fix (patched HEAD baseline)
8b957bec Merge pull request #2555 from bmjask/shaders/startup-preparation
```
Rationale: #1792 removes the per-page `UpdateTileMappings`+fence (~0.5 ms/page on NVIDIA; 3.4 GB in one
`MapTitlePhysicalPages` = ~24 s main-thread stall, which is exactly our world-load window) and #1453 stops
`alloc_pool` leaking a PC allocator on every list Reset/split retirement. Neither touches submit ordering or
coherence, so both are safe to run with the current env knobs.

Build (lock held, `CARGO_TARGET_DIR=D:\git\xcl\target`):
- `cargo build --release -p xcl` → **exit 0**, 1m34s, 3 pre-existing warnings, `target\release\xcl.exe` rebuilt 12:56.
- `cargo test --release -p xcl --lib -- title_list::tests` → **5 passed**, incl. both new #1453 tests.
- `cargo test --release -p xcl --lib -- kernelx::` → **43 passed, 1 ignored** (covers the #1792 path; it adds no test).

## Recommended next cherry-picks
1. **#1422** — applies cleanly; held recordings' sparse blocks are decommitted and can be re-handed while a
   submitted draw still reads them (`#1358`, 240 swaps/60 s). Fits the "garbage indirect arguments" symptom; verify
   with a world-load smoke before keeping.
2. **#2052** — applies cleanly, 68 lines; measured 14–32 spurious cycle breaks *per world load*, each one releasing
   GPU work early. Small but sync-graph behavioural → smoke-run before merge.
3. **#1517 then #1184, rebased** — the real load-time fix (142 → 3.2 µs/page) plus the integration branch's
   `70a160e`/`0764a57` put-off-mapping commits on top. Do not hand-resolve the 10 hunks in `sparse.rs`; the branch
   author rebased these within the last day, so re-fetch before writing a resolution.
4. **#1850 is already ours** — do not re-cherry-pick; if the title is still slow on compute, check that
   `XCL_HEAP_WINDOWS=1` is set, since the win is measured on heap windows.
5. Not worth it for the 8 GB/16 GB target: #1329 (adds a VRAM shadow copy), LOOK_SKIP (relaxes coherence), #1766
   (diagnostics), PRECOMPILE_SLICE (our `XCL_SKIP_PREPARATION` already removes the whole precompile pass).

## Notes
- Our baseline commit exists only on `agent/upstream`; `D:\git\xcl` was not touched by this session and still holds
  those edits uncommitted (another session was editing that checkout while this ran). Drop `574a60f1` (or rebase
  it) if this branch is ever proposed upstream.
- The 24 GB commit / 58k-pipeline death is not addressed by any single clean PR here: #1517 + the loading series is
  the load-time half, #1422/#1453 the leak half. There is no upstream equivalent of `memcap.rs`.
