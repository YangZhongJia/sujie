"""ShotBridge 客户端入口（截图端）。"""

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shotbridge import bootstrap  # noqa: E402

bootstrap.init_logging("client")
bootstrap.log_environment()

try:
    from shotbridge.client import main  # noqa: E402
except Exception:
    bootstrap.log("导入客户端模块失败：\n" + traceback.format_exc())
    raise

if __name__ == "__main__":
    raise SystemExit(main())
