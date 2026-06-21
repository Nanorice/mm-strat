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

& $Py (Join-Path $Root 'flows\daily_pipeline_flow.py') --serve *>&1 | Tee-Object -FilePath $Log
