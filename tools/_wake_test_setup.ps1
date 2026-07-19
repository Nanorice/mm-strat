# One-off TEST scaffolding (run ELEVATED). Diagnoses open issue #1: does the RTC
# wake timer actually fire? Registers PrefectWakeTest with settings IDENTICAL to
# the prod PrefectPipelineWake task (only Once-vs-Weekly differs), snapshots the
# ARMED wake-timer state (the evidence never captured), then sleeps the box.
#
# On wake, wake_for_pipeline.ps1 records the -Phase post snapshot automatically.
# Compare logs/prefect/wakediag_<date>.log pre-vs-post:
#   - pre shows a timer armed for $At but box never woke  -> RTC firmware miss (BIOS)
#   - pre shows NO timer armed                            -> task/power-setting bug
# Clean up:  Unregister-ScheduledTask PrefectWakeTest -Confirm:$false
param(
    [datetime]$At = (Get-Date).AddMinutes(8),   # default: 8 min from now (ACPI margin)
    [switch]$NoSleep                            # register + snapshot only, don't sleep
)
$ErrorActionPreference = 'Stop'
$Root = 'C:\Users\sh019\Documents\projects\mm-strat'

Unregister-ScheduledTask -TaskName 'PrefectSleepTest' -Confirm:$false -ErrorAction SilentlyContinue

# Mirror prod (scripts/register_prefect_wake_task.ps1) settings EXACTLY so the
# test exercises the real wake path; only the trigger is Once instead of Weekly.
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}\scripts\wake_for_pipeline.ps1"' -f $Root)
$trigger = New-ScheduledTaskTrigger -Once -At $At
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName 'PrefectWakeTest' -Action $action -Trigger $trigger `
    -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host ("[OK] PrefectWakeTest armed (Once {0}, WakeToRun, prod-mirrored)" -f $At.ToString('yyyy-MM-dd HH:mm:ss'))

# Capture the ARMED state NOW, while elevated and before sleep. This is the
# missing evidence: /waketimers should list a timer for ~$At.
& (Join-Path $Root 'scripts\wake_diag.ps1') -Phase pre
Write-Host "[OK] Pre-sleep snapshot written to logs/prefect/wakediag_<date>.log"

if ($NoSleep) { Write-Host "[..] -NoSleep set; not sleeping. Sleep manually to start the test."; return }

# Refuse to sleep if a pipeline run is live (never sleep the box mid-run).
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'run_daily_pipeline\.py' }
if ($running) { Write-Host "[ERR] pipeline run active - aborting sleep. Re-run when idle."; exit 1 }

Write-Host ("[..] sleeping now (S3); box should wake at {0}" -f $At.ToString('HH:mm:ss'))
Start-Sleep -Seconds 2
rundll32.exe powrprof.dll,SetSuspendState 0,1,0
