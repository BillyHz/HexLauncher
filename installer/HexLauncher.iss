; Compile with build.py: version and source paths come from the same build.
#ifndef AppVersion
  #error AppVersion is required. Run python build.py.
#endif
#ifndef NumericVersion
  #error NumericVersion is required. Run python build.py.
#endif
#ifndef ProjectRoot
  #error ProjectRoot is required. Run python build.py.
#endif

[Setup]
AppId={{2D188C74-33D6-4986-B173-461D356A6854}
AppName=HexLauncher
AppVersion={#AppVersion}
AppPublisher=HexLauncher
AppPublisherURL=https://github.com/BillyHz/HexLauncher
AppSupportURL=https://github.com/BillyHz/HexLauncher/issues
DefaultDirName={localappdata}\Programs\HexLauncher
DisableDirPage=no
UsePreviousAppDir=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
UsePreviousTasks=no
WizardStyle=modern
SetupIconFile={#ProjectRoot}\Hex.ico
UninstallDisplayIcon={app}\HexLauncher.exe
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=HexLauncher-Setup-v{#AppVersion}-windows-x64
VersionInfoVersion={#NumericVersion}
Compression=lzma2
SolidCompression=yes
CloseApplications=no
RestartApplications=no
UninstallDisplayName=HexLauncher

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; No unchecked flag: the optional desktop shortcut is selected by default.
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[CustomMessages]
spanish.LauncherLanguage=es
english.LauncherLanguage=en

[INI]
; Only installation defaults go here; existing JSON settings are never replaced.
Filename: "{app}\installation.ini"; Section: "HexLauncher"; Key: "language"; String: "{cm:LauncherLanguage}"

[Files]
Source: "{#ProjectRoot}\dist\HexLauncher.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#ProjectRoot}\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Dirs]
; Runtime data belongs to the player and is never removed by the uninstaller.
Name: "{app}\HexFiles"; Flags: uninsneveruninstall
Name: "{app}\HexMods\Fabric"; Flags: uninsneveruninstall
Name: "{app}\HexMods\Forge"; Flags: uninsneveruninstall
Name: "{app}\HexMods\NeoForge"; Flags: uninsneveruninstall
Name: "{app}\HexInstances"; Flags: uninsneveruninstall
Name: "{app}\HexJDK"; Flags: uninsneveruninstall
Name: "{app}\HexServer"; Flags: uninsneveruninstall
Name: "{app}\logs"; Flags: uninsneveruninstall

[Icons]
Name: "{userprograms}\HexLauncher\HexLauncher"; Filename: "{app}\HexLauncher.exe"; WorkingDir: "{app}"
Name: "{userdesktop}\HexLauncher"; Filename: "{app}\HexLauncher.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\HexLauncher.exe"; Description: "{cm:LaunchProgram,HexLauncher}"; Flags: nowait postinstall skipifsilent
