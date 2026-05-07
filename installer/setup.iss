; ============================================================
; 百度贴吧自动签到 - Inno Setup 安装脚本
; 用户级安装（无需管理员权限），默认装到 %LOCALAPPDATA%\Programs
; 通过 build.ps1 调用，版本号由命令行 /DMyAppVersion=x.y.z 注入
; ============================================================

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppName        "百度贴吧自动签到"
#define MyAppExeName     "BaiduTiebaSign.exe"
#define MyAppPublisher   "BaiduTiebaSign"
#define MyAppURL         "https://github.com/"

[Setup]
AppId={{E7F4A5C8-9D2B-4F1E-A6D0-1C3B5E7F9A2D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}

; 用户级安装（关键）：无需 UAC，安装到当前用户的 LocalAppData，
; 这样 exe 可以读写 config.json / sign.log 不受权限限制。
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
AllowNoIcons=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName} {#MyAppVersion}

OutputDir=out
OutputBaseFilename=BaiduTiebaSign-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=

; Windows 7 SP1 起可装
MinVersion=6.1sp1

[Languages]
Name: "chinesesimp"; MessagesFile: "ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{autoprograms}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 卸载时清理运行期产生的文件（用户已安装目录写入了 config.json / sign.log）
Type: files; Name: "{app}\config.json"
Type: files; Name: "{app}\sign.log"
