#requires -Version 5.1
<#
  A/B benchmark launch: windowed-cap30 (arm A) vs borderless-nocap (arm B).

  Same runtime state as D:\Gry\VItoriaBr-data\Launch-VItoriaBr-AB.ps1 for the
  opt build, plus the harness measurement logging and bench-env.json, so
  tools/bench needs no extra flags. Never touches settings.xml and never
  clears caches.

  Runtime constants (both arms):
    - D:\git\VItoriaBr-opt (Agent A heap-buffer patch is the build default;
      VICTORY_HEAP_BUFFERS_TABLES must stay UNSET - =1 reverts to the old
      mirror-everything path and is not used in this experiment),
    - VICTORY_REFRESH=120,
    - 1280x720 windowed swapchain (VICTORY_DISPLAY_MODE), warm shader cache.

  Arm switches:
    -Memory      Agent E Arm B staging bounds (TEXTURE_CATCHUP=0,
                 STAGE_MS=24, STAGE_MB=64). Pass in BOTH arms.
    -Borderless  VICTORY_BORDERLESS=1 on the title's own window (arm B only).

  Usage:
      .\benchmarks\launch-bench-ab.ps1 -Memory                       # arm A
      .\benchmarks\launch-bench-ab.ps1 -Memory -Borderless           # arm B
      .\benchmarks\launch-bench-ab.ps1 -Memory -Borderless -PrintEnv
#>
[CmdletBinding()]
param(
    [ValidateSet('opt', 'stable')][string]$Build = 'opt',
    [switch]$Memory,
    [switch]$Borderless,
    [switch]$PrintEnv
)

$ErrorActionPreference = 'Stop'

$repo    = if ($Build -eq 'opt') { 'D:\git\VItoriaBr-opt' } else { 'D:\git\VItoriaBr' }
$exe     = Join-Path $repo 'target\release\victory.exe'
$game    = 'D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK'
$gameExe = Join-Path $game 'game_scarlett_master.exe'
$data    = 'D:\Gry\VItoriaBr-data'
$logs    = Join-Path $data 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$env:VICTORY_CONFIG = Join-Path $repo 'victory.toml'
$env:VICTORY_HOST_WAVE = '32'
$env:VICTORY_VIEW_LIMIT = '1000000'
$env:VICTORY_CARD_ACCOUNTING = '1'
$env:VICTORY_DISPLAY_MODE = '1280x720'
$env:VICTORY_AMBIENT = '0'
$env:VICTORY_RELAY = '2'
$env:VICTORY_QUEUE2 = '1'
$env:VICTORY_ASYNC_SUBMIT = '1'
$env:VICTORY_COPY_PLAIN = '1'
$env:VICTORY_TEXTURE_NO_WAIT = '1'
$env:VICTORY_CARD_BUFFERS_MIN_MB = '1'
$env:VICTORY_CARD_BUFFERS_MB = '768'
$env:VICTORY_TEXTURE_BUDGET_MB = '4096'
$env:VICTORY_PAGE_WRITES = 'slots'
$env:VICTORY_WIDE_REFRESH = '1'
$env:VICTORY_WIDE_MERGE = '1'
$env:VICTORY_JOIN_COPIES = '1'
$env:VICTORY_LEVELS_ON_DEMAND = '1'
$env:VICTORY_CARD_REHASH_RUNS = '1'
$env:VICTORY_STAGING_POOL = '1'
$env:VICTORY_LATE_WAIT = '3'
$env:VICTORY_WIDE_BACK = '1'
$env:VICTORY_BACK_OWN_VIEW = '1'
$env:VICTORY_SHADER_LOOP_LIMIT = '256'
$env:VICTORY_BVH_BUILDER = '0'
$env:VICTORY_CARD_FETCH_INFLIGHT = '0'

# Agent A heap-buffer patch = the opt build's default path. The old
# mirror-everything path would be VICTORY_HEAP_BUFFERS_TABLES=1; never set it
# here, and drop any leftover from the shell.
Remove-Item Env:VICTORY_HEAP_BUFFERS_TABLES -ErrorAction SilentlyContinue

# Agent E Arm B: bounded texture staging (24 ms / 64 MB) instead of the
# 250 ms (750 catch-up) pass.
if ($Memory) {
    $env:VICTORY_TEXTURE_CATCHUP = '0'
    $env:VICTORY_TEXTURE_STAGE_MS = '24'
    $env:VICTORY_TEXTURE_STAGE_MB = '64'
} else {
    Remove-Item Env:VICTORY_TEXTURE_CATCHUP -ErrorAction SilentlyContinue
    Remove-Item Env:VICTORY_TEXTURE_STAGE_MS  -ErrorAction SilentlyContinue
    Remove-Item Env:VICTORY_TEXTURE_STAGE_MB  -ErrorAction SilentlyContinue
}

# Borderless fullscreen on the title's own window (arm B).
if ($Borderless) { $env:VICTORY_BORDERLESS = '1' }
else { Remove-Item Env:VICTORY_BORDERLESS -ErrorAction SilentlyContinue }

# Constant in both arms: report 120 Hz so pacing is not capped at 30 in
# quality mode. The settings.xml refresh (60/1 vs 120/1) is what differs and
# both values are recorded in run.json.
$env:VICTORY_REFRESH = '120'

# Measurement logging: only the two records the harness parses are raised to
# INFO; everything else stays at WARN (same as benchmarks\launch-bench.ps1).
$env:VICTORY_LOG = 'victory_gpu::host=info,victory_gpu::framelog=info,warn'
$env:VICTORY_FRAME_LOG = '1'

$resolved = [ordered]@{}
Get-ChildItem env: | Where-Object { $_.Name -like 'VICTORY_*' } | ForEach-Object {
    $resolved[$_.Name] = $_.Value
}
$record = [ordered]@{
    captured_utc = (Get-Date).ToUniversalTime().ToString('o')
    runtime      = 'vitoriabr'
    profile      = if ($Borderless) { 'ab-borderless-nocap' } else { 'ab-windowed-cap30' }
    build        = $Build
    repo         = $repo
    data_root    = $data
    env          = $resolved
}
$record | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $logs 'bench-env.json')

Write-Host "AB benchmark launch: $($record.build) / $($record.profile)"
$record.env.GetEnumerator() | Sort-Object Name | ForEach-Object {
    Write-Host ("  {0}={1}" -f $_.Name, $_.Value)
}

if ($PrintEnv) { return }

if (!(Test-Path -LiteralPath $exe)) {
    throw "Runtime missing: $exe`nBuild it first: cd $repo; cargo build --release -p victory"
}
if (!(Test-Path -LiteralPath $gameExe)) {
    throw "Title executable missing: $gameExe"
}

# Force the discrete adapter for this runtime on a hybrid laptop.
$gpuKey = 'HKCU:\Software\Microsoft\DirectX\UserGpuPreferences'
if (!(Test-Path $gpuKey)) { New-Item -Path $gpuKey -Force | Out-Null }
Set-ItemProperty -Path $gpuKey -Name $exe -Value 'GpuPreference=2;'

$stdout = Join-Path $logs 'game-stdout.log'
$stderr = Join-Path $logs 'game-stderr.log'
Remove-Item $stdout, $stderr -ErrorAction SilentlyContinue

Push-Location $repo
try {
    $p = Start-Process -FilePath $exe `
        -ArgumentList @('run', '--execute', $gameExe) `
        -WorkingDirectory $repo `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    Write-Host "AB $($record.profile) PID $($p.Id)"
    Write-Host "stderr: $stderr"
} finally {
    Pop-Location
}
