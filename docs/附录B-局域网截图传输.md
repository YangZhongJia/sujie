# 局域网截图自动落地 —— 技术方案调研报告

**场景**：Windows 悬浮球截图工具，点击截图后自动把图片经局域网传到另一台 PC 的指定文件夹。
**验证**：下列 URL 均已实际访问确认；未能确证的写「未确认」。

## 0. 结论速览

| 排名 | 方案 | 开发量 | 可靠性 | 免配置程度 |
|---|---|---|---|---|
| 1 | 目标机跑 HTTP 接收端 + 客户端 POST | 极小（~40 行） | 高 | 高（只放行 1 个端口） |
| 2 | Windows 共享文件夹 + UNC 直写 | 最小（~10 行） | 中高 | **低**（共享+账号+防火墙 6 步） |
| 3 | SMB2 协议栈直连（smbprotocol / go-smb2 / smb-rs） | 中 | 中高 | 中 |
| 附 | LocalSend / PairDrop 协议复用 | 小 | 高 | 中（目标机需装 App） |

**「当前页面截图」**：只有 Chrome 扩展路线能拿到**页面内容**（`captureVisibleTab` / `Page.captureScreenshot`）；所有 Win32 原生截屏 API 拿到的都是像素，且通常只有可见区。

---

## 1. 传输方案 Top3

### Top1（首选）自建极简 HTTP 接收端

**技术栈**：目标机 Python + FastAPI（约 20 行）；客户端 Python + requests。
**依赖**：`fastapi>=0.110`、`uvicorn>=0.27`、`python-multipart>=0.0.9`（**必需**，缺了 `File()` 直接报错）、`requests>=2.31`。
**依据**：[FastAPI 文件上传官方文档](https://fastapi.tiangolo.com/tutorial/request-files/)；[requests quickstart（2.34.2）](https://requests.readthedocs.io/en/latest/user/quickstart/)。

接收端（目标机 `receiver.py`）：

```python
from pathlib import Path
from typing import Annotated
from fastapi import FastAPI, File, UploadFile

DEST = Path(r"C:\Users\Other\Pictures\Inbox")   # 唯一要改的地方
DEST.mkdir(parents=True, exist_ok=True)
app = FastAPI()

@app.post("/upload")
async def upload(file: Annotated[UploadFile, File()]):
    name = Path(file.filename or "shot.png").name      # 只取文件名，防路径穿越
    dest = DEST / name
    with dest.open("wb") as f:
        while chunk := await file.read(1 << 20):        # 分块落盘，不进内存
            f.write(chunk)
    return {"ok": True, "path": str(dest)}
```

启动：`uvicorn receiver:app --host 192.168.0.23 --port 8765`

客户端（`send.py`）：

```python
import os, requests
from datetime import datetime

URL = "http://192.168.0.23:8765/upload"     # 允许在界面里配置

def send(path: str) -> None:
    name = f"{datetime.now():%Y%m%d-%H%M%S}_{os.path.basename(path)}"
    with open(path, "rb") as f:                          # 必须二进制模式
        r = requests.post(URL, files={"file": (name, f, "image/png")}, timeout=10)
    r.raise_for_status()
    print(r.json())
```

**为什么第一**：只需在目标机放行 1 个自定义 TCP 端口（比 445 更容易加白、杀软误报概率低）；不碰 SMB 凭据/共享权限/工作组；目标机换 Linux 也能跑；可加 `Authorization: Bearer <token>` 鉴权。

**设备发现（对应需求 A4）**

- **手填 IP：默认推荐**，0 依赖、最可靠。
- mDNS 自动发现：`zeroconf>=0.131`（[python-zeroconf](https://github.com/python-zeroconf/python-zeroconf)，纯 Python，Bonjour 兼容）：

```python
import socket
from zeroconf import ServiceInfo, Zeroconf, ServiceBrowser, IPVersion

info = ServiceInfo("_shot._tcp.local.", "floating-ball._shot._tcp.local.",
                    addresses=[socket.inet_aton("192.168.0.23")], port=8765,
                    properties={"path": "/upload"}, server="shot-pc.local.")
zc = Zeroconf(ip_version=IPVersion.All)
zc.register_service(info)          # 客户端端用 ServiceBrowser(zc, "_shot._tcp.local.", listener)
```

（官方示例：[examples/registration.py](https://github.com/python-zeroconf/python-zeroconf/blob/master/examples/registration.py)）

- ⚠️ Windows 上 mDNS 依赖「网络发现」开启，VPN/多网卡/虚拟网卡会干扰 → **务必保留手填 IP 兜底**。

### Top2 Windows 共享文件夹 + UNC 直写（目标机零安装）

**技术栈**：纯 Python 标准库 `shutil` + `os`，无第三方依赖。

```python
import os, shutil
from datetime import datetime

DEST = r"\\192.168.0.23\SharedFolder\Inbox"      # 界面里可配

def send(path: str) -> None:
    os.makedirs(DEST, exist_ok=True)
    out = os.path.join(DEST, f"{datetime.now():%Y%m%d-%H%M%S}_{os.path.basename(path)}")
    shutil.copy2(path, out)                          # 保留 mtime 等元数据
```

（[shutil 文档](https://docs.python.org/3/library/shutil.html)：copy2 保留元数据；Windows 上 copyfile 用 1 MiB 缓冲；copy2 不复制 owner/ACL/ADS）

**目标机必须做的 5 件事**（缺一即失败，详见第 3 节）：真实本地账号+密码（PIN 不行）、网络=专用网络、网络发现+文件和打印机共享开、密码保护共享开且共享权限里加账号、防火墙放行 SMB-In / NB-Session-In。

**坑**：Windows 凭据管理器缓存 UNC 凭据，改密码后要 `net use \\192.168.0.23 /delete`；服务账户与交互式登录凭据不共享；跨网段/VLAN 常被路由 ACL 拦。

### Top3 SMB2 协议栈直连

**何时用**：不想让目标机配共享、需要自定义凭据、或目标机不是 Windows。
**库对比（均已核实）**：

| 语言 | 包 | 版本/状态 | 备注 |
|---|---|---|---|
| Python | [`smbprotocol`](https://pypi.org/project/smbprotocol/) / [jborean93/smbprotocol](https://github.com/jborean93/smbprotocol) | 1.17.0，MIT，**需 Python ≥3.10** | 高层 `smbclient` 与 os/os.path 同构；SMB 2.0.0–3.1.1，NTLM+Kerberos |
| Python | [fortra/impacket](https://github.com/fortra/impacket) | v0.13.1 | 含 `examples/smbclient.py`；安全工具出身 → **杀软误报高，不建议进产品** |
| Go | [`github.com/hirochachacha/go-smb2`](https://github.com/hirochachacha/go-smb2)（注意**不是 go-smb**） | 活跃 | `smb2.Dialer{Initiator:&smb2.NTLMInitiator{User,Password}}`，io/fs 接口 |
| Rust | [`smb` (smb-rs)](https://crates.io/crates/smb) / [afiffon/smb-rs](https://github.com/afiffon/smb-rs) | 27 版，16.9k 下载 | tokio 异步、加密+压缩、TCP445/139/QUIC443 |
| C# | [`SMBLibrary`](https://www.nuget.org/packages/SMBLibrary)（TalAloni，6.97M 下载） | 1.5.8.1 | SMB1/2.0/2.1/3.0 客户端+服务端 |
| C# | [`SmbSharp`](https://www.nuget.org/packages/SmbSharp) | 2.1.0，MIT | **Windows 上直接用原生 UNC 路径**＝零成本实现 Top2；Linux/macOS 转调 `smbclient` |
| C# | `SMB-Client` / `SMBLibraryLite` / `TouchSocketPro.Smb` | 1.4.12 / 1.4.3.2 / 4.3.10 | 备选，下载量小 |
| C# | ~~`SMBClient`~~ | **不存在（NuGet 404）** | 需求里提到的包名有误 |

Python 骨架（smbprotocol）：

```python
from smbclient import register_session, open_file, reset_connection_cache

SERVER, SHARE, USER, PWD = "192.168.0.23", "SharedFolder", "<user>", "<password>"

def save(name: str, data: bytes) -> None:
    register_session(SERVER, username=USER, password=PWD)
    with open_file(rf"\\{SERVER}\{SHARE}\Inbox\{name}.png", mode="wb") as fd:  # 与 open() 同构
        fd.write(data)
    reset_connection_cache()        # 进程退出前释放连接
```

**⚠️ 关键限制**：Win11 24H2 / Server 2025 起 **SMB 签名默认强制**，"会阻止连接工作组计算机、来宾认证共享或不支持签名的第三方 SMB 服务器"（[官方文档](https://learn.microsoft.com/en-us/windows-server/storage/file-server/troubleshoot/detect-enable-and-disable-smbv1-v2-v3)）。目标机需关闭强制签名（`Set-SmbClientConfiguration -RequireSMBSigning $false`，需管理员）——这本身又是权限/安全坑。**这基本判了 SMB 直连在「免配置」维度的死刑。**

**附加：LocalSend / PairDrop（协议现成）**
- [localsend/localsend](https://github.com/localsend/localsend) — Apache-2.0，~94k stars，HTTPS REST，默认 TCP+UDP **53317**。
- 协议 v2.2：[localsend/protocol](https://github.com/localsend/protocol) → `POST /api/localsend/v2/prepare-upload` 换 sessionId/fileId → `POST /api/localsend/v2/upload?sessionId=&fileId=&token=` 传二进制 → sha256 校验（不符返回 422）。
- [PairDrop](https://github.com/schlagmichdoch/PairDrop)（GPLv3，~11.6k stars）：浏览器版 AirDrop，可直接网页拖拽上传。
- 好处：零代码 + 自带设备发现；坏处：目标机要装 App，接收目录要改 App 设置（CLI `--output` 参数**未确认**）。

### 1.4 已核实「不存在 / 不建议」的候选项

- `AlexEudes/Upload` → GitHub **404，仓库不存在**；`go-http-file-upload` → **无此独立知名项目**，搜索首位是 [zupzup/golang-http-file-upload-download](https://github.com/zupzup/golang-http-file-upload-download)（MIT，175★，2023-03 最后提交，仅示例级）。
- [filebrowser/filebrowser](https://github.com/filebrowser/filebrowser) → 已被作者于 2026-08-31 **归档（只读）**；继任 [gtsteffaniak/filebrowser](https://github.com/gtsteffaniak/filebrowser)（FileBrowser Quantum，Apache-2.0，~8.8k★）。
- PicGo uploader 生态存在（[Molunerfinn/picgo](https://github.com/Molunerfinn/picgo)，如 [picgo-plugin-gitea-uploader](https://github.com/GeorgeHu6/picgo-plugin-gitea-uploader)），但面向**图床**非本地文件夹，且基于 Electron（体积大）。

---

## 2. 「当前页面截图」Top2

**先说结论**：Win32 原生截屏（mss / ImageGrab / PrintWindow / WGC / desktopCapturer）拿到的都是**屏幕或窗口像素**，且通常只有可见区域；要拿「浏览器页面内容（含滚动区）」，**必须走 Chrome 扩展 + CDP**。

### 路径 1（首选，最快）：Chrome 扩展 `chrome.tabs.captureVisibleTab`

**依赖**：Chrome 扩展 MV3；manifest 需 `permissions: ["activeTab"]` 或 `host_permissions: ["<all_urls>"]`。

```js
// service worker
const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
const dataUrl = await chrome.tabs.captureVisibleTab(tab.windowId, { format: "png" });
const blob = await (await fetch(dataUrl)).blob();
await fetch("http://192.168.0.23:8765/upload", { method: "POST", body: blob });
```

**限制**：
- 只截**可见区域**（要整页见路径 2）；`captureVisibleTab` 每秒最多 2 次（Chrome 92+）。
- `activeTab` 下还能截 `chrome://`、其他扩展页、`data:` URL（[tabs API 官方文档](https://developer.chrome.com/docs/extensions/reference/api/tabs)）。
- 扩展直接上传 = **悬浮球不参与传输**，链路最短。

### 路径 2（要整页/滚动区）：Chrome 扩展 `chrome.debugger` + CDP `Page.captureScreenshot`

**依赖**：`permissions: ["debugger"]`（会弹「正在调试」黄条，用户信任与商店审核成本高）。

```js
const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
await chrome.debugger.attach({ tabId: tab.id }, "1.3");
const { data } = await chrome.debugger.sendCommand(
  { tabId: tab.id }, "Page.captureScreenshot",
  { format: "png", captureBeyondViewport: true });   // 超出视口 = 整页
await chrome.debugger.detach({ tabId: tab.id });
```

**限制**：
- `captureBeyondViewport` 在 CDP 中标注为 **experimental**（[Page 域文档](https://chromedevtools.github.io/devtools-protocol/tot/Page/)）。
- 企业策略 `DisableScreenshots` / DLP 会直接拦下 attach，报 "Screenshot capture is restricted by policy."（[chrome.debugger 文档](https://developer.chrome.com/docs/extensions/reference/api/debugger)；示例 [chrome-extensions-samples](https://github.com/GoogleChrome/chrome-extensions-samples/tree/main/api-samples/debugger)）。
- 调试条不会被截进图。

### 备选：原生窗口/屏幕捕获（拿不到页面内容，但无需装扩展）

| 方案 | 版本 | 能拿什么 | 限制 |
|---|---|---|---|
| Python `mss` | [10.2.0](https://pypi.org/project/mss/)（[repo](https://github.com/BoboTiG/python-mss)），MIT，Py≥3.9，零依赖 | 多显示器区域像素 | 必须**最先 import mss**，否则别的库先调 `SetProcessDpiAware` 导致高 DPI 缩放错位 |
| Pillow `ImageGrab` | [13.0.0 文档](https://pillow.readthedocs.io/en/stable/reference/ImageGrab.html) | 屏幕区域；**`window=HWND` 参数自 Pillow 11.2.1 起可用** → 按窗口 HWND 捕获 | 仍是像素、仍是可见区 |
| `PrintWindow` | [user32 文档](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-printwindow) | 指定窗口渲染结果 | 阻塞同步；目标程序须处理 WM_PRINT/WM_PRINTCLIENT；`PW_RENDERFULLCONTENT`(0x2) **未在文档中列出（未确认）** |
| WGC | [屏幕捕获文档](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture) | GPU 合成后的窗口帧 | 需 `GraphicsCapturePicker` 用户授权弹窗（带黄框）；仅桌面版；WinUI3 需 `InitializeWithWindow.Initialize` |
| Electron `desktopCapturer` | [文档](https://www.electronjs.org/docs/latest/api/desktop-capturer) | 屏幕/单窗口缩略图 | 主进程专用；默认 thumbnailSize 150×150（设 0 跳过）；拿不到页面 DOM |
| Playwright / Puppeteer | [Playwright 截图](https://playwright.dev/docs/screenshots) | 真·整页 PNG | **控制自己的浏览器实例，不能接管用户已开的 Chrome 标签页** → 与悬浮球场景不匹配 |
| C# `Graphics.CopyFromScreen` | [文档](https://learn.microsoft.com/en-us/dotnet/api/system.drawing.graphics.copyfromscreen) | 屏幕区域像素 | System.Drawing.Common；失败抛 Win32Exception |

---

## 3. 防火墙 / 杀软 / 权限 坑清单

**收件方（目标机）**

1. Windows 防火墙默认**入站全部阻断**；程序首次监听会弹窗，**若用户不是本机管理员则静默生成阻断规则**（[防火墙规则文档](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules)）。
2. 放行（管理员 PowerShell）：`New-NetFirewallRule -DisplayName "Shot In" -Direction Inbound -Program "C:\...\python.exe" -RemoteAddress LocalSubnet -Action Allow`（[New-NetFirewallRule](https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule)）。
3. SMB 需开「文件和打印机共享 (SMB-In)」+「(NB-Session-In)」，端口 **445 / 139**（[SMB 端口官方文档](https://learn.microsoft.com/en-us/windows-server/storage/file-server/best-practices-analyzer/smb-open-file-sharing-ports)）。
4. 共享必须用**带密码的真实本地账号**（PIN 不能用于文件共享认证）、网络=专用网络、网络发现+文件和打印机共享开、密码保护共享开、共享权限里加该账号（[官方站点 Q&A 实操](https://learn.microsoft.com/en-us/answers/questions/5603229/)）。
5. **SMBv1 一律不要开**：已废弃，Win11 默认无 SMB1 客户端/服务端，Win10 Home/Pro 无 SMB1 服务端（[文档](https://learn.microsoft.com/en-us/windows-server/storage/file-server/troubleshoot/smbv1-not-installed-by-default-in-windows)）；检测 `Get-SmbServerConfiguration | Select EnableSMB1Protocol`（[文档](https://learn.microsoft.com/en-us/windows-server/storage/file-server/troubleshoot/detect-enable-and-disable-smbv1-v2-v3)）。
6. **Win11 24H2 起 SMB 签名强制**，会挡工作组/来宾/第三方服务器连接（同上文档）——Top2/Top3 最大隐形坑。
7. LocalSend 需放行 **TCP+UDP 53317**（[localsend README](https://github.com/localsend/localsend)）；路由器 AP 隔离、VPN、企业防火墙会阻断局域网流量。
8. HTTP 接收端建议只监听内网网卡（`--host 192.168.0.23` 而非 `0.0.0.0`）+ 加 token 鉴权。

**杀软 / 打包**

9. 未签名 EXE 会触发 SmartScreen「Windows 已保护你的电脑」；自签名等同未签名；EV 证书已不能绕过；**微软商店是唯一零警告路径**；Win11 的 Smart App Control 会直接拦未签名文件（[SmartScreen 开发者文档](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)；[设置项](https://learn.microsoft.com/en-us/windows/security/threat-protection/windows-defender-smartscreen/windows-defender-smartscreen-available-settings)）。
10. `impacket` 等安全工具库极易被杀软误报 → 不要进产品依赖；PyInstaller 打包的 exe 同样触发信誉提示（需引导用户加白名单）。
11. 目标机首次运行 Python 程序时需允许「专用网络」。

**客户端**

13. 高 DPI：必须最先 `import mss`，否则截图错位；UNC 凭据被 Windows 凭据管理器缓存 → 改密码后 `net use \\ip /delete`。
14. 目标 IP 变更需可重解析（存 IP + 支持「重试/重新发现」）；截图瞬间页面可能正在滚动/动画 → CDP 截图前等 `document.fonts.ready` + 一帧 rAF。

---

## 4. 最终推荐组合

**客户端**：Python 悬浮球 GUI（PySide6 / tkinter）+ `mss` 选区截屏；**「当前页面」交给 Chrome 扩展**，扩展直接 POST 到接收端（悬浮球与传输解耦）。

**接收端**：目标机 `receiver.py`（FastAPI，8765，单目录落盘 + 时间戳文件名 + token 鉴权），用 `New-NetFirewallRule` 只放行 LocalSubnet。

**为什么这样组合**

- **选 HTTP 而非 SMB**：一次性绕开 6 个 Windows 侧配置坑（专用账号/密码、密码保护共享、网络发现、共享权限、防火墙 445、Win11 24H2 起 SMB 签名强制），配置项从 ~6 步降到 1 步；且自定义端口在企业网络里更容易加白。
- **选 FastAPI 而非 filebrowser**：filebrowser 已被归档（继任 FileBrowser Quantum 仍活跃），但它带鉴权/用户/分享等一堆本场景不需要的功能，为「落盘到文件夹」引入它不划算；20 行自写更可控、更少依赖。
- **选扩展 + `captureVisibleTab` 而非原生截屏**：只有它能拿到**浏览器页面内容**而非屏幕像素，且扩展可直接上传、链路最短；只有确实需要整页滚动区时才升级到 `chrome.debugger` + `captureBeyondViewport`（并接受「正在调试」黄条与策略被禁风险）。
- **保留 UNC 直写作为降级通道**：目标机不允许装 Python 时，用 `shutil.copy2` 写 `\\IP\share`，配置清单见第 3 节。
- **保留手填 IP + zeroconf 双通道**：mDNS 在 Windows 上依赖「网络发现」且受 VPN/虚拟网卡干扰，手填 IP 永远是兜底。
- **不选 LocalSend/PairDrop 作为默认**：协议成熟、零代码，但目标机要装 App、接收目录在 App 里配、还多一个 53317 端口的放行负担——适合当「手动补发」备用通道，不适合做默认链路。

**落地顺序**：① 先用 `receiver.py` + `requests` 跑通「本地 PNG → 目标机文件夹」；② 再接 `mss` 选区截图与扩展的当前页面截图；③ 最后加 zeroconf 自动发现、token 鉴权、断线重试与降级到 UNC。\n