; AQRTI Custom NSIS installer script
; Runs after electron-builder generates the standard installer sections.

!macro customInstall
  ; Create AQRTI data directory in %APPDATA%
  CreateDirectory "$APPDATA\AQRTI\data"
  CreateDirectory "$APPDATA\AQRTI\data\vault"
  CreateDirectory "$APPDATA\AQRTI\data\models"
  CreateDirectory "$APPDATA\AQRTI\data\backups"
  CreateDirectory "$APPDATA\AQRTI\data\logs"
  CreateDirectory "$APPDATA\AQRTI\data\research"
  CreateDirectory "$APPDATA\AQRTI\data\predictions"
!macroend

!macro customUninstall
  ; Ask before removing user data
  MessageBox MB_YESNO "Remove AQRTI data (database, models, vault)?" IDNO skip_data_remove
    RMDir /r "$APPDATA\AQRTI"
  skip_data_remove:
!macroend
