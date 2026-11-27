# 14 — XUser offline-auth path: XCL fails fast, it never leaves a token request pending

Run `xcl-lockhart-200952`, W2 park t=180.4–598.6 s. Source: XCL `main` = `7318cf60` (read-only, no build, no GPU).
**REA not applicable** per `rea-evidence.md` §3: claims rest on complete XCL source + the run log, not a source-less binary.
Skill applied: ECC `deep-research` methodology adapted to local source (grep→call graph→evidence table); `research-ops` evidence-first rules.

## 1. State machine (file:line)

Call graph, title → XCL:
- `XUserAddAsync` (mod.rs:517) → `begin_with` local offline user, logs `XUserAddAsync(options=…) → local offline user` (mod.rs:518). `XUserAddResult` (mod.rs:525) hands the single `USER` handle and fires `user_signed_in()` (mod.rs:914–923) → device-association callbacks.
- Token flow (the only "auth request" that exists in XCL):
  `XUserGetTokenAndSignature(Utf16)Async` (mod.rs:756 / 798) → `note_token_request` (mod.rs:742–754):
  - counts #N (AtomicU64), logs `XUser: token #N for {method} {url} – …` when N<24 or N%64 (mod.rs:746–748);
  - `xbox_live_tokens = false` → returns `Err(E_CANNOT_CONNECT)` = **0x80072EFD** (mod.rs:737–738);
  - `true` → `build_token_payload` (mod.rs:698–722) with `xsign::offline_token()` = `XBL3.0 x=xcl;local-<id>` (xsign.rs:108–110) + real ECDSA P-256 XSTS v1 sig (xsign.rs:189–232).
- The Err is NOT returned to the caller synchronously: `begin_with_fixups` (mod.rs:774/816 → xasync.rs:553) always starts the async; provider `payload_provider` OP_DO_WORK (xasync.rs:509–519) runs the closure, **completes the block with 0x80072EFD, size 0** → `XAsyncComplete` (xasync.rs:279–327) posts the title's callback on PORT_COMPLETION. Test proves it: `token_requests_fail_offline_by_default` — `XAsyncGetStatus(b,true) == 0x80072EFD` (api.rs:1772–1792).
- When there is no Xbox Live a token request therefore goes nowhere: no HTTP is made by XCL, the async just fails like a console that cannot connect (config.rs:63–67; HANDOFF.md:1485–1493). The title's own POST `…CreateTicketXbl3` string we see in the log is the *url argument* printed by mod.rs:747.

## 2. Every wait the title can block on

| wait | file:line | can it hang forever? |
|---|---|---|
| `XAsyncGetStatus(b, wait=true)` | xasync.rs:336–341 — `cv.wait`, **no timeout** | only if OP_DO_WORK never runs, i.e. nobody dispatches the block's queue PORT_WORK (manual mode, taskqueue.rs:317–331) or all shared pool workers are themselves blocked (pool = 2–8 threads, taskqueue.rs:109–130). XCL itself always completes. |
| title callback on PORT_COMPLETION | xasync.rs:321–325 | needs the title pumping its queue; item exists. |
| `XTaskQueueDispatch(INFINITE)` | taskqueue.rs:359–380 | wakes on submit **and** terminate (tested, 953–991). No lost-wakeup. |
| terminated queue | XAsyncSchedule → E_ABORT → XAsyncBegin completes the block (xasync.rs:272–275, 254–257) | no hang. |
| `Sleep` | kernelx.rs:1589–1622; pass-through; `XCL_SLEEP_HOLD=0` disables the PSO-hold compensation | `Sleep(INFINITE)` passes straight through (1609) — a title-side park looks identical from outside. |
| sign-in / privilege gates | `XUserGetState` always SignedIn (mod.rs:611–617), `XUserCheckPrivilege` always true (api.rs:1297–1306), change-event never fires but nobody in XCL waits on it (mod.rs:666–672), resolve-UI/sign-out stubs complete at once (api.rs:958–999), sign-out deferral = explicit error (api.rs:983–988), XStore/XAppCapture refused with REGDB_E_CLASSNOTREG (api.rs:100, 271–274), unimplemented slots = E_NOTIMPL + log (api.rs:392–412) | **no gate in XCL waits on anything.** |

**Is there an XCL path that never signals? Proven no** for the auth path: the run itself shows token #11 *answered* at t=390.2 inside W2 (async completed, worker woke to log it). The 14–44 s retry cadence before t=163.9 and the lone #11 are the **title's own backoff**, and W2 contains zero `[STUB]/[WARN]/[ERROR]` (13-idle-windows.md §2) — the title never touched an unimplemented call; it sits in a wait of its own making. Only structural way to hang XCL's async: title blocks the very thread that pumps the async's manual queue — identical contract to real GDK, not an XCL bug.

## 3. Effective setting

`xbox_live_tokens` default false (config.rs:187), xcl.toml false → **false was effective**; proven directly by the log branch taken: "none: no Xbox Live (0x80072EFD)" (mod.rs:747). No `XCL_*` env changes it (only the toml key + test-only thread-local `TOKENS_HERE`, mod.rs:732–735). `XCL_NETWORK=0` (netoff.rs:62) is separate, off by default here, and irrelevant: the refusal happens before any socket. `sandbox_id = "RETAIL"` (config.rs:166, returned by mod.rs:246).

## 4. Minimal offline-correct behaviour — ranked by evidence

1. **Keep the fail-fast (current, evidence-backed as intentional)** — 0x80072EFD is what a console without XBL returns; Minecraft/Fortnite reach their offline paths with it (config.rs:63–67, HANDOFF.md:1485–1493). The token stage is already correct; the title's park is its own gate waiting for a *successful* CreateTicketXbl3 or for its server (title-side).
2. **`xbox_live_tokens = true`** — fully implemented local branch (xsign.rs:107–110, mod.rs:698–722), no patch needed. Caveat with evidence: it produced *retry-forever* in Minecraft because the backend then rejected the placeholder (HANDOFF.md:1488–1490) — it moves the failure from token to HTTP, it does not fake a server (HANDOFF.md:1492–1493: no TomBox-style local XBL). As a gate-release for Lockhart: **speculation**, no code promises it.
3. Anything stronger (fake CreateTicketXbl3 endpoint, fake entitlement) is **speculation against explicit project policy** — no TODO/stub exists for it; refusal is deliberate (api.rs:99–100 "deliberately unavailable (no fake licences)", mod.rs:950–951).

## 5. Decisive experiment (no build needed)

Run A (control, already have) + Run B: same launcher, xcl.toml `xbox_live_tokens = true`, plus `XCL_THREAD_DUMP_AT=210,330,450` (host.rs:98–110) and `XCL_ACTIVITY=1`.
- Proof-of-setting line: every token log flips to `XUser: token #… – XCL's local placeholder` (mod.rs:747).
- **Right guess**: presents survive t=180 (W2 gone or moved), and/or dumps show the parked main thread under the XUser/auth stack (waiting on XAsyncGetStatus or a title sign-in event).
- **Wrong guess**: W2 reappears at ≈t=180 with the same decay shape, token lines merely relabelled, retry count keeps growing while presents die → the gate is NOT the token stage; the dumps' main-thread RIP names the true wait (then read that stack against 13-idle-windows.md §6's pass criterion, and look at non-auth subsystems — the token refusal itself is provably answer-fast either way).

Note: pool starvation (taskqueue.rs:114) remains the one unproven XCL-side starvation vector if dumps show a blocked completion callback occupying pool workers — check dumps for `xcl-taskqueue-*` threads inside title callbacks.

## Wynik eksperymentu decydujacego (run xcl-lockhart-205725, 600 s)
- `xbox_live_tokens = true` weszlo w zycie: 0 linii `no Xbox Live`, 16 linii lokalnego
  placeholdera. Sciezka offline zostala tedy wykonana.
- Park WROCIL i PRZESUNAL SIE WCOSNIEJ: ostatnie niezerowe okno t=136 s (wczesniej ~180 s).
- Srednia fps spadla: 3137 prezentacji / 600 s = 5,2 fps (baseline false: 4775/600 = 8,0).
- WNIOSK: H-bramka-auth ODRZUCONA eksperymentalnie. Placeholder nie odblokowuje parku,
  a sam path tokena kosztuje. Konfiguracja przywr6cona do `xbox_live_tokens = false`.
- NOWY MOCNY DOWOD POSZYCIA: tu2 przed parkiem w tym runie widac t=136: 1079 drawow/klatke,
  430 dispatchy, 9 submitow/draw, frame dump 3020: non_dark 518094/518400 (99,9%).
  Tytul REALNIE rysuje scene przed parkiem. Park jest po wejsciu w swiat, nie przed.
