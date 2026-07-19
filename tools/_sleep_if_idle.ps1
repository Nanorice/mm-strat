# TEST backstop: force S3 sleep ONLY if no pipeline run is active, so it can
# never sleep the box mid-run. Used by the one-off PrefectSleepTest task.
$running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'run_daily_pipeline\.py' }
if (-not $running) {
    rundll32.exe powrprof.dll,SetSuspendState 0,1,0
}
