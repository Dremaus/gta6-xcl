# PROTO-RECOMP - H1 selective AOT (one hot leaf)

Status: **harness proven on a synthetic stand-in; real target pending profiling.**
Spec: [`NATIVE-VERTICAL-SLICE.md`](NATIVE-VERTICAL-SLICE.md) §0 (selective AOT, not
full recompilation), §3.3 (H1: one hot function), §4.8 (stop rules), §6.8
(selective AOT workflow).
Code: `D:\git\gta6-native-proto` (separate repo; no game data).

## 1. Exact H1 target

H1 asks for **one leaf draw-packet/constant packer**, selected by profiling,
called ≥500×/frame, writing a bounded buffer, using only a supported x64
subset, with a stable byte hash for build 1.0.2.1. Fallback order: frustum /
sphere visibility, matrix palette / skinning, draw-argument packer.

Target executed today: **synthetic stand-in**, not the title's function.

| field | value |
|---|---|
| provider | `synthetic` (`targets/standin/pack.asm`, 15 insns, 82 B) |
| module | `targets/standin/pack.bin` |
| rva / size | `0x0` / `82` |
| sha256(bytes) | `f9f42cb3f4204563ef00a9b9b26f4193a959acb11fb69596c76f5259b4778962` |
| call count / inclusive ms | `null` / `null` (profiler gap) |
| ABI | win64: `uint64_t f(const void* args, uint8_t* out, size_t cap)` |
| purity | reads `[args,args+64)`, writes `[out,out+64)`, no calls/branches/TLS |
| build guard | 1.0.2.1 image `e95020b2…a08993`, enforced before lifting |

The stand-in keeps the H1 shape: leaf, bounded input/output, AVX subset
(`vmovdqu`, `vpaddd`, `vpsrld`, `vcvtdq2ps`, `vmulps`, `mov`), and a packet
layout with ids, packed sums, UNORM16 floats, cap and a tag. Swapping in the
profiled RVA does not change the harness:

```powershell
.\build.ps1 -Target game -Image <game.exe> -Rva 0x<profiler-rva> -CallCount <n>
```

## 2. What was built

* `tools/lift.py` - x86-64 subset → C++ intrinsics on an explicit `G6nCpu`
  state; refuses unsupported instructions. No image bytes are embedded.
* `tools/interp.py` - interpreter of the untouched bytes producing the full
  final state (16 GPRs, 16 XMM, RFLAGS). Replaces Unicorn 2.1.4, which
  silently mis-executes VEX `vpaddd`/`vcvtdq2ps` on this host.
* `tools/oracle.py` - `interp` (original bytes, full state) and `native`
  (original bytes on the CPU, packet) oracles.
* `src/harness.cpp` - 110k-vector differential with packet canaries and an
  in-process exhaustive selftest; `--aot=off|on` is the kill switch.
* `tools/guard.py` + `manifest/builds.json` - build-hash and blob-hash pins,
  negative control included.
* `manifest/h1.json` - module/RVA/size/sha256/call-count manifest plus the
  exact profiler handoff.

## 3. Evidence (last run, `evidence/h1-diff.json`, verdict PASS)

| check | result |
|---|---|
| blob hash guard | OK (`f9f42cb3…`) |
| 1.0.2.1 image hash guard | OK (`e95020b2…`) |
| negative control (wrong hash) | rejected (exit 1) |
| vectors | 110,000 = 100,000 generated + 10,000 recorded (`b7147abc…`) |
| kill switch off vs on | byte-identical, FNV `21d0e9c54a9d880d` |
| original vs reference, 2,048 sample | 0 mismatches (full state + packet) |
| original vs lifted, 2,048 sample | 0 mismatches (full state + packet) |
| original vs native CPU, 2,048 sample | 0 mismatches (packet) |
| selftest | 1,048,576 vectors, 0 mismatches |

Reproduce:

```powershell
cd D:\git\gta6-native-proto
powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1
.\.venv\Scripts\python.exe tools\verify.py `
  --image "D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK\game_scarlett_master.exe"
```

## 4. Gap and what the profiler must supply

`D:\Gry\VItoriaBr-data\Launch-VItoriaBr-Profile.ps1` has not produced
`profile.txt.folded` yet, and the parser
(`D:\git\gta6-30fps\tools\profile\parse_victory_profile.py`) emits self/inclusive
times per **symbol name**, not module/RVA/size, calls/frame, or a recorded
corpus. Required from the profiler/layer for the real H1 unit:

1. module + RVA + size of the hottest supported leaf in `room01`;
2. sha256 of those function bytes (pinned to build 1.0.2.1);
3. calls/frame and inclusive ms over a 30 s sample;
4. 10k recorded invocations (args + out) captured at the call site.

Until (1)-(4) exist, `manifest/h1.json` stays `standin_pending_profiler` and no
claim is made about the title's code.

## 5. Stop-rule status (§4.8)

* Bit-exact: **PASS** on the stand-in, including full register state and
  kill-switch identity.
* Performance: **not measured**. §3.3 requires the lifted unit within 1.2× of
  the original and a ≥5% frame-time gain; without the real target and frame
  timing there is no claim.
* Integration: **none**. `G6N_RECOMP=off|on` frame-level identity/delta is a
  later gate; H1 remains a research result until both pass.

If the profiled candidate is not liftable or is slower, shelve AOT and spend
the time on the renderer (per §4.8); the 30 fps thesis does not depend on H1.
