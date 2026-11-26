# Texture residency for 8 GB cards: LNX `SKIP_MIPS` vs cool-fox `DROP_MIPS`

Date: 2026-11-26
Status: assessment only, no patch applied
Scope: read-only review of `D:\git\LNX-victory` (commit `c04e615`), `cool-fox-12gb`
(HEAD `67298e8`; feature commit `fcb4f71`), and `D:\git\VItoriaBr-opt`
(`d93d263` plus the two uncommitted files `descriptor/host.rs` and `draw.rs`).
The game (PID 21992) and all trees were left untouched. No game files or bytes
are included. Firecrawl MCP is not registered in this session, so the web
evidence below comes from `webfetch`/`websearch`; REA was not needed because no
binary analysis is required.

## 1. Executive summary

There are two fundamentally different patches:

| | LNX-victory `VICTORY_TEXTURE_SKIP_MIPS` | cool-fox `VICTORY_TEXTURE_DROP_MIPS` |
|---|---|---|
| Mechanism | Keep the title's resource shape and mip numbering. Create a **reserved** texture; leave the top `k` mips unmapped; map the rest to a private heap. Clamp SRV sampling to the first backed mip. | Shrink the **host copy** itself: create a texture whose level 0 is title level `N` (`from_level`). Renumber every subresource, shift views, and remap copies/readback. |
| Blast radius | ~2 production files in LNX; our tree needs ~3-4 | 5 source files, +829/-12 in `fcb4f71`; docs claim 8 files/+897/-14 including docs/tools |
| Subresource numbering | Unchanged | Changed: `mip - drop + slice * (mips - drop)` |
| Upload/staging work | Unchanged; uploads into unmapped mips are dropped by tier 2 | Host desc is smaller, so the staging buffer is smaller; the source-read shortening (`staging_layout`) is **not wired** at HEAD |
| Views | `ResourceMinLODClamp = k` (sampling clamp) | `MostDetailedMip -= base`, `MipLevels` reduced, clamp reduced |
| Our tree fit | Good: `tiles.rs` already creates reserved textures and checks tier 2 | Poor: our `Staging`/`HostTexture` lack the base/first/level0/serial fields; many extra subresource users exist |

**Recommendation: do not port cool-fox `DROP_MIPS` now. If a residency
experiment is wanted, port the LNX `SKIP_MIPS` mechanism only, default off, in
the order in section 5.1. Expect a real VRAM reduction (reference reports
1.5-4 GB), not a frame-rate win. Our own E2b measurement already showed that
2.2 GB less VRAM did not move fps; the current frame is CPU/submit-bound
(`docs/EXPERIMENTS-2026-11-25.md`, `docs/PERF-DIAGNOSIS-2026-11-25.md`).**

The LNX README reports ~4 GB of card memory saved on an RTX 5060 Ti 8 GB, but
still only 7-8 fps in Series S + host FSR, GPU ~66% busy (CPU-side bound). The
cool-fox README reports 2.70 fps upstream vs 2.40 fps with `DROP_MIPS=1` at
1080p, with different draw counts (4,470 vs 6,050), and 7.70 fps only with
`RENDER_SCALE=0.5` (540p world upscaled). Neither reference demonstrates a
30 fps path.

## 2. What our tree already has

Relevant code in `D:\git\VItoriaBr-opt` (working-tree line numbers; the two
uncommitted files can shift them):

| Area | Site | What exists |
|---|---|---|
| Host copy creation | `resource.rs:1296 hosted`, `resource.rs:2042 host_texture`, `resource.rs:2053 host_texture_as` | Lazy host copies; a `reserved` flag already creates `ID3D12Resource` via `CreateReservedResource` (`resource.rs:2119`). |
| Reserved/tiled levels | `tiles.rs:78 wanted`, `tiles.rs:281 Tiled::make`, `tiles.rs:557 UpdateTileMappings` | Tier-2 check, 64 KiB tile pool, per-level mapping, `first_shown`, `show_from`. `VICTORY_LEVELS_ON_DEMAND=1` (default off). |
| Upload/detile | `texture.rs:646 upload`, `texture.rs:1144 detile`, `texture.rs:1424 staging` | Full console layout is detiled into a staging buffer; every subresource is copied by title index. |
| Copies/readback | `list.rs:839 unlike`, `list.rs:855 copy_resource`, `list.rs:937 copy_texture_region`, `list.rs:1106 read_back`, `list.rs:1180 resolve` | Copy/resolve/readback use title subresource indices directly. |
| Views | `descriptor/host.rs:2811 make`, `descriptor/host.rs:2873 first_shown`, `descriptor/host.rs:2896 CreateShaderResourceView` | SRV creation already has a tile-path level shift (`show_from`) after `fits`. |
| Accounting | `resource.rs:1416 room`, `resource.rs:1464 targets_room_kept`, `resource.rs:1929 HOST_TEXTURES`, `resource.rs:1934 host_bytes`, `resource.rs:1947 HostTexture::new` | `GetResourceAllocationInfo` bytes, `KINDS[1]` filled-texture bytes, `room()` gate. |
| Other subresource users | `capture.rs:318`, `host.rs:1308`, `texture.rs:304`, `texture.rs:738`, `texture.rs:864`, `tiles.rs:1109` | Frame capture, depth-twin/plane copies, alias-through-buffer, upload, zero-fill, tile readback. These matter for any renumbering scheme. |

The existing reserved/tile path is the single most important asset: the hard
D3D12 work (tier-2 query, 64 KiB alignment, heap creation, `UpdateTileMappings`,
private heap lifetime) is already understood in this tree.

## 3. Side-by-side implementation

### 3.1 Functions and structs

| Concern | LNX-victory | cool-fox-12gb |
|---|---|---|
| Gate / policy | `resource.rs:2320 skip_mips(host, desc) -> Option<u32>`; `VICTORY_TEXTURE_SKIP_MIPS` 1-3, default 0; fixed `k` | `resource.rs:1513 drop_levels(desc) -> u32`; `VICTORY_TEXTURE_DROP_MIPS` 0-4, default 0; `n = min(n, mips-1)` |
| Actual drop of a resource | `resource.rs:2386 reserved_texture(host, desc, state, k)`; returns `ID3D12Resource` | `resource.rs:1537 dropped(this) -> u32`; uses `made_copy(this).base` when a host copy exists, else `drop_levels(desc)` |
| Mapping | None. Resource desc/mips/subresources unchanged. | `resource.rs:1551 host_subresource(this, index) -> Option<u32>`; `resource.rs:1561 title_subresources`; `resource.rs:1569 readback_subresource` |
| View shift | `resource.rs:2529 clamp_to_backed(texture, &mut Option<SRV_DESC>, k)` sets `ResourceMinLODClamp = max(k)`; call at `descriptor/host.rs:2980` | `resource.rs:1584 shift_levels(drop, &mut first, &mut levels, &mut clamp)`; `descriptor/host.rs:4388 from_base`, `:4400 clamp_view_mips`, call at `:4242` |
| Host desc shrink | No | `resource.rs:104 ResourceDesc::from_level(base)`; `resource.rs:1272 base_level`; `resource.rs:1620 hosted` creates `host_texture(&r.desc.from_level(base))` |
| Staging struct | `HostTexture` unchanged; no new staging fields | `texture.rs:35 Staging` adds `drop`, `first_mip`, `title_bytes` (and, on this tree, `base`, `first`, `level0`, `serial`, `holds`, `once`, etc.) |
| Upload | Unchanged; copies all subresources; tier 2 drops writes into unmapped top mips | `texture.rs:673 upload`; `Staging::part` indexes title mips; `texture.rs:1888 staging`; `staging_layout` exists but is `#[allow(dead_code)]` at HEAD |
| Detile | Unchanged | `texture.rs:1507 detile`; `layout.detile(tiled, mip + first_mip, ...)`; `part(i)` returns `self.first + i % (mips-first)` |
| Alias | No guard; host descs are equal, so `GetCopyableFootprints` still matches; skipped top mips read zero | `texture.rs:189 alias` rejects if `dropped(placed) != dropped(source)` |
| Copies | No remap; top-mip writes are dropped by tier 2 | `list.rs:888 unlike(dst, src, mapped)`; `:993 copy_levels`; `:1041 copy_texture_region` remaps dst/src; `:1269 read_back` remaps; `:1345 resolve` uses remapped indices |
| Accounting | `HostTexture::new` uses `host_bytes` (`GetResourceAllocationInfo`); no explicit skipped-page accounting in LNX | Host desc is smaller, so `host_bytes` is smaller; `title_bytes`/`staging` fields support budget checks |
| Warm path | None | `apps/victory/src/translate.rs` changed in `fcb4f71` for an unrelated warm-capture path; it does **not** follow mip mapping. Our tree's `warm.rs` is shader-only. |
| Shader cache | Untouched | `DROP_MIPS` does not enter `shader_cache.rs`; the key change in the docs is for `VICTORY_NAN_SCRUB`, a separate shader feature |

### 3.2 Eligibility, exactly as coded

LNX `skip_mips` returns `k` only when all of these hold:

- tiled-resources tier >= 2 (checked once with `CheckFeatureSupport`);
- format is BC1-BC5 or BC6H-BC7 (`70..=84 | 94..=99`);
- dimension is `TEXTURE2D` (3), `depth_or_array_size == 1`;
- `mip_levels > k`, width >= 512, height >= 512;
- `sample_count <= 1`;
- no render-target, depth or unordered-access flag (`flags & 0x7 == 0`).

cool-fox `drop_levels` returns `n` only when:

- `fills(desc)` (not a buffer; no target/depth/UAV flag);
- `dimension == TEXTURE2D`, `depth_or_array_size == 1`, `sample_count <= 1`;
- `mip_levels >= 5`;
- `n = min(n, mip_levels - 1)`, min side >= 512, and both sides are a multiple
  of `4 << n`, so host level `m` is title level `m + n` in whole 4-texel blocks.

**Documentation contradiction:** `docs/HYBRID-8GB.md` says arrays and cubes are
included, but the code excludes them (`depth_or_array_size != 1` returns 0), and
its own "known issues" says arrays and MSAA do not take the drop path. Trust the
code, not the table. LNX also excludes arrays and MSAA.

### 3.3 Invariants

LNX:

1. The host resource keeps the title's `ResourceDesc` (width, height, mips,
   array size, subresource count). Barriers, size queries, copies and readback
   keep their numbering.
2. Tiles from subresource `k` onward are mapped to one heap; tiles before `k`
   are unmapped. Tier 2 guarantees reads return zero and writes are dropped.
3. The private data GUID stores `k`; the private `ID3D12Heap` keeps the heap
   alive for the texture's lifetime.
4. Every SRV that reaches level `k` gets `ResourceMinLODClamp >= k`; a view
   that only covers skipped levels is currently left alone and reads zero.
5. The texture is not a render target, depth target or UAV, so no clear/write
   path depends on the skipped levels.

cool-fox:

1. Host level `m` is title level `m + base`; `base` is the configured drop or a
   later level chosen by held-only residency.
2. Every external subresource reference must be remapped by
   `host_subresource`; aliases with different `base` are refused; copies between
   whole resources are done level by level.
3. Views subtract `base` from `MostDetailedMip`/`ResourceMinLODClamp` and reduce
   `MipLevels`; `clamp_view_mips` keeps explicit views inside the shrunken
   texture.
4. The tile path is disabled for a dropped texture (`drop_levels != 0` keeps it
   on the plain path), because tiles number levels as the title does.
5. Staging indexes title mips through `first`/`first_mip`; the source buffer
   may be shortened only for a single 2D slice (currently written but not
   wired).

### 3.4 What the references actually measured

| Source | Machine | Result | Caveat |
|---|---|---|---|
| cool-fox README / `docs/HYBRID-8GB.md` | i9-14900HX, RTX 4060 Laptop 8 GB, 1080p | upstream 2.70 fps / 370 ms, ~4,470 draws; `DROP_MIPS=1` 2.40 fps / 417 ms, ~6,050 draws; 0.31 -> 0.11 MB per indexed texture upload | Different scenes/draw counts; the doc itself says not a same-scene A/B. 8 GB card still at budget with 12-14k texture slots waiting. 7.70 fps came only from `RENDER_SCALE=0.5` (540p world, upscaled). |
| LNX README | RTX 5060 Ti 8 GB, Ryzen 5 9600X, 32 GB | ~4 GB card memory saved; 3.3-4.6 fps in world (was 1.3); 7-8 fps Series S + host FSR, GPU ~66% busy | fps improvement is confounded with `VICTORY_CARD_FETCH_INFLIGHT=0` and `VICTORY_TEXTURE_NO_WAIT=1`; skip-mips alone was not isolated. |
| XCL PR #2385 (different layer, same class of fix) | RTX 3060 12 GB; RTX 5070 Ti 16 GB; RX 7800 XT 16 GB | 12 GB 3060: 12,606 -> 10,658 MB local video memory at the same elapsed time; 2,685 textures / 4,765 MB of tiles omitted; no device removal. Forced `XCL_TEXTURE_MAX=1024` on 16 GB: 3.7 GB of texture tiles kept out. | 8 GB untested; "tile counter, not a claim of net VRAM saved"; same title but a different compatibility layer. GPU tests confirm clamped filtered sampling is bit-identical to a fully backed texture with the same clamp; `Load`/mip queries of skipped mips are not clamped and read zero. |
| Our tree (`docs/EXPERIMENTS-2026-11-25.md`) | RTX 4060 Laptop 8 GB, 16 GB | Baseline 0.2-1 fps, 7.5 GB VRAM; E2b (texture budget 4096 MB, card buffers 768 MB) 5.3 GB VRAM, same 1 fps | The strongest local evidence: 2.2 GB less VRAM did not move fps; the frame is CPU/submit-bound. |

## 4. Expected VRAM math

For a full BC7 chain, level 0 is three quarters of the texture:

| Texture | Full chain (approx.) | After dropping 1 level | Saved |
|---|---:|---:|---:|
| 512x512 BC7, 10 mips | 341 KiB | 85 KiB | 256 KiB |
| 1024x1024 BC7, 11 mips | 1.33 MiB | 0.33 MiB | 1 MiB |
| 2048x2048 BC7, 12 mips | 5.33 MiB | 1.33 MiB | 4 MiB |
| 4096x4096 BC1, 13 mips | 10.67 MiB | 2.67 MiB | 8 MiB |

If the title has thousands of eligible textures, 1.5-4 GB is plausible; LNX
reports ~4 GB and XCL reports 3.7 GB of tiles kept out under a forced cap. But
the eligible fraction is unknown until instrumented: uncompressed UI, arrays,
cubes, MSAA, render targets and textures below 512 texels do not participate.
Do not assume the full 4 GB in our tree.

A rough demand check: cool-fox reports 12-14k slots waiting; our logs have
reported ~23k. If the average waiting texture is ~1 MB of host copy, one level
removed turns ~1 MB into ~0.25 MB and saves ~0.75 MB per texture; 10k eligible
textures would be ~7.5 GB. That is an illustrative upper bound, not a forecast;
the actual count and size distribution must be measured.

## 5. Port design for VItoriaBr-opt

### 5.1 Track A (recommended): LNX reserved top mips

Production diff estimate: **~250-320 LOC across 3-4 files** (plus tests).
This is the minimal, low-risk port because it changes no resource shape and no
subresource numbering.

| Phase | File / site (working tree) | Change | Est. LOC | Exit criterion |
|---|---|---|---:|---|
| A0. Gate and counters | `resource.rs:1268 fills` (new helpers nearby), `resource.rs:78`-equivalent tier query in `tiles.rs` or local | Parse `VICTORY_TEXTURE_SKIP_MIPS` once (0-3), query tier 2 once, log requested/enabled, add counters for textures/tiles/MB. Gate off if tier < 2 or `VICTORY_LEVELS_ON_DEMAND=1` (mutually exclusive). | 45-60 | `=0` is behavior-identical; `=1` logs one line and no texture changes yet. |
| A1. Reserved texture | `resource.rs:2053 host_texture_as`, hook before `resource.rs:2112`; new `reserved_texture` near `resource.rs:2154` | On an eligible `!reserved` texture, copy desc, set `layout = 64KB_UNDEFINED_SWIZZLE`, `alignment = 0`, `CreateReservedResource`; `GetResourceTiling`; require `k < NumStandardMips`; create heap of `(total-start)*64KiB`; one `UpdateTileMappings` from subresource `k`; `SetPrivateDataInterface` the heap and `SetPrivateData` `k`; fall back to committed on any failure. | 120-150 | Logs show N textures and MB skipped; no device removal; `=0` vs `=1` screenshots differ only by expected softness. |
| A2. SRV clamp | `resource.rs` new `skipped_mips`/`clamp_to_backed`; call in `descriptor/host.rs:2868` (after `fits`, before `first_shown`) | Read `k` from private data. For `None` desc, build a default 2D SRV (unless typeless) with `ResourceMinLODClamp=k`. For `Texture2D`/`Texture2DArray`, if the view reaches `k`, set clamp `max(k)`. Add the one-mip-view fix: if the view only covers mips below `k`, move `MostDetailedMip` to `k` and reduce `MipLevels` instead of leaving it to read zero. | 60-80 | No black/missing textures in the screenshot set; point/UI samplers and one-mip views tested; `Load` of skipped mips is documented as zero. |
| A3. Accounting | `resource.rs:1934 host_bytes`, `resource.rs:1947 HostTexture::new` | For a skipped texture, count the mapped bytes (`(total-start)*64KiB`) instead of `GetResourceAllocationInfo`'s virtual size. Optionally count each skipped page once when aliases share an address. Log skipped textures/MB on the memory line. | 25-40 | The `memory of textures` / `the card:` lines show the expected drop; `room()` admits more textures; no over-budget/over-admission. |
| A4. Optional upload/detile skip | `texture.rs:705` upload loop; `texture.rs:1168` detile loop | Do not record copies for subresources with `mip < k` (their destination is unmapped); do not detile those mips (leave zeros). Keep subresource indices unchanged. This saves copy commands/CPU, not staging bytes. | 15-25 | Fewer copy commands, same image; staging memory unchanged. |
| A5. Alias/copy/readback guards | `texture.rs:182 alias`; `list.rs:839 unlike` or copy sites | If `skipped_mips(placed) != skipped_mips(source)`, refuse the alias/copy and fall back to title-memory upload. Readback of a skipped mip returns zeros or is refused with a log. | 20-35 | No cross-alias corruption; no new device removal. |
| A6. Cache/docs | `shader_cache.rs` (no change), `victory.example.toml`, this document | Do **not** add the mip count to the shader cache key: shaders are unchanged and editing `shader_cache.rs` changes its own `include_bytes!` key, invalidating ~23,815 translations (~146 s cold per `BENCHMARK-PROTOCOL.md`). Env is read once; restart is the invalidation. Document the switch and the `Load` caveat. | 0 code | Warm cache still hits; no retranslation storm. |

Conflict with `VICTORY_LEVELS_ON_DEMAND`: our `hosted` calls
`host_texture_as(..., true)` for the tile path (`resource.rs:1359`). If the skip
hook is placed inside `host_texture_as`, it must be gated with `!reserved`; the
two mechanisms must never both map the same texture. The simplest safe rule:
**if `tiles::wanted()` is true, disable `SKIP_MIPS` for the run and log why.**
Do not A/B them together.

Heap lifetime: the private `ID3D12Heap` must be kept alive by
`SetPrivateDataInterface` on the texture. Without that, the local `heap`
variable drops and the texture points at freed memory; this is a device-removal
class bug. LNX does this at `resource.rs:2492`; copy that invariant, not just
the mapping call.

Heap granularity: LNX creates one heap per skipped texture. That is simple and
correct, but streaming thousands of textures will create/destroy many heaps.
Measure `skipped_textures` and heap churn. If it is material, reuse the
`tiles.rs` pool or a shared heap with a range allocator in a follow-up; do not
start there.

### 5.2 Track B (not recommended): cool-fox host-level drop

Production diff estimate: **~1,000-1,200 LOC across 4+ files** (plus tests).
This is the order the cool-fox patch uses, and the order in the brief:

| Phase | File / site (working tree) | Change | Est. LOC | Why it is risky here |
|---|---|---|---:|---|
| B0. Drop levels | `resource.rs:1268` nearby; new functions near `resource.rs:1934`/`2053` | `drop_levels`, `dropped`, `host_subresource`, `title_subresources`, `readback_subresource`, `shift_levels`, `from_level`, `base_level`; gate; `HostTexture.base`; `hosted` uses `from_level(base)`; tile path stays out. | 420-480 | New `base` field and lifecycle (`serial`, `grown`, `holds`) must be threaded through `HostTexture`, `Made`, `let_go_idle`, `census`, aliases. Our tree does not have cool-fox's held-only base machinery. |
| B1. Staging layout | `texture.rs:35 Staging`, `:646 upload`, `:1144 detile`, `:1424 staging` | Add `drop/first_mip/title_bytes` (and `base/first/level0/serial/holds`); implement `staging_layout`; make `staging` use the shortened layout; `detile` use `part(i)`; add `upload_from`. | 240-280 | The cool-fox HEAD still marks `staging_layout` dead code and its comment says "not yet wired"; you would be finishing an unfinished optimization, not porting a proven one. |
| B2. View/descriptor shift | `descriptor/host.rs:2811`, after `fits`/`first_shown` | `from_base`, `clamp_view_mips`, call after `first_shown`; handle 2D/2DArray/cube. | 80-100 | Order with `first_shown` matters; a double shift (tile path + drop) produces wrong mips. |
| B3. Copies/readback/resolve/alias | `list.rs:839`, `:855`, `:937`, `:1106`, `:1180`; `texture.rs:182`, `:304` | `unlike(dst,src,mapped)`; `copy_levels`; remap dst/src subresources; skip copies into omitted levels; remap readback; reject alias with different drops; audit alias-through-buffer. | 160-210 | Our tree has extra subresource users not touched by the cool-fox patch: `capture.rs:318`, `host.rs:1308`, `texture.rs:304/738/864`, `tiles.rs:1109`. Every one is a potential silent mismatch. |
| B4. Cache key | `shader_cache.rs` | **No change for DROP_MIPS.** If a live policy toggle is added, clear `STAGING`, descriptor heap and `THROUGH`; otherwise restart. Editing `shader_cache.rs` invalidates all shader translations. | 0 | Misreading the docs table as "DROP_MIPS needs a shader cache key" would cost a full retranslation for no benefit. The docs' `shader_cache.rs` line is for `VICTORY_NAN_SCRUB`. |
| B5. Warm/replay | `apps/victory/src/warm.rs`, `apps/victory/src/translate.rs` | Our `warm` path is shader-only; no texture subresource mapping. If a future warm/replay records texture copies, remap them. | 0 now | Cool-fox's `translate.rs` change in `fcb4f71` is a warm-capture feature, not mip mapping; the docs table overstates it. |

Why not Track B in our tree:

- It renumbers subresources across the entire GPU layer; our tree has more
  consumers than the cool-fox patch (capture, depth-twin planes, alias-through
  buffer, tile path). A missed site is a wrong-level copy or a silent zero.
- It depends on `HostTexture.base`, which our tree does not have; adding it
  touches budgeting, idle eviction and alias lifetime.
- Its upload-source shortening is not actually wired at HEAD, so the measured
  0.31 -> 0.11 MB/upload comes from the smaller host desc/staging buffer, not
  from the advertised source-read shortening. LNX gets the VRAM win without
  this complexity.
- The measured fps result is flat or worse (2.70 vs 2.40, different draws); it
  is not a performance patch.

### 5.3 Exact files/functions/lines summary

Track A (production):

| File | Function / line | Change | Est. LOC |
|---|---|---|---:|
| `crates/victory-gpu/src/resource.rs` | `fills` 1268; new `skip_mips` near it; `host_texture_as` 2053, hook before 2112; new `reserved_texture`, `skipped_mips`, `clamp_to_backed` after 2154; `HostTexture::new` 1947 | gate, reserved texture, private data, clamp helpers, accounting | 220-280 |
| `crates/victory-gpu/src/descriptor/host.rs` | `make` 2811; insert after `fits` at 2867, before `first_shown` at 2873 | call `clamp_to_backed` | 5-8 |
| `crates/victory-gpu/src/tiles.rs` | `wanted` 78 | expose/reuse the tier-2 query (optional refactor) | 10-20 |
| `crates/victory-gpu/src/texture.rs` | upload loop 705; detile loop 1168; alias 182 | optional copy/detile skip, alias guard | 20-35 |
| `crates/victory-gpu/src/list.rs` | `unlike` 839, copy/readback sites | optional skip-count guard | 10-20 |

Track B (production, for comparison): `resource.rs` 420-480, `texture.rs`
240-280, `list.rs` 160-210, `descriptor/host.rs` 80-100, plus audit of
`capture.rs`/`host.rs`/`tiles.rs` 50-150; total ~1,000-1,200 LOC.

## 6. Risks and mitigations

1. **Tiled-resources tier 2 (critical).** Tier 1 does not guarantee that reads
   of unmapped tiles return zero and writes are dropped. LNX checks
   `D3D12_FEATURE_D3D12_OPTIONS.TiledResourcesTier >= 2`; our `tiles.rs:78`
   already does the same for levels-on-demand. If tier < 2, disable the switch
   with a warning and use committed textures. Test on the actual RTX 4060
   Laptop; do not assume.
2. **Arrays, cubes, 3D, MSAA (high).** Gate `dimension == TEXTURE2D`,
   `depth_or_array_size == 1`, `sample_count <= 1`. Do not follow the cool-fox
   doc prose that says arrays are included; its code excludes them. A
   `Texture2DArray` SRV of a single-slice 2D resource is fine and is handled by
   `clamp_to_backed`; a real array/cube resource is not.
3. **One-mip and partial views / shader `Load` (high, visual).**
   `ResourceMinLODClamp` clamps sampling, not explicit `Load` or mip queries.
   XCL's GPU tests confirm: filtered sampling with the clamp is bit-identical to
   a fully backed texture with the same clamp, but an unclamped `Load` of mip 0
   reads zero. LNX leaves a view that only covers skipped levels alone ("reads
   zero"). Fix this in our port: if a view's range is entirely below `k`, shift
   `MostDetailedMip` to `k` and reduce `MipLevels`; add a one-mip/point-sampler
   GPU test. Otherwise UI/terrain textures with `MipLevels=1` can go black.
4. **Mip mismatch between aliases (high).** A placed view in another format can
   alias a texture's memory (`resource.rs:1214 alias_of`, `texture.rs:182
   alias`). If one side is skipped and the other is not, the top mips read zero
   or lose data. Add a `skipped_mips` comparison and refuse the alias/copy when
   the counts differ; fall back to title-memory upload. Track B's
   `dropped(placed) != dropped(source)` is the correct invariant; Track A must
   add the equivalent guard because its resource descs are otherwise identical.
5. **Copies/resolves/readback into skipped mips (medium-high).** Tier 2 drops
   writes and returns zeros for reads, so a copy from a skipped top mip to a
   non-skipped texture writes zeros. Audit `list.rs` copy/resolve/readback and
   `capture.rs`; log the first such copy. Do not silently accept a black
   texture.
6. **Budget accounting (high).** `GetResourceAllocationInfo` on a reserved
   resource may report the virtual size, not the mapped heap size. If so,
   `KINDS[1]` still counts the full texture, `room()` keeps refusing new
   copies, and the VRAM saving never changes residency behavior. Count
   `(total-start)*64KiB` explicitly (or store it in private data) and subtract
   it on drop. If aliases share an address, count each skipped page once
   (XCL's `skipped_pages` does this); otherwise the memory line over-reports.
7. **Coexistence with `VICTORY_LEVELS_ON_DEMAND` / tiles (high).** Both use
   reserved textures and `UpdateTileMappings`. Our `hosted` calls
   `host_texture_as(..., true)` for the tile path. Gate the skip hook with
   `!reserved` and add a global "one mechanism per run" check. A/B them
   separately.
8. **Heap-per-texture churn (medium).** LNX creates one heap per skipped
   texture. Thousands of streaming textures mean thousands of heap
   create/destroy calls and 64 KiB-granular waste. Measure before optimizing;
   if needed, reuse the `tiles.rs` pool or a shared heap with ranges.
9. **Cache invalidation (medium).** `STAGING`/`THROUGH` are keyed by resource
   address and are cleared by `texture::forget` on `Resource::drop`
   (`texture.rs:616`, `resource.rs:2360`), so address reuse is already handled.
   The shader/pipeline caches do not depend on texture mips; **do not edit
   `shader_cache.rs`** (its own bytes are part of the key). If a live toggle is
   ever added, clear the descriptor heap and staging maps; otherwise env is read
   once and a restart is the invalidation.
10. **Visual quality (high).** k=1 halves the largest side; k=2 quarters it;
    k=3 eighths it. Expect soft distant detail, signage, foliage and possibly UI
    atlases. Start at k=1, screenshot the route in section 8, and do not ship
    k=2/3 without a visual review. Consider excluding UI/text atlases by format
    or a size threshold if artifacts are unacceptable.
11. **Stability/TDR (medium).** The current tree already loses the device in 3D
    after ~2-3 minutes in some profiles (`docs/STABILITY-TDR.md`). A texture
    patch adds a new reserved-resource/heap lifetime path, which is exactly the
    kind of change that can turn a latent TDR into a reproducible one. Run the
    baseline first; do not attribute a baseline TDR to the patch.
12. **Licensing (medium).** LNX and cool-fox are GPL-3.0; our tree is GPL-3.0,
    so their code can be ported with attribution. XCL is GPL-2.0-only and is
    **not** compatible for copying into a GPL-3.0 tree; use it only as a
    behavioral reference/clean-room test description. The XCL PR is cited here
    for measurements and GPU-test semantics, not as code to copy.
13. **Coverage/savings (medium).** Only block-compressed 2D single-slice
    textures >= 512 texels participate. Uncompressed UI, arrays, cubes, MSAA,
    render targets and small textures keep all mips. Instrument the eligible
    fraction before promising a number.
14. **Reserved-resource debug-layer warnings (low).** The D3D12 debug layer may
    warn about unmapped tiles or state; release builds are the benchmark. Do not
    run the A/B with the debug layer unless diagnosing.

## 7. What we should expect

- **VRAM:** a real reduction in the texture host-copy pool, likely 1.5-4 GB on
  this title if enough eligible textures are resident. That can move the card
  from 95-107% of its 7,188 MB budget to below the 90% texture-queue line.
- **Residency behavior:** more textures admitted, fewer `the card has no room
  for more; they wait` events, and fewer long streaming stalls **if** the
  texture queue is the active bottleneck.
- **Frame rate:** approximately flat. Cool-fox measured 2.70 -> 2.40 fps with
  different draw counts; our E2b measured 7.5 -> 5.3 GB VRAM with the same 1 fps.
  Do not promise 30 fps, and do not call this a performance patch.
- **Image:** expected softness at distance; possible black/missing textures if
  one-mip views, aliases or `Load` paths are not guarded.
- **The one measured 7.70 fps result** is `RENDER_SCALE=0.5` (540p world
  upscaled), not texture residency. It is not comparable to 1080p.

If the goal is 30 fps, the evidence says the leverage is elsewhere: the staging
pass (`draw.rs` `heap_textures`), per-draw/submit cost, copy/copy-back, and
eventually a native renderer. Texture residency is a stability/quality-of-
residency valve, not the 30 fps lever.

## 8. A/B test plan (one change at a time)

Preconditions: game closed before each run; same build; same save/reference
scene; warm shader cache; same settings, resolution, render scale, console
profile, ambient and budget switches. Do not run the benchmark while PID 21992
is still the live test instance. Implement the patch in a separate worktree or
clone, never in the running `VItoriaBr-opt` tree.

Arms:

| Arm | Build | `VICTORY_TEXTURE_SKIP_MIPS` | `VICTORY_TEXTURE_DROP_MIPS` | Other changes |
|---|---|---:|---:|---|
| A0 baseline | patched build | 0 | 0 | none |
| A1 | same build | 1 | 0 | none |
| A2 (only if A1 passes) | same build | 2 | 0 | none |
| A3 (only if A2 passes) | same build | 3 | 0 | none |
| B1 (optional, separate build) | Track B build | 0 | 1 | none |

Keep `VICTORY_LEVELS_ON_DEMAND` fixed at **0** for all arms; Track A and the
tile path are mutually exclusive. If the baseline profile requires levels-on-
demand for stability, run a separate baseline with it on and do not compare
across that difference.

Run protocol:

1. Baseline A0 first: load the reference save, wait for the scene to settle
   (`draws >= 1000`, stable camera), then measure for 300 s. Take screenshots
   at t=0, 150 s and 300 s (same camera). Sample VRAM every 2 s.
2. Restart for A1. Same save, same camera, same warm cache. Measure 300 s and
   screenshot the same three points.
3. Restart for A2/A3 only if the previous arm passed. Never change k mid-run
   (env is read once).
4. If comparing Track B, use a separate build and arm B1; do not run skip and
   drop together.
5. Alternate A0/A1/A0/A1 if thermal drift is suspected; at least two runs per
   arm, three preferred.

Commands (operator, later):

```powershell
# VRAM sampler in a second terminal
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits -l 2

# The project harness, with the game already closed
python tools\bench\bench_run.py --runtime vitoriabr --variant skipmips-k1 `
  --cache warm --runs 3 --window 300 `
  --out benchmarks\runs\2026-11-26-texture-residency\skipmips-k1
```

Set the env in the launcher/terminal, for example:

```powershell
$env:VICTORY_TEXTURE_SKIP_MIPS = '1'
$env:VICTORY_LEVELS_ON_DEMAND = '0'
# keep every other baseline switch unchanged
```

Metrics and counters:

- `framelog`/host frame line: p50, p95, p99, 1% low, draws.
- `memory of textures: ... the card: ... MB in use of a budget of ... MB`
  (`copystat.rs:733`).
- `HEAP_TEXTURES_WAITING` (`draw.rs:415`, logged in the frame/queue census).
- `HEAP_TEXTURES_FULL` (`draw.rs:418`) and the one-time
  `textures picked by index: the card has no room for more; they wait`.
- New skip counters: skipped textures, skipped tiles, skipped MB, heap count.
- `nvidia-smi` peak/end; `crashes.log`, Windows Event Log, `temp\victory-*.crash.log`.
- Screenshots at the three points; compare with a visual checklist: distant
  signs, ground, foliage, UI text, character faces, sky, water, mirrors/RT
  reflections, alpha-tested effects.

Pass/fail gates:

- PASS only if: no device removal/TDR or new fatal crash in 300 s; no new
  black/missing texture in the screenshot set; VRAM end/peak lower by at least
  ~1 GB (or the skipped-MB counter shows the expected saving); the texture
  waiting/full counters improve; fps p50 is not worse by more than 5%.
- FAIL if: image holes, alias corruption, a reproducible new TDR, no measurable
  VRAM/accounting change, or `room()` still refuses textures because the
  accounting was not fixed.
- If baseline A0 already TDRs before 300 s, record the time and use a 120 s
  window for both arms; compare time-to-TDR rather than claiming 5-minute
  stability.

## 9. Recommendation

**Port the LNX `SKIP_MIPS` mechanism only, behind a default-off switch, as a
P3 residency experiment. Do not port cool-fox `DROP_MIPS`.**

Why:

1. **Risk/cost.** Track A is ~250-320 production LOC and keeps the resource
   shape; Track B is ~1,000-1,200 LOC and renumbers every subresource across
   code that cool-fox did not have to touch in our tree (capture, depth-twin
   planes, alias-through-buffer, tile path).
2. **Fit.** Our tree already has tier-2 reserved textures, 64 KiB tile mapping
   and `show_from`; Track A reuses that knowledge. Track B would require
   finishing cool-fox's own unwired staging optimization and adding
   `HostTexture.base`/`serial`/`holds` machinery.
3. **Benefit.** Track A gets the VRAM saving (reference: ~4 GB LNX, 3.7 GB XCL
   under a forced cap) without the frame-rate promise. Track B's measured fps
   is flat/worse and its upload-source win is not actually wired at HEAD.
4. **Our bottleneck.** E2b already showed 2.2 GB less VRAM with unchanged fps.
   The current frame is CPU/submit-bound; texture residency will not move 1-2
   fps to 30. If the goal is stability/visual holes, Track A is a cheap valve;
   if the goal is 30 fps, spend the time on the staging pass, per-draw/submit,
   copy/copy-back and the native path.

Conditions to merge Track A:

- Tier 2 confirmed on the target GPU; fallback tested.
- Explicit mapped-byte accounting; `room()` sees the saving.
- One-mip-view and alias/copy guards; `Load` zeros documented and reviewed.
- 300 s A/B shows >=1 GB saving, no visual holes, no new TDR, fps not worse
  >5%.
- Default off in `victory.example.toml`; README warns about softness and
  `Load`/mip-query zeros.

If those conditions are not met, keep the switch off and do not merge a
half-ported Track B.

## 10. Change impact ledger

| Dimension | Impact |
|---|---|
| Code | Track A: `resource.rs` (new helpers, hook, accounting), `descriptor/host.rs` (one call), optional `tiles.rs` tier helper, optional `texture.rs`/`list.rs` guards. No changes to `shader_cache.rs`, `pipeline`, `victory-shader`. |
| Data | No persisted game data or save format. New in-process counters only. Existing `STAGING`/`THROUGH` maps are keyed by resource address and already cleared on `Resource::drop` (`texture.rs:616`, `resource.rs:2360`). |
| Interfaces | New environment variable `VICTORY_TEXTURE_SKIP_MIPS` (0-3, default 0). No ABI/API change. D3D12 resource semantics change for eligible textures (reserved + unmapped top mips), which is observable to the title only through zero reads/dropped writes. |
| Tests | Unit tests for the gate matrix (format, dimension, array, MSAA, flags, mips, tier), view clamp (2D/2DArray, default view, one-mip, existing clamp), tile mapping count, and accounting. Optional GPU test for sampling/clamp; optional smoke run. |
| Documentation | This document; `victory.example.toml`; README warning; update the memory-line/counter docs if accepted. No game files. |
| Release | Default off; opt-in via env. Rollback is `VICTORY_TEXTURE_SKIP_MIPS=0` and a restart, or revert the commit. No data migration, no irreversible effect. |
| Monitoring | Log skipped textures/tiles/MB, heap count, `the card:` line, `HEAP_TEXTURES_WAITING/FULL`, crash/TDR. Compare before/after. |

## 11. Open questions / unverified

1. Does `GetResourceAllocationInfo` on a reserved resource report the mapped
   heap size or the full virtual size on this driver? **Unverified.** Plan for
   explicit mapped-byte accounting; do not rely on the query.
2. Does our NVIDIA driver map a packed mip tail correctly with LNX's one-region
   `UpdateTileMappings` from subresource `k`? LNX does it; test a 512x512 BC7
   10-mip texture and sample the clamped levels.
3. What does a one-mip `Texture2D` SRV with `ResourceMinLODClamp=k` do when the
   view's only mip is 0? LNX leaves it unclamped and reads zero; our port should
   shift it to `k` and test. **Unverified on this driver.**
4. Do the title's shaders use `Load`/mip queries on textures that would be
   skipped? Instrument the descriptor/resource use; XCL confirms `Load` reads
   zero and mip queries are not clamped.
5. What fraction of our resident textures is eligible (BC, 2D, single-slice,
   >=512, no RT/DS/UAV)? Instrument first; the 1.5-4 GB estimate is from other
   trees.
6. Does the current launcher set `VICTORY_LEVELS_ON_DEMAND=1` on this machine?
   If yes, Track A must be gated off or the two must be reconciled; do not
   enable both.
7. Does the current 3D TDR reproduce on A0 within 5 minutes? If yes, the
   stability gate must be time-to-TDR, not "no TDR in 5 minutes."
8. Cool-fox docs vs code: arrays are claimed but excluded; `staging_layout` is
   written but not wired; `translate.rs` change is unrelated to mip mapping.
   Treat the code as authoritative.
9. XCL is GPL-2.0-only; its code must not be copied into this GPL-3.0 tree.
   Its PR is a behavioral/measurement reference only.

## 12. References

Local source (read-only):

- `D:\git\LNX-victory` commit `c04e615`: `crates/victory-gpu/src/resource.rs`
  (skip/reserved/clamp functions at 2306-2595; hook at 2218),
  `crates/victory-gpu/src/descriptor/host.rs` (call at 2978).
- `D:\git\cool-fox-12gb` (clone of `miaohaixiang1-netizen/cool-fox-12gb`, HEAD
  `67298e8`; feature commit `fcb4f71`): `resource.rs` 104/1272/1513-1596/
  1620/2501-2522; `texture.rs` 35/189/673/1507/1888; `list.rs`
  888/916/993/1041/1269/1345; `descriptor/host.rs` 4242/4388-4400.
- `D:\git\VItoriaBr-opt` `d93d263` plus uncommitted `descriptor/host.rs` and
  `draw.rs`: line map in section 2.
- `D:\git\gta6-30fps\docs\EXPERIMENTS-2026-11-25.md`,
  `docs/PERF-DIAGNOSIS-2026-11-25.md`, `docs/MEMORY-STREAMING.md`,
  `docs/STABILITY-TDR.md`, `docs/BENCHMARK-PROTOCOL.md`.

Web:

- cool-fox README and `docs/HYBRID-8GB.md`:
  <https://github.com/miaohaixiang1-netizen/cool-fox-12gb>
  and <https://github.com/miaohaixiang1-netizen/cool-fox-12gb/blob/main/docs/HYBRID-8GB.md>
- LNX-victory: <https://github.com/Linox-IDK/LNX-victory>
- XCL PR #2385 ("D3D12.X: sampled textures go without their top mips while
  video memory fills up"): <https://gf.openbay.app/greyfinch/xcl/issues/2375>
  (migrated from `ivall/xcl` PR 2385). Key evidence: GPU clamp/filter tests,
  12 GB 3060 12,606 -> 10,658 MB, 2,685 textures / 4,765 MB tiles omitted;
  `Load`/mip queries read zero; 8 GB untested.
- Microsoft D3D12 `ResourceMinLODClamp`:
  <https://learn.microsoft.com/en-us/windows/win32/api/d3d12/ns-d3d12-d3d12-tex2d-srv>
- Microsoft D3D12 `GetResourceAllocationInfo`:
  <https://learn.microsoft.com/en-us/windows/win32/api/d3d12/nf-d3d12-id3d12device-getresourceallocationinfo(uint_uint_constd3d12_resource_desc)>
- Microsoft D3D12 reserved resources / tiled resources:
  <https://learn.microsoft.com/en-us/windows/win32/direct3d12/uploading-resources>

Method note: Firecrawl MCP was not registered in this session; `webfetch` and
`websearch` were used as the fallback. No binary analysis (REA) was required.
