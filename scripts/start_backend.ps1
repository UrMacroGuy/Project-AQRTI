# AQRTI Backend Watchdog
# Keeps the backend alive forever — restarts it automatically on crash or close.
# Run this once; leave the window open (minimise it).

$BackendDir = "$PSScriptRoot\..\backend"
$Python     = "$BackendDir\.venv\Scripts\python.exe"
$Script     = "$BackendDir\main.py"
$RestartDelay = 3   # seconds to wait before restarting after a crash

$host.UI.RawUI.WindowTitle = "AQRTI Backend (Watchdog)"

function Write-Status($msg, $color = "Cyan") {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $msg" -ForegroundColor $color
}

Write-Status "AQRTI Backend Watchdog started" "Green"
Write-Status "Python : $Python"
Write-Status "Script : $Script"
Write-Status "Auto-restart delay: ${RestartDelay}s"
Write-Host ""

$restarts = 0

while ($true) {
    if ($restarts -gt 0) {
        Write-Status "Restarting backend (attempt #$restarts)..." "Yellow"
        Start-Sleep -Seconds $RestartDelay
    }

    Write-Status "Starting backend..." "Green"

    try {
        $proc = Start-Process -FilePath $Python `
            -ArgumentList $Script `
            -WorkingDirectory $BackendDir `
            -PassThru `
            -WindowStyle Hidden

        Write-Status "Backend running (PID $($proc.Id))" "Green"
        $proc.WaitForExit()
        $exit = $proc.ExitCode
        Write-Status "Backend exited (code $exit)" "Red"
    } catch {
        Write-Status "Failed to start backend: $_" "Red"
    }

    $restarts++
}
