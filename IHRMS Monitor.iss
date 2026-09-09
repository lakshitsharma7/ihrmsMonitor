[Setup]
AppId={{8A8898F6-DFEE-4752-9A92-6F83BE800E5C}
AppName=iHRMS Monitor
AppVersion=2.0.1
DefaultDirName={autopf}\iHRMS Monitor
DefaultGroupName=iHRMS Monitor
OutputDir=installer
OutputBaseFilename=iHRMS-Monitor-Installer
SetupIconFile=assets\ihrms-logo-icon.ico
UninstallDisplayIcon={app}\iHRMS Monitor.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
CloseApplications=yes
RestartApplications=no

[Files]
Source: "dist\iHRMS Monitor\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "scripts\uninstall_notifier.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\iHRMS Monitor"; Filename: "{app}\iHRMS Monitor.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\iHRMS Monitor"; Filename: "{app}\iHRMS Monitor.exe"; WorkingDir: "{app}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "iHRMS Monitor"; ValueData: """{app}\iHRMS Monitor.exe"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\iHRMS Monitor.exe"; Description: "Launch iHRMS Monitor"; Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\uninstall_notifier.ps1"""; Flags: runhidden

