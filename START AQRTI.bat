@echo off
title AQRTI Launcher
echo.
echo  ==========================================
echo   AQRTI Intelligence Terminal
echo  ==========================================
echo.

REM Kill any existing instances on those ports first
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING" 2^>nul') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 " ^| findstr "LISTENING" 2^>nul') do taskkill /F /PID %%a >nul 2>&1

timeout /t 1 /nobreak >nul

REM Start backend watchdog (minimised, auto-restarts on crash)
start "AQRTI Backend" /MIN "%~dp0scripts\start_backend.bat"

REM Start frontend watchdog (minimised)
start "AQRTI Frontend" /MIN "%~dp0scripts\start_frontend.bat"

echo  Backend  starting on http://localhost:8000
echo  Frontend starting on http://localhost:3000
echo.
echo  Opening browser in 10 seconds...
timeout /t 10 /nobreak >nul
start http://localhost:3000

echo  Done. Both servers are running in the background.
echo  Close the minimised windows to stop them.
