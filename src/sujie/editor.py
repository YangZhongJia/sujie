"""Post-capture annotation editor using PySide6 only."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPolygonF,
    QShortcut,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import paths

TOOLS = (("pen", "画笔"), ("arrow", "箭头"), ("rect", "矩形"),
         ("ellipse", "圆形"), ("text", "文字"), ("mosaic", "马赛克"))

# QDialog.Accepted/Rejected 之外的自定义结果码，client 侧据此区分「不发送」的收尾
RESULT_COPY = 2
RESULT_SAVE = 3


class _Canvas(QWidget):
    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.source = image.convertToFormat(QImage.Format_ARGB32)
        self.tool = "pen"
        self.actions: list[dict] = []
        self.cursor = 0
        self._rendered: QImage | None = None
        self._start: QPointF | None = None
        self._current: QPointF | None = None
        self._points: list[QPointF] = []
        self.setMinimumSize(600, 360)
        self.setMouseTracking(True)

    @property
    def image(self) -> QImage:
        return self._render().copy()

    def _render(self) -> QImage:
        if self._rendered is not None:
            return self._rendered
        image = self.source.copy()
        for action in self.actions[:self.cursor]:
            if action["kind"] == "mosaic":
                rect = action["rect"].intersected(image.rect())
                if rect.width() < 5 or rect.height() < 5:
                    continue
                crop = image.copy(rect)
                small = crop.scaled(max(1, rect.width() // 14), max(1, rect.height() // 14),
                                    Qt.IgnoreAspectRatio, Qt.FastTransformation)
                painter = QPainter(image)
                painter.drawImage(rect.topLeft(), small.scaled(rect.size(), Qt.IgnoreAspectRatio,
                                                               Qt.FastTransformation))
                painter.end()
                continue
            painter = QPainter(image)
            painter.setPen(QPen(QColor("#ff3b30"), max(4, image.width() // 900),
                                Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            if action["kind"] == "pen":
                painter.drawPolyline(QPolygonF(action["points"]))
            elif action["kind"] == "text":
                font = QFont()
                font.setFamilies(["Microsoft YaHei UI", "Segoe UI"])
                font.setPixelSize(max(18, image.width() // 80))
                font.setBold(True)
                painter.setFont(font)
                painter.drawText(action["point"], action["text"])
            else:
                self._draw_shape(painter, action["kind"], action["start"], action["end"])
            painter.end()
        self._rendered = image
        return image

    def _layout(self) -> tuple[QRectF, float]:
        scale = min(self.width() / self.source.width(), self.height() / self.source.height())
        width, height = self.source.width() * scale, self.source.height() * scale
        return QRectF((self.width() - width) / 2, (self.height() - height) / 2, width, height), scale

    def _image_point(self, point: QPointF) -> QPointF:
        rect, scale = self._layout()
        return QPointF(
            min(max((point.x() - rect.x()) / scale, 0), self.source.width() - 1),
            min(max((point.y() - rect.y()) / scale, 0), self.source.height() - 1),
        )

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#e5e5ea"))
        rect, scale = self._layout()
        painter.drawImage(rect, self._render())
        painter.setPen(QPen(QColor("#d2d2d7"), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        if self._start is None:
            return
        painter.save()
        painter.translate(rect.x(), rect.y())
        painter.scale(scale, scale)
        painter.setPen(QPen(QColor("#ff3b30"), max(2.0, 4.0 / scale), Qt.SolidLine,
                            Qt.RoundCap, Qt.RoundJoin))
        if self.tool == "pen" and len(self._points) > 1:
            painter.drawPolyline(QPolygonF(self._points))
        elif self._current is not None and self.tool in ("arrow", "rect", "ellipse"):
            self._draw_shape(painter, self.tool, self._image_point(self._start),
                             self._image_point(self._current))
        elif self._current is not None and self.tool == "mosaic":
            painter.fillRect(QRectF(self._image_point(self._start), self._image_point(self._current)).normalized(),
                             QColor(255, 255, 255, 65))
        painter.restore()

    @staticmethod
    def _draw_shape(painter: QPainter, kind: str, start: QPointF, end: QPointF) -> None:
        rect = QRectF(start, end).normalized()
        if kind == "rect":
            painter.drawRect(rect)
        elif kind == "ellipse":
            painter.drawEllipse(rect)
        elif kind == "arrow":
            painter.drawLine(start, end)
            dx, dy = end.x() - start.x(), end.y() - start.y()
            length = max(1.0, (dx * dx + dy * dy) ** 0.5)
            ux, uy = dx / length, dy / length
            size = max(12.0, abs(dx) * 0.04)
            base = QPointF(end.x() - ux * size, end.y() - uy * size)
            side = QPointF(-uy * size * 0.45, ux * size * 0.45)
            painter.drawLine(end, base + side)
            painter.drawLine(end, base - side)

    def _add_action(self, action: dict) -> None:
        del self.actions[self.cursor:]
        self.actions.append(action)
        self.cursor += 1
        self._rendered = None
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        self._start = self._current = event.position()
        point = self._image_point(self._start)
        self._points = [point]
        if self.tool == "text":
            text, ok = QInputDialog.getText(self, "添加文字", "输入标注文字：")
            if ok and text:
                self._add_action({"kind": "text", "point": point, "text": text})
            self._start = self._current = None
            self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._start is None:
            return
        self._current = event.position()
        if self.tool == "pen":
            self._points.append(self._image_point(self._current))
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton or self._start is None:
            return
        start, end = self._image_point(self._start), self._image_point(event.position())
        distance = abs(end.x() - start.x()) + abs(end.y() - start.y())
        if self.tool == "pen" and len(self._points) > 1:
            self._add_action({"kind": "pen", "points": list(self._points)})
        elif self.tool == "mosaic" and distance > 5:
            self._add_action({"kind": "mosaic", "rect": QRectF(start, end).normalized().toAlignedRect()})
        elif self.tool in ("arrow", "rect", "ellipse") and distance > 3:
            self._add_action({"kind": self.tool, "start": start, "end": end})
        self._start = self._current = None
        self._points = []
        self.update()

    def undo(self) -> None:
        if self.cursor:
            self.cursor -= 1
            self._rendered = None
            self.update()

    def redo(self) -> None:
        if self.cursor < len(self.actions):
            self.cursor += 1
            self._rendered = None
            self.update()


class ScreenshotEditor(QDialog):
    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑截图")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setWindowModality(Qt.ApplicationModal)
        self.resize(1000, 720)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(12)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(6)
        self.canvas = _Canvas(image, self)
        self._tool_buttons: dict[str, QPushButton] = {}
        for tool, label in TOOLS:
            button = QPushButton(label)
            button.setProperty("tool", True)
            button.setCheckable(True)
            button.setChecked(tool == "pen")
            button.clicked.connect(lambda checked=False, t=tool: self._select_tool(t))
            toolbar.addWidget(button)
            self._tool_buttons[tool] = button
        undo = QPushButton("撤销")
        undo.setToolTip("撤销上一步")
        undo.clicked.connect(self.canvas.undo)
        redo = QPushButton("重做")
        redo.setToolTip("恢复上一步")
        redo.clicked.connect(self.canvas.redo)
        divider = QFrame()
        divider.setFrameShape(QFrame.VLine)
        divider.setFrameShadow(QFrame.Plain)
        toolbar.addWidget(undo)
        toolbar.addWidget(redo)
        toolbar.addWidget(divider)
        size_label = QLabel(f"{image.width()} × {image.height()}")
        size_label.setProperty("role", "subtitle")
        toolbar.addWidget(size_label)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)
        layout.addWidget(self.canvas, 1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        copy = QPushButton("复制")
        copy.setToolTip("复制到剪贴板并关闭（Ctrl+C）")
        copy.clicked.connect(self._copy_and_close)
        save = QPushButton("保存")
        save.setToolTip("保存到本机并关闭（Ctrl+S）")
        save.clicked.connect(self._save_and_close)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        send = QPushButton("发送")
        send.setProperty("primary", True)
        send.setDefault(True)
        send.setAutoDefault(True)
        send.clicked.connect(self.accept)
        footer.addWidget(copy)
        footer.addWidget(save)
        footer.addWidget(cancel)
        footer.addWidget(send)
        layout.addLayout(footer)
        send_shortcut = QShortcut(QKeySequence("Ctrl+Enter"), self)
        send_shortcut.activated.connect(self.accept)
        copy_shortcut = QShortcut(QKeySequence(QKeySequence.Copy), self)
        copy_shortcut.activated.connect(self._copy_and_close)
        save_shortcut = QShortcut(QKeySequence(QKeySequence.Save), self)
        save_shortcut.activated.connect(self._save_and_close)

    @property
    def image(self) -> QImage:
        return self.canvas.image

    def _copy_and_close(self) -> None:
        QGuiApplication.clipboard().setImage(self.image)
        self.done(RESULT_COPY)

    def _save_and_close(self) -> None:
        directory = paths.local_data_dir() / "saved"
        directory.mkdir(parents=True, exist_ok=True)
        default = str(directory / f"shot-{datetime.now():%Y%m%d-%H%M%S}.png")
        path, _ = QFileDialog.getSaveFileName(self, "保存截图", default, "PNG 图片 (*.png)")
        if not path:
            return
        if not self.image.save(path, "PNG"):
            QMessageBox.warning(self, "保存失败", f"无法写入文件：{path}")
            return
        self.done(RESULT_SAVE)

    def _select_tool(self, tool: str) -> None:
        self.canvas.tool = tool
        for key, button in self._tool_buttons.items():
            button.setChecked(key == tool)
