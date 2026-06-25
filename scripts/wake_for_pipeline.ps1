# Wake-task action: wake the box, RESTART Prefect, hold awake across 22:00.
#
# Task Scheduler wakes the machine (-WakeToRun) and runs this at 21:55. Two jobs:
#  1. Restart the Prefect server + serve. The server does NOT survive a sleep/wake
#     cleanly (it resumes broken), and AtLogon tasks don't re-fire on wake — so a
#     fresh restart here is what guarantees a healthy server before the 22:00 run.
#  2. Hold the system-required lock ~10 min so a short idle timeout can't re-suspend
#     the box before 22:00. The flow then holds its OWN lock for the run and its
#     completion hook sleeps the box at the end.
$ErrorActionPreference = 'SilentlyContinue'

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root 'logs\prefect'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ('wake_{0}.log' -f (Get-Date -Format 'yyyy-MM-dd'))
function Log($m) { ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) | Out-File -FilePath $Log -Append -Encoding utf8 }

# Server-independent Discord alert (raw webhook read from .env). The Prefect
# DiscordWebhook block is unusable here: loading a block needs the API, which is
# exactly what's down when the wake health check fails.
function Send-DiscordAlert($msg) {
    $envFile = Join-Path $Root '.env'
    if (-not (Test-Path $envFile)) { return }
    $line = Get-Content $envFile | Where-Object { $_ -match '^\s*DISCORD_WEBHOOK_URL\s*=' } | Select-Object -First 1
    if (-not $line) { return }
    $url = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'")
    if (-not $url) { return }
    try {
        $body = [System.Text.Encoding]::UTF8.GetBytes((@{ content = $msg } | ConvertTo-Json -Compress))
        Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 10 | Out-Null
    } catch {}
}

Log "woke for nightly pipeline"

# Prune wake logs older than 30 days.
Get-ChildItem $LogDir -Filter 'wake_*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Hold the box awake first (covers the restart + the gap to 22:00).
# ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001) => block sleep.
$sig = '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$p = Add-Type -MemberDefinition $sig -Name Power -Namespace Win32 -PassThru
$p::SetThreadExecutionState([uint32]'0x80000001') | Out-Null

# --- Restart Prefect so the 22:00 run gets a clean, healthy server ---
# Stop the tasks, kill the FULL prefect process set (server + serve + their
# flow-execution children), then WAIT for the SQLite WAL lock to actually
# release. A blind sleep races the handle teardown on force-kill: the new
# server would start into a still-locked prefect.db, fail startup state
# validation with 'database is locked', and never reach healthy.
foreach ($t in 'PrefectServer', 'PrefectDailyPipelineServe') {
    Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
}
# Match server, serve, AND the flow-execution child (run_daily_pipeline.py):
# that child holds live DB connections, so leaving it orphaned contends on the
# lock with the fresh server.
$prefectPat = 'prefect server start|daily_pipeline_flow\.py|run_daily_pipeline\.py'
function Get-PrefectProcs {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $prefectPat }
}
Get-PrefectProcs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

# Active barrier: block until every matched proc is gone AND :4200 is free
# (the dying child releases the WAL lock as it exits). Cap at ~30s.
$gone = $false
for ($i = 0; $i -lt 30; $i++) {
    $alive = @(Get-PrefectProcs).Count
    $port = @(Get-NetTCPConnection -LocalPort 4200 -State Listen -ErrorAction SilentlyContinue).Count
    if ($alive -eq 0 -and $port -eq 0) { $gone = $true; break }
    Start-Sleep -Seconds 1
}
Log ("teardown clear: {0} (waited {1}s, procs left={2})" -f $gone, $i, @(Get-PrefectProcs).Count)

Start-ScheduledTask -TaskName 'PrefectServer'
# Require SUSTAINED health, not a single 200. The server answers /api/health
# during early startup, then can die ~2s later on a 'database is locked' state-
# validation error. Handing off to serve inside that window is how the 06-25
# run was silently lost (single check passed, so no alert fired either). Only
# declare healthy after it survives several consecutive checks (~12s).
$healthy = $false; $streak = 0
for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:4200/api/health' -TimeoutSec 3 | Out-Null; $streak++ }
    catch { $streak = 0 }
    if ($streak -ge 6) { $healthy = $true; break }
    Start-Sleep -Seconds 2
}
Log ("server healthy (sustained): {0} after {1}s" -f $healthy, ($i * 2))
if (-not $healthy) {
    Log "ALERT: server unhealthy after wake - notifying Discord"
    Send-DiscordAlert "🛑 ITX wake (21:55): Prefect server did NOT come up. Tonight's 22:00 pipeline run will NOT fire - manual recovery needed."
}
Start-ScheduledTask -TaskName 'PrefectDailyPipelineServe'
Log "serve (re)started"

# Hold awake through the 22:00 trigger; flow takes over its own lock once running.
Start-Sleep -Seconds 600
# Release the lock (ES_CONTINUOUS only); the flow's post-run hook sleeps the box.
$p::SetThreadExecutionState([uint32]'0x80000000') | Out-Null
Log "released keep-awake lock"
