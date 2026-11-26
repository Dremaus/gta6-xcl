# Crash triage — int3 (`0x80000003`) and access violations (`0xc0000005`)

Date: 2026-11-26 · Scope: read-only analysis of `D:\Gry\VItoriaBr-data\data\7952987A\crashes.log`,
the running title's prepared image, and the layer tree `D:\git\VItoriaBr-opt` (read-only).
**The game was not started, stopped, focused, suspended or read from memory. No Ghidra import of the
120 MB image was made. No game content or game bytes are reproduced in this report** (only RVAs,
file offsets, PE header facts, instruction *semantics* and numeric code constants).

---

## 0. Verdicts at a glance

| # | Event | Verdict | Confidence |
|---|-------|---------|-----------|
| 1 | `0x80000003` at `victory-image-…dll+0x5149aec`, **57 of 58 int3 reports** | **Title-side assertion**, byte `0xCC` is **on disk** (memory == file). It is the *"free list empty"* trap of a title pool allocator, reached through a legitimate virtual call. Nothing was patched into `.text`. | **Very high** (byte + control flow + register invariant 57/57) |
| 1b | Writer of the `0xCC` | **The title's own compiled code**, copied verbatim by `prepare.rs`. Not the layer. | High |
| 2 | `0xc0000005` write at `victory.exe+0x66cfae`, fault address `0x54311ac00` | A **transient non-present / no-access window** hitting a `zlib-rs` literal store that writes into **title memory** on a **DirectStorage worker thread**. Not a code bug in `zlib-rs`; not a stale-pointer wild write. | Medium-high (mechanism proven; losing interleaving inferred) |
| 3 | The whole AV population (5 reports: 3 reads, 2 writes) | **Systemic**: every one reports a page that is `read-write` *at report time* while the access faulted. That is the signature of the layer's **remap gap / placeholder window**, not of five independent bad pointers. | Medium-high |
| 4 | Correlation with the Fast4 profile | **Mechanistically strong** for `relay=2` (`relay_exact`), which removes the "wait for everything" barrier for submissions that read title memory, plus `queue2`/`async_submit` adding threads. Not yet A/B-proven. | Medium |

The earlier "the file at that RVA contains `0x85 0xED`, no `0xCC`" finding is **wrong**: it read
`file_offset = RVA − 0x1000` instead of `RVA − 0xC00`, i.e. exactly **0x400 bytes too low** (the
`.text` `RawOff`). The `0x85 0xED` pair lives at RVA `0x51496ec`, `0x400` bytes before the crash
site. See §2.2.

---

## 1. Artifacts and identity

| Artifact | Identity | Evidence |
|---|---|---|
| Layer binary | `target\release\victory.exe`, 9,970,176 bytes, SHA-256 `bf12251edb95f1c47a22c06a210c76bcb1d169c8f2ffeb3f7d3744f2a9638df0` | REA `inspect_rust_binary` → **`ev_8b7c5e724b3be6f98dac0aafd20f09c643cc098cba6e3441ab025d02e33aeda6`**; `inspect_binary_hardening` → **`ev_020c068146750314b5f3c0d2fc04d2bc82fc5ab6b12655b213b9ed206b9d4632`** |
| Prepared title image in the crash | `victory-image-b99f876b74d4a77f.dll`, 120,181,760 bytes, `ImageBase 0x140000000`, `SizeOfImage 0xb06d000`, `DllCharacteristics 0x8160` (ASLR/NX/high-entropy; **CFG absent**), 10 sections | Byte-level PE parse (this analysis) |
| `.text` of that image | `VA 0x1000`, `VSize 0x5f3f966`, `RawOff 0x400`, `RawSize 0x5f3fa00` → **`file_offset = RVA − 0xC00`** | same |
| `.pdata` | `VA 0xabcf000`, 299,257 `RUNTIME_FUNCTION` entries | same |
| PDB of the layer | `target\release\victory.pdb` (36,392,960 bytes), DBI age 1, 13,123 `S_PUB32`, 0 `S_GPROC32` | Minimal MSF/CodeView parser (this analysis) |
| `zlib-rs` | `0.6.8`, checksum `b268e58e…4112` | `Cargo.lock:903-906` |

REA hardening facts for `victory.exe` (`ev_020c0681…`): `dynamic_base` enabled, `high_entropy_va`
enabled, `nx_compat` enabled, `guard_cf` **enabled** (`DllCharacteristics 0x4000`), `cfg_instrumented`
claim set, no Authenticode. REA `inspect_rust_binary` found **no `.dep-v0`** section (no
cargo-auditable metadata), and inferred rustc commit `48a229ceaefd4985c50990b14116b6d856af0985`
from a `/rustc/<hash>/` path at file offset 7,733,248. *Absence of `.dep-v0` is not proof of no
dependencies* — dependencies were read from `Cargo.lock` instead.

---

## 2. Crash 1 — `0x80000003` at `0x5149aec`

### 2.1 What the log actually says (57 of 58 int3 reports)

Identical RVA in **57** reports across several dying processes, with an identical register
signature every time:

- `rax` low 32 bits = **`0x0001fffe`** in **57/57** reports; the high 32 bits are constant *within*
  a process and differ between processes (`0x829…` vs `0x166…`).
- `rbx == rdx` (`0xc` or `0x10c`), `rsi = 0xc`, `rbp` 0x20…0x160, `r12` small (1…0x158),
  `r13 = 0`, `r15` a heap-looking pointer, `rsp` in the thread's stack.
- frames `#3…#7` are the same in every report, ending in `KERNEL32+0x2dda7` / `ntdll+0xc9c5c`
  (`BaseThreadInitThunk` / `RtlUserThreadStart`) — a **worker thread**, not the main thread.
- the remaining int3 report is at a **different** site (`0xf2cc4b`, `rax = 0`), §7.5.

`#1 = 0xa5db22` is the **return address** of `call qword ptr [r9+0x30]` at `0xa5db1e`
(`r9 = [object]`, `rcx = object`, `edx = ebx`, `r8b = [rdi+0x7d]`). So the trap was reached from a
**legitimate virtual call through vtable slot 6**. `#2 = 0x5453ac7` is the return address of the
`call` at `0x5453ac2` in the function starting at `0x5453ab0` (`push rsi/rdi/rbx`, `sub rsp,0x30`,
`r8 = &out`), i.e. #1's caller.

### 2.2 RVA → file offset, and the correction of the earlier finding

| RVA | file offset | bytes at that offset |
|---|---|---|
| `0x5149aec` (**crash RIP**) | **`0x5148eec`** | **`cc`** — the int3 *is in the file* |
| `0x5149aec` read as if it were a file offset | `0x5149aec` | unrelated code bytes |
| `0x5149aec − 0x1000` (**the old parse**) | `0x5148aec` | **`85 ed`** — where the old "no 0xCC" claim came from |

The old parse used `RVA − section VA` and **dropped `.text`'s `RawOff = 0x400`**. The `0x85 0xED`
pair also occurs at RVA `0x51496ec` (a second occurrence), which is why the wrong answer looked
plausible. Correct parse: **memory == file**; the crash RIP byte is `0xCC` on disk.

### 2.3 What the byte is (semantics, no bytes quoted)

The containing function is `[0x5149980, 0x5149b04)` per `.pdata` (len `0x184`, unwind info
`0x679d5f4`); the trap is at **+0x16c**. Its body is a **tagged free-list pop** (pool allocator):

```
head  = [rcx+0x20]                     ; 64-bit { tag: high 32 | index: low 17 }
if (u32)head == 0x1fffe  -> trap       ; free list empty           <-- reached in 57/57
idx   = head & 0x1ffff
tag   = head & 0xffffffff00000000
next  = ([rcx+0x28][idx] & 0x1ffff) | tag
lock cmpxchg [rcx+0x20], next ; retry on failure
lock inc dword [rcx+0x10]
[rcx+0x28][idx] |= dword [rcx+0x30]
ptr = [rcx]                            ; pool base
if (ptr == 0) -> trap                  ; pool not allocated        <-- the other trap, not hit
ptr += u32 [rcx+8] * idx               ; stride
if ([rcx+0x18] != 0) call [rcx+0x18](ptr)   ; optional ctor/notify
call 0x5149b10(ptr, 1)                 ; tail stub -> 0x27a040
return ptr
```

Both trap conditions jump to the same `0xCC`. The registers decide which one fired: `rax` holds
`head` at the `je`, and it is `…0001fffe` in **57/57** reports → **"free list empty"**, never
"pool base null".

Immediately after the `0xCC`: `xor edi,edi; mov rax,rdi; add rsp,0x28; pop rdi; pop rsi; ret`
→ the trap path **returns 0**, and the caller at `0xa5db22` does `test rax,rax; je <fallback>`.
So this is a **debug assertion with a designed graceful "no object" continuation**, fatal only
because nobody handles `EXCEPTION_BREAKPOINT` (`crash.rs:128-135` lists it as `FATAL`).

### 2.4 Writer attribution

| Candidate writer | Evidence | Verdict |
|---|---|---|
| Title image bytes | `0xCC` present at the exact mapped file offset; preceded by a 2-byte `jmp` that skips it, i.e. *not* the fall-through path | **Yes** |
| `victory-loader/src/prepare.rs` | `prepare()` (`prepare.rs:44-114`) rewrites only: `IMAGE_FILE_DLL`, `AddressOfEntryPoint`, `CheckSum`, `FORCE_INTEGRITY`, import directory → terminator, bound-import directory → 0, TLS callback pointer → 0 + one `DIR64` reloc → `ABSOLUTE`. **No `.text` write path exists.** | No |
| `victory-loader/src/thunks.rs` | writes `0xCC` padding, but only into its **own** `VirtualAlloc` block (`thunks.rs:117`), sealed `PAGE_EXECUTE_READ`, and only reached via `unimplemented_import` which **logs** `VItoriaBr: unimplemented import …` first (absent from the log) | No |
| `victory-loader/src/crash.rs:832` | `[0xCC; 16]` is a **stack local** in a test helper for the illegal-instruction emulator | No |
| `victory-gpu/src/host.rs:7258-7287` | `NtWriteVirtualMemory` path writes **shader results (data)** into title memory; never code | No |
| Any other `.text` / `VirtualProtectEx` / hardware-breakpoint writer | repo-wide search of `crates/` + `apps/` found **none** writing the title's `.text`; no `DR0..DR7` use | No |

**Attribution: the title.** The prepared image is a *copy of the title module* whose name is derived
from the original's BLAKE3 (`prepare.rs:29-31`), so the byte at `0x5149aec` is the title's own
compiled trap. Confidence **high**. The trap is also **not** the "detour with padding" shape: no
such detour is needed to explain this crash, and the layer rightly rejected it.

### 2.5 Verdict for crash 1

A genuine **title-side out-of-resources assertion** (empty tagged free list) inside a
vtable-dispatched pool allocator, hit repeatedly and deterministically per process (the head word
stays `…1fffe` for the whole process, so the pool is *permanently* exhausted — an allocation/release
imbalance, not a transient race).

**The layer must not patch the `0xCC`** — that byte is the title's diagnosis, and skipping it would
hide a resource leak. The layer's job is to find *why the title's pool never gets slots back*.
See §5 (P2) and §7.

---

## 3. Access violations — all five reports

### 3.1 The population

| # | Site | Access | Fault address | Protection at report | Internally consistent? |
|---|------|--------|---------------|----------------------|------------------------|
| 9 | `image+0x11171a8` | read | `0x53ac873b8` | read-write | yes (read of a title buffer) |
| 10 | `image+0x11170ae` | read | `0x524e322c8` | read-write | yes; frames `#1/#2/#3` **identical** to #9 (`0x1116f09`, `0x63e78`, `0x4eaa05a`) |
| 11 | `victory.exe+0x65709e` | write | `0x5433a6000` | read-write | **no** — see §3.2 |
| 12 | `image+0x4e8b4b4` | read | `0x516a22ec0` | read-write | yes (`rcx` = fault address) |
| 63 | `victory.exe+0x66cfae` | write | `0x54311ac00` | read-write | **yes** — see §3.3 |

**Every one of the five** faults on a page that `VirtualQuery` calls `PAGE_READWRITE` at report
time. `crash.rs`'s `memory_at()` is exact (`crash.rs:620-657`): `PAGE_GUARD` → "a guard page"
(`:642`), and "read-write" **only** for `Protect & 0xff == PAGE_READWRITE` (`:646`). So this is not
a formatting artefact. Five independent "bad pointers" that all happen to be RW at report time is
implausible; **one transient class** is the parsimonious explanation — and two of the three reads
share the exact same frame triple, i.e. the same copy/compare loop hit twice at nearby addresses.

The layer already documents this class for reads (`watch.rs:1103-1118`: *"the fault was taken in the
gap, the handler sees the page committed and read-write again … reports a read AV 'on a read-write
page' (the third crash class, 26.11)"*). The remap machinery uses `MapViewOfFile3` placeholders over
a reservation with `PAGE_NOACCESS` and then commits `PAGE_READWRITE` (`watch.rs:1480-1524`,
`1571-1616`); in that window any access — **read or write, title thread or layer thread** — faults
with `0xC0000005`, and by report time the window is closed.

### 3.2 Why record 11 is not usable (`victory.exe+0x65709e`)

- `.pdata` puts `0x65709e` at **+0x15e** inside `[0x656f40, 0x657101)` (len `0x1c1`), a function
  whose public-symbol neighbours and callers are `core::slice::sort::…`
  (`#1 0x65908a` ≈ `sort::stable::quicksort`, `#2 0x64a847` ≈ `sort::…::insert_tail`).
- Decoding from the **function entry**, `0x65709e` is **not an instruction boundary**: the
  instruction at `0x65709c` is a 3-byte `setne al` ending at `0x65709f`. `setne` touches no memory,
  so it cannot raise a write AV.
- That function's body contains a `call` followed by `ud2` — the Rust panic/abort pad — consistent
  with sort code, not with an inflate loop.
- Its `#3 = 0xd6442` (`LocalKey<RefCell<zlib_rs::stable::Inflate>>::with`) contradicts a sort chain.

Conclusion: record 11's lines are **scrambled**. `crashes.log` is appended to by several dying
processes without a lock, and the file visibly contains interleaved fragments (e.g.
`unix time unix time 1795676516, process 34152`, duplicated PID digits). Record 11 is therefore
**excluded** from the mechanism analysis; it is neither evidence for nor against a second zlib site.
This is a real triage-tooling defect (see §5 P3).

### 3.3 The consistent write AV (`victory.exe+0x66cfae`)

```
unix time 1795715258, process 8164
VItoriaBr: unhandled exception 0xc0000005 at victory.exe+0x66cfae (write 0x54311ac00: read-write)
  rax 0x8  rbx 0x26844658500  rcx 0x0  rdx 0x360  rsi 0x7ff7cd17dc40  rdi 0x101  rsp 0xee71dfee50  rbp 0x1ff
  r8 0x0   r9 0xa8c0c0c7e9ec101  r10 0x8  r11 0x20  r12 0x54311ac00  r13 0x50  r14 0x9  r15 0x3d
  #0 0x66cfae  #1 0x66ef9a  #2 0x660757  #3 0xd6442  #4 0x100bd0  #5 0x10450f  #6 0xcd8f9
  #7 0xeaaf4  #8 0x6fe8f3  #9 KERNEL32+0x2dda7  #10 ntdll+0xc9c5c
```

`0x66cfae` is `mov byte ptr [r12 + rcx], r13b` with `rcx = 0` → the faulting address is **exactly
`r12 = 0x54311ac00`**, at page offset `0xC00`. `r13b` is the decoded literal byte, `r12` the output
base, `rcx` the output position. **The very first byte of the stream's destination was not
writable.**

Function: `.pdata [0x66cd20, 0x66dd23)`, len `0x1003`, fault at **+0x28e**. Its body is the inflate
state machine (jump table on `[rcx+0x158]`, Huffman tables at `[rsi + idx*4]`, `out` base
`= [rcx+0x70]` → `r12`, `out_len = [rcx+0x78]` → `[rsp+0x38]`), entering by zeroing
`[rcx+0x78..0x88]` and setting `[rcx+0x70] = 1` as an in-progress sentinel. The store is guarded by
`cmp rcx, [rsp+0x38]; jae <slow/error path>` **before** it — the length was fine; the *destination*
was not writable.

Symbols (PDB `S_PUB32`):

| RVA | Symbol | Role |
|---|---|---|
| `0x66c3d0` | `zlib_rs::crc32::pclmulqdq::Accumulator::finish` (next `0x66dd30`) | shows `0x66cd20` has **no public symbol** (private/inlined) |
| `0x66cfae` | inside the `0x66cd20` function | **literal store of `inflate`** |
| `0x66e0f0` | `zlib_rs::inflate::inflate` (next `0x6711f0`) → `0x66ef9a` inside | #1 |
| `0x660710` | `zlib_rs::stable::Inflate::decompress` (`0x660710..0x660820`) → `0x660757` inside | #2 |
| `0xd6370` | `std::thread::local::LocalKey<RefCell<zlib_rs::stable::Inflate>>::with` (next `0xd6690`) → `0xd6442` inside | #3 |
| `0xcd8f9` | `___rust_begin_short_backtrace::<…victory_hle::modules::dstorage::schedulers::{{closure}}…>` | #6 = DStorage **scheduler thread entry** |

### 3.4 Layer call chain (source file/line recoverable)

```
victory_hle::modules::dstorage::work()                 dstorage.rs:492   (scheduler worker thread)
 └ execute(request)                                    dstorage.rs:854
    └ into_destination(request, len, fill)             dstorage.rs:1065
       ├ victory_gpu::kernel_will_write(dest, len)     dstorage.rs:1075  <-- opens guarded blocks
       ├ out = from_raw_parts_mut(dest, len)           dstorage.rs:1078  <-- raw slice over TITLE memory
       ├ fill(out)                                     dstorage.rs:1079
       │   └ inflate(source, out)                      dstorage.rs:932  (Zlib branch: 918 / 908)
       │       └ INFLATE.with_borrow_mut(|state| ...)  dstorage.rs:937  (thread-local zlib_rs::Inflate)
       │           └ state.decompress(...)             dstorage.rs:947
       │               └ zlib_rs::stable::Inflate::decompress      0x660710
       │                   └ zlib_rs::inflate::inflate             0x66e0f0
       │                       └ mov [r12+rcx], r13b               0x66cfae  <-- FAULT
       └ victory_gpu::title_memory_written(dest, len)  dstorage.rs:1085
```

`kernel_will_write` is `victory_gpu::watch::writing` (`watch.rs:860-865`, re-exported at
`lib.rs:86`):

```rust
pub fn writing(at: usize, len: usize) {
    open(&mut guards(), at, at.saturating_add(len));   // takes guards() only
    crate::descriptor::host::remapped(at, len);
}
```

Guards are `VirtualProtect(…, PAGE_READONLY)` (`watch.rs:749-755`); the VEH's open path restores
`PAGE_READWRITE` (`watch.rs:839-854`). **`writing()` takes the `guards()` mutex, not the `MAPPING`
lock**, and the block can be re-guarded immediately afterwards — the code comment at
`dstorage.rs:1071-1074` says so explicitly ("a block guarded again meanwhile faults into the guard
instead of failing the write"). That is the designed behaviour; it relies on the VEH to open it.

### 3.5 Why it was fatal (not a recovered first-chance fault)

`crash.rs` prints **"first-chance exception"** from the VEH (`crash.rs:359-379`) and
**"unhandled exception"** only from the unhandled filter (`report_unhandled`, `crash.rs:386-389`).
This entry says *unhandled* → the process was terminating. So the VEH's write branch **declined**:

```
watch.rs:1142-1175
  if open(&mut g, at, at+1) -> CONTINUE_EXECUTION        // our guard, fine
  if writable(at)           -> CONTINUE_EXECUTION        // became RW again, fine
  else if reserved(at) && !this_thread_remapping() { wait; retry if back }
  else                      -> CONTINUE_SEARCH           // <-- fatal path taken
```

`writable()` is strict (`watch.rs:1304-1312`): `State == MEM_COMMIT && Protect == PAGE_READWRITE`.
`open()` only recognises blocks recorded in `g.protected` (plus registered aliases,
`watch.rs:819-835`). `reserved()` only recognises `State == MEM_RESERVE`. A page that is
**committed but `PAGE_NOACCESS`**, or a page whose remap completed between the fault and the check,
matches **none** of the three, so the branch gives up. The read branch, by contrast, has
`late_retry()`/`read_retry()` (`watch.rs:1119-1141`, `1231`, `1243`) bounded retries and a
"wait for the remapping, then re-ask" step.

**The asymmetry is the bug**: the write branch has no equivalent of "wait for the mapping change and
ask again".

### 3.6 Verdict for crashes of type 2

`zlib-rs 0.6.8` is doing exactly what it was asked: writing literal bytes into the slice the layer
handed it at `dstorage.rs:1078`, which is **title memory**. The fault is a **remap/guard window on a
title page** hit by a layer thread during a DirectStorage decompression, fatal because the VEH's
write branch gave up instead of waiting and re-asking. Confidence medium-high on the mechanism
(protection string, code paths and the 5/5 RW-at-report pattern are proven), medium on the precise
losing interleaving (no fault-time `VirtualQuery` is in the log).

---

## 4. Correlation with the Fast4 profile

`relay=2, late_wait=2, join_parts=8, join_copies=1, queue2=1, async_submit=1`

- `relay=2` = `relay_exact()` (`host.rs:2125-2137`): *"a submission that reads title memory a
  flight's shaders may write … waits only until the flights that declared that memory have landed,
  **not for everything in the air**"*. At `relay=1` both wait for **everything**. This removes a
  global barrier between GPU-side merges (which re-guard and copy title pages — `host.rs:7256-7287`,
  `write_mapped` via `NtWriteVirtualMemory`) and other threads that touch title memory. The
  DStorage destination is **not declared as a flight range**; it is only opened through
  `watch::writing()`.
- `queue2=1` (fetches on a second copy queue, `host.rs:2265-2272`) and `async_submit=1`
  (`framelog.rs:35`, separate submit thread) add **more concurrent threads** touching the same block
  set — more chances for a re-guard/remap to race a reader or writer.
- `late_wait=2` (`host.rs:2029-2069`, stats at `host.rs:3457`: *"title bytes put in under flights'
  shader writes per frame"*) increases look-at/write-back activity during loading — the same window.
- Caveat: `relay`, `join_parts`, `join_copies` are **profile-log labels**; the tree's identifiers are
  the env switches `VICTORY_RELAY`, `VICTORY_QUEUE2`, `VICTORY_ASYNC_SUBMIT`,
  `VICTORY_LATE_WAIT`. `join_parts`/`join_copies` were **not found as identifiers** in this tree.

**Verdict: strong mechanistic correlation, not proof.** There is no profile-off run in the log, and
the DStorage worker is not itself gated by these switches — the profile widens the window rather
than creating the fault. This is exactly what A/B step 1 tests (§6).

Note also a **host GPU device removal** in the same log (`0x887A0007`, "after 1 submissions sent
ahead (`VICTORY_RELAY=1`)", PIDs 20920, 18372). Those are a different failure mode (device lost),
not an AV, and are out of scope here.

---

## 5. Fix proposal

### P0 — write-AV, ~15 lines in `watch.rs` (minimal, behaviour-preserving)

In `on_write`, replace the final `else { CONTINUE_SEARCH }` with the read branch's pattern:

```rust
} else {
    drop(g);
    // The page may be no-access (a remap placeholder) or read-only for a
    // change that has not finished, or has just finished. Ask again once it
    // is quiet, exactly as the read side does, bounded per thread and address.
    let waiting = (!this_thread_reading()).then(title_memory_reading);
    let ok = { let mut g = guards(); open(&mut g, at, at + 1) } || writable(at);
    drop(waiting);
    if ok && write_retry(at) {          // same shape as read_retry(), watch.rs:1243
        framelog::add(T::GuardFaults, 1);
        return EXCEPTION_CONTINUE_EXECUTION;
    }
    EXCEPTION_CONTINUE_SEARCH
}
```

Rationale: turns a rare fatal AV into a retry; no change to the success path; bounded, so a genuine
bad pointer still reports. Guard with an env switch (`VICTORY_WRITE_RETRY=1`) for an exact A/B.

### P1 — root cause (structural, after P0 confirms)

Make the CPU-writer declaration *stick* for the duration of the write instead of being undone by a
concurrent guard/remap: either

1. register `[dest, dest+len)` in the `Guards` bookkeeping as "CPU writing" (a per-block writer
   count that `guard()`/`copy_mapped`/the remapper skips while non-zero), **or**
2. make `dstorage`'s direct-address branch write via the bounce buffer when the destination block is
   in a guarded/aliased set — the `PAGE_DESTINATION` path already does the "fill beside, then
   `write_physical`" dance with retries (`dstorage.rs:1110-1167`).

**Do not** try to fix this by holding `title_memory_reading()` across `fill(out)` alone:
`writing()` takes `guards()`, not `MAPPING` (verified above), so a `MAPPING` read lock would not stop
a re-guard.

### P2 — int3 (diagnostics only; **do not patch the byte**)

1. **No `.text` patch, no detour.** The `0xCC` is the title's own assertion and is already `0xCC` on
   disk; a "detour with padding" would *mask* an allocation/release imbalance.
2. Add layer-side bookkeeping that would let the next run name the exhausted pool: count
   create/release per HLE module, and on `EXCEPTION_BREAKPOINT` append those counters plus the
   faulting object's vtable pointer (`[rcx]`) to `crashes.log`. One extra line in `report()`, no
   title-memory writes.
3. **Diagnostic-only experiment** (needs owner approval; a behaviour change): an off-by-default
   `VICTORY_INT3_SKIP=<hex RVA>` in `crash.rs` that, for a 1-byte `0xCC` at exactly that RVA, logs
   the pool state and advances `RIP` by 1. Because the trap path is `xor edi,edi; mov rax,rdi; …;
   ret` (returns 0) and the caller tests `rax` for 0 with a fallback, this exercises the title's
   **own graceful "no object" path**. It fixes nothing; it answers "is the NULL path survivable, and
   how far does the run get?". Risk: converts the crash into a later NULL dereference and hides the
   leak — diagnostic builds only.

### P3 — crash-log integrity (cheap, high value for triage)

`crashes.log` interleaves lines from concurrent dying processes (visible as duplicated
`unix time`/`process` fragments, and as the incoherent record 11 in §3.2). Write each report under a
single lock **and** a single `write_all` with a record id and a trailing delimiter, so a record can
never be spliced. Until then, treat any report whose lines disagree (RIP not on an instruction
boundary, frames from unrelated modules) as suspect rather than as evidence.

---

## 6. Safe A/B plan (no changes to the running tree or the running game)

Hard rules: build **only** in a separate worktree of `D:\git\VItoriaBr-opt` (e.g.
`opencode.worktree_create`), never in `target\release`; never touch the running `victory.exe`/PID
21992; one variable per run; each config = 3 loads of the same save/seed, 15–20 min.

| Step | Build | Env (added to the Fast4 profile) | What it tests | Pass criterion |
|---|---|---|---|---|
| A1 | current | `VICTORY_RELAY=1` | `relay_exact` is the enabler | 0 AV entries in 3/3 loads |
| A2 | current | `VICTORY_QUEUE2=0` | second copy queue is the second thread | 0 AV entries |
| A3 | current | `VICTORY_ASYNC_SUBMIT=0` | submit thread is the third thread | 0 AV entries |
| A4 | current | `VICTORY_LATE_WAIT=1` | page look-at/write-back under flights | 0 AV entries |
| B1 | P0 (`VICTORY_WRITE_RETRY=1`) | full Fast4 profile | the fix | 0 `unhandled exception 0xc0000005`; the write-retry counter > 0 proves the race was hit and absorbed |
| B2 | P0 off (`=0`) | full profile | regression gate | same AV reproduced (controls the harness) |

Per-run metrics (all already logged or trivially added): `crashes.log` entries by
`(code, module+RVA)`; `framelog` `GuardFaults`, `LateReads`, `RemapUs`; DirectStorage `RETRIED[0..2]`
and `VICTORY_DSTORAGE_RETRIES`; the P0 write-retry counter.

Ordering: **A1 → A4 (no rebuild) → B1**. If one of A1–A4 clears the AV, the immediate mitigation may
be a profile change rather than code; B1 is the durable fix. Stop condition: if int3 frequency
changes in any arm (up or down), stop and re-baseline — the two crash classes may share a
resource-pressure cause.

---

## 7. Explicit unknowns

1. **Which pool the title exhausted.** The image is stripped of readable names; the vtable slot
   (offset `0x30`) and the caller's object layout (`+0x20`, `+0x7d`) are known, the pool's owner is
   not. Needs a title-side name (PDB/map) or the P2 counters.
2. **Pool capacity and the release path.** The head word is permanently `…1fffe` per process, which
   says "empty", not *why*. A leak, an over-sized initial allocation and a failed release all fit.
3. **Whether `0x85 0xED` came from this exact file.** I can prove the arithmetic that produces it
   (offset `RVA − 0x1000`) and that the current file has `0xCC` at the corrected offset; I cannot
   prove which file/parse produced the old note.
4. **The exact losing interleaving of the AVs.** A fault-time `VirtualQuery` (inside the VEH, before
   `open()`) would settle "committed no-access placeholder" vs "reserve gap" vs "guard we did not
   record". Not in this log.
5. **The second int3 site** `image+0xf2cc4b` (1 report, `rax = 0`, chain `0xe8905 → 0x194162 →
   0x50498d1 → 0x2591398 → 0x2592d0f → 0x2215eca`). A different assertion, not analysed. The outer
   frame `0x2215eca` also appears in the pool-trap chain (`#7`), so both come from the same thread
   pool.
6. **Whether `relay=2` is causal.** No profile-off run exists in `crashes.log`; §4 is mechanism +
   timing, not a controlled comparison.
7. **Whether continuing past the int3 is safe.** The caller's `test rax,rax; je` strongly suggests
   the title has a NULL path, but no run has taken it.
8. **`0x66cd20`'s own name.** It has no `S_PUB32` (private/inlined); identified as the inflate
   literal loop from its call chain, state layout and `.pdata` extent, not from a symbol.
9. **Frames `#4..#8` of the write-AV trace** and `#3..#7` of the int3 trace resolve to unrelated
   publics (`windows::Media::Audio`, `std::sys::io::error::windows::errno`, …). With modern x64
   unwind data these are not reliably attributable; only `#0..#3` are used here.
10. **The page at `0x54311ac00` was not read.** Reading the live process was out of scope by
    instruction; all conclusions come from the log, the file bytes, the PDB and the sources.
11. **The three title-side read AVs were not instruction-decoded.** They are used only as population
    evidence (same protection string; two share the same frames), not as per-instruction findings.

---

## 8. Evidence index

| Ref | Evidence |
|---|---|
| `ev_8b7c5e72…3aeda6` | REA `inspect_rust_binary`, `victory.exe`, SHA-256 `bf12251e…`, 9,970,176 B; no `.dep-v0`; rustc commit `48a229ce…` inferred at file offset 7,733,248 |
| `ev_020c0681…9d4632` | REA `inspect_binary_hardening`, same SHA-256; `dynamic_base`/`high_entropy_va`/`nx_compat` enabled; `guard_cf` enabled (file offset 334, 2 bytes); `cfg_instrumented` claim at file offset 8,577,584; no Authenticode (file offset 408) |
| Game image | `victory-image-b99f876b74d4a77f.dll`, 120,181,760 B, base `0x140000000`, `SizeOfImage 0xb06d000`, `DllCharacteristics 0x8160`; `.text` VA `0x1000`/RawOff `0x400`; `.pdata` VA `0xabcf000`, 299,257 entries |
| int3 site | RVA `0x5149aec` → file offset **`0x5148eec`** = `0xCC`; `.pdata` func `0x5149980..0x5149b04` (len `0x184`), trap at `+0x16c`; unwind `0x679d5f4` |
| int3 trap conditions | `cmp eax,0x1fffe; je 0x5149aec` and `test rdi,rdi; je 0x5149aec`; sentinel `0x1fffe`, index mask `0x1ffff`, head `[rcx+0x20]`, table `[rcx+0x28]`, bits `[rcx+0x30]`, base `[rcx]`, stride `[rcx+8]`, optional `[rcx+0x18]`, counter `[rcx+0x10]` |
| int3 continuation | `0x5149aed` `xor edi,edi` → `0x5149aef` `mov rax,rdi` → `add rsp,0x28` / `pop rdi` / `pop rsi` / `ret`; caller check at `0xa5db22` (`test rax,rax; je`) |
| write-AV site | RVA `0x66cfae` → `.pdata` func `0x66cd20..0x66dd23` (len `0x1003`), fault at `+0x28e`; `mov byte [r12+rcx], r13b`; `r12 = [state+0x70]`, `out_len = [state+0x78]` |
| write-AV chain | `0x66cfae` ← `zlib_rs::inflate::inflate` `0x66e0f0` ← `zlib_rs::stable::Inflate::decompress` `0x660710` ← `LocalKey<RefCell<Inflate>>::with` `0xd6370` ← `…dstorage::schedulers::{{closure}}…` at `0xcd8f9` |
| inconsistent record | `victory.exe+0x65709e` is **not** an instruction boundary (inside `setne al` at `0x65709c`); `.pdata [0x656f40,0x657101)`; callers `0x65908a`/`0x64a847` are `core::slice::sort::…`; body has a `ud2` panic pad → record scrambled |
| Sources | `dstorage.rs:492, 854, 918, 932-970, 1065-1087, 1110-1167`; `watch.rs:749-755, 819-854, 860-865, 1092-1176, 1243, 1304-1312, 1480-1524, 1571-1616`; `crash.rs:128-135, 359-379, 386-389, 620-657`; `prepare.rs:29-31, 44-114`; `thunks.rs:117`; `host.rs:2029-2069, 2125-2137, 7256-7287`; `Cargo.lock:903-906` |
| Crash log | `D:\Gry\VItoriaBr-data\data\7952987A\crashes.log`, 62,756 B, last write 2026-11-26 18:47:38: **58 int3** (57 × `image+0x5149aec`, all `rax&0xffffffff == 0x1fffe`; 1 × `image+0xf2cc4b`, `rax = 0`), **5 AV headers** (3 reads in the title image, 2 writes in `victory.exe`), all five "read-write" at report time |
