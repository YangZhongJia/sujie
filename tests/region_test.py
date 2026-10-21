"""区域框选测试：验证遮罩窗、拖拽选区与物理坐标换算。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sujie import capture, region, win32util  # noqa: E402

results = []


def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f"  —  {detail}" if detail else ""))
    return condition


def main():
    win32util.enable_dpi_awareness()
    app = QApplication(sys.argv)

    monitors = win32util.enumerate_monitors()
    monitor = monitors[0]
    image, origin = capture.grab_virtual()
    crop = capture.crop_virtual(image, origin, (monitor.left, monitor.top, monitor.right, monitor.bottom))

    selector = region.RegionSelector(crop, monitor)
    picked = {}
    selector.selected.connect(lambda rect: picked.update(rect=rect))
    selector.cancelled.connect(lambda: picked.update(rect=None))

    selector.show()
    app.processEvents()

    start = QPoint(100, 120)
    end = QPoint(420, 360)

    def drag():
        QTest.mousePress(selector, Qt.LeftButton, pos=start)
        QTest.mouseMove(selector, end)
        QTest.mouseRelease(selector, Qt.LeftButton, pos=end)

    QTimer.singleShot(300, drag)
    QTimer.singleShot(1500, app.quit)
    app.exec()

    rect = picked.get("rect")
    check("框选产生了选区", rect is not None, str(rect))
    if rect:
        dpr = selector._dpr or 1.0
        expected = (
            monitor.left + int(round(start.x() * dpr)),
            monitor.top + int(round(start.y() * dpr)),
            monitor.left + int(round(end.x() * dpr)),
            monitor.top + int(round(end.y() * dpr)),
        )
        check("选区物理坐标正确", tuple(rect) == expected, f"{tuple(rect)} vs 期望 {expected}")

        shot = capture.capture_rect(tuple(rect))
        check("选区截图尺寸正确", shot.image.size == (end.x() - start.x(), end.y() - start.y()),
              str(shot.image.size))

    # 极小拖拽应视为取消
    selector2 = region.RegionSelector(crop, monitor)
    picked2 = {}
    selector2.selected.connect(lambda rect: picked2.update(rect=rect))
    selector2.cancelled.connect(lambda: picked2.update(cancelled=True))
    selector2.show()
    app.processEvents()

    def tiny_drag():
        QTest.mousePress(selector2, Qt.LeftButton, pos=QPoint(200, 200))
        QTest.mouseMove(selector2, QPoint(201, 201))
        QTest.mouseRelease(selector2, Qt.LeftButton, pos=QPoint(201, 201))

    QTimer.singleShot(300, tiny_drag)
    QTimer.singleShot(1200, app.quit)
    app.exec()
    check("过小的拖拽视为取消", picked2.get("cancelled") is True, str(picked2))

    failed = [r for r in results if r[0] == "FAIL"]
    print("=" * 60)
    print(f"总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项")
    for _, name, detail in failed:
        print(f"  x {name} {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
