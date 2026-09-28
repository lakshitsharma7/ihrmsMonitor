#ifndef MyAppVersion
#define MyAppVersion "1.0"
#endif

[Setup]
AppId={{8A8898F6-DFEE-4752-9A92-6F83BE800E5C}
AppName=Workpulse
AppVersion={#MyAppVersion}
VersionInfoVersion={#MyAppVersion}
DefaultDirName={autopf}\Workpulse
DefaultGroupName=Workpulse
UsePreviousAppDir=no
OutputDir=installer
OutputBaseFilename=WorkpulseSetup
SetupIconFile=assets\ihrms-logo-icon.ico
UninstallDisplayIcon={app}\Workpulse.exe
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
CloseApplications=force
RestartApplications=no

[Files]
Source: "dist\Workpulse\Workpulse.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Workpulse\_internal\*"; DestDir: "{app}\_internal"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "scripts\uninstall_notifier.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\Workpulse"; Filename: "{app}\Workpulse.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Workpulse"; Filename: "{app}\Workpulse.exe"; WorkingDir: "{app}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Workpulse"; ValueData: """{app}\Workpulse.exe"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Workpulse.exe"; Description: "Launch Workpulse"; Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\uninstall_notifier.ps1"""; Flags: runhidden
