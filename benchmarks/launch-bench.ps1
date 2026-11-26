#requires -Version 5.1
<#
  Benchmark launch for the gta6-30fps harness.

  The project launchers set VICTORY_LOG=warn, which suppresses the fps line and
  the frame log, so a measurement would have no frame data. This script is the
  same profile with measurement logging on:

      VICTORY_LOG='victory_gpu::host=info,victory_gpu::framelog=info,warn'
      VICTORY_FRAME_LOG=1

  Only the two records the harness parses are raised to INFO; everything else
  stays at WARN, so the logging cost stays off the measured path as far as the
  runtime allows.

  Source of truth for the profile:
      D:\Gry\VItoriaBr-data\Launch-VItoriaBr.ps1
      D:\Gry\fxceless-data\Launch-Fxceless.ps1
  If either launcher changes, update this file too - the resolved environment
  is written to <data>\logs\bench-env.json and recorded in every run.json.

  Usage:
      .\benchmarks\launch-bench.ps1                  # VItoriaBr, quality 1080p
      .\benchmarks\launch-bench.ps1 -Performance     # VItoriaBr, 720p
      .\benchmarks\launch-bench.ps1 -Fxceless        # fxceless, 720p
      .\benchmarks\launch-bench.ps1 -PrintEnv        # print, do not start
#>
[CmdletBinding()]
param(
    [switch]$Fxceless,
    [switch]$Performance,
    [switch]$Quality,
    [switch]$PrintEnv
)

$ErrorActionPreference = 'Stop'

if ($Fxceless) {
    $repo    = 'D:\git\fxceless-victory'
    $data    = 'D:\Gry\fxceless-data'
    $runtime = Join-Path $repo 'target\release\victory.exe'
    $game    = 'D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK'
    $exe     = Join-Path $game 'game_scarlett_master.exe'
    $env:VICTORY_CONFIG = Join-Path $repo 'victory.toml'
    $env:VICTORY_HOST_WAVE = '32'
    $env:VICTORY_VIEW_LIMIT = '1000000'
    $env:VICTORY_FULLSCREEN = '0'
    $env:VICTORY_LIBRARY_MAP = '0'
    $env:VICTORY_RELAY = '0'
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
    $env:VICTORY_LATE_WAIT = '3'
    $env:VICTORY_WIDE_BACK = '1'
    $env:VICTORY_BACK_OWN_VIEW = '0'
    $env:VICTORY_SHADER_LOOP_LIMIT = '256'
    $env:VICTORY_INDIRECT_GATHER = '0'
    $env:VICTORY_JOIN_PARTS = '0'
    $env:VICTORY_CARD_REHASH_RUNS = '1'
    $env:VICTORY_LEVELS_ON_DEMAND = '1'
    $env:VICTORY_BVH_BUILDER = '0'
    $env:VICTORY_CARD_FETCH_INFLIGHT = '0'
    $profile = if ($Quality) { 'quality' } else { 'performance' }
} else {
    $repo    = 'D:\git\VItoriaBr'
    $data    = 'D:\Gry\VItoriaBr-data'
    $runtime = Join-Path $repo 'target\release\victory.exe'
    $game    = 'D:\Gry\GTA6.Xbox.v1.0.2.1-CYBERLEEK'
    $exe     = Join-Path $game 'game_scarlett_master.exe'
    $env:VICTORY_CONFIG = Join-Path $repo 'victory.toml'
    $env:VICTORY_HOST_WAVE = '32'
    $env:VICTORY_VIEW_LIMIT = '1000000'
    $env:VICTORY_RELAY = '2'
    $env:VICTORY_QUEUE2 = '1'
    $env:VICTORY_ASYNC_SUBMIT = '1'
    $env:VICTORY_COPY_PLAIN = '1'
    $env:VICTORY_TEXTURE_NO_WAIT = '1'
    $env:VICTORY_CARD_BUFFERS_MB = '1024'
    $env:VICTORY_TEXTURE_BUDGET_MB = '5120'
    $env:VICTORY_PAGE_WRITES = 'slots'
    $env:VICTORY_WIDE_REFRESH = '1'
    $env:VICTORY_WIDE_MERGE = '1'
    $env:VICTORY_JOIN_COPIES = '1'
    $env:VICTORY_BVH_BUILDER = '0'
    $env:VICTORY_CARD_FETCH_INFLIGHT = '0'
    if ($Performance) {
        $env:VICTORY_DISPLAY_MODE = '1280x720'
        $env:VICTORY_AMBIENT = '0'
        $env:VICTORY_ASYNC_PRESENT = '1'
        $env:VICTORY_DISK_CORES = 'slow'
        $env:VICTORY_TEXTURE_BUDGET_MB = '4096'
        $env:VICTORY_CARD_BUFFERS_MB = '768'
        $env:VICTORY_LEVELS_ON_DEMAND = '1'
        $env:VICTORY_CARD_BUFFERS_MIN_MB = '1'
        $env:VICTORY_CARD_REHASH_RUNS = '1'
        $env:VICTORY_STAGING_POOL = '1'
        $env:VICTORY_LATE_WAIT = '3'
        $env:VICTORY_WIDE_BACK = '1'
        $env:VICTORY_BACK_OWN_VIEW = '1'
        $env:VICTORY_SHADER_LOOP_LIMIT = '256'
        $profile = 'performance'
    } else {
        $env:VICTORY_DISPLAY_MODE = '1920x1080'
        $env:VICTORY_AMBIENT = '0.6'
        $profile = 'quality'
    }
}

# Measurement logging: this is the only difference from the project launcher.
$env:VICTORY_LOG = 'victory_gpu::host=info,victory_gpu::framelog=info,warn'
$env:VICTORY_FRAME_LOG = '1'

$logs = Join-Path $data 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null

$resolved = [ordered]@{}
Get-ChildItem env: | Where-Object { $_.Name -like 'VICTORY_*' } | ForEach-Object {
    $resolved[$_.Name] = $_.Value
}
$record = [ordered]@{
    captured_utc = (Get-Date).ToUniversalTime().ToString('o')
    runtime      = if ($Fxceless) { 'fxceless' } else { 'vitoriabr' }
    profile      = $profile
    repo         = $repo
    data_root    = $data
    env          = $resolved
}
$record | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $logs 'bench-env.json')

Write-Host "benchmark launch: $($record.runtime) / $profile"
$record.env.GetEnumerator() | Sort-Object Name | ForEach-Object {
    Write-Host ("  {0}={1}" -f $_.Name, $_.Value)
}

if ($PrintEnv) { return }

if (!(Test-Path -LiteralPath $runtime)) {
    throw "Runtime missing: $runtime`nBuild it first: cd $repo; cargo build --release -p victory"
}
if (!(Test-Path -LiteralPath $exe)) {
    throw "Title executable missing: $exe"
}

# Force the discrete adapter for this runtime on a hybrid laptop.
$gpuKey = 'HKCU:\Software\Microsoft\DirectX\UserGpuPreferences'
if (!(Test-Path $gpuKey)) { New-Item -Path $gpuKey -Force | Out-Null }
Set-ItemProperty -Path $gpuKey -Name $runtime -Value 'GpuPreference=2;'

$stdout = Join-Path $logs 'game-stdout.log'
$stderr = Join-Path $logs 'game-stderr.log'
Remove-Item $stdout, $stderr -ErrorAction SilentlyContinue

Push-Location $repo
try {
    $p = Start-Process -FilePath $runtime `
        -ArgumentList @('run', '--execute', $exe) `
        -WorkingDirectory $repo `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -PassThru
    Write-Host "started PID $($p.Id)"
    Write-Host "stderr: $stderr"
} finally {
    Pop-Location
}
