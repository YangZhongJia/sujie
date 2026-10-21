"""启动引导：日志落盘、全局异常兜底、单实例互斥。

打包成窗口程序（console=False）后进程没有 stdout/stderr，任何崩溃都看不见，
所以这里先把日志文件接起来，再进主流程。
"""

from __future__ import annotations

import ctypes
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

from .paths import local_data_dir

_IS_WINDOWS = sys.platform == "win32"
_stream = None
_log_path: Optional[str] = None
_mutex_handle = None


def log_path() -> str:
    return _log_path or ""


def _log_dir() -> Path:
    return local_data_dir() / "logs"


def _show_error_dialog(title: str, text: str) -> None:
    """只在打包后的窗口程序里弹原生对话框；开发态只打印。"""
    if not getattr(sys, "frozen", False) or not _IS_WINDOWS:
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)
    except Exception:
        pass


def init_logging(name: str = "app", show_dialog_on_error: bool = True) -> str:
    """初始化日志文件，并把未捕获异常写进日志。返回日志路径。"""
    global _stream, _log_path

    directory = _log_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        directory = Path(os.environ.get("TEMP") or ".")

    path = directory / f"{name}.log"
    try:
        if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
            os.replace(path, directory / f"{name}.old.log")
    except OSError:
        pass

    try:
        stream = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        stream = None

    _stream = stream
    _log_path = str(path)

    # 窗口程序没有标准输出，重定向到日志，避免 print() 直接抛异常
    if stream is not None:
        if sys.stdout is None:
            sys.stdout = stream  # type: ignore[assignment]
        if sys.stderr is None:
            sys.stderr = stream  # type: ignore[assignment]

    def _excepthook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log(f"未捕获异常：\n{text}")
        if show_dialog_on_error:
            _show_error_dialog(
                "速截 出错了",
                f"{exc_type.__name__}: {exc}\n\n详细信息已写入日志：\n{_log_path}",
            )

    sys.excepthook = _excepthook
    log("=" * 60)
    log(f"启动 {name} @ {datetime.now():%Y-%m-%d %H:%M:%S}")
    return str(path)


def log(message: str) -> None:
    """写一条日志（同时尽量写到 stderr）。"""
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    stream = _stream
    if stream is not None:
        try:
            stream.write(line + "\n")
            stream.flush()
            return
        except Exception:
            pass
    try:
        print(line)
    except Exception:
        pass


def log_environment() -> None:
    """记录运行环境，便于排查（尤其是打包后的问题）。"""
    log(
        "环境: frozen=%s executable=%s meipass=%s python=%s cwd=%s argv=%s"
        % (
            getattr(sys, "frozen", False),
            sys.executable,
            getattr(sys, "_MEIPASS", ""),
            sys.version.split()[0],
            os.getcwd(),
            sys.argv,
        )
    )


def acquire_single_instance(key: str) -> bool:
    """单实例互斥：已有同名实例在跑时返回 False。"""
    global _mutex_handle
    if not _IS_WINDOWS:
        return True
    ERROR_ALREADY_EXISTS = 183
    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, f"Global\\{key}")
        if not handle:
            return True
        if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            ctypes.windll.kernel32.CloseHandle(handle)
            return False
        _mutex_handle = handle
        return True
    except Exception:
        return True
