# Self-anchored launcher for the local Prefect server (API + UI at :4200).
# Independent of an activated venv and of CWD — a boot task can provide neither.
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Root '.venv\Scripts\python.exe'
$LogDir = Join-Path $Root 'logs\prefect'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ("server_{0}.log" -f (Get-Date -Format 'yyyy-MM-dd_HHmmss'))

# Prune launcher logs older than 30 days.
Get-ChildItem $LogDir -Filter 'server_*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
Set-Location $Root

& $Py -m prefect server start *>&1 | Tee-Object -FilePath $Log
