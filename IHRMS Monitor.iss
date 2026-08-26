; Inno Setup script for IHRMS Monitor
; Use Inno Setup Compiler (https://jrsoftware.org/isinfo.php) to compile this into a Windows setup installer.

[Setup]
AppName=IHRMS Monitor
AppVersion=1.0.0
DefaultDirName={autopf}\IHRMS Monitor
DefaultGroupName=IHRMS Monitor
UninstallDisplayIcon={app}\IHRMS Monitor.exe
Compression=lzma2
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=IHRMSMonitorSetup
DisableProgramGroupPage=yes

[Files]
Source: "dist\IHRMS Monitor.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\IHRMS Monitor"; Filename: "{app}\IHRMS Monitor.exe"
Name: "{autodesktop}\IHRMS Monitor"; Filename: "{app}\IHRMS Monitor.exe"

[Run]
Filename: "{app}\IHRMS Monitor.exe"; Description: "Launch IHRMS Monitor"; Flags: nowait postinstall skipifsilent
