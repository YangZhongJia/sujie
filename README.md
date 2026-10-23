# 速截

Windows 截图 / 录屏工具：点悬浮球，编辑截图后发送到一台或多台接收电脑。

## 功能

- 单击悬浮球截图，**长按弹出四向扇形菜单**：上滑截图、左滑录屏、右滑贴图、下滑最近记录
- 支持活动窗口、当前显示器、整个屏幕和手动框选
- 截图后可画笔标注、画箭头、矩形和圆形、添加文字、打马赛克，并撤销/重做
- 录屏用内置 ffmpeg（窗口/显示器/整屏/框选），录完自动发送，支持流式上传大文件
- 截图可以「贴」在屏幕最上层对照，支持滚轮缩放、拖动、双击关闭
- 最近记录：保留最近 200 条截图/录屏，可一键重新发送
- 可扫描局域网或手动添加多个接收端，每个接收端可设独立密钥
- 断网时只为未送达的接收端排队补发，已送达端不会重复收到
- 每台电脑可选截图、收图或同时截图和收图模式

## 使用

两台或多台 Windows 电脑安装同一个安装包，并连接到同一局域网。

1. 首次启动选择本机模式：只截图、只收图、同时截图和收图。之后可在设置或接收端托盘菜单中更改。
2. 收图电脑启动接收端；右键托盘图标可查看 IP、打开保存目录或更改保存目录。
3. 截图电脑在设置中扫描或手动添加接收电脑。需要共享密钥时，为每个目标填写对应密钥。
4. 单击悬浮球截图（松手即截），完成标注后点“发送”；长按悬浮球往左滑开始录屏，再单击小球停止并发送。默认保存到接收电脑的「图片\\速截」目录，按日期分文件夹。

也可以按 `Ctrl+Alt+R` 开始/停止录屏。

当前只支持 Windows 10/11 64 位。传输使用局域网 HTTP，不经过云服务；共享密钥可防止未授权上传，但传输内容未加密。请只在可信局域网使用。

## 构建

需要 Windows、Python 3.10 或更新版本、Inno Setup 6：

```powershell
python -m pip install PySide6 Pillow PyInstaller imageio-ffmpeg
# ffmpeg.exe 不进仓库（87 MB），tools\package.ps1 会自动从 imageio-ffmpeg 复制到 assets\bin\
powershell -NoProfile -ExecutionPolicy Bypass -File tools\package.ps1
```

安装包输出到 `dist\installer\速截-Setup-1.1.0.exe`。

## 检查

```powershell
python tests\smoke_test.py
python tests\editor_test.py
python tests\ui_smoke_test.py
python tests\interaction_test.py
python tests\record_test.py
python tests\e2e_exe_test.py
```

端到端测试需要已解锁的 Windows 桌面。

## 许可证

本仓库尚未指定许可证。公开仓库不代表授权复制、修改或分发；发布前请补充所需许可证。
