# 调研报告：GitHub 上有没有现成的「悬浮球点一下就截图、还能通过局域网传到另一台电脑」的项目？

调研时间：2026-10-21　｜　调研方式：GitHub 仓库检索 + 逐个读源码/README + API 取 star/许可证/最后提交

---

## 0. 结论速览

**有类似项目，但没有一个现成的能直接满足你的需求。** 拆成三段看：

| 能力 | 现成方案成熟度 | 代表项目 |
| --- | --- | --- |
| ① 桌面上可拖动、半透明、永远置顶的悬浮球/悬浮条 | 很成熟，代码可以直接借鉴 | ShareX、opensnap、floating_ball、PyQt-Frameless-Window |
| ② 点一下就把"当前画面"截下来 | 很成熟，Windows 原生 API 就有 | ShareX、Greenshot、Flameshot、windows-capture |
| ③ 截完自动传到**局域网另一台电脑的指定文件夹** | 少见。截图工具的上传目标几乎都是图床/FTP/云盘；**"局域网直传 + 落盘到指定目录"这一环基本都是自己写** | 只有 ShareX 的 Custom uploader / SMB 目标勉强接近 |

所以正确的做法是：**借 #1 的壳、用 #2 的 API、自己写 #3**，而不是找一个项目改。

一个需要提前纠正的点：你说的"**当前页面**"，如果指的是**浏览器里正在看的那一页**（不含浏览器工具栏、能滚到看不见的部分），那任何 Windows 原生截图 API 都做不到 —— 它们只能拿到屏幕像素。真要做到"页面级"截图，只有 **Chrome 扩展**这条路（`chrome.tabs.captureVisibleTab` 或 `chrome.debugger` + CDP `Page.captureScreenshot`）。本方案按"屏幕像素级截图"实现，覆盖 99% 的实际使用场景；页面级截图列在附录里作为可选增强。

---

## 1. 最接近的几个项目（按契合度排序）

| 项目 | ★ | 语言/框架 | 许可证 | 最后提交 | 契合度评价 |
| --- | --- | --- | --- | --- | --- |
| [ShareX/ShareX](https://github.com/ShareX/ShareX) | 40263 | C# / WinForms | GPL-3.0 | 2026-10-20 | **能力最全**：全屏/活动窗口/活动显示器/区域/滚动截图 + 截图后的自动化任务链（after-capture tasks）+ 几十种上传目标（含自定义 HTTP、SMB 共享）。缺点是：它是"大而全的瑞士军刀"，不是你要的"一个小球"，且 GPL-3.0 |
| [sparshsam/opensnap](https://github.com/sparshsam/opensnap) | 1 | C# / .NET 8 WPF | ⚠️ 无 LICENSE 文件（README 写 MIT，矛盾） | 2026-08-24 | **产品形态最贴合**：一个 240×36 的半透明玻璃胶囊常驻置顶、可拖动，三个按钮分别是"区域/全屏/活动窗口"，带 Win+Shift+S 热键、Inno Setup 安装包、开机自启。唯独**没有任何网络上传能力** |
| [cnbright/floating_ball](https://github.com/cnbright/floating_ball) | 22 | Python / PySide6 | MIT | 2023-03-17 | **悬浮球最好的可直接复制参考**：Windows 下的圆形渐变球、无边框透明、置顶、可拖动、系统托盘、PyInstaller 打包脚本一应俱全。但它的"截图"只是 `pyautogui.hotkey('winleft','shift','s')` 去调系统截图工具，等于没实现 |
| [greenshot/greenshot](https://github.com/greenshot/greenshot) | 5201 | C# | GPL-3.0 | 2026-10-20 | 1.4 版引入了可插拔的**截图后编排框架**（`src/Greenshot.Base/Recipes/`），把"选区 → 处理 → 落地/上传"抽象成步骤流水线。这个**架构思路**是最值得抄的部分 |
| [flameshot-org/flameshot](https://github.com/flameshot-org/flameshot) | 31271 | C++ / Qt | GPL-3.0 | 2026-10-16 | 区域选择的交互做得最好（`src/widgets/capture/`），框选遮罩、控制点、尺寸提示的细节可参考 |
| [NiiightmareXD/windows-capture](https://github.com/NiiightmareXD/windows-capture) | 519 | Rust（有 Python 绑定） | MIT | 2026-10-05 | 用 Windows Graphics Capture API 截"某个窗口/某块显示器"，比抓屏再裁剪更干净、不被遮挡影响。若将来需要"截被遮挡的窗口"可以换它 |
| [Flowdesktech/Snapboard](https://github.com/Flowdesktech/Snapboard) | 7 | C# / WPF .NET 10 | MIT | 2026-04-19 | 截图管理面板，README 明确写了"无网络代码"—— 反证了第 ③ 环确实少有人做 |
| [gaoyan2659365465/ScreenshotFloatingBall](https://github.com/gaoyan2659365465/ScreenshotFloatingBall) | — | Python / PyQt5 | — | — | 名字最像你的需求：PyQt5 + 大漠插件，截图后存到**本机**指定文件夹并按序号命名。是"本机落盘"，不是局域网 |
| [BoPinHuai/screenshot-tool](https://github.com/BoPinHuai/screenshot-tool) | — | — | — | — | README 自述"Windows 轻量截图工具，悬浮球形态"，规模很小 |
| [Mrducan1245/FloatScreenBall](https://github.com/Mrducan1245/FloatScreenBall) | — | Java | — | 2022 | "悬浮球带截图和录屏功能"，形态接近但是 Java/Android 向 |
| [michaelz9436/DeskAI](https://github.com/michaelz9436/DeskAI) | 11 | Python | MIT | 2026-03-11 | AI 截图识别悬浮球助手，可作为"截完图还能干什么"的扩展参考 |
| [Wucy0519/Ferry](https://github.com/Wucy0519/Ferry) | — | Swift / macOS | — | — | 文件/截图悬浮球"中转站"，是唯一把"悬浮球 + 传给另一处"都做了的，但仅限 Mac 且不是局域网直传 |
| [MapleYazuu/Screenshot-Ai](https://github.com/MapleYazuu/Screenshot-Ai) | — | Android / Kotlin | GPL-3.0 | — | 安卓端"单击桌面悬浮球即截屏"，交互逻辑可参考 |

> 表中"★"和"最后提交"为调研当天通过 GitHub API 实读值；标 `—` 的项未能取到可信数值，不做断言。

### 一句话结论

- **想要"直接下载就能用"**：没有。最接近的是 ShareX（但要自己配 Custom uploader 脚本打到局域网机器，且它的"上传后落盘"要对方开 FTP/WebDAV/共享），体验和"点一下球"差很远。
- **想要"拿来改"**：`opensnap`（形态）+ `floating_ball`（Python 悬浮球实现）+ 自己写上传/接收，是成本最低的组合。

---

## 2. 从这些项目里学到的 5 个关键实现点

这些是踩过坑的人已经付过学费的地方，本方案全部采纳：

1. **透明置顶窗口的正确标志位组合**（来自 floating_ball 与多个 PyQt 无边框窗口库）：
   `FramelessWindowHint | WindowStaysOnTopHint | Tool` + `WA_TranslucentBackground`，
   再补一个 `WindowDoesNotAcceptFocus`（= `WS_EX_NOACTIVATE`），**保证点小球不会把当前窗口的焦点抢走**，
   否则"截当前活动窗口"会截到小球自己。
2. **拖动与点击必须区分**（来自 floating_ball）：按下时记 `drag_position = globalPos - frameGeometry.topLeft()`，
   移动时按位移量累加，松手时位移 < 6px 才判定为"点击"。不区分的话一拖就误触发截图。
3. **截图前必须先把自己藏起来**，否则悬浮球会出现在截图里；截完立刻显示回来（`hide()` → `processEvents()` → 抓图 → `show()`）。
4. **多显示器 + 高 DPI 是最大的坑**：Windows 的"逻辑坐标"和"物理像素"在不同显示器上缩放比可能不同。
   本方案统一按**虚拟桌面物理像素**处理（先抓整块虚拟桌面，再按矩形裁剪），避免三套坐标系打架。
5. **打包成 exe 后路径全变**：`__file__`、`sys._MEIPASS`、PySide6 插件目录、图标资源都要特殊处理；
   无控制台窗口程序崩溃时看不到任何报错 —— 必须自带日志和全局异常兜底（本方案有 `bootstrap.py` 专管这件事）。

另外 Electron 路线有几个已知硬伤（若将来换技术栈需注意）：`transparent: true` 会丢掉 Windows 的 Aero Snap；
透明无边框窗口每次 `hide()`→`show()` 会有约 300ms 淡入动画（正解是窗口常驻、只把坐标挪到屏幕外）；
`win.isVisible()` 在透明窗口上恒为 `true`。

---

## 3. 局域网传输方案对比（第 ③ 环怎么实现）

| 方案 | 目标机需要装什么 | 需要放行 | 优点 | 缺点 |
| --- | --- | --- | --- | --- |
| **① 自建极简 HTTP 接收端**（本方案采用） | 装 速截 接收端（一个托盘小程序） | 1 个自定义 TCP 端口（默认 8765） | 双向可控、能返回"存到哪了"、能做密钥校验、能自动发现、离线队列可补发 | 目标机要装软件 |
| ② Windows 共享文件夹 + UNC 直写 `\\IP\share\dir` | 什么都不用装 | 445 / 139 | 零安装、`shutil.copy2` 一行搞定、能保留修改时间 | 配置 6 步（真实本地账号、专用网络、网络发现、密码保护共享、共享权限、防火墙）；Win11 24H2 起 SMB 签名强制，要改 `Set-SmbClientConfiguration -RequireSMBSigning $false`；凭据会被缓存，改密码要 `net use \\ip /delete` |
| ③ SMB2 协议栈直连（`smbprotocol` / `go-smb2` / `smb-rs` / `SMBLibrary`） | 不用装客户端，但目标机仍需开共享 | 445 | 不依赖 Windows 的 `net use` 映射，程序内直接读写 | 同样受 SMB 签名/共享配置影响，代码量比 HTTP 大 |

**最终选择 ①，并保留 ② 作为备选。** 理由：
- 只需要在防火墙上开一个端口，配置量比开共享少一半；
- 接收端可以把"存到哪个文件夹、按什么规则命名、要不要按日期分目录"完全做成自己的配置，不受 Windows 共享权限体系约束；
- 出问题时能拿到明确的 HTTP 错误（超时/401/500），比 SMB 的 `系统错误 53/64` 好排查。

自动发现用 **UDP 广播**（比 mDNS 简单可靠得多，不依赖 Windows 的"网络发现"服务），并且**永远保留手填 IP 兜底**——
VPN 虚拟网卡、多网卡、公司网络隔离都会让广播失效。

---

## 4. 最终技术选型

| 维度 | 选择 | 理由 |
| --- | --- | --- |
| 语言/框架 | **Python 3.14 + PySide6 6.11.2** | 本机已预装 PySide6 + Pillow；一套代码同时写截图端和接收端；PyInstaller 直接出 exe，Inno Setup 出安装包 |
| 为什么不选 C#/WPF | — | 调研报告原本推荐 C#（原生透明窗、WGC 截图、单文件发布），但本机没有 .NET SDK，装一遍要几百 MB 且当天无法验证；而 Python 环境已就绪，能立刻跑通端到端 |
| 为什么不选 Electron | — | 透明窗口三个坑（丢 Aero Snap、show 有淡入延迟、isVisible 恒真）都要额外绕；打包体积 150MB+ |
| 截图 | Pillow `ImageGrab.grab(all_screens=True)` + 按矩形裁剪 | 支持多屏、跨 DPI，一次抓全虚拟桌面最稳 |
| 传输 | 自建 HTTP 接收端（`http.server` + 裸二进制 body） | 见第 3 节；不引 FastAPI 是为了零额外依赖、减小安装包 |
| 备选传输 | SMB 直写（`smbprotocol`，失败回退 `net use`） | 目标机不想装任何软件时的兜底 |
| 发现 | UDP 广播 8766 | 不依赖 mDNS/网络发现服务 |
| 打包 | PyInstaller onedir + Inno Setup 6 | onedir 启动快、不用每次解压；单个 exe 通过 `--receiver` 切换身份 |

---

## 5. 许可证红线（若要二次开发/商用必看）

- **GPL-3.0 项目**（ShareX、Greenshot、Flameshot、PyQt-Frameless-Window）：**只能读思路，不能复制代码**，否则你的程序也必须 GPL 开源。
- **无 LICENSE 文件的项目**（opensnap、desktopPet）：默认"版权保留"，**连代码和图片资源都不能复制**。
- **MIT / Apache-2.0**（floating_ball、Snapboard、windows-capture、smbprotocol）：可以自由借鉴和商用，保留版权声明即可。
- Flameshot 的 logo 是 Free Art License，图标不要直接搬。

本方案的代码是**按上述思路重新实现**的（没有复制任何 GPL 项目的代码），图标为程序生成，
依赖项 PySide6（LGPL-3.0）、Pillow（MIT-CMU）、PyInstaller（GPL-2.0 with exception，允许打包分发）、smbprotocol（MIT）均可商用。

---

## 6. 附录

两份详细调研原文已一并归档：

- `附录A-桌面悬浮截图与跨机传输.md` —— 悬浮窗/截图/跨机传输三条技术路线的仓库清单、源码级实现要点、Electron 坑、许可证逐项分析
- `附录B-局域网截图传输.md` —— 三种传输方案的完整对比、Chrome 扩展"页面级截图"的两条路径、防火墙/杀软/权限 11 条坑清单

> 附录中标注"未确认"的条目，表示调研当天未能通过接口或源码证实，仅供参考。
