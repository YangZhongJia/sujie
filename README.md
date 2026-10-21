# 速截

Windows 桌面截图工具：点悬浮球截图，自动通过局域网发送到另一台电脑。

## 功能

- 拖动悬浮球，单击截图并发送
- 支持活动窗口、当前显示器、整个屏幕和手动框选
- 自动扫描局域网接收端，也可手动填写 IP
- 断网时暂存截图，连接恢复后自动补发
- 图片保存在接收电脑本地，不经过云服务

## 快速开始

两台电脑都安装同一个 Windows 安装包，并连接到同一个局域网。

1. 收图电脑：从开始菜单启动「接收端（托盘服务）」。右键托盘图标可查看 IP、打开或更改保存目录。
2. 截图电脑：启动「截图端（悬浮球）」。首次运行会打开设置，扫描并双击收图电脑；也可以手动填写 IP 和端口。
3. 保存连接设置后，点击悬浮球截图发送。默认保存到收图电脑的「图片\\ShotBridge」目录，按日期分文件夹。

当前程序只支持 Windows 10/11 64 位。默认 HTTP 传输只适合可信的局域网；可在接收端设置共享密钥。传输内容未加密。

## 从源码构建

需要 Windows、Python 3.10 或更新版本、Inno Setup 6：

```powershell
python -m pip install PySide6 Pillow PyInstaller
powershell -NoProfile -ExecutionPolicy Bypass -File tools\package.ps1
```

安装包输出到 `dist\installer\ShotBridge-Setup-1.0.0.exe`。只构建便携目录可加 `-SkipInstaller`。

端到端测试（需要已解锁的 Windows 桌面）：

```powershell
python tests\e2e_exe_test.py
```

## 许可证

本仓库尚未指定许可证。公开仓库不代表授权复制、修改或分发；发布前请补充所需许可证。
