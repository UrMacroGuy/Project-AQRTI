' Launches start_aqrti.bat with zero visible window. A cmd.exe shortcut's
' own WindowStyle property only minimizes (still flashes on screen);
' WScript.Shell.Run with windowStyle=0 is the actual "no window at all" path.
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\start_aqrti.bat"

Set shell = CreateObject("WScript.Shell")
shell.Run """" & batPath & """", 0, False
