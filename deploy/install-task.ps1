<#
.SYNOPSIS
  Register (or remove) the Dennis bot as a Windows scheduled task.
  UNMAINTAINED: see the notice below.

.DESCRIPTION
  UNMAINTAINED / NOT THE SUPPORTED PATH.

  The target platform is Linux: WSL2 now, a Linux VPS later. The supported
  way to keep the bot up is the systemd unit installed by
  deploy/bootstrap.sh (deploy/dennis.service). This script is kept - not
  deleted - so a future native-Windows deployment has a starting point.

  Like deploy/bootstrap.ps1 it is ASCII-only and saved as UTF-8 with a BOM,
  so Windows PowerShell 5.1 can at least parse it; tests/test_platform.py
  enforces that much and nothing more.

  What it does, when it works: Task Scheduler is the lighter option on a
  personal desktop - the task runs as the logged-in user, so it inherits
  the normal environment, the GPU and the user's PATH, none of which a
  LocalSystem service gets cleanly. The machine is not always-on, so the
  task is deliberately "at logon" rather than "at startup".

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\install-task.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File deploy\install-task.ps1 -Remove
#>
[CmdletBinding()]
param(
    [string]$TaskName = 'DennisBot',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$vpy = Join-Path $repo '.venv\Scripts\pythonw.exe'   # pythonw: no console window
$main = Join-Path $repo 'main.py'

Write-Host "! deploy/install-task.ps1 is UNMAINTAINED. On the supported" -ForegroundColor Yellow
Write-Host "! Linux/WSL2 target, use the systemd unit from bootstrap.sh." -ForegroundColor Yellow

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "removed scheduled task '$TaskName'" -ForegroundColor Green
    return
}

if (-not (Test-Path $vpy)) {
    throw "venv not found at $vpy - run deploy\bootstrap.ps1 first"
}

$action = New-ScheduledTaskAction -Execute $vpy -Argument "`"$main`"" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn
# Below-normal priority (7) matches the render politeness knobs: the bot is
# a background resident on a machine somebody is actually using. It must not
# be stopped when the box goes on battery or sits idle.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -Priority 7

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Dennis - Telegram-controlled video pipeline' `
    -Force | Out-Null

Write-Host "registered '$TaskName' (starts at logon)" -ForegroundColor Green
Write-Host @"
  start now:  Start-ScheduledTask -TaskName $TaskName
  stop:       Stop-ScheduledTask  -TaskName $TaskName
  logs:       the bot logs to stdout; for a file, run main.py from a terminal
              or add a redirect in the action arguments.
  remove:     powershell -File deploy\install-task.ps1 -Remove
"@
