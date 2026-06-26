@echo off
title AQRTI Paper Trading Agent
chcp 65001 >nul
echo [%date% %time%] Paper Trading Agent started.
echo Runs mark-to-market every 5 minutes and full cycle once per day.
echo Press Ctrl+C to stop.
echo.

set LAST_FULL_CYCLE_DATE=NONE

:loop
:: Check if backend is alive
curl -s --max-time 3 http://localhost:8000/health >nul 2>&1
if %errorlevel% neq 0 (
    echo [%time%] Backend offline - skipping, retrying in 60s
    timeout /t 60 /nobreak >nul
    goto loop
)

:: Run mark-to-market (lightweight: SL/TP/expiry check)
echo [%time%] Running mark-to-market...
curl -s -X POST http://localhost:8000/admin/paper-mtm --max-time 30 >nul 2>&1

:: Run full paper trade cycle once per calendar day
for /f "tokens=*" %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
if not "%LAST_FULL_CYCLE_DATE%"=="%TODAY%" (
    echo [%time%] Running full paper trade cycle for %TODAY%...
    curl -s -X POST http://localhost:8000/admin/paper-trade --max-time 120 >nul 2>&1
    set LAST_FULL_CYCLE_DATE=%TODAY%
    echo [%time%] Full cycle done.
)

:: Wait 5 minutes before next tick
echo [%time%] Next MTM check in 5 minutes...
timeout /t 300 /nobreak >nul
goto loop