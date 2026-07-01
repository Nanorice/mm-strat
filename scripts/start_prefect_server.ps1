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
# PREFECT_API_DATABASE_TIMEOUT is the legacy setting name the server actually reads
# (configurations.py uses PREFECT_API_DATABASE_TIMEOUT, not PREFECT_SERVER_DATABASE_TIMEOUT).
# Raise from default 10s so startup state validation survives transient contention.
$env:PREFECT_API_DATABASE_TIMEOUT = '60'
Set-Location $Root

# Checkpoint+truncate the WAL, then delete the SHM+WAL files.
# The SHM persists across sleep/wake with stale WAL lock state; wal_checkpoint(TRUNCATE)
# clears WAL content but leaves the SHM intact. A stale SHM makes SQLite think a lock
# is held by a dead connection, causing 'database is locked' in startup state validation.
& $Py (Join-Path $Root 'scripts\checkpoint_prefect_wal.py') *> (Join-Path $LogDir 'wal_checkpoint.log')
$PrefectDb = Join-Path $env:USERPROFILE '.prefect'
Remove-Item -Path (Join-Path $PrefectDb 'prefect.db-wal') -Force -ErrorAction SilentlyContinue
Remove-Item -Path (Join-Path $PrefectDb 'prefect.db-shm') -Force -ErrorAction SilentlyContinue

# Launch the server with a DIRECT all-stream redirect, NOT '... | Tee-Object'.
# Running it inside a PowerShell pipeline (Tee) made the server EXIT on a startup
# 'database is locked' that a direct foreground start survived (2026-06-30), and
# Tee buffered the crash traceback away so it never reached the log. '*>' writes
# every stream straight to the file with no pipeline in between.
& $Py -m prefect server start *> $Log
