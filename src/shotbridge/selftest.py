"""无界面自检：不弹窗、不需要桌面处于解锁状态，逐项检查关键链路。

用法（安装后直接跑）：

    ShotBridge.exe --selftest                        # 用当前 client.json 的目标
    ShotBridge.exe --selftest --host 192.168.1.20    # 临时指定接收端
    ShotBridge.exe --selftest --port 8765 --token 1234
    ShotBridge.exe --selftest --no-upload            # 只探测，不上传测试图

结果同时写到 `%LOCALAPPDATA%\\ShotBridge\\logs\\selftest.log`，并在有控制台时打到标准输出。
退出码：0 = 关键能力都正常；1 = 有检查项失败（每项都会写原因）。
"""

from __future__ import annotations

import io
import os
import sys
import time
from typing import Callable, List

from . import APP_TITLE, __version__, bootstrap, capture, config, paths, uploader, win32util

_LINES: List[str] = []


def _line(text: str) -> None:
    _LINES.append(text)
    bootstrap.log("[selftest] " + text)
    # 打包成窗口程序后 sys.stdout 已被 bootstrap 指向同一个日志流，再写一次会重复
    stream = sys.stdout
    if stream is not None and stream is not getattr(bootstrap, "_stream", None):
        try:
            stream.write(text + "\n")
            stream.flush()
        except Exception:
            pass


def _parse_args(argv: List[str]) -> dict:
    opts = {"host": "", "port": 0, "token": None, "upload": True}
    i = 0
    while i < len(argv):
        item = argv[i]
        if item == "--host" and i + 1 < len(argv):
            opts["host"] = argv[i + 1]
            i += 2
            continue
        if item == "--port" and i + 1 < len(argv):
            try:
                opts["port"] = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if item == "--token" and i + 1 < len(argv):
            opts["token"] = argv[i + 1]
            i += 2
            continue
        if item == "--no-upload":
            opts["upload"] = False
        i += 1
    return opts


def _report_path() -> str:
    folder = os.path.join(paths.local_data_dir(), "logs")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        folder = os.environ.get("TEMP", ".")
    return os.path.join(folder, "selftest.log")


def run(argv: List[str]) -> int:
    opts = _parse_args(argv)
    failures = 0
    total = 0

    def check(name: str, fn: Callable[[], str]) -> bool:
        nonlocal failures, total
        total += 1
        try:
            detail = fn()
        except Exception as exc:  # noqa: BLE001 - 自检要把任何异常都变成一行结论
            failures += 1
            _line(f"[失败] {name}：{exc}")
            return False
        _line(f"[正常] {name}：{detail}")
        return True

    started = time.strftime("%Y-%m-%d %H:%M:%S")
    _line("=" * 62)
    _line(f"{APP_TITLE} 自检 @ {started}  版本 {__version__}")
    _line(f"解释器 {sys.version.split()[0]}  frozen={getattr(sys, 'frozen', False)}  exe={paths.executable_path()}")
    _line(f"配置目录 {paths.app_data_dir()}")

    client_cfg = config.ClientConfig.load()

    def _config_check() -> str:
        return (
            f"目标={client_cfg.host or '(未设置)'}:{client_cfg.port} "
            f"密钥={'已设置' if client_cfg.token else '空'} 截图方式={client_cfg.capture_mode}"
        )

    check("读取截图端配置", _config_check)

    def _iface_check() -> str:
        ips = win32util.local_ipv4_addresses()
        if not ips:
            raise RuntimeError("没有找到可用的局域网 IP")
        return ", ".join(ips)

    check("本机局域网地址", _iface_check)

    def _outbox_check() -> str:
        folder = paths.outbox_dir()
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, ".selftest")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        pending = len([n for n in os.listdir(folder) if not n.startswith(".")])
        return f"{folder}（待发 {pending} 张）"

    check("待发队列可读写", _outbox_check)

    def _capture_check() -> str:
        shot = capture.capture_primary_monitor()
        return f"{shot.image.width}x{shot.image.height} {shot.image.mode}"

    screen_ok = check("屏幕截图", _capture_check)
    if not screen_ok:
        _line("        提示：屏幕截图失败最常见原因是桌面已锁定（锁屏/远程桌面断开），解锁后重试即可。")

    def _encode_check() -> str:
        from PIL import Image

        image = Image.new("RGB", (64, 32), (233, 79, 55))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return f"PNG {len(buffer.getvalue())} 字节"

    check("图片编码", _encode_check)

    host = opts["host"] or client_cfg.host
    port = opts["port"] or client_cfg.port
    token = client_cfg.token if opts["token"] is None else opts["token"]

    if not host:
        failures += 1
        total += 1
        _line("[失败] 接收端连通性：还没填接收端 IP（设置里填，或运行时加 --host）")
        receiver_ok = False
    else:
        state = {"ok": False}

        def _ping_check() -> str:
            result = uploader.http_ping(host, port, token)
            if not result.ok:
                raise RuntimeError(result.message)
            state["ok"] = True
            return f"{host}:{port} 设备={result.remote_path}"

        receiver_ok = check(f"接收端连通性（{host}:{port}）", _ping_check)

        if receiver_ok and opts["upload"]:
            def _upload_check() -> str:
                from PIL import Image

                if screen_ok:
                    image = capture.capture_primary_monitor().image
                else:
                    image = Image.new("RGB", (64, 32), (233, 79, 55))
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                stamp = time.strftime("%Y%m%d-%H%M%S")
                result = uploader.http_upload(
                    host, port, token, f"selftest-{stamp}.png", buffer.getvalue(), timeout=20.0
                )
                if not result.ok:
                    raise RuntimeError(result.message)
                return result.remote_path or result.message

            check("上传测试图", _upload_check)
        elif receiver_ok:
            _line("[跳过] 上传测试图：运行时指定了 --no-upload")

    _line("-" * 62)
    if failures:
        _line(f"结论：{total - failures}/{total} 项正常，{failures} 项失败（详见上面的原因）")
    else:
        _line(f"结论：全部 {total} 项检查正常")
    _line("=" * 62)

    report = _report_path()
    try:
        with open(report, "a", encoding="utf-8") as fh:
            fh.write("\n".join(_LINES) + "\n")
        _line(f"报告已追加到：{report}")
    except OSError:
        pass
    return 0 if failures == 0 else 1


def main(argv: List[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    return run(list(argv))


if __name__ == "__main__":
    raise SystemExit(main())
