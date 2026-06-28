@echo off
title AQRTI Backend
cd /d "%~dp0..\backend"

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
