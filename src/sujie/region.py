"""区域框选：在鼠标所在显示器上叠加半透明遮罩，拖拽选择矩形。

实现要点：
- 遮罩窗只覆盖「鼠标所在的那一块显示器」，避免跨屏混合 DPI 下图像与选框错位。
- 内部一律使用 Qt 逻辑坐标；对外输出时换算回虚拟桌面物理像素。
"""

from __future__ import annotations

from typing import Optional, Tuple

from PIL import Image
from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from . import capture, win32util

Rect = Tuple[int, int, int, int]


class RegionSelector(QWidget):
    """半透明遮罩 + 拖拽框选。"""

    selected = Signal(object)  # (left, top, right, bottom) 物理像素
    cancelled = Signal()

    def __init__(self, screen_image: Image.Image, monitor: win32util.Monitor, parent=None):
        super().__init__(parent)
        self._monitor = monitor
        self._origin = None
        self._current = QRect()
        self._has_selection = False

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Window
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)

        # 把物理像素图像转成 Qt 图像，并按显示器 DPI 设置 devicePixelRatio
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self._dpr = screen.devicePixelRatio() if screen else 1.0

        qimage = QImage.fromData(_pil_to_png_bytes(screen_image), "PNG")
        self._pixmap = QPixmap.fromImage(qimage)
        self._pixmap.setDevicePixelRatio(self._dpr)

        target = screen.geometry() if screen else QRect(0, 0, monitor.width, monitor.height)
        self.setGeometry(target)
        # 遮罩窗口在 Qt 全局「逻辑」坐标系中的左上角，用于换算回物理像素
        self._origin_logical = (self.x(), self.y())

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        painter.drawPixmap(self.rect(), self._pixmap)

        dim = QColor(0, 0, 0, 120)
        painter.fillRect(self.rect(), dim)

        if self._current.isValid() and self._current.width() > 1 and self._current.height() > 1:
            # 选区恢复明亮
            painter.setClipRect(self._current)
            painter.drawPixmap(self.rect(), self._pixmap)
            painter.setClipping(False)

            pen = QPen(QColor("#ff4d3d"), 2)
            painter.setPen(pen)
            painter.drawRect(self._current)

            painter.setPen(QPen(QColor("#ffffff"), 1))
            for x in (self._current.left(), self._current.right()):
                painter.drawLine(x, self._current.top(), x, self._current.bottom())
            for y in (self._current.top(), self._current.bottom()):
                painter.drawLine(self._current.left(), y, self._current.right(), y)

            painter.setPen(QPen(QColor("#ffffff")))
            font = QFont()
            font.setPointSize(10)
            painter.setFont(font)
            painter.drawText(
                self._current.adjusted(4, 4, -4, -20),
                int(Qt.AlignLeft | Qt.AlignTop),
                f"{self._current.width()} × {self._current.height()}",
            )

        hint = QColor(255, 255, 255, 230)
        painter.setPen(QPen(hint))
        font = QFont()
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(
            self.rect().adjusted(16, 16, -16, -16),
            int(Qt.AlignTop | Qt.AlignLeft),
            "拖动鼠标框选区域　·　松开鼠标确认　·　按 Esc 取消",
        )

    # ------------------------------------------------------------------ 交互
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self._current = QRect(self._origin, self._origin)
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._origin is not None:
            pos = event.globalPosition().toPoint()
            self._current = QRect(self._origin, pos).normalized()
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self._origin is not None:
            rect = self._current
            if rect.width() >= 4 and rect.height() >= 4:
                self._has_selection = True
                self.selected.emit(self._to_physical(rect))
            else:
                self.cancelled.emit()
            self.close()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter):
            rect = self._current
            if rect.width() >= 4 and rect.height() >= 4:
                self._has_selection = True
                self.selected.emit(self._to_physical(rect))
                self.close()
            else:
                self.cancelled.emit()
                self.close()

    # -------------------------------------------------------------- 坐标换算
    def _to_physical(self, rect: QRect) -> Rect:
        """Qt 全局逻辑坐标 → 虚拟桌面物理像素。"""
        dpr = self._dpr or 1.0
        ox, oy = self._origin_logical
        left = self._monitor.left + int(round((rect.left() - ox) * dpr))
        top = self._monitor.top + int(round((rect.top() - oy) * dpr))
        right = self._monitor.left + int(round((rect.right() - ox) * dpr))
        bottom = self._monitor.top + int(round((rect.bottom() - oy) * dpr))
        return (left, top, right, bottom)


def _pil_to_png_bytes(image: Image.Image) -> bytes:
    import io

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def select_region() -> Optional[Rect]:
    """弹出框选界面并返回选区（物理像素矩形）；用户取消返回 None。"""
    import ctypes

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT()
    win32util.user32.GetCursorPos(ctypes.byref(pt))
    monitor = win32util.monitor_containing_point(pt.x, pt.y)
    if monitor is None:
        monitors = win32util.enumerate_monitors()
        monitor = monitors[0] if monitors else win32util.Monitor(0, 0, 1920, 1080, True)

    image, origin = capture.grab_virtual()
    crop = capture.crop_virtual(image, origin, (monitor.left, monitor.top, monitor.right, monitor.bottom))

    result: dict = {}

    selector = RegionSelector(crop, monitor)
    selector.selected.connect(lambda rect: result.setdefault("rect", rect))
    selector.show()  # 不用 showFullScreen：那会强制铺满主屏，而非鼠标所在屏
    selector.raise_()

    from PySide6.QtWidgets import QApplication

    # 模态等待选择完成
    while selector.isVisible():
        QApplication.processEvents()
        QApplication.instance().thread().msleep(10)

    return result.get("rect")
