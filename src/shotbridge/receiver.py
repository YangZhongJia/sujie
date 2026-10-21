"""接收端：在「另一台电脑」上运行，把收到的截图落盘到指定文件夹。

提供：
- HTTP 服务（默认 8765）：
    GET  /ping   健康检查 + 设备信息
    POST /upload 接收图片二进制（Header: X-File-Name，可选 X-Token）
- UDP 发现应答（8766），供客户端一键扫描局域网设备
- 系统托盘：显示接收状态、打开文件夹、修改保存目录、开机自启
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import unquote, urlparse

from . import APP_NAME, __version__, bootstrap, discovery, paths, win32util

RECEIVER_VALUE_NAME = "ShotBridgeReceiver"

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-一-鿿 ]")


def sanitize_filename(name: str, fallback: str = "shot.png") -> str:
    """去掉路径分隔符等危险字符，只保留文件名。"""
    name = os.path.basename(name or "").strip()
    name = _SAFE_NAME.sub("_", name)
    if not name:
        name = fallback
    return name[:120]


class ReceiverState:
    """接收端运行时状态。"""

    def __init__(self, config):
        self.config = config
        self.count = 0
        self.last_file = ""
        self.last_time = ""
        self.lock = threading.Lock()

    def save_dir(self) -> str:
        return self.config.resolved_save_dir()

    def target_dir(self) -> str:
        base = self.save_dir()
        if self.config.subdir_by_date:
            return os.path.join(base, datetime.now().strftime("%Y-%m-%d"))
        return base

    def info(self) -> dict:
        ips = win32util.local_ipv4_addresses()
        return {
            "app": APP_NAME,
            "version": __version__,
            "device": socket.gethostname(),
            "ips": ips,
            "ip": ips[0] if ips else "127.0.0.1",
            "http_port": self.config.port,
            "save_dir": self.save_dir(),
            "count": self.count,
        }


class ReceiverHandler(BaseHTTPRequestHandler):
    server_version = f"ShotBridge/{__version__}"
    state: ReceiverState = None  # type: ignore[assignment]

    # ------------------------------------------------------------ 基础响应
    def _send_json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def _authorized(self) -> bool:
        token = (self.state.config.token or "").strip()
        if not token:
            return True
        provided = self.headers.get("X-Token", "")
        return provided == token

    def log_message(self, fmt, *args):  # 静音默认日志
        if os.environ.get("SHOTBRIDGE_HTTP_LOG"):
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # ---------------------------------------------------------------- 路由
    def do_GET(self):  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if not self._authorized():
            self._send_json({"ok": False, "message": "token 无效"}, 401)
            return
        if path in ("/", "/ping", "/health"):
            self._send_json({"ok": True, **self.state.info()})
        else:
            self._send_json({"ok": False, "message": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        path = urlparse(self.path).path.rstrip("/") or "/"
        if path != "/upload":
            self._send_json({"ok": False, "message": "not found"}, 404)
            return
        if not self._authorized():
            self._send_json({"ok": False, "message": "token 无效"}, 401)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._send_json({"ok": False, "message": "空请求体"}, 400)
            return

        data = self.rfile.read(length)
        raw_name = unquote(self.headers.get("X-File-Name", "") or "")
        name = sanitize_filename(raw_name, "shot.png")

        # 扩展名统一：客户端可能传 .png/.jpg
        try:
            saved = self._save(name, data)
        except OSError as exc:
            self._send_json({"ok": False, "message": f"写入失败：{exc}"}, 500)
            return

        with self.state.lock:
            self.state.count += 1
            self.state.last_file = saved
            self.state.last_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        self._send_json(
            {
                "ok": True,
                "message": "接收成功",
                "path": saved,
                "name": os.path.basename(saved),
                "size": len(data),
            }
        )

    # ---------------------------------------------------------------- 辅助
    def _save(self, name: str, data: bytes) -> str:
        directory = self.state.target_dir()
        os.makedirs(directory, exist_ok=True)
        stem, ext = os.path.splitext(name)
        ext = ext or ".png"
        prefix = self.state.config.filename_prefix or "shot"
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = os.path.join(directory, f"{prefix}-{stamp}{ext}")
        index = 1
        while os.path.exists(candidate):
            candidate = os.path.join(directory, f"{prefix}-{stamp}-{index}{ext}")
            index += 1
        with open(candidate, "wb") as fh:
            fh.write(data)
        return candidate

def start_server(config) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """后台启动 HTTP 服务。"""
    state = ReceiverState(config)
    handler = type("BoundHandler", (ReceiverHandler,), {"state": state})
    bind = config.bind_address or "0.0.0.0"
    httpd = ThreadingHTTPServer((bind, int(config.port)), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, name="sb-http", daemon=True)
    thread.start()
    return httpd, thread


def _receiver_main_gui(argv=None) -> int:
    """接收端 GUI（托盘）。"""
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QApplication, QInputDialog, QMenu, QMessageBox, QSystemTrayIcon

    from .balloon import make_app_icon
    from .config import ReceiverConfig

    if not bootstrap.acquire_single_instance("ShotBridgeReceiver"):
        bootstrap.log("已有接收端在运行，本次退出")
        return 0

    bootstrap.log("准备创建 QApplication…")
    win32util.enable_dpi_awareness()
    app = QApplication(argv or sys.argv)
    app.setQuitOnLastWindowClosed(False)
    bootstrap.log("QApplication 创建完成")

    config = ReceiverConfig.load()
    if not config.save_dir:
        config.save_dir = os.path.join(
            os.environ.get("USERPROFILE", os.path.expanduser("~")), "Pictures", "ShotBridge"
        )
        config.save()
    bootstrap.log(f"配置已加载：端口={config.port} 目录={config.resolved_save_dir()}")

    icon = make_app_icon("#2f7de1")
    tray = QSystemTrayIcon(icon, app)
    tray.setToolTip(f"{APP_NAME} 接收端")

    httpd = None
    responder = None

    def device_info() -> dict:
        info = ReceiverState(config).info()
        info["http_port"] = config.port
        return info

    def ensure_server():
        nonlocal httpd, responder
        if httpd is not None:
            return
        try:
            httpd, _ = start_server(config)
            bootstrap.log(f"HTTP 服务已启动，端口 {config.port}，保存目录 {config.resolved_save_dir()}")
        except OSError as exc:
            bootstrap.log(f"监听端口 {config.port} 失败：{exc}")
            # 不弹模态框（开机自启时会卡住桌面），改为托盘气泡提示
            tray.showMessage(
                f"{APP_NAME} 启动失败",
                f"无法监听端口 {config.port}：{exc}\n请换一个端口。",
                QSystemTrayIcon.Critical,
                8000,
            )
            return
        responder = discovery.DiscoveryResponder(device_info)
        responder.start()
        bootstrap.log(f"局域网发现服务已启动，端口 {discovery.DISCOVERY_PORT}")
        refresh_tray()

    def refresh_tray():
        ips = win32util.local_ipv4_addresses()
        tip = (
            f"{APP_NAME} 接收端 v{__version__}\n"
            f"保存目录：{config.resolved_save_dir()}\n"
            f"监听端口：{config.port}\n"
            f"本机 IP：{', '.join(ips) if ips else '未识别'}"
        )
        tray.setToolTip(tip)

    def open_folder():
        win32util.open_path(config.resolved_save_dir())

    def change_folder():
        from PySide6.QtWidgets import QFileDialog

        directory = QFileDialog.getExistingDirectory(
            None, "选择截图保存目录", config.resolved_save_dir()
        )
        if directory:
            config.save_dir = directory
            config.save()
            refresh_tray()

    def change_port():
        nonlocal httpd
        text, ok = QInputDialog.getInt(None, "设置端口", "HTTP 服务端口：", int(config.port), 1024, 65535)
        if ok:
            config.port = text
            config.save()
            if httpd is not None:
                httpd.shutdown()
                httpd.server_close()
                httpd = None
            ensure_server()
            refresh_tray()

    def change_token():
        current = config.token or ""
        text, ok = QInputDialog.getText(
            None,
            "设置共享密钥",
            "留空表示不校验。填了以后，截图端必须填一模一样的密钥：",
            text=current,
        )
        if ok:
            config.token = text.strip()
            config.save()
            refresh_tray()
            tray.showMessage(
                APP_NAME,
                "已设置密钥" if config.token else "已取消密钥校验",
                QSystemTrayIcon.Information,
                4000,
            )

    def toggle_autostart():
        enabled = not win32util.is_autostart_enabled(RECEIVER_VALUE_NAME)
        command = f'"{paths.executable_path()}" --receiver'
        ok = win32util.set_autostart(enabled, RECEIVER_VALUE_NAME, command)
        config.auto_start = enabled and ok
        config.save()
        tray.showMessage(
            APP_NAME,
            "已设置开机自启" if config.auto_start else "已取消开机自启",
            QSystemTrayIcon.Information,
            3000,
        )
        refresh_tray()

    def show_info():
        state = ReceiverState(config)
        info = state.info()
        QMessageBox.information(
            None,
            "接收端信息",
            f"设备名：{info['device']}\n"
            f"本机 IP：{', '.join(info['ips']) or '未识别'}\n"
            f"端口：{config.port}\n"
            f"保存目录：{info['save_dir']}\n"
            f"已接收：{info['count']} 张\n\n"
            "在截图端「设置 → 接收方式」里填入上面的 IP 和端口即可。",
        )

    def quit_app():
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if responder is not None:
            responder.stop()
        app.quit()

    menu = QMenu()
    menu.addAction(QAction("打开截图文件夹", menu, triggered=open_folder))
    menu.addAction(QAction("显示接收端信息", menu, triggered=show_info))
    menu.addSeparator()
    menu.addAction(QAction("更改保存目录…", menu, triggered=change_folder))
    menu.addAction(QAction("更改端口…", menu, triggered=change_port))
    menu.addAction(QAction("更改共享密钥…", menu, triggered=change_token))
    autostart_action = QAction("开机自启", menu, checkable=True)
    autostart_action.setChecked(win32util.is_autostart_enabled(RECEIVER_VALUE_NAME))
    autostart_action.triggered.connect(lambda _checked: toggle_autostart())
    menu.addAction(autostart_action)
    menu.addSeparator()
    menu.addAction(QAction("退出", menu, triggered=quit_app))
    tray.setContextMenu(menu)

    tray.activated.connect(
        lambda reason: open_folder() if reason == QSystemTrayIcon.Trigger else None
    )

    ensure_server()
    tray.show()
    refresh_tray()
    bootstrap.log("托盘已显示，进入事件循环")

    # 定期刷新托盘提示里的已接收数量
    timer = QTimer()
    timer.timeout.connect(refresh_tray)
    timer.start(5000)

    code = app.exec()
    bootstrap.log(f"事件循环结束，退出码 {code}")
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="ShotBridge 接收端")
    parser.add_argument("--receiver", action="store_true", help="以接收端身份运行")
    parser.add_argument("--no-tray", action="store_true", help="不显示托盘，仅跑服务")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--dir", default=None, help="截图保存目录")
    args = parser.parse_args(argv)

    from .config import ReceiverConfig

    config = ReceiverConfig.load()
    if args.port:
        config.port = args.port
    if args.dir:
        config.save_dir = os.path.abspath(args.dir)
    config.save()

    if args.no_tray:
        win32util.enable_dpi_awareness()
        httpd, _ = start_server(config)
        responder = discovery.DiscoveryResponder(lambda: ReceiverState(config).info())
        responder.start()
        info = ReceiverState(config).info()
        print(f"{APP_NAME} 接收端已启动：http://{info['ip']}:{config.port}")
        print(f"保存目录：{config.resolved_save_dir()}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            httpd.shutdown()
            responder.stop()
        return 0

    return _receiver_main_gui()


if __name__ == "__main__":
    raise SystemExit(main())
