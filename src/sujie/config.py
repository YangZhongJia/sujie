"""配置：客户端与接收端的设置持久化（JSON 文件）。"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Dict
from hashlib import sha256

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


def receiver_target(host: str, port: int = 8765, token: str = "", name: str = "") -> Dict[str, Any]:
    host = str(host).strip()
    if not host or any(ch.isspace() for ch in host) or "/" in host:
        raise ValueError("接收端地址无效")
    if isinstance(port, bool):
        raise ValueError("接收端端口无效")
    port = int(port)
    if not 1 <= port <= 65535:
        raise ValueError("接收端端口必须在 1 到 65535 之间")
    identity = sha256(f"{host.casefold()}:{port}".encode("utf-8")).hexdigest()[:16]
    return {"id": identity, "name": name.strip() or host, "host": host, "port": port,
            "token": str(token or "").strip()}


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
        data = data or {}
        if cls is ClientConfig:
            data = dict(data)
            # Upgrade the old single-receiver client.json without changing its target.
            if "targets" not in data and data.get("host"):
                try:
                    data["targets"] = [receiver_target(
                        data["host"], data.get("port", 8765), data.get("token", "")
                    )]
                except (TypeError, ValueError):
                    data["targets"] = []
            normalized = []
            raw_targets = data.get("targets", [])
            if isinstance(raw_targets, list):
                for raw_target in raw_targets:
                    if not isinstance(raw_target, dict):
                        continue
                    try:
                        target = receiver_target(
                            raw_target.get("host", ""), raw_target.get("port", 8765),
                            raw_target.get("token", ""), raw_target.get("name", ""),
                        )
                    except (TypeError, ValueError):
                        continue
                    target["id"] = str(raw_target.get("id") or target["id"])
                    normalized.append(target)
            data["targets"] = normalized
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

    targets: list[Dict[str, Any]] = field(default_factory=list)

    capture_mode: str = "window"     # window | monitor | screen | region
    after_capture: str = "editor"    # editor | send | copy | pin
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

    # 长按扇形菜单
    radial_enabled: bool = True
    radial_long_press_ms: int = 500
    radial_radius: int = 132
    radial_show_reserved: bool = True
    radial_hint_shown: bool = False

    # 贴图钉屏
    hide_pins_when_capturing: bool = True
    pin_max_count: int = 8

    # 最近记录
    history_limit: int = 200

    # 录屏
    record_mode: str = "monitor"     # monitor | region | window
    record_fps: int = 30
    record_audio: str = "none"       # none | mic
    record_mic_device: str = ""
    record_send_after: bool = True
    record_keep_local: bool = False
    record_dir: str = ""
    record_max_mb: int = 500

    _file_name = CLIENT_CONFIG_NAME
    _defaults = {
        "targets": [],
        "capture_mode": "window",
        "after_capture": "editor",
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
        "radial_enabled": True,
        "radial_long_press_ms": 500,
        "radial_radius": 132,
        "radial_show_reserved": True,
        "radial_hint_shown": False,
        "hide_pins_when_capturing": True,
        "pin_max_count": 8,
        "history_limit": 200,
        "record_mode": "monitor",
        "record_fps": 30,
        "record_audio": "none",
        "record_mic_device": "",
        "record_send_after": True,
        "record_keep_local": False,
        "record_dir": "",
        "record_max_mb": 500,
    }


MODE_CHOICES = ("screenshot", "receiver", "both")
MODE_LABELS = {
    "screenshot": "只截图",
    "receiver": "只收图",
    "both": "同时截图和收图",
}


@dataclass
class AppModeConfig(_JsonConfig):
    """本机工作模式。首次运行时为空，由启动引导选择。"""

    mode: str = ""

    _file_name = "mode.json"
    _defaults = {"mode": ""}


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
    max_upload_mb: int = 2048         # 单个文件上限（录屏会比较大），0 表示不限制

    _file_name = RECEIVER_CONFIG_NAME
    _defaults = {
        "save_dir": "",
        "port": 8765,
        "token": "",
        "subdir_by_date": True,
        "filename_prefix": "shot",
        "auto_start": False,
        "bind_address": "0.0.0.0",
        "max_upload_mb": 2048,
    }

    def resolved_save_dir(self) -> str:
        r"""未配置时使用「图片\速截」。"""
        if self.save_dir:
            return os.path.abspath(os.path.expanduser(self.save_dir))
        pics = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        return os.path.join(pics, "Pictures", "速截")
