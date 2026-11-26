# Borderless fullscreen i cap 120 Hz: patch, weryfikacja, rollback

Data: 2026-11-25. Autor: Agent F (present/cap verification).
Zakres: (a) patch `VICTORY_BORDERLESS=1` w `D:\git\VItoriaBr-opt\crates\victory-gpu\src\host.rs`,
(b) `VICTORY_REFRESH=120` w `dxgi.rs` (w tym samym worktree), (c) patch użytkownika w
`D:\Gry\VItoriaBr-data\data\7952987A\storage\settings\settings.xml` (backup
`settings.xml.cap-bak`). Poza zakresem: shadery, streaming, submit, audio.
**Nic nie było uruchamiane; żadne repo nie zostało zmienione przez ten dokument**
(przegląd kodu w `VItoriaBr-opt` w stanie, jaki zostawił orchestrator).

Werdykt w skrócie: patch borderless jest poprawny strukturalnie (dobre okno, dobry
styl, `SWP_ASYNCWINDOWPOS`, `SWP_FRAMECHANGED`), ale **rozmiar okna będzie
zwirtualizowany (2048×1280 zamiast 2560×1600)** — proces nie ma DPI-awareness — a
konfiguracja wymaga jeszcze **`VICTORY_DISPLAY_MODE=1280x720`**, bo `modes()` raportuje
3840×2160 i gra może nie znaleźć trybu 1280×720@120. Patch settings.xml wygląda na
plauzibilny; `frameRateLimit=0` prawie na pewno znaczy „bez limitu”, a najgorszy
scenariusz to cichy cap 30, nie crash.

## 0. TL;DR

1. **Borderless (host.rs):** 5 defektów, żaden nie blokuje testu. Najważniejszy: proces
   jest DPI-unaware (brak manifestu, brak wywołania), więc `GetSystemMetrics` daje
   **2048×1280 na panelu 2560×1600@125%** i DWM bitmapowo skaluje okno — ekran
   zakryty, obraz miękki (podwójne skalowanie 1280×720→2048×1280→2560×1600).
   Poprawka: `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` w
   `apps/victory/src/main.rs`, zanim powstanie jakiekolwiek okno, włączany tylko
   przy `VICTORY_BORDERLESS=1`.
2. **dxgi.rs `modes()`:** zgłasza **jeden** tryb o rozmiarze `display_size()`
   (domyślnie 3840×2160). Przy `resolutionFullscreen=1280x720` gra może nie znaleźć
   swojego trybu. **Obowiązkowo w zestawie env:** `VICTORY_REFRESH=120` **i**
   `VICTORY_DISPLAY_MODE=1280x720`.
3. **settings.xml:** wszystkie wartości w plauzibilnych domenach RAGE. Gra sama
   zapisała wcześniej `frameRateLimit=30` (wartość liczbowa, nie indeks) — `0` to
   niemal na pewno „bez limitu”. Jeśli jednak 0 jest niepoprawne: clamp do 30
   (wykrywalny), ignorowanie ustawienia (pożądane) albo reset sekcji `<video>`
   (wykrywalny po zakończeniu — gra nadpisuje settings.xml przy wyjściu).
   Drabinka awaryjna: **0 → 60 → 120 → 30**.
4. **Uwaga przy patchu XML:** patch dodał BOM na początku pliku. RAGE zwykle go
   toleruje; przy objawach nieparsowania ustawień przepisać bez BOM.
5. **Protokół uruchomienia:** kliknij okno gry **zanim** naciśniesz Enter —
   `SWP_NOACTIVATE` celowo nie kradnie fokusa, a Enter trafia do okna z fokusem
   (terminal/launcher, jeśli gra nie była kliknięta).

## 1. Przegląd patcha borderless (`host.rs`)

Miejsca: `borderless()` host.rs:7927-7965, wywołanie w `presenter()` host.rs:7873-7882,
wybór okna `title_window()` host.rs:7967-7986, okno tytułu tworzone przez HLE
(`crates/victory-hle/src/modules/lifecycle.rs:62-79`, hook wndproc :165-195).

### 1.1 Defekty i poprawki

| # | Miejsce | Defekt | Poprawka / obejście |
|---|---|---|---|
| D1 | host.rs:7943-7944 | Proces DPI-unaware → `GetSystemMetrics` zwraca **2048×1280** na 2560×1600@125%; `SetWindowPos` daje okno 2048×1280 w jednostkach wirtualnych, DWM bitmapowo je rozciąga. Ekran zakryty, ale podwójne skalowanie i miękki obraz. | `SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)` na starcie procesu (p. 1.2). Bez tego: oczekiwany log „borderless fullscreen applied … width=2048 height=1280” — to jest dymiący dowód. |
| D2 | host.rs:7929, presenter 7877-7882 | Wątek pomocniczy jest odpięty (`std::thread::spawn` bez join); zmiana stylu może dolecieć **po** `CreateSwapChainForHwnd` i pierwszym Present → błysk okna z ramką, potem skok do fullscreen. `SWP_ASYNCWINDOWPOS` sprawia, że wątek się nie blokuje na tytule, więc join jest bezpieczny. | `borderless()` niech zwraca `JoinHandle`; `presenter()` robi join przed utworzeniem swap chaina. Kosmetyczne — nie blokuje testu. |
| D3 | host.rs:7967-7986 | `title_window()` bierze **pierwsze** widoczne okno procesu (EnumWindows idzie topmost-first). Dialog (xgameui) widoczny przed głównym oknem → borderless na złym HWND. | Wybierać największe (pole) widoczne okno procesu zamiast pierwszego; ewentualnie filtr po klasie okna z `lifecycle.rs`. Niskie prawdopodobieństwo, tania poprawka. |
| D4 | host.rs:7945-7957 | Jednorazowe ustawienie. Jeśli tytuł sam później wywoła `SetWindowPos` (zmiana trybu, przywrócenie własnego prostokąta), fullscreen znika bez ponownego przyłożenia. | Dokumentuję jako ograniczenie. Dla tego testu (stałe 1280×720, brak zmiany trybu) OK. Ewentualnie asercja w `window_proc` (lifecycle.rs:165) na `WM_WINDOWPOSCHANGING` — ryzyko walki z tytułem, nie teraz. |
| D5 | host.rs:7958-7962 | `let _ = SetWindowPos(...)` — błąd ignorowany, a log i tak mówi „applied”. | Logować wynik. Kosmetyczne. |
| D6 | host.rs:7943-7944 | `SM_CXSCREEN/SM_CYSCREEN` to **monitor główny**; okno na drugim monitorze zostanie przeniesione na główny. | `MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)` + `GetMonitorInfoW` → `rcMonitor` (przy PMv2 daje fizyczne piksele). Razem z D1. |

Co jest **dobrze** w tym patchu (potwierdzam, zgodnie z zaleceniami z PRESENT-LATENCY.md):

- celuje w **okno tytułu**, nie w zapasowe okno hosta (stary `VICTORY_FULLSCREEN` celował w złe okno);
- maska stylu czyści `WS_CAPTION|WS_THICKFRAME|WS_MINIMIZEBOX|WS_MAXIMIZEBOX|WS_SYSMENU`
  i ustawia `WS_POPUP` — poprawny przepis na borderless; `GetWindowLongW/SetWindowLongW`
  na `GWL_STYLE` z innego wątku jest legalne (zakaz dotyczy tylko `GWL_WNDPROC`);
- `SWP_FRAMECHANGED` jest (wymagane po zmianie stylu), `SWP_NOACTIVATE` (nie kradnie
  fokusa), `SWP_SHOWWINDOW`, `SWP_NOZORDER`;
- **brak `ResizeBuffers`** — flip-model sam skaluje 1280×720 do klienta okna (efekt STRETCH);
- `borderless()` wywoływane tylko w gałęzi „okno tytułu istnieje”; gdy go nie ma,
  zapasowe okno hosta zostaje bez zmian (poprawnie);
- brak `SendMessage` z wątku prezentującego (taki był grzech starych wersji).

### 1.2 Umiejscowienie `SetProcessDpiAwarenessContext` i ryzyka

**Gdzie:** `apps/victory/src/main.rs::main()` (linia 147), na samej górze, **zanim**
wykona się `Command::Run` → `run::run(...)` (main.rs:197). Okno tytułu powstaje w
`lifecycle.rs::CreateWindowExW` z wątku tytułu — kontekst DPI musi być ustawiony
wcześniej (po utworzeniu okna zmiana jest ignorowana). Konkretnie:

```rust
// main.rs, przed obsługą Command::Run; tylko gdy zażądano borderless
if std::env::var_os("VICTORY_BORDERLESS").is_some_and(|v| v != "0") {
    use windows::Win32::UI::HiDpi::{
        SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
    };
    let ok = unsafe {
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
    };
    // ok: BOOL; przy niepowodzeniu (stary Windows) borderless nadal działa, tylko miękko
}
```

**Ryzyka:**

1. **Zmiana przestrzeni współrzędnych dla całego procesu** — wszystkie okna (w tym
   zapasowe okno hosta, host.rs:8284) przechodzą na fizyczne piksele. Zapasowe okno
   liczy rozmiar z `AdjustWindowRect` — skaluje się poprawnie.
2. **Logika tytułu oparta o metryki ekranu** — tytuł konsolowy renderuje do stałego
   backbuffera (1280×720), więc `GetSystemMetrics` u niego to zwykle tylko rozmiar
   okna; ale **wejście (kursor)** musi zostać sprawdzone po włączeniu — jeśli HLE
   tłumaczy współrzędne ekranowe, zmiana 2048×1280 → 2560×1600 może przesunąć
   kursor. Weryfikacja: pozycja kursora w menu po kliknięciu.
3. **PMv2 i `WM_DPICHANGED`** przy przenoszeniu między monitorami — nieobsłużone
   kończy się bitmapowym skalowaniem (akceptowalne; używamy tylko monitora głównego).
4. **Wsparcie systemowe** — `SetProcessDpiAwarenessContext` wymaga Win10 1703+;
   D3D12 i tak wymaga Win10, więc ryzyko zerowe; przy niepowodzeniu wywołania
   (zwraca 0) patch borderless działa dalej — tylko obraz miękki (stan dzisiejszy).
5. **Ograniczenie do `VICTORY_BORDERLESS=1`** (opt-in) — normalne przebiegi
   (translate/warm/inne tytuły) zachowują dzisiejsze zachowanie DPI-unaware.
   **Nie** ustawiać globalnie bez pomiaru.

## 2. Przegląd `dxgi.rs` — `modes()` (dxgi.rs:247-288)

| # | Miejsce | Uwaga | Wniosek |
|---|---|---|---|
| M1 | dxgi.rs:227-241 | `display_size()` domyślnie **3840×2160**; `modes()` zgłasza jeden tryb o tym rozmiarze. settings.xml żąda 1280×720 → gra filtrująca tryby po rozmiarze nie znajdzie dopasowania. | **Wymagane:** `VICTORY_DISPLAY_MODE=1280x720` w zestawie env razem z `VICTORY_REFRESH=120`. |
| M2 | dxgi.rs:269-275 | `VICTORY_REFRESH=120` przechodzi walidację (24..=360), fallback 60 przy braku/w złym wartości. | OK. Bez zmiennej gra dostanie 60 Hz i interwały 120 Hz będą niemożliwe — zmienna jest **obowiązkowa** dla tego testu. |
| M3 | dxgi.rs:262-264 | Przy `*count < 1` zwraca `MORE_DATA` bez ustawienia `*count = 1` (kontrakt DXGI każe ustawić pełną liczbę). | Kosmetyka zgodności; tytuły rzadko w to trafiają. |
| M4 | dxgi.rs:258-265 | Zawsze `*count = 1`. Konsola zgłasza wiele trybów; tytuł szukający pary (rozdzielczość, odświeżanie) ma jednego kandydata. | Na później: zgłaszać ≥2 tryby ((1280,720,refresh) i (display,refresh)); teraz wystarczy M1. |

Struktura `Mode` (32 bajty, dxgi.rs:210-220) zgadza się z `DXGI_MODE_DESC`; `refresh
[120, 1]` to poprawne 120,0 Hz. `format: 0` (UNKNOWN), `scanlines: 1` (progresywne) — OK.

## 3. Walidacja patcha settings.xml

Zmiany względem backupu (plik napisany wcześniej przez samą grę — najlepsze źródło
domen):

| Klucz | Gra zapisała | Patch | Domeny RAGE / plauzibilność |
|---|---|---|---|
| `graphics/desiredFPS` | 30 | **60** | 30/60/120; cel dla FSR, nie cap — bezpieczne |
| `video/refreshRate` | 60/1 | **120/1** | licznik/mianownik; spójne z `VICTORY_REFRESH=120` |
| `video/resolutionFullscreen` | 3840×2160 | **1280×720** | plauzibilne; wymaga M1 (`VICTORY_DISPLAY_MODE=1280x720`) |
| `video/frameRateLimit` | 30 | **0** | gra zapisała **liczbę** (30), nie indeks 1..7 jak GTA V/RDR2 → `0` niemal na pewno „bez limitu”; spójne z `vSync=0` |
| `video/vSync` | 2 (połówka) | **0** (off) | 0=off, 1=on, 2=half — standard RAGE |
| BOM | brak | **dodany** | parser RAGE zwykle toleruje; przy objawach — przepisać bez BOM |
| koniec pliku | bez znaku nowej linii | dodany | bez znaczenia |
| formatowanie | wielolinijne | jednolinijkowe `resolutionFullscreen` | bez znaczenia |

### 3.1 Co może zrobić gra, jeśli `frameRateLimit=0` jest niepoprawne

(a) **clamp do najbliższej poprawnej wartości** → najpewniej 30 (jej własny default)
→ test pokaże równo 30 fps — stabilne, wykrywalne;
(b) **zignorować ustawienie** → brak capa (to, czego chcemy);
(c) **uznać sekcję `<video>` za uszkodzoną** → przepisać defaulty (30/vSync 2/4K)
przy wyjściu — wykrywalne przez readback.

Żaden scenariusz nie crashuje gry; najgorszy to cichy cap 30.

### 3.2 Drabinka awaryjna

1. `frameRateLimit=0`, `vSync=0`, `desiredFPS=60` (bieżący patch) — **weryfikacja
   przez readback po wyjściu gry** (gra nadpisuje settings.xml przy exit; diff z
   `.cap-bak` pokaże, co zaakceptowała).
2. Jeśli cap 30 albo nadpisanie: `frameRateLimit=60` (desiredFPS zostaje 60).
3. Jeśli nadal cap: `frameRateLimit=120` (spójne z 120/1).
4. Podłoga dowodowa: `frameRateLimit=30`, `vSync=2` (wartości zapisane przez samą
   grę) — potwierdza, że parser czyta plik; wtedy problem leży w domenie, nie w pliku.

## 4. Weryfikacja

### 4.1 Env i log

Oczekiwane wiersze logu przy starcie:

```
borderless fullscreen applied to the title window (VICTORY_BORDERLESS=1)  width=… height=…
display mode reported to the title  width=… height=…
```

- `width=2048 height=1280` → potwierdzenie D1 (DPI-unaware); `2560x1600` → DPI fix działa.
- `width=1280 height=720` w wierszu `display mode reported` → `VICTORY_DISPLAY_MODE` ustawione.
- Brak wiersza „borderless … applied” mimo env=1 → okno tytułu nie zostało znalezione
  (zapasowe okno hosta) albo `title_window()` złapało złe okno.

### 4.2 Styl i prostokąt okna (GetWindowRect)

PowerShell (proces sprawdzający też jest DPI-unaware, więc współrzędne są w tej samej
przestrzeni wirtualnej, co u gry — oczekiwane 2048×1280 bez DPI fix, 2560×1600 z):

```powershell
Add-Type @"
using System; using System.Text; using System.Runtime.InteropServices;
using System.Collections.Generic;
public class W {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; public override string ToString() => $"{L},{T} {R-L}x{B-T}"; }
  public delegate bool EnumProc(IntPtr h, IntPtr lp);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr lp);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll", EntryPoint="GetWindowLongPtrW")] public static extern IntPtr GetWindowLongPtr(IntPtr h, int i);
  [DllImport("user32.dll")] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  public static List<IntPtr> List(uint pid) { var f = new List<IntPtr>(); EnumWindows((h,lp)=>{ uint p; GetWindowThreadProcessId(h,out p); if(p==pid && IsWindowVisible(h)) f.Add(h); return true; }, IntPtr.Zero); return f; }
}
"@
$proc = Get-Process -Name victory -ErrorAction Stop   # proces emulatora; okno gry należy do niego
foreach ($h in [W]::List($proc.Id)) {
  $r = New-Object W+RECT; [W]::GetWindowRect($h,[ref]$r) | Out-Null
  $style = [W]::GetWindowLongPtr($h,-16).ToInt64()     # -16 = GWL_STYLE
  $sb = New-Object System.Text.StringBuilder 256; [W]::GetWindowTextW($h,$sb,256) | Out-Null
  "{0} '{1}' rect={2} style=0x{3:X8} caption={4}" -f $h,$sb,$r,$style,(($style -band 0x00C00000) -ne 0)
}
```

Kryteria przejścia:

- **bez paska tytułu:** `caption=False` (bity `WS_CAPTION` = 0x00C00000 wyzerowane;
  borderless popup ma zwykle 0x90000000+);
- **pełny ekran:** `rect=0,0 2048x1280` (bez DPI fix) albo `0,0 2560x1600` (z DPI fix)
  — identyczny z rozmiarem ekranu w przestrzeni procesu;
- dokładnie jedno widoczne okno procesu spełnia oba warunki (więcej → D3).

### 4.3 Readback settings (po wyjściu gry)

Gra nadpisuje settings.xml przy zakończeniu — diff po ostatnim przebiegu pokazuje,
co zaakceptowała:

```powershell
git -C D:\git\gta6-30fps diff --no-index -- "D:\Gry\VItoriaBr-data\data\7952987A\storage\settings\settings.xml.cap-bak" "D:\Gry\VItoriaBr-data\data\7952987A\storage\settings\settings.xml"
```

Oczekiwane: `desiredFPS=60`, `frameRateLimit=0`, `vSync=0`, `refreshRate=120/1`,
`resolutionFullscreen=1280x720` **pozostają** po wyjściu. Jeśli gra je przepisała
(np. frameRateLimit z powrotem 30) → przejść do drabinki 3.2.

### 4.4 FPS w logu

Wiersz frame-rate po przebiegu: `frameRateLimit=0` + `vSync=0` powinny dać FPS
niezależny od 30; cap 30 w logu przy wolnym hostcie nie rozstrzyga (menu trzyma
30-31 fps samo z siebie — zob. PRESENT-LATENCY.md p. 0.2), więc rozstrzyga readback 4.3,
nie FPS.

## 5. Rollback

Wszystkie przełączniki są env- lub plikowe — żaden nie wymaga operacji git:

1. **Kod:** `VICTORY_BORDERLESS` i `VICTORY_REFRESH` usunąć ze środowiska startu
   (`VICTORY_BORDERLESS=0` działa równoważnie — warunek to `v != "0"`); opcjonalnie
   `VICTORY_DISPLAY_MODE` też usunąć. Kod w `VItoriaBr-opt` zostaje — jest martwy bez env.
   **Nie robić `git checkout --` na `host.rs`/`dxgi.rs`** — w worktree leżą
   niezacommitowane zmiany orchestratora (ta sama zasada co w PRESENT-LATENCY.md).
2. **Ustawienia:** przywrócić backup, **tylko gdy gra nie działa** (nadpisuje plik
   przy wyjściu):

   ```powershell
   Copy-Item "D:\Gry\VItoriaBr-data\data\7952987A\storage\settings\settings.xml.cap-bak" `
             "D:\Gry\VItoriaBr-data\data\7952987A\storage\settings\settings.xml" -Force
   ```

   Docelowy interfejs to `Patch-GameSettings.ps1 -Restore` (według planu
   orchestratora). **Na dzień tego dokumentu skrypt nie istnieje** — w
   `D:\git\gta6-30fps\tools\` jest tylko `bench\profile\shader\assets\`, a jedyny
   .ps1 to `benchmarks\launch-bench.ps1`. Dopóki nie powstanie, używać powyższego
   Copy-Item.
3. Po rollbacku: uruchomić grę raz bez env i sprawdzić 4.3 (plik z powrotem
   30/60/2/3840×2160).

## 6. Protokół uruchomienia: kliknij, potem Enter

Kolejność ma znaczenie, bo patch używa `SWP_NOACTIVATE` (celowo nie kradnie fokusa),
a `Enter` trafia do okna **z fokusem**:

1. Start z env: `VICTORY_BORDERLESS=1 VICTORY_REFRESH=120 VICTORY_DISPLAY_MODE=1280x720`.
2. Poczekać, aż okno gry się pojawi i narysuje pierwsze klatki (menu).
3. **Ktoś klika raz w okno gry** — daje mu aktywację/przód bez zmiany jego stanu.
4. **Dopiero potem Enter** (konsolowy „naciśnij Enter”/wznowienie tytułu).
   Enter przed kliknięciem idzie do terminala/launchera i zostaje zgubiony przez grę.
5. Nie alt-tabować do czasu minięcia pauzy; po każdej utracie fokusa — ponowny klik
   w okno, zanim kolejny Enter.
6. Po wyjściu gry: weryfikacja 4.3 (readback) i 4.4 (log FPS).

## 8. Wyniki na �ywo (2026-11-26, orchestrator)

1. **CAPEM BY� PO STRONIE GRY � nie w XML.** Log warstwy pokaza� wielokrotne
   `victory_gpu::frame: frame interval interval=33.333ms` � tytu� ustawia w�asny
   interwa� klatki przez method slot vtable urz�dzenia 0x270 (`set_interval` w
   `crates/victory-gpu/src/frame.rs`, zegar tickaj�cy co `length` mikrosekund).
   33333 us = dok�adnie 30 fps w menu, mimo desiredFPS=60/frameRateLimit=0 w XML
   i 120 Hz zg�aszanego przez `VICTORY_REFRESH`. To jest tryb konsolowy gry
   (pacing blokad� 30 Hz), a nie cap z pliku ustawie�.
2. **Patch `VICTORY_UNCAP=1` (frame.rs):** skraca ��dany interwa� o po�ow�
   (33333 -> 16666 us, z pod�og� `VICTORY_REFRESH`, domy�lnie 120 Hz). Gra
   pozostaje event-driven � dostaje tokeny klatek 2x cz�ciej.
3. **Wynik testu (build opt + Borderless + Memory + Uncap + NoXmemBatch):**
   menu stabilne **60.0 fps / 16.7 ms/frame** (12 draws/frame) przez >4 minuty,
   zero device-removed. Poprzedni identyczny run bez UNCAP: 30.0 fps / 33.3 ms.
   Cap 30 fps w grze: **USUNI�TY**.
4. **Uwaga regresyjna:** z w��czonym batchowaniem xmem (Agent A) przy UNCAP gra
   crashn�a po ~3 s: `mapping physical pages failed ... error 487` a potem
   wyj�tek 0x80000003 w kodzie tytu�u. Wy��czenie (`VICTORY_HLE_XMEM_BATCH=0`)
   przywraca stabilno��. Agent A naprawia w worktree `VItoriaBr-opt-hle`.
5. **DPI:** `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` w
   `apps/victory/src/main.rs` przy VICTORY_BORDERLESS=1 (zale�no�� windows +
   cecha Win32_UI_HiDpi w apps/victory/Cargo.toml). Zwirtualizowane 2048x1280
   znika przy nast�pnym pe�nym te�cie.
6. **Launcher:** `Launch-VItoriaBr-AB.ps1` ma teraz flagi `-Borderless
   -Uncap -NoXmemBatch` (plus istniej�ce `-Memory`); env `VICTORY_UNCAP`
   wy��czany, gdy flagi nie podano.
