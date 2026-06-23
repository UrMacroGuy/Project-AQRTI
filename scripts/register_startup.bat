@echo off
echo Registering AQRTI Git Agent to run at Windows startup...

schtasks /create /tn "AQRTI Git Agent" ^
  /tr "\"C:\Users\praty\AppData\Local\Programs\Python\Python312\python.exe\" \"C:\Users\praty\OneDrive\Desktop\Project AQRTI\scripts\git_agent.py\"" ^
  /sc onlogon ^
  /ru "%USERNAME%" ^
  /f

if %errorlevel% == 0 (
  echo.
  echo SUCCESS: AQRTI Git Agent will now start automatically when you log in.
  echo To remove: run unregister_startup.bat
) else (
  echo.
  echo ERROR: Failed to register. Try running as Administrator.
)

pause
