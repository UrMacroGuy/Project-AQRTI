@echo off
title AQRTI Git Agent
echo =======================================
echo   AQRTI Git Agent — Auto Commit/Push
echo =======================================
echo.
echo Watching for changes in Project AQRTI...
echo Press Ctrl+C to stop (commits pending changes first)
echo.

cd /d "%~dp0.."
"C:\Users\praty\AppData\Local\Programs\Python\Python312\python.exe" scripts\git_agent.py

pause
