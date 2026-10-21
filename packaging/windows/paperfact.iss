; The Windows installer, compiled by scripts/build_app.py with Inno Setup 6:
;   ISCC /DAppVersion=0.2.0 /DSourceDir=dist\Paperfact /DOutputDir=dist paperfact.iss
;
; Installs for the current user only, under %LOCALAPPDATA%\Programs, so neither
; installing nor the in-app update asks for administrator rights. Papers and notes
; live in %APPDATA%\Paperfact, outside the install folder: uninstalling or updating
; never touches them.

#ifndef AppVersion
  #error AppVersion must be defined
#endif

[Setup]
; Fixed for the life of the app: Windows recognises a new version as an update of
; this one by it.
AppId={{6E0F4C2B-7D1A-4C8E-9B3F-2A5D8E1C4F70}
AppName=Paperfact
AppVersion={#AppVersion}
AppVerName=Paperfact {#AppVersion}
AppPublisher=Paperfact
AppPublisherURL=https://github.com/puddings-world/Paperfact
AppUpdatesURL=https://github.com/puddings-world/Paperfact/releases
LicenseFile=..\..\LICENSE
CreateUninstallRegKey=not IsAcceptanceTest
UsePreviousAppDir=not IsAcceptanceTest
UsePreviousGroup=not IsAcceptanceTest
UsePreviousTasks=not IsAcceptanceTest
DefaultDirName={localappdata}\Programs\Paperfact
DefaultGroupName=Paperfact
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir={#OutputDir}
OutputBaseFilename=Paperfact-{#AppVersion}-windows-x64-setup
SetupIconFile=..\..\assets\paper-daily.ico
UninstallDisplayIcon={app}\Paperfact.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; The in-app update runs this installer while the old copy is shutting down.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
; Inno Setup ships Traditional Chinese only as an unofficial translation, outside
; its installer: this copy is jrsoftware/issrc's, tag is-6_4_3.
Name: "zh_tw"; MessagesFile: "ChineseTraditional.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; A previous version's files that this one no longer ships.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Paperfact"; Filename: "{app}\Paperfact.exe"; Check: not IsAcceptanceTest
Name: "{autodesktop}\Paperfact"; Filename: "{app}\Paperfact.exe"; Tasks: desktopicon; Check: not IsAcceptanceTest

[Run]
; Not skipped in silent mode: the in-app update installs silently and expects the
; new version to open when it is done.
Filename: "{app}\Paperfact.exe"; Description: "{cm:LaunchProgram,Paperfact}"; Flags: nowait postinstall; Check: not IsAcceptanceTest

[Code]
function IsAcceptanceTest: Boolean;
begin
  Result := ExpandConstant('{param:ACCEPTANCETEST|0}') = '1';
end;

function InitializeSetup: Boolean;
begin
  Result := True;
  if IsAcceptanceTest and (ExpandConstant('{param:DIR|}') = '') then
  begin
    MsgBox('Acceptance testing requires an explicit /DIR.', mbError, MB_OK);
    Result := False;
  end;
end;
