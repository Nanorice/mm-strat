# TEST wake action: on wake from idle-sleep, (1) revive the Prefect server+serve and
# (2) arm a FAKE (selftest) scheduled job to confirm a job runs post-revival.
# Discord at each step. Self-contained; touches no prod scripts.
$ErrorActionPreference = 'SilentlyContinue'
$Root = 'C:\Users\sh019\Documents\projects\mm-strat'
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
$env:PYTHONUTF8 = '1'

function Send-Discord($msg) {
    $line = Get-Content (Join-Path $Root '.env') | Where-Object { $_ -match '^\s*DISCORD_WEBHOOK_URL\s*=' } | Select-Object -First 1
    $url = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'")
    if ($url) {
        $b = [System.Text.Encoding]::UTF8.GetBytes((@{ content = $msg } | ConvertTo-Json -Compress))
        try { Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/json; charset=utf-8' -Body $b -TimeoutSec 10 | Out-Null } catch {}
    }
}

# Hold the box awake for the duration of the test (released at the end).
$sig = '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$p = Add-Type -MemberDefinition $sig -Name Pw -Namespace W32 -PassThru
$p::SetThreadExecutionState([uint32]'0x80000001') | Out-Null

& (Join-Path $Root 'scripts\wake_diag.ps1') -Phase post 2>&1 | Out-Null
Send-Discord "ITX woke from idle-sleep (test) - reviving Prefect server..."

# --- (1) Revive server + serve ---
foreach ($t in 'PrefectServer', 'PrefectDailyPipelineServe') { Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Out-Null }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -EA SilentlyContinue |
    Where-Object { $_.CommandLine -match 'prefect server start|daily_pipeline_flow|run_daily_pipeline' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -EA SilentlyContinue }
for ($i = 0; $i -lt 15; $i++) { if (@(Get-NetTCPConnection -LocalPort 4200 -State Listen -EA SilentlyContinue).Count -eq 0) { break }; Start-Sleep 1 }
Start-ScheduledTask -TaskName 'PrefectServer'
$streak = 0; $healthy = $false
for ($i = 0; $i -lt 45; $i++) {
    try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:4200/api/health' -TimeoutSec 3 | Out-Null; $streak++ } catch { $streak = 0 }
    if ($streak -ge 6) { $healthy = $true; break }; Start-Sleep 2
}
if (-not $healthy) {
    Send-Discord "ITX test: server FAILED to revive after wake"
    $p::SetThreadExecutionState([uint32]'0x80000000') | Out-Null
    exit 1
}
Send-Discord "ITX test: server revived (sustained healthy)"
Start-ScheduledTask -TaskName 'PrefectDailyPipelineServe'
Send-Discord "ITX test: serve restarted - ready for a job"
Start-Sleep 25   # let serve attach + register the deployment

# --- (2) Fire a fake (selftest) job; its completion hook Discords the status ---
Send-Discord "ITX test: arming a fake selftest job (~2 min)..."
& $Py (Join-Path $Root 'tools\_hook_test_schedule.py') arm --selftest --run-min 2 2>&1 | Out-Null

# Hold awake long enough for the scheduled job to fire (+2 min) and report Completed.
Start-Sleep 240

# Restore the prod idle-sleep timeout (2h) that the arm script shortened for the test.
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 7200 2>&1 | Out-Null
powercfg /setactive SCHEME_CURRENT 2>&1 | Out-Null
Send-Discord "ITX test: done - idle-sleep restored to 2h"

$p::SetThreadExecutionState([uint32]'0x80000000') | Out-Null
