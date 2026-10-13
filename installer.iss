; Inno Setup script - run build.bat first (it produces dist\Lavati Downloader\).
#define AppName "Lavati Downloader"
#define AppVersion "0.2.0"
#define AppExe "Lavati Downloader.exe"
#ifndef DistDir
  #define DistDir "dist\Lavati Downloader"
#endif

[Setup]
AppId={{7C4A9E21-5B3D-4F68-A1E7-92D0C6B8F135}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Lavati Softwares
AppCopyright=Copyright (C) Lavati Softwares. MIT License.
AppPublisherURL=https://github.com/yuvarajkanesan/LavatiDownloader
AppSupportURL=https://github.com/yuvarajkanesan/LavatiDownloader/issues
VersionInfoCompany=Lavati Softwares
VersionInfoDescription=Lavati Downloader Setup
VersionInfoProductName=Lavati Downloader
VersionInfoVersion={#AppVersion}
WizardSizePercent=115
DisableProgramGroupPage=yes
AllowNoIcons=yes
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
SetupIconFile=build_scripts\app_icon.ico
OutputDir=dist
OutputBaseFilename=LavatiDownloader-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardImageFile=installer\wizard-large.bmp
WizardSmallImageFile=installer\wizard-small.bmp
LicenseFile=LICENSE.txt
InfoBeforeFile=installer\welcome.txt
DisableWelcomePage=no
DisableReadyPage=no
ShowLanguageDialog=no
SetupMutex=LavatiDownloaderSetupMutex
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
DirExistsWarning=no
UsePreviousTasks=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible

[Messages]
WelcomeLabel1=Welcome to Lavati Downloader
WelcomeLabel2=This will install Lavati Downloader {#AppVersion} on your computer.%n%nIt is recommended that you close other applications before continuing.
FinishedHeadingLabel=Lavati Downloader is ready
FinishedLabel=Setup has finished installing Lavati Downloader. Start it from the Start menu or the desktop shortcut.

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "autostart"; Description: "Start Lavati Downloader when I sign in to Windows"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "PRIVACY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "SECURITY.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "LavatiDownloader"; ValueData: """{app}\{#AppExe}"""; Tasks: autostart; Flags: uninsdeletevalue

; written by the app on first start; removed again so no dangling browser entries are left behind
Root: HKCU; Subkey: "Software\Google\Chrome\NativeMessagingHosts\com.lavati.idm_downloader"; Flags: dontcreatekey uninsdeletekey
Root: HKCU; Subkey: "Software\Microsoft\Edge\NativeMessagingHosts\com.lavati.idm_downloader"; Flags: dontcreatekey uninsdeletekey

[InstallDelete]
; a clean update: remove files of the previous version that the new one no longer ships
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  KeepData: Boolean;

function HasParam(const Name: String): Boolean;
var
  i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), Name) = 0 then Result := True;
end;

{ A short "free and open source" page, shown right after the license. }
procedure InitializeWizard();
var
  Page: TWizardPage;
  Info: TNewStaticText;
begin
  Page := CreateCustomPage(wpLicense, 'Free and open source',
    '{#AppName} is MIT licensed and free to use.');
  Info := TNewStaticText.Create(Page);
  Info.Parent := Page.Surface;
  Info.WordWrap := True;
  Info.AutoSize := False;
  Info.Width := Page.SurfaceWidth;
  Info.Height := ScaleY(80);
  Info.Caption := 'There are no ads, no accounts and no tracking. It is built in the open and anyone can read, change and share it.';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
begin
  if CurUninstallStep = usUninstall then
    { a running copy keeps its files locked, which would leave the folder behind }
    Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "{#AppExe}"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  if CurUninstallStep = usPostUninstall then
  begin
    if not KeepData then
    begin
      { download queue, segment state and settings }
      if DirExists(ExpandConstant('{localappdata}\idm-downloader')) then
        DelTree(ExpandConstant('{localappdata}\idm-downloader'), True, True, True);
      { the in-app "start on boot" switch writes this value itself }
      RegDeleteValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Run', 'LavatiDownloader');
    end;
    { the uninstaller lives inside the install folder, so remove it a moment after it exits;
      rmdir without /s only removes the folder when empty, so a shared folder is never wiped }
    Exec(ExpandConstant('{cmd}'), '/c ping 127.0.0.1 -n 3 >nul & del /q "' + ExpandConstant('{app}') + '\unins*.*" & rmdir "' + ExpandConstant('{app}') + '"', '', SW_HIDE, ewNoWait, Code);
  end;
end;

{ close a running copy before an update or uninstall touches its files }
function InitializeUninstall(): Boolean;
var
  Code: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM "{#AppExe}"', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /IM idm-native-host.exe', '', SW_HIDE, ewWaitUntilTerminated, Code);
  { silent uninstalls wipe everything unless started with /KEEPDATA; interactive ones ask (default: keep) }
  if UninstallSilent then
    KeepData := HasParam('/KEEPDATA')
  else
    KeepData := MsgBox('Keep your download list and settings?' + #13#10 + #13#10 +
      'Choose Yes to keep them for a future install, or No to remove all Lavati Downloader data. ' +
      'Downloaded files are never deleted.',
      mbConfirmation, MB_YESNO) = IDYES;
  Result := True;
end;

const
  UninstKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{7C4A9E21-5B3D-4F68-A1E7-92D0C6B8F135}_is1';

{ If a copy is already installed (per-user or all-users), say so and ask before upgrading it. }
function InitializeSetup(): Boolean;
var
  Ver, Msg: String;
begin
  Result := True;
  Ver := '';
  if not RegQueryStringValue(HKCU, UninstKey, 'DisplayVersion', Ver) then
    if not RegQueryStringValue(HKLM, UninstKey, 'DisplayVersion', Ver) then
      Ver := '';
  if (Ver <> '') and not WizardSilent then
  begin
    if CompareText(Ver, '{#AppVersion}') = 0 then
      Msg := '{#AppName} ' + Ver + ' is already installed on this computer.' + #13#10 + #13#10 +
             'Reinstall it? Your downloads and settings are kept.'
    else
      Msg := '{#AppName} ' + Ver + ' is already installed on this computer.' + #13#10 + #13#10 +
             'Upgrade it to version {#AppVersion}? Your downloads and settings are kept.';
    Result := MsgBox(Msg, mbConfirmation, MB_YESNO) = IDYES;
  end;
end;
