#define MyAppName "GhostNet Receiver"
#define MyAppVersion "0.4.0"
#define MyAppExeName "GhostNetReceiver.exe"

[Setup]
AppId={{B8E21C4A-7D55-4F0A-9C3B-1A2E8F6D4C90}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppName}
AppCopyright=GPL-3.0-or-later
VersionInfoVersion=0.4.0.0
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
VersionInfoDescription=GhostNet Receiver Setup
VersionInfoOriginalFileName=GhostNetReceiverSetup.exe
VersionInfoCompany={#MyAppName}
DefaultDirName={localappdata}\Programs\GhostNetReceiver
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=ghostnet.ico
OutputDir=release
OutputBaseFilename=GhostNetReceiver-0.4.0-Setup
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
LicenseFile=LICENSE
InfoBeforeFile=QUICKSTART.md
; This build is intentionally unsigned.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "dist\GhostNetReceiver\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start GhostNet Receiver"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
