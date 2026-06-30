; Inno Setup script per Sonora
; Compila con:  ISCC.exe installer\sonora.iss   (richiede Inno Setup 6)
; Prima di compilare esegui la build:  pyinstaller build.spec --noconfirm

#define AppName "Sonora"
; AppVersion può essere passata dalla riga di comando (CI):
;   ISCC.exe /DAppVersion=1.6.0 installer\sonora.iss
#ifndef AppVersion
  #define AppVersion "1.5.7"
#endif
#define AppPublisher "Pisco Factory"
#define AppExe "Sonora.exe"

[Setup]
AppId={{C9D4E2F1-5A6B-4C7D-9E8F-SONORA000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=© 2026 {#AppPublisher}
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist_installer
OutputBaseFilename=SonoraSetup-{#AppVersion}
SetupIconFile=..\resources\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Auto-update: se Sonora è in esecuzione (avvio installer dall'app), chiudila
; per poter sovrascrivere i file, senza chiedere conferma all'utente.
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; Aggiornamento pulito: rimuove il payload della versione precedente PRIMA di
; copiare la nuova, così non restano file obsoleti (tipico con PyInstaller, dove
; il contenuto di _internal\ cambia tra build). Le impostazioni utente vivono in
; %APPDATA%\Sonora e NON vengono toccate.
Type: filesandordirs; Name: "{app}\_internal"
Type: files; Name: "{app}\Sonora.exe"

[Files]
; copia l'intera cartella prodotta da PyInstaller (onedir)
Source: "..\dist\Sonora\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Disinstalla {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
