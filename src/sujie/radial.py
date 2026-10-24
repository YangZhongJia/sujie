"""长按悬浮球弹出的四向扇形菜单（径向菜单 / pie menu）。

设计要点
--------
* 只负责**显示**：窗口带 ``WA_TransparentForMouseEvents``，鼠标事件永远留在
  :class:`~sujie.balloon.FloatingBall` 上（它天然持有鼠标抓取），小球把指针位置
  转发给本类用于高亮。这样不需要跨窗口追踪，也不会抢焦点。
* 方向判定用「主导轴」：``|dy| >= |dx|`` 走上下，否则走左右。四个 90° 扇区，没有
  斜角选不到的缝。
* 半径会按小球到屏幕四边的最近距离收缩（最小 :data:`MIN_RADIUS`），保证球停在
  角落时扇区仍然完整可见。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import QPoint, QPointF, QRectF, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QWidget

# ---------------------------------------------------------------- 尺寸/阈值常量
DEFAULT_RADIUS = 132
MIN_RADIUS = 60            # 靠近屏幕边缘时允许缩到这么小，避免扇形被窗口裁掉
MAX_RADIUS = 190
INNER_RADIUS = 46          # 扇区内缘基准（实际按半径比例算，见 paintEvent）
WINDOW_MARGIN = 8
LABEL_MIN_RADIUS = 84      # 半径小于这个值时只留图标，不画文字

DEAD_ZONE = 26             # 小于这个距离 = 中心死区（松手即取消）
HIGHLIGHT_MIN = 44         # 新选中一个扇区需要达到的距离
HYSTERESIS = 36            # 已高亮后回退到该距离以下才取消（防抖）

GAP_DEGREES = 6.0
SECTOR_ANGLES: Dict[str, tuple] = {
    # Qt 角度制：0° 在 3 点钟方向，逆时针为正
    "up": (45.0, 135.0),
    "left": (135.0, 225.0),
    "down": (225.0, 315.0),
    "right": (315.0, 405.0),
}
SECTOR_ORDER = ("up", "left", "down", "right")


@dataclass(frozen=True)
class Sector:
    """一个扇区的定义。想加新功能只需要在 :data:`SECTORS` 里加一行。"""

    key: str
    label: str
    icon: str
    action: Optional[str]
    enabled: bool = True


SECTORS: Dict[str, Sector] = {
    "up": Sector("up", "截图", "camera", "screenshot"),
    "left": Sector("left", "录屏", "record", "record"),
    "right": Sector("right", "贴图", "pin", "pin"),
    "down": Sector("down", "记录", "history", "history"),
}


def sector_at(dx: int, dy: int) -> Optional[str]:
    """把相对位移映射到扇区；中心死区返回 None。"""
    distance = math.hypot(dx, dy)
    if distance < DEAD_ZONE:
        return None
    if abs(dy) >= abs(dx):          # 竖轴优先（45° 交界归上下，规则写死）
        return "up" if dy < 0 else "down"
    return "left" if dx < 0 else "right"


def _polar(cx: float, cy: float, radius: float, degrees: float) -> QPointF:
    radians = math.radians(degrees)
    return QPointF(cx + radius * math.cos(radians), cy - radius * math.sin(radians))


class RadialMenu(QWidget):
    """四个扇形的浮层。纯展示，不接收鼠标事件。"""

    closed = Signal()

    def __init__(self, accent: str = "#e94f37", parent=None):
        super().__init__(parent)
        self._accent = QColor(accent)
        self._current: Optional[str] = None
        self._open = False
        self._radius = DEFAULT_RADIUS
        self._center_global = QPoint(0, 0)
        self._center_local = QPointF(0.0, 0.0)
        self.show_reserved = True
        self._animation: Optional[QPropertyAnimation] = None

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    # ------------------------------------------------------------- 对外接口
    def is_open(self) -> bool:
        return self._open

    def set_accent(self, color: str) -> None:
        """跟随设置里的悬浮球配色。"""
        self._accent = QColor(color)
        self.update()

    def current_sector(self) -> Optional[str]:
        return self._current

    def radius(self) -> int:
        return self._radius

    def open_at(self, center_global: QPoint, radius: Optional[int] = None) -> None:
        """在小球中心弹出菜单。重复调用只更新位置，不会叠窗口。"""
        self._center_global = QPoint(center_global)
        self._radius = self._resolve_radius(QPoint(center_global), radius)
        width = 2 * self._radius + 2 * WINDOW_MARGIN
        x = self._center_global.x() - width // 2
        y = self._center_global.y() - width // 2

        screen = QApplication.screenAt(self._center_global) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = min(max(x, area.left()), max(area.left(), area.right() - width + 1))
            y = min(max(y, area.top()), max(area.top(), area.bottom() - width + 1))

        self._center_local = QPointF(
            self._center_global.x() - x, self._center_global.y() - y
        )
        self.setGeometry(x, y, width, width)
        self._current = None
        self._open = True
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._fade(1.0, 110)
        self.update()

    def update_cursor(self, global_pos: QPoint) -> None:
        """按指针位置更新高亮扇区（由小球在拖动过程中转发）。"""
        if not self._open:
            return
        dx = global_pos.x() - self._center_global.x()
        dy = global_pos.y() - self._center_global.y()
        distance = math.hypot(dx, dy)
        candidate = sector_at(dx, dy)

        if candidate is None:
            selected = None
        elif candidate == self._current and distance >= HYSTERESIS:
            selected = candidate               # 已高亮，允许小幅回退
        elif distance >= HIGHLIGHT_MIN:
            selected = candidate
        else:
            selected = None

        if selected != self._current:
            self._current = selected
            self.update()

    def commit(self) -> Optional[str]:
        """松手时调用：返回选中的扇区 key（可能是预留槽），未选中返回 None。"""
        selected = self._current
        self.close_menu()
        return selected

    def close_menu(self) -> None:
        if not self._open:
            return
        self._open = False
        self._current = None
        self._fade(0.0, 80, hide=True)
        self.closed.emit()

    # ------------------------------------------------------------- 内部实现
    def _fade(self, target: float, duration: int, hide: bool = False) -> None:
        if self._animation is not None:
            self._animation.stop()
        animation = QPropertyAnimation(self, b"windowOpacity", self)
        animation.setStartValue(float(self.windowOpacity()))
        animation.setEndValue(float(target))
        animation.setDuration(duration)
        if hide:
            animation.finished.connect(self._hide_now)
        else:
            animation.finished.connect(self._clear_animation)
        self._animation = animation
        animation.start()

    def _clear_animation(self) -> None:
        self._animation = None

    def _hide_now(self) -> None:
        self._animation = None
        if not self._open:
            self.hide()

    def _resolve_radius(self, center: QPoint, radius: Optional[int]) -> int:
        desired = int(radius or DEFAULT_RADIUS)
        desired = max(MIN_RADIUS, min(MAX_RADIUS, desired))
        screen = QApplication.screenAt(center) or QApplication.primaryScreen()
        if screen is None:
            return desired
        area = screen.availableGeometry()
        room = min(
            center.x() - area.left(),
            area.right() - center.x(),
            center.y() - area.top(),
            area.bottom() - center.y(),
        )
        limit = room - WINDOW_MARGIN
        if limit < MIN_RADIUS:
            # 球贴在屏幕边缘：宁可把扇形缩小，也不能让窗口把扇区裁掉一半
            return int(max(44, limit))
        return int(max(MIN_RADIUS, min(desired, limit)))

    def _annular_path(self, radius_out: float, radius_in: float,
                      start: float, end: float) -> QPainterPath:
        cx, cy = self._center_local.x(), self._center_local.y()
        path = QPainterPath()
        path.moveTo(_polar(cx, cy, radius_out, start))
        path.arcTo(QRectF(cx - radius_out, cy - radius_out, radius_out * 2, radius_out * 2), start, end - start)
        path.lineTo(_polar(cx, cy, radius_in, end))
        path.arcTo(QRectF(cx - radius_in, cy - radius_in, radius_in * 2, radius_in * 2), end, start - end)
        path.closeSubpath()
        return path

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        cx, cy = self._center_local.x(), self._center_local.y()
        radius = float(self._radius)
        inner = max(22.0, radius * 0.34)
        show_labels = self._radius >= LABEL_MIN_RADIUS

        for key in SECTOR_ORDER:
            sector = SECTORS[key]
            active = key == self._current
            start, end = SECTOR_ANGLES[key]
            start += GAP_DEGREES / 2.0
            end -= GAP_DEGREES / 2.0

            if not sector.enabled:
                if not self.show_reserved:
                    continue
                pen = QPen(QColor(110, 110, 115, 75), 1.3, Qt.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawPath(self._annular_path(radius, inner, start, end))
            else:
                fill = QColor(self._accent)
                fill.setAlpha(226 if active else 0)
                if active:
                    painter.setBrush(QBrush(fill))
                    painter.setPen(QPen(QColor(255, 255, 255, 220), 1.3))
                else:
                    painter.setBrush(QBrush(QColor(255, 255, 255, 238)))
                    painter.setPen(QPen(QColor(210, 210, 215, 210), 1.2))
                painter.drawPath(self._annular_path(radius, inner, start, end))

            middle = (start + end) / 2.0
            radians = math.radians(middle)
            span = radius - inner
            icon_radius = inner + span * 0.42
            label_radius = inner + span * 0.84
            icon_size = max(15.0, radius * 0.13)
            icon_center = QPointF(
                cx + math.cos(radians) * icon_radius,
                cy - math.sin(radians) * icon_radius,
            )

            if sector.enabled:
                color = QColor(255, 255, 255, 255) if active else QColor(29, 29, 31, 220)
            else:
                color = QColor(110, 110, 115, 130)
            self._draw_icon(painter, sector.icon, icon_center, icon_size, color)

            if show_labels:
                painter.setPen(QPen(color))
                font = QFont(self.font())
                font.setPixelSize(max(10, int(radius * 0.095)))
                font.setBold(active)
                painter.setFont(font)
                text = sector.label if sector.enabled else "预留"
                if not sector.enabled and not self.show_reserved:
                    continue
                painter.drawText(
                    QRectF(
                        cx + math.cos(radians) * label_radius - 34,
                        cy - math.sin(radians) * label_radius - 12,
                        68,
                        24,
                    ),
                    int(Qt.AlignCenter),
                    text,
                )

        # 中心提示：当前选中的动作名
        ring = max(14.0, inner - 8)
        painter.setBrush(QBrush(QColor(255, 255, 255, 248)))
        painter.setPen(QPen(QColor(210, 210, 215, 230), 1.0))
        painter.drawEllipse(QPointF(cx, cy), ring, ring)
        if self._current is not None and show_labels:
            sector = SECTORS[self._current]
            color = QColor(29, 29, 31) if sector.enabled else QColor(110, 110, 115)
            painter.setPen(QPen(color))
            font = QFont(self.font())
            font.setPixelSize(max(10, int(radius * 0.085)))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                QRectF(cx - ring, cy - ring, ring * 2, ring * 2),
                int(Qt.AlignCenter),
                sector.label if sector.enabled else "预留",
            )

    @staticmethod
    def _draw_icon(painter: QPainter, kind: str, center: QPointF,
                   size: float, color: QColor) -> None:
        cx, cy = center.x(), center.y()
        half = size / 2.0
        painter.save()
        pen = QPen(color, max(1.4, size * 0.11))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

        if kind == "camera":
            width, height = size * 0.88, size * 0.62
            top = cy - height / 2 + size * 0.07
            rect = QRectF(cx - width / 2, top, width, height)
            painter.drawRoundedRect(rect, size * 0.13, size * 0.13)
            painter.drawEllipse(QPointF(cx, top + height * 0.55), size * 0.15, size * 0.15)
            painter.drawLine(
                QPointF(cx - width * 0.24, top),
                QPointF(cx - width * 0.10, top - size * 0.12),
            )
        elif kind == "record":
            painter.drawEllipse(QPointF(cx, cy), half * 0.88, half * 0.88)
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(QPointF(cx, cy), half * 0.42, half * 0.42)
        elif kind == "pin":
            painter.drawEllipse(QPointF(cx, cy - half * 0.30), half * 0.44, half * 0.44)
            painter.drawLine(QPointF(cx - half * 0.20, cy + half * 0.06),
                             QPointF(cx - half * 0.34, cy + half * 0.60))
            painter.drawLine(QPointF(cx + half * 0.20, cy + half * 0.06),
                             QPointF(cx + half * 0.34, cy + half * 0.60))
            painter.drawLine(QPointF(cx - half * 0.38, cy + half * 0.62),
                             QPointF(cx + half * 0.38, cy + half * 0.62))
        elif kind == "history":
            for offset in (-half * 0.46, 0.0, half * 0.46):
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(cx - half * 0.60, cy + offset), half * 0.10, half * 0.10)
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawLine(QPointF(cx - half * 0.28, cy + offset),
                                 QPointF(cx + half * 0.62, cy + offset))
        painter.restore()

    # 便于测试：返回所有可点扇区
    @staticmethod
    def enabled_sectors() -> List[str]:
        return [key for key in SECTOR_ORDER if SECTORS[key].enabled]
