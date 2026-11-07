; Inno Setup 6 script for the SolidSeas Viewer installer, SolidSeas-Setup-<version>.exe.
;
; scripts\build-installer.ps1 builds the one-folder viewer (scripts\build-viewer.ps1
; -OneFolder) and then compiles this script with ISCC.exe, passing:
;
;   /DAppVersion=<version>      from src\solidseas\__init__.py (required)
;   /DViewerDir=<folder>        the one-folder build, dist\SolidSeasViewer (required)
;   /DIconFile=<file.ico>       the program's icon, drawn by solidseas_app.viewer.icon
;   /DExtensionsDir=<folder>    optional: a folder of extension packages (.zip) to install
;   /DOutputDir=<folder>        where the installer goes, dist by default
;
; What it does: installs the folder for the current user, with no administrator rights, in
; %LOCALAPPDATA%\Programs\SolidSeas (an administrator can choose to install for all users,
; in Program Files), adds a Start menu entry and, if asked, a desktop shortcut, and registers
; an uninstaller in Settings > Apps (Programs and Features). It adds no file associations,
; services, firewall rules or anything else that needs an administrator.
;
; Extension packages given at build time go into {app}\SolidSeas extensions, one of the
; folders the viewer reads beside itself (solidseas_app.extensions.BESIDE_FOLDERS): it adds
; them, switched off, the next time it starts. That folder belongs to the installer, which
; replaces its zip files on each install that carries packages.
;
; The viewer keeps its settings in %APPDATA%\SolidSeas and its caches in %LOCALAPPDATA%.
; Neither is touched by installing, upgrading or uninstalling: uninstalling removes only
; the files this installer put in {app}.

#ifndef AppVersion
  #error Pass the version: ISCC /DAppVersion=<version> (scripts\build-installer.ps1 does)
#endif
#ifndef ViewerDir
  #error Pass the one-folder build: ISCC /DViewerDir=<dist\SolidSeasViewer>
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define AppName "SolidSeas Viewer"
#define AppExe "SolidSeasViewer.exe"
#define AppUrl "https://github.com/SolidSeasOrg/Solidseas"

[Setup]
; The AppId stays the same for every release, so a new version upgrades the old one in place.
AppId={{E5DE8A19-905E-4947-9398-EB4442E16FAE}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=SolidSeas
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
DefaultDirName={autopf}\SolidSeas
DefaultGroupName=SolidSeas
DisableProgramGroupPage=yes
; Per user, with no administrator rights; the first page lets an administrator install for
; all users instead.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
LicenseFile=..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=SolidSeas-Setup-{#AppVersion}
#ifdef IconFile
SetupIconFile={#IconFile}
#endif
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; A running viewer installed here is closed before its files are replaced or removed (see
; [Code]: its worker processes have no window, so the Restart Manager alone cannot close
; them, and closing the viewer's window ends them). The Restart Manager stays on for anything
; else that holds the program's files. The viewer is not started again afterwards; the last
; page offers to start it.
CloseApplications=yes
CloseApplicationsFilter=*.exe,*.dll,*.pyd
RestartApplications=no
ChangesAssociations=no
ChangesEnvironment=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; The program's own libraries from the version before, so a library the new version no
; longer carries is not left behind. Only files this installer put there.
Type: filesandordirs; Name: "{app}\_internal"
#ifdef ExtensionsDir
Type: files; Name: "{app}\SolidSeas extensions\*.zip"
#endif

[Files]
Source: "{#ViewerDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
#ifdef ExtensionsDir
Source: "{#ExtensionsDir}\*.zip"; DestDir: "{app}\SolidSeas extensions"; Flags: ignoreversion skipifsourcedoesntexist
#endif

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
// Close the SolidSeas Viewer that runs from Dir, through its main window, as a person closing
// it would: that ends its worker processes too. A copy of the viewer that runs from anywhere
// else (the single-file program, another install) is left alone. Waits up to 20 seconds.
function CloseInstalledViewer(Dir: String): Boolean;
var
  Find, Script: String;
  Code: Integer;
begin
  StringChangeEx(Dir, '''', '''''', True);
  Find := '@(Get-Process -Name SolidSeasViewer -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith(''' + Dir + '\'', [StringComparison]::OrdinalIgnoreCase) })';
  Script := '$p = ' + Find + '; if ($p.Count -eq 0) { exit 0 }; ' +
    '$p | ForEach-Object { [void]$_.CloseMainWindow() }; $end = (Get-Date).AddSeconds(20); ' +
    'while ((Get-Date) -lt $end) { Start-Sleep -Milliseconds 300; $p = ' + Find + '; if ($p.Count -eq 0) { exit 0 } }; exit 1';
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    '-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "' + Script + '"',
    '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if DirExists(ExpandConstant('{app}')) and not CloseInstalledViewer(ExpandConstant('{app}')) then
    Result := 'SolidSeas Viewer is still running and did not close. Close it, then run Setup again.';
end;

function InitializeUninstall(): Boolean;
begin
  Result := CloseInstalledViewer(ExpandConstant('{app}'));
  if not Result then
    SuppressibleMsgBox('SolidSeas Viewer is still running and did not close. Close it, then uninstall again.',
      mbError, MB_OK, IDOK);
end;
