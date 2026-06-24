# AQRTI Frontend Watchdog
# Serves the UI on port 3000, restarts on crash.

$UiDir        = "$PSScriptRoot\..\ui"
$RestartDelay = 3

$host.UI.RawUI.WindowTitle = "AQRTI Frontend (port 3000)"

function Write-Status($msg, $color = "Cyan") {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $msg" -ForegroundColor $color
}

Write-Status "AQRTI Frontend server starting on http://localhost:3000" "Green"

while ($true) {
    try {
        $proc = Start-Process -FilePath "python" `
            -ArgumentList "-m", "http.server", "3000" `
            -WorkingDirectory $UiDir `
            -PassThru `
            -WindowStyle Hidden
        $proc.WaitForExit()
        Write-Status "Frontend exited (code $($proc.ExitCode)) — restarting in ${RestartDelay}s..." "Yellow"
    } catch {
        Write-Status "Failed to start frontend: $_" "Red"
    }
    Start-Sleep -Seconds $RestartDelay
}
