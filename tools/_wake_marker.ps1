# Wake-test proof action. Reports HOW the box actually woke (from powercfg
# /lastwake), so it cannot falsely claim a pass when the task merely ran late on
# an already-awake box (StartWhenAvailable catch-up) or after a power-button wake.
$ErrorActionPreference = 'SilentlyContinue'
$Root = 'C:\Users\sh019\Documents\projects\mm-strat'
& (Join-Path $Root 'scripts\wake_diag.ps1') -Phase post 2>&1 | Out-Null

# If the idle test set a short idle-sleep timeout, restore it to disabled (0) so the
# box can't immediately idle-sleep again and strand itself. Best-effort; only takes
# effect when this task runs elevated (the idle test registers it RunLevel Highest).
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP STANDBYIDLE 0 2>&1 | Out-Null
powercfg /setactive SCHEME_CURRENT 2>&1 | Out-Null

# Did the box ACTUALLY sleep since the test was armed? /lastwake persists from a
# previous wake, so it lies if the task merely fired on an awake box. Confirm a
# real sleep (Kernel-Power 42) occurred after the sentinel the arm script wrote.
$slept = $false
$sentinel = Join-Path $Root 'logs\prefect\wake_test_sentinel.txt'
if (Test-Path $sentinel) {
    try {
        $armedAt = [datetime]((Get-Content $sentinel -Raw).Trim())
        $slept = @(Get-WinEvent -FilterHashtable @{LogName = 'System'; ProviderName = 'Microsoft-Windows-Kernel-Power'; Id = 42; StartTime = $armedAt } -EA SilentlyContinue).Count -gt 0
    } catch {}
}

$lw = (& powercfg /lastwake | Out-String)
if (-not $slept) { $verdict = '[INCONCLUSIVE] box never slept after arming - task fired on an awake box' }
elseif ($lw -match 'Power Button') { $verdict = '[FAIL] woke by POWER BUTTON - timer did NOT fire' }
elseif ($lw -match 'Timer') { $verdict = '[OK] TIMER WAKE confirmed' }
else { $verdict = '[??] slept but wake source unclear - check wakediag log' }

$msg = "WAKE TEST @ $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss'): $verdict"
$line = Get-Content (Join-Path $Root '.env') | Where-Object { $_ -match '^\s*DISCORD_WEBHOOK_URL\s*=' } | Select-Object -First 1
$url = ($line -split '=', 2)[1].Trim().Trim('"').Trim("'")
if ($url) {
    $body = [System.Text.Encoding]::UTF8.GetBytes((@{ content = $msg } | ConvertTo-Json -Compress))
    try { Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/json; charset=utf-8' -Body $body -TimeoutSec 10 | Out-Null } catch {}
}
$msg | Out-File (Join-Path $Root 'logs\prefect\wake_marker.txt') -Append -Encoding utf8
