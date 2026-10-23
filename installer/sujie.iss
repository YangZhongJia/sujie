; 速截 安装包脚本（Inno Setup 6）
; 编译：ISCC.exe installer\sujie.iss  （或执行 tools\package.ps1）
; 说明：默认按「为所有用户安装」提权安装到 Program Files，这样才能写防火墙规则；
;       传 /CURRENTUSER 可免提权装到 %LOCALAPPDATA%\Programs（此时跳过防火墙配置）。

#define AppName "速截"
#define AppShortName "速截"
; 版本号由 tools\package.ps1 用 /DAppVersion=<src/sujie/__init__.py> 传入，
; 单独手工编译时才回落到这里的默认值。
#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppPublisher "速截"
#define AppExe "速截.exe"

[Setup]
AppId={{8F3C1E4A-2B7D-4C55-9E8A-1D6F0B3A7C21}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppShortName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\dist\installer
OutputBaseFilename=速截-Setup-{#AppVersion}
SetupIconFile=..\assets\sujie.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog commandline
MinVersion=10.0
CloseApplications=yes
RestartApplications=no
AllowNoIcons=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式（按已选模式启动）"; GroupDescription: "附加任务："; Flags: checkedonce
Name: "autostart"; Description: "开机自动启动 速截"; GroupDescription: "附加任务："; Flags: checkedonce

[Files]
Source: "..\dist\{#AppShortName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\使用说明.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\速截（启动已选模式）"; Filename: "{app}\{#AppExe}"
Name: "{group}\只截图"; Filename: "{app}\{#AppExe}"; Parameters: "--mode screenshot"
Name: "{group}\只收图"; Filename: "{app}\{#AppExe}"; Parameters: "--mode receiver"
Name: "{group}\同时截图和收图"; Filename: "{app}\{#AppExe}"; Parameters: "--mode both"
Name: "{group}\选择本机工作模式"; Filename: "{app}\{#AppExe}"
Name: "{group}\使用说明"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\使用说明.md"""
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\速截（按设置模式启动）"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; 开机自启（HKCU；提权安装时仍是当前登录用户的注册表）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "速截"; ValueData: """{app}\{#AppExe}"""; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "速截Receiver"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "速截Client"; Flags: uninsdeletevalue

[Run]
; 放行接收端端口（程序级放行 + UDP 8766 局域网发现），只对专用/域网络生效；非提权安装时自动跳过
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""速截 Receiver"""; Flags: runhidden; StatusMsg: "配置防火墙…"; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""速截 Receiver"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=private,domain"; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""速截 Discovery"""; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""速截 Discovery"" dir=in action=allow protocol=UDP localport=8766 profile=private,domain"; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{app}\{#AppExe}"; Description: "选择此电脑的工作模式"; Flags: nowait postinstall skipifsilent
Filename: "{sys}\notepad.exe"; Parameters: """{app}\使用说明.md"""; Description: "打开使用说明"; Flags: postinstall skipifsilent unchecked nowait

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""速截 Receiver"""; Flags: runhidden; RunOnceId: "DelFwRule"; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""速截 Discovery"""; Flags: runhidden; RunOnceId: "DelFwDisc"; Check: IsAdminInstallMode

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
