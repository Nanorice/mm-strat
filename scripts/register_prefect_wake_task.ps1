# Registers the wake task that powers the box on ~5 min before the nightly run.
#
# Prefect cannot wake the machine; this Task Scheduler task does. -WakeToRun
# wakes from sleep/hibernate (S1-S4) — NOT from a full shutdown (S5; that needs a
# BIOS "Resume by RTC Alarm"). Pair with: the Prefect cron at 22:00, the flow's
# sleep-on-completion hook, and Power Options -> "Allow wake timers = Enabled".
#
# Needs an ELEVATED PowerShell (writing the root task library requires admin).
param(
    [string]$TaskName = 'PrefectPipelineWake',
    [string]$At = '21:45'          # 15 min before the 22:00 run: margin for a late ACPI wake
)
$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
$WakeScript = Join-Path $Root 'scripts\wake_for_pipeline.ps1'

# A wake-timer wake is "unattended"; Windows then re-sleeps after the unattended
# sleep timeout (UNATTENDSLEEP, default 120s) BEFORE the wake task gets to run.
# That is what silently skipped the 2026-06-24 run. Widen it to 15 min on AC so
# the box stays up long enough for StartWhenAvailable to fire the wake task.
powercfg -attributes SUB_SLEEP 7bc4a2f9-d8fc-4469-b07b-33eb785aaca0 -ATTRIB_HIDE 2>&1 | Out-Null
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP 7bc4a2f9-d8fc-4469-b07b-33eb785aaca0 900 2>&1 | Out-Null
powercfg /setactive SCHEME_CURRENT 2>&1 | Out-Null
Write-Host "[OK] Set unattended sleep timeout (AC) = 900s"

# The box is put to sleep by the OS idle timeout (not a script): on this hardware
# an idle-triggered S3 sleep (Kernel-Power Reason 7) wakes reliably on the RTC
# timer, whereas a programmatic SetSuspendState (Reason 4) only fires ~50%. Keep
# hibernation OFF so the idle sleep is S3, never S4 (the RTC does NOT wake from S4;
# root cause of the missed 2026-06-26 wake). This also turns off Fast Startup.
powercfg /hibernate off 2>&1 | Out-Null
Write-Host "[OK] Hibernation disabled (suspends now go to S3, which wakes reliably)"

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{0}"' -f $WakeScript)

# Weekly Mon-Fri at $At, matching the pipeline's 0 22 * * 1-5 schedule.
$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday -At $At

$settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20)

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -RunLevel Limited -ErrorAction Stop | Out-Null
    Write-Host "[OK] Registered wake task '$TaskName' (wakes Mon-Fri at $At)"
    Write-Host "     Ensure Power Options -> Sleep -> 'Allow wake timers' = Enabled."
} catch {
    Write-Host "[ERR] Failed to register '$TaskName': $($_.Exception.Message)"
    Write-Host "      Run this from an ELEVATED PowerShell (Run as administrator)."
    exit 1
}
