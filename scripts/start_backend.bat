@echo off
title AQRTI Backend (watchdog)
cd /d "%~dp0..\backend"

:loop
echo [%time%] Starting AQRTI backend...
.venv\Scripts\python.exe main.py
echo [%time%] Backend stopped (exit code %errorlevel%) — restarting in 3s...
timeout /t 3 /nobreak >nul
goto loop
