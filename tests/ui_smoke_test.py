"""界面层冒烟测试：设置对话框、悬浮球、托盘可用性 —— 不弹阻塞式窗口。

后台测试覆盖不到的地方（设置页字段收集与校验、悬浮球绘制与接缝 clamp）在这里补上。

用法： python tests\\ui_smoke_test.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# 配置写到临时目录，别碰真实 client.json
_TMP = tempfile.mkdtemp(prefix="sb_ui_")
os.environ["APPDATA"] = _TMP

results: list[tuple[bool, str, str]] = []


def check(ok: bool, name: str, detail: str = "") -> bool:
    results.append((bool(ok), name, detail))
    print(("  [PASS] " if ok else "  [FAIL] ") + name + (f"  ({detail})" if detail else ""))
    return bool(ok)


def main() -> int:  # noqa: C901
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QLabel,
        QMessageBox,
        QSystemTrayIcon,
        QTabWidget,
    )

    from sujie import region, settings_ui
    from sujie.balloon import FloatingBall, make_app_icon
    from sujie.config import ClientConfig
    from sujie.settings_ui import SettingsDialog
    from sujie.uploader import UploadResult

    app = QApplication.instance() or QApplication(sys.argv[:1])

    print("\n[1] 悬浮球")
    cfg = ClientConfig()
    cfg.ball_size = 52
    cfg.ball_opacity = 1.0
    ball = FloatingBall(cfg)
    check(ball.width() >= 40, "悬浮球有尺寸", f"{ball.width()}x{ball.height()}")
    flags = ball.windowFlags()
    check(bool(flags & Qt.FramelessWindowHint), "无边框窗口")
    check(bool(flags & Qt.WindowStaysOnTopHint), "始终置顶")
    check(bool(flags & Qt.WindowDoesNotAcceptFocus), "不抢焦点（保证前台窗口截图准确）")
    check(ball.testAttribute(Qt.WA_TranslucentBackground), "背景透明")

    ball.move(300, 200)
    ball.show()
    app.processEvents()
    img = ball.grab().toImage()
    check(img.width() > 0 and img.height() > 0, "悬浮球可以渲染", f"{img.width()}x{img.height()}")
    opaque = sum(
        1
        for y in range(0, img.height(), 2)
        for x in range(0, img.width(), 2)
        if img.pixelColor(x, y).alpha() > 128
    )
    check(opaque > 50, "球体有可见像素", f"{opaque} 个不透明采样点")

    # 双屏接缝：让球正好骑在第一块屏右边界上，clamp 必须把它整个挪进某块屏内
    first = app.screens()[0].geometry()
    ball.move(first.right() - ball.width() // 2, 100)
    straddles = not any(s.availableGeometry().contains(ball.frameGeometry()) for s in app.screens())
    ball._clamp_to_screen()
    app.processEvents()
    inside = any(s.availableGeometry().contains(ball.frameGeometry()) for s in app.screens())
    check(straddles, "构造出骑在接缝上的小球", f"放到 ({first.right() - ball.width() // 2},100)")
    check(inside, "跨屏接缝的小球被夹回屏内", f"({ball.x()},{ball.y()})")

    print("\n[1b] 点击 / 拖动 判定")
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    def mouse(kind, lx, ly, gx, gy):
        button = Qt.LeftButton if kind != QEvent.MouseMove else Qt.NoButton
        buttons = Qt.NoButton if kind == QEvent.MouseButtonRelease else Qt.LeftButton
        return QMouseEvent(kind, QPointF(lx, ly), QPointF(gx, gy), button, buttons, Qt.NoModifier)

    clicks: list[int] = []
    ball.clicked.connect(lambda: clicks.append(1))

    # 纯粹点一下 → 必须触发 clicked
    ball.mousePressEvent(mouse(QEvent.MouseButtonPress, 10, 10, 300, 200))
    ball.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, 10, 10, 300, 200))
    check(len(clicks) == 1, "原地按下抬起 = 一次点击", f"clicked {len(clicks)} 次")

    # 拖出去再拖回原点 → 不能触发 clicked（防误截图）
    ball.mousePressEvent(mouse(QEvent.MouseButtonPress, 10, 10, 300, 200))
    ball.mouseMoveEvent(mouse(QEvent.MouseMove, 10, 10, 420, 320))
    ball.mouseMoveEvent(mouse(QEvent.MouseMove, 10, 10, 300, 200))
    ball.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, 10, 10, 300, 200))
    check(len(clicks) == 1, "拖出去再回原点不算点击", f"clicked {len(clicks)} 次")

    # 小抖动（未越过阈值）仍算点击
    ball.mousePressEvent(mouse(QEvent.MouseButtonPress, 10, 10, 300, 200))
    ball.mouseMoveEvent(mouse(QEvent.MouseMove, 10, 10, 302, 201))
    ball.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, 10, 10, 302, 201))
    check(len(clicks) == 2, "轻微抖动仍算点击", f"clicked {len(clicks)} 次")

    print("\n[1c] 长按 → 扇形菜单")
    from PySide6.QtTest import QTest

    radials: list[int] = []
    moves: list[int] = []
    commits: list[int] = []
    ball.radialRequested.connect(lambda _p: radials.append(1))
    ball.radialMoved.connect(lambda _p: moves.append(1))
    ball.radialCommitted.connect(lambda _p: commits.append(1))

    before_y = ball.y()

    ball.mousePressEvent(mouse(QEvent.MouseButtonPress, 10, 10, 300, 200))
    QTest.qWait(650)                                  # 超过 500ms 长按阈值
    check(len(radials) == 1, "长按弹出扇形菜单", f"radialRequested {len(radials)} 次")
    check(len(clicks) == 2, "长按不会额外触发截图", f"clicked {len(clicks)} 次")

    ball.mouseMoveEvent(mouse(QEvent.MouseMove, 10, 10, 300, 80))
    check(len(moves) == 1, "菜单展开时移动只更新高亮", f"radialMoved {len(moves)} 次")
    check(ball.y() == before_y, "菜单展开时小球不再跟着移动", f"y {before_y} → {ball.y()}")

    ball.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, 10, 10, 300, 80))
    check(len(commits) == 1, "松手提交扇区", f"radialCommitted {len(commits)} 次")
    check(len(clicks) == 2, "长按松手不算点击", f"clicked {len(clicks)} 次")

    ball._config.radial_enabled = False
    ball.mousePressEvent(mouse(QEvent.MouseButtonPress, 10, 10, 300, 200))
    QTest.qWait(650)
    check(len(radials) == 1, "关掉长按后不再弹菜单", f"radialRequested {len(radials)} 次")
    ball.mouseReleaseEvent(mouse(QEvent.MouseButtonRelease, 10, 10, 300, 200))
    ball._config.radial_enabled = True

    print("\n[2] 设置对话框")
    config_path = Path(_TMP) / "速截" / "client.json"
    cfg2 = ClientConfig()
    dialog = SettingsDialog(cfg2)
    check(dialog.windowTitle() != "", "对话框有标题", dialog.windowTitle())

    tabs = dialog.findChild(QTabWidget)
    check(
        tabs is not None and tabs.count() == 4,
        "四个设置页",
        " / ".join(tabs.tabText(i) for i in range(tabs.count())) if tabs else "没找到 QTabWidget",
    )

    hint_texts = [w.text() for w in dialog.findChildren(QLabel) if w.text()]
    check(any("另一台电脑" in s for s in hint_texts), "接收端页有「在哪台电脑上配置」的引导说明")

    dialog.host_edit.setText("192.168.1.99")
    dialog.port_spin.setValue(9999)
    dialog.token_edit.setText("abc123")
    dialog._add_target()
    collected = dialog._collect()
    target = collected.targets[0]
    check(target["host"] == "192.168.1.99", "接收端 IP 被正确收集", target["host"])
    check(int(target["port"]) == 9999, "端口被正确收集", str(target["port"]))
    check(target["token"] == "abc123", "每个接收端密钥被正确收集", target["token"])

    modes = [dialog.mode_combo.itemData(i) for i in range(dialog.mode_combo.count())]
    check(set(modes) == {"window", "monitor", "screen", "region"}, "四种截图方式都在下拉里", str(modes))
    afters = [dialog.after_capture_combo.itemData(i) for i in range(dialog.after_capture_combo.count())]
    check(set(afters) == {"editor", "send", "copy", "pin"}, "四种截图后动作都在下拉里", str(afters))
    check(dialog.after_capture_combo.currentData() == "editor", "默认动作是打开编辑器",
          str(dialog.after_capture_combo.currentData()))
    dialog.after_capture_combo.setCurrentIndex(dialog.after_capture_combo.findData("send"))
    check(dialog._collect().after_capture == "send", "切换后收集到直接发送",
          str(dialog._collect().after_capture))
    dialog.after_capture_combo.setCurrentIndex(dialog.after_capture_combo.findData("editor"))
    roles = [dialog.role_combo.itemData(i) for i in range(dialog.role_combo.count())]
    check(set(roles) == {"screenshot", "receiver", "both"}, "三个工作模式都可选择", str(roles))

    # 模态框换成记录器，避免测试卡住
    seen: list[str] = []

    class _FakeBox:
        Ok = QMessageBox.Ok
        Yes = QMessageBox.Yes
        No = QMessageBox.No

        @staticmethod
        def warning(_parent, _title, text, *a, **k):
            seen.append(text)
            return QMessageBox.Ok

        @staticmethod
        def question(_parent, _title, text, *a, **k):
            seen.append(text)
            return QMessageBox.Yes

    orig_msgbox = settings_ui.QMessageBox
    orig_test = settings_ui.uploader.test_targets
    settings_ui.QMessageBox = _FakeBox  # type: ignore[assignment]

    def run_accept(dialog):
        """连接测试在后台线程跑，_on_accept 返回后要等线程收尾。

        先把 result 重置掉：对话框第二次保存时 result 可能仍是上次的
        Accepted，等待循环会立即空转退出，线程还没保存就被销毁。
        """
        import time

        dialog.setResult(QDialog.Rejected)
        dialog._on_accept()
        waited = 0.0
        while dialog.result() != QDialog.Accepted and waited < 8.0:
            time.sleep(0.02)
            app.processEvents()
            waited += 0.02

    try:
        dialog._targets.clear()
        dialog._refresh_targets()
        dialog.host_edit.setText("")
        run_accept(dialog)
        check(dialog.result() == QDialog.Accepted, "可先保存模式、稍后配置接收端")

        # 填好 + 测试连接通过 → 应写入 client.json
        seen.clear()
        settings_ui.uploader.test_targets = lambda _t: UploadResult(True, "连接正常")
        dialog.host_edit.setText("127.0.0.1")
        dialog.port_spin.setValue(18765)
        dialog._add_target()
        run_accept(dialog)
        check(dialog.result() == QDialog.Accepted, "填好后保存成功")
    finally:
        settings_ui.QMessageBox = orig_msgbox  # type: ignore[assignment]
        settings_ui.uploader.test_targets = orig_test

    check(config_path.exists(), "设置已落盘", str(config_path))
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        target = data.get("targets", [{}])[0]
        check(target.get("host") == "127.0.0.1" and int(target.get("port") or 0) == 18765,
              "落盘的接收端目标正确", f"{target.get('host')}:{target.get('port')}")
        role_path = Path(_TMP) / "速截" / "mode.json"
        check(json.loads(role_path.read_text(encoding="utf-8")).get("mode") == "screenshot",
              "工作模式已记住")
        required = {
            "targets", "capture_mode", "after_capture", "show_ball",
            "record_mode", "record_fps", "record_send_after",
            "radial_enabled", "radial_radius", "pin_max_count", "history_limit",
        }
        missing = sorted(required - set(data))
        check(not missing, "配置字段齐全",
              ("缺少 " + ", ".join(missing)) if missing else f"{len(data)} 个键")

    dialog.deleteLater()
    app.processEvents()

    print("\n[3] 图标与区域遮罩")
    icon = make_app_icon("#e94f37")
    check(not icon.isNull(), "应用图标可用", f"{icon.availableSizes()}")
    check(hasattr(region, "RegionSelector"), "区域选择器类存在")
    check(callable(getattr(region, "select_region", None)), "select_region 可调用")

    print("\n[4] 托盘可用性")
    check(QSystemTrayIcon.isSystemTrayAvailable(), "系统托盘可用")

    print("\n[5] 截图失败的提示文案")
    from sujie import client as client_mod

    locked = client_mod.capture_error_text(OSError("screen grab failed"))
    check("锁定" in locked, "锁屏时提示看得懂", locked)
    other = client_mod.capture_error_text(RuntimeError("找不到可截图的窗口"))
    check("找不到可截图的窗口" in other, "其它异常带上原因", other)

    ball.hide()
    ball.deleteLater()
    app.processEvents()

    passed = sum(1 for ok, _, _ in results if ok)
    print(f"\n==== 结果 {passed}/{len(results)} 通过 ====")
    for ok, name, detail in results:
        if not ok:
            print(f"  失败：{name}  {detail}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
