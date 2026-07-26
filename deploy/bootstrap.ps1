<#
.SYNOPSIS
  Dennis — native Windows setup (the counterpart to deploy/bootstrap.sh).

.DESCRIPTION
  Runs natively on Windows 11, NOT under WSL: the render box is a normal
  desktop, and Playwright/ffmpeg/NVENC all work better outside the WSL
  boundary. Creates the venv, installs pinned dependencies, checks FFmpeg,
  installs headless Chromium, generates the brand assets and fixtures, and
  runs the offline test suite.

  Idempotent — safe to re-run after a pull.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\bootstrap.ps1

.EXAMPLE
  # skip the (slow) suite when you just want dependencies refreshed
  powershell -ExecutionPolicy Bypass -File deploy\bootstrap.ps1 -SkipTests
#>
[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipBrowser
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "    ! $msg" -ForegroundColor Yellow }

# --------------------------------------------------------------- python
Step "Python 3.11+"
$py = $null
foreach ($cand in @('py -3.12', 'py -3.11', 'python')) {
    $exe, $verArg = $cand.Split(' ', 2)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    try {
        $v = & $exe $verArg -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$v -ge [version]'3.11') { $py = $cand; break }
    } catch { }
}
if (-not $py) {
    throw "Python 3.11+ not found. Install it: winget install Python.Python.3.12"
}
Write-Host "    using: $py"

# ------------------------------------------------------------------ venv
Step "virtualenv + pinned dependencies"
if (-not (Test-Path '.venv')) {
    $exe, $verArg = $py.Split(' ', 2)
    if ($verArg) { & $exe $verArg -m venv .venv } else { & $exe -m venv .venv }
}
$vpy = Join-Path $repo '.venv\Scripts\python.exe'
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -e '.[dev,filings]' --quiet
if ($LASTEXITCODE -ne 0) { throw "dependency install failed" }

# ---------------------------------------------------------------- ffmpeg
Step "FFmpeg 6+"
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    Warn "ffmpeg is not on PATH. Install it with:"
    Warn "    winget install Gyan.FFmpeg"
    Warn "then open a NEW terminal (PATH is only refreshed for new processes)."
    throw "ffmpeg is required"
}
$ffver = (& ffmpeg -hide_banner -version | Select-Object -First 1)
Write-Host "    $ffver"

# --------------------------------------------------------------- encoder
Step "hardware encoder (NVENC)"
# The pipeline smoke-tests the encoder at runtime; this is just an early
# heads-up so a missing driver is obvious now rather than mid-render.
$encoders = & ffmpeg -hide_banner -encoders 2>$null
if ($encoders -match 'h264_nvenc') {
    Write-Host "    h264_nvenc present — finals will use the GPU"
} else {
    Warn "h264_nvenc not listed; renders fall back to libx264 (fine, just slower)"
}

# -------------------------------------------------------------- chromium
if (-not $SkipBrowser) {
    Step "headless Chromium (10-K screenshots + the design-kit exporter)"
    & $vpy -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Warn "Chromium install failed — 10-K auto-shots degrade to none; the"
        Warn "design-kit exporter will not run until this succeeds."
    }
}

# ------------------------------------------------------------------ .env
Step ".env"
if (-not (Test-Path '.env')) {
    Copy-Item '.env.example' '.env'
    Write-Host "    wrote .env from .env.example — EDIT IT before starting:"
    Write-Host "      TELEGRAM_BOT_TOKEN, OPERATOR_CHAT_IDS"
    Write-Host "      (going live) MOCK_MODE=false, ELEVENLABS_API_KEY + voice ids,"
    Write-Host "      PEXELS_API_KEY, SEC_USER_AGENT, GITHUB_MODELS_TOKEN"
} else {
    Write-Host "    .env already exists — left alone"
}

# ---------------------------------------------------------------- assets
Step "brand assets + fixtures (deterministic, generated locally)"
& $vpy scripts\gen_assets.py
& $vpy scripts\gen_fixtures.py

Step "design kit"
if (Test-Path 'assets\kit\manifest.json') {
    $n = (Get-ChildItem -Recurse -Filter *.png assets\kit | Measure-Object).Count
    Write-Host "    $n exported frames present"
} else {
    Warn "assets\kit is missing. Export it once with:"
    Warn "    .venv\Scripts\python.exe scripts\export_design_kit.py"
}

# ----------------------------------------------------------------- tests
if (-not $SkipTests) {
    Step "offline test suite (MOCK_MODE, zero network)"
    & $vpy -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "test suite failed" }
}

Step "done"
Write-Host @"
Start the bot:
    .venv\Scripts\python.exe main.py

To run it in the background at logon, register the scheduled task:
    powershell -ExecutionPolicy Bypass -File deploy\install-task.ps1
"@ -ForegroundColor Green
