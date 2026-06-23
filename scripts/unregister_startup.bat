@echo off
echo Removing AQRTI Git Agent from Windows startup...

schtasks /delete /tn "AQRTI Git Agent" /f

if %errorlevel% == 0 (
  echo SUCCESS: AQRTI Git Agent removed from startup.
) else (
  echo ERROR: Task not found or could not be removed.
)

pause
