"""桌面悬浮小球：可拖动、单击截图、右键菜单。"""

from __future__ import annotations

import json
from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from . import bootstrap
from .config import ClientConfig

DRAG_THRESHOLD = 6  # 像素，小于该位移视为「点击」


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

    def __init__(self, config: ClientConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._press_global: Optional[QPoint] = None
        self._offset = QPoint(0, 0)
        self._dragged = False
        self._busy = False

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
        self.setToolTip("ShotBridge：单击截图并编辑后发送\n拖动可移动位置，右键打开菜单")

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        size = self.width()
        color = QColor(self._config.ball_color)
        if self._busy:
            color = QColor("#9aa0a6")

        # 外圈
        painter.setBrush(Qt.NoBrush)
        pen = QPen(QColor(255, 255, 255, 220), 2)
        painter.setPen(pen)
        painter.drawEllipse(1, 1, size - 2, size - 2)

        # 主体渐变
        from PySide6.QtGui import QRadialGradient

        radial = QRadialGradient(
            size * 0.35, size * 0.30, size * 0.8,
        )
        radial.setColorAt(0.0, color.lighter(140))
        radial.setColorAt(1.0, color.darker(115))
        painter.setBrush(QBrush(radial))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(3, 3, size - 6, size - 6)

        # 相机图标
        painter.setPen(QPen(QColor(255, 255, 255), max(1.5, size / 22)))
        icon_w, icon_h = size * 0.44, size * 0.32
        x = (size - icon_w) / 2
        y = (size - icon_h) / 2 + size * 0.03
        painter.drawRoundedRect(int(x), int(y), int(icon_w), int(icon_h), 3, 3)
        painter.setBrush(QBrush(QColor(255, 255, 255)))
        painter.drawEllipse(int(x + icon_w * 0.33), int(y + icon_h * 0.20), int(icon_w * 0.34), int(icon_w * 0.34))

    # ------------------------------------------------------------------ 交互
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._offset = self._press_global - self.frameGeometry().topLeft()
            self._dragged = False

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._press_global is None:
            return
        pos = event.globalPosition().toPoint()
        if not self._dragged and (pos - self._press_global).manhattanLength() > DRAG_THRESHOLD:
            self._dragged = True
        if self._dragged:
            self.move(pos - self._offset)
            self._clamp_to_screen()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._press_global is not None:
            moved = (event.globalPosition().toPoint() - self._press_global).manhattanLength()
            dragged = self._dragged
            busy = self._busy
            self._press_global = None
            # 只要拖动过程中曾经越过阈值，就不算点击（防止「拖完回到原点」误触发截图）
            if moved <= DRAG_THRESHOLD and not dragged and not busy:
                bootstrap.log(f"鼠标释放 → 判定为点击（位移 {moved}px）")
                self.clicked.emit()
            elif dragged:
                bootstrap.log(f"鼠标释放 → 判定为拖动（位移 {moved}px），保存位置")
                self._save_position()
            else:
                bootstrap.log(f"鼠标释放 → 忽略（位移 {moved}px 拖动={dragged} 忙={busy}）")

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
        self.move(area.right() - self.width() - 30, area.top() + 60)

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

    def apply_config(self, config: ClientConfig) -> None:
        self._config = config
        size = max(28, int(config.ball_size))
        self.setFixedSize(size, size)
        self.setWindowOpacity(float(config.ball_opacity))
        self.update()
