@echo off
title AQRTI Paper Trading Agent
echo [%date% %time%] Paper Trading Agent started.
echo Runs daily paper trade cycle every 5 minutes while backend is live.
echo Press Ctrl+C to stop.
echo.

:loop
:: Check if backend is alive
curl -s --max-time 3 http://localhost:8000/health >nul 2>&1
if %errorlevel% neq 0 (
    echo [%time%] Backend offline — skipping cycle, retrying in 60s
    timeout /t 60 /nobreak >nul
    goto loop
)

:: Run a paper trade cycle
echo [%time%] Running paper trade cycle...
curl -s -X POST http://localhost:8000/admin/paper-trade --max-time 30 -o paper_agent_last.json 2>&1
if exist paper_agent_last.json (
    for /f "tokens=*" %%a in ('type paper_agent_last.json') do echo [%time%] Result: %%a
    del paper_agent_last.json >nul 2>&1
)

:: Wait 5 minutes before next cycle
echo [%time%] Next cycle in 5 minutes...
timeout /t 300 /nobreak >nul
goto loop
