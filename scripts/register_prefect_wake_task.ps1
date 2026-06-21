# Registers the wake task that powers the box on ~5 min before the nightly run.
#
# Prefect cannot wake the machine; this Task Scheduler task does. -WakeToRun
# wakes from sleep/hibernate (S1-S4) — NOT from a full shutdown (S5; that needs a
# BIOS "Resume by RTC Alarm"). Pair with: the Prefect cron at 22:00, the flow's
# sleep-on-completion hook, and Power Options -> "Allow wake timers = Enabled".
#
# Needs an ELEVATED PowerShell (writing the root task library requires admin).
param(
    [string]$TaskName = 'PrefectPipelineWake',
    [string]$At = '21:55'          # 5 min before the 22:00 Prefect run, local time
)
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$WakeScript = Join-Path $Root 'scripts\wake_for_pipeline.ps1'

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $WakeScript)

# Weekly Mon-Fri at $At, matching the pipeline's 0 22 * * 1-5 schedule.
$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At

$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -RunLevel Limited -ErrorAction Stop | Out-Null
    Write-Host "[OK] Registered wake task '$TaskName' (wakes Mon-Fri at $At)"
    Write-Host "     Ensure Power Options -> Sleep -> 'Allow wake timers' = Enabled."
} catch {
    Write-Host "[ERR] Failed to register '$TaskName': $($_.Exception.Message)"
    Write-Host "      Run this from an ELEVATED PowerShell (Run as administrator)."
    exit 1
}
