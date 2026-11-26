# SCENE INTEL — 2026-11-26

**Public 8 GB NVIDIA options, CGBJ provenance, and fixes worth porting**

| | |
|---|---|
| Target | RTX 4060 Laptop 8 GB VRAM / 16 GB RAM, Windows 11 |
| As-of | 2026-11-26T18:24Z |
| PortWatch snapshot | live fetch 2026-11-26T16:18:31Z (task cited 10:23:53Z) |
| Tracker SHA-256 | `AE51F7D2111496921151835195F40C30E695779690C9A778858AF83AEDA3351A` |
| Method | PortWatch tracker JSON + authenticated GitHub REST API (4,973/5,000 core calls left) + project READMEs, commits, PRs, trees, workflows + media cross-check |
| Firecrawl | **Not registered in this session.** `search("firecrawl")` returned 0 tools. Fallback: `websearch` + `webfetch` (Google/Bing News, GitHub raw/API). |
| Safety | No game files read, no game process touched, no binaries downloaded or executed. |

**Evidence labels:** `[F]` sourced fact · `[SR]` self-reported by project owner · `[I]` inference · `[R]` recommendation.
**Confidence:** **A** = measured protocol + exact hardware · **B** = self-reported with per-run numbers, hardware, settings · **C** = headline number, incomplete method · **D** = claim only.

---

## 1. TL;DR

- **The best public 8 GB NVIDIA result is 8–10 fps at 1080p**, on `soldsawn/victory-nvidia-8gb` with an RTX 4060 Laptop 8 GB, **48 GB RAM**, `--console series-x`, `VICTORY_TEXTURE_DROP_MIPS=2`, `VICTORY_COPY_PLAIN=1`, thin LTO. VRAM 6.6/7.0 GB. `[SR]` `[B]`
- **CGBJ's 25 fps is not an 8 GB result.** It is a private build on a **16 GB VRAM** NVIDIA GPU, self-reported, never independently reproduced. Its original repo is **404**. The closest public code from that tree measures **2.40–2.70 fps at 1080p on an RTX 4060 Laptop 8 GB**. `[F]` `[SR]` `[A for the 2.4–2.7 measurement]`
- **Residency is the gate; submit is the ceiling.** The soldsawn run fits the world in 6.6–7.0 GB only because 1080p + two dropped mip levels free ~1.4–2.3 GB. Without that, the same class of card sits at 7.4–7.6/8.0 GB and drops to ~6 fps. Once it fits, the GPU sits at 50–58 % and the submit/copy thread limits the frame. `[SR]` `[I]`
- **30 fps on 8 GB via the translation layer is not demonstrated anywhere.** Best public 8 GB number is ~10 fps; the submit thread, not the GPU, is the wall (30–58 % GPU busy in the best runs). `[SR]` `[I]`
- **Most actionable new material:** CGBJ's submission ports (Port 5 zero-copy CBV, Port 1 in-place 32-bit heap, descriptor-record deferral), the 8 GB residency trio (1080p + `DROP_MIPS=2` + `HEAP_WORKER`), and four shader-correctness commits. Details in §4. `[F]`
- **Do not chase the 25 fps number.** It is a 16 GB-VRAM, private, internally inconsistent spec sheet (see §3.3). `[R]`

---

## 2. Ranked table — public 8 GB NVIDIA options

Ranked by **usefulness to our 4060/16 GB tree** (evidence quality × applicability × code availability), not raw fps. Cross-project fps is not directly comparable: different scenes, profiles, drivers and RAM.

| # | Project / head | Measured fps on 8 GB NVIDIA | Hardware and settings | Code status | Provenance / confidence |
|---|---|---|---|---|---|
| **1** | [`soldsawn/victory-nvidia-8gb`](https://github.com/soldsawn/victory-nvidia-8gb) `c09a44e9` (2026-11-25 21:55Z) | **8–10 fps** (103.9–129.1 ms), 3,005–5,027 draws, **6.6/7.0 GB VRAM**, GPU 50–58 %, CPU 45–50 % | RTX 4060 Laptop 8 GB, i5-12450H, **48 GB RAM**, Win 11 HAGS. Series X + `VICTORY_RESOLUTION=1920x1080` + `VICTORY_TEXTURE_DROP_MIPS=2` + `VICTORY_COPY_PLAIN=1` + thin LTO. 4K ladder: 6 fps, 153–172 ms, 7.4–7.6/8.0 GB. | GPL-3.0. Public source, **true GitHub fork** of `fxceless/victory-fork`. 62★ / 11 forks, 5 open issues, **no releases**. | **B**. Concrete per-run numbers and settings; self-reported; **48 GB RAM is part of the result** — not reproduced on 16 GB. |
| **2** | [`ad3lre/victory-nvidia-8gb`](https://github.com/ad3lre/victory-nvidia-8gb) `f2553c25` (2026-11-26 17:17Z) | **8.7 fps / ~115 ms** (own hardware note); GTX 1660 6 GB: 5–6 fps at 1080p + `DropMips=2` | RTX 4060 Laptop 8 GB + i7-14700KF (per `docs/HARDWARE-GTX1660.md`); settings inherited from soldsawn | GPL-3.0. Fork of `soldsawn/victory-nvidia-8gb`, 5★ / 5 forks. **Telemetry ON by default** to `rxnd.de` (see §6). | **B−**. Number is a cross-reference, not a full protocol. Same lineage as #1. |
| **3** | [`Linox-IDK/LNX-victory`](https://github.com/Linox-IDK/LNX-victory) `c04e6159` (2026-11-25 22:49Z) | **3.3–4.6 fps** at 1080p Series X (2.5 avg earlier); **7–8 fps** Series S + host FSR | RTX 5060 Ti **8 GB**, Ryzen 5 9600X, 32 GB. `TEXTURE_SKIP_MIPS=1`, `TEXTURE_NO_WAIT=1`, `CARD_FETCH_INFLIGHT=0`, `LDS_REGION_RACE=1` | GPL-3.0. Public, fork of `fxceless/victory-fork`. **4★**, 0 forks, no releases, 0 issues. | **B−**. Honest per-stage table; tiny repo, no independent repro, 5060 Ti is faster than 4060 Laptop. |
| **4** | [`miaohaixiang1-netizen/cool-fox-12gb`](https://github.com/miaohaixiang1-netizen/cool-fox-12gb) `67298e81` (2026-11-26 11:45Z) | **2.70 fps** (`DROP_MIPS=0`) · **2.40 fps** (`DROP_MIPS=1`), 370/417 ms, draws 4,470/6,050 | **Same laptop class:** RTX 4060 Laptop 8 GB, i9-14900HX, 31.6 GB DDR5, Win 11 26300. **1080p Series S.** The 7.70 fps row is **540p internal upscaled**, not 1080p. | GPL-3.0. Public, **3★ / 4 forks**. Direct fork of CGBJ `f4b48ad` + 8 GB patch. | **A− for the measurement** (logged A/B, exact hardware). **C for base lineage** (mirror, see §3). |
| **5** | [`DoubleGhosty/cool_fox`](https://github.com/DoubleGhosty/cool_fox) `3277b15` (2026-11-26 17:59Z) | **No formal 8 GB measurement.** Launcher comment: “the frame rate held at 5–7 fps here” — hardware not stated. Ships a 4 GB profile. | Unknown NVIDIA card in launcher comment; 4 GB VRAM profile exists | GPL-3.0. Public, but **not a GitHub fork** of the original. **575★ / 359 forks** in ~9.5 h (fork:star 0.62, abnormally high). No releases. | **D for fps**, **A for activity**. Most active CGBJ continuation; popularity metrics look inflated. |
| **6** | [`GiovannaSGuerrera/Victory-RTX2080`](https://github.com/GiovannaSGuerrera/Victory-RTX2080) `ede4cbb6` (2026-11-26 09:32Z) | **0.3–2.5 fps** at **1280×720** Series S; crashes; black surfaces | RTX 2080 **8 GB**, Ryzen 5 5500, 32 GB, driver 621.14 | GPL-3.0. Public, 2★ / 1 fork, no releases. Honest “not a stable conversion” README. | **B−** for honesty, **D** for usefulness. |
| **7** | [`Zettrox/ztrx`](https://github.com/Zettrox/ztrx) | **1–3 fps** on RTX 3050 **8 GB** | RTX 3050 8 GB; played to “Gone Fishing” | **Repo and account both 404** as of 2026-11-26. Not recoverable. | **Historical only. Not usable.** |

**Omitted from the ranking:** `Dolberthi/neptune-dolberth-nvidia-8gb` targets this exact GPU (RTX 4060 8 GB) but publishes **no fps number**, only switches and a diagnostics harness; `kitotake/cool_fox` is a stale sibling with a dead release link; `codec-d/cool_fox` is 404; `trustno1-coder/VIctory-NVIDIA` is **12 GB**. None can be ranked on measured 8 GB fps.

### 2.1 Not 8 GB, but the reference points that matter

| Project | fps / hardware | Why it matters |
|---|---|---|
| [`fxceless/victory-fork`](https://github.com/fxceless/victory-fork) `52ac4ec0` | **8.2–8.6 fps** at first boat mission, 3,000–5,000 draws, **RTX 4070 12 GB**, with `VICTORY_HEAP_WORKER=1`; 6.2–6.7 without it | Proves the ~8–10 fps band is reachable on the same code family **when VRAM is not the limit**. Our 8 GB needs `DROP_MIPS` to get there. `[SR]` |
| [`trustno1-coder/VIctory-NVIDIA`](https://github.com/trustno1-coder/VIctory-NVIDIA) `85a529b6` | **19–22 fps** on RTX 5070 **12 GB**, Series S + half render scale (540p internal); 14.9 fps on 5060 Ti 16 GB (PCIe x4) | Best public NVIDIA path. Shows half-scale + Series S + ray-walk skip is the big lever — and that it costs picture quality. `[SR]` |
| [`Belobug/VIctory-Belobug-AMD`](https://github.com/Belobug/VIctory-Belobug-AMD) | **22 fps** avg, RX 9070 XT **16 GB**, ~12 GB VRAM, 30 GB RAM | Current tracker #1. Not applicable to 8 GB; VRAM alone rules it out. `[SR]` `[F]` |
| [`avatarmanz/VIctory-7900XTX`](https://github.com/avatarmanz/VIctory-7900XTX) | **16 fps** avg, RX 7900 XTX **24 GB**, 40–46 GB private memory | Threading/submission work is the upstream of CGBJ and trustno1. `[SR]` |
| [`DexNom/VIctory`](https://github.com/DexNom/VIctory) | 3–4 fps, RX 7900 XTX; best-rated picture 0.85 | Ray-tracing and texture-residency reference; NVIDIA path explicitly untested. `[SR]` |
| [`xcl-dev/xcl`](https://github.com/xcl-dev/xcl) | Unmerged NVIDIA branch ~5 fps, world incomplete; menus 30 fps | Shader translation reference (26,698 programs). Not a playable option. `[SR]` |
| [`Marvisak/VIctory`](https://github.com/Marvisak/VIctory) | ~1 fps, RX 6700 XT | Base layer; not competitive. `[SR]` |
| [`stellarr-studio/kelvaroq`](https://github.com/stellarr-studio/kelvaroq) | ~10 fps, **RTX 5080 4K**; 7.6 fps mean heavy frame; external 4090 1440p 10 fps | No 8 GB measurement. Ships a 31.86 MB prebuilt ZIP. Claims “#1 of 44” — stale, tracker has CGBJ #1. `[SR]` |

---

## 3. CGBJ verdict

### 3.1 The claim

PortWatch's CGBJ entry (`verification: portwatch`, assessed 2026-11-26) states verbatim:

> “It averages 25 fps with 8 GB system RAM and 16 GB VRAM.”
> Blockers: “Gameplay does not sustain 30 fps; 25 fps is the reported average”; “Code is private, so nobody outside the group can test or reproduce it.”

PortWatch's score for CGBJ is **89.6 %** (history, 2026-11-26) after a rendering re-rate that dropped every non-DexNom build above 0.7 to 0.7. The `DoubleGhosty/cool_fox` README badge says **91.5 %**; media repeated 91.5 %. That badge is **stale/inflated by 1.9 points** relative to the live tracker. `[F]`

Media cross-check: `[F]`
- TechRadar (2026-11-26): “stable 25 to 30fps… 8GB of system RAM and an Nvidia GPU that has 16GB of video memory.”
- Dany892 on X (CGBJ-adjacent): “stable 20 FPS in gameplay… 30 FPS in cutscenes… uses only 10 GB of system ram… stable on 16 GB of VRAM.”
- `awful` on X: “Around 25 FPS on NVIDIA GPUs… Tested with just 8GB RAM and 16GB VRAM… Results also need independent testing.”
- GameRant/OpenCritic: “up to 24 FPS… 10 GB of system RAM… 16 GB of VRAM.”

### 3.2 Repository status and mirror chain

The original repository `codec-d/cool_fox` is **HTTP 404** as of 2026-11-26T18:0xZ. The **account `codec-d` still exists** (GitHub user id 58233486, created 2019-11-26, 3 public repos, 106 followers). The GitHub DMCA directory `2026/11` has 164 files; its newest entries are dated **2026-11-24**, and the only GTA VI-related notice is `2026-11-24-take-two.md` (Leonida). **No notice names `codec-d/cool_fox` or CGBJ.** So this was an owner-side deletion/privatisation, not a published DMCA takedown. `[F]`

Mirrors appeared within 25 minutes of each other:

| Repo | Created | Head | Contains `f4b48ad`? | Contains other heads? | Stars/forks | Notes |
|---|---|---|---|---|---|---|
| `codec-d/cool_fox` (original) | — | — | — | — | — | **404.** Account alive. |
| [`kitotake/cool_fox`](https://github.com/kitotake/cool_fox) | 2026-11-26T08:37:20Z | `7329cbd1b2ff` (11:42Z) | Yes | No (`3277b15` absent) | 1★ / 3 | Keeps the **original README**; its download link points at `codec-d/cool_fox/releases/latest` → **dead**. |
| [`DoubleGhosty/cool_fox`](https://github.com/DoubleGhosty/cool_fox) | 2026-11-26T08:48:31Z | `3277b1565118` (17:59Z) | Yes | No (`7329cbd` absent) | 575★ / 359 | Rewritten README, “community continuation”, most commits. All continuation commits carry 17:59Z committer timestamps (consistent with a rebase/repush). |
| [`miaohaixiang1-netizen/cool-fox-12gb`](https://github.com/miaohaixiang1-netizen/cool-fox-12gb) | 2026-11-26T09:01:51Z | `67298e81824e` (11:45Z) | Yes | No | 3★ / 4 | 8 GB patch on `f4b48ad`. Repo name says 12gb; content is 8 GB. |

**Provenance finding:** none of the three mirrors is a GitHub fork of the original (`fork=false`), so GitHub's fork graph cannot attest lineage. The only cryptographic link is the shared commit **`f4b48ad766`** (“Publish the pareto-residency Windows build and portable launcher”, 2026-11-26T06:33:14Z). `kitotake` and `DoubleGhosty` do **not** contain each other's heads — they are **sibling branches from `f4b48ad`**, not a linear chain. Therefore there is **no canonical CGBJ tree** to audit. `[F]` `[I]`

### 3.3 Decomposing the 25 fps claim

| Claim component | Evidence | Assessment |
|---|---|---|
| 25 fps average | PortWatch entry, owner-reported; media 24–30; Dany says 20 stable / 30 cutscenes | **Contradictory even within the friendly sources.** 25 is a peak-ish number, not a stable average. `[SR]` `[D]` |
| 16 GB VRAM | Consistent across PortWatch, TechRadar, Dany, GameRant | **This is not an 8 GB GPU.** Even if true, it says nothing about a 4060 Laptop 8 GB. `[F]` |
| 8 GB system RAM | PortWatch and TechRadar; Dany says 10 GB; GameRant says 10 GB; observed commits elsewhere are 10.5–15.5 GB (Kelvaroq), 30 GB (Belobug), 40–46 GB (AvatarManz) | **Internally incoherent.** 8 GB system RAM is below what the title commits in every measured run. Treat the spec sheet as unreliable. `[F]` `[I]` |
| Reduced render scale | The 8 GB fork author writes that CGBJ's 25 fps was “also at reduced render resolution”; TechRadar/DSOGaming do not mention it | **Third-party inference, not a CGBJ statement.** Plausible given every other NVIDIA path uses half-scale, but unconfirmed. `[I]` |
| Independent reproduction | None. PortWatch “checked with the group”; no public code, no log, no save, no capture with overlay | **Not reproducible.** `[F]` |

### 3.4 The same-laptop measurement that settles it

The closest public code to CGBJ is `miaohaixiang1-netizen/cool-fox-12gb`: base `f4b48ad` + an 8 GB residency patch. On **RTX 4060 Laptop 8 GB / i9-14900HX / 31.6 GB / Win 11 26300**, Series S, **1920×1080 output**, median of world frames with draws > 1,000: `[SR]` `[A−]`

| Build | Scene | Median fps | Frame time | Draws | Indexed texture upload |
|---|---|---:|---:|---:|---:|
| Upstream `cool_fox`, `DROP_MIPS=0` | in world | **2.70** | 370 ms | ~4,470 | 0.31 MB/texture |
| This branch, `DROP_MIPS=1` | in world (heavier) | **2.40** | 417 ms | ~6,050 | **0.11 MB/texture** |
| This branch, diag + D3D12 debug layer | in world | 2.40 | 417 ms | ~4,820 | 0.11 MB/texture |
| This branch | menus / loading | 30.0 | 33 ms | 7–10 | — |
| Earlier NVIDIA branch, **`RENDER_SCALE=0.5`** | in world | **7.70** | 130 ms | ~4,920 | — |

The author's own reading, which we agree with: the 7.70 fps row is **540p internal upscaled to 1080p**, “not that the code is faster”; at true 1080p this machine is **2–3 fps**. The `DROP_MIPS=1` patch cut texture bytes per upload by ~2.8× but **did not raise fps** — draws differed 35 % between runs, so it is not a clean A/B. The author explicitly says: “don't read it as a performance patch.” `[SR]` `[I]`

### 3.5 Verdict

> **CGBJ is not a usable 8 GB NVIDIA option.** Its 25 fps figure is a **16 GB-VRAM, private, owner-reported, never-reproduced** number, attached to an **internally inconsistent 8 GB system-RAM spec**. The original repo is **404**; the three surviving mirrors are **siblings from `f4b48ad`**, not a verifiable chain; no official build exists. The closest public code from that tree measures **2.40–2.70 fps at 1080p on an RTX 4060 Laptop 8 GB** — roughly **10× below the claim**. `[F]` `[SR]` `[I]`
>
> **Do not budget against 25 fps. Do not treat CGBJ as evidence that 8 GB VRAM can reach 25 fps. Do use its submission and residency commits as code to port (§4).** `[R]`

---

## 4. New actionable fixes since our last review

Our last review is anchored at **2026-11-26 07:48 local / 06:48Z** (`docs/EXPERIMENTS-2026-11-25.md` mtime). “Landed after” means commit/push time after that. “Not yet in our tree” covers earlier commits we had not folded in.

### 4.1 Landed after the morning review

| Area | Change | Exact source | Why it matters for 4060 / 8 GB | Status |
|---|---|---|---|---|
| **Texture residency** | `VICTORY_TEXTURE_DROP_MIPS=N` (0–4) drops the N largest host mip levels; views shift automatically | [`fcb4f71bbb`](https://github.com/miaohaixiang1-netizen/cool-fox-12gb/commit/fcb4f71bbb) · upstream PR [`fxceless/victory-fork#610`](https://github.com/fxceless/victory-fork/pull/610) (**open, not merged**) | 0.31 → 0.11 MB/texture; **no fps gain by itself** on 8 GB, but it is what lets soldsawn fit 6.6/7.0 GB at 8–10 fps. Treat as a **residency enabler**, not a speed switch. | Patch exists; A/B incomplete |
| **Shader / colour** | `VICTORY_NAN_SCRUB=1` replaces NaN/±∞ in colour and f32 image stores with 0 | [`db556df3a8`](https://github.com/miaohaixiang1-netizen/cool-fox-12gb/commit/db556df3a8) | Fixes black blotches on NVIDIA faces/sky; changes console behaviour, so **off by default**. Add to shader-cache key (already done). | Off by default |
| **Shader** | Experimental loose-LDS path for one digest (`50cf2832…`) | [`aed9bdc0e4`](https://github.com/miaohaixiang1-netizen/cool-fox-12gb/commit/aed9bdc0e4) | One stubborn program; may see stale LDS values. **Do not enable globally.** | Off by default |
| **Shader** | Leave the unused LOD slot of an array-texture query undefined (DXIL validator error on retail shaders) | [`caec503049`](https://github.com/DoubleGhosty/cool_fox/commit/caec503049) · CGBJ PR #2 | Removes a class of pipeline/validator refusals. Low risk. | In `DoubleGhosty` |
| **Shader** | Recover the voxel-visibility shader when the wave64 mask is restored from scalar copies | [`cbb00ee870`](https://github.com/DoubleGhosty/cool_fox/commit/cbb00ee870) | Foliage / volumetric visibility programs compile on 32-lane NVIDIA. | In `DoubleGhosty` |
| **Shader / pipeline** | One back edge per loop header; indirect clamps built with Wine's HLSL compiler; 256 MiB pipeline-worker stack; root signatures built in-tree | [`1febfd8f97`](https://github.com/DoubleGhosty/cool_fox/commit/1febfd8f97) · [`df94eb4957`](https://github.com/DoubleGhosty/cool_fox/commit/df94eb4957) · [`8b6c0b82e7`](https://github.com/DoubleGhosty/cool_fox/commit/8b6c0b82e7) · [`5398ce918b`](https://github.com/DoubleGhosty/cool_fox/commit/5398ce918b) | Robustness under vkd3d/Proton and fewer pipeline refusals. Mostly Linux/Wine value; Windows value is the stack + root signatures. | In `DoubleGhosty` |
| **Submission** | **Renderer Port 5, zero-copy CBV** (`VICTORY_PORT_CBV=1`): constant buffers read as raw bytes in place, ~**22,000 buffer copies/frame** eliminated | [`c7fff5410a`](https://github.com/DoubleGhosty/cool_fox/commit/c7fff5410a) | Directly attacks our submit/copy wall. Biggest single CPU-side candidate. | Off by default, enabled in launchers at `3277b156` |
| **Submission** | **Renderer Port 1**: title's 32-bit graphics heap used in place (`VICTORY_PORT_CONSTANTS=1`); pages get section slices in address order | [`c496640276`](https://github.com/DoubleGhosty/cool_fox/commit/c496640276) · [`5e0c9ab01e`](https://github.com/DoubleGhosty/cool_fox/commit/5e0c9ab01e) | Removes another copy path for constants. A/B separately from Port 5. | Off by default |
| **Submission / frame pacing** | `VICTORY_FRAME_INTERVAL_MS=16.667` (60) or `8.333` (120), title's own 30 fps setting patched to match; simulation clock stays 1.00× | [`098a7d0474`](https://github.com/DoubleGhosty/cool_fox/commit/098a7d0474) | Useful only after we are above 30 fps; do **not** enable while debugging 2–10 fps. | Off by default |
| **Output** | `VICTORY_OUTPUT=1920x1080\|2560x1440`, `VICTORY_RENDER_SCALE=0.667..1.0`, 4K backbuffer pool check bypassed | [`a4d9895ee6`](https://github.com/DoubleGhosty/cool_fox/commit/a4d9895ee6) · [`28238acab6`](https://github.com/DoubleGhosty/cool_fox/commit/28238acab6) | Lets us test 1080p / 720p without patching the exe. | Off by default |
| **8 GB settings** | Launchers enable Port 1 + Port 5 by default; **Series X**, not Series S, because Series S drops head/skin meshes on 8 GB (faces render as eyes + teeth) | [`3277b15651`](https://github.com/DoubleGhosty/cool_fox/commit/3277b15651) · [`Play-VIctory.cmd`](https://github.com/DoubleGhosty/cool_fox/blob/3277b1565118/Play-VIctory.cmd) | **Correctness fix, not just perf.** Our tree's Series S experiments should re-check faces/skin. | In `DoubleGhosty` |
| **VRAM** | Submit-thread profiler, lock-free write-watch answers, clamps kept over direct draws | [`658d561516`](https://github.com/Dolberthi/neptune-dolberth-nvidia-8gb/commit/658d561516) | Better attribution of the submit thread; no fps claim. | In Neptune |
| **VRAM** | Eliminate 8 GB buffer/texture eviction thrashing; widen texture queue to 92 % and DirectStorage staging to 64 MB | [`6937446cd1`](https://github.com/Dolberthi/neptune-dolberth-nvidia-8gb/commit/6937446cd1) · [`1bdc77d000`](https://github.com/Dolberthi/neptune-dolberth-nvidia-8gb/commit/1bdc77d000) | Directly targets the “card has no room; they wait” state. **Unverified**; no published fps. | In Neptune |

### 4.2 Verified in this pass, but committed before the morning review

| Area | Change | Exact source | Evidence |
|---|---|---|---|
| **8 GB recipe** | 1080p + `DROP_MIPS=2` + `COPY_PLAIN=1` + thin LTO → **8–10 fps**, 6.6/7.0 GB VRAM on RTX 4060 Laptop | [`soldsawn/victory-nvidia-8gb` README](https://github.com/soldsawn/victory-nvidia-8gb) `c09a44e9` | Concrete hardware + per-run ms + draws + VRAM. The single most actionable measurement in this brief. |
| **Texture residency** | `VICTORY_TEXTURE_MAX_DIM=1024` caps top mips, ~1.5–2 GB VRAM, prevents `0x887A0006`; `VICTORY_RAM_TRIM_MB`, 2-tier placed-resource slabs | [`Dolberthi/neptune`](https://github.com/Dolberthi/neptune-dolberth-nvidia-8gb) `cd24555e3b` | README claims; no fps table. Use as an alternative to `DROP_MIPS`, A/B separately. |
| **Texture residency** | `VICTORY_TEXTURE_SKIP_MIPS=1`: big BC textures become tiled resources with memory only from level 2 down (~4× less each); ~4 GB saved | [`Linox-IDK/LNX-victory`](https://github.com/Linox-IDK/LNX-victory) `c04e6159` | 8 GB card reaches 3.3–4.6 fps at 1080p; no “textures missing” reports. |
| **Submission** | Descriptor records of draw tables deferred to the draws: **280 ms → ~124 ms**; preparing thread **48 ms** is the wall; 18 refresh steps + 7 card steps per frame | [`DoubleGhosty/cool_fox/docs/findings.md`](https://github.com/DoubleGhosty/cool_fox/blob/f4b48ad766/docs/findings.md) | RX 7900 XTX measurements; the mechanism is card-agnostic. |
| **Submission** | `VICTORY_HEAP_WORKER=1` (async heap-indexed texture upload) moves 6.2–6.7 → **8.2–8.6 fps** at first boat mission | [`fxceless/victory-fork#1007`](https://github.com/fxceless/victory-fork/pull/1007) (**open**) | RTX 4070 12 GB, 3,000–5,000 draws. |
| **Shader** | 245 / 26,599 shaders fail (was 337); 2–4 compute failures in a run; **no pipeline refused**; `VICTORY_LDS_REGION_RACE=1` gets shadow/RT-builder pipelines on NVIDIA | [`LNX-victory` README](https://github.com/Linox-IDK/LNX-victory/blob/c04e6159/README.md) | Concrete counts; self-reported. |
| **Shader / RT** | Native BVH (`VICTORY_NATIVE_BVH=1`), inline ray queries (`AllocateRayQuery`, `TraceRayInline`), bind cache | [`012fbf0526`](https://github.com/Linox-IDK/LNX-victory/commit/012fbf0526) · [`44280ad213`](https://github.com/Linox-IDK/LNX-victory/commit/44280ad213) · [`4dc1ac71a6`](https://github.com/Linox-IDK/LNX-victory/commit/4dc1ac71a6) | RT builder runs but the title crashes ~1 min later; **keep RT off** until stable. |
| **Submission research** | Kelvaroq: each GPU descriptor translated once at write, per-submission work **<1 ms**, 121 M rows zero errors; memory copied/frame 100 MB → **<8 MB**; 18 s → 60 ms per heavy frame | [`stellarr-studio/kelvaroq`](https://github.com/stellarr-studio/kelvaroq) `e062a82e` | RTX 5080, self-reported. **Watch item, not a merge candidate** — different memory architecture. |

### 4.3 The 8 GB settings recipe implied by the evidence

```text
console         = series-x            # CGBJ launcher: series-s drops head/skin on 8 GB
resolution      = 1920x1080           # frees ~1.4-2.3 GB vs 4K ladder
texture         = DROP_MIPS=2         # soldsawn: 8-10 fps, 6.6/7.0 GB
copy            = COPY_PLAIN=1        # -20 ms copy-back (PR #1032)
upload          = HEAP_WORKER=1       # 6.2-6.7 -> 8.2-8.6 fps on 12 GB
cache           = WARM_CACHE=1 + pre-translate; pipeline workers normal priority
submit          = JOIN_COPIES=1, CARD_STEPS=2, RELAY=2, INDIRECT_WINDOW=1
avoid           = THIN=1, JOIN_PARTS=8 on NVIDIA  # head skin missing / video repeats
avoid           = CARD_FETCH_INFLIGHT=1           # GPU 100 -> 600 ms
budget          = CARD_BUFFERS_MB 512-1024, TEXTURE_BUDGET_MB 5120 for 8 GB
```

`DROP_MIPS=2` is not free: distant textures blur, and array/MSAA textures are excluded. It is a **memory enabler**, not a speed switch (§3.4). `[SR]` `[I]`

---

## 5. Why the 8 GB ceiling is where it is

| Observation | Number | Source |
|---|---|---|
| Best 8 GB result | 8–10 fps, 103.9–129.1 ms | soldsawn, RTX 4060 Laptop, 48 GB RAM |
| GPU busy at that result | 50–58 % | soldsawn |
| CPU busy at that result | 45–50 % | soldsawn |
| Submit-thread cost in the same code family | 48 ms/frame; 70 ms in fxceless | cool_fox findings; fxceless |
| GPU work in the same code family | ~5–14 ms/frame (4.6–5.4 ms at 540p; ~9 ms at 1080p) | trustno1; fxceless |
| Texture slots waiting when VRAM is full | 4,009–8,393 (GTX 1660 6 GB); 12,000–14,000 (8 GB laptop) | ad3lre; cool-fox-12gb |
| VRAM at 8–10 fps | 6.6 / 7.0 GB | soldsawn |
| VRAM without 1080p + drop mips | 7.4–7.6 / 8.0 GB, ~6 fps | soldsawn |
| Draws at 8–10 fps | 3,005–5,027 | soldsawn |

**Inference:** on 8 GB the card is **not** the frame-rate limiter at 1080p + `DROP_MIPS=2`; the **submit/copy thread** is. That is consistent with our own E2b result: freeing 2.2 GB of VRAM did not change fps. The 8 GB problem is therefore **two problems**: (a) fit the world without eviction thrash, then (b) cut per-frame submit/copy work. CGBJ's 25 fps likely comes from solving (b) on a 16 GB card where (a) never binds. `[I]` `[R]`

---

## 6. Security and provenance review

### 6.1 Findings that change how we use the code

| Artifact | Finding | Risk | Action |
|---|---|---|---|
| `ad3lre/victory-nvidia-8gb` | **Telemetry ON by default**: one report per `victory run`, sent to `https://rxnd.de/vi/v1`; includes GPU/driver/VRAM, CPU, RAM, display, **BLAKE3 hash of the title executable**, 1-second fps timeline, CPU/GPU load/temps, logs, **screenshots**; a **sibling recorder process** survives a TDR or hard kill | Privacy + third-party endpoint + data exfiltration surface | Set `VICTORY_TELEMETRY=0`, `--no-telemetry`, or `[telemetry] enabled=false`. Do not run on a desktop with sensitive windows. Prefer soldsawn's tree. |
| `ad3lre/victory-nvidia-8gb` | `apps/victory/build.rs` **downloads** `Microsoft.Direct3D.D3D12 1.620.2` from NuGet at build time and installs `D3D12Core.dll` beside the exe; SHA-256 verified | Build-time supply chain; network dependency | Vendor the NuGet package / DLL, verify hash, use `VICTORY_SKIP_AGILITY_FETCH=1` with a pre-placed DLL. |
| `stellarr-studio/kelvaroq` | Prebuilt `Kelvaroq-0.2.0-windows-x64.zip`, **31,856,767 bytes**, 2,688 downloads, SHA-256 published in the release body (`c2f99a3c…5885`); includes native engine, reference interpreter, notices, `sources/native.zip`; update check is **read-only** (GitHub API, opens a link; no auto-download) | Binary trust; “built entirely with Moon AI” provenance; 31 MB opaque engine | Verify SHA-256 before extracting; prefer building from source; run in a sandbox/VM first. Do not run as admin or add AV exclusions. |
| `DoubleGhosty/cool_fox` | `Play-VIctory-4GB.cmd` hardcodes `VICTORY_GAME_DIR=C:\Users\Léo\Downloads\GTA\GTA6.Xbox.v1.0.2.1-CYBERLEEK` | Leaks a developer's Windows username and the leaked-dump folder name; normalises using the leak; not malware | **Never run as-is.** Set `VICTORY_GAME_DIR` to your own dump. Treat the path as a provenance red flag, not an exploit. |
| `Dolberthi/neptune-dolberth-nvidia-8gb` | `neptune-turbo.ps1` changes process priority/affinity, lowers background memory priority, **closes NVIDIA Broadcast**, and launches a generated sampler with `powershell.exe -ExecutionPolicy Bypass` | System-wide side effects; hidden helper process | Review before running; skip it for benchmarking. It is not required by the runtime. |
| `kitotake/cool_fox` | README download instructions point to `codec-d/cool_fox/releases/latest` → **404** | Dead link; if the repo is ever republished, followers may grab an unverified ZIP | Do not follow the link. Use source at a pinned SHA. |
| `Zettrox/ztrx` | Repo **and account** are 404 | Cached links/reuploads cannot be traced; possible name reuse | Do not use any `ztrx` mirror (`Smurfshot/ztrx`, `Beaver6513/ztrx-lowvram`, etc.). |
| Repos whose trees we scanned (`DoubleGhosty`, `miaohaixiang`, `Dolberthi`, `Giovanna`, `kelvaroq`, `LNX`) | **No committed `.exe`/`.msi`/`.zip`/`.dll`** except Kelvaroq's release asset. The four CI workflows we read use `actions/checkout@v4/v5` with a `permissions:` block and contain **no `pull_request_target`, no `secrets.`, and no `curl`/`Invoke-WebRequest`**. | Low | Still pin SHAs; do not run untrusted PR workflows. |

### 6.2 Do-not-use list

**A. Security — never run**
1. `gamescarletmaster.exe`, “GTA VI PC installer”, “GTA 6 PC Version”, “KytyPS5” landing pages, `FREE-GTA6-*`, `GTA-VI-Installer-PC`, `GTA-6-CyberLeek-PC-Build`. `[F]`
2. The 33-repo “GTA 6 Switch Version PC Emulator 2026” ring — identical repos created within minutes, cross-starred, promoting a “PC installer”. PortWatch labels them **malware**. `[F]`
3. Any download that asks for admin, an antivirus exclusion, crypto/gift cards, or a password. Security researchers tracked **355 fake-launcher domains** and **27,000+ GTA VI-themed detections**; ESET found `gta6_installer.exe` carrying the Vidar infostealer. `[F]`
4. `ad3lre/victory-nvidia-8gb` **with telemetry left on**. `[F]`

**B. Provenance — unverifiable / missing**
5. `codec-d/cool_fox` (404) and any ZIP claiming to be its “private release”. `[F]`
6. `Zettrox/ztrx` (repo + account 404) and every `ztrx` re-upload. `[F]`
7. Any `cool_fox` mirror other than the three pinned siblings; no canonical tree exists. `[I]`
8. PortWatch's 104 known re-uploads (e.g. `alvarez190/VIctory-7900XTX`, `fablinoo/palmwave`) — copies can hide modified build scripts. `[F]`

**C. Performance — safe but not worth our time**
9. `GiovannaSGuerrera/Victory-RTX2080` — honest, but 0.3–2.5 fps at 720p and crashes. `[SR]`
10. `Marvisak/VIctory` — ~1 fps; base only. `[SR]`
11. `kitotake/cool_fox` — stale snapshot, dead release link, 1★. `[F]`

---

## 7. Recommendation

**Use soldsawn's 8 GB profile as the reference, not CGBJ.** The public, reproducible 8 GB ceiling is **8–10 fps at 1080p** on an RTX 4060 Laptop with 48 GB RAM, and that number depends on three things we can copy: **1080p + `DROP_MIPS=2` to fit 6.6–7.0 GB**, **Series X for correct head/skin meshes**, and **async texture upload** (`HEAP_WORKER=1`). CGBJ's 25 fps is a 16 GB-VRAM private claim with an incoherent 8 GB-RAM spec; the same code family measures **2.4–2.7 fps at 1080p** on our laptop class, so it must not set our target. The highest-leverage new code is CGBJ's **submission** work — Port 5 zero-copy CBV (~22,000 copies/frame), Port 1 in-place 32-bit heap, and descriptor-record deferral (280 → 124 ms) — because our own E2b already showed VRAM is not the limiter once the world fits: the submit/copy thread is. Port those onto our pinned tree, keep the 8 GB residency profile, and measure with our existing protocol; expect **3–6 fps on 16 GB RAM**, not 8–10, because soldsawn had 48 GB and our commit pressure is worse. Treat 30 fps as a native-renderer problem; the layer's best public 8 GB result is ~10 fps with the GPU half idle. `[R]`

---

## 8. Next 3 experiments for our tree

All three use `docs/BENCHMARK-PROTOCOL.md`: same save, 300 s, warm cache, median + p95, draws, submit/copy/GPU ms, peak dedicated VRAM + private commit, 1 % low, screenshots at fixed points.

### E-A — 8 GB residency profile (cheapest, highest confidence)

- **Patch:** `VICTORY_TEXTURE_DROP_MIPS=2` (PR #610 / `fcb4f71b`), `VICTORY_RESOLUTION=1920x1080`, `VICTORY_COPY_PLAIN=1` (#1032), `VICTORY_HEAP_WORKER=1` (#1007), `--console series-x`.
- **Hypothesis:** on our 4060/16 GB, VRAM falls from ~7.5 GB to ≤7.0 GB, texture-slot waiting drops below ~2,000, and fps moves from 1–2 to **4–6**. `[I]`
- **Measure:** VRAM/commit, `textures waiting`, submit ms, copy-back ms, fps. A/B each switch, not the bundle.
- **Kill:** if fps is unchanged at stable VRAM (as in our E2b), stop tuning residency and go to E-B. If commit paging rises above ~15 GB, drop `HEAP_WORKER` and retest.

### E-B — Port CGBJ submission changes (highest upside)

- **Patch:** cherry-pick `c7fff541` (Port 5 CBV), `c4966402` + `5e0c9ab0` (Port 1 constants), and the descriptor-record deferral from `f4b48ad`. Keep each behind its `VICTORY_PORT_*` switch.
- **Hypothesis:** submit-thread time falls ≥30 %, copies/frame fall by ~20 k, and fps moves **+50–150 %** at the same picture (target 4–6 fps). `[I]`
- **Measure:** submit ms, `after_present`/`until_submit`, copies MB/frame, draws, fps; A/B Port 5 and Port 1 separately.
- **Kill:** if submit ms does not move, the bottleneck is elsewhere (write-watch / relay); fall back to `VICTORY_THIN`/`JOIN_PARTS` profiling and the Neptune submit profiler.

### E-C — Shader/LOD correctness gate (not an fps experiment)

- **Patch:** `caec5030` (undefined LOD slot), `cbb00ee8` (voxel wave64), `db556df3` (`NAN_SCRUB`, off by default), `4dc1ac71` + `4bf44ac9` (bind cache), `LNX`'s `LDS_REGION_RACE=1` + `LDS_BOUNDS` default.
- **Hypothesis:** pipeline refusals go from ~245/26,599 to <50, dropped draws from ~7 % to <2 %, and black/garbage faces + foliage disappear. `[I]`
- **Measure:** refusal count, dropped-draw reasons, 10 fixed screenshots, crash log. Do **not** judge by fps.
- **Kill:** if a switch changes console behaviour (NaN scrub) or crashes the RT builder, keep it off and document it.

**Watch, do not merge:** Kelvaroq's translate-once descriptor model and unified-memory layer. It is the only public design that claims to remove the copy loop (100 MB → <8 MB/frame) rather than tune it. If E-B plateaus below 6 fps, this is the next research spike. `[I]` `[R]`

---

## 9. Evidence log

### 9.1 Retrieval

| Item | Value |
|---|---|
| PortWatch JSON | `https://portwatch-vi.xyz/data/tracker.json` |
| Fetched | 2026-11-26T16:18:31Z (server `updated` field) |
| SHA-256 | `AE51F7D2111496921151835195F40C30E695779690C9A778858AF83AEDA3351A` |
| GitHub API | authenticated GitHub CLI; `rate_limit.core` 4,973/5,000 remaining at start |
| HTTP checks | `codec-d/cool_fox` → 404; `Zettrox/ztrx` → 404; `users/Zettrox` → 404; `users/codec-d` → 200 (id 58233486) |
| DMCA log | `github/dmca/2026/11` has 164 files; newest entries are 2026-11-24; the only GTA VI notice is `2026-11-24-take-two.md` (Leonida); **no CGBJ/codec-d notice** |
| Binaries | none downloaded or executed |

### 9.2 Repository metadata (as of 2026-11-26T18:2xZ)

| Repo | Stars | Forks | Open issues | License | Created | Pushed | Head |
|---|---:|---:|---:|---|---|---|---|
| `soldsawn/victory-nvidia-8gb` | 62 | 11 | 5 | GPL-3.0 | 2026-11-25T13:52Z | 2026-11-25T21:55Z | `c09a44e97df4` |
| `ad3lre/victory-nvidia-8gb` | 5 | 5 | 0 | GPL-3.0 | 2026-11-25T19:48Z | 2026-11-26T17:17Z | `f2553c2506d6` |
| `miaohaixiang1-netizen/cool-fox-12gb` | 3 | 4 | 2 | GPL-3.0 | 2026-11-26T09:01Z | 2026-11-26T11:52Z | `67298e81824e` |
| `Linox-IDK/LNX-victory` | 4 | 0 | 0 | GPL-3.0 | 2026-11-24T21:56Z | 2026-11-25T22:53Z | `c04e6159c145` |
| `DoubleGhosty/cool_fox` | 575 | 359 | 23 | GPL-3.0 | 2026-11-26T08:48Z | 2026-11-26T17:59Z | `3277b1565118` |
| `kitotake/cool_fox` | 1 | 3 | 0 | GPL-3.0 | 2026-11-26T08:37Z | 2026-11-26T11:42Z | `7329cbd1b2ff` |
| `GiovannaSGuerrera/Victory-RTX2080` | 2 | 1 | 2 | GPL-3.0 | 2026-11-26T01:35Z | 2026-11-26T09:39Z | `ede4cbb6f872` |
| `Zettrox/ztrx` | — | — | — | — | — | — | **404** |
| `Belobug/VIctory-Belobug-AMD` | 1,823 | 348 | 230 | GPL-3.0 | 2026-11-25T09:41Z | 2026-11-26T17:52Z | `cd8dfc06ace7` |
| `avatarmanz/VIctory-7900XTX` | 1,793 | 580 | 276 | GPL-3.0 | 2026-11-25T22:18Z | 2026-11-26T17:26Z | `2de998014dc8` |
| `DexNom/VIctory` | 1,216 | 156 | 89 | GPL-3.0 | 2026-11-25T12:14Z | 2026-11-26T01:12Z | `64bd58f5fb79` |
| `xcl-dev/xcl` | 8,551 | 1,189 | 1,838 | GPL-2.0 | 2026-11-20T20:03Z | 2026-11-26T18:06Z | `8b957bec6f82` |
| `Marvisak/VIctory` | 13,169 | 2,196 | 2,034 | GPL-3.0 | 2026-11-23T21:47Z | 2026-11-25T23:27Z | `63bcca43c6a0` |
| `fxceless/victory-fork` | 3,250 | 967 | 1,176 | GPL-3.0 | 2026-11-24T18:02Z | 2026-11-26T18:08Z | `52ac4ec0f8a0` |
| `uiliannn/VItoriaBr` | 222 | 50 | 85 | GPL-3.0 | 2026-11-24T10:05Z | 2026-11-26T04:09Z | `1361e190b7f4` |
| `stellarr-studio/kelvaroq` | 168 | 47 | 11 | GPL-3.0 | 2026-11-24T22:58Z | 2026-11-26T17:59Z | `e062a82e0485` |
| `trustno1-coder/VIctory-NVIDIA` | 97 | 32 | 0 | GPL-3.0 | 2026-11-25T23:35Z | 2026-11-26T17:57Z | `85a529b61a8e` |

### 9.3 What we did not verify

- We did **not** run any build or measure fps ourselves. Every fps number in this brief is `[SR]` unless labelled otherwise.
- We did **not** download the Kelvaroq ZIP, the leaked dump, or any game bytes. The SHA-256 is quoted from the release body.
- We did **not** inspect `codec-d/cool_fox` (404). Its content is known only through the three mirrors and `f4b48ad`.
- We did **not** prove that `DoubleGhosty` or `kitotake` are exact copies of the original beyond the shared `f4b48ad` commit. Sibling branches can contain unrelated changes.
- Star/fork counts are point-in-time and can be inflated; the `DoubleGhosty` fork:star ratio (0.62) is abnormal and should not be read as adoption.
- PortWatch scores are self-reported and not independently reproduced; its own CGBJ entry says the code is private and the fps is owner-reported.
- We did not read all 164 DMCA notice bodies. The “no notice” finding is based on the directory's filenames (no CGBJ/codec-d entry, newest 2026-11-24) and the one GTA VI-related notice (Take-Two/Leonida).

---

## 10. One-line answers

- **Best public 8 GB NVIDIA option:** `soldsawn/victory-nvidia-8gb`, 8–10 fps @1080p, RTX 4060 Laptop, 48 GB RAM. `[SR]`
- **CGBJ on 8 GB:** does not exist as a public, reproducible option. 25 fps is 16 GB VRAM, private, unverified. `[F]`
- **Same-laptop CGBJ-family measurement:** 2.40–2.70 fps @1080p. `[SR]`
- **Biggest new lever:** CGBJ Port 5 zero-copy CBV + Port 1 in-place heap + descriptor deferral. `[F]`
- **Biggest correctness trap:** in the CGBJ continuation, Series S on an 8 GB card drops head/skin meshes — verify faces before trusting Series S results. `[F]`
- **Do not use:** `ztrx` (404 account), `codec-d/cool_fox` (404), any `cool_fox` “release” ZIP, any GTA VI “installer”. `[F]`
