# Register (or re-register) the nightly pipeline as a Windows Scheduled Task (S4).
#
# Idempotent: unregisters any existing task of the same name first, then creates
# it fresh. Run from an ELEVATED PowerShell prompt (task registration needs admin
# unless you scope it to the current user with -CurrentUser).
#
#   powershell -ExecutionPolicy Bypass -File scripts/register_nightly_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/register_nightly_task.ps1 -At "06:30" -TaskName "Quantamental Nightly"
#
# Defaults: runs every day at 06:00 local time. Market data for the prior close
# is settled well before then; the pipeline targets "yesterday" by default.

param(
    [string]$TaskName = "QuantamentalNightlyPipeline",
    [string]$At = "06:00",
    [switch]$CurrentUser
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $ProjectRoot "scripts\run_nightly_pipeline.ps1"
if (-not (Test-Path $Launcher)) { throw "Launcher not found: $Launcher" }

# Run the .ps1 launcher under powershell.exe with an execution-policy bypass so
# the task isn't blocked by the machine's default policy.
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Launcher`"" `
    -WorkingDirectory $ProjectRoot

$Trigger = New-ScheduledTaskTrigger -Daily -At $At

# Wake the box if asleep; run whether or not the user is logged on; don't stop
# the run just because it crosses a battery/idle boundary.
$Settings = New-ScheduledTaskSettingsSet `
    -WakeToRun `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

# Remove any prior registration so this script is safe to re-run.
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Unregistering existing task '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$register = @{
    TaskName  = $TaskName
    Action    = $Action
    Trigger   = $Trigger
    Settings  = $Settings
    Description = "Nightly quantamental data pipeline + R2 dashboard sync (S4)."
}

if ($CurrentUser) {
    # Runs only when this user is logged on — no admin needed, no stored password.
    $register["User"] = "$env:USERDOMAIN\$env:USERNAME"
    $register["RunLevel"] = "Limited"
} else {
    # Run whether or not logged on, with highest privileges. Prompts for the
    # account password at registration (stored by Task Scheduler).
    $register["User"] = "$env:USERDOMAIN\$env:USERNAME"
    $register["RunLevel"] = "Highest"
    $register["LogonType"] = "S4U"  # run without storing the password; no network creds
}

Register-ScheduledTask @register | Out-Null

Write-Host "[OK] Registered '$TaskName' to run daily at $At."
Write-Host "     Launcher: $Launcher"
Write-Host "     Verify:   Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "     Test now: Start-ScheduledTask -TaskName '$TaskName'"
