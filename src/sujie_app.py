"""统一入口：模式启动器、截图端、接收端和自检。

    速截.exe                        → 按本机模式启动/首次选择模式
    速截.exe --receiver             → 接收端（托盘服务）
    速截.exe --client               → 截图端（悬浮球）
    速截.exe --mode both            → 同时启动截图端和接收端
    速截.exe --choose-mode          → 重新选择本机工作模式
    速截.exe --selftest [--host IP] → 无界面自检（排查用，不弹窗）

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

from sujie import bootstrap  # noqa: E402

if "--selftest" in sys.argv:
    _ROLE = "selftest"
elif "--receiver" in sys.argv:
    _ROLE = "receiver"
elif "--client" in sys.argv:
    _ROLE = "client"
else:
    _ROLE = "launcher"

bootstrap.init_logging(_ROLE)
bootstrap.log_environment()

try:
    if _ROLE == "selftest":
        from sujie.selftest import main as _main  # noqa: E402
    elif _ROLE == "receiver":
        from sujie.receiver import main as _main  # noqa: E402
    elif _ROLE == "client":
        from sujie.client import main as _main  # noqa: E402
    else:
        from sujie.launcher import main as _launcher_main  # noqa: E402

        def _main():
            try:
                index = sys.argv.index("--mode")
                mode = sys.argv[index + 1]
            except (ValueError, IndexError):
                mode = None
            return _launcher_main(mode, force_choose="--choose-mode" in sys.argv)
except Exception:
    bootstrap.log(f"导入 {_ROLE} 模块失败：\n" + traceback.format_exc())
    raise

if __name__ == "__main__":
    raise SystemExit(_main())
