@echo off
title AQRTI Backend
cd /d "%~dp0..\backend"

:: Check if already running
curl -s --max-time 2 http://localhost:8000/health >nul 2>&1
if %errorlevel%==0 (
    echo [%time%] Backend already running on port 8000.
    exit /b 0
)

:: Kill anything stuck on port 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING 2^>nul') do (
    echo [%time%] Clearing port 8000 - killing PID %%a
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

:: LITE MODE = 1 disables the every-5-min strategy loop and hourly agents (saves ~500MB RAM)
:: Set to 0 to run full mode (strategy loop + agents run continuously)
set AQRTI_LITE_MODE=1

:loop
echo [%time%] Starting AQRTI backend (LITE_MODE=%AQRTI_LITE_MODE%)...
.venv\Scripts\python.exe main.py
echo [%time%] Backend stopped -- restarting in 3s...
timeout /t 3 /nobreak >nul
goto loop
