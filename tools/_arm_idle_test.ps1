# Idle-sleep wake test (run ELEVATED). Instead of suspending via the script
# (Reason 4 = Application API), this sets a short AC idle-sleep timeout so the box
# sleeps ON ITS OWN (Reason 7 = System Idle) once you stop touching it - a genuinely
# different sleep trigger. Then it arms a wake. Tests whether idle-triggered S3
# sleeps wake more reliably than API-triggered ones.
#
# The wake marker restores the idle timeout to disabled, and the task is registered
# RunLevel Highest so the marker can do that even on a power-button recovery.
param([int]$Min = 10, [int]$IdleSec = 180)
$Root = 'C:\Users\sh019\Documents\projects\mm-strat'
$WakeAt = (Get-Date).AddMinutes($Min)

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}\tools\_wake_marker.ps1"' -f $Root)
$trigger = New-ScheduledTaskTrigger -Once -At $WakeAt
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
try {
    Register-ScheduledTask -TaskName 'PrefectWakeTest' -Action $action -Trigger $trigger `
        -Settings $settings -RunLevel Highest -Force -ErrorAction Stop | Out-Null
    $info = Get-ScheduledTask -TaskName 'PrefectWakeTest' | Get-ScheduledTaskInfo
    Write-Host ("[OK] armed PrefectWakeTest for {0} (NextRun={1})" -f $WakeAt.ToString('HH:mm:ss'), $info.NextRunTime)
} catch {
    Write-Host ("[ERR] " + $_.Exception.Message); exit 1
}

& (Join-Path $Root 'scripts\wake_diag.ps1') -Phase pre   # /waketimers proof the alarm is armed

# Sentinel: the marker checks for a real sleep (event 42) after this time, so it
# can't falsely pass if the box never actually slept.
(Get-Date -Format 'o') | Out-File -FilePath (Join-Path $Root 'logs\prefect\wake_test_sentinel.txt') -Encoding utf8

# Set a short AC idle-sleep timeout so the box idle-sleeps (Reason 7) on its own.
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE $IdleSec 2>&1 | Out-Null
powercfg /setactive SCHEME_CURRENT 2>&1 | Out-Null
Write-Host ("[OK] AC idle-sleep timeout set to {0}s" -f $IdleSec)
Write-Host ("[..] STOP touching the box now (no keyboard/mouse). It should idle-sleep in ~{0}s;" -f $IdleSec)
Write-Host ("     wake armed for {0}. The marker restores the idle timeout to disabled on wake." -f $WakeAt.ToString('HH:mm:ss'))
