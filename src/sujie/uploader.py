"""上传通道：HTTP 接收端与离线待发队列。"""

from __future__ import annotations

import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from . import paths
from .config import ClientConfig

USER_AGENT = "Sujie/1.0"


def _opener() -> urllib.request.OpenerDirector:
    """局域网直连用的 opener：显式忽略系统代理。

    Windows 上装了 Clash / v2ray 之类的代理时，系统代理是全局的，
    Python 的 urllib 会自动走它；一旦代理的绕过列表里没写内网网段，
    发往 192.168.x.x 的请求就会被代理吃掉，表现为「连不上但网络正常」。
    这里强制直连，避免用户排查半天。
    """
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass
class UploadResult:
    ok: bool
    message: str = ""
    remote_path: str = ""
    successful_targets: int = 0
    total_targets: int = 0
    failed_targets: List[dict] = field(default_factory=list)


# --------------------------------------------------------------------- HTTP

def http_ping(host: str, port: int, token: str = "", timeout: float = 4.0) -> UploadResult:
    """探测 HTTP 接收端是否在线。"""
    url = f"http://{host}:{port}/ping"
    request = urllib.request.Request(url, method="GET")
    request.add_header("User-Agent", USER_AGENT)
    if token:
        request.add_header("X-Token", token)
    try:
        with _opener().open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            try:
                data = json.loads(body)
            except ValueError:
                data = {}
            return UploadResult(True, "连接正常", str(data.get("device", "")))
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return UploadResult(False, "密钥不匹配（接收端要求 token）")
        return UploadResult(False, f"HTTP {exc.code}: {exc.reason}")
    except Exception as exc:
        return UploadResult(False, f"无法连接 {host}:{port} —— {exc}")


def http_upload(
    host: str,
    port: int,
    token: str,
    filename: str,
    data: bytes,
    timeout: float = 20.0,
) -> UploadResult:
    """把图片二进制 POST 给接收端。"""
    url = f"http://{host}:{port}/upload"
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Content-Type", "application/octet-stream")
    request.add_header("X-File-Name", urllib.parse.quote(filename))
    request.add_header("X-Size", str(len(data)))
    if token:
        request.add_header("X-Token", token)
    try:
        with _opener().open(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = {}
            return UploadResult(
                True,
                parsed.get("message", "上传成功"),
                str(parsed.get("path", "")),
            )
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            pass
        if exc.code == 401:
            return UploadResult(False, "密钥不匹配（接收端要求 token）")
        return UploadResult(False, f"HTTP {exc.code} {detail}")
    except Exception as exc:
        return UploadResult(False, f"上传失败：{exc}")


# ------------------------------------------------------------------ 统一入口

def upload_image(
    config: ClientConfig,
    filename: str,
    data: bytes,
) -> UploadResult:
    """把图片发给配置的所有接收端，并返回未成功的目标。"""
    return upload_targets(config.targets, filename, data)


def upload_targets(targets: List[dict], filename: str, data: bytes) -> UploadResult:
    if not targets:
        return UploadResult(False, "尚未配置接收端地址")
    failed = []
    sent = 0
    for target in targets:
        result = http_upload(
            str(target.get("host", "")),
            int(target.get("port", 8765)),
            str(target.get("token", "")),
            filename,
            data,
        )
        if result.ok:
            sent += 1
        else:
            failed.append({**target, "error": result.message})
    total = len(targets)
    message = f"已发送到 {sent}/{total} 个接收端"
    if failed:
        message += f"；{len(failed)} 个失败"
    return UploadResult(not failed, message, successful_targets=sent, total_targets=total, failed_targets=failed)


def test_connection(config: ClientConfig) -> UploadResult:
    """测试所有接收端，汇总失败目标。"""
    failed = []
    sent = 0
    for target in config.targets:
        result = http_ping(str(target.get("host", "")), int(target.get("port", 8765)), str(target.get("token", "")))
        if result.ok:
            sent += 1
        else:
            failed.append({**target, "error": result.message})
    total = len(config.targets)
    details = "; ".join(
        f"{target.get('host')}:{target.get('port')} {target.get('error')}"
        for target in failed
    )
    message = f"连接正常：{sent}/{total} 个接收端"
    if details:
        message += f"；{details}"
    return UploadResult(total > 0 and not failed, message, successful_targets=sent, total_targets=total, failed_targets=failed)


# ------------------------------------------------------------------ 待发队列

class Outbox:
    """离线待发队列：发送失败时把图片存到本地，恢复连接后自动补发。"""

    def __init__(self, directory: Optional[str] = None):
        self.directory = directory or str(paths.outbox_dir())

    def add(self, filename: str, data: bytes, targets: Optional[List[dict]] = None) -> str:
        os.makedirs(self.directory, exist_ok=True)
        safe = _safe_filename(filename)
        target = os.path.join(self.directory, safe)
        stem, ext = os.path.splitext(safe)
        index = 1
        while os.path.exists(target):
            target = os.path.join(self.directory, f"{stem}-{index}{ext}")
            index += 1
        with open(target, "wb") as fh:
            fh.write(data)
        _write_meta(target, {"filename": filename, "targets": targets or []})
        return target

    def pending(self) -> List[Tuple[str, bytes, str, List[dict]]]:
        """返回 [(队列文件名, 图像, 原始文件名, 失败目标)]。"""
        items: List[Tuple[str, bytes, str, List[dict]]] = []
        if not os.path.isdir(self.directory):
            return items
        for name in sorted(os.listdir(self.directory)):
            if not name.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                continue
            full = os.path.join(self.directory, name)
            try:
                with open(full, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            meta = _read_meta(full)
            if isinstance(meta, dict):
                original = str(meta.get("filename", name))
                targets = meta.get("targets", [])
            else:  # 兼容旧版只保存原文件名的队列
                original, targets = str(meta or name), []
            items.append((name, data, original, targets if isinstance(targets, list) else []))
        return items

    def update_targets(self, queue_name: str, filename: str, targets: List[dict]) -> None:
        _write_meta(os.path.join(self.directory, queue_name), {"filename": filename, "targets": targets})

    def remove(self, queue_name: str) -> None:
        for suffix in ("", ".meta"):
            path = os.path.join(self.directory, queue_name + suffix)
            try:
                os.remove(path)
            except OSError:
                pass

    def count(self) -> int:
        if not os.path.isdir(self.directory):
            return 0
        return len(
            [n for n in os.listdir(self.directory) if n.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))]
        )


def _safe_filename(name: str) -> str:
    keep = []
    for ch in name:
        keep.append(ch if (ch.isalnum() or ch in "-_. ") else "_")
    result = "".join(keep).strip() or "shot.png"
    return result[:120]


def _meta_path(path: str) -> str:
    return path + ".meta"


def _write_meta(path: str, data: dict) -> None:
    try:
        with open(_meta_path(path), "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
    except OSError:
        pass


def _read_meta(path: str):
    try:
        with open(_meta_path(path), "r", encoding="utf-8") as fh:
            raw = fh.read().strip()
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    except OSError:
        return None


def flush_outbox(config: ClientConfig, outbox: Outbox, on_result: Optional[Callable[[UploadResult, str], None]] = None) -> int:
    """只补发每张图尚未成功的接收端，返回完全送达的图片数。"""
    sent = 0
    for queue_name, data, original, targets in outbox.pending():
        result = upload_targets(targets or config.targets, original, data)
        if result.ok:
            outbox.remove(queue_name)
            sent += 1
        else:
            outbox.update_targets(queue_name, original, result.failed_targets)
        if on_result:
            on_result(result, original)
    return sent
