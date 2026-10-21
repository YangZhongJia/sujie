"""客户端：悬浮小球 → 截图 → 发送到对方电脑。"""

from __future__ import annotations

import io
import os
import sys
import time
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QImage
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon

from . import APP_NAME, __version__, bootstrap, capture, launcher, paths, region, uploader, win32util
from .balloon import FloatingBall, make_app_icon
from .config import AppModeConfig, CAPTURE_MODE_LABELS, CAPTURE_MODES, ClientConfig
from .editor import ScreenshotEditor

CLIENT_VALUE_NAME = "速截"
CAPTURE_DEBOUNCE = 0.45  # 秒：两次截图请求的最小间隔，挡住连点/重复点击事件


def capture_error_text(exc: Exception) -> str:
    """把截图异常翻译成用户看得懂的一句话。"""
    text = str(exc)
    if isinstance(exc, OSError) or "screen grab failed" in text:
        return "截图失败：屏幕可能已锁定（锁屏或远程桌面已断开），解锁后再点小球。"
    if isinstance(exc, RuntimeError):
        return f"截图失败：{text}"
    return f"截图失败：{text or exc.__class__.__name__}"


class _UploadSignals(QObject):
    done = Signal(int, int, str, str, bool)


class _FlushSignals(QObject):
    done = Signal(int)


class _FlushTask(QRunnable):
    def __init__(self, config: ClientConfig, outbox: uploader.Outbox, signals: _FlushSignals):
        super().__init__()
        self.config = config
        self.outbox = outbox
        self.signals = signals

    def run(self):  # noqa: D102
        self.signals.done.emit(uploader.flush_outbox(self.config, self.outbox))


class _UploadTask(QRunnable):
    """后台线程执行上传，避免阻塞界面。"""

    def __init__(self, targets: list[dict], filename: str, data: bytes,
                 signals: _UploadSignals, outbox: uploader.Outbox, retry_enabled: bool):
        super().__init__()
        self._targets = targets
        self._filename = filename
        self._data = data
        self._signals = signals
        self._outbox = outbox
        self._retry_enabled = retry_enabled

    def run(self):  # noqa: D102
        result = uploader.upload_targets(self._targets, self._filename, self._data)
        queued = bool(result.failed_targets) and self._retry_enabled
        if queued:
            try:
                self._outbox.add(self._filename, self._data, result.failed_targets)
            except OSError:
                queued = False
        self._signals.done.emit(
            result.successful_targets, result.total_targets, result.message, self._filename, queued
        )


class ClientApp(QObject):
    """客户端主控。"""

    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.config = ClientConfig.load()
        self._role_mode = AppModeConfig.load().mode or "screenshot"
        self._pending_role_mode: Optional[str] = None
        self.outbox = uploader.Outbox()
        self._busy = False
        self._flush_busy = False
        self._last_capture_ts = 0.0  # 防抖：连点两下只截一张
        self._last_foreground = 0

        self.ball = FloatingBall(self.config)
        self.ball.clicked.connect(lambda: self.capture_and_send("悬浮球点击"))
        self.ball.menuRequested.connect(self._show_ball_menu)

        self.tray = QSystemTrayIcon(make_app_icon(self.config.ball_color), app)
        self.tray.setToolTip(f"{APP_NAME} v{__version__}\n单击悬浮球，编辑后发送")
        self._build_tray_menu()
        self.tray.activated.connect(self._on_tray_activated)

        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(2)
        self._flush_signals = _FlushSignals(self)
        self._flush_signals.done.connect(self._on_flush_done)

        # 跟踪前台窗口：托盘菜单触发截图时前台可能已改变
        self._fg_timer = QTimer(self)
        self._fg_timer.timeout.connect(self._track_foreground)
        self._fg_timer.start(400)

        # 离线补发
        self._retry_timer = QTimer(self)
        self._retry_timer.timeout.connect(self._flush_outbox)
        self._retry_timer.start(int(max(15, self.config.retry_interval)) * 1000)

        if os.environ.get(launcher.MANAGED_ENV) == "1":
            self._role_timer = QTimer(self)
            self._role_timer.timeout.connect(self._check_role_mode)
            self._role_timer.start(1000)

        self.ball.restore_position()
        if self.config.show_ball:
            self.ball.show()
        self.tray.show()

    # ------------------------------------------------------------- 托盘菜单
    def _build_tray_menu(self) -> None:
        menu = QMenu()

        action_shot = QAction("截图并编辑", menu)
        action_shot.triggered.connect(lambda: self.capture_and_send("托盘菜单"))
        menu.addAction(action_shot)

        mode_menu = menu.addMenu("截图方式")
        self._mode_actions = {}
        for key in CAPTURE_MODES:
            action = QAction(CAPTURE_MODE_LABELS.get(key, key), mode_menu, checkable=True)
            action.setChecked(self.config.capture_mode == key)
            action.triggered.connect(lambda _checked, k=key: self._set_capture_mode(k))
            mode_menu.addAction(action)
            self._mode_actions[key] = action

        action_toggle = QAction("显示/隐藏悬浮球", menu)
        action_toggle.triggered.connect(self._toggle_ball)
        menu.addAction(action_toggle)

        menu.addSeparator()

        action_outbox = QAction("打开待发队列文件夹", menu)
        action_outbox.triggered.connect(lambda: win32util.open_path(paths.outbox_dir()))
        menu.addAction(action_outbox)

        action_settings = QAction("设置…", menu)
        action_settings.triggered.connect(self.open_settings)
        menu.addAction(action_settings)

        self.autostart_action = QAction("开机自启", menu, checkable=True)
        self.autostart_action.setChecked(win32util.is_autostart_enabled(CLIENT_VALUE_NAME))
        self.autostart_action.triggered.connect(self._toggle_autostart)
        menu.addAction(self.autostart_action)

        menu.addSeparator()
        action_quit = QAction("退出", menu)
        action_quit.triggered.connect(self.quit)
        menu.addAction(action_quit)

        self.tray.setContextMenu(menu)
        self._menu = menu

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_ball()

    def _show_ball_menu(self, pos) -> None:
        """小球右键菜单：复用托盘菜单。"""
        menu = self._menu
        menu.popup(pos if hasattr(pos, "x") else self.ball.mapToGlobal(self.ball.rect().center()))

    def _toggle_ball(self) -> None:
        if self.ball.isVisible():
            self.ball.hide()
        else:
            self.ball.show()
            self.ball.raise_()

    def _set_capture_mode(self, mode: str) -> None:
        self.config.capture_mode = mode
        self.config.save()
        for key, action in self._mode_actions.items():
            action.setChecked(key == mode)
        self.tray.showMessage(
            APP_NAME,
            f"截图方式已切换为：{CAPTURE_MODE_LABELS.get(mode, mode)}",
            QSystemTrayIcon.Information,
            2000,
        )

    def _toggle_autostart(self) -> None:
        enabled = not win32util.is_autostart_enabled(CLIENT_VALUE_NAME)
        command = paths.startup_target()
        ok = win32util.set_autostart(enabled, CLIENT_VALUE_NAME, command)
        self.autostart_action.setChecked(enabled and ok)
        self.config.auto_start = enabled and ok
        self.config.save()
        self.tray.showMessage(
            APP_NAME,
            "已设置开机自启" if self.config.auto_start else "已取消开机自启",
            QSystemTrayIcon.Information,
            2500,
        )

    def _check_role_mode(self) -> None:
        mode = AppModeConfig.load().mode or "screenshot"
        if mode != self._role_mode:
            self._role_mode = mode
            self._pending_role_mode = mode
        self._apply_pending_role_mode()

    def _apply_pending_role_mode(self) -> None:
        if self._pending_role_mode and not self._busy and not self._flush_busy:
            mode = self._pending_role_mode
            self._pending_role_mode = None
            launcher.launch_mode(mode, current_role="client", app=self.app)

    # -------------------------------------------------------------- 前台跟踪
    def _track_foreground(self) -> None:
        hwnd = win32util.foreground_window()
        if not hwnd:
            return
        try:
            own = int(self.ball.winId())
        except Exception:
            own = 0
        if hwnd == own:
            return
        self._last_foreground = hwnd

    def _target_hwnd(self) -> int:
        """目标窗口：优先用最近一次的前台窗口（托盘菜单触发时也准确）。"""
        current = win32util.foreground_window()
        try:
            own = int(self.ball.winId())
        except Exception:
            own = 0
        if current and current != own:
            return current
        return self._last_foreground

    # ---------------------------------------------------------------- 截图
    def capture_and_send(self, reason: str = "未知") -> None:
        bootstrap.log(f"capture_and_send 被调用（来源={reason}，模式={self.config.capture_mode}，忙={self._busy}）")
        if self._busy:
            bootstrap.log("  上一次截图还没结束，本次忽略")
            return
        if not self.config.targets:
            bootstrap.log("  还没配置接收端，打开设置引导用户")
            self.tray.showMessage(
                APP_NAME,
                "还没有配置接收端。请在设置里添加一台或多台接收电脑。",
                QSystemTrayIcon.Warning,
                5000,
            )
            self.open_settings()
            return
        now = time.monotonic()
        if now - self._last_capture_ts < CAPTURE_DEBOUNCE:
            bootstrap.log(f"  距离上次截图只有 {now - self._last_capture_ts:.2f}s，判定为连点，忽略")
            return
        self._last_capture_ts = now
        self._busy = True
        self.ball.set_busy(True)
        try:
            shot = self._capture()
        except Exception as exc:
            self._busy = False
            self.ball.set_busy(False)
            bootstrap.log(f"截图失败：{exc!r}")
            self.tray.showMessage(
                APP_NAME, capture_error_text(exc), QSystemTrayIcon.Warning, 5000
            )
            return
        if shot is None:
            self._busy = False
            self.ball.set_busy(False)
            return

        image, title = shot
        self.ball.hide()
        self.app.processEvents()
        try:
            editor = ScreenshotEditor(self._to_qimage(image))
            if editor.exec() != QDialog.Accepted:
                self._busy = False
                self.ball.set_busy(False)
                return
            filename, data = self._encode(editor.image, title)
        except Exception as exc:
            self._busy = False
            self.ball.set_busy(False)
            bootstrap.log(f"截图编辑失败：{exc!r}")
            self.tray.showMessage(APP_NAME, f"打开编辑器失败：{exc}", QSystemTrayIcon.Warning, 5000)
            return
        finally:
            self.ball.show()
            self.app.processEvents()

        signals = _UploadSignals()
        signals.done.connect(self._on_upload_done)
        task = _UploadTask(
            [dict(target) for target in self.config.targets], filename, data,
            signals, self.outbox, self.config.retry_enabled,
        )
        self.pool.start(task)

    def _capture(self):
        mode = self.config.capture_mode
        if mode not in CAPTURE_MODES:
            mode = "window"

        if mode == "region":
            self.ball.hide()
            self.app.processEvents()
            try:
                rect = region.select_region()
            finally:
                self.ball.show()
                self.app.processEvents()
            if rect is None:
                return None
            result = capture.capture_rect(rect)
            return result.image, result.title

        if mode == "screen":
            self.ball.hide()
            self.app.processEvents()
            try:
                result = capture.capture_screen()
            finally:
                self.ball.show()
                self.app.processEvents()
            return result.image, result.title

        if mode == "monitor":
            self.ball.hide()
            self.app.processEvents()
            try:
                result = capture.capture_monitor_under_cursor()
            finally:
                self.ball.show()
                self.app.processEvents()
            return result.image, result.title

        # window 模式
        hwnd = self._target_hwnd()
        rect = win32util.window_rect(hwnd) if hwnd else None
        title = win32util.window_title(hwnd) if hwnd else ""
        if rect is None:
            rect = win32util.foreground_window_rect()
        if rect is None:
            raise RuntimeError("找不到可截图的窗口")
        self.ball.hide()
        self.app.processEvents()
        try:
            result = capture.capture_rect(rect)
        finally:
            self.ball.show()
            self.app.processEvents()
        result.title = title
        return result.image, title

    def _encode(self, image, title: str = "") -> tuple[str, bytes]:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = _safe_title(title)
        filename = f"shot-{stamp}{suffix}.png"
        buffer = QByteArray()
        device = QBuffer(buffer)
        device.open(QIODevice.WriteOnly)
        image.save(device, "PNG")
        device.close()
        return filename, bytes(buffer)

    @staticmethod
    def _to_qimage(image) -> QImage:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        result = QImage.fromData(buffer.getvalue(), "PNG")
        if result.isNull():
            raise RuntimeError("无法打开截图图像")
        return result

    # ------------------------------------------------------------ 上传回调
    def _on_upload_done(self, succeeded: int, total: int, message: str, filename: str, queued: bool) -> None:
        bootstrap.log(f"上传结束 成功={succeeded}/{total} 文件={filename} 消息={message}")
        self._busy = False
        self.ball.set_busy(False)
        if succeeded == total:
            if self.config.notify_on_send:
                self.tray.showMessage(
                    APP_NAME, f"已发送到 {succeeded} 台电脑：{filename}", QSystemTrayIcon.Information, 2500
                )
        else:
            self.tray.showMessage(
                APP_NAME,
                f"{message}\n" + ("失败目标已加入待发队列。" if queued else "请检查连接后重试。"),
                QSystemTrayIcon.Warning,
                5000,
            )
        self._flush_outbox()
        self._apply_pending_role_mode()

    def _flush_outbox(self) -> None:
        if not self.config.retry_enabled or self._busy or self._flush_busy:
            return
        if self.outbox.count() == 0:
            return
        self._flush_busy = True
        self.pool.start(_FlushTask(self.config, self.outbox, self._flush_signals))

    def _on_flush_done(self, sent: int) -> None:
        self._flush_busy = False
        if sent:
            self.tray.showMessage(
                APP_NAME, f"已向离线接收端补发 {sent} 张截图", QSystemTrayIcon.Information, 2500
            )
        self._apply_pending_role_mode()

    # ---------------------------------------------------------------- 设置
    def first_run_guide(self) -> None:
        """首次运行且没填接收端 IP：直接弹设置，省得用户点了球才发现发不出去。"""
        if not self.config.targets:
            bootstrap.log("首次运行：未配置接收端，自动打开设置")
            self.tray.showMessage(
                APP_NAME,
                "先添加接收电脑，截图才能发送。",
                QSystemTrayIcon.Information,
                6000,
            )
            self.open_settings()

    def open_settings(self) -> None:
        from .settings_ui import SettingsDialog

        dialog = SettingsDialog(self.config, self.parent())
        if dialog.exec():
            self.config = ClientConfig.load()
            self.ball.apply_config(self.config)
            for key, action in self._mode_actions.items():
                action.setChecked(key == self.config.capture_mode)
            self._retry_timer.setInterval(int(max(15, self.config.retry_interval)) * 1000)
            mode = AppModeConfig.load().mode or "screenshot"
            if mode != self._role_mode:
                self._role_mode = mode
                self._pending_role_mode = mode
                if self._busy or self._flush_busy:
                    self.tray.showMessage(
                        APP_NAME, "当前截图或补发完成后切换工作模式。",
                        QSystemTrayIcon.Information, 3000,
                    )
                self._apply_pending_role_mode()

    def parent(self):
        return None

    def quit(self) -> None:
        try:
            self.config.save()
        except Exception:
            pass
        self.app.quit()


def _safe_title(title: str) -> str:
    if not title:
        return ""
    keep = []
    for ch in title[:24]:
        if ch.isalnum() or ch in "-_ ":
            keep.append(ch)
        else:
            keep.append("_")
    cleaned = "".join(keep).strip().replace(" ", "_")
    return ("-" + cleaned) if cleaned else ""


def main(argv=None) -> int:
    if not bootstrap.acquire_single_instance("速截Client"):
        bootstrap.log("已有客户端在运行，本次退出")
        return 0

    bootstrap.log("准备创建 QApplication…")
    win32util.enable_dpi_awareness()
    app = QApplication(argv or sys.argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    bootstrap.log("QApplication 创建完成")

    controller = ClientApp(app)
    app._sujie_controller = controller  # 防止被回收
    # 首次运行没配接收端时，稍等界面起来再自动弹设置
    QTimer.singleShot(900, controller.first_run_guide)
    bootstrap.log("悬浮球已就绪，进入事件循环")
    code = app.exec()
    bootstrap.log(f"事件循环结束，退出码 {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
