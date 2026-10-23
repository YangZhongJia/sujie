"""贴图钉屏：把一块截图钉在桌面最上层，可拖动、缩放、随手关掉。

和「截图发送」互补：贴图只留在本机，用来对照抄写、比对两处界面。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QGuiApplication, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QWidget

from . import APP_NAME, bootstrap, paths, win32util

MIN_ZOOM = 0.10
MAX_ZOOM = 4.00
ZOOM_STEP = 1.12
BORDER = 2


class PinWindow(QWidget):
    """一张钉在屏幕上的图。"""

    closedByUser = Signal(object)

    def __init__(self, pixmap: QPixmap, position: Optional[QPoint] = None, parent=None):
        super().__init__(parent)
        self._original = QPixmap(pixmap)
        self._zoom = 1.0
        self._drag_origin: Optional[QPoint] = None
        self._hovered = False
        self._moved = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setMouseTracking(True)
        self.setToolTip("拖动移动 · 滚轮缩放 · 双击关闭 · 右键菜单")

        self._apply_zoom(1.0)
        if position is not None:
            self.move(position)
        self._clamp_to_screen()

        shortcut = QShortcut(QKeySequence("Escape"), self)
        shortcut.setContext(Qt.ApplicationShortcut)
        shortcut.activated.connect(self.close)

    # ------------------------------------------------------------- 基本属性
    def zoom(self) -> float:
        return self._zoom

    def image_size(self) -> tuple:
        return self._original.width(), self._original.height()

    def set_zoom(self, zoom: float) -> None:
        self._apply_zoom(zoom)

    # ---------------------------------------------------------------- 缩放
    def _apply_zoom(self, zoom: float) -> None:
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, float(zoom)))
        width = max(24, int(round(self._original.width() * zoom)))
        height = max(24, int(round(self._original.height() * zoom)))
        center = self.geometry().center() if self.isVisible() else None
        self._zoom = zoom
        self.setFixedSize(width + BORDER * 2, height + BORDER * 2)
        self._scaled = self._original.scaled(
            width, height, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        if center is not None:
            self.move(center.x() - self.width() // 2, center.y() - self.height() // 2)
            self._clamp_to_screen()
        self.update()

    def wheelEvent(self, event):  # noqa: N802
        delta = event.angleDelta().y()
        if not delta:
            return
        factor = ZOOM_STEP if delta > 0 else 1.0 / ZOOM_STEP
        self._apply_zoom(self._zoom * factor)

    # ---------------------------------------------------------------- 交互
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._moved = False

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_origin is not None:
            self._moved = True
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            self._clamp_to_screen()

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_origin = None

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.close()

    def enterEvent(self, event):  # noqa: N802
        self._hovered = True
        self.update()

    def leaveEvent(self, event):  # noqa: N802
        self._hovered = False
        self.update()

    def contextMenuEvent(self, event):  # noqa: N802
        menu = QMenu(self)
        copy_action = QAction("复制图片", menu)
        copy_action.triggered.connect(self.copy_to_clipboard)
        menu.addAction(copy_action)
        save_action = QAction("另存为…", menu)
        save_action.triggered.connect(self.save_as)
        menu.addAction(save_action)
        menu.addSeparator()
        close_action = QAction("关闭", menu)
        close_action.triggered.connect(self.close)
        menu.addAction(close_action)
        menu.exec(event.globalPos())

    def copy_to_clipboard(self) -> None:
        QGuiApplication.clipboard().setPixmap(self._original)

    def save_as(self) -> None:
        default = str(paths.local_data_dir() / "pins" / f"pin-{datetime.now():%Y%m%d-%H%M%S}.png")
        os.makedirs(os.path.dirname(default), exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(self, "另存贴图", default, "PNG 图片 (*.png)")
        if not path:
            return
        self._original.save(path, "PNG")
        bootstrap.log(f"贴图另存为 {path}")

    def closeEvent(self, event):  # noqa: N802
        self.closedByUser.emit(self)
        super().closeEvent(event)

    # ---------------------------------------------------------------- 绘制
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor(18, 20, 24, 210))
        painter.drawPixmap(BORDER, BORDER, self._scaled)
        color = QColor(233, 79, 55, 235) if self._hovered else QColor(255, 255, 255, 90)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(color, BORDER))
        painter.drawRect(QRectF(BORDER / 2, BORDER / 2, self.width() - BORDER, self.height() - BORDER))

    # ---------------------------------------------------------------- 位置
    def _clamp_to_screen(self) -> None:
        screens = QApplication.screens()
        if not screens:
            return
        center = self.geometry().center()
        screen = QApplication.screenAt(center) or QApplication.primaryScreen() or screens[0]
        area = screen.availableGeometry()
        pos = self.pos()
        x = min(max(pos.x(), area.left()), max(area.left(), area.right() - self.width() + 1))
        y = min(max(pos.y(), area.top()), max(area.top(), area.bottom() - self.height() + 1))
        if (x, y) != (pos.x(), pos.y()):
            self.move(x, y)


class PinManager:
    """管理所有钉图（持有引用，避免被 GC）。"""

    def __init__(self, max_count: int = 8):
        self._pins: List[PinWindow] = []
        self.max_count = max(1, int(max_count or 8))
        self._hidden_for_capture = False

    def count(self) -> int:
        return len(self._pins)

    def pins(self) -> List[PinWindow]:
        return list(self._pins)

    def create(self, pixmap: QPixmap, position: Optional[QPoint] = None) -> PinWindow:
        while len(self._pins) >= self.max_count:
            oldest = self._pins.pop(0)
            try:
                oldest.closedByUser.disconnect()
            except (RuntimeError, TypeError):
                pass
            oldest.close()
        window = PinWindow(pixmap, position)
        window.closedByUser.connect(self._on_closed)
        self._pins.append(window)
        window.show()
        window.raise_()
        bootstrap.log(f"新增钉图 {window.image_size()}，当前共 {len(self._pins)} 张")
        return window

    def _on_closed(self, window) -> None:
        if window in self._pins:
            self._pins.remove(window)

    def hide_all(self) -> None:
        if not self._pins:
            return
        self._hidden_for_capture = True
        for window in self._pins:
            window.hide()

    def show_all(self) -> None:
        if not self._hidden_for_capture:
            return
        self._hidden_for_capture = False
        for window in self._pins:
            window.show()
            window.raise_()

    def close_all(self) -> None:
        for window in list(self._pins):
            window.close()
        self._pins.clear()

    @property
    def hidden_for_capture(self) -> bool:
        return self._hidden_for_capture
