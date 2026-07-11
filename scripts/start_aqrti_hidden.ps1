# Launches the three AQRTI watchdog loops (backend, markov, frontend) as
# hidden background processes, each independently crash-restarting via its
# own start_*.bat loop. Called from start_aqrti.bat so all escaping/quoting
# happens once, here, in a normal PowerShell script -- not nested inside a
# cmd.exe -> "powershell -Command '...'" string, which is fragile and hard
# to verify by inspection across three layers of shell quoting.

param(
    [Parameter(Mandatory = $true)]
    [string]$ScriptsDir
)

$services = @("start_backend.bat", "start_markov.bat", "start_frontend.bat")

foreach ($svc in $services) {
    $path = Join-Path $ScriptsDir $svc
    if (-not (Test-Path $path)) {
        Write-Host "MISSING: $path" -ForegroundColor Red
        continue
    }
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "`"$path`"" -WindowStyle Hidden
    Write-Host "Started (hidden): $svc"
}
