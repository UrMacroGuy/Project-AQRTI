@echo off
title AQRTI Backend
cd /d "%~dp0..\backend"

:: Prevent two copies of this restart-loop running at once. Without this, a
:: second launch would kill the first loop's backend (port-kill below) but
:: BOTH loops keep respawning independently forever, fighting over port 8000
:: -- the root cause of the "two Python interpreters for the same process"
:: symptom (each loop's own goto :loop spawns a fresh python.exe on its own
:: 3s timer, so you get two live backend processes alternately stealing the
:: port from each other).
set LOCKFILE=%~dp0..\backend\start_backend.lock
if exist "%LOCKFILE%" (
    echo [%time%] Another start_backend.bat loop appears to be running already.
    echo [%time%] If that's wrong ^(stale lock from a crash^), delete: %LOCKFILE%
    echo [%time%] Exiting so we don't fight the existing loop over port 8000.
    exit /b 1
)
echo. > "%LOCKFILE%"

:: Kill any process holding port 8000 (including stale backend loops)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING 2^>nul') do (
    echo [%time%] Killing PID %%a on port 8000
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 2 /nobreak >nul

:loop
echo [%time%] Starting AQRTI backend...
.venv\Scripts\python.exe main.py
echo [%time%] Backend stopped -- restarting in 3s...
timeout /t 3 /nobreak >nul
goto loop
