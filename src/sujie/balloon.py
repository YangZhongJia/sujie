"""桌面悬浮小球：可拖动、单击截图、右键菜单。"""

from __future__ import annotations

import json
import time
from typing import Optional

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import bootstrap
from .config import ClientConfig

DRAG_THRESHOLD = 6  # 像素，小于该位移视为「点击」
LONG_PRESS_MS = 500  # 长按多久弹出扇形菜单


def make_app_icon(color: str = "#e94f37", size: int = 64) -> QIcon:
    """程序图标（运行时绘制，避免额外资源文件）。"""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(QBrush(QColor(color)))
    painter.setPen(QPen(QColor("#ffffff"), max(2, size // 16)))
    painter.drawEllipse(2, 2, size - 4, size - 4)
    # 相机机身
    body_w, body_h = size * 0.42, size * 0.30
    x = (size - body_w) / 2
    y = (size - body_h) / 2 + size * 0.04
    painter.setBrush(QBrush(QColor(255, 255, 255)))
    painter.setPen(QPen(QColor("#ffffff"), 1))
    painter.drawRoundedRect(int(x), int(y), int(body_w), int(body_h), 4, 4)
    painter.setBrush(QBrush(QColor(color)))
    painter.drawEllipse(int(x + body_w * 0.34), int(y + body_h * 0.22), int(body_w * 0.32), int(body_w * 0.32))
    painter.end()
    return QIcon(pixmap)


class FloatingBall(QWidget):
    """无边框、置顶、半透明的小球。"""

    clicked = Signal()
    menuRequested = Signal(QPoint)

    # 长按扇形菜单：requested=展开（参数=球心全局坐标），moved=指针位置，committed=松手
    radialRequested = Signal(QPoint)
    radialMoved = Signal(QPoint)
    radialCommitted = Signal(QPoint)

    def __init__(self, config: ClientConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._press_global: Optional[QPoint] = None
        self._press_time = 0.0
        self._offset = QPoint(0, 0)
        self._dragged = False
        self._busy = False
        self._radial_active = False
        self._recording = False
        self._record_text = ""
        self._pulse_phase = 0.0

        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.timeout.connect(self._on_long_press)

        self._pulse_timer = QTimer(self)
        self._pulse_timer.timeout.connect(self._on_pulse)

        size = max(28, int(config.ball_size))
        self.setFixedSize(size, size)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowOpacity(float(config.ball_opacity))
        self.setToolTip("速截：单击截图并编辑后发送\n拖动可移动位置，右键打开菜单")

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event):  # noqa: N802
        from PySide6.QtGui import QRadialGradient

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        size = self.width()
        color = QColor(self._config.ball_color)
        if self._busy:
            color = QColor("#9aa0a6")
        if self._recording:
            color = QColor("#d32f2f")

        # 外圈（录制时按脉冲相位呼吸）
        painter.setBrush(Qt.NoBrush)
        if self._recording:
            alpha = int(120 + 135 * self._pulse_phase)
            painter.setPen(QPen(QColor(255, 82, 82, alpha), 3))
        else:
            painter.setPen(QPen(QColor(255, 255, 255, 220), 2))
        painter.drawEllipse(1, 1, size - 2, size - 2)

        # 主体渐变
        radial = QRadialGradient(
            size * 0.35, size * 0.30, size * 0.8,
        )
        radial.setColorAt(0.0, color.lighter(140))
        radial.setColorAt(1.0, color.darker(115))
        painter.setBrush(QBrush(radial))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(3, 3, size - 6, size - 6)

        if self._recording:
            self._paint_recording(painter, size)
            return

        # 相机图标
        painter.setPen(QPen(QColor(255, 255, 255), max(1.5, size / 22)))
        icon_w, icon_h = size * 0.44, size * 0.32
        x = (size - icon_w) / 2
        y = (size - icon_h) / 2 + size * 0.03
        painter.drawRoundedRect(int(x), int(y), int(icon_w), int(icon_h), 3, 3)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(int(x + icon_w * 0.33), int(y + icon_h * 0.20), int(icon_w * 0.34), int(icon_w * 0.34))

    def _paint_recording(self, painter: QPainter, size: int) -> None:
        """录制态：白色方块 + 计时文字。"""
        side = max(8.0, size * 0.30)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(
            QRectF((size - side) / 2, size * 0.30 - side / 2, side, side), 2.0, 2.0
        )
        if self._record_text:
            font = QFont(self.font())
            font.setPixelSize(max(8, int(size * 0.19)))
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QPen(QColor(255, 255, 255, 235)))
            painter.drawText(
                QRectF(0, size * 0.60, size, size * 0.24),
                int(Qt.AlignCenter),
                self._record_text,
            )

    # ------------------------------------------------------------------ 交互
    def _long_press_ms(self) -> int:
        """长按阈值（毫秒），限制在 200–1500 之间，配置写错也不会卡死交互。"""
        raw = getattr(self._config, "radial_long_press_ms", LONG_PRESS_MS) or LONG_PRESS_MS
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = LONG_PRESS_MS
        return max(200, min(1500, value))

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._press_time = time.monotonic()
            self._offset = self._press_global - self.frameGeometry().topLeft()
            self._dragged = False
            self._radial_active = False
            if bool(getattr(self._config, "radial_enabled", True)) and not self._busy:
                self._long_press_timer.start(self._long_press_ms())

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._press_global is None:
            return
        pos = event.globalPosition().toPoint()
        if self._radial_active:
            self.radialMoved.emit(pos)      # 菜单已展开：只更新高亮，球不动
            return
        if not self._dragged and (pos - self._press_global).manhattanLength() > DRAG_THRESHOLD:
            self._dragged = True
            self._long_press_timer.stop()   # 开始拖动就不再触发长按
        if self._dragged:
            self.move(pos - self._offset)
            self._clamp_to_screen()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._press_global is not None:
            pos = event.globalPosition().toPoint()
            moved = (pos - self._press_global).manhattanLength()
            dragged = self._dragged
            busy = self._busy
            radial = self._radial_active
            self._long_press_timer.stop()
            self._press_global = None
            self._radial_active = False
            if radial:
                bootstrap.log(f"鼠标释放 → 扇形菜单提交（位移 {moved}px）")
                self.radialCommitted.emit(pos)
                return
            # 只要拖动过程中曾经越过阈值，就不算点击（防止「拖完回到原点」误触发截图）
            held = time.monotonic() - self._press_time
            long_press_expected = held >= self._long_press_ms() * 0.8
            if moved <= DRAG_THRESHOLD and not dragged and not busy and not long_press_expected:
                bootstrap.log(f"鼠标释放 → 判定为点击（位移 {moved}px）")
                self.clicked.emit()
            elif moved <= DRAG_THRESHOLD and not dragged and long_press_expected:
                # 长按了但立刻松手：绝大多数是用户本来想开扇区又放弃，
                # 如果这里还判成点击，就会莫名其妙多截一张图。
                bootstrap.log(f"鼠标释放 → 长按后松手，忽略（位移 {moved}px，按住 {held:.2f}s）")
            elif dragged:
                bootstrap.log(f"鼠标释放 → 判定为拖动（位移 {moved}px），保存位置")
                self._save_position()
            else:
                bootstrap.log(f"鼠标释放 → 忽略（位移 {moved}px 拖动={dragged} 忙={busy}）")

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        # 双击交给单击处理（录制中双击 = 停止），避免吞掉事件
        self.mousePressEvent(event)

    def _on_long_press(self) -> None:
        if self._press_global is None or self._dragged or self._busy:
            return
        if not bool(getattr(self._config, "radial_enabled", True)):
            return
        self._radial_active = True
        bootstrap.log("长按触发 → 弹出扇形菜单")
        self.radialRequested.emit(self.geometry().center())

    def _on_pulse(self) -> None:
        self._pulse_phase = 0.0 if self._pulse_phase >= 1.0 else self._pulse_phase + 0.25
        self.update()

    def contextMenuEvent(self, event):  # noqa: N802
        self.menuRequested.emit(event.globalPos())

    # ------------------------------------------------------------- 位置管理
    def restore_position(self) -> None:
        raw = self._config.ball_position
        if not raw:
            self.move_to_default()
            return
        try:
            x, y = json.loads(raw)
            self.move(int(x), int(y))
        except Exception:
            self.move_to_default()
        self._clamp_to_screen()

    def move_to_default(self) -> None:
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        self.move(area.right() - self.width() - 140, area.top() + 140)

    def _save_position(self) -> None:
        pos = self.pos()
        self._config.ball_position = json.dumps([pos.x(), pos.y()])
        try:
            self._config.save()
        except Exception:
            pass

    def _clamp_to_screen(self) -> None:
        """保证小球完整落在某一块屏幕里（避免卡在两屏接缝或飞出屏幕）。"""
        rect = self.geometry()
        # 完整落在任意一块屏幕内就没问题（双屏接缝处会横跨两块屏，判为不合格）
        for screen in QApplication.screens():
            if screen.availableGeometry().contains(rect):
                return
        screen = QApplication.screenAt(rect.center()) or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        pos = self.pos()
        x = min(max(pos.x(), area.left()), area.right() - self.width() + 1)
        y = min(max(pos.y(), area.top()), area.bottom() - self.height() + 1)
        if (x, y) != (pos.x(), pos.y()):
            self.move(x, y)

    # ---------------------------------------------------------------- 状态
    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.update()

    def set_recording(self, recording: bool, elapsed: str = "") -> None:
        """切换录制态外观：红环脉冲 + 白方块 + 计时。"""
        self._recording = bool(recording)
        self._record_text = elapsed or ""
        if self._recording:
            if not self._pulse_timer.isActive():
                self._pulse_timer.start(250)
        else:
            self._pulse_timer.stop()
            self._pulse_phase = 0.0
        self.update()

    def set_record_text(self, elapsed: str) -> None:
        self._record_text = elapsed
        if self._recording:
            self.update()

    def is_recording(self) -> bool:
        return self._recording

    def apply_config(self, config: ClientConfig) -> None:
        self._config = config
        size = max(28, int(config.ball_size))
        self.setFixedSize(size, size)
        self.setWindowOpacity(float(config.ball_opacity))
        self.update()
