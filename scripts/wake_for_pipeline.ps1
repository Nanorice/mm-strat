# Wake-task action: keep the box awake across the 22:00 Prefect trigger.
#
# Task Scheduler wakes the machine (-WakeToRun) and runs this at 21:55. We then
# hold the system-required lock for ~10 min (until ~22:05) so a short idle-sleep
# timeout can't re-suspend the box before Prefect's 22:00 run starts. Once the
# pipeline is running it keeps the CPU busy, and the flow's completion hook sleeps
# the box again when the run finishes.
$ErrorActionPreference = 'SilentlyContinue'

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root 'logs\prefect'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ('wake_{0}.log' -f (Get-Date -Format 'yyyy-MM-dd'))
("{0}  woke for nightly pipeline; holding awake ~10 min" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')) |
    Out-File -FilePath $Log -Append -Encoding utf8

# Prune wake logs older than 30 days.
Get-ChildItem $LogDir -Filter 'wake_*.log' -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force -ErrorAction SilentlyContinue

# ES_CONTINUOUS (0x80000000) | ES_SYSTEM_REQUIRED (0x00000001) => block sleep.
$sig = '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint esFlags);'
$p = Add-Type -MemberDefinition $sig -Name Power -Namespace Win32 -PassThru
$p::SetThreadExecutionState([uint32]'0x80000001') | Out-Null
Start-Sleep -Seconds 600
# Release the lock (ES_CONTINUOUS only); normal idle/flow-hook sleep resumes.
$p::SetThreadExecutionState([uint32]'0x80000000') | Out-Null
