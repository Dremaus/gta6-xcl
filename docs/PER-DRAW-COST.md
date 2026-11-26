# Per-draw host cost (Agent K) — VICTORY_DRAW_READY_CACHE

Date: 2026-11-26. Tree: `D:\git\VItoriaBr-opt-hle` (Agent A's opt-hle).
Files touched: `crates/victory-gpu/src/draw.rs` only (+242/−22, commit
`02f224f` on branch `hle-opt-gameinput-xmem`).
Game was not launched for this document (Claude owns game runs tonight).
GPL-3.0; no game data in the tree.

Streszczenie (PL): rysunek klatki z logów A/B (04:33 i 06:00) pokazuje, że
wątek renderujący liczy drawy w 16–78 ms na klatkę, a ściana czasu idzie na
`preparing`/staging (414–1036 ms), `copy-back` (208–430 ms) i czekanie
`lines and settling` w Present (768–1259 ms). Per-draw CPU jest realne, ale
mniejsze. Patch (`VICTORY_DRAW_READY_CACHE=1`) usuwa z każdego drawa powtarzalne
wyszukiwania kopii buforów w globalnej mapie (≈20–60 blokad + skanów BTreeMap na
draw) i przenosi je do pamięci listy - oczekiwana poprawka rzędu kilku procent
klatki, nie rzędu 2x.

## 1. What runs PER DRAW (code evidence)

Path: title `DrawInstanced`/`DrawIndexedInstanced` → `State::draw` (draw.rs)
→ `prepare_for` → `bind` → per stage `tables` → per used entry `table_entry`
→ `mirror` + `readable`. queue.rs holds only queue-level calls (execute,
present); no per-draw work. Counts are per draw of a world scene
(typical: 2 stages, 10–30 used table entries, 1–4 vertex slots, 1 index
buffer, up to 8 render targets + depth).

| # | Step | Where | Runs | Rough cost |
|---|---|---|---|---|
| 1 | Host pipeline lookup (`host_pipeline`, skipped/builder checks) | pipeline.rs (`Table<24>`) | 1× | ns-level |
| 2 | `early_textures` budget check + bake-shader set probe | draw.rs `bind` first line | 1× | ~0.1 µs |
| 3 | Descriptor heaps / root signature / PSO `Set*` — only on change | `bind` | 0–3× | ~0 when stable |
| 4 | Per stage: `values = vec![0u32; dwords]` alloc + user-data words (`host_word`, `user_value`) + `SetGraphicsRoot32BitConstants` | `bind` | 2× | ~1–2 µs |
| 5 | `tables()` per used entry: `fresh` Vec, `heap_of` + `heap.index` arithmetic | `tables` | ~10–30× | ~0.5 µs/entry |
| 6 | `table_entry` → `HostHeap::mirror`: `made` mutex + views RwLock read + `View` clone + key compare | descriptor/host.rs:2005 | ~10–30× | ~0.3–1 µs/entry |
| 7 | `readable` → `placed_texture` probe + `buffer_copy`: **1–3 × `shadow::find`/`exact` — each a global `buffers()` mutex + BTreeMap reverse scan (≤64) + Arc clone** | descriptor/host.rs:2258, shadow.rs:3505 | per buffer entry | ~1–3 µs/entry |
| 8 | `defer_refresh` (deferred mutex + HashSet insert) / `defer_gpu_write` (mutex + Vec push, no dedup) | host.rs:6429–6455 | per buffer entry | ~0.2–0.5 µs |
| 9 | Texture view arms: `alias_of` (env-off fast) + `hosted` mutex ×2–3 + `twin_use` + `ensure_state` (`states` mutex + `GetDesc` COM) | `readable` match | per texture entry | ~1–3 µs/entry |
| 10 | VB/IB binds: **`shadow::find_any` ×(1–5)** (same global mutex + scan) + refresh + `IASet*` | `prepare_for` | 1× | ~1–5 µs |
| 11 | Targets + depth: `ensure_state` per RT, `twin_use` depth | `prepare_for` | ~2–9× | ~1–4 µs |
| 12 | Root SRV/UAV binds: slot lookup cached (`root_srv_slots`), still refresh + `SetGraphicsRootDescriptorTable` | `bind` loops | per view | ~1–3 µs |
| 13 | `DrawInstanced` COM record call itself | `draw` | 1× | ~1–3 µs |
| 14 | diagnostics-only: `trace`/`note_op` (string build) | gated behind `dred_on()`/capture | 1× | ~0 unless DRED |

Sum ≈ **15–60 µs CPU per draw**. Cross-check: the frame line
`recording, all threads: 1513.8 ms in 75257 calls` ≈ 20 µs/call wall — same
order (that wall includes blocking waits, see §2).

## 2. What runs PER FRAME (not per draw)

| Step | Where | Measured (ab-opt-new run, 04:33Z; night runs 06:00) |
|---|---|---|
| `heap_buffers` pass — changed slots (870–1600) or full rescan every 64 frames (28k–70k slots) + unwatched whole-span refresh | draw.rs `heap_buffers` (Agent A's deferral) | inside `preparing` |
| Texture staging pass (`heap_textures`, budget 250/750 ms, early 12 ms, bake 1500 ms) | draw.rs, once per frame + bake | `preparing` **414–1036 ms/frame median** — the biggest single line item (MEMORY-STREAMING C1; Agent E) |
| Deferred copies at submit (title memory → host copies, page-fault heavy) | host.rs `execute` | `copies 104–684 ms`, 171–219 MB/frame; **kernel 234–750 ms on the submit thread** |
| Copy-back (snapshot+compare of declared writes) | shadow.rs | `copy-back 208–430 ms` |
| Present-side waits (fence settle, `lines and settling`) | queue.rs | `present call 783–1393 ms` — the render thread *waits*, does not compute |
| Render thread CPU total | framelog `ran … (user …, kernel …)` | **16–78 ms/frame** — what all the per-draw work above actually costs |

So the night-run statement "per-draw share ≈ 0.2–0.6 ms" is frame_ms ÷
draws (631–1880 ms ÷ 3000–3700 draws): the per-draw *count of draws* sets the
frame, but the per-draw *CPU* is bounded by the 16–78 ms the render thread
reports. The rest of the wall is staging + copies + GPU drain (items 2–5
above), which this patch does not touch.

## 3. The patch

**Switch: `VICTORY_DRAW_READY_CACHE=1`** (off by default; env-only, per
process). One mechanism: *a list remembers the host copy of a buffer once and
later draws refresh that copy instead of searching the global copy map again.*

- `State` (per title command list, draw.rs) gains two memos:
  `ready_copies: (view index, generation) → (Arc<Shadow>, address, len)` and
  `ready_buffers: (address, size) → Arc<Shadow>` for VB/IB binds.
- `State::readied` (used by `table_entry` and all three `tables()` readable
  sites) hits the memo by the descriptor record's `(i, generation)` — the
  pair that names one immutable `View` (generations move forward when the
  record is rewritten). Miss: normal `readable`, plus remember if the view
  names buffer memory (`cacheable`).
- `State::bound_shadow` does the same for `shadow::find_any` in the VB/IB
  binds of `prepare_for`.
- `readable` was split verbatim into `buffer_reads` (refresh + `gpu_writes`
  decision with `STORES`/`write_skip` evaluated *at call time*) and
  `readable_texture` (the state/twin/upload arms). The hit path runs
  `buffer_reads` exactly as before — data freshness per draw is unchanged.
- Memos are cleared in `State::tables_done` (slots given back) and by list
  reset — they live exactly as long as the list.
- Counters `DRAW_READY_CACHE[0/1]` (searched/reused) print every 512 lists
  when the switch is on.

Why semantics are preserved:
- `defer_refresh` already collapses the identical range per list; the memo
  removes the *lookups before* that dedup (steps 7 and 10, the `buffers()`
  mutex + BTreeMap scans), which are a pure function of the view and the copy
  map while the list itself keeps the found copy alive (its refresh steps
  hold `Arc<Shadow>`).
- Reusing the copy found once is the precedent this module already ships for
  root SRV/UAV slots: `root_srv_slots` — "later draws of the list bring that
  one up to date, whatever copy the address would find by then."
- Texture/placed-texture views are never remembered (`cacheable` only names
  buffer memory; the arms' per-draw state tracking always runs). For buffer
  views the arms are provably no-ops on host copies (`resource::hosted`,
  `alias_of`, `twin` all answer none for `BUFFER`; `buffer_bytes(null)` is
  safe). One diagnostics-only difference: a remembered unordered buffer view
  skips `capture::note_target` in the frame listing.

Tests added (`draw::tests`): record words key the view identity; `cacheable`
selects exactly the buffer-naming view kinds; the memos leave with the list
(`tables_done`, reset). `cargo test --offline -p victory-gpu`: **179 passed,
0 failed, 5 ignored** (baseline ~176 + 3; the known
`indirect::tests::warp_budget…` WARP flake passed this run).
`cargo build --offline --release -p victory --features diagnostics`: clean.
`cargo test --offline -p victory-hle`: 112+1+1 passed (xmem/gameinput not
touched by this patch).

## 4. A/B command (opt-hle binary, same env as Launch-VItoriaBr-AB.ps1 -Build opt -Memory -Borderless -Uncap -NoXmemBatch)

The stock `-Build opt` launcher points at `D:\git\VItoriaBr-opt` (Claude's
tree tonight) — run this instead, it replicates the same env on opt-hle:

```powershell
$repo = 'D:\git\VItoriaBr-opt-hle'
$gameExe = 'D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\game_scarlett_master.exe'
$logs = 'D:\Gry\VItoriaBr-data\logs'
$env:VICTORY_CONFIG = "$repo\victory.toml"
# the launcher's opt set:
$env:VICTORY_HOST_WAVE='32'; $env:VICTORY_VIEW_LIMIT='1000000'
$env:VICTORY_LOG='info'; $env:VICTORY_FRAME_LOG='1'; $env:VICTORY_CARD_ACCOUNTING='1'
$env:VICTORY_DISPLAY_MODE='1280x720'; $env:VICTORY_AMBIENT='0'
$env:VICTORY_RELAY='2'; $env:VICTORY_QUEUE2='1'; $env:VICTORY_ASYNC_SUBMIT='1'
$env:VICTORY_COPY_PLAIN='1'; $env:VICTORY_TEXTURE_NO_WAIT='1'
$env:VICTORY_CARD_BUFFERS_MIN_MB='1'; $env:VICTORY_CARD_BUFFERS_MB='768'
$env:VICTORY_TEXTURE_BUDGET_MB='4096'; $env:VICTORY_PAGE_WRITES='slots'
$env:VICTORY_WIDE_REFRESH='1'; $env:VICTORY_WIDE_MERGE='1'; $env:VICTORY_JOIN_COPIES='1'
$env:VICTORY_LEVELS_ON_DEMAND='1'; $env:VICTORY_CARD_REHASH_RUNS='1'
$env:VICTORY_STAGING_POOL='1'; $env:VICTORY_LATE_WAIT='3'
$env:VICTORY_WIDE_BACK='1'; $env:VICTORY_BACK_OWN_VIEW='1'
$env:VICTORY_SHADER_LOOP_LIMIT='256'; $env:VICTORY_BVH_BUILDER='0'
$env:VICTORY_CARD_FETCH_INFLIGHT='0'; $env:VICTORY_REFRESH='120'
$env:VICTORY_BORDERLESS='1'; $env:VICTORY_UNCAP='1'; $env:VICTORY_HLE_XMEM_BATCH='0'
$env:VICTORY_TEXTURE_CATCHUP='0'; $env:VICTORY_TEXTURE_STAGE_MS='24'; $env:VICTORY_TEXTURE_STAGE_MB='64'
# reproducible camera/walk (gameinput.rs scripted keys):
$env:VICTORY_KEYS = '60:w,5:s,60:a,5:d,120:w'
# arm A: $env:VICTORY_DRAW_READY_CACHE unset; arm B: ='1'
$arm = 'A'   # then 'B'
Push-Location $repo
if ($arm -eq 'B') { $env:VICTORY_DRAW_READY_CACHE='1' } else { Remove-Item Env:VICTORY_DRAW_READY_CACHE -ErrorAction SilentlyContinue }
$p = Start-Process -FilePath "$repo\target\release\victory.exe" `
  -ArgumentList @('run', $gameExe, '--execute') -PassThru `
  -RedirectStandardOutput "$logs\draw-$arm-stdout.log" -RedirectStandardError "$logs\draw-$arm-stderr.log"
Write-Host "draw $arm PID $($p.Id) stderr: $logs\draw-$arm-stderr.log"
Pop-Location
```

Analysis (both arms, same stretch after the world loads):

```powershell
cd D:\git\gta6-30fps
python tools\bench\parse_frame_cost.py "D:\Gry\VItoriaBr-data\logs\draw-A-stderr.log"
python tools\bench\parse_frame_cost.py "D:\Gry\VItoriaBr-data\logs\draw-B-stderr.log"
Select-String "D:\Gry\VItoriaBr-data\logs\draw-B-stderr.log" -Pattern 'buffer copies looked up and remembered'
Select-String "D:\Gry\VItoriaBr-data\logs\draw-B-stderr.log" -Pattern 'render thread: ran|recording, all threads'
```

Gate for promotion: p50 `render thread: ran` ms and p50 `recording, all
threads` ms/3000 draws drop by ≥15% in B vs A, `reused` ≫ `searched`, no new
device removal, identical picture on a screenshot spot.

## 5. Honest expected impact at 5000 draws

The cache removes ~20–60 global `buffers()` mutex+BTreeMap probes and a
similar number of made/views mutexes per draw → ~100k–300k fewer cross-thread
lock acquisitions per frame (the same lock is hammered by the submit thread's
copies and the once-per-frame heap pass, so contention amplifies each probe).
That targets the *per-draw CPU line only*: 16–78 ms/frame measured today,
consistent with 15–60 µs/draw. Best case 2–3× faster on that line ⇒
**−5 to −50 ms/frame**, i.e. at 3500 draws/frame a frame of 631–1880 ms moves
by roughly **0.5–8%** ⇒ expected **+0.0–0.1 fps** at current rates
(0.5–1.6 fps). The frame wall is staging (`preparing` 414–1036 ms), copies /
copy-back (208–684 + 208–430 ms) and the present-side drain (768–1259 ms):
those live in `preparing`/relay/GPU-execution (MEMORY-STREAMING, STABILITY-TDR
slices), not in per-draw bookkeeping, and no per-draw cache can cut them.
Secondary hoped-for effect: fewer probes ⇒ the submit thread holds
`buffers()` for shorter stretches ⇒ render/present waits may shrink a little
too; measure `in the present call`, not just `ran`, in the A/B.

## 6. What is left on the table (for the next slice)

- `defer_gpu_write` has no per-list dedup (duplicate GpuWrite steps per draw);
  `writing()` dedups at submit, but the pushes + mutex are per draw.
- Per-stage `vec![0u32; dwords]` allocation per draw (small, easy).
- The once-per-frame `heap_buffers` rescan (every 64 frames, 28k–70k
  `mirror`+`buffer_copy` probes) could ride the same memo.
- `texture::mapped_bytes` VirtualQuery storms inside the staging pass
  (Agent E's line), not per draw.
