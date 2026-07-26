<#
.SYNOPSIS
  Register (or remove) the Dennis bot as a Windows scheduled task that
  starts at logon.

.DESCRIPTION
  Task Scheduler is the lighter option on a personal desktop: the task runs
  as the logged-in user, so it inherits the normal environment, the GPU and
  the user's PATH — none of which a LocalSystem service gets cleanly.

  Manual `python main.py` remains the default way to run the bot; this is
  only for leaving it up between reboots. The machine is not always-on, so
  the task is deliberately "at logon" rather than "at startup".

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

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "removed scheduled task '$TaskName'" -ForegroundColor Green
    return
}

if (-not (Test-Path $vpy)) {
    throw "venv not found at $vpy — run deploy\bootstrap.ps1 first"
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
    -Settings $settings -Description 'Dennis — Telegram-controlled video pipeline' `
    -Force | Out-Null

Write-Host "registered '$TaskName' (starts at logon)" -ForegroundColor Green
Write-Host @"
  start now:  Start-ScheduledTask -TaskName $TaskName
  stop:       Stop-ScheduledTask  -TaskName $TaskName
  logs:       the bot logs to stdout; for a file, run main.py from a terminal
              or add a redirect in the action arguments.
  remove:     powershell -File deploy\install-task.ps1 -Remove
"@
