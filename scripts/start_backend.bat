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

:loop
echo [%time%] Starting AQRTI backend...
.venv\Scripts\python.exe main.py
echo [%time%] Backend stopped -- restarting in 5s...
timeout /t 5 /nobreak >nul
goto loop
