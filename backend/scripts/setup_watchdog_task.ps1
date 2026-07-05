# GO-2: Register AQRTI backend + watchdog as Windows Scheduled Tasks
# Run this once as Administrator:
#   Right-click PowerShell → Run as Administrator
#   cd "C:\Users\praty\OneDrive\Desktop\Project AQRTI\backend\scripts"
#   .\setup_watchdog_task.ps1

$BackendDir = "C:\Users\praty\OneDrive\Desktop\Project AQRTI\backend"
$Python     = "$BackendDir\.venv\Scripts\python.exe"
$Scripts    = "$BackendDir\scripts"

# ── Task 1: AQRTI Backend (starts uvicorn on login) ──────────────────
$BackendAction  = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m uvicorn aqrti.api.app:app --host 0.0.0.0 --port 8000" `
    -WorkingDirectory $BackendDir

$BackendTrigger = New-ScheduledTaskTrigger -AtLogOn

$BackendSettings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([System.TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName "AQRTI Backend" `
    -Action $BackendAction `
    -Trigger $BackendTrigger `
    -Settings $BackendSettings `
    -RunLevel Highest `
    -Force

Write-Host "Registered: AQRTI Backend (starts at login)" -ForegroundColor Green

# ── Task 2: AQRTI Watchdog (pings /health, restarts on 3 failures) ───
$WatchdogAction  = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "`"$Scripts\watchdog.py`"" `
    -WorkingDirectory $BackendDir

$WatchdogTrigger = New-ScheduledTaskTrigger -AtLogOn

$WatchdogSettings = New-ScheduledTaskSettingsSet `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit ([System.TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName "AQRTI Watchdog" `
    -Action $WatchdogAction `
    -Trigger $WatchdogTrigger `
    -Settings $WatchdogSettings `
    -RunLevel Highest `
    -Force

Write-Host "Registered: AQRTI Watchdog (health-check loop)" -ForegroundColor Green

# ── Task 3: AQRTI Scheduler (standalone APScheduler process) ─────────────────
# Runs the scheduler in its own process so a heavy retrain/pipeline step
# cannot freeze the FastAPI dashboard.  The API detects scheduler.pid and
# skips starting its embedded scheduler automatically.
$SchedulerAction  = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument "-m aqrti.scheduler" `
    -WorkingDirectory $BackendDir

$SchedulerTrigger = New-ScheduledTaskTrigger -AtLogOn

$SchedulerSettings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([System.TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName "AQRTI Scheduler" `
    -Action $SchedulerAction `
    -Trigger $SchedulerTrigger `
    -Settings $SchedulerSettings `
    -RunLevel Highest `
    -Force

Write-Host "Registered: AQRTI Scheduler (standalone APScheduler process)" -ForegroundColor Green
Write-Host ""
Write-Host "All three tasks start at next login. To start now:" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName 'AQRTI Backend'"
Write-Host "  Start-ScheduledTask -TaskName 'AQRTI Watchdog'"
Write-Host "  Start-ScheduledTask -TaskName 'AQRTI Scheduler'"
