"""Windows 平台辅助：DPI 感知、前台窗口、显示器枚举、开机自启、打开文件夹。"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Optional

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    try:
        shcore = ctypes.windll.shcore
    except AttributeError:  # pragma: no cover - 老系统
        shcore = None
else:  # pragma: no cover
    user32 = gdi32 = shcore = None


# --------------------------------------------------------------------------- DPI

def enable_dpi_awareness() -> None:
    """让本进程感知每显示器 DPI，使 Win32 坐标与截图坐标（物理像素）一致。

    必须在创建任何窗口之前调用，否则高 DPI 下窗口矩形与截图像素会错位。
    """
    if not IS_WINDOWS:
        return
    try:
        # PER_MONITOR_AWARE_V2 = -4
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        if shcore is not None and shcore.SetProcessDpiAwareness(2) == 0:
            return
    except Exception:
        pass
    try:
        user32.SetProcessDPIAware()
    except Exception:
        pass


# --------------------------------------------------------------------- 虚拟屏幕

@dataclass
class Monitor:
    """一块显示器在虚拟桌面中的位置（物理像素）。"""

    left: int
    top: int
    width: int
    height: int
    primary: bool = False

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height


def virtual_screen_rect() -> tuple[int, int, int, int]:
    """整个虚拟桌面（所有显示器并集）的物理像素矩形 (left, top, right, bottom)。"""
    if not IS_WINDOWS:
        return (0, 0, 1920, 1080)
    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
    SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
    left = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    top = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return (left, top, left + width, top + height)


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("rcMonitor", _RECT),
        ("rcWork", _RECT),
        ("dwFlags", ctypes.c_ulong),
    ]


def enumerate_monitors() -> List[Monitor]:
    """枚举所有显示器。

    注意：EnumDisplayMonitors 的回调第三参数是 RECT*（显示器矩形），
    要拿 MONITORINFO（工作区、是否主显示器）必须再调 GetMonitorInfoW。
    """
    if not IS_WINDOWS:
        return [Monitor(0, 0, 1920, 1080, True)]
    result: List[Monitor] = []

    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(_RECT), ctypes.c_longlong
    )

    def _cb(hmon, hdc, lprc, lparam):
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if user32.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(info)):
            m = info.rcMonitor
            result.append(
                Monitor(
                    left=int(m.left),
                    top=int(m.top),
                    width=int(m.right) - int(m.left),
                    height=int(m.bottom) - int(m.top),
                    primary=bool(info.dwFlags & 1),  # MONITORINFOF_PRIMARY
                )
            )
        else:
            r = lprc.contents
            result.append(
                Monitor(
                    left=int(r.left),
                    top=int(r.top),
                    width=int(r.right) - int(r.left),
                    height=int(r.bottom) - int(r.top),
                )
            )
        return 1

    cb = callback_type(_cb)
    user32.EnumDisplayMonitors(None, None, cb, 0)
    if not result:
        l, t, r, b = virtual_screen_rect()
        result = [Monitor(l, t, r - l, b - t, True)]
    return result


def monitor_containing_point(x: int, y: int) -> Optional[Monitor]:
    """返回包含物理坐标 (x, y) 的显示器。"""
    for m in enumerate_monitors():
        if m.left <= x < m.right and m.top <= y < m.bottom:
            return m
    return None


# --------------------------------------------------------------------- 窗口

def foreground_window() -> int:
    """当前前台窗口 HWND。"""
    if not IS_WINDOWS:
        return 0
    return int(user32.GetForegroundWindow())


def window_rect(hwnd: int) -> Optional[tuple[int, int, int, int]]:
    """窗口在虚拟桌面中的物理像素矩形。"""
    if not IS_WINDOWS or not hwnd:
        return None

    class RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    r = RECT()
    if not user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(r)):
        return None
    return (r.left, r.top, r.right, r.bottom)


def foreground_window_rect() -> Optional[tuple[int, int, int, int]]:
    """前台窗口矩形；当前前台窗口是我们自己的悬浮球时返回 None。"""
    hwnd = foreground_window()
    if not hwnd:
        return None
    return window_rect(hwnd)


def window_title(hwnd: int) -> str:
    if not IS_WINDOWS or not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def is_our_foreground(hwnd_ours: int) -> bool:
    """判断前台窗口是否就是我们的悬浮球（是则说明焦点在我们身上）。"""
    return bool(hwnd_ours) and foreground_window() == hwnd_ours


# ----------------------------------------------------------------- 开机自启

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _run_key():
    import winreg

    return winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_ALL_ACCESS)


def is_autostart_enabled(value_name: str) -> bool:
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return bool(value)
    except (FileNotFoundError, OSError):
        return False


def set_autostart(enabled: bool, value_name: str, command: str) -> bool:
    """在 HKCU\\...\\Run 写入/删除开机自启项。返回是否操作成功。"""
    if not IS_WINDOWS:
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_ALL_ACCESS
        ) as key:
            if enabled:
                winreg.SetValueEx(key, value_name, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, value_name)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def autostart_command(value_name: str) -> Optional[str]:
    if not IS_WINDOWS:
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            return value
    except (FileNotFoundError, OSError):
        return None


# ------------------------------------------------------------------- 其他

def open_path(path: str) -> bool:
    """用系统默认程序打开文件/文件夹。"""
    if not path:
        return False
    try:
        os.startfile(path)  # type: ignore[attr-defined]
        return True
    except Exception:
        try:
            subprocess.Popen(["explorer", path])
            return True
        except Exception:
            return False


def local_ipv4_addresses() -> List[str]:
    """本机 IPv4 地址列表，第一个是「最可能给同事用的局域网地址」。

    顺序很重要：Windows 上常同时存在 WSL / Docker / 虚拟网卡（172.16/12、
    169.254/16 等），用户需要的是默认路由那张网卡的地址。
    这里用 UDP 连接一个外网地址（不实际发包）拿到出口网卡 IP，排到最前。
    """
    import socket

    ordered: List[str] = []

    def add(ip: str) -> None:
        if not ip or ip.startswith("127.") or ip.startswith("169.254."):
            return
        if ip not in ordered:
            ordered.append(ip)

    # 1) 默认路由出口网卡
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(0.3)
            s.connect(("223.5.5.5", 80))
            add(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass

    # 2) 主机名解析到的所有地址
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except Exception:
        pass

    return ordered
