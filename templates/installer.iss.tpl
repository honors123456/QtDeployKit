; 本文件由 QtDeployKit 根据 templates/installer.iss.tpl 自动生成,请勿手改
; 要调整安装包行为,改模板后重新运行 deploy.py

#define MyAppName "@APP_NAME@"
#define MyAppVersion "@APP_VERSION@"
#define MyAppPublisher "@PUBLISHER@"
#define MyAppExeName "@EXE_NAME@"

[Setup]
; AppId 由应用名派生(uuid5),同一应用重复打包保持不变,升级安装可正确覆盖
AppId={{@APP_ID@}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=@OUTPUT_DIR@
OutputBaseFilename=@OUTPUT_BASENAME@
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
@ARCH_LINES@
; 默认装到 Program Files(需管理员),同时允许用户改选「仅为我安装」装到用户目录
; ——用户目录可写、免 UAC,是程序需要写自身目录时的逃生通道
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayIcon={app}\{#MyAppExeName}
@SETUP_ICON_LINE@

[Languages]
@LANGUAGE_LINES@

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "@DIST_DIR@\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: ".qtdeploykit"
@VCREDIST_FILE_LINE@

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
@VCREDIST_RUN_LINE@
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Code]
// 检测 VC++ 2015-2022 运行时是否已安装,已装则跳过静默安装步骤
function VCRedistInstalled: Boolean;
var
  Installed: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM64,
    'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\@ARCH@',
    'Installed', Installed) and (Installed = 1);
end;
