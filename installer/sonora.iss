; Inno Setup script per Sonora
; Compila con:  ISCC.exe installer\sonora.iss   (richiede Inno Setup 6)
; Prima di compilare esegui la build:  pyinstaller build.spec --noconfirm

#define AppName "Sonora"
; AppVersion può essere passata dalla riga di comando (CI):
;   ISCC.exe /DAppVersion=1.6.0 installer\sonora.iss
#ifndef AppVersion
  #define AppVersion "1.5.2"
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

[Code]
var
  RemoveUserDataCheckBox: TNewCheckBox;
  RemoveUserData: Boolean;

// Pos() cercando a partire da StartPos (Inno Setup non ha PosEx built-in).
function PosFrom(const SubStr, S: String; StartPos: Integer): Integer;
var
  Found: Integer;
begin
  if StartPos < 1 then StartPos := 1;
  if StartPos > Length(S) then begin Result := 0; Exit; end;
  Found := Pos(SubStr, Copy(S, StartPos, Length(S) - StartPos + 1));
  if Found = 0 then
    Result := 0
  else
    Result := Found + StartPos - 1;
end;

// Estrae il valore stringa di una chiave JSON semplice: "key": "value".
// Basta per leggere stem_engine_dir da settings.json senza un parser JSON completo.
function ExtractJsonString(const Json, Key: String): String;
var
  P, PStart, PEnd: Integer;
begin
  Result := '';
  P := Pos('"' + Key + '"', Json);
  if P = 0 then Exit;
  P := PosFrom(':', Json, P);
  if P = 0 then Exit;
  P := PosFrom('"', Json, P);
  if P = 0 then Exit;
  PStart := P + 1;
  PEnd := PosFrom('"', Json, PStart);
  if PEnd = 0 then Exit;
  Result := Copy(Json, PStart, PEnd - PStart);
end;

function InitializeUninstall(): Boolean;
var
  Form: TSetupForm;
  Lbl: TNewStaticText;
  BtnOK, BtnCancel: TNewButton;
begin
  RemoveUserData := False;
  Result := True;
  if UninstallSilent() then
    Exit;   // disinstallazione silenziosa (/VERYSILENT): non bloccare su un dialog, tieni i dati

  Form := CreateCustomForm(ScaleX(380), ScaleY(160), False, False);
  try
    Form.Caption := 'Disinstalla {#AppName}';

    Lbl := TNewStaticText.Create(Form);
    Lbl.Parent := Form;
    Lbl.Left := ScaleX(16);
    Lbl.Top := ScaleY(16);
    Lbl.Width := Form.ClientWidth - ScaleX(32);
    Lbl.Height := ScaleY(70);
    Lbl.AutoSize := False;
    Lbl.WordWrap := True;
    Lbl.Caption :=
      'Vuoi rimuovere anche i dati utente (impostazioni, cronologia, sessioni ' +
      'mixer) e il motore di separazione stem (fino a ~3 GB) da %APPDATA%\Sonora?';

    RemoveUserDataCheckBox := TNewCheckBox.Create(Form);
    RemoveUserDataCheckBox.Parent := Form;
    RemoveUserDataCheckBox.Left := ScaleX(16);
    RemoveUserDataCheckBox.Top := Lbl.Top + Lbl.Height + ScaleY(8);
    RemoveUserDataCheckBox.Width := Form.ClientWidth - ScaleX(32);
    RemoveUserDataCheckBox.Caption := 'Rimuovi anche dati utente e motore stem (azione irreversibile)';
    RemoveUserDataCheckBox.Checked := False;

    BtnOK := TNewButton.Create(Form);
    BtnOK.Parent := Form;
    BtnOK.Width := ScaleX(75);
    BtnOK.Height := ScaleY(23);
    BtnOK.Left := Form.ClientWidth - ScaleX(75) - ScaleX(75) - ScaleX(16) - ScaleX(8);
    BtnOK.Top := Form.ClientHeight - ScaleY(23) - ScaleY(16);
    BtnOK.Caption := 'Continua';
    BtnOK.ModalResult := mrOk;
    BtnOK.Default := True;

    BtnCancel := TNewButton.Create(Form);
    BtnCancel.Parent := Form;
    BtnCancel.Width := ScaleX(75);
    BtnCancel.Height := ScaleY(23);
    BtnCancel.Left := Form.ClientWidth - ScaleX(75) - ScaleX(16);
    BtnCancel.Top := Form.ClientHeight - ScaleY(23) - ScaleY(16);
    BtnCancel.Caption := 'Annulla';
    BtnCancel.ModalResult := mrCancel;
    BtnCancel.Cancel := True;

    Form.ActiveControl := BtnOK;
    Form.FlipAndCenterIfNeeded(True, nil, False);

    if Form.ShowModal() = mrOk then
    begin
      RemoveUserData := RemoveUserDataCheckBox.Checked;
      Result := True;
    end
    else
      Result := False;
  finally
    Form.Free();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, SettingsFile, CustomEngineDir: String;
  JsonText: AnsiString;
begin
  if (CurUninstallStep = usPostUninstall) and RemoveUserData then
  begin
    DataDir := ExpandConstant('{userappdata}\Sonora');
    SettingsFile := DataDir + '\settings.json';
    // Il motore stem può vivere fuori da %APPDATA% se l'utente ha scelto una
    // cartella personalizzata (impostazione "stem_engine_dir"): rimuovila prima.
    if FileExists(SettingsFile) and LoadStringFromFile(SettingsFile, JsonText) then
    begin
      CustomEngineDir := ExtractJsonString(String(JsonText), 'stem_engine_dir');
      if (CustomEngineDir <> '') and DirExists(CustomEngineDir + '\stem-engine') then
        DelTree(CustomEngineDir + '\stem-engine', True, True, True);
    end;
    if DirExists(DataDir) then
      DelTree(DataDir, True, True, True);
  end;
end;
