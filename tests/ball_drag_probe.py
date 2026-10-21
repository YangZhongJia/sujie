"""探针：用真实鼠标事件拖一下悬浮球，打印 Qt 收到的每个鼠标事件。

用来查「拖动成功后仍然触发了一次截图」这个偶发问题：
如果一次拖动里 Qt 收到两轮 press/release，第二轮的位移必然接近 0 → 被判定成点击。

用法： python tests\\ball_drag_probe.py
"""

from __future__ import annotations

import ctypes
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QEvent, QTimer  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sujie.balloon import FloatingBall  # noqa: E402
from sujie.config import ClientConfig  # noqa: E402

user32 = ctypes.WinDLL("user32", use_last_error=True)

events: list[str] = []


class SpyBall(FloatingBall):
    def mousePressEvent(self, event):  # noqa: N802
        events.append(f"PRESS   local={event.position().toPoint()} global={event.globalPosition().toPoint()}")
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        events.append(f"MOVE    global={event.globalPosition().toPoint()} drag={self._dragged}")
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        moved = (
            abs(event.globalPosition().toPoint().x() - self._press_global.x())
            + abs(event.globalPosition().toPoint().y() - self._press_global.y())
            if self._press_global is not None
            else -1
        )
        events.append(
            f"RELEASE global={event.globalPosition().toPoint()} moved={moved} drag={self._dragged}"
        )
        super().mouseReleaseEvent(event)


def main() -> int:
    app = QApplication(sys.argv[:1])
    cfg = ClientConfig()
    cfg.ball_size = 52
    cfg.ball_opacity = 1.0
    cfg.ball_position = ""
    ball = SpyBall(cfg)
    clicks: list[float] = []
    ball.clicked.connect(lambda: clicks.append(time.time()))
    ball.show()
    app.processEvents()
    time.sleep(0.6)
    app.processEvents()

    rect = ball.frameGeometry()
    print(f"球窗口: ({rect.left()},{rect.top()},{rect.right()},{rect.bottom()})")
    cx, cy = rect.center().x(), rect.center().y()

    def do_drag() -> None:
        user32.SetCursorPos(cx, cy)
        time.sleep(0.2)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.2)
        steps = 16
        for i in range(1, steps + 1):
            user32.SetCursorPos(cx - 220 * i // steps, cy + 120 * i // steps)
            time.sleep(0.04)
        time.sleep(0.2)
        user32.mouse_event(0x0004, 0, 0, 0, 0)

    QTimer.singleShot(300, do_drag)
    QTimer.singleShot(4500, app.quit)
    app.exec()

    print(f"\n拖动过程收到 {len(events)} 个鼠标事件：")
    for line in events:
        print("  " + line)
    moved = ball.frameGeometry().topLeft()
    print(f"\n球位置: ({moved.x()},{moved.y()})  原位置: ({rect.left()},{rect.top()})")
    print(f"clicked 触发次数: {len(clicks)}")
    ok = len(clicks) == 0 and moved.x() != rect.left()
    print("\n==== " + ("符合预期：拖动没有触发点击" if ok else "异常：拖动触发了点击或没移动") + " ====")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
