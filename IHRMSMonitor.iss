; Inno Setup script for IHRMS Monitor
; Use Inno Setup Compiler (https://jrsoftware.org/isinfo.php) to compile this into a Windows setup installer.

[Setup]
AppName=IHRMS Monitor
AppVersion=1.0.0
DefaultDirName={autopf}\IHRMSMonitor
DefaultGroupName=IHRMS Monitor
UninstallDisplayIcon={app}\IHRMSMonitor.exe
Compression=lzma2
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=IHRMSMonitorSetup
DisableProgramGroupPage=yes

[Files]
Source: "dist\IHRMSMonitor.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\IHRMS Monitor"; Filename: "{app}\IHRMSMonitor.exe"
Name: "{autodesktop}\IHRMS Monitor"; Filename: "{app}\IHRMSMonitor.exe"

[Run]
Filename: "{app}\IHRMSMonitor.exe"; Description: "Launch IHRMS Monitor"; Flags: nowait postinstall skipifsilent
