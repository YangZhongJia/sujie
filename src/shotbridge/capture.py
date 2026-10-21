"""截图实现。

统一策略：先抓取整个虚拟桌面（多显示器拼接），再按物理像素矩形裁剪。
这样所有截图来源（窗口 / 显示器 / 区域）共用一套坐标换算，
不会出现 mss / ImageGrab / Win32 三套坐标系互相对不上的经典问题。

坐标约定：全部使用 **虚拟桌面物理像素**，原点在虚拟桌面左上角，
虚拟桌面原点可能为负（副屏在主屏左侧时）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from PIL import Image, ImageGrab

from . import win32util

Rect = Tuple[int, int, int, int]


@dataclass
class CaptureResult:
    image: Image.Image
    rect: Rect          # 截图对应的虚拟桌面物理像素矩形
    title: str = ""     # 截图来源窗口标题（仅窗口模式）


def _virtual_origin() -> tuple[int, int]:
    left, top, _, _ = win32util.virtual_screen_rect()
    return left, top


def grab_virtual() -> Tuple[Image.Image, tuple[int, int]]:
    """抓取整个虚拟桌面，返回 (图像, 图像左上角对应的虚拟桌面坐标)。"""
    image = ImageGrab.grab(all_screens=True)
    return image.convert("RGB"), _virtual_origin()


def crop_virtual(image: Image.Image, origin: tuple[int, int], rect: Rect) -> Image.Image:
    """把虚拟桌面坐标系下的矩形裁剪出来。"""
    ox, oy = origin
    left, top, right, bottom = rect
    box = (left - ox, top - oy, right - ox, bottom - oy)
    width, height = image.size
    box = (
        max(0, min(box[0], width)),
        max(0, min(box[1], height)),
        max(0, min(box[2], width)),
        max(0, min(box[3], height)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError(f"无效截图区域: {rect}")
    return image.crop(box)


def capture_rect(rect: Rect) -> CaptureResult:
    """按虚拟桌面物理像素矩形截图。"""
    image, origin = grab_virtual()
    return CaptureResult(image=crop_virtual(image, origin, rect), rect=rect)


def capture_screen() -> CaptureResult:
    """整个虚拟桌面（所有显示器）截图。"""
    rect = win32util.virtual_screen_rect()
    return capture_rect(rect)


def capture_primary_monitor() -> CaptureResult:
    """主显示器截图。"""
    monitors = win32util.enumerate_monitors()
    primary = next((m for m in monitors if m.primary), monitors[0])
    return capture_rect((primary.left, primary.top, primary.right, primary.bottom))


def capture_monitor_under_cursor() -> CaptureResult:
    """鼠标所在显示器截图。"""
    from PIL import ImageGrab as _IG

    # ImageGrab 不暴露鼠标位置，这里用 win32
    import ctypes

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT()
    win32util.user32.GetCursorPos(ctypes.byref(pt))
    monitor = win32util.monitor_containing_point(pt.x, pt.y)
    if monitor is None:
        return capture_primary_monitor()
    return capture_rect((monitor.left, monitor.top, monitor.right, monitor.bottom))


def capture_foreground_window() -> CaptureResult:
    """当前活动窗口截图。

    注意：窗口必须在前台（未被遮挡），否则截到的是遮挡它的内容。
    需要遮挡可见时可用 Win32 的 PrintWindow/WGC 方案，复杂度更高。
    """
    rect = win32util.foreground_window_rect()
    if rect is None:
        raise RuntimeError("无法获取前台窗口")
    left, top, right, bottom = rect
    if right - left < 2 or bottom - top < 2:
        raise RuntimeError("前台窗口尺寸异常")
    title = win32util.window_title(win32util.foreground_window())
    result = capture_rect(rect)
    result.title = title
    return result


def capture_window_at_cursor() -> CaptureResult:
    """鼠标悬停位置的窗口截图（可取到窗口标题栏外的整个窗口）。"""
    import ctypes

    if not win32util.IS_WINDOWS:
        return capture_foreground_window()

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT()
    win32util.user32.GetCursorPos(ctypes.byref(pt))
    hwnd = win32util.user32.WindowFromPoint(pt)
    if not hwnd:
        return capture_foreground_window()
    # 逐级向上取根窗口（去掉子控件）
    root = win32util.user32.GetAncestor(hwnd, 2)  # GA_ROOT
    rect = win32util.window_rect(root)
    if rect is None:
        return capture_foreground_window()
    title = win32util.window_title(root)
    result = capture_rect(rect)
    result.title = title
    return result
