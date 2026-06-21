# Nightly pipeline launcher for Windows Task Scheduler (S4).
#
# Task Scheduler cannot activate a venv and launches with CWD=C:\Windows\System32.
# This wrapper is fully self-anchored: it resolves the project root from its own
# location, calls the venv Python by absolute path, and pins CWD to the root so
# every relative path (.env, data/, logs/) resolves correctly.
#
# Register with: scripts/register_nightly_task.ps1 (or schtasks, see runbook).

$ErrorActionPreference = "Stop"

# Project root = parent of the scripts/ dir this file lives in.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Entry  = Join-Path $ProjectRoot "scripts\run_daily_pipeline.py"

$LogDir = Join-Path $ProjectRoot "logs\scheduler"
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }
$Stamp  = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "nightly_$Stamp.log"

Set-Location $ProjectRoot

# Force UTF-8 for child-process stdout/stderr so the log is plain text, not the
# UTF-16LE that PowerShell's native redirection would otherwise emit.
$env:PYTHONIOENCODING = "utf-8"
$OutputEncoding = [System.Text.Encoding]::UTF8

"[$(Get-Date -Format o)] Starting nightly pipeline" |
    Out-File -FilePath $LogFile -Encoding utf8

# Forward any extra args (e.g. --force, --date) straight through. Pipe combined
# streams through Out-File -Encoding utf8 to keep the log readable.
& $Python $Entry @args 2>&1 |
    Out-File -FilePath $LogFile -Encoding utf8 -Append
$Code = $LASTEXITCODE

"[$(Get-Date -Format o)] Pipeline exited with code $Code" |
    Out-File -FilePath $LogFile -Encoding utf8 -Append

# Prune scheduler logs older than 30 days so the dir doesn't grow unbounded.
Get-ChildItem $LogDir -Filter "nightly_*.log" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

exit $Code
