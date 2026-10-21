# GitHub 调研报告：桌面截图 + 悬浮/置顶小挂件 + 跨机传输（Windows 技术选型）

> 数据口径：star / 语言 / 许可证 / 最后推送时间均取自 GitHub REST API（`api.github.com/repos/{owner}/{repo}`）与仓库 README/源码目录实读，**采样日期 2026-10-21**。未能用 API 确认的项已显式标注「未确认」。闭源商业软件（Lightshot / PicPick / Xnip / Sniip / Screenpresso / Monosnap / Snipaste）**没有官方开源仓库**，故不出现在列表中。

---

## 1. 高度相关（同时命中「悬浮入口 + 截图 + 远端发送」或几乎等价的产品形态）

| 仓库 | ★ | 语言 | 许可证 | 最后推送 | 悬浮入口 | 截图 | 远端发送 | Windows |
|---|---|---|---|---|---|---|---|---|
| [ShareX/ShareX](https://github.com/ShareX/ShareX) | 40,263 | C# | GPL-3.0 | 2026-10-20 | 托盘 + **Pin to Screen 浮动窗** | 全屏/窗口/区域/滚动 | ✅ FTP/SFTP/自定义HTTP/S3/GCS/OwnCloud/OneDrive/邮件/**共享文件夹** | ✅ 原生 |
| [sparshsam/opensnap](https://github.com/sparshsam/opensnap) | 1 | C#/WPF .NET 8 | ⚠️ **仓库无 LICENSE 文件** | 2026-08-24 | ✅ **半透明玻璃胶囊 240×36 常驻置顶、可拖动、三按钮** | ✅ 全屏/活动窗口/区域 | ❌ 无网络（仅存本地+剪贴板） | ✅ 原生 |
| [Flowdesktech/Snapboard](https://github.com/Flowdesktech/Snapboard) | 7 | C#/WPF .NET 10 | MIT | 2026-04-19 | 托盘 + 常驻面板 | ✅ 捕获/标注/OCR/二维码/取色/测量 | ❌ 明确「无网络代码」 | ✅ 原生 |
| [greenshot/greenshot](https://github.com/greenshot/greenshot) | 5,201 | C# | GPL-3.0 | 2026-10-20 | 托盘 | ✅ 区域/窗口/全屏 | ✅ 导出到文件/剪贴板/邮件/**自定义 HTTP** | ✅ 原生 |
| [flameshot-org/flameshot](https://github.com/flameshot-org/flameshot) | 31,271 | C++ | GPL-3.0 | 2026-10-16 | 托盘（无悬浮球） | ✅ 区域/窗口/全屏/滚动 | ⚠️ 仅 Imgur | ✅ 原生 |
| [NiiightmareXD/windows-capture](https://github.com/NiiightmareXD/windows-capture) | 519 | Rust（含 Python 绑定） | MIT | 2026-10-05 | ❌（库） | ✅ **WGC 截当前窗口/显示器**，v2.0.1 支持 DXGI 桌面复制 | ❌ | ✅ 库 |

**opensnap 是本需求形态上最贴合的参照物**：README 明确写「translucent glass capsule — click to capture, drag to move」「always-on-top」「240×36 px」，三按钮 = 区域选择 / 全屏 / 活动窗口，另有全局热键 Win+Shift+S / Win+Shift+W、Windows OCR、托盘内最近 20 条历史、智能文件名模板、Inno Setup 安装包 + MSIX + Microsoft Store 上架、开机自启。
⚠️ **法律红线**：opensnap 根目录**没有 LICENSE 文件**（GitHub API `license: null`），但 README 写「MIT © Kovina」——两者矛盾。**只能读思路，不能复制代码或资产进商业产品**。

**Greenshot 1.4 新增了可插拔的截图后编排框架**（`src/Greenshot.Base/Recipes/`：`CaptureRecipe.cs`、`RecipeComposer.cs`、`RecipeValidator.cs`、`Pipeline/`、`Sources/`、`Triggers/`，以及 `WellKnownStepTypes.cs`）。其步骤类型常量全集（实测原文）：`Source / InteractiveSelection / ImmediateFeedback / Processors / Destinations / Notification / DynamicDestination / Effect / Conditional / TextEffect / Annotation / SetVariable / SaveFile / Clipboard / Editor / Printer / Email / CustomDestination / UserPrompt / RecordVideo / Stdout / Stderr / Slot`；`IsDestination()` 判定导出类集合为 `{Destinations, SaveFile, Clipboard, Editor, Printer, Email, DynamicDestination, CustomDestination}`；Source 覆盖 `Screen/Window/ActiveWindow/Clipboard/File/LastRegion`。→ 这是「截图 → 自动落地/上传/通知」最成熟的开源编排模型。

---

## 2. 部分相关（只满足其中一到两点，可作单点参考）

### 2.1 局域网「发到另一台电脑」
| 仓库 | ★ | 语言 | 许可证 | 最后推送 | 说明 |
|---|---|---|---|---|---|
| [localsend/localsend](https://github.com/localsend/localsend) | 95,059 | Dart/Flutter（另有 Rust `server/`、`cli/`） | Apache-2.0 | 2026-10-17 | 局域网自动发现 + HTTP 传输，产品级「一键发给某台机器」；不含截图 |
| [syncthing/syncthing](https://github.com/syncthing/syncthing) | 89,568 | Go | MPL-2.0 | 2026-10-21 | 文件夹双向同步；「远端文件夹自动出现」的最贴合语义，但两台机都要装 |
| [schollz/croc](https://github.com/schollz/croc) | 40,690 | Go | MIT | 2026-10-20 | PAKE 加密中继传输；**需人工输入 code-phrase，不适合一键自动** |
| [schlagmichdoch/PairDrop](https://github.com/schlagmichdoch/PairDrop) | 11,637 | JavaScript | GPL-3.0 | 2026-04-22 | WebRTC 浏览器直传，需人工确认 |
| [RobinLinus/snapdrop](https://github.com/RobinLinus/snapdrop) | 36 | JavaScript(+Rust) | GPL-3.0 | 2026-09-15 | ⚠️ 该仓库 `created_at=2026-09-14`，2026-09 被重建/重写历史，原高星仓库已不存在；当前仅 36★/1 fork |
| [darkpenguin23/sambam](https://github.com/darkpenguin23/sambam) | 18 | Go | ⚠️ 无 LICENSE | 2026-02-27 | **一条命令起 SMB 文件服务器**，Windows 客户端 `net use Z: \\host\share` 即可；适合做「接收端」 |
| [FWeinb/electron-screenshot-app](https://github.com/FWeinb/electron-screenshot-app) | 未确认 | JavaScript/Electron | 未确认 | 未确认 | 老牌 Electron 截图示例（`screenshot(options, cb)` 返回 Buffer） |

### 2.2 浏览器页面截图（若「当前页面」指浏览器标签页）
| 仓库 | ★ | 语言 | 许可证 | 最后推送 |
|---|---|---|---|---|
| [alyssaxuu/screenity](https://github.com/alyssaxuu/screenity) | 18,795 | JavaScript | GPL-3.0 | 2026-10-20 |
| [mrcoles/full-page-screen-capture-chrome-extension](https://github.com/mrcoles/full-page-screen-capture-chrome-extension) | ≈1,500 | JavaScript | MIT | 2026-08-12 |

后者即 **GoFullPage 的开源仓库**（gofullpage.com FAQ 指向它），文件：`api.js` / `page.js` / `popup.js` / `manifest.json` / `popup.html`。GoFullPage 商店版用户量 1,100 万（来源：Chrome Web Store publisher "Full Page LLC"）。
（`firefox-shot` 与 `Sender(mickael-menu)` 的真实仓库**本次多次搜索均未找到**，`alyssaxuu/gofullpage`、`mickael-menu/sender` 均 404 → 标注**未确认**。）

### 2.3 透明置顶可拖动悬浮窗（三条技术路线的现成实现）
| 仓库 | ★ | 语言 | 许可证 | 最后推送 | 用途 |
|---|---|---|---|---|---|
| [zhiyiYo/PyQt-Frameless-Window](https://github.com/zhiyiYo/PyQt-Frameless-Window) | 766 | Python | **GPL-3.0** | 2026-08-02 | 跨平台无边框窗（Win11 snap / Win10 acrylic / Win11 mica / 禁止截屏） |
| [yjg30737/pyqt-frameless-window](https://github.com/yjg30737/pyqt-frameless-window) | 43 | Python | **MIT** | 2023-07-18 | Win32 API 无边框，`setPressToMove(True)` 拖动；3 年未更新 |
| [XiaoshuDeXiaowo/QtFramelessWindow](https://github.com/XiaoshuDeXiaowo/QtFramelessWindow) | 0 | Python | LGPL-3.0 | 2026-03-28 | QtPy 版同类库 |
| [Berny23/transparent-overlays](https://github.com/Berny23/transparent-overlays) | 28 | C#/WPF | **MIT** | 2021-08-08 | Windows 可拖动透明置顶窗口显示图片并记忆位置；5 年未更新 |
| [ryanputraa/RB-Notes](https://github.com/ryanputraa/RB-Notes) | 2 | TypeScript/Electron | **MIT** | 2026-04-05 | Electron 常驻桌面浮窗，electron-builder + Squirrel 打包 |
| [kokoronoka/desktopPet](https://github.com/kokoronoka/desktopPet) | 0 | JavaScript/Electron | ⚠️ 无 LICENSE | 2026-08-04 | 透明置顶浮层的**穿透点击 + 拖动 + 点击/拖动区分**三大技巧 |
| [yjg30737/pyqt-transparent-timer](https://github.com/yjg30737/pyqt-transparent-timer) | 未确认 | Python | 未确认 | 未确认 | PyQt 透明置顶小挂件范例 |
| [BasedHardware/omi](https://github.com/BasedHardware/omi/blob/main/desktop/windows/docs/bar-gotchas.md) | 未确认（monorepo） | TypeScript/Electron | 未确认 | 未确认 | **Windows 透明置顶浮层踩坑文档（本文最有价值的单份资料）** |
| [electron/electron](https://github.com/electron/electron) | 123,433 | C++ | MIT | 2026-10-21 | 内置 `desktopCapturer` 屏幕捕获 API |

---

## 3. 可借鉴的关键实现（具体到文件与思路）

### 3.1 悬浮球：透明 + 置顶 + 可拖动 + 点击穿透
- **WPF 形态参考（思路）**：`sparshsam/opensnap` → `MainWindow.xaml`（无边框/透明/Topmost/圆角胶囊的 XAML）、`MainWindow.xaml.cs`（拖动 + 位置持久化）、`TrayService.cs`（托盘 + 历史菜单）、`StartupManager.cs`（开机自启）、`AppSettings.cs`、`HotkeyService.cs`（全局热键）、`OcrService.cs`、`UpdateService.cs`、`LocalizationService.cs`；安装：`setup.iss`（Inno Setup，支持 per-user/per-machine/silent）、`build-installer.bat`、`package-msix.ps1` + `Package.appxmanifest`、`create-desktop-shortcut.ps1`。⚠️ 无许可证，只可读思路。
- **WPF 可安全复用**：`Berny23/transparent-overlays`（MIT）——透明置顶 + 拖动 + 记忆位置。
- **Electron 拖动**：`ryanputraa/RB-Notes` 用 `-webkit-app-region: drag`；**重要坑（作者 2026-04 记录）**：`transparent: true` 的 BrowserWindow 会被 Windows 当成分层窗口，**彻底脱离 Aero Snap / Win+Arrow 分屏体系**；改成 `transparent: false` + 纯色 `backgroundColor` 才恢复。
- **Electron 穿透 + 拖动 + 点击/拖动区分**：`kokoronoka/desktopPet`（`main.js` / `renderer.js` / `preload.js`）——① 渲染进程每次 `mousemove` 判断指针是否在小挂件上，动态 `setIgnoreMouseEvents(true/false)` 实现「除挂件外点透」；② 拖动的指针增量经 IPC `move-window` 交给主进程 `setBounds`，并按当前显示器 work area 夹取；③ 位移未超阈值视为点击（否则会误触发点击）。
- **Electron Windows 四大坑（`BasedHardware/omi/desktop/windows/docs/bar-gotchas.md`）**：
  1. 透明 frameless HWND 每次 hidden→show 都会播放约 300ms 的 OS 级 alpha 淡入，**不可禁用**（`DWMWA_TRANSITIONS_FORCEDISABLED` 无效，见 `electron/electron#45730`）→ **正解：窗口常驻，永不 `hide()`；启动时 park 到 (-32000,-32000)，只用 `setBounds` 做 park/unpark**；
  2. 尺寸变化时 bottom-pinned 内容会跟着跑（plummet）→ 用 `overflow: clip` 的 clip-reveal 动画，不要用 enter-animation/opacity；
  3. `win.isVisible()` 永远为 true，不能当「是否在屏上」的真值，要用业务标志位；
  4. 非激活（`focusable:false`）窗口的输入差异。
- **C++ 路线**：`flameshot` → `src/widgets/draggablewidgetmaker.cpp/.h`（**可拖动浮动控件工厂**）、`src/widgets/trayicon.cpp`。
- **PyQt 路线**：`zhiyiYo/PyQt-Frameless-Window`（继承 `FramelessWindow`/`FramelessMainWindow`，支持 Win11 snap layout、Win10 acrylic、Win11 mica、禁止截屏）——⚠️ GPL-3.0，闭源商用请改用 MIT 的 `yjg30737/pyqt-frameless-window` 或 LGPL 的 `QtFramelessWindow`，或自行实现 Win32 `WM_NCLBUTTONDOWN/HTCAPTION`（几十行）。

### 3.2 截图能力
- **ShareX**（`ShareX.ScreenCaptureLib/`）：`Screenshot.cs`（全屏/窗口）、`Screenshot_Transparent.cs`（透明窗口截图）、`HDRScreenCapture.cs`、`RegionCaptureOptions.cs`、`RegionCaptureTasks.cs`、`ScrollingCaptureManager.cs`、`Presentation/RegionCapture/`（区域选择 UI）。
- **当前窗口高质量截图（强烈推荐）**：`NiiightmareXD/windows-capture`（MIT）——Windows Graphics Capture API，含 `windows-capture-python` 子目录（Python 绑定）；v2.0.1 增加 DXGI Desktop Duplication 与硬件加速编码。
- **零依赖跨平台截图**：`BoboTiG/python-mss`（1,287★，MIT）——纯 ctypes，多显示器支持，pip 即用。
- **区域选择遮罩 UI**：`flameshot` → `src/widgets/capture/`：`capturewidget.cpp/h`、`selectionwidget.cpp/h`（选区）、`magnifierwidget.cpp/h`（放大镜）、`buttonhandler.cpp/h`、`capturetoolbutton.cpp/h`、`hovereventfilter.cpp/h`、`notifierbox.cpp/h`、`overlaymessage.cpp/h`、`modificationcommand.cpp/h`、`colorpicker.cpp/h`。
- **opensnap 简化版**：`AreaSelectorWindow.xaml/.xaml.cs`（区域选择窗）、`ScreenshotService.cs`（全屏/活动窗口）、`CaptureService.cs`（编排）、`CapturePopup.xaml`（截图后浮动操作面板）。

### 3.3 远端发送 / 落地到指定文件夹
- **【方案 A｜零依赖】UNC 网络共享直写**：ShareX `ShareX.UploadersLib/FileUploaders/SharedFolderUploader.cs` 实测核心逻辑——`string filePath = account.GetLocalhostPath(fileName);` → `FileHelpers.CreateDirectoryFromFilePath(filePath);` → `new FileStream(filePath, FileMode.Create)`。把路径配成 `\\192.168.1.20\shots\` 即直接写远端共享目录（Windows 原生 UNC，无需远端装任何东西）。同目录还有 `Copy.cs`、`LocalhostAccount.cs`。
- **【方案 B｜自建 HTTP 接收端】ShareX Custom Uploader**：`ShareX.UploadersLib/CustomUploader/`（`CustomUploaderItem.cs`、`CustomUploaderInput.cs`、`ShareXCustomUploaderSyntaxParser.cs`、`Functions/`）+ 官方文档 `https://getsharex.com/docs/custom-uploader`：支持 GET/POST/PUT/PATCH/DELETE，Body 类型 None/MultipartFormData/FormURLEncoded/JSON/XML/Binary，自定义 Headers（含 Authorization Basic）、URL parameters，变量语法 `{json:jsonPath}` `{xml:xpath}` `{regex:...}` `{response}` `{filename}` `{base64:text}`，配置可导出 `.sxcu`（JSON：Version/Name/DestinationType/RequestMethod/RequestURL/Parameters/Headers/Body/Arguments/FileFormName/URL/ThumbnailURL/DeletionURL/ErrorMessage）。→ **接收端只需实现一个 `POST /upload`（multipart）+ 返回 JSON 即可**，配置模型直接照搬。
- **【方案 C｜SMB 接收端】** `darkpenguin23/sambam`（Go，SMB 2.1/3.0/3.1.1、多共享、per-share ACL、mDNS+WS-Discovery）——一条命令让远端机器变成可 `net use` 的文件服务器。注意无许可证。
- **【方案 D｜局域网自动发现】** `localsend/localsend`（Apache-2.0）——HTTP 传输 + mDNS 发现，仓库结构 `app/`（Flutter）、`server/`、`cli/`、`packages/`（Rust 分支）。
- **其他可抄的 uploader 源码**：`FileUploaders/FTP.cs` + `FTPAccount.cs`、`SFTP.cs`（SSH 传文件）、`Email.cs`，以及 S3/Azure/GCS/Backblaze/Box/Dropbox/OneDrive/OwnCloud/Seafile/Plik/Pomf/Immich/Mega/Lambda 等一整套实现。
- **浏览器页面截图 → 本机程序**：Chrome 扩展用 `chrome.tabs.captureVisibleTab` 或 CDP `Page.captureScreenshot(captureBeyondViewport:true)`（Chrome 112+ 整页），再经 **Native Messaging** 交给桌面端，由桌面端统一做「落盘 + 跨机发送」。参考 `mrcoles/full-page-screen-capture-chrome-extension`（MIT）的 `api.js`/`page.js`/`popup.js` 与 `alyssaxuu/screenity`。

### 3.4 打包与安装
- Inno Setup：`opensnap/setup.iss` + `build-installer.bat`（per-user / per-machine / silent）。
- MSIX 上架：`opensnap/package-msix.ps1` + `Package.appxmanifest`（含 Microsoft Store 渠道）。
- 单文件自包含 EXE：`Flowdesktech/Snapboard` → `dotnet publish Snapboard -c Release -r win-x64 --self-contained true /p:PublishSingleFile=true`。
- Greenshot：`installer/`、`chocolatey/` 目录；1.4 开发环境要求 VS 2026 + MSVC v145 + .NET SDK 10 + .NET Framework 4.8 targeting pack。

---

## 4. 许可证注意事项（能否商用 / 二次开发）

| 许可证 | 项目 | 结论 |
|---|---|---|
| **GPL-3.0** | ShareX、Greenshot、Flameshot、Screenity、PairDrop、snapdrop、zhiyiYo/PyQt-Frameless-Window | ⚠️ **不可将代码拷进闭源商业产品**。只要链接/派生，整个产品须以 GPL-3.0 发布并提供完整源码。只可「读思路后自行重写」 |
| **MIT** | electron、croc、windows-capture、python-mss、mrcoles 扩展、Snapboard、RB-Notes、Berny23/transparent-overlays、yjg30737/pyqt-frameless-window | ✅ 可商用闭源，保留版权与许可声明 |
| **Apache-2.0** | LocalSend | ✅ 可商用闭源，需保留 LICENSE/NOTICE 并标注修改 |
| **MPL-2.0** | Syncthing | ✅ 文件级 copyleft：改过的文件需以 MPL 开源，其余可闭源 |
| **MS-PL** | ScreenToGif | ✅ 可商用闭源，保留声明 |
| **LGPL-3.0** | QtFramelessWindow | ✅ 动态链接可闭源分发，需允许用户替换该库 |
| **无许可证**（默认版权保留） | **opensnap**、sambam、desktopPet | ❌ **不可复制代码/资产**，仅可阅读思路。opensnap README 自称 MIT 但仓库无 LICENSE 文件，需向作者确认后才可复用 |
| 附加条款 | Flameshot | logo 为 Free Art License v1.3、按钮图标 Apache-2.0、`capture/capturewidget.cpp` 基于 ckaiser/Lightscreen (GPLv2)、含 KDE/ksnapshot `regiongrabber.cpp` (LGPL) → **不要搬图标与资源** |
| 商标 | Greenshot / ShareX | 均有 Logo/品牌使用政策（ShareX: `getsharex.com/docs/brand-assets`），别用其图标做自己产品 |

**结论：商业闭源产品的安全区 = MIT / Apache-2.0 / MPL / 自己写的代码 + Windows API + 只读 GPL 项目**。

---

## 5. 技术选型建议

### 5.1 结论：**C# / WPF（.NET 8，自包含单文件）最优**，Electron 次之，PyQt 垫底

| 维度 | C#/WPF | Electron | Python/PyQt |
|---|---|---|---|
| 透明置顶圆形挂件 | ✅ 原生最省心：`WindowStyle=None` + `AllowsTransparency=True` + `Topmost=True` + `Background=Transparent` + `Ellipse`；拖动用 `CaptureMouse()`+`PointToScreen()` 或 Win32 `WM_NCLBUTTONDOWN/HTCAPTION` | ⚠️ 能做但坑多：`transparent:true` 掉出 Aero Snap；300ms fade 必须靠「常驻 + park 到 -32000」规避 | ✅ `FramelessWindowHint|StaysOnTopHint|Tool` + `WA_TranslucentBackground`；但可用库多为 GPL/LGPL |
| 当前窗口截图 | ✅ WGC（windows-capture 生态）或 `PrintWindow`/`BitBlt` | ❌ `desktopCapturer` 只能给**屏幕**源，拿「当前窗口」需自研 WGC | ✅ `windows-capture` 的 Python 绑定 + `python-mss` |
| 跨机落地 | ✅ UNC 直写 / HttpClient POST / SMB，全 .NET BCL | ✅ Node fetch/axios，能力等价 | ✅ requests，但打包后体积与依赖地狱 |
| 安装包体积 | ~60–70 MB（self-contained 单文件） | ~120–180 MB | PyInstaller 100–200 MB + 抗病毒误报率高 |
| 启动/内存 | ~40 MB，秒开 | ~120 MB 常驻 | ~80 MB + Python 运行时 |
| 杀软误报/签名 | 低 | 高（Electron 打包常见误报） | 高 |
| 开机自启/托盘/单实例 | ✅ 成熟（`Microsoft.NET.Test.Sdk` 无关；HKCU Run + NotifyIcon） | ✅ electron-builder NSIS/Squirrel | ⚠️ 需手搓 |
| 跨平台 | ❌（正是本需求优点） | ✅ | ✅ |

**推荐理由（本需求 90% 是 Windows 原生能力）**：WPF/.NET 8 在「透明置顶小窗、点击穿透、全局热键、托盘、开机自启、当前窗口截图」这些核心诉求上都是一行到几十行原生 API，且没有 Electron 的透明窗渲染陷阱、没有 Python 的打包体积/杀软问题；`dotnet publish --self-contained -p:PublishSingleFile=true` 直接产出单 EXE，再套 Inno Setup 模板（opensnap 的 `setup.iss`）就是完整安装包。

### 5.2 落地架构（建议按此切分）
1. **桌面端（C# WPF）**：常驻进程 → 透明圆形挂件（`Topmost`、可选 `WS_EX_TRANSPARENT` 穿透、位置持久化到 `%AppData%`）+ 托盘图标 + 全局热键。
2. **截图层（可插拔）**：全屏（WGC 或 GDI `CopyFromScreen`）、当前活动窗口（WGC，参考 windows-capture）、区域选择（全屏截图 + 自绘透明遮罩窗拖矩形，参考 Flameshot `selectionwidget` / ShareX `Presentation/RegionCapture` / opensnap `AreaSelectorWindow`）。若要「当前浏览器页面整页」，加一个 Chrome 扩展（参考 mrcoles/Screenity）经 Native Messaging 回传，桌面端统一走「落盘 + 发送」。
3. **传输层（3 选 1，UI 可切换）**：
   - **默认：SMB/UNC 直写** `\\192.168.x.x\shots\`（参考 ShareX `SharedFolderUploader.cs`；远端用 Windows 自带共享，或用 sambam 起 SMB 服务）→ 最贴合「传到指定文件夹」，零远端依赖。
   - **备选：自建 HTTP 接收端**（远端跑一个极简 POST /upload 服务），桌面端照搬 ShareX Custom Uploader 的配置模型。
   - **备选：LocalSend 协议**（Apache-2.0）自动发现目标设备，适合不写死 IP 的场景。
4. **安装**：Inno Setup（per-user/per-machine/silent）+ 可选 MSIX；开机自启写 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`（参考 opensnap `StartupManager.cs`）。

### 5.3 若最终选 Electron，必须提前处理的 5 件事
1. 挂件窗口**永不 hide()**，启动 park 到 `(-32000,-32000)`，只用 `setBounds` park/unpark（omi 文档）。
2. `transparent: true` 会丢失 Aero Snap；接受则可保留真透明，否则用 `transparent:false` + 纯色背景（RB-Notes 作者 2026-04 实证）。
3. 用 `setIgnoreMouseEvents` 做穿透，且**拖动过程中必须暂停穿透判定**（desktopPet）。
4. 拖动增量经 IPC 交主进程 `setBounds`，并按当前显示器 work area 夹取；点击与拖动用位移阈值区分。
5. 「当前窗口截图」Electron 无原生能力，必须自己接 WGC——这会让 Electron 路线的实际成本高于 WPF。

### 5.4 实现前必查的坑清单
- 多显示器 + 混合 DPI：坐标换算用 `PhysicalToLogicalPoint`/`DpiHelper`；跨屏拖动要跟随显示器切换。
- 截图「当前窗口」时若目标被遮挡，GDI/BitBlt 只能拿到被遮挡画面或黑屏 → 必须 WGC。
- UNC 写入要求远端开启网络发现+文件共享并放行账号；防火墙端口（自建 HTTP/SMB）需显式放行。
- 悬浮球「穿透点击」若做错会挡住下层应用的高频操作；建议做成可开关的设置项。
- WPF 首次 Show 有系统动画，频繁 hide/show 挂件会有闪烁 → 用 `Opacity` 渐变或 `Visibility` 切换并注意 `SetWindowPos` 顺序。

---

## 附：本次未能确认的项（诚实标注）
- `firefox-shot`、GoFullPage 官方仓库、`Sender(mickael-menu)` 的真实 GitHub 仓库地址 → **未确认**（多次搜索未找到；`alyssaxuu/gofullpage`、`mickael-menu/sender` 返回 404）。
- `FWeinb/electron-screenshot-app`、`yjg30737/pyqt-transparent-timer`、`BasedHardware/omi` 的 star 数/许可证/最后推送 → **未确认**（仅通过搜索结果页确认存在与功能）。
- Greenshot 的 sticky/pin 浮动窗源码文件位置 → **未定位到具体文件**（`src/Greenshot.Base/Controls/` 实测仅有 `GreenshotForm.cs`、`InteractiveUserInteraction.cs`、`SaveImageFileDialog.cs`）。
- ShareX 是否原生支持「SMB 目的地」→ **无原生 SMB uploader**，但 `SharedFolderUploader` 走文件系统路径，配置 UNC 即等价于 SMB 写入（此结论基于源码实读）。
