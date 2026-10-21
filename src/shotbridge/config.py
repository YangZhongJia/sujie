"""配置：客户端与接收端的设置持久化（JSON 文件）。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict

from . import paths

CLIENT_CONFIG_NAME = "client.json"
RECEIVER_CONFIG_NAME = "receiver.json"

CAPTURE_MODES = ("window", "monitor", "screen", "region")
CAPTURE_MODE_LABELS = {
    "window": "当前活动窗口",
    "monitor": "当前显示器",
    "screen": "整个屏幕",
    "region": "手动框选区域",
}
def _atomic_write(path: str, data: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class _JsonConfig:
    """JSON 配置基类：字段自动序列化，未知键忽略。"""

    _file_name = ""
    _defaults: Dict[str, Any] = {}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)  # type: ignore[arg-type]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
        kwargs = {k: v for k, v in (data or {}).items() if k in known}
        obj = cls(**kwargs)  # type: ignore[call-arg]
        # 类型纠正（手工改过 JSON 也不会崩）
        for f in fields(cls):  # type: ignore[arg-type]
            if f.name not in kwargs:
                continue
            current = getattr(obj, f.name)
            default = cls._defaults.get(f.name)
            try:
                if isinstance(default, bool) and not isinstance(current, bool):
                    setattr(obj, f.name, bool(current))
                elif isinstance(default, int) and not isinstance(current, bool) and not isinstance(current, int):
                    setattr(obj, f.name, int(current))
                elif isinstance(default, str) and not isinstance(current, str):
                    setattr(obj, f.name, str(current))
            except (TypeError, ValueError):
                setattr(obj, f.name, default)
        return obj

    @property
    def path(self) -> str:
        return str(paths.app_data_dir() / self._file_name)

    def save(self) -> None:
        _atomic_write(self.path, json.dumps(self.to_dict(), indent=2, ensure_ascii=False))

    @classmethod
    def load(cls):
        path = str(paths.app_data_dir() / cls._file_name)
        data: Dict[str, Any] = {}
        if os.path.exists(path):
            try:
                with open(path, "rb") as fh:
                    raw = fh.read()
                # 用户可能用记事本改过配置：UTF-8 带 BOM / UTF-16 都要能读
                if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
                    text = raw.decode("utf-16")
                elif raw.startswith(b"\xef\xbb\xbf"):
                    text = raw.decode("utf-8-sig")
                else:
                    text = raw.decode("utf-8", "replace")
                data = json.loads(text) if text.strip() else {}
                if not isinstance(data, dict):
                    data = {}
            except (OSError, ValueError):
                data = {}
        return cls.from_dict(data)  # type: ignore[return-value]


@dataclass
class ClientConfig(_JsonConfig):
    """客户端（截图端）配置。"""

    host: str = ""                   # HTTP 接收端 IP
    port: int = 8765                 # HTTP 接收端端口
    token: str = ""                  # 共享密钥（可空）

    capture_mode: str = "window"     # window | monitor | screen | region
    auto_start: bool = False
    retry_enabled: bool = True
    retry_interval: int = 60         # 离线重发轮询间隔（秒）
    notify_on_send: bool = True
    sound_on_send: bool = False
    show_ball: bool = True
    ball_size: int = 52
    ball_opacity: float = 0.9
    ball_color: str = "#e94f37"
    ball_position: str = ""          # "x,y" 记忆位置

    _file_name = CLIENT_CONFIG_NAME
    _defaults = {
        "host": "",
        "port": 8765,
        "token": "",
        "capture_mode": "window",
        "auto_start": False,
        "retry_enabled": True,
        "retry_interval": 60,
        "notify_on_send": True,
        "sound_on_send": False,
        "show_ball": True,
        "ball_size": 52,
        "ball_opacity": 0.9,
        "ball_color": "#e94f37",
        "ball_position": "",
    }


@dataclass
class ReceiverConfig(_JsonConfig):
    """接收端（接收方电脑）配置。"""

    save_dir: str = ""               # 截图落盘目录
    port: int = 8765
    token: str = ""                  # 校验用密钥，客户端需填写相同值
    subdir_by_date: bool = True      # 按日期分子目录
    filename_prefix: str = "shot"    # 文件名前缀
    auto_start: bool = False
    bind_address: str = "0.0.0.0"

    _file_name = RECEIVER_CONFIG_NAME
    _defaults = {
        "save_dir": "",
        "port": 8765,
        "token": "",
        "subdir_by_date": True,
        "filename_prefix": "shot",
        "auto_start": False,
        "bind_address": "0.0.0.0",
    }

    def resolved_save_dir(self) -> str:
        r"""未配置时使用「图片\ShotBridge」。"""
        if self.save_dir:
            return os.path.abspath(os.path.expanduser(self.save_dir))
        pics = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        return os.path.join(pics, "Pictures", "ShotBridge")
