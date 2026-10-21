"""应用数据目录（Windows）。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import APP_NAME

_FROZEN = getattr(sys, "frozen", False)


def _home() -> Path:
    return Path(os.path.expanduser("~"))


def _app_dir(base: str) -> Path:
    directory = Path(base) / APP_NAME
    legacy = Path(base) / "ShotBridge"
    if legacy.is_dir() and not directory.exists():
        try:
            legacy.replace(directory)
        except OSError:
            pass
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def app_data_dir() -> Path:
    """配置目录：%APPDATA%\\速截"""
    base = os.environ.get("APPDATA") or str(_home() / "AppData" / "Roaming")
    return _app_dir(base)


def local_data_dir() -> Path:
    """本地数据目录：%LOCALAPPDATA%\\速截（日志、待发队列）。"""
    base = os.environ.get("LOCALAPPDATA") or str(_home() / "AppData" / "Local")
    return _app_dir(base)


def outbox_dir() -> Path:
    """离线待发队列目录。"""
    d = local_data_dir() / "outbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_file() -> Path:
    return local_data_dir() / "sujie.log"


def executable_path() -> str:
    """当前可执行文件路径（打包后为 exe，开发态为 python 脚本）。"""
    if _FROZEN:
        return sys.executable
    return os.path.abspath(sys.argv[0])


def startup_target() -> str:
    """开机自启时执行的命令（打包后直接跑 exe；开发态跑 python 脚本）。"""
    if _FROZEN:
        return f'"{sys.executable}"'
    import shlex

    py = f'"{sys.executable}"'
    script = os.path.abspath(sys.argv[0])
    return f'{py} "{script}"'
