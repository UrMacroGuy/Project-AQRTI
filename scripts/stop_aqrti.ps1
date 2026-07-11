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

# Kill the watchdog cmd.exe processes FIRST, before their python/node
# children. Each watchdog loop respawns its child within 3s of it dying
# (start_backend.bat/start_markov.bat/start_frontend.bat's "goto loop"), so
# killing the child before the parent risks a race where the still-alive
# watchdog spawns a replacement that survives this script. These run hidden
# (Start-Process -WindowStyle Hidden in start_aqrti.bat) so there's no
# visible window to close by title -- match on command line instead.
Get-CimInstance Win32_Process -Filter "Name='cmd.exe'" | ForEach-Object {
    $cmd = $_.CommandLine
    if ($cmd -and ($cmd -like "*start_backend.bat*" -or $cmd -like "*start_markov.bat*" -or $cmd -like "*start_frontend.bat*")) {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            Write-Status "Killed watchdog shell PID $($_.ProcessId): $cmd" "Red"
            $killed++
        } catch {
            Write-Status "Could not kill PID $($_.ProcessId): $_" "Red"
        }
    }
}

# Now kill the leaf python/node processes themselves.
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='node.exe'" | ForEach-Object {
    $cmd = $_.CommandLine
    if ($cmd -and ($cmd -like "*AQRTI*main.py*" -or $cmd -like "*strategy_loop_cycle.py*" -or $cmd -like "*ui*http.server*3000*" -or $cmd -like "*serve*ui*" -or $cmd -like "*markov.app*" -or $cmd -like "*http.server*3000*")) {
        try {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
            Write-Status "Killed PID $($_.ProcessId): $cmd" "Red"
            $killed++
        } catch {
            Write-Status "Could not kill PID $($_.ProcessId): $_" "Red"
        }
    }
}

# Clean up watchdog lock files — without this, a force-killed watchdog loop
# leaves start_backend.lock/start_markov.lock behind, and the next
# start_aqrti.bat run silently refuses to start that service (exits
# immediately thinking another loop is already running), which looks like
# "the backend/markov module just won't start" with no obvious cause.
$backendDir = Join-Path (Split-Path $PSScriptRoot -Parent) "backend"
foreach ($lock in @("start_backend.lock", "start_markov.lock")) {
    $lockPath = Join-Path $backendDir $lock
    if (Test-Path $lockPath) {
        Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
        Write-Status "Removed stale lock: $lock" "Red"
        $killed++
    }
}

if ($killed -eq 0) {
    Write-Status "Nothing was running." "Green"
} else {
    Write-Status "Stopped $killed process(es). AQRTI is fully stopped." "Green"
}

Start-Sleep -Seconds 2
