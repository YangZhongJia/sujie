"""ShotBridge —— 悬浮小球截图 + 局域网跨机投递。

模块划分：
    paths        应用数据目录
    config       客户端 / 接收端配置（JSON 持久化）
    win32util    DPI 感知、前台窗口、显示器枚举、开机自启
    capture      屏幕 / 窗口 / 区域截图
    region       区域框选遮罩窗
    uploader     HTTP 上传 + 离线重发队列
    discovery    UDP 局域网设备自动发现
    balloon      桌面悬浮小球
    settings_ui  设置对话框
    client       客户端主程序
    receiver     接收端主程序（HTTP 服务 + 托盘）
"""

__version__ = "1.0.0"
APP_NAME = "ShotBridge"
APP_TITLE = "ShotBridge 截图传输"
