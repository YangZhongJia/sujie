"""端到端冒烟测试：截图 → HTTP 上传 → 落盘 → 校验。

运行：
    "C:\\Program Files\\Python314\\python.exe" tests\\smoke_test.py
"""

import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 测试全程把 APPDATA 指到临时目录，绝不动用户真实配置
_SANDBOX_APPDATA = tempfile.mkdtemp(prefix="sb_smoke_appdata_")
os.environ["APPDATA"] = _SANDBOX_APPDATA

sys.path.insert(0, str(ROOT / "src"))

from sujie import capture, discovery, uploader, win32util  # noqa: E402
from sujie.config import ClientConfig, ReceiverConfig, receiver_target  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results = []


SKIPPED = []


def skip(name, reason=""):
    SKIPPED.append(name)
    print(f"[跳过] {name}{('：' + reason) if reason else ''}")


def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"[{status}] {name}" + (f"  —  {detail}" if detail else ""))
    return condition


def main():
    print("=" * 68)
    print("速截 冒烟测试")
    print("=" * 68)

    win32util.enable_dpi_awareness()

    # ---------------------------------------------------------- 显示器枚举
    monitors = win32util.enumerate_monitors()
    check("枚举显示器", len(monitors) >= 1, f"{len(monitors)} 块：{monitors}")

    # -------------------------------------------------------------- 截图
    # 桌面被锁屏（LogonUI 在前台）时 ImageGrab 会抛 OSError，这里降级为跳过，
    # 保证接收端/网络部分仍然能被验证。
    from PIL import Image

    try:
        result = capture.capture_screen()
    except OSError as exc:
        skip("整屏截图", f"截屏不可用（{exc}），桌面可能已锁定")
        result = capture.CaptureResult(image=Image.new("RGB", (800, 600), (40, 40, 40)), rect=(0, 0, 800, 600))
    else:
        check("整屏截图", result.image.width > 0 and result.image.height > 0,
              f"{result.image.width}x{result.image.height}")
        check("整屏截图尺寸与虚拟桌面一致",
              result.image.size == (win32util.virtual_screen_rect()[2] - win32util.virtual_screen_rect()[0],
                                    win32util.virtual_screen_rect()[3] - win32util.virtual_screen_rect()[1]),
              str(result.image.size))

    try:
        primary = capture.capture_primary_monitor()
    except OSError as exc:
        skip("主显示器截图", str(exc))
    else:
        check("主显示器截图", primary.image.width > 0, f"{primary.image.size}")

    try:
        mon = monitors[0]
        region = capture.capture_rect((mon.left + 10, mon.top + 10, mon.left + 210, mon.top + 110))
    except OSError as exc:
        skip("区域截图", str(exc))
    else:
        check("区域截图", region.image.size == (200, 100), str(region.image.size))

    # ------------------------------------------------------------ 编码
    filename, data = "shot-test.png", b""
    import io

    buf = io.BytesIO()
    result.image.save(buf, format="PNG")
    data = buf.getvalue()
    check("PNG 编码", len(data) > 1000, f"{len(data)} 字节")

    # ---------------------------------------------------- HTTP 接收端
    tmpdir = tempfile.mkdtemp(prefix="sb_test_")
    port = 18765
    receiver_config = ReceiverConfig()
    receiver_config.save_dir = tmpdir
    receiver_config.port = port
    receiver_config.token = "test-token"
    receiver_config.subdir_by_date = False

    from sujie.receiver import start_server

    httpd, _ = start_server(receiver_config)
    time.sleep(0.3)
    check("接收端启动", httpd is not None, f"端口 {port}")

    try:
        # ping
        ping = uploader.http_ping("127.0.0.1", port, "test-token")
        check("HTTP /ping", ping.ok, ping.message)

        ping_bad = uploader.http_ping("127.0.0.1", port, "wrong-token")
        check("错误密钥被拒绝", not ping_bad.ok, ping_bad.message)

        # 上传
        up = uploader.http_upload("127.0.0.1", port, "test-token", "hello.png", data)
        check("HTTP 上传", up.ok, up.message)

        landed = os.path.join(tmpdir, os.path.basename(up.remote_path))
        check("文件落盘", os.path.exists(landed), landed)
        if os.path.exists(landed):
            check("落盘内容一致", open(landed, "rb").read() == data)

        # 客户端配置联动
        client_config = ClientConfig()
        client_config.targets = [receiver_target("127.0.0.1", port, "test-token")]
        up2 = uploader.upload_image(client_config, "hello2.png", data)
        check("按配置上传", up2.ok, up2.message)

        # ------------------------------------------------ 多接收端与单独补发
        second_dir = os.path.join(tmpdir, "second")
        second_port = port + 2
        client_config.targets.append(receiver_target("127.0.0.1", second_port, "second-token"))
        fanout = uploader.upload_image(client_config, "fanout.png", data)
        check("多目标部分成功", fanout.successful_targets == 1 and len(fanout.failed_targets) == 1,
              fanout.message)
        first_count = len([name for name in os.listdir(tmpdir) if name.endswith(".png")])
        fanout_outbox = uploader.Outbox(os.path.join(tmpdir, "fanout-outbox"))
        fanout_outbox.add("fanout.png", data, fanout.failed_targets)

        second_config = ReceiverConfig()
        second_config.save_dir = second_dir
        second_config.port = second_port
        second_config.token = "second-token"
        second_config.subdir_by_date = False
        httpd2, _ = start_server(second_config)
        time.sleep(0.2)
        resent = uploader.flush_outbox(client_config, fanout_outbox)
        second_count = len([name for name in os.listdir(second_dir) if name.endswith(".png")])
        first_count_after = len([name for name in os.listdir(tmpdir) if name.endswith(".png")])
        check("失败接收端恢复后补发", resent == 1 and second_count == 1, f"补发={resent} 文件={second_count}")
        check("补发不重复发送给已成功端", first_count_after == first_count, f"{first_count} -> {first_count_after}")
        check("全部目标送达后清空队列", fanout_outbox.count() == 0)

        # --------------------------------------------------------- 发现
        responder = discovery.DiscoveryResponder(
            lambda: {"device": "TEST-PC", "ips": ["127.0.0.1"], "http_port": port}
        )
        started = responder.start()
        check("发现服务启动", started)
        time.sleep(0.3)
        devices = discovery.discover(timeout=2.0)
        found = [d for d in devices if d.get("device") == "TEST-PC"]
        check("局域网发现", bool(found), f"发现 {len(devices)} 个设备")
        responder.stop()

        # ----------------------------------------------------- 离线队列
        outbox = uploader.Outbox(os.path.join(tmpdir, "outbox"))
        outbox.add("queue-me.png", data)
        check("待发队列写入", outbox.count() == 1)
        pending = outbox.pending()
        check("待发队列读取", len(pending) == 1 and pending[0][2] == "queue-me.png")
        outbox.remove(pending[0][0])
        check("待发队列删除", outbox.count() == 0)

        # 配置里的错误主机应当失败
        bad_config = ClientConfig()
        bad_config.targets = [receiver_target("127.0.0.1", 1)]
        bad = uploader.upload_image(bad_config, "x.png", data)
        check("不可达时返回失败", not bad.ok, bad.message)

        # ------------------------------------------- 配置容错（记事本改过的文件）
        appdata = os.path.join(_SANDBOX_APPDATA, "速截")
        os.makedirs(appdata, exist_ok=True)
        if True:
            with open(os.path.join(appdata, "client.json"), "wb") as fh:
                fh.write(b"\xef\xbb\xbf" + json.dumps({"host": "10.0.0.9", "port": 9000}).encode("utf-8"))
            loaded = ClientConfig.load()
            check("旧版单接收端配置能迁移", loaded.targets[0]["host"] == "10.0.0.9" and int(loaded.targets[0]["port"]) == 9000,
                  f"targets={len(loaded.targets)}")
            with open(os.path.join(appdata, "client.json"), "wb") as fh:
                fh.write(json.dumps({"host": "10.0.0.10"}).encode("utf-16"))
            loaded2 = ClientConfig.load()
            check("UTF-16 的配置能读", loaded2.targets[0]["host"] == "10.0.0.10", loaded2.targets[0]["host"])
        check("测试没有写真实 APPDATA",
              os.path.normcase(os.environ["APPDATA"]) == os.path.normcase(_SANDBOX_APPDATA),
              os.environ["APPDATA"])
    finally:
        if "httpd2" in locals():
            httpd2.shutdown()
            httpd2.server_close()
        httpd.shutdown()
        httpd.server_close()

    shutil.rmtree(tmpdir, ignore_errors=True)

    print("=" * 68)
    failed = [r for r in results if r[0] == FAIL]
    print(f"总计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项")
    if SKIPPED:
        print(f"跳过 {len(SKIPPED)} 项（{', '.join(SKIPPED)}）")
    for _, name, detail in failed:
        print(f"  ✗ {name} {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
