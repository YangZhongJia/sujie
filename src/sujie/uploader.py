"""上传通道：HTTP 接收端与离线待发队列。"""

from __future__ import annotations

import http.client
import io
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from . import paths
from .config import ClientConfig

USER_AGENT = "Sujie/1.0"

# 多目标并行发送的线程上限：局域网带宽就那么多，目标再多并行也没有额外收益，
# 反而会互相挤占。普通交换机环境下 4 路并发足够跑满。
MAX_PARALLEL_TARGETS = 4

# 离线待发队列的条目上限，防止收图电脑长期离线时队列无限增长
OUTBOX_MAX_ITEMS = 200


def _send_parallel(targets: List[dict], send: Callable[[dict], "UploadResult"]) -> List["UploadResult"]:
    """并行把同一份内容发给所有接收端，返回结果列表（顺序与 targets 一致）。

    串行逐台发时总耗时是累加的：5 台电脑 = 5 倍时间；并行后取决于最慢的一台。
    send 内部已自行捕获所有网络异常并转成失败结果，这里不会向外抛。
    """
    if len(targets) <= 1:
        return [send(target) for target in targets]
    workers = min(len(targets), MAX_PARALLEL_TARGETS)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="sujie-send") as pool:
        return list(pool.map(send, targets))


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


# ----------------------------------------------------- HTTP（流式，适合录屏）

CHUNK_SIZE = 1024 * 1024
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
VIDEO_SUFFIXES = (".mp4", ".webm", ".mkv", ".mov", ".avi")
MEDIA_SUFFIXES = IMAGE_SUFFIXES + VIDEO_SUFFIXES


def _remote_limit_mb(host: str, port: int, token: str) -> int:
    """问一下接收端的单文件上限；问不到就返回 0。"""
    request = urllib.request.Request(f"http://{host}:{port}/ping")
    request.add_header("User-Agent", USER_AGENT)
    if token:
        request.add_header("X-Token", token)
    with _opener().open(request, timeout=3.0) as response:
        payload = json.loads(response.read().decode("utf-8", "replace"))
    return int(payload.get("max_upload_mb") or 0)


def http_upload_file(
    host: str,
    port: int,
    token: str,
    filename: str,
    path: str,
    size: Optional[int] = None,
    timeout: float = 120.0,
    progress: Optional[Callable[[int, int], None]] = None,
    keep_name: bool = False,
) -> UploadResult:
    """按 1MB 分块把磁盘文件 POST 给接收端。

    录屏动辄几十上百 MB，不能像截图那样整段放进内存（``http_upload`` 就是那样），
    所以这里直接用 ``http.client`` 自己拼请求体，读一块发一块。
    注意：``http.client`` 天生不走系统代理，正好符合局域网直连的要求。
    ``keep_name`` 给「发送文件」用：请接收端保留原文件名，而不是改写成时间戳名。
    """
    try:
        total = int(size if size is not None else os.path.getsize(path))
    except OSError as exc:
        return UploadResult(False, f"读取文件失败：{exc}")

    connection = None
    try:
        connection = http.client.HTTPConnection(host, int(port), timeout=timeout)
        connection.putrequest("POST", "/upload")
        connection.putheader("User-Agent", USER_AGENT)
        connection.putheader("Content-Type", "application/octet-stream")
        connection.putheader("X-File-Name", urllib.parse.quote(filename))
        connection.putheader("X-Size", str(total))
        connection.putheader("X-Stream", "1")
        if keep_name:
            connection.putheader("X-Keep-Name", "1")
        if token:
            connection.putheader("X-Token", token)
        connection.putheader("Content-Length", str(total))
        connection.endheaders()

        sent = 0
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(CHUNK_SIZE)
                if not chunk:
                    break
                connection.send(chunk)
                sent += len(chunk)
                if progress is not None:
                    try:
                        progress(sent, total)
                    except Exception:  # 进度回调不允许影响上传
                        pass

        response = connection.getresponse()
        body = response.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = {}
        if response.status == 401:
            return UploadResult(False, "密钥不匹配（接收端要求 token）")
        if response.status >= 400:
            return UploadResult(False, f"HTTP {response.status} {parsed.get('message', '')}".strip())
        return UploadResult(True, parsed.get("message", "上传成功"), str(parsed.get("path", "")))
    except Exception as exc:
        # 接收端体积超限时会直接掐断连接（它不想白读几十 MB），客户端只会看到
        # 10053/10054。这里回头查一次上限，把「文件太大」这个真实原因翻译出来。
        message = f"上传失败：{exc}"
        try:
            limit = _remote_limit_mb(host, int(port), token)
        except Exception:
            limit = 0
        if limit and total > limit * 1024 * 1024:
            message = (
                f"文件太大：{total / 1048576:.0f} MB，接收端上限 {limit} MB"
                "（可以在接收端设置里调大）"
            )
        return UploadResult(False, message)
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def upload_targets_file(
    targets: List[dict],
    filename: str,
    path: str,
    size: Optional[int] = None,
    progress: Optional[Callable[[int, int], None]] = None,
    keep_name: bool = False,
) -> UploadResult:
    """把磁盘上的文件（录屏或任意文件）发给所有接收端。"""
    if not targets:
        return UploadResult(False, "尚未配置接收端地址")

    def _send(target: dict) -> UploadResult:
        return http_upload_file(
            str(target.get("host", "")),
            int(target.get("port", 8765)),
            str(target.get("token", "")),
            filename,
            path,
            size=size,
            progress=progress,
            keep_name=keep_name,
        )

    failed = []
    sent = 0
    for target, result in zip(targets, _send_parallel(targets, _send)):
        if result.ok:
            sent += 1
        else:
            failed.append({**target, "error": result.message})
    total = len(targets)
    message = f"已发送到 {sent}/{total} 个接收端"
    if failed:
        # 只有一个接收端时把具体原因透出来（例如「文件太大」「密钥不匹配」），
        # 否则用户只看到「0/1 个接收端」，不知道该怎么处理。
        if total == 1:
            message = str(failed[0].get("error") or message)
        else:
            message += f"；{len(failed)} 个失败"
    return UploadResult(not failed, message, successful_targets=sent, total_targets=total, failed_targets=failed)


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

    def _send(target: dict) -> UploadResult:
        return http_upload(
            str(target.get("host", "")),
            int(target.get("port", 8765)),
            str(target.get("token", "")),
            filename,
            data,
        )

    failed = []
    sent = 0
    for target, result in zip(targets, _send_parallel(targets, _send)):
        if result.ok:
            sent += 1
        else:
            failed.append({**target, "error": result.message})
    total = len(targets)
    message = f"已发送到 {sent}/{total} 个接收端"
    if failed:
        message += f"；{len(failed)} 个失败"
    return UploadResult(not failed, message, successful_targets=sent, total_targets=total, failed_targets=failed)


def test_targets(targets: List[dict]) -> UploadResult:
    """逐个 ping 接收端，汇总失败目标。"""
    failed = []
    sent = 0
    for target in targets:
        result = http_ping(str(target.get("host", "")), int(target.get("port", 8765)), str(target.get("token", "")))
        if result.ok:
            sent += 1
        else:
            failed.append({**target, "error": result.message})
    total = len(targets)
    details = "; ".join(
        f"{target.get('host')}:{target.get('port')} {target.get('error')}"
        for target in failed
    )
    message = f"连接正常：{sent}/{total} 个接收端"
    if details:
        message += f"；{details}"
    return UploadResult(total > 0 and not failed, message, successful_targets=sent, total_targets=total, failed_targets=failed)


def test_connection(config: ClientConfig) -> UploadResult:
    """测试所有接收端，汇总失败目标。"""
    return test_targets(config.targets)


# ------------------------------------------------------------------ 待发队列

class Outbox:
    """离线待发队列：发送失败时把图片存到本地，恢复连接后自动补发。

    队列条目数有上限（:data:`OUTBOX_MAX_ITEMS`）：收图电脑长期离线时，
    每次发送失败都会往这里堆一份副本，不设上限会把磁盘慢慢撑爆。
    超限后按最旧优先淘汰（连同 meta 一起删）。
    """

    def __init__(self, directory: Optional[str] = None):
        self.directory = directory or str(paths.outbox_dir())

    def _evict_old(self) -> None:
        try:
            names = [n for n in os.listdir(self.directory)
                     if n.lower().endswith(MEDIA_SUFFIXES)]
        except OSError:
            return
        excess = len(names) - OUTBOX_MAX_ITEMS
        if excess <= 0:
            return
        def _mtime(name: str) -> float:
            try:
                return os.path.getmtime(os.path.join(self.directory, name))
            except OSError:
                return 0.0
        for name in sorted(names, key=_mtime)[:excess]:
            self.remove(name)

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
        self._evict_old()
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

    def add_file(self, filename: str, source: str, targets: Optional[List[dict]] = None) -> str:
        """把录像这类大文件放进队列：只复制文件，不读进内存。"""
        os.makedirs(self.directory, exist_ok=True)
        safe = _safe_filename(filename)
        target = os.path.join(self.directory, safe)
        stem, ext = os.path.splitext(safe)
        index = 1
        while os.path.exists(target):
            target = os.path.join(self.directory, f"{stem}-{index}{ext}")
            index += 1
        shutil.copy2(source, target)
        _write_meta(target, {"filename": filename, "targets": targets or []})
        self._evict_old()
        return target

    def pending_files(self) -> List[Tuple[str, str, str, List[dict]]]:
        """返回 [(队列文件名, 完整路径, 原始文件名, 失败目标)]，图片和视频都算。"""
        items: List[Tuple[str, str, str, List[dict]]] = []
        if not os.path.isdir(self.directory):
            return items
        for name in sorted(os.listdir(self.directory)):
            if not name.lower().endswith(MEDIA_SUFFIXES):
                continue
            full = os.path.join(self.directory, name)
            meta = _read_meta(full)
            if isinstance(meta, dict):
                original = str(meta.get("filename", name))
                targets = meta.get("targets", [])
            else:  # 兼容旧版只保存原文件名的队列
                original, targets = str(meta or name), []
            items.append((name, full, original, targets if isinstance(targets, list) else []))
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
        return len([n for n in os.listdir(self.directory) if n.lower().endswith(MEDIA_SUFFIXES)])


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
    """只补发每个文件尚未成功的接收端，返回完全送达的文件数。"""
    sent = 0
    for queue_name, path, original, targets in outbox.pending_files():
        result = upload_targets_file(targets or config.targets, original, path)
        if result.ok:
            outbox.remove(queue_name)
            sent += 1
        else:
            outbox.update_targets(queue_name, original, result.failed_targets)
        if on_result:
            on_result(result, original)
    return sent
