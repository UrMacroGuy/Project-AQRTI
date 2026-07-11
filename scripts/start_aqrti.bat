@echo off
title AQRTI Launcher
cd /d "%~dp0"

echo [%time%] Stopping any existing AQRTI backend/markov/frontend first...
call "%~dp0stop_aqrti.bat" >nul 2>&1

echo [%time%] Starting AQRTI backend, Markov module, and frontend (all hidden, single launcher)...

:: All three watchdog loops run fully hidden (no visible windows), each
:: still its own independent process with its own crash-restart loop
:: (start_backend.bat / start_markov.bat / start_frontend.bat) -- only the
:: "3 separate visible windows" UX changed, not the crash-isolation between
:: services. Delegated to a .ps1 (start_aqrti_hidden.ps1) instead of inline
:: powershell -Command strings, since nested quoting across
:: cmd -> powershell-string -> Start-Process-ArgumentList is fragile and
:: hard to verify; a real .ps1 file is not.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_aqrti_hidden.ps1" -ScriptsDir "%~dp0."

timeout /t 3 /nobreak >nul

echo [%time%] Opening AQRTI in your browser...
start "" "http://localhost:3000"

echo.
echo AQRTI is starting up in the background (no separate windows to manage).
echo Give it 30-60 seconds to finish booting (market data, predictions, etc.)
echo before the dashboard shows full data.
echo.
echo To stop AQRTI, use the "Stop AQRTI" shortcut on your Desktop.
echo.
pause
