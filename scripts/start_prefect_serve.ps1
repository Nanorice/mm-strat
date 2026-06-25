# Self-anchored launcher for the daily-pipeline scheduler (Prefect `serve`).
# Waits for the local server, then registers the deployment + cron schedule and
# executes scheduled runs. Plays the worker role for static infra.
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$LogDir = Join-Path $Root 'logs\prefect'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ("serve_{0}.log" -f (Get-Date -Format 'yyyy-MM-dd_HHmmss'))

Get-ChildItem $LogDir -Filter 'serve_*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Talk to the persistent local server so runs show up in the UI.
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
# Emit flow-run heartbeats every 30s so the 'crash-zombie-flow-runs' automation
# (90s proactive window) can mark a run Crashed when its process dies hard
# (box sleeps / server lost) instead of leaving it stuck in Running.
$env:PREFECT_FLOWS_HEARTBEAT_FREQUENCY = '30'
Set-Location $Root

# Wait up to ~2 min for the server API to come up (it starts in a sibling task).
$healthy = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:4200/api/health' -TimeoutSec 3 | Out-Null
        $healthy = $true
        break
    } catch {
        Start-Sleep -Seconds 2
    }
}
if (-not $healthy) {
    "Prefect server did not become healthy within timeout" | Tee-Object -FilePath $Log
    exit 1
}

# Server is healthy: idempotently ensure server-side automations (zombie-run
# detection). Best-effort and timeout-bounded - never blocks serve startup.
& $Py (Join-Path $Root 'scripts\ensure_prefect_automations.py') *>&1 | Tee-Object -FilePath $Log -Append

& $Py (Join-Path $Root 'flows\daily_pipeline_flow.py') --serve *>&1 | Tee-Object -FilePath $Log -Append
