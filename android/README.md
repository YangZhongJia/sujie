# 速截 · Android

桌面版「速截」的 Android 客户端 / 接收端，走**同一套线协议**，所以 Windows 电脑和平板可以互相发。

## 能力

| 能力 | 说明 |
| --- | --- |
| 桌面悬浮球 | 单击截图并发送，长按弹菜单（截图 / 框选 / 接收端开关 / 打开 / 隐藏），可拖动并记住位置 |
| 静默截图 | 通过无障碍服务 `takeScreenshot()`，开启一次后**不再弹任何系统框** |
| 屏幕录制授权兜底 | 没开无障碍时回退到 MediaProjection（每次会话系统强制弹「立即开始」确认，无法绕过） |
| 作为接收端 | 常驻 HTTP 服务（TCP 8765）+ UDP 设备发现（8766），Windows 端能直接扫到并发送 |
| 局域网发现 | 广播 `SHOTBRIDGE_DISCOVER`，同时向各网卡子网广播（受限广播在部分机型/AP 上会被丢） |
| 离线待发队列 | 发送失败的文件落盘 + `.meta`，只补发没成功的接收端，上限 200 条 |
| 多目标并行 | 最多 4 路并发，与桌面端 `MAX_PARALLEL_TARGETS` 一致 |
| 收到即入图库 | 可选，Android 10+ 走 MediaStore |

## 与桌面端协议一致的部分

代码在 `core/`（纯 JVM，无 Android 依赖），全部对齐 `src/sujie/`：

| 项 | 值 |
| --- | --- |
| 魔数 | `SHOTBRIDGE_DISCOVER` / `SHOTBRIDGE_REPLY` |
| 端口 | TCP 8765（HTTP）、UDP 8766（发现） |
| 路由 | `GET /ping`、`GET /health`、`GET /`、`POST /upload` |
| 请求头 | `X-File-Name`（URL 编码）、`X-Size`、`X-Stream`、`X-Keep-Name`、`X-Token` |
| 鉴权 | token 为空放行；否则 `X-Token` 必须相等，否则 401 |
| 超限 | 413 + `文件太大（上限 N MB）…` |
| 命名 | `shot-YYYYmmdd-HHMMSS.ext`；保留原名时 stem 截断 80 字符；重名加 `-1`/`-2` |
| 落盘 | 先写 `.part` 再改名，重名检查在锁内 |
| 配置 | `client.json` / `receiver.json`，字段名与桌面端一致，可互相拷贝 |

## 构建

需要 JDK 17、Android SDK 34。仓库路径含中文时：

- `gradle.properties` 里必须保留 `android.overridePathCheck=true`（AGP 的硬检查）；
- **不要**在 `org.gradle.jvmargs` 里加 `-Dfile.encoding=UTF-8`——Gradle 用它写测试 worker 的 `@argfile`，但 JVM 读该文件用系统编码（中文 Windows 是 GBK），非 ASCII 路径会被读坏，表现为 `ClassNotFoundException`。

```powershell
cd android
# 方式一：设好环境变量后直接用 wrapper
$env:JAVA_HOME = "C:\path\to\jdk-17"
$env:ANDROID_HOME = "C:\path\to\android-sdk"
.\gradlew.bat :core:test :app:assembleDebug

# 方式二：把路径写进 _build.bat（含本机绝对路径，已 gitignore）后
.\_build.bat :core:test :app:assembleDebug

adb install -r app\build\outputs\apk\debug\app-debug.apk
```

## 首次使用

1. 打开应用 → 允许通知；
2. 授予「显示在其他应用上层」（悬浮球必需，平台限制）；
3. **开启静默截图**：应用内点「开启静默截图」→ 系统无障碍设置里打开「速截」。
   不开启也能用，但每次截图都会弹系统屏幕录制确认框；
4. 在「接收端」里扫描局域网或填 IP；
5. 点悬浮球即可截图发送。

## 验证

`core` 的 22 个 JVM 单元测试覆盖协议兼容性（`:core:test`），包括：

- 魔数、端口、UA、文件名百分号编码与 `urllib.parse.quote` 一致；
- 上传/落盘字节完全一致、保留中文原名、重名不覆盖、`.part` 清理；
- token 不匹配与超限时的错误文案；
- 多目标部分失败汇总、待发队列只补发失败目标；
- 配置往返与手工改坏文件的容错；
- 真实 UDP 发现往返。

跨端互通已实测：桌面端 `uploader.http_upload` / `http_upload_file`（含 3 MB 流式与中文文件名）→ 平板接收端落盘成功；平板悬浮球静默截图 → 桌面端接收端落盘成功。

## 已知平台限制

- 截图必须有一次系统级授权（无障碍服务或 MediaProjection），任何应用都无法绕过。
- MediaProjection 一个会话只能 `createVirtualDisplay` 一次（Android 14 硬限制），所以实现里 VirtualDisplay 常驻、旋转时 `resize` 而不是重建。
- 悬浮球需要 `SYSTEM_ALERT_WINDOW`。
