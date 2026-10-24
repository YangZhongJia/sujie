"""GUI 端到端集成测试：真实点击悬浮球 → 截图 → 上传 → 对方电脑落盘。

运行：
    "C:\\Program Files\\Python314\\python.exe" tests\\integration_test.py
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
_SANDBOX_APPDATA = tempfile.mkdtemp(prefix="sb_it_appdata_")
os.environ["APPDATA"] = _SANDBOX_APPDATA

from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from sujie import win32util  # noqa: E402
from sujie.client import ClientApp  # noqa: E402
from sujie.config import ClientConfig, ReceiverConfig, receiver_target  # noqa: E402
from sujie.receiver import start_server  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f"  —  {detail}" if detail else ""))
    return condition


def main():
    win32util.enable_dpi_awareness()

    tmpdir = tempfile.mkdtemp(prefix="sb_it_")
    port = 18766
    receiver_config = ReceiverConfig()
    receiver_config.save_dir = tmpdir
    receiver_config.port = port
    receiver_config.token = ""
    receiver_config.subdir_by_date = False

    httpd, _ = start_server(receiver_config)
    time.sleep(0.3)

    config = ClientConfig()
    config.targets = [receiver_target("127.0.0.1", port)]
    config.capture_mode = "screen"
    config.notify_on_send = False
    config.retry_enabled = False
    config.show_ball = True
    config.save()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = ClientApp(app)
    ball = controller.ball
    ball.show()
    app.processEvents()

    check("悬浮球已显示", ball.isVisible(), f"位置 {ball.pos().x()},{ball.pos().y()}")
    check("悬浮球置顶", bool(ball.windowFlags() & Qt.WindowStaysOnTopHint))
    check("悬浮球不抢焦点", bool(ball.windowFlags() & Qt.WindowDoesNotAcceptFocus))

    def accept_editor():
        for window in app.topLevelWidgets():
            if window.windowTitle() == "编辑截图":
                for button in window.findChildren(QPushButton):
                    if button.text() == "发送":
                        button.click()
                        return
        QTimer.singleShot(100, accept_editor)

    QTimer.singleShot(300, accept_editor)
    # 真实点击小球
    QTest.mouseClick(ball, Qt.LeftButton, pos=QPoint(ball.width() // 2, ball.height() // 2))
    app.processEvents()

    # 等待上传完成
    deadline = time.time() + 15
    landed = None
    while time.time() < deadline:
        files = [f for f in os.listdir(tmpdir) if f.lower().endswith(".png")]
        if files:
            landed = os.path.join(tmpdir, files[0])
            break
        app.processEvents()
        time.sleep(0.1)

    check("截图已上传并落盘", landed is not None, landed or "超时未收到文件")
    if landed:
        size = os.path.getsize(landed)
        check("落盘文件非空", size > 1000, f"{size} 字节")
        try:
            from PIL import Image

            with Image.open(landed) as im:
                check("落盘文件是合法图片", im.width > 0 and im.height > 0, f"{im.width}x{im.height}")
        except Exception as exc:
            check("落盘文件是合法图片", False, str(exc))

    # 拖动不触发截图（阈值判定）
    before = len([f for f in os.listdir(tmpdir) if f.lower().endswith(".png")])
    QTest.mousePress(ball, Qt.LeftButton, pos=QPoint(ball.width() // 2, ball.height() // 2))
    QTest.mouseMove(ball, QPoint(ball.width() // 2 + 60, ball.height() // 2 + 40))
    QTest.mouseRelease(ball, Qt.LeftButton, pos=QPoint(ball.width() // 2 + 60, ball.height() // 2 + 40))
    app.processEvents()
    time.sleep(1.0)
    after = len([f for f in os.listdir(tmpdir) if f.lower().endswith(".png")])
    check("拖动小球不会误触发截图", before == after, f"{before} -> {after}")

    def editor_open() -> bool:
        # accept() 只隐藏对话框不销毁对象，必须看可见性
        return any(w.isVisible() and w.windowTitle() == "编辑截图" for w in app.topLevelWidgets())

    def wait_idle(timeout: float = 10.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline and controller._busy:
            app.processEvents()
            time.sleep(0.1)

    def png_count() -> int:
        return len([f for f in os.listdir(tmpdir) if f.lower().endswith(".png")])

    # 截图后动作 = 直接发送：不弹编辑器，直接上传
    wait_idle()
    time.sleep(0.6)  # 过截图防抖窗口
    controller.config.after_capture = "send"
    before_direct = png_count()
    QTest.mouseClick(ball, Qt.LeftButton, pos=QPoint(ball.width() // 2, ball.height() // 2))
    app.processEvents()
    landed_direct = None
    deadline = time.time() + 15
    while time.time() < deadline:
        if png_count() > before_direct:
            landed_direct = True
            break
        app.processEvents()
        time.sleep(0.1)
    check("直接发送模式截图已落盘", landed_direct is not None,
          f"{before_direct} -> {png_count()}")
    check("直接发送模式没弹编辑器", not editor_open())

    # 截图后动作 = 复制到剪贴板：本机动作，不上传
    wait_idle()
    time.sleep(0.6)
    controller.config.after_capture = "copy"
    QGuiApplication.clipboard().clear()
    before_copy = png_count()
    QTest.mouseClick(ball, Qt.LeftButton, pos=QPoint(ball.width() // 2, ball.height() // 2))
    app.processEvents()
    deadline = time.time() + 5
    clip = QGuiApplication.clipboard().image()
    while time.time() < deadline and (clip.isNull() or clip.width() <= 100):
        app.processEvents()
        time.sleep(0.1)
        clip = QGuiApplication.clipboard().image()
    check("复制模式剪贴板有图", not clip.isNull() and clip.width() > 100,
          f"{clip.width()}x{clip.height()}")
    check("复制模式不产生上传", png_count() == before_copy, f"{before_copy} -> {png_count()}")
    check("复制模式没弹编辑器", not editor_open())

    controller.quit()
    httpd.shutdown()
    httpd.server_close()
    shutil.rmtree(tmpdir, ignore_errors=True)

    failed = [r for r in results if r[0] == FAIL]
    print("=" * 60)
    print(f"总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项")
    for _, name, detail in failed:
        print(f"  x {name} {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
