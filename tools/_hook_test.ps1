# One-off TEST scaffolding (run ELEVATED). Full sleep+wake hook cycle:
#   1. restart serve so the flow's new "sleeping" Discord message is loaded
#   2. arm PrefectWakeTest (settings IDENTICAL to prod PrefectPipelineWake) ~WakeMin out
#   3. capture the pre-sleep /waketimers snapshot (open issue #1 evidence)
#   4. arm a FAST idempotent scheduled run (date=$Date, sleep_after=True) ~RunMin out
# The Prefect job's completion hook SLEEPS the box (S3); the wake task WAKES it.
# Watch Discord:  ✅ Completed -> 😴 sleeping -> ⏰ woke -> ✅ healthy -> 🚀 serve restarted.
# Cleanup after the cycle:
#   python tools/_hook_test_schedule.py cleanup
#   Unregister-ScheduledTask PrefectWakeTest -Confirm:$false
param(
    [int]$RunMin = 2,               # minutes until the scheduled selftest run fires
    [int]$WakeMin = 10              # minutes until the wake task fires (selftest completes in seconds)
)
$ErrorActionPreference = 'Stop'
$Root = 'C:\Users\sh019\Documents\projects\mm-strat'
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
$env:PYTHONUTF8 = '1'

$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
if (-not $elevated) { Write-Host '[ERR] run this ELEVATED (registers a wake task + reads /waketimers).'; exit 1 }

# Never start while a pipeline run is live (it holds the DuckDB write lock).
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'run_daily_pipeline\.py' }
if ($running) { Write-Host '[ERR] a pipeline run is active - wait for it to finish.'; exit 1 }

# Ensure the server is healthy; recover it in place if down (a full pipeline run's
# completion reliably hangs the SQLite server - issue #2 - so it is often down here).
$srvHealthy = $false
try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:4200/api/health' -TimeoutSec 3 | Out-Null; $srvHealthy = $true } catch {}
if (-not $srvHealthy) {
    Write-Host '[..] server down - recovering it'
    foreach ($t in 'PrefectServer', 'PrefectDailyPipelineServe') { Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Out-Null }
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -EA SilentlyContinue |
        Where-Object { $_.CommandLine -match 'prefect server start|daily_pipeline_flow|run_daily_pipeline' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
    for ($i = 0; $i -lt 15; $i++) { if (@(Get-NetTCPConnection -LocalPort 4200 -State Listen -EA SilentlyContinue).Count -eq 0) { break }; Start-Sleep 1 }
    Start-ScheduledTask -TaskName 'PrefectServer'
    $streak = 0
    for ($i = 0; $i -lt 45; $i++) {
        try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:4200/api/health' -TimeoutSec 3 | Out-Null; $streak++ } catch { $streak = 0 }
        if ($streak -ge 6) { $srvHealthy = $true; break }
        Start-Sleep 2
    }
    if (-not $srvHealthy) { Write-Host '[ERR] could not recover Prefect server'; exit 1 }
    Write-Host '[OK] server recovered'
}

$WakeAt = (Get-Date).AddMinutes($WakeMin)

# Q1 lever: enable wake timers on DC too (prod register set only AC; DC was Disabled,
# so a momentary DC reading would silently kill the wake timer).
powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 2>&1 | Out-Null
powercfg /setactive SCHEME_CURRENT 2>&1 | Out-Null
Write-Host '[OK] wake timers enabled on AC and DC'

# 1. Restart serve so the updated flow code (the "sleeping" Discord message) is loaded.
Write-Host '[..] restarting serve to load updated flow code'
Stop-ScheduledTask -TaskName 'PrefectDailyPipelineServe' -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'daily_pipeline_flow\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName 'PrefectDailyPipelineServe'
Start-Sleep -Seconds 25   # let serve re-register the deployment + schedule

# 2. Arm the wake task (prod-mirrored; only the trigger differs: Once vs Weekly).
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}\scripts\wake_for_pipeline.ps1"' -f $Root)
$trigger = New-ScheduledTaskTrigger -Once -At $WakeAt
$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName 'PrefectWakeTest' -Action $action -Trigger $trigger `
    -Settings $settings -RunLevel Limited -Force | Out-Null
Write-Host ("[OK] PrefectWakeTest armed for {0} (WakeToRun)" -f $WakeAt.ToString('yyyy-MM-dd HH:mm:ss'))

# 3. Pre-sleep diag: capture /waketimers (the missing open-issue-#1 evidence) while elevated.
& (Join-Path $Root 'scripts\wake_diag.ps1') -Phase pre

# 4. Arm the scheduled selftest run; it skips the pipeline and its completion hook sleeps the box.
& $Py (Join-Path $Root 'tools\_hook_test_schedule.py') arm --sleep-after 1 --selftest --run-min $RunMin
if ($LASTEXITCODE -ne 0) { Write-Host '[ERR] failed to arm scheduled run'; exit 1 }

Write-Host ''
Write-Host '==================== TEST ARMED ===================='
Write-Host ("Selftest run fires ~{0} min from now (sleep_after=True) -> completes in seconds -> box SLEEPS." -f $RunMin)
Write-Host ("Wake task fires {0} -> box WAKES, wake script runs." -f $WakeAt.ToString('HH:mm:ss'))
Write-Host 'Discord timeline: Completed -> sleeping -> woke -> server healthy -> serve restarted.'
Write-Host 'Cleanup once done:  python tools/_hook_test_schedule.py cleanup ; Unregister-ScheduledTask PrefectWakeTest -Confirm:$false'
