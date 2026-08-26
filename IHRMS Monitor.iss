; Inno Setup script for iHRMS Monitor
; Use Inno Setup Compiler (https://jrsoftware.org/isinfo.php) to compile this into a Windows setup installer.

[Setup]
AppName=iHRMS Monitor
AppVersion=1.0.0
DefaultDirName={autopf}\iHRMS Monitor
DefaultGroupName=iHRMS Monitor
UninstallDisplayIcon={app}\iHRMS Monitor.exe
Compression=lzma2
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=iHRMSMonitorSetup
DisableProgramGroupPage=yes

[Files]
Source: "dist\iHRMS Monitor.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\iHRMS Monitor"; Filename: "{app}\iHRMS Monitor.exe"
Name: "{autodesktop}\iHRMS Monitor"; Filename: "{app}\iHRMS Monitor.exe"

[Run]
Filename: "{app}\iHRMS Monitor.exe"; Description: "Launch iHRMS Monitor"; Flags: nowait postinstall skipifsilent
