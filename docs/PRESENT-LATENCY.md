# Present, okno i opóźnienie: swap chain, DWM, wejście

Data: 2026-11-25. Autor: Agent F (present / window / swapchain / input latency).
Zakres: tylko warstwa prezentacji i okna w `D:\git\VItoriaBr` i
`D:\git\fxceless-victory`. Poza zakresem: deskryptory/heap, shadery, streaming,
VRAM, submit, audio (A–E, G–J). **Żadne repo nie zostało zmienione** — ten
dokument opisuje pomiar i patch do wykonania.

Wersje, na których pracowano (drzewa robocze, nie commity):

| repo | HEAD | niezacommitowane |
|---|---|---|
| `VItoriaBr` | `5a84eb4` | wybór adaptera high-performance w `crates/victory-gpu/src/host.rs` (+33/−1) |
| `fxceless-victory` | `085ee7c` | blok `VICTORY_FULLSCREEN` w `crates/victory-gpu/src/host.rs` (+26) |

> Uwaga przy rollbacku: w `VItoriaBr` w `host.rs` leży **cudza, niezacommitowana**
> zmiana (adapter). Nigdy nie rób `git checkout -- crates/victory-gpu/src/host.rs`
> — skasuje ją. Najpierw `git diff > …patch` albo commit adaptera.

## 0. TL;DR

1. **Present nie jest ścianą.** Nasza kopia do back buffera + `Present` to
   **~2 ms** (run 225: 2 ms z 136 ms klatki, `crates/victory-gpu/src/capture.rs:123-131`),
   a menu trzyma **29-31 fps / 32-34 ms** przy 3-14 draws (17 z 25 wierszy,
   12 dokładnie 30,0, w `benchmarks/vitoriabr-4060-parsed.csv`).
2. **DWM to 0,6–2,6%** obecnej klatki (jeden interwał kompozycji 16,7 ms przy
   60 Hz wobec 649–2705 ms). Przy celu 33,3 ms to jednak **do 50% budżetu** —
   warto usunąć, ale po naprawie CPU, nie zamiast niej.
3. **Patch `VICTORY_FULLSCREEN=1` jest w złym miejscu.** Zmienia tylko *zapasowe*
   okno (`make_window`), a nie okno gry; przy widocznym oknie gry **nigdy się nie
   wykonuje**. Ogłoszone „borderless = czarny ekran” nie zostało w ogóle
   przetestowane.
4. **Jeśli się wykona, psuje swap chain na stałe:** `CreateSwapChainForHwnd`
   wiąże łańcuch z HWND raz i nigdy nie da się go przepiąć; okno gry pojawia się
   potem nad popupem → czarny, nieodmalowany klient. Dodatkowo popup kradnie
   aktywację i jest tworzony z `GetSystemMetrics`, co na tym laptopie daje
   **2048×1280**, nie 2560×1600 (skalowanie 125%).
5. **Brak dowodu, że to on dał czarny ekran:** log z przebiegu pełnoekranowego
   (21:58) został skasowany przez launcher, a `fxceless` w tym samym buildzie
   robił TDR w 3D (log 21:07–21:11, `ERROR … host GPU device removed`).
6. **Poprawny borderless** = okno gry wybrane deterministycznie, zmiana stylu
   + `SetWindowPos` na monitor, **bez** `ResizeBuffers` przy 720p + `STRETCH`,
   `WM_SIZE` tylko dla własnej klasy, żadnego `SendMessage` z wątku prezentującego.
7. **Kolejność:** P1 pomiar (nic nie zmienia) → P2 borderless na oknie gry
   (domyślnie off) → P3 usunięcie martwego popupu → P4 opcjonalnie 1:1/DPI.
   Exclusive fullscreen **nie jest** celem: to tryb, który już zawiódł, a na tym
   laptopie dochodzi cross-adapter (dGPU renderuje, iGPU skanuje panel).

## 1. Co robi kod dziś

### 1.1 Łańcuch prezentacji

```
tytuł: IDXGISwapChain3::Present(plane)
  └─ HLE queue.rs:1016 present()
       ├─ queue.rs:1043  send_behind()      (VICTORY_ASYNC_PRESENT=1: wstaw Present do kolejki i wróć)
       ├─ queue.rs:1050-1063 settle_for_present() / release_held()
       ├─ queue.rs:1071  PresentLineUs     ← kolejki + settle (to jest koszt CPU klatki)
       └─ Host::present (host.rs:7736)
            ├─ host.rs:7739 PresentShowUs  ← nasza kopia + swapchain Present
            └─ host.rs:7856 p.swap_chain.Present(0, DXGI_PRESENT(0))
```

Liczniki (`crates/victory-gpu/src/framelog.rs:26-32`, opis w `:396-416`):

| licznik | gdzie | co obejmuje |
|---|---|---|
| `PresentUs` | `queue.rs:1027` | całe wywołanie Present tytułu: kolejki, settle, nasza kopia, `Present`, framelog |
| `PresentLineUs` | `queue.rs:1071` | kolejki + settle **przed** naszą kopią (koszt CPU klatki, nie DWM) |
| `PresentShowUs` | `host.rs:7739` | nasza kopia do back buffera + `IDXGISwapChain3::Present` |

Z `VICTORY_ASYNC_PRESENT=1` (`queue.rs:98-110`) `PresentUs` przestaje zawierać
kolejki i settle — Present wraca od razu, a kopię i `Present` robi nasz wątek.
Przy porównaniach trzeba trzymać ten przełącznik stały.

### 1.2 Swap chain

`host.rs:7865-7910` (`fxceless`: `:8146-8191`):

```rust
DXGI_SWAP_CHAIN_DESC1 {
    Width: width, Height: height,          // rozmiar TEKSTURY tytułu, nie okna
    Format: format,
    SampleDesc: { Count: 1, Quality: 0 },
    BufferUsage: DXGI_USAGE_RENDER_TARGET_OUTPUT,
    BufferCount: BUFFERS,                   // = 2 (host.rs:7411)
    SwapEffect: DXGI_SWAP_EFFECT_FLIP_DISCARD,
    ..Default::default()                    // Scaling = DXGI_SCALING_STRETCH, AlphaMode = UNSPECIFIED
}
```

- `CreateSwapChainForHwnd(&queue, hwnd, &desc, None, None)` — `host.rs:7893`.
  **HWND jest wiązany na całe życie łańcucha**; nie ma API, żeby go zmienić.
- `Scaling` jest wzięty z `Default` (STRETCH). To dlatego 720p w większym oknie
  w ogóle się pokazuje — i dlatego obraz jest miękki (widać to na
  `D:\Gry\fxceless-data\logs\screen-fx-windowed.png`).
- `Present(0, DXGI_PRESENT(0))` — bez vsync; wynik jest **odrzucany** (`let _ =`).
- Brak `DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT` i
  `SetMaximumFrameLatency` — czyli domyślna kolejka DWM (do 1 dodatkowej klatki).
- Brak obsługi `DXGI_STATUS_MODE_CHANGED` / `DXGI_ERROR_DEVICE_REMOVED`
  przy `Present` — przy zmianie trybu łańcuch nie jest odtwarzany.

### 1.3 Okno

`host.rs:7871-7874`:

```rust
let hwnd = match title_window() {
    Some(hwnd) => hwnd,        // okno gry (tworzone przez tytuł przez HLE)
    None => window(width, height)?,   // zapasowe okno runtime'u
};
```

- `title_window()` (`host.rs:7915-7934`, `fxceless:8196-8215`) bierze **pierwsze
  widoczne okno najwyższego poziomu naszego procesu w kolejności Z**. Nie sprawdza
  klasy, tytułu, rozmiaru ani tego, czy to okno gry. Nigdy później nie jest
  wołane — `presenter` powstaje raz.
- Okno gry tworzy tytuł: `victory-hle/src/modules/lifecycle.rs:62-85` przekazuje
  jego `CreateWindowExW` do systemu, a `fit()` (`:113-149`) zmniejsza okno
  większe niż obszar roboczy. Styl (pasek tytułu) pochodzi od tytułu — dlatego
  go widać.
- Zapasowe okno: `host.rs:8232-8249` (`window`), `:8251-8259` (`window_proc` =
  `DefWindowProcW`), `:8261-8297` (`make_window`): `WS_OVERLAPPEDWINDOW |
  WS_VISIBLE`, `AdjustWindowRect`, własny wątek + `pump()` (`:8299-8308`).
  Brak `WM_SIZE`, brak `WS_EX_NOACTIVATE` (okno z `WS_VISIBLE` normalnie
  aktywuje się przy tworzeniu).

### 1.4 Rozmiar i resize

`host.rs:7762-7787`: `ResizeBuffers` jest wołany **tylko wtedy, gdy zmieni się
rozmiar prezentowanej tekstury** (dynamiczna rozdzielczość tytułu), nie gdy
zmieni się okno. Wcześniej `settle_now(WHY_SYNC)` czeka na submity. Przy
niepowodzeniu: `tracing::warn!("swap chain not resized")` i `return None` —
czyli **klatka nie jest w ogóle pokazywana**. W zachowanych logach nie ma tego
warninga (log jest na poziomie `warn`, więc by się pojawił).

### 1.5 Podpis okna (FPS)

`Meter::frame` (`host.rs:7455-7468`) co sekundę dokleja
`" | VIctory {fps} fps {ms} ms/frame {draws} draws/frame"` do tytułu okna
(`host.rs:7695-7728`, format `:7704`) i robi to z osobnego wątku
(`SetWindowTextW` = `SendMessage` do wątku okna, więc prezentowanie nie czeka).
**Po usunięciu paska tytułu ten odczyt znika.** `fxceless` ma dodatkowo
`fpsbox` rysowany w rogu (`host.rs:8108`); `VItoriaBr` **nie ma** `fpsbox.rs`.

### 1.6 Wejście

`victory-hle/src/modules/gameinput.rs:1070-1089` — klawiatura przez
`GetAsyncKeyState` (tylko gdy foreground należy do naszego procesu, `:1241-1246`),
pady przez XInput. Próbkowanie odbywa się wtedy, gdy tytuł o to poprosi, czyli
**raz na jego klatkę**. Przy 649–2705 ms/klatkę opóźnienie wejścia to cała
klatka, niezależnie od DWM.

## 2. Dlaczego „720p → 1080p popup” dał czarny ekran

### 2.1 Co patch zrobił

Tylko `fxceless`, `crates/victory-gpu/src/host.rs:8640-8665` (w drzewie, nie w
HEAD):

```rust
if std::env::var_os("VICTORY_FULLSCREEN").is_some_and(|v| v != "0") {
    let screen_w = GetSystemMetrics(SM_CXSCREEN);   // 2048 tutaj, nie 2560
    let screen_h = GetSystemMetrics(SM_CYSCREEN);   // 1280 tutaj, nie 1600
    return CreateWindowExW(..., WS_POPUP | WS_VISIBLE, 0, 0, screen_w, screen_h, ...);
}
```

To jest gałąź w `make_window`, a `make_window` jest wołane **wyłącznie** przez
`window()`, gdy `title_window()` zwróci `None`. Swap chain nadal dostaje rozmiar
tekstury (720p) i `Scaling = STRETCH`.

### 2.2 Trzy strukturalne pułapki (wszystkie w kodzie, niezależne od wyniku testu)

1. **Gałąź jest martwa w normalnej kolejności startu.** Okno gry jest widoczne
   przed pierwszym Present (dowód: podpis `Americas` w pasku tytułu na
   `screen-fx-windowed.png` i `screen-e1e2.png` pochodzi z `InternalGetWindowText`
   **okna swap chainu**). Wtedy `title_window()` zwraca `Some`, `window()` nie
   jest wołane i `VICTORY_FULLSCREEN` nie robi nic. Czy w przebiegu 21:58 był
   wyścig (pierwszy Present przed pokazaniem okna gry) — **nie wiadomo**.
2. **Jeśli gałąź się wykona, swap chain zostaje na popupie na zawsze.**
   `CreateSwapChainForHwnd` (`:8174`) wiąże HWND; `presenter` nie jest nigdy
   odtwarzany. Okno gry powstaje później, jest wyżej w Z i dostaje aktywację →
   użytkownik widzi nieodmalowany czarny klient okna gry, a klatki idą do
   niewidocznego popupu. Dodatkowo `WS_VISIBLE` bez `WS_EX_NOACTIVATE` kradnie
   foreground, a tytuł może się wtedy zatrzymać (utrata `WM_ACTIVATEAPP`).
3. **Popup nie jest pełnoekranowy na tym laptopie.** Proces jest DPI-unaware
   (brak manifestu i brak `SetProcessDpiAwarenessContext`; w zbudowanym
   `target\release\victory.exe` nie ma ani `dpiAware`, ani `PerMonitor`, a w
   `AppCompatFlags\Layers` nie ma override'u; potwierdzone:
   `SM_CXSCREEN` = 2048×1280 przy panelu 2560×1600 i skali 125%, a
   `MonitorFromPoint` + `GetMonitorInfo` w tym samym procesie zwracają
   `rcMonitor` 2048×1280 i `rcWork` 2048×1232 — czyli również współrzędne
   wirtualne). `GetSystemMetrics` daje więc 2048×1280 — nie 1920×1080, jak
   zapisano w `docs/EXPERIMENTS-2026-11-25.md:45`. DWM skaluje to bitmapowo o 1,25×.

### 2.3 Co jest udowodnione, a co nie

- **Udowodnione:** patch jest nieosiągalny, gdy okno gry jest widoczne; jeśli
  się wykona, wiąże swap chain z popupem bezpowrotnie; rozmiar popupu jest
  liczony z DPI-virtualizowanych metryk; wynik `Present` jest wyrzucany.
- **Nieudowodnione:** że to ten patch dał czarny ekran 21:58. Launcher kasuje
  poprzedni log przy starcie (`Launch-Fxceless.ps1:54`), a log 21:07–21:11 kończy
  się `ERROR victory_gpu::host: host GPU device removed` (TDR w 3D). Przebieg
  pełnoekranowy był też uruchomiony z `VICTORY_LOG=warn` (`:15`), więc nawet
  `info!` z gałęzi fullscreen (`:8646-8650`) był wyciszony — **nie ma dowodu, że
  gałąź w ogóle się wykonała**.
- **Wykluczone (dla zachowanych logów):** błąd `ResizeBuffers` / `no swap chain`
  — nie ma tych warningów. Ale log z samego przebiegu pełnoekranowego nie istnieje.

### 2.4 Jak to rozstrzygnąć jednym uruchomieniem

1. Zostaw `VICTORY_LOG=info` (P1) i **skopiuj log przed następnym startem**.
2. W menu (29-31 fps, 3-14 draws - tam czarny ekran nie może być TDR) ustaw
   `VICTORY_BORDERLESS=1`. Oczekiwane: brak paska, obraz nie-czarny, 29-31 fps.
3. W logu sprawdź `presenting to a window class=… title=… window=… client=…` —
   tytuł musi być oknem gry (`Americas`), a nie `VIctory`.
4. Dopiero potem wejdź w 3D.

## 3. Ile kosztuje present i DWM (liczby)

### 3.1 Co mamy w logach

Zachowane logi (`D:\Gry\VItoriaBr-data\logs\game-stderr.log`,
`D:\Gry\fxceless-data\logs\game-stderr.log`) są na poziomie `warn`
(`Launch-VItoriaBr.ps1:41`, `Launch-Fxceless.ps1:15`), a frame log jest wyłączony
(`Launch-VItoriaBr.ps1:66`; `framelog.rs:267-273` — w release tylko
`VICTORY_FRAME_LOG=1`). **Dlatego w logach nie ma ani jednego `PresentUs` /
`PresentShowUs`.** Są tylko `fps, ms/frame, draws` z paska tytułu.

### 3.2 Liczby, które mamy

| pozycja | wartość | źródło |
|---|---:|---|
| klatka 3D (ten laptop) | 649–2705 ms | `EXPERIMENTS-2026-11-25.md`, `PERF-DIAGNOSIS:01` |
| nasza kopia + `Present` | **2 ms** (1,5% z 136 ms) | `crates/victory-gpu/src/capture.rs:123-131` (run 225, mocniejsza karta) |
| `PresentUs` z kolejkami | 77 ms z 136 ms | `crates/victory-gpu/src/queue.rs:78-80` (run 225) |
| menu | 29-31 fps / 32-34 ms / 3-14 draws (12× 30,0) | `benchmarks/vitoriabr-4060-parsed.csv` (17 z 25 wierszy ≥ 29,5) |
| interwał kompozycji @60 Hz | 16,7 ms | 2,6% z 649 ms, 0,62% z 2705 ms |
| interwał kompozycji @240 Hz | 4,2 ms | 0,64% / 0,15%; `Win32_VideoController`: 2560×1600@240 (lista trybów monitora podaje też 60 Hz) |
| próbkowanie klawiatury | 1 klatka = 649–2705 ms | `gameinput.rs:1169-1175` |

Przy celu 33,3 ms: 16,7 ms to **50% budżetu**, 4,2 ms to 12,5%. To jest właściwy
powód, żeby zajmować się DWM — **opóźnienie**, nie przepustowość.

### 3.3 Czego logi nie mówią

- **Czasu DWM nie ma nigdzie.** `PresentShowUs` kończy się na powrocie z
  `Present`, czyli przed kompozycją i skanoutem. To, co DWM dokłada, to
  *opóźnienie wyświetlenia*, nie czas CPU.
- **Cross-adapter:** panel jest na Radeon 780M (`Win32_VideoController`:
  2560×1600), a gra chodzi na RTX 4060 (`GpuPreference=2` w rejestrze). Każda
  klatka przechodzi dGPU → shared → iGPU. To dodatkowa kopia pełnej klatki i
  powód, dla którego „independent flip” (direct scanout) jest tu mało realny przy
  720p + STRETCH.
- **Kolejka flip:** `BUFFERS = 2`, brak waitable object → do 1 dodatkowej klatki
  opóźnienia w kolejce DWM. Przy 30 fps to 33 ms; przy 1 fps to 1 s, ale i tak
  zdominowane przez samą klatkę.

### 3.4 Wniosek

- **CPU-side present (nasza kopia + `Present`): ~2 ms, 0,07–0,31% klatki
  649–2705 ms.** Nie warto go „optymalizować” przed CPU.
- **`PresentUs` = 77 ms to kolejki i settle, nie swap chain.** To koszt, którym
  zajmują się inne zakresy (submit/kolejki), nie ten dokument.
- **DWM: 0,6–2,6% teraz, do 50% budżetu przy 33,3 ms.** Usunięcie paska i
  kompozycji to tania, izolowana zmiana, która nie dotyka gorącej ścieżki — ale
  nie zbliży 1–2 fps do 30.

## 4. Co potrzebuje poprawny borderless

1. **Wybierz okno gry, nie „pierwsze widoczne”.** `title_window()` musi
   preferować okno, którego klasa/tytuł pochodzi od tytułu, i mieć rozmiar
   klienta > 0. Jeśli nie ma takiego — **nie twórz zapasowego**; odłóż Present
   (albo zachowaj dzisiejsze okno zapasowe tylko wtedy, gdy tytuł naprawdę nie
   ma okna). Popup nigdy nie może przejąć swap chainu.
2. **`ResizeBuffers`:** tylko na wątku prezentującym, bez zajętego back buffera i
   bez `Present` w locie; dziś robi to `host.rs:7762-7787` przy zmianie rozmiaru
   *tekstury*. Przy 720p + `STRETCH` **nie jest potrzebny** po zdjęciu paska —
   klient rośnie, DXGI rozciąga. Przy 1:1 (`SCALING_NONE`) jest obowiązkowy, z
   rozmiarem **klienta**, nie okna. Nigdy z `WndProc`/`WM_SIZE` okna gry — to
   wątek tytułu i grozi `DXGI_ERROR_INVALID_CALL` albo blokadą.
3. **`DXGI_SCALING`:** ustaw jawnie w `DXGI_SWAP_CHAIN_DESC1`. `STRETCH` = szybka
   ścieżka 720p (GPU skaluje); `NONE` = 1:1, tylko gdy bufory == klient. Ustaw
   też jawnie `AlphaMode: DXGI_ALPHA_MODE_IGNORE` i `Flags: 0` — `..Default::default()`
   to właśnie sposób, w jaki dostaliśmy niejawną politykę.
4. **`WM_SIZE`:** dla **własnej** klasy (`window_proc`, dziś `DefWindowProcW`)
   zapisz nowy rozmiar klienta i pozwól podnieść go wątkowi prezentującemu.
   Okno gry dostaje `WM_SIZE` samo i tytuł je obsługuje — nie dokładaj drugiego
   handlera. Dla przeniesienia na inny monitor: `WM_DISPLAYCHANGE` /
   `WM_DPICHANGED` (przy zmianie DPI).
5. **`ShowWindow`:** po zmianie stylu
   `SetWindowPos(hwnd, None, r.left, r.top, w, h, SWP_FRAMECHANGED | SWP_NOZORDER |
   SWP_NOACTIVATE | SWP_SHOWWINDOW)`. Nie `SW_MAXIMIZE` na `WS_POPUP`. Nie wołaj
   `ShowWindow`/`SetWindowLongPtrW` z wątku prezentującego: one **wysyłają**
   `WM_STYLECHANGING`/`WM_WINDOWPOSCHANGING` do wątku okna, który może być w
   środku klatki trwającej sekundy.
6. **Styl:** `GWL_STYLE & ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX |
   WS_MAXIMIZEBOX | WS_SYSMENU) | WS_POPUP | WS_VISIBLE`. Zachowaj
   `WS_CLIPCHILDREN`/`WS_CLIPSIBLINGS`, jeśli tytuł je ustawił. `WS_EX_NOACTIVATE`
   nie jest potrzebny na oknie gry (nie tworzymy go), ale jest konieczny, gdyby
   zapasowe okno zostało.
7. **Monitor, nie ekran:** `MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)` +
   `GetMonitorInfoW` → `rcMonitor`. `GetSystemMetrics(SM_CXSCREEN)` jest złe na
   multi-monitorze i przy DPI-virtualizacji (tutaj: 2048×1280 zamiast 2560×1600);
   `GetMonitorInfo` w procesie DPI-unaware zwraca **te same** współrzędne
   wirtualne (sprawdzone: `rcMonitor` 2048×1280, `rcWork` 2048×1232), więc jest
   z nimi spójne. Nie mieszaj go z fizycznymi pikselami.
8. **DPI:** albo zostaw proces DPI-unaware i używaj **spójnie** współrzędnych
   wirtualnych (`GetMonitorInfo` też je zwraca), albo ustaw
   `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` **przed** pierwszym
   oknem (wymaga `Win32_UI_HiDpi` w features). Nie mieszaj obu.
9. **Fokus i odczyt FPS:** nie odbieraj aktywacji oknu gry; po zdjęciu paska
   `VItoriaBr` traci jedyny odczyt fps — na czas testów ustaw `VICTORY_LOG=info`
   albo dodaj `fpsbox` (jak w `fxceless`).
10. **Nie dodawaj buforów.** `BUFFERS = 2` to dobra wartość dla opóźnienia; 3
    bufory zwiększą je o co najmniej klatkę.

## 5. Plan patchu (P0–P5)

Wszystko poza P1 jest **domyślnie wyłączone** zmienną środowiskową. Rollback =
`VICTORY_BORDERLESS=0`, bez cofania kodu.

### P0 — punkt odniesienia (bez zmian w kodzie)

1. Skopiuj launcher i zmień **dwie** linie w kopii (oryginał zostaje):
   `Launch-VItoriaBr.ps1:41` → `$env:VICTORY_LOG = 'info'`,
   `:66` → `$env:VICTORY_FRAME_LOG = '1'`.
   ```powershell
   Copy-Item D:\Gry\VItoriaBr-data\Launch-VItoriaBr.ps1 D:\Gry\VItoriaBr-data\Launch-VItoriaBr-Present.ps1
   ```
2. Uruchom `-Performance` (720p, ambient 0) i wejdź do menu.
   Uwaga: ten profil ustawia też `VICTORY_ASYNC_PRESENT=1` (`Launch-VItoriaBr.ps1:65`),
   więc `PresentUs` nie zawiera wtedy kolejek — porównuj `PresentShowUs` i
   `PresentLineUs`, nie sam `PresentUs`.
3. Wyciągnij liczby:
   ```powershell
   $log='D:\Gry\VItoriaBr-data\logs\game-stderr.log'
   $e=[char]27
   Get-Content $log | ForEach-Object { $_ -replace "$e\[[0-9;]*m",'' } |
     Select-String -Pattern 'frame times:|usual frame|long frame .*in the present call|presenting to a window|swap chain' |
     Set-Content D:\Gry\VItoriaBr-data\logs\present-extract.txt
   ```
   W `present-extract.txt` szukaj:
   `in the present call 77.0 (lines and settling 75.0, copy and show 2.0)`.
   To jest podział, którego brakuje w logach.
4. Zapisz `ms_p50`, `ms_p95` z `python tools/bench/parse_victory_log.py …`
   (nie zmieniaj narzędzi — to zakres innego agenta).

**Gate:** `copy and show` < 5 ms, brak `swap chain not resized`, brak
`device removed`.

### P1 — diagnostyka (bez zmiany zachowania)

W `presenter()` (`host.rs:7865`, `fxceless:8146`), przed
`CreateSwapChainForHwnd`, zaloguj raz:

```rust
// SAFETY: a live window; the calls only read.
let (class, text, window, client) = unsafe {
    let mut class = [0u16; 128];
    let n = GetClassNameW(hwnd, &mut class).max(0) as usize;
    let mut text = [0u16; 256];
    let t = GetWindowTextW(hwnd, &mut text).max(0) as usize;
    let mut window = RECT::default();
    let mut client = RECT::default();
    let _ = GetWindowRect(hwnd, &mut window);
    let _ = GetClientRect(hwnd, &mut client);
    (
        String::from_utf16_lossy(&class[..n]),
        String::from_utf16_lossy(&text[..t]),
        window,
        client,
    )
};
tracing::info!(
    ?hwnd,
    class = %class,
    title = %text,
    window = %format_args!("{}x{} at ({}, {})", window.right - window.left, window.bottom - window.top, window.left, window.top),
    client = %format_args!("{}x{}", client.right, client.bottom),
    style = %format_args!("{:#x}", unsafe { GetWindowLongPtrW(hwnd, GWL_STYLE) } as u32),
    ex_style = %format_args!("{:#x}", unsafe { GetWindowLongPtrW(hwnd, GWL_EXSTYLE) } as u32),
    foreground = unsafe { GetForegroundWindow() } == hwnd,
    swap = %format_args!("{width}x{height} {:?}", format),
    "presenting to a window"
);
```

Oraz, przy `Present` (`host.rs:7856`), zaloguj błąd (raz na sekundę, nie na
klatkę):

```rust
let presented = p.swap_chain.Present(0, DXGI_PRESENT(0));
if let Err(e) = &presented {
    static LAST: std::sync::Mutex<Option<std::time::Instant>> = std::sync::Mutex::new(None);
    // …throttle 1 s…
    tracing::warn!(error = %e, frame, "present failed");
}
```

Uwaga: `windows-rs` zwraca `Result<()>`, więc **pozytywny** status
`DXGI_STATUS_OCCLUDED` (0x087A0001) nie jest widoczny jako błąd. Zasłonięte okno
trzeba wykrywać przez `IsIconic`/`GetForegroundWindow`, a `MODE_CHANGED` wymaga
odtworzenia łańcucha.

**Gate:** w logu jest dokładnie jeden `presenting to a window` z tytułem okna gry
(`Americas`) i `client` równym faktycznemu obszarowi klienta; żadnych `present failed`.

### P2 — borderless na oknie gry (`VICTORY_BORDERLESS=1`)

W `host.rs` (VItoriaBr; analogicznie `fxceless`):

```rust
/// `VICTORY_BORDERLESS=1`: the title's own window, without its frame, over the
/// monitor it is on. Off by default; never creates a window.
fn borderless() -> bool {
    static ON: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *ON.get_or_init(|| std::env::var_os("VICTORY_BORDERLESS").is_some_and(|v| v != "0"))
}

/// Not on the presenting thread: SetWindowLongPtrW and SetWindowPos send to the
/// window's thread, which may be inside a frame that lasts seconds. The swap
/// chain is bound to the window, not its style, so nothing here touches it.
fn borderless_soon(hwnd: HWND) {
    let _ = std::thread::Builder::new()
        .name("victory-borderless".into())
        .spawn(move || {
            // SAFETY: a live window of this process; style and placement only.
            unsafe {
                let mut info = MONITORINFO {
                    cbSize: size_of::<MONITORINFO>() as u32,
                    ..Default::default()
                };
                let monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
                if !GetMonitorInfoW(monitor, &mut info).as_bool() {
                    tracing::warn!("borderless: no monitor for the window");
                    return;
                }
                let style = GetWindowLongPtrW(hwnd, GWL_STYLE) as u32;
                let bare = style & !(WS_CAPTION.0 | WS_THICKFRAME.0
                    | WS_MINIMIZEBOX.0 | WS_MAXIMIZEBOX.0 | WS_SYSMENU.0);
                SetWindowLongPtrW(hwnd, GWL_STYLE, (bare | WS_POPUP.0 | WS_VISIBLE.0) as isize);
                let r = info.rcMonitor;
                let placed = SetWindowPos(
                    hwnd, None, r.left, r.top, r.right - r.left, r.bottom - r.top,
                    SWP_FRAMECHANGED | SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                );
                tracing::info!(ok = placed.is_ok(), x = r.left, y = r.top,
                    w = r.right - r.left, h = r.bottom - r.top,
                    "borderless: the title's window over its monitor (VICTORY_BORDERLESS=1)");
            }
        });
}
```

W `presenter()`:

```rust
let title = title_window();
let hwnd = match title {
    Some(hwnd) => hwnd,
    None => window(width, height)?,
};
// … CreateSwapChainForHwnd …
if borderless() && title.is_some() {
    borderless_soon(hwnd);
}
```

Sygnatury `windows` 0.62: `SetWindowPos(hwnd, Option<HWND>, …)`,
`GetWindowLongPtrW` zwraca `isize`, `WS_*.0` to `u32`. `MONITORINFO` i
`GetMonitorInfoW` są w `Win32::Graphics::Gdi` (feature już włączony w
`crates/victory-gpu/Cargo.toml`).

**Czego P2 NIE robi:** nie woła `ResizeBuffers`, nie zmienia `Scaling`, nie
tworzy okna, nie zmienia DPI, nie dotyka `Present`. Dlatego nie może zepsuć
obrazu - bo tylko zmienia obszar klienta, a DXGI go rozciąga.

**Gate:** menu 29-31 fps (12× 30,0), obraz nie-czarny, brak paska, `GetWindowRect` ==
`rcMonitor`, brak nowych warningów, klawiatura działa.

### P3 — usuń martwy popup

W `fxceless` usuń blok `:8640-8665` (albo zamień na `tracing::warn!` „ignored;
use VICTORY_BORDERLESS=1”, żeby stare skrypty nie dawały czarnego ekranu).
W `VItoriaBr` nie ma czego usuwać. **Nie** dodawaj nowego okna zapasowego.

**Gate:** `rg VICTORY_FULLSCREEN D:\git\fxceless-victory` → tylko warning.

### P4 — opcjonalnie 1:1 (1080p) i DPI

- `VICTORY_PRESENT_BUFFERS=client`: przy każdej zmianie klienta `ResizeBuffers`
  do rozmiaru klienta i `Scaling: DXGI_SCALING_NONE`. Oczekiwane: wyraźniej,
  ale **wolniej** (więcej pracy GPU) — na tym laptopie raczej odrzucić.
- `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` w
  `apps/victory/src/main.rs` przed jakimkolwiek oknem (dodaj `Win32_UI_HiDpi` do
  features). Oczekiwane: brak bitmapowego skalowania 1,25×, ostrzejszy obraz;
  **testuj osobno**, bo zmienia wyniki `fit()` i `GetSystemMetrics`.

### P5 — opcjonalnie niskie opóźnienie kolejki

`DXGI_SWAP_CHAIN_FLAG_FRAME_LATENCY_WAITABLE_OBJECT` +
`SetMaximumFrameLatency(1)` + czekanie na waitable przed rysowaniem. Przy 1 fps
**nie da nic** (kolejka nigdy nie jest pełna), a może zwiększyć stall CPU; ma
sens dopiero przy 30 fps. Zmierzyć PresentMonem, nie „na oko”.

**Czego nie robimy:** `SetFullscreenState(TRUE)` (exclusive). To tryb, który już
zawiódł, wymaga zmiany trybu i na tym laptopie przechodzi przez iGPU; Windows 10+
i tak może go zamienić na borderless (fullscreen optimizations). Nie jest
potrzebny do 30 fps.

## 6. Ryzyka

| ryzyko | prawd. | wpływ | mitygacja |
|---|---|---|---|
| swap chain znowu na złym oknie | średnie, jeśli zostanie fallback | czarny ekran | P1 log HWND; P2 tylko `title.is_some()`; P3 usuwa popup |
| TDR w 3D (fxceless, agresywny profil) | średnie | czarny ekran bez związku z oknem | profil stabilny (relay=0, bez gather/join, 4096/768), limit 150 s, log przed startem |
| blokada wątku tytułu przez `SetWindowLongPtrW`/`SetWindowPos` | średnie | przestój 1 klatki przy starcie | osobny wątek, bez czekania (P2) |
| utrata odczytu fps po zdjęciu paska | pewne w `VItoriaBr` | brak pomiaru | `VICTORY_LOG=info` lub `fpsbox` |
| rozmycie 720p → 2560×1600 | pewne | wygląd | oczekiwane; P4 dopiero po pomiarze |
| okno nie pokrywa panelu (DPI 125%) | niskie | pasek pulpitu | `rcMonitor`, nie `SM_CXSCREEN` |
| Alt+Tab/taskbar inaczej | pewne | kosmetyka | `WS_POPUP` bez `WS_EX_TOOLWINDOW` zostaje w Alt+Tab |
| utrata niezacommitowanej zmiany adaptera | niskie | poważny | patch/commit przed pracą (nagłówek) |

## 7. Testy

| # | scenariusz | komenda / ustawienie | pass |
|---|---|---|---|
| T0 | menu, windowed, info | `Launch-VItoriaBr-Present.ps1 -Performance` | 29-31 fps (12× 30,0), `copy and show` < 5 ms, brak warningów |
| T1 | menu, borderless | `$env:VICTORY_BORDERLESS='1'` | brak paska, obraz nie-czarny, 29-31 fps, `GetWindowRect` == monitor |
| T2 | 3D, windowed vs borderless, 3 przebiegi | ten sam save/kamera | p50 różni się < 1%; brak TDR |
| T3 | Alt+Tab, powrót, klawiatura | ręcznie | obraz wraca, klawisze działają, brak `present failed` |
| T4 | 1:1 1080p (P4) | `VICTORY_PRESENT_BUFFERS=client` | obraz 1:1, fps nie gorszy niż −10% (inaczej odrzucić) |
| T5 | soak 10 min w 3D | stabilny profil | brak `device removed`, VRAM < 7,8 GB |
| T6 | drugi monitor / 125% | jeśli dostępny | okno na monitorze, brak rozjechania współrzędnych |

Screenshot do weryfikacji paska: `Win+PrintScreen` → `%USERPROFILE%\Pictures\Screenshots`.
Rozmiar okna: `GetWindowRect` w P1 (log), nie z obrazka.

**PresentMon** (nie ma go na tej maszynie - `wpr.exe` jest, PresentMon nie):
po instalacji uruchom na 30 s i sprawdź `PresentMode` oraz `msUntilDisplayed`:

```powershell
PresentMon.exe --process_name game_scarlett_master.exe --output_file D:\Gry\VItoriaBr-data\logs\present.csv --timed 30
# składnia zależy od wersji; potwierdź --help
```

Oczekiwane przy 720p + STRETCH: `Composed: Flip` (nie `Hardware: Independent
Flip`). To jedyny sposób, żeby zmierzyć DWM, a nie nasz `Present`.

**Rollback:** `$env:VICTORY_BORDERLESS='0'` (kod zostaje). Przy cofaniu kodu:
najpierw `git -C D:\git\VItoriaBr diff > D:\Gry\VItoriaBr-data\host-before-present.patch`,
potem commit adaptera, dopiero potem revert borderless.

## 8. Czego ten dokument nie twierdzi

- Nie twierdzi, że borderless da 30 fps. Daje ostrzejszy/pełny obraz i usuwa
  jeden interwał kompozycji z opóźnienia; nie rusza 649–2705 ms CPU.
- Nie twierdzi, że DWM jest przyczyną „visual lag”. Przy 1–2 fps lag to cała
  klatka (649–2705 ms), ~40–160× interwał DWM.
- Nie zmierzył DWM na tej maszynie (brak PresentMon; logi na `warn`).
- „2 ms” pochodzi z runu 225 na mocniejszej karcie; na tym laptopie to nadal
  jeden submit + `Present`, ale wymaga potwierdzenia w P0/P1.
- Nie rozstrzyga, co dało czarny ekran 21:58 — log tego przebiegu nie istnieje.
  Podaje dwie hipotezy i test, który je rozdziela.
