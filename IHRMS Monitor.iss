; Inno Setup script for iHRMS Monitor
; Use Inno Setup Compiler (https://jrsoftware.org/isinfo.php) to compile this into a Windows setup installer.

#ifndef MyAppVersion
#define MyAppVersion "1.0.0"
#endif

[Setup]
; A stable AppId is what lets a new build upgrade an existing install
; instead of appearing as a second program in Apps & Features.
AppId={{8F3C7A21-4B6D-4E15-9C2A-1D7E5B8A0342}
AppName=iHRMS Monitor
AppVersion={#MyAppVersion}
AppPublisher=Indovision Services
UninstallDisplayName=iHRMS Monitor
UninstallDisplayIcon={app}\iHRMS Monitor.exe

; Installed per user, into a writable location, for two reasons:
;   1. The app records its own auto-start entry under HKCU, which needs no
;      administrator rights.
;   2. It writes runtime files (screenshots) inside its own directory. Under
;      Program Files a standard user cannot write there and screenshot
;      capture would fail. Installing per user keeps the existing behaviour
;      working without changing any application code.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\iHRMS Monitor
DefaultGroupName=iHRMS Monitor
DisableProgramGroupPage=yes

; 64-bit build produced by PyInstaller.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; The app runs in the tray and auto-starts, so an upgrade will usually find
; it running; without this its files cannot be replaced.
CloseApplications=yes
RestartApplications=no

Compression=lzma2
SolidCompression=yes
OutputDir=dist\installer
OutputBaseFilename=iHRMSMonitorSetup
SetupIconFile=assets\ihrms-logo-icon.ico

[Files]
Source: "dist\iHRMS Monitor\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\iHRMS Monitor"; Filename: "{app}\iHRMS Monitor.exe"; \
    WorkingDir: "{app}"
Name: "{group}\Uninstall iHRMS Monitor"; Filename: "{uninstallexe}"
Name: "{autodesktop}\iHRMS Monitor"; Filename: "{app}\iHRMS Monitor.exe"; \
    WorkingDir: "{app}"

[Run]
Filename: "{app}\iHRMS Monitor.exe"; Description: "Launch iHRMS Monitor"; Flags: nowait postinstall skipifsilent

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
    ValueName: "ActivityTracker"; ValueType: none; \
    Flags: uninsdeletevalue dontcreatekey

[UninstallDelete]
; The app writes screenshots inside its own directory at runtime. Inno only
; removes what it installed, so these are cleared explicitly to avoid
; leaving the program folder behind after uninstalling.
Type: filesandordirs; Name: "{app}\_internal\screenshots"
Type: dirifempty; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"
