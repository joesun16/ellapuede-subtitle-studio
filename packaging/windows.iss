#ifndef AppDist
  #error AppDist is required
#endif
#ifndef InstallerOutput
  #error InstallerOutput is required
#endif
#ifndef AppVersion
#error AppVersion must be provided by package_installers.py
#endif
[Setup]
AppId={{92C71659-120F-4501-BBA1-2F7591B42E31}
AppName=EllaPuede Subtitle Extractor
AppVersion={#AppVersion}
AppPublisher=EllaPuede
DefaultDirName={localappdata}\Programs\EllaPuede
DefaultGroupName=EllaPuede
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.17763
OutputDir={#InstallerOutput}
OutputBaseFilename=EllaPuede-{#AppVersion}-Windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\app-icon.ico
UninstallDisplayIcon={app}\EllaPuede.exe
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
SetupLogging=yes
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked
[Files]
Source: "{#AppDist}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\EllaPuede"; Filename: "{app}\EllaPuede.exe"
Name: "{userdesktop}\EllaPuede"; Filename: "{app}\EllaPuede.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\EllaPuede.exe"; Description: "Launch EllaPuede"; Flags: nowait postinstall skipifsilent
