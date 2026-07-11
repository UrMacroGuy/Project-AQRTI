@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0test_hidden.ps1" -ScriptsDir "%~dp0."
