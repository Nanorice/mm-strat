# Arms a one-off wake (PrefectWakeTest) whose action revives the server + runs a
# fake job (_wake_revive_job_test.ps1). Pair with idle-sleep: run this, then leave
# the box untouched so it idle-sleeps (Reason 7, the trigger that wakes reliably).
# Needs ELEVATION (registering a wake task).
param([int]$Min = 10)
$Root = 'C:\Users\sh019\Documents\projects\mm-strat'
$WakeAt = (Get-Date).AddMinutes($Min)

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}\tools\_wake_revive_job_test.ps1"' -f $Root)
$trigger = New-ScheduledTaskTrigger -Once -At $WakeAt
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
try {
    Register-ScheduledTask -TaskName 'PrefectWakeTest' -Action $action -Trigger $trigger `
        -Settings $settings -RunLevel Highest -Force -ErrorAction Stop | Out-Null
    $info = Get-ScheduledTask -TaskName 'PrefectWakeTest' | Get-ScheduledTaskInfo
    Write-Host ("[OK] armed PrefectWakeTest for {0} (NextRun={1})" -f $WakeAt.ToString('HH:mm:ss'), $info.NextRunTime)
} catch {
    Write-Host ("[ERR] " + $_.Exception.Message); exit 1
}

# Temporarily shorten idle-sleep to 3 min so the box sleeps quickly for the test;
# the wake action restores it to 2h (prod) when it finishes.
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 180 2>&1 | Out-Null
powercfg /setactive SCHEME_CURRENT 2>&1 | Out-Null
Write-Host "[OK] idle-sleep temporarily set to 3 min for the test (restored to 2h on wake)"

& (Join-Path $Root 'scripts\wake_diag.ps1') -Phase pre
(Get-Date -Format 'o') | Out-File -FilePath (Join-Path $Root 'logs\prefect\wake_test_sentinel.txt') -Encoding utf8
Write-Host ("[..] now leave the box untouched. It idle-sleeps per your power plan, then wakes ~{0}." -f $WakeAt.ToString('HH:mm:ss'))
Write-Host "     Watch Discord: woke -> server revived -> serve restarted -> fake job armed -> job Completed."
