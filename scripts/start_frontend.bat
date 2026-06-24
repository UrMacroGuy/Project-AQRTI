@echo off
title AQRTI Frontend (port 3000)
cd /d "%~dp0..\ui"

REM Try venv python first, fall back to system python
set PYTHON=%~dp0..\backend\.venv\Scripts\python.exe
if not exist "%PYTHON%" set PYTHON=python

:loop
echo [%time%] Starting AQRTI frontend on http://localhost:3000
"%PYTHON%" -m http.server 3000
echo [%time%] Frontend stopped — restarting in 3s...
timeout /t 3 /nobreak >nul
goto loop
