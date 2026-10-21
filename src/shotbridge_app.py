"""统一入口：一个 exe 三种身份。

    ShotBridge.exe                        → 截图端（悬浮球）
    ShotBridge.exe --receiver             → 接收端（托盘服务）
    ShotBridge.exe --selftest [--host IP] → 无界面自检（排查用，不弹窗）

这样安装包只需要带一份运行时（PySide6 等），体积减半，也避免两个 exe
各自的单实例互斥/开机自启注册互相干扰。
"""

import os
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Windows may otherwise resolve Qt dependencies from another application on PATH.
_dll_dirs = [
    os.add_dll_directory(str(Path(sys._MEIPASS) / name))
    for name in ("PySide6", "shiboken6")
] if getattr(sys, "frozen", False) and sys.platform == "win32" else []

from shotbridge import bootstrap  # noqa: E402

if "--selftest" in sys.argv:
    _ROLE = "selftest"
elif "--receiver" in sys.argv:
    _ROLE = "receiver"
else:
    _ROLE = "client"

bootstrap.init_logging(_ROLE)
bootstrap.log_environment()

try:
    if _ROLE == "selftest":
        from shotbridge.selftest import main as _main  # noqa: E402
    elif _ROLE == "receiver":
        from shotbridge.receiver import main as _main  # noqa: E402
    else:
        from shotbridge.client import main as _main  # noqa: E402
except Exception:
    bootstrap.log(f"导入 {_ROLE} 模块失败：\n" + traceback.format_exc())
    raise

if __name__ == "__main__":
    raise SystemExit(_main())
