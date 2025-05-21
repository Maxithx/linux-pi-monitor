; Inno Setup script for Raspberry Pi Monitor Installer
; Lavet af THXMAN

#define MyAppName "Raspberry Pi Monitor"
#define MyAppVersion "1.0"
#define MyAppPublisher "THXMAN"
#define MyAppExeName "app.exe"

[Setup]
AppId={{E0E0292A-88DD-4875-9C21-AEDEA4F490C6}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
UninstallDisplayIcon={app}\raspberry_pi_monitor_generated_icon.ico
OutputDir=G:\hjaelpnu_mobilapp\Rasp-pi-monitor\output_setup
OutputBaseFilename=Raspberry Pi Monitor
SetupIconFile=G:\hjaelpnu_mobilapp\Rasp-pi-monitor\raspberry_pi_monitor_generated_icon.ico
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "G:\hjaelpnu_mobilapp\Rasp-pi-monitor\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "G:\hjaelpnu_mobilapp\Rasp-pi-monitor\static\*"; DestDir: "{app}\static"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "G:\hjaelpnu_mobilapp\Rasp-pi-monitor\templates\*"; DestDir: "{app}\templates"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "G:\hjaelpnu_mobilapp\Rasp-pi-monitor\raspberry_pi_monitor_generated_icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\raspberry_pi_monitor_generated_icon.ico"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Start {#MyAppName}"; Flags: nowait postinstall skipifsilent
