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

echo  Waiting for backend to come online...
:wait_backend
timeout /t 2 /nobreak >nul
curl -s --max-time 2 http://localhost:8000/health >nul 2>&1
if %errorlevel% neq 0 goto wait_backend
echo  Backend is online!

REM Start paper trading agent (runs every 5 min, auto-marks-to-market)
start "AQRTI Paper Agent" /MIN "%~dp0scripts\paper_trading_agent.bat"

echo.
echo  Backend  running on  http://localhost:8000
echo  Frontend running on  http://localhost:3000
echo  Paper agent running (every 5 min)
echo.
echo  Opening browser...
start http://localhost:3000

echo  Done. All services running. Close minimised windows to stop.
