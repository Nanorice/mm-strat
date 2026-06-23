# Idempotent registration of the two boot tasks that keep Prefect alive on ITX:
#   1. PrefectServer                -> start_prefect_server.ps1  (API + UI :4200)
#   2. PrefectDailyPipelineServe    -> start_prefect_serve.ps1   (cron scheduler)
#
# Default trigger: AtLogOn (no admin needed; assumes the ops box auto-logs-in).
# For true headless always-on, re-register with an S4U principal (needs admin) —
# see scripts header notes / the runbook.
param(
    [string]$ServerTask = 'PrefectServer',
    [string]$ServeTask  = 'PrefectDailyPipelineServe'
)
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot

function Register-BootTask([string]$Name, [string]$ScriptPath) {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $ScriptPath)
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    # No RestartCount: auto-restart-on-failure spawned a 2nd server while the old
    # process tree (uvicorn child) still held the SQLite lock -> "database is
    # locked" -> crash -> restart -> cascade. A single instance is stable; clean
    # restarts go through the wake task (kill-then-start) or a manual bounce.
    # IgnoreNew: never run two instances of the same task concurrently.
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit ([TimeSpan]::Zero)   # long-running: no time limit

    Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
    try {
        Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger `
            -Settings $settings -RunLevel Limited -ErrorAction Stop | Out-Null
        Write-Host "[OK] Registered scheduled task: $Name"
    } catch {
        Write-Host "[ERR] Failed to register '$Name': $($_.Exception.Message)"
        Write-Host "      Registering tasks needs an ELEVATED PowerShell (Run as administrator)."
        exit 1
    }
}

Register-BootTask $ServerTask (Join-Path $Root 'scripts\start_prefect_server.ps1')
Register-BootTask $ServeTask  (Join-Path $Root 'scripts\start_prefect_serve.ps1')

Write-Host ""
Write-Host "Start now without waiting for logon:"
Write-Host "  Start-ScheduledTask -TaskName '$ServerTask'"
Write-Host "  Start-ScheduledTask -TaskName '$ServeTask'"
