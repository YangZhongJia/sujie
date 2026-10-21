; ShotBridge 安装包脚本（Inno Setup 6）
; 编译：ISCC.exe installer\shotbridge.iss  （或执行 tools\package.ps1）
; 说明：默认按「为所有用户安装」提权安装到 Program Files，这样才能写防火墙规则；
;       传 /CURRENTUSER 可免提权装到 %LOCALAPPDATA%\Programs（此时跳过防火墙配置）。

#define AppName "ShotBridge 截图桥"
#define AppShortName "ShotBridge"
#define AppVersion "1.0.0"
#define AppPublisher "ShotBridge"
#define AppExe "ShotBridge.exe"

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
OutputBaseFilename=ShotBridge-Setup-{#AppVersion}
SetupIconFile=..\assets\shotbridge.ico
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
Name: "desktopicon"; Description: "创建桌面快捷方式（截图端）"; GroupDescription: "附加任务："; Flags: checkedonce
Name: "autostart"; Description: "开机自动启动截图端（悬浮球）"; GroupDescription: "附加任务："; Flags: checkedonce
Name: "receiverstart"; Description: "安装完成后立即启动接收端（这台电脑负责接收）"; GroupDescription: "附加任务："; Flags: unchecked

[Files]
Source: "..\dist\{#AppShortName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\使用说明.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
Name: "{group}\截图端（悬浮球）"; Filename: "{app}\{#AppExe}"
Name: "{group}\接收端（托盘服务）"; Filename: "{app}\{#AppExe}"; Parameters: "--receiver"
Name: "{group}\使用说明"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\使用说明.md"""
Name: "{group}\卸载 {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; 开机自启（HKCU；提权安装时仍是当前登录用户的注册表）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "ShotBridgeClient"; ValueData: """{app}\{#AppExe}"""; Tasks: autostart; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "ShotBridgeReceiver"; Flags: uninsdeletevalue

[Run]
; 放行接收端端口（程序级放行 + UDP 8766 局域网发现），只对专用/域网络生效；非提权安装时自动跳过
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""ShotBridge Receiver"""; Flags: runhidden; StatusMsg: "配置防火墙…"; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""ShotBridge Receiver"" dir=in action=allow program=""{app}\{#AppExe}"" enable=yes profile=private,domain"; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""ShotBridge Discovery"""; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""ShotBridge Discovery"" dir=in action=allow protocol=UDP localport=8766 profile=private,domain"; Flags: runhidden; Check: IsAdminInstallMode
Filename: "{app}\{#AppExe}"; Description: "启动截图端（悬浮球）"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExe}"; Parameters: "--receiver"; Description: "启动接收端"; Flags: nowait postinstall skipifsilent; Tasks: receiverstart
Filename: "{sys}\notepad.exe"; Parameters: """{app}\使用说明.md"""; Description: "打开使用说明"; Flags: postinstall skipifsilent unchecked nowait

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""ShotBridge Receiver"""; Flags: runhidden; RunOnceId: "DelFwRule"; Check: IsAdminInstallMode
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""ShotBridge Discovery"""; Flags: runhidden; RunOnceId: "DelFwDisc"; Check: IsAdminInstallMode

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
