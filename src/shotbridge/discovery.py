"""局域网设备自动发现：UDP 广播问答。

接收端在 UDP 8766 端口监听，收到魔数包后用单播回复自己的信息；
客户端广播魔数包并收集回复，用于在设置界面里一键选择目标机器。
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Callable, Dict, List, Optional

DISCOVERY_PORT = 8766
MAGIC = b"SHOTBRIDGE_DISCOVER"
REPLY_MAGIC = b"SHOTBRIDGE_REPLY"


def _broadcast_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(1.0)
    return sock


class DiscoveryResponder:
    """接收端：应答发现请求。"""

    def __init__(self, info_provider: Callable[[], Dict], port: int = DISCOVERY_PORT):
        self._info_provider = info_provider
        self._port = port
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sock: Optional[socket.socket] = None

    def start(self) -> bool:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self._port))
            sock.settimeout(0.5)
        except OSError:
            return False
        self._sock = sock
        self._thread = threading.Thread(target=self._loop, name="sb-discovery", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(1024)  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                break
            if MAGIC not in data:
                continue
            try:
                payload = json.dumps(self._info_provider()).encode("utf-8")
            except Exception:
                continue
            try:
                self._sock.sendto(REPLY_MAGIC + payload, addr)  # type: ignore[union-attr]
            except OSError:
                pass


def discover(timeout: float = 1.6) -> List[Dict]:
    """客户端：广播发现，收集局域网内的接收端。返回设备信息列表。"""
    found: Dict[str, Dict] = {}
    try:
        sock = _broadcast_socket()
    except OSError:
        return []

    try:
        for broadcast_addr in ("255.255.255.255", "127.0.0.1"):
            try:
                sock.sendto(MAGIC, (broadcast_addr, DISCOVERY_PORT))
            except OSError:
                continue

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            if not data.startswith(REPLY_MAGIC):
                continue
            try:
                info = json.loads(data[len(REPLY_MAGIC):].decode("utf-8"))
            except Exception:
                continue
            key = info.get("device") or addr[0]
            info["_source_ip"] = addr[0]
            found[key] = info
    finally:
        try:
            sock.close()
        except OSError:
            pass

    return list(found.values())
