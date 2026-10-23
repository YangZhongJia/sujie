"""客户端：悬浮小球 → 截图 → 发送到对方电脑。"""

from __future__ import annotations

import io
import os
import sys
import time
from datetime import datetime
from typing import Optional

from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QByteArray,
    QBuffer,
    QIODevice,
    QObject,
    QPoint,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QAction, QCursor, QImage, QPixmap
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QMessageBox, QSystemTrayIcon

from . import (
    APP_NAME,
    __version__,
    bootstrap,
    capture,
    history as history_mod,
    launcher,
    paths,
    pinboard,
    radial,
    recorder,
    region,
    uploader,
    win32util,
)
from .balloon import FloatingBall, make_app_icon
from .config import AppModeConfig, CAPTURE_MODE_LABELS, CAPTURE_MODES, ClientConfig
from .editor import ScreenshotEditor

CLIENT_VALUE_NAME = "速截"
CAPTURE_DEBOUNCE = 0.45  # 秒：两次截图请求的最小间隔，挡住连点/重复点击事件
RECORD_TICK_MS = 500     # 录制计时刷新间隔
HOTKEY_ID = 0xA17
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000


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


class _FileUploadSignals(QObject):
    done = Signal(int, int, str, str, bool, str)


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
                 signals: _UploadSignals, outbox: uploader.Outbox, retry_enabled: bool,
                 history: Optional["history_mod.History"] = None, labels: Optional[list[str]] = None):
        super().__init__()
        self._targets = targets
        self._filename = filename
        self._data = data
        self._signals = signals
        self._outbox = outbox
        self._retry_enabled = retry_enabled
        self._history = history
        self._labels = labels or []

    def run(self):  # noqa: D102
        result = uploader.upload_targets(self._targets, self._filename, self._data)
        queued = bool(result.failed_targets) and self._retry_enabled
        if queued:
            try:
                self._outbox.add(self._filename, self._data, result.failed_targets)
            except OSError:
                queued = False
        if self._history is not None:
            try:
                self._history.add_image(
                    self._filename, self._data, self._labels, result.ok,
                    result.remote_path, result.message,
                )
            except Exception as exc:  # 历史记录失败不能影响发送结果
                bootstrap.log(f"写历史记录失败：{exc!r}")
        self._signals.done.emit(
            result.successful_targets, result.total_targets, result.message, self._filename, queued
        )


class _FileUploadTask(QRunnable):
    """上传磁盘上的大文件（录屏）：边读边发，不占内存。"""

    def __init__(self, targets: list[dict], filename: str, path: str,
                 signals: _FileUploadSignals, outbox: uploader.Outbox, retry_enabled: bool,
                 history: Optional["history_mod.History"] = None, labels: Optional[list[str]] = None):
        super().__init__()
        self._targets = targets
        self._filename = filename
        self._path = path
        self._signals = signals
        self._outbox = outbox
        self._retry_enabled = retry_enabled
        self._history = history
        self._labels = labels or []

    def run(self):  # noqa: D102
        result = uploader.upload_targets_file(self._targets, self._filename, self._path)
        queued = bool(result.failed_targets) and self._retry_enabled
        if queued:
            try:
                self._outbox.add_file(self._filename, self._path, result.failed_targets)
            except OSError:
                queued = False
        if self._history is not None:
            try:
                self._history.add_video(
                    self._path, self._labels, result.ok, result.remote_path, result.message
                )
            except Exception as exc:
                bootstrap.log(f"写历史记录失败：{exc!r}")
        self._signals.done.emit(
            result.successful_targets, result.total_targets, result.message,
            self._filename, queued, self._path,
        )


class _HotkeyFilter(QAbstractNativeEventFilter):
    """接 Ctrl+Alt+R：录制时没有窗口有焦点，只能靠全局热键。"""

    def __init__(self, callback):
        super().__init__()
        self._callback = callback

    def nativeEventFilter(self, event_type, message):  # noqa: N802
        try:
            if event_type in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                import ctypes
                from ctypes import wintypes

                msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == WM_HOTKEY and int(msg.wParam) == HOTKEY_ID:
                    self._callback()
        except Exception:
            pass
        return False, 0


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

        self.history = history_mod.History(limit=self.config.history_limit)
        self.pins = pinboard.PinManager(max_count=self.config.pin_max_count)
        self.recorder = recorder.Recorder()
        self.radial = radial.RadialMenu(accent=self.config.ball_color)
        self._file_signals = _FileUploadSignals(self)
        self._file_signals.done.connect(self._on_video_upload_done)

        self.ball = FloatingBall(self.config)
        self.ball.clicked.connect(lambda: self.capture_and_send("悬浮球点击"))
        self.ball.menuRequested.connect(self._show_ball_menu)
        self.ball.radialRequested.connect(self._on_radial_requested)
        self.ball.radialMoved.connect(self._on_radial_moved)
        self.ball.radialCommitted.connect(self._on_radial_committed)

        self._record_timer = QTimer(self)
        self._record_timer.timeout.connect(self._tick_record)
        self._hotkey_filter: Optional[_HotkeyFilter] = None
        self._hotkey_ok = False

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
        self._register_hotkey()

    # ------------------------------------------------------------- 托盘菜单
    def _build_tray_menu(self) -> None:
        menu = QMenu()

        action_shot = QAction("截图并编辑", menu)
        action_shot.triggered.connect(lambda: self.capture_and_send("托盘菜单"))
        menu.addAction(action_shot)

        self._record_action = QAction("开始录制", menu)
        self._record_action.triggered.connect(lambda: self.toggle_record("托盘菜单"))
        menu.addAction(self._record_action)

        action_history = QAction("最近记录…", menu)
        action_history.triggered.connect(self.show_history)
        menu.addAction(action_history)

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

    # ------------------------------------------------------------ 四向扇形
    def _on_radial_requested(self, center: QPoint) -> None:
        if self._busy or self.recorder.is_recording():
            return
        if not self.radial.is_open():
            self.radial.open_at(center, self.config.radial_radius)

    def _on_radial_moved(self, pos: QPoint) -> None:
        if self.radial.is_open():
            self.radial.update_cursor(pos)

    def _on_radial_committed(self, pos: QPoint) -> None:
        if not self.radial.is_open():
            return
        self.radial.update_cursor(pos)
        sector = self.radial.current_sector()
        self.radial.close_menu()
        if not sector:
            return
        action = radial.SECTORS[sector].action
        bootstrap.log(f"扇形菜单选择：{sector} → {action}")
        self._dispatch_sector(action)

    def _dispatch_sector(self, action: str) -> None:
        if action == "screenshot":
            self.capture_and_send("扇形菜单")
        elif action == "record":
            self.toggle_record("扇形菜单")
        elif action == "pin":
            self.pin_capture("扇形菜单")
        elif action == "history":
            self.show_history()

    # ------------------------------------------------------------ 抓屏保护
    def _hide_overlays(self) -> None:
        """抓屏前把扇形菜单和钉图藏起来，否则会被一起截进去。"""
        if self.radial.is_open():
            self.radial.close_menu()
        if self.config.hide_pins_when_capturing:
            self.pins.hide_all()

    def _restore_overlays(self) -> None:
        if self.config.hide_pins_when_capturing:
            self.pins.show_all()

    # -------------------------------------------------------------- 录制
    def toggle_record(self, reason: str = "菜单") -> None:
        if self.recorder.is_recording():
            self.stop_record(reason)
        else:
            self.start_record(reason)

    def start_record(self, reason: str = "菜单") -> None:
        if self.recorder.is_recording():
            return
        if not self.config.targets and self.config.record_send_after:
            self.tray.showMessage(
                APP_NAME, "还没有配置接收端，录制完成后只能存在本机。",
                QSystemTrayIcon.Warning, 4000,
            )
        probe = recorder.probe()
        if not probe.ok:
            bootstrap.log(f"录制不可用：{probe.error}")
            self.tray.showMessage(
                APP_NAME,
                f"录屏需要 ffmpeg，但没有找到：{probe.error}",
                QSystemTrayIcon.Critical, 8000,
            )
            return
        self._hide_overlays()
        try:
            rect = self._record_rect()
        finally:
            self._restore_overlays()
        if rect is None:
            return
        self.ball.hide()
        self.app.processEvents()
        try:
            path = self.recorder.start(
                rect,
                fps=self.config.record_fps,
                audio=self.config.record_audio,
                mic=self.config.record_mic_device,
                out_dir=self.config.record_dir or None,
                max_mb=self.config.record_max_mb,
            )
        except Exception as exc:
            bootstrap.log(f"启动录制失败：{exc!r}")
            self.tray.showMessage(APP_NAME, f"启动录制失败：{exc}", QSystemTrayIcon.Critical, 6000)
            return
        finally:
            self.ball.show()
            self.app.processEvents()
        self.ball.set_recording(True, "00:00")
        self._record_timer.start(RECORD_TICK_MS)
        self._record_action.setText("停止录制并发送")
        self.tray.showMessage(
            APP_NAME, f"开始录制（来源={reason}）\n再长按小球或按 Ctrl+Alt+R 停止",
            QSystemTrayIcon.Information, 3000,
        )
        bootstrap.log(f"开始录制 → {path}")

    def stop_record(self, reason: str = "菜单") -> None:
        if not self.recorder.is_recording():
            return
        self._record_timer.stop()
        ok, path, message = self.recorder.stop()
        self.ball.set_recording(False)
        self._record_action.setText("开始录制")
        bootstrap.log(f"停止录制（来源={reason}）ok={ok} path={path} msg={message}")
        if not ok or path is None:
            self.tray.showMessage(APP_NAME, f"录制失败：{message}", QSystemTrayIcon.Critical, 6000)
            return
        name = os.path.basename(str(path))
        try:
            size_mb = os.path.getsize(path) / 1024 / 1024
        except OSError:
            size_mb = 0.0
        if not self.config.record_send_after or not self.config.targets:
            self.history.add_video(path, [], True, "", "仅保存到本机")
            self.tray.showMessage(
                APP_NAME, f"录制完成：{name}（{size_mb:.1f} MB，已保存到本机）",
                QSystemTrayIcon.Information, 4000,
            )
            return
        labels = [f"{t.get('host')}:{t.get('port')}" for t in self.config.targets]
        self.tray.showMessage(
            APP_NAME, f"录制完成：{name}（{size_mb:.1f} MB），正在发送…",
            QSystemTrayIcon.Information, 3000,
        )
        task = _FileUploadTask(
            [dict(target) for target in self.config.targets], name, str(path),
            self._file_signals, self.outbox, self.config.retry_enabled,
            self.history, labels,
        )
        self.pool.start(task)

    def _tick_record(self) -> None:
        if not self.recorder.is_recording():
            self._record_timer.stop()
            return
        self.ball.set_record_text(self.recorder.elapsed_text())
        if self.recorder.over_size_limit():
            bootstrap.log("录制文件超过上限，自动停止")
            self.tray.showMessage(APP_NAME, "录制文件已达上限，自动停止并发送。", QSystemTrayIcon.Warning, 4000)
            self.stop_record("超过体积上限")

    def _record_rect(self):
        mode = (self.config.record_mode or "monitor").lower()
        if mode == "region":
            self.ball.hide()
            self.app.processEvents()
            try:
                return region.select_region()
            finally:
                self.ball.show()
                self.app.processEvents()
        if mode == "window":
            hwnd = self._target_hwnd()
            rect = win32util.window_rect(hwnd) if hwnd else None
            if rect is None:
                rect = win32util.foreground_window_rect()
            return rect
        if mode == "screen":
            return win32util.virtual_screen_rect()
        cursor = QCursor.pos()
        monitor = win32util.monitor_containing_point(cursor.x(), cursor.y())
        if monitor is not None:
            return (monitor.left, monitor.top, monitor.width, monitor.height)
        return win32util.virtual_screen_rect()

    def _on_video_upload_done(self, succeeded: int, total: int, message: str,
                              filename: str, queued: bool, path: str) -> None:
        bootstrap.log(f"录屏上传结束 成功={succeeded}/{total} 文件={filename} 消息={message}")
        if succeeded == total:
            if self.config.notify_on_send:
                self.tray.showMessage(
                    APP_NAME, f"录屏已发送到 {succeeded} 台电脑：{filename}",
                    QSystemTrayIcon.Information, 3000,
                )
        else:
            self.tray.showMessage(
                APP_NAME,
                f"{message}\n" + ("失败目标已加入待发队列。" if queued else "请检查连接后重试。"),
                QSystemTrayIcon.Warning, 5000,
            )
        self._flush_outbox()

    # -------------------------------------------------------------- 贴图
    def pin_capture(self, reason: str = "菜单") -> None:
        if self._busy:
            return
        self._busy = True
        self.ball.set_busy(True)
        self._hide_overlays()
        try:
            shot = self._capture()
        except Exception as exc:
            bootstrap.log(f"贴图截图失败：{exc!r}")
            self.tray.showMessage(APP_NAME, capture_error_text(exc), QSystemTrayIcon.Warning, 5000)
            return
        finally:
            self._busy = False
            self.ball.set_busy(False)
            self._restore_overlays()
        if shot is None:
            return
        image, _title = shot
        pixmap = _pil_to_pixmap(image)
        self.pins.create(pixmap)
        bootstrap.log(f"已钉一张图（来源={reason}），当前 {self.pins.count()} 张")

    def close_pins(self) -> None:
        count = self.pins.count()
        self.pins.close_all()
        if count:
            self.tray.showMessage(APP_NAME, f"已关闭 {count} 张钉图", QSystemTrayIcon.Information, 2000)

    # ------------------------------------------------------------ 最近记录
    def show_history(self) -> None:
        dialog = history_mod.HistoryDialog(self.history, self.parent())
        dialog.resendRequested = self._resend_entry
        dialog._sync_buttons()
        dialog.exec()

    def _resend_entry(self, entry) -> None:
        path = entry.local_path
        if not path or not os.path.isfile(path):
            self.tray.showMessage(APP_NAME, "本地文件已不存在，无法重新发送。", QSystemTrayIcon.Warning, 4000)
            return
        if not self.config.targets:
            self.tray.showMessage(APP_NAME, "还没有配置接收端。", QSystemTrayIcon.Warning, 4000)
            self.open_settings()
            return
        labels = [f"{t.get('host')}:{t.get('port')}" for t in self.config.targets]
        if entry.kind == "video":
            task = _FileUploadTask(
                [dict(t) for t in self.config.targets], entry.name, path,
                self._file_signals, self.outbox, self.config.retry_enabled, self.history, labels,
            )
        else:
            try:
                with open(path, "rb") as handle:
                    data = handle.read()
            except OSError as exc:
                self.tray.showMessage(APP_NAME, f"读取文件失败：{exc}", QSystemTrayIcon.Warning, 4000)
                return
            signals = _UploadSignals()
            signals.done.connect(self._on_upload_done)
            task = _UploadTask(
                [dict(t) for t in self.config.targets], entry.name, data,
                signals, self.outbox, self.config.retry_enabled, self.history, labels,
            )
        self.pool.start(task)
        bootstrap.log(f"重新发送：{entry.name}")

    # -------------------------------------------------------------- 热键
    def _register_hotkey(self) -> None:
        import ctypes

        try:
            self._hotkey_filter = _HotkeyFilter(lambda: self.toggle_record("全局热键"))
            self.app.installNativeEventFilter(self._hotkey_filter)
            ok = ctypes.windll.user32.RegisterHotKey(
                None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord("R")
            )
            self._hotkey_ok = bool(ok)
            bootstrap.log(f"注册 Ctrl+Alt+R 热键：{'成功' if ok else '失败（可能已被占用）'}")
        except Exception as exc:
            bootstrap.log(f"注册热键异常：{exc!r}")

    def _unregister_hotkey(self) -> None:
        if not self._hotkey_ok:
            return
        try:
            import ctypes

            ctypes.windll.user32.UnregisterHotKey(None, HOTKEY_ID)
        except Exception:
            pass
        self._hotkey_ok = False

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
        if self.recorder.is_recording():
            # 录制中单击小球 = 停止录制（并按配置发送），这是用户最直觉的操作
            bootstrap.log("  正在录制，本次点击判定为「停止录制」")
            self.stop_record(f"{reason}（停止）")
            return
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
        self._hide_overlays()
        try:
            shot = self._capture()
        except Exception as exc:
            self._busy = False
            self.ball.set_busy(False)
            self._restore_overlays()
            bootstrap.log(f"截图失败：{exc!r}")
            self.tray.showMessage(
                APP_NAME, capture_error_text(exc), QSystemTrayIcon.Warning, 5000
            )
            return
        self._restore_overlays()
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
                bootstrap.log("  编辑器里取消了，本次不发送")
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
        self._unregister_hotkey()
        if self.recorder.is_recording():
            try:
                self.recorder.stop()
            except Exception:
                pass
        try:
            self.config.save()
        except Exception:
            pass
        self.app.quit()


def _pil_to_pixmap(image) -> QPixmap:
    """PIL 图像 → QPixmap（走 PNG 中转，纯 RGBA/RGB 都稳）。"""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    pixmap = QPixmap()
    if not pixmap.loadFromData(buffer.getvalue(), "PNG"):
        raise RuntimeError("无法转换为显示图像")
    return pixmap


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
    from .theme import apply_theme

    apply_theme(app)
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
