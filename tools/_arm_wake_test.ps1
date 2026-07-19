# Arms a one-off PrefectWakeTest to wake the box in $Min minutes and run the
# lightweight wake marker. Reports whether the wake timer actually armed.
# With -Sleep: also snapshots /waketimers (proof armed) then sleeps the box (S3),
# so the whole sleep->wake test runs from one elevated command. Needs ELEVATION.
param([int]$Min = 5, [switch]$Sleep)
$Root = 'C:\Users\sh019\Documents\projects\mm-strat'
$WakeAt = (Get-Date).AddMinutes($Min)
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}\tools\_wake_marker.ps1"' -f $Root)
$trigger = New-ScheduledTaskTrigger -Once -At $WakeAt
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
try {
    Register-ScheduledTask -TaskName 'PrefectWakeTest' -Action $action -Trigger $trigger `
        -Settings $settings -RunLevel Limited -Force -ErrorAction Stop | Out-Null
    $info = Get-ScheduledTask -TaskName 'PrefectWakeTest' | Get-ScheduledTaskInfo
    Write-Host ("[OK] armed PrefectWakeTest for {0} (NextRun={1})" -f $WakeAt.ToString('HH:mm:ss'), $info.NextRunTime)
} catch {
    Write-Host ("[ERR] " + $_.Exception.Message)
    exit 1
}

# Capture /waketimers proof the alarm is armed (visible while awake, before sleep).
& (Join-Path $Root 'scripts\wake_diag.ps1') -Phase pre

# Sentinel: the marker checks for a real sleep (event 42) after this time, so it
# can't falsely pass if the box never actually slept.
(Get-Date -Format 'o') | Out-File -FilePath (Join-Path $Root 'logs\prefect\wake_test_sentinel.txt') -Encoding utf8

if ($Sleep) {
    Write-Host ("[..] sleeping now (S3); box should wake ~{0}" -f $WakeAt.ToString('HH:mm:ss'))
    Start-Sleep -Seconds 2
    rundll32.exe powrprof.dll,SetSuspendState 0,1,0
}
else {
    Write-Host ("[..] now leave the box idle (it sleeps per your power-plan timeout) OR sleep it manually. Wake armed ~{0}" -f $WakeAt.ToString('HH:mm:ss'))
}
