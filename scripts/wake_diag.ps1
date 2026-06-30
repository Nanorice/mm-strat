# Wake-timer diagnostic snapshot. Captures the evidence open issue #1 needs:
# is the RTC wake timer actually ARMED at sleep time, and what woke (or failed to
# wake) the box. Distinguishes "timer never armed" from "armed but RTC missed".
#   -Phase pre   : run IMMEDIATELY before the box sleeps. /waketimers needs ELEVATION.
#   -Phase post  : run first thing on wake (what woke it, which sleep state it left).
# Appends to logs/prefect/wakediag_<date>.log; read alongside wake_<date>.log.
param([ValidateSet('pre', 'post')][string]$Phase = 'post')
$ErrorActionPreference = 'SilentlyContinue'

$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root 'logs\prefect'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir ('wakediag_{0}.log' -f (Get-Date -Format 'yyyy-MM-dd'))

function W($m) { ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m) | Out-File -FilePath $Log -Append -Encoding utf8 }
function Capture($name, $sb) {
    W ("----- {0} -----" -f $name)
    try { (& $sb | Out-String).TrimEnd() | Out-File -FilePath $Log -Append -Encoding utf8 }
    catch { W ("  <err> " + $_.Exception.Message) }
}

$elevated = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
W ("===== PHASE={0}  elevated={1} =====" -f $Phase, $elevated)

# Available sleep states — confirm S3 only (hibernate off), relevant both phases.
Capture 'powercfg /a' { powercfg /a }

if ($Phase -eq 'pre') {
    # THE missing evidence: is a wake timer armed, and for what time? Needs admin.
    if ($elevated) { Capture 'powercfg /waketimers' { powercfg /waketimers } }
    else { W '  /waketimers SKIPPED (not elevated) - re-run pre snapshot elevated' }

    # Does Windows think the wake task will run, and when?
    Capture 'wake task NextRunTime' {
        foreach ($t in 'PrefectPipelineWake', 'PrefectWakeTest') {
            $info = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue | Get-ScheduledTaskInfo -ErrorAction SilentlyContinue
            if ($info) { "{0}: NextRun={1} LastResult={2}" -f $t, $info.NextRunTime, $info.LastTaskResult }
        }
    }

    # Is "Allow wake timers" actually enabled on the active scheme (AC + DC)?
    Capture 'allow-wake-timers setting' {
        powercfg /query SCHEME_CURRENT SUB_SLEEP BD3B718A-0680-4D9D-8AB2-E1D2B4AC806D
    }
}
else {
    # What woke the box, and which sleep state did it actually enter last?
    Capture 'powercfg /lastwake' { powercfg /lastwake }
    Capture 'Kernel-Power 42 (last 3; state 4=S3, 5=S4 hibernate)' {
        Get-WinEvent -FilterHashtable @{LogName = 'System'; ProviderName = 'Microsoft-Windows-Kernel-Power'; Id = 42 } -MaxEvents 3 -ErrorAction SilentlyContinue |
            Select-Object TimeCreated, @{N = 'state'; E = { ([xml]$_.ToXml()).Event.EventData.Data | Where-Object { $_.Name -eq 'TargetState' } | ForEach-Object { $_.'#text' } } } |
            Format-Table -AutoSize | Out-String
    }
    Capture 'Power-Troubleshooter (last 3 wake sessions)' {
        Get-WinEvent -FilterHashtable @{LogName = 'System'; ProviderName = 'Microsoft-Windows-Power-Troubleshooter' } -MaxEvents 3 -ErrorAction SilentlyContinue |
            Select-Object TimeCreated, Message | Format-List | Out-String
    }
}
