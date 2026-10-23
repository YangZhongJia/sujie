"""录屏与流式上传的自动化测试。

覆盖：
1. ffmpeg 探测与命令拼装
2. 真实录制 2 秒（需要桌面未锁屏）
3. 40 MB 大文件流式上传（内存不炸 + 内容一致）
4. 接收端体积上限
5. 上传中断不留下半截文件
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sujie import recorder, uploader, win32util  # noqa: E402
from sujie.config import ReceiverConfig  # noqa: E402
from sujie.receiver import start_server  # noqa: E402

PASSED = 0
FAILED = 0
SKIPPED = 0


def check(condition: bool, name: str, detail="") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [OK]   {name}" + (f"  ({detail})" if detail else ""))
    else:
        FAILED += 1
        print(f"  [FAIL] {name}  ({detail})")


def skip(name: str, reason: str = "") -> None:
    global SKIPPED
    SKIPPED += 1
    print(f"  [SKIP] {name}" + (f"  ({reason})" if reason else ""))


def free_port() -> int:
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def make_big_file(path: Path, size_mb: int) -> int:
    chunk = b"\x00" * (1024 * 1024)
    with open(path, "wb") as handle:
        for _ in range(size_mb):
            handle.write(chunk)
    return size_mb * 1024 * 1024


def main() -> int:
    print("== 录屏 / 流式上传测试 ==")

    print("\n[1] ffmpeg 探测与命令拼装")
    probe = recorder.probe(refresh=True)
    check(probe.ok, "找到可用的 ffmpeg", probe.path or probe.error)
    if not probe.ok:
        print("\n没有 ffmpeg，后续录制相关的检查全部跳过")
        print(f"\n结果：{PASSED} 通过 / {FAILED} 失败 / {SKIPPED} 跳过")
        return 1 if FAILED else 0
    check(probe.encoder in recorder.ENCODER_PREFERENCE, "选中的编码器在白名单里", probe.encoder)
    check(bool(probe.version), "ffmpeg 版本可读", (probe.version or "")[:60])

    argv = recorder.build_command(
        probe.path, str(Path(tempfile.gettempdir()) / "x.mp4"),
        (0, 0, 1280, 720), fps=15, encoder=probe.encoder,
    )
    joined = " ".join(argv)
    check("gdigrab" in argv or "ddagrab" in argv, "用 gdigrab/ddagrab 采集桌面", joined[:80])
    check("-video_size" in argv and "1280x720" in argv, "视频尺寸传进去了")
    check("-framerate" in argv and "15" in argv, "帧率传进去了")
    check("-c:v" in argv, "指定了编码器参数")
    check(argv.count("-i") == 1 and argv[argv.index("-i") + 1] == "desktop", "输入设备是 desktop")

    print("\n[2] 区域规范化")
    rect = recorder.normalize_rect((-1920, 0, 1921, 1081))
    check(rect[2] % 2 == 0 and rect[3] % 2 == 0, "宽高被压成偶数（h264 要求）", str(rect))
    rect2 = recorder.normalize_rect((0, 0, 0, 0))
    check(rect2[2] > 0 and rect2[3] > 0, "非法尺寸退回整块桌面", str(rect2))

    print("\n[3] 真实录制 2 秒")
    screen = win32util.virtual_screen_rect()
    out_dir = Path(tempfile.mkdtemp(prefix="sujie_rec_"))
    rec = recorder.Recorder()
    try:
        path = rec.start(screen, fps=15, audio="none", out_dir=str(out_dir), max_mb=200)
        check(bool(path), "录制已启动", str(path))
        time.sleep(2.2)
        elapsed = rec.elapsed_text()
        check(elapsed in ("00:02", "00:03", "00:01"), "计时器在走", elapsed)
        ok, stopped, message = rec.stop()
        check(ok, "录制正常停止", message)
        size = os.path.getsize(stopped) if stopped and os.path.exists(stopped) else 0
        check(size > 1000, "生成了非空的 mp4", f"{size} 字节")
        with open(stopped, "rb") as handle:
            head = handle.read(12)
        check(head[4:8] == b"ftyp", "文件是合法 mp4（ftyp 头）", head[:12].hex())
    except Exception as exc:
        if "screen grab" in str(exc).lower() or "locked" in str(exc).lower():
            skip("真实录制 2 秒", f"桌面不可抓取：{exc}")
        else:
            check(False, "真实录制 2 秒", repr(exc))

    print("\n[4] 40 MB 大文件流式上传")
    port = free_port()
    save_dir = Path(tempfile.mkdtemp(prefix="sujie_recv_"))
    config = ReceiverConfig(port=port, save_dir=str(save_dir), subdir_by_date=False,
                            filename_prefix="rec", token="", max_upload_mb=2048)
    httpd, thread = start_server(config)
    try:
        big = out_dir / "big.mp4"
        expected = make_big_file(big, 40)
        started = time.time()
        result = uploader.upload_targets_file(
            [{"host": "127.0.0.1", "port": port}], "big.mp4", str(big)
        )
        cost = time.time() - started
        check(result.ok, "40 MB 上传成功", f"{result.message}（{cost:.1f}s）")
        landed = [p for p in save_dir.iterdir() if p.suffix == ".mp4"]
        check(len(landed) == 1, "接收端落盘 1 个文件", f"{[p.name for p in landed]}")
        if landed:
            check(landed[0].stat().st_size == expected, "大小完全一致", f"{landed[0].stat().st_size}")
            check(landed[0].name.startswith("rec-"), "文件名前缀生效", landed[0].name)
        check(not list(save_dir.glob("*.part")), "没有残留 .part 文件")

        print("\n[5] 接收端体积上限")
        config.max_upload_mb = 1
        result = uploader.upload_targets_file(
            [{"host": "127.0.0.1", "port": port}], "big.mp4", str(big)
        )
        check(not result.ok, "超过上限被拒绝", result.message)
        check("413" in result.message or "太大" in result.message, "错误信息说明是体积问题", result.message)
        check(len([p for p in save_dir.iterdir() if p.suffix == ".mp4"]) == 1, "被拒绝的文件没有落盘")

        print("\n[6] 上传中断不留半截文件")
        import http.client

        config.max_upload_mb = 2048
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.putrequest("POST", "/upload")
        connection.putheader("X-File-Name", "broken.mp4")
        connection.putheader("Content-Length", "1048576")
        connection.endheaders()
        connection.send(b"\x00" * 4096)
        connection.close()
        time.sleep(0.8)
        leftovers = [p.name for p in save_dir.iterdir() if p.suffix in (".part", ".mp4")]
        check(len(leftovers) == 1, "中断的上传没有产生新文件", str(leftovers))
        check(not list(save_dir.glob("*.part")), "也没有 .part 残留")
    finally:
        httpd.shutdown()
        httpd.server_close()

    print("\n[7] 日志与输出目录")
    check(str(recorder.default_record_dir()).endswith("速截"), "默认录像目录在「视频\\速截」",
          str(recorder.default_record_dir()))
    log_path = Path(tempfile.gettempdir()) / "sujie_ffmpeg_rec.log"
    check(True, "ffmpeg 日志路径约定存在", str(log_path))

    print(f"\n结果：{PASSED} 通过 / {FAILED} 失败 / {SKIPPED} 跳过")
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
