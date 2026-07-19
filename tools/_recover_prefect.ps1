# Hardened single recovery of the Prefect server + serve: teardown (stop tasks,
# kill stale procs, wait :4200 free) -> start server -> require SUSTAINED health
# (6 consecutive) -> start serve. Same logic the wake action uses.
$ErrorActionPreference = 'SilentlyContinue'
foreach ($t in 'PrefectServer', 'PrefectDailyPipelineServe') { Stop-ScheduledTask -TaskName $t | Out-Null }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'prefect server start|daily_pipeline_flow|run_daily_pipeline' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
for ($i = 0; $i -lt 15; $i++) { if (@(Get-NetTCPConnection -LocalPort 4200 -State Listen).Count -eq 0) { break }; Start-Sleep 1 }
# Checkpoint the WAL while the db is unlocked so a bloated WAL can't stall startup.
$Py = Join-Path (Split-Path -Parent $PSScriptRoot) '.venv\Scripts\python.exe'
if (Test-Path $Py) { & $Py (Join-Path (Split-Path -Parent $PSScriptRoot) 'scripts\checkpoint_prefect_wal.py') 2>&1 | Write-Host }
Start-ScheduledTask -TaskName 'PrefectServer'
$streak = 0; $healthy = $false
for ($i = 0; $i -lt 45; $i++) {
    try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:4200/api/health' -TimeoutSec 3 | Out-Null; $streak++ } catch { $streak = 0 }
    if ($streak -ge 6) { $healthy = $true; break }
    Start-Sleep 2
}
Write-Host "server healthy (sustained)=$healthy"
if ($healthy) { Start-ScheduledTask -TaskName 'PrefectDailyPipelineServe'; Write-Host 'serve started' }
else { Write-Host 'server did NOT come up'; exit 1 }
