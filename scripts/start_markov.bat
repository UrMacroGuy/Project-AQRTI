@echo off
title AQRTI Markov
cd /d "%~dp0..\backend"

:: Same lock pattern as start_backend.bat — prevents two watchdog loops
:: fighting over port 8001.
set LOCKFILE=%~dp0..\backend\start_markov.lock
if exist "%LOCKFILE%" (
    echo [%time%] Another start_markov.bat loop appears to be running already.
    echo [%time%] If that's wrong ^(stale lock from a crash^), delete: %LOCKFILE%
    echo [%time%] Exiting so we don't fight the existing loop over port 8001.
    exit /b 1
)
echo. > "%LOCKFILE%"

:: Kill any process holding port 8001 (including stale markov loops)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8001 " ^| findstr LISTENING 2^>nul') do (
    echo [%time%] Killing PID %%a on port 8001
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 2 /nobreak >nul

:loop
echo [%time%] Starting AQRTI Markov module (port 8001)...
.venv\Scripts\python.exe -m markov.app
echo [%time%] Markov module stopped -- restarting in 3s...
timeout /t 3 /nobreak >nul
goto loop
