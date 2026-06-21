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
    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
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
