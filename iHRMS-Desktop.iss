#ifndef MyAppVersion
#define MyAppVersion "1.0.0"
#endif

[Setup]
AppId={{8A8898F6-DFEE-4752-9A92-6F83BE800E5C}
AppName=iHRMS Desktop
AppVersion={#MyAppVersion}
AppPublisher=Indovision Services Private Limited
AppPublisherURL=https://indovisionservices.in
AppSupportURL=https://indovisionservices.in
AppUpdatesURL=https://indovisionservices.in
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany=Indovision Services Private Limited
VersionInfoDescription=iHRMS Desktop Setup
VersionInfoCopyright=Copyright (C) 2026 Indovision Services Private Limited
VersionInfoProductName=iHRMS Desktop
DefaultDirName={autopf}\iHRMS Desktop
DefaultGroupName=iHRMS Desktop
UsePreviousAppDir=yes
OutputDir=dist\Windows
OutputBaseFilename=iHRMS-Desktop-Setup-{#MyAppVersion}
SetupIconFile=assets\ihrms-logo-icon.ico
UninstallDisplayIcon={app}\iHRMS-Desktop.exe
Compression=lzma2/ultra64
SolidCompression=yes
LZMADictionarySize=65536
LZMAUseSeparateProcess=yes
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
CloseApplications=force
#ifdef SignToolName
SignTool={#SignToolName}
SignedUninstaller=yes
#endif

[Files]
Source: "dist\iHRMS-Desktop\iHRMS-Desktop.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\iHRMS-Desktop\iHRMS-Supervisor.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\iHRMS-Desktop\_internal\*"; DestDir: "{app}\_internal"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "scripts\uninstall_notifier.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "scripts\register_task.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\iHRMS Desktop"; Filename: "{app}\iHRMS-Desktop.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\iHRMS Desktop"; Filename: "{app}\iHRMS-Desktop.exe"; WorkingDir: "{app}"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "iHRMS Desktop"; ValueData: """{app}\iHRMS-Supervisor.exe"" --startup"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Indovision\iHRMSMonitor"; Flags: uninsdeletekey

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\register_task.ps1"" -AppDir ""{app}"""; Flags: runhidden
Filename: "{app}\iHRMS-Supervisor.exe"; Parameters: "--startup"; Description: "Launch iHRMS Desktop"; Flags: nowait postinstall skipifsilent; WorkingDir: "{app}"

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""Unregister-ScheduledTask -TaskName ('iHRMSDesktopAutoRestart-' + $env:USERNAME) -Confirm:$false -ErrorAction SilentlyContinue"""; Flags: runhidden
Filename: "powershell.exe"; Parameters: "-NoProfile -Command ""Stop-Process -Name 'iHRMS-Desktop','iHRMS-Supervisor' -Force -ErrorAction SilentlyContinue"""; Flags: runhidden
Filename: "powershell.exe"; Parameters: "-NoProfile -Command ""cmdkey /delete:iHRMS_Desktop:session 2>$null"""; Flags: runhidden
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\scripts\uninstall_notifier.ps1"""; Flags: runhidden

[Code]
function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  // Terminate any running application or supervisor processes before file replacement
  Exec('taskkill.exe', '/F /IM iHRMS-Desktop.exe', '', SW_HIDE, ewWaitUntilTerminated, ErrorCode);
  Exec('taskkill.exe', '/F /IM iHRMS-Supervisor.exe', '', SW_HIDE, ewWaitUntilTerminated, ErrorCode);
  Exec('taskkill.exe', '/F /IM Workpulse.exe', '', SW_HIDE, ewWaitUntilTerminated, ErrorCode);
  Exec('taskkill.exe', '/F /IM "iHRMS Monitor.exe"', '', SW_HIDE, ewWaitUntilTerminated, ErrorCode);
  Result := True;
end;

