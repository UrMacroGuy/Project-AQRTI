# AQRTI Stop — kills backend, frontend, and any strategy-loop subprocess,
# matched by command line (not just by port), so orphaned/duplicate
# processes get cleaned up too (this project has previously ended up with
# duplicate main.py processes from different Python interpreters).

$host.UI.RawUI.WindowTitle = "AQRTI Stop"

function Write-Status($msg, $color = "Cyan") {
    $ts = Get-Date -Format "HH:mm:ss"
    Write-Host "[$ts] $msg" -ForegroundColor $color
}

Write-Status "Stopping AQRTI..." "Yellow"

$killed = 0
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='node.exe'" | ForEach-Object {
    $cmd = $_.CommandLine
    if ($cmd -and ($cmd -like "*AQRTI*main.py*" -or $cmd -like "*strategy_loop_cycle.py*" -or $cmd -like "*ui*http.server*3000*" -or $cmd -like "*serve*ui*")) {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            Write-Status "Killed PID $($_.ProcessId): $cmd" "Red"
            $killed++
        } catch {
            Write-Status "Could not kill PID $($_.ProcessId): $_" "Red"
        }
    }
}

# Also close the watchdog cmd windows themselves so they don't just restart
# what we killed above.
Get-Process -Name "cmd" -ErrorAction SilentlyContinue | Where-Object {
    $_.MainWindowTitle -like "AQRTI*"
} | ForEach-Object {
    Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    Write-Status "Closed window: $($_.MainWindowTitle)" "Red"
    $killed++
}

if ($killed -eq 0) {
    Write-Status "Nothing was running." "Green"
} else {
    Write-Status "Stopped $killed process(es). AQRTI is fully stopped." "Green"
}

Start-Sleep -Seconds 2
