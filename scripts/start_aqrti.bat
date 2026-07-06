@echo off
title AQRTI Launcher
cd /d "%~dp0"

echo [%time%] Stopping any existing AQRTI backend/frontend first...
call "%~dp0stop_aqrti.bat" >nul 2>&1

echo [%time%] Starting AQRTI backend (watchdog, minimized)...
start "AQRTI Backend" /min cmd /c "%~dp0start_backend.bat"

timeout /t 3 /nobreak >nul

echo [%time%] Starting AQRTI frontend (watchdog, minimized)...
start "AQRTI Frontend" /min cmd /c "%~dp0start_frontend.bat"

timeout /t 3 /nobreak >nul

echo [%time%] Opening AQRTI in your browser...
start "" "http://localhost:3000"

echo.
echo AQRTI is starting up. Backend + Frontend windows are running minimized
echo in your taskbar. Give it 30-60 seconds to finish booting (market data,
echo predictions, etc.) before the dashboard shows full data.
echo.
echo To stop AQRTI, use the "Stop AQRTI" shortcut on your Desktop.
echo.
pause
