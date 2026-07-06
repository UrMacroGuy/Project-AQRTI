@echo off
title AQRTI Stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop_aqrti.ps1"
