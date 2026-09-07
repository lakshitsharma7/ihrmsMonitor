[Setup]
AppName=iHRMS Monitor
AppVersion=2.0.1
DefaultDirName={autopf}\iHRMS Monitor
DefaultGroupName=iHRMS Monitor
OutputDir=installer
OutputBaseFilename=iHRMS-Monitor-Installer
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64

[Files]
Source: "dist\iHRMS Monitor\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\iHRMS Monitor"; Filename: "{app}\iHRMS Monitor.exe"
Name: "{commondesktop}\iHRMS Monitor"; Filename: "{app}\iHRMS Monitor.exe"

[Run]
Filename: "{app}\iHRMS Monitor.exe"; Description: "Launch iHRMS Monitor"; Flags: nowait postinstall skipifsilent
