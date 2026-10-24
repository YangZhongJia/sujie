"""生成 README 用的界面截图。

思路：控件（悬浮球/扇形菜单/编辑器/历史/设置）用 Qt offscreen 渲染成
带透明通道的 PNG，再合成到**完全虚构的桌面场景**上——壁纸、任务栏和
"数据后台"窗口全部用 PIL 画出来，数据皆为编造，保证截图不含任何真实
用户信息。既能精确定位控件状态（比如扇形菜单高亮哪个扇区），观感也自然。

用法：
    python tools\\make_docs_shots.py            # 生成全部图片到 docs\\images\\
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_OUT = ROOT / "docs" / "images"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# offscreen 平台不会自己找系统字体，不指定字体目录中文会渲染成方框
_win_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
if _win_fonts.is_dir():
    os.environ.setdefault("QT_QPA_FONTDIR", str(_win_fonts))
_SANDBOX = tempfile.mkdtemp(prefix="sujie_shots_")
os.environ["APPDATA"] = _SANDBOX
os.environ["LOCALAPPDATA"] = str(Path(_SANDBOX) / "local")

sys.path.insert(0, str(ROOT / "src"))

from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray, QPoint, QPointF, QIODevice, QRectF  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402

from sujie import history as history_mod, pinboard, theme  # noqa: E402
from sujie.balloon import FloatingBall  # noqa: E402
from sujie.client import _pil_to_qimage  # noqa: E402
from sujie.config import ClientConfig, receiver_target  # noqa: E402
from sujie.editor import ScreenshotEditor  # noqa: E402
from sujie.radial import RadialMenu  # noqa: E402
from sujie.settings_ui import SettingsDialog  # noqa: E402

MAX_WIDTH = 880
INK = (31, 41, 55)
MUTE = (107, 114, 128)


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    path = _win_fonts / name
    if not path.exists():
        path = _win_fonts / "msyh.ttc"
    return ImageFont.truetype(str(path), size)


# ----------------------------------------------------------------虚构场景
def draw_dashboard(width: int, height: int) -> Image.Image:
    """虚构的「电商数据后台」整窗画面：所有数字、人名、订单号都是编的。"""
    img = Image.new("RGB", (width, height), (245, 246, 248))
    d = ImageDraw.Draw(img)
    scale = width / 1600.0

    def s(v: float) -> int:
        return int(v * scale)

    # 浏览器窗口顶栏
    d.rectangle([0, 0, width, s(56)], fill=(250, 250, 252), outline=(228, 230, 236))
    for i, color in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
        d.ellipse([s(18) + i * s(22), s(20), s(30) + i * s(22), s(32)], fill=color)
    d.rounded_rectangle([s(110), s(14), width - s(220), s(42)], radius=s(14),
                        fill=(240, 241, 245))
    d.text((s(130), s(21)), "shop-admin.example.local/overview", font=_font(s(14)), fill=MUTE)

    # 左侧导航
    side = s(230)
    d.rectangle([0, s(56), side, height], fill=(255, 255, 255))
    d.text((s(26), s(84)), "数商管理后台", font=_font(s(19), True), fill=INK)
    menus = ("数据概览", "订单管理", "商品管理", "用户分析", "营销中心", "系统设置")
    for i, name in enumerate(menus):
        y = s(140) + i * s(46)
        if i == 0:
            d.rounded_rectangle([s(16), y, side - s(16), y + s(38)], radius=s(8),
                                fill=(239, 246, 255))
            d.text((s(38), y + s(9)), name, font=_font(s(15), True), fill=(37, 99, 235))
        else:
            d.text((s(38), y + s(9)), name, font=_font(s(15)), fill=MUTE)
            d.rounded_rectangle([s(20), y + s(12), s(28), y + s(24)], radius=s(3),
                                fill=(217, 219, 226))

    # 顶部页头
    d.text((side + s(32), s(80)), "数据概览", font=_font(s(22), True), fill=INK)
    d.text((side + s(32), s(116)), "更新于 14:32 · 数据每 5 分钟自动刷新", font=_font(s(13)), fill=MUTE)
    d.rounded_rectangle([width - s(230), s(82), width - s(40), s(118)], radius=s(18),
                        fill=(240, 241, 245))
    d.text((width - s(214), s(90)), "搜索订单 / 商品 / 用户…", font=_font(s(13)), fill=MUTE)
    d.ellipse([width - s(32), s(86), width - s(4), s(114)], fill=(37, 99, 235))

    # 指标卡
    cards = (
        ("今日订单", "1,284", "+12.4%", (22, 163, 74)),
        ("今日销售额", "¥52,360", "+8.2%", (22, 163, 74)),
        ("支付转化率", "3.6%", "-0.4%", (220, 38, 38)),
        ("新用户", "862", "+15.7%", (22, 163, 74)),
    )
    card_w, card_h = (width - side - s(32) * 2 - s(20) * 3) // 4, s(120)
    for i, (label, value, delta, color) in enumerate(cards):
        x = side + s(32) + i * (card_w + s(20))
        y = s(150)
        d.rounded_rectangle([x, y, x + card_w, y + card_h], radius=s(12),
                            fill=(255, 255, 255), outline=(233, 235, 240))
        d.text((x + s(18), y + s(16)), label, font=_font(s(13)), fill=MUTE)
        d.text((x + s(18), y + s(42)), value, font=_font(s(26), True), fill=INK)
        d.text((x + s(18), y + s(86)), delta + " 较昨日", font=_font(s(12)), fill=color)

    # 柱状图卡
    gx, gy = side + s(32), s(300)
    gw, gh = width - side - s(32) * 2 - s(380), s(330)
    d.rounded_rectangle([gx, gy, gx + gw, gy + gh], radius=s(12),
                        fill=(255, 255, 255), outline=(233, 235, 240))
    d.text((gx + s(22), gy + s(18)), "近 7 日销售趋势", font=_font(s(16), True), fill=INK)
    d.text((gx + s(22), gy + s(48)), "单位：万元", font=_font(s(12)), fill=MUTE)
    bars = (34, 52, 41, 66, 58, 82, 91)
    plot_x, plot_y = gx + s(60), gy + s(90)
    plot_w, plot_h = gw - s(100), gh - s(150)
    for i, v in enumerate(bars):
        bw = plot_w // (len(bars) * 2)
        bx = plot_x + i * plot_w // len(bars) + bw // 2
        bh = int(plot_h * v / 100)
        color = (59, 130, 246) if i < 5 else (37, 99, 235)
        d.rounded_rectangle([bx, plot_y + plot_h - bh, bx + bw, plot_y + plot_h],
                            radius=s(3), fill=color)
        d.text((bx, plot_y + plot_h + s(10)),
               f"10-{18 + i}", font=_font(s(11)), fill=MUTE)

    # 订单表
    tx, ty = gx + gw + s(24), s(300)
    tw, th = width - s(40) - tx, s(330)
    d.rounded_rectangle([tx, ty, tx + tw, ty + th], radius=s(12),
                        fill=(255, 255, 255), outline=(233, 235, 240))
    d.text((tx + s(22), ty + s(18)), "最近订单", font=_font(s(16), True), fill=INK)
    heads = ("订单号", "客户", "金额", "状态")
    cols = (tx + s(22), tx + s(150), tx + s(240), tx + s(330))
    for text, cx in zip(heads, cols):
        d.text((cx, ty + s(56)), text, font=_font(s(12), True), fill=MUTE)
    rows = (
        ("SJ-1024-0392", "张**", "¥1,299", "已完成"),
        ("SJ-1024-0391", "李**", "¥386", "已发货"),
        ("SJ-1024-0390", "王**", "¥2,150", "待付款"),
        ("SJ-1024-0389", "赵**", "¥98", "已完成"),
        ("SJ-1024-0388", "陈**", "¥560", "已发货"),
    )
    for i, row in enumerate(rows):
        ry = ty + s(88) + i * s(44)
        d.line([tx + s(16), ry - s(8), tx + tw - s(16), ry - s(8)], fill=(240, 241, 245))
        for text, cx in zip(row, cols):
            d.text((cx, ry), text, font=_font(s(13)), fill=INK)
    status_pill = {"已完成": (236, 253, 245), "已发货": (232, 240, 254), "待付款": (255, 247, 237)}
    for i, row in enumerate(rows):
        ry = ty + s(88) + i * s(44)
        d.rounded_rectangle([cols[3] - s(8), ry - s(4), cols[3] + s(64), ry + s(22)],
                            radius=s(12), fill=status_pill[row[3]])

    return img


def draw_wallpaper(width: int, height: int) -> Image.Image:
    """虚构桌面：渐变壁纸 + 装饰圆 + 底部任务栏。"""
    img = Image.new("RGB", (width, height))
    top, bottom = (21, 46, 89), (46, 94, 152)
    for y in range(height):
        t = y / height
        img.paste(tuple(int(a + (b - a) * t) for a, b in zip(top, bottom)), (0, y, width, y + 1))
    d = ImageDraw.Draw(img, "RGBA")
    for cx, cy, r, alpha in ((width - 260, 190, 300, 16), (170, height - 240, 340, 13),
                             (width // 2 + 180, height - 90, 240, 10)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, alpha))

    bar = 48
    d.rectangle([0, height - bar, width, height], fill=(18, 24, 38))
    d.rounded_rectangle([14, height - bar + 10, 38, height - bar + 34], radius=6,
                        fill=(37, 99, 235))
    for i in range(4):
        for j in range(2):
            d.rectangle([19 + i * 5, height - bar + 15 + j * 5,
                         22 + i * 5, height - bar + 18 + j * 5], fill=(255, 255, 255))
    colors = ((52, 120, 246), (74, 160, 90), (222, 122, 46), (140, 94, 210), (64, 150, 160))
    for i, color in enumerate(colors):
        cx = 70 + i * 46
        d.rounded_rectangle([cx, height - bar + 11, cx + 28, height - bar + 39],
                            radius=8, fill=color)
    d.text((width - 96, height - bar + 14), "14:35", font=_font(15), fill=(226, 232, 240))
    return img


def compose_desktop(width: int, height: int) -> Image.Image:
    """壁纸 + 一扇虚构后台窗口（带阴影），作为悬浮球截图的底。"""
    scene = draw_wallpaper(width, height).convert("RGBA")
    app = draw_dashboard(width - 360, height - 230)
    app = app.resize((int(app.width * 0.94), int(app.height * 0.94)), Image.LANCZOS)
    ax, ay = 150, 66
    shadow = Image.new("RGBA", (app.width + 60, app.height + 60), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [30, 34, shadow.width - 6, shadow.height - 6], radius=14, fill=(0, 0, 0, 110))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    scene.alpha_composite(shadow, (ax - 30, ay - 30))
    scene.alpha_composite(app.convert("RGBA"), (ax, ay))
    return scene


# ----------------------------------------------------------------控件渲染
def qpixmap_to_pil(pixmap: QPixmap) -> Image.Image:
    buffer = QByteArray()
    device = QBuffer(buffer)
    device.open(QIODevice.WriteOnly)
    pixmap.save(device, "PNG")
    device.close()
    return Image.open(io.BytesIO(bytes(buffer))).convert("RGBA")


def save(img: Image.Image, name: str) -> None:
    if img.width > MAX_WIDTH:
        ratio = MAX_WIDTH / img.width
        img = img.resize((MAX_WIDTH, max(1, int(img.height * ratio))), Image.LANCZOS)
    img.convert("RGB").save(_OUT / name, optimize=True)
    print(f"  {name}: {img.width}x{img.height}")


def main() -> int:
    _OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    theme.apply_theme(app)

    width, height = 1920, 1080
    print(f"合成虚构桌面 {width}x{height}（不含任何真实信息）")

    # ------------------------------------------------------------ 悬浮球 + 扇形
    config = ClientConfig()
    ball = FloatingBall(config)
    ball_pm = qpixmap_to_pil(ball.grab())

    menu = RadialMenu(accent="#e94f37")
    center = QPoint(500, 400)
    menu.open_at(center, 132)
    menu.update_cursor(QPoint(center.x(), center.y() - 110))  # 高亮「截图」扇区
    menu_pm = qpixmap_to_pil(menu.grab())
    menu.close_menu()

    back = compose_desktop(width, height).crop((width - 820, 0, width, 560)).copy()

    def paste_ball(canvas: Image.Image, bx: int, by: int) -> tuple[int, int]:
        canvas.alpha_composite(ball_pm, (bx, by))
        return bx + ball_pm.width // 2, by + ball_pm.height // 2

    # 图 1：悬浮球停在桌面
    shot_ball = back.copy()
    paste_ball(shot_ball, back.width - 140, 44)
    save(shot_ball, "ball-desktop.png")

    # 图 2：长按弹出扇形菜单（小球 + 菜单合成）
    # 小球要离边足够远，半径 132 的菜单才不会被画布裁掉
    shot_radial = back.copy()
    bcx, bcy = paste_ball(shot_radial, back.width - 240, 170)
    mx = bcx - menu_pm.width // 2
    my = bcy - menu_pm.height // 2
    shot_radial.alpha_composite(menu_pm, (mx, my))
    save(shot_radial, "radial-menu.png")

    # 图 3：贴图钉在桌面上（贴图内容 = 后台图表区的「截图」）
    dash = draw_dashboard(width, height)
    chart = dash.crop((int(width * 0.17), int(height * 0.31),
                       int(width * 0.70), int(height * 0.60))).copy()
    chart = chart.resize((int(chart.width * 0.9), int(chart.height * 0.9)), Image.LANCZOS)
    pin_qpm = QPixmap.fromImage(_pil_to_qimage(chart))
    pin = pinboard.PinWindow(pin_qpm, QPoint(120, 160))
    pin_pm = qpixmap_to_pil(pin.grab())
    pin.close()
    shot_pin = back.copy()
    shot_pin.alpha_composite(pin_pm, (40, 40))
    save(shot_pin, "pin.png")

    # ------------------------------------------------------------ 编辑器
    editor = ScreenshotEditor(_pil_to_qimage(dash))
    canvas = editor.canvas
    canvas._add_action({"kind": "arrow", "start": QPointF(width * 0.36, height * 0.20),
                        "end": QPointF(width * 0.50, height * 0.155)})
    canvas._add_action({"kind": "rect", "start": QPointF(width * 0.60, height * 0.30),
                        "end": QPointF(width * 0.86, height * 0.56)})
    canvas._add_action({"kind": "text", "point": QPointF(width * 0.60, height * 0.61),
                        "text": "周五周六销量明显上涨"})
    canvas._add_action({"kind": "mosaic",
                        "rect": QRectF(width * 0.415, height * 0.36,
                                       width * 0.035, height * 0.24).toAlignedRect()})
    editor.resize(1040, 760)
    save(qpixmap_to_pil(editor.grab()), "editor.png")

    # ------------------------------------------------------------ 最近记录
    store = history_mod.History(limit=50)
    buf = io.BytesIO()
    small = dash.resize((900, int(height * 900 / width)), Image.LANCZOS)
    small.save(buf, format="PNG")
    payload = buf.getvalue()
    store.add_image("shot-销售周报.png", payload, ["192.168.1.20", "192.168.1.99"],
                    True, r"\\书房台式机\图片\速截\2026-10-24", "已发送到 2/2 个接收端")
    store.add_image("shot-待付款订单.png", payload, ["192.168.1.20"], True, "",
                    "已发送到 1/1 个接收端")
    video = Path(_SANDBOX) / "rec-后台操作演示.mp4"
    video.write_bytes(b"\x00\x00\x00\x20ftypisom" + b"\x00" * 96)
    store.add_video(video, ["192.168.1.99"], True, "", "已发送到 1/1 个接收端")
    doc = Path(_SANDBOX) / "商品清单-10月.xlsx"
    doc.write_bytes(b"PK\x03\x04" + b"\x00" * 64)
    store.add_file(doc, ["192.168.1.20", "192.168.1.99"], True, "", "已发送到 2/2 个接收端")

    dialog = history_mod.HistoryDialog(store)
    dialog.resize(800, 560)
    save(qpixmap_to_pil(dialog.grab()), "history.png")

    # ------------------------------------------------------------ 设置页
    cfg = ClientConfig()
    cfg.targets = [
        receiver_target("192.168.1.20", 8765, "", "书房台式机"),
        receiver_target("192.168.1.99", 8765, "share-key", "笔记本"),
    ]
    settings = SettingsDialog(cfg)
    settings.resize(880, 660)
    tabs = settings.findChild(QTabWidget)
    tabs.setCurrentIndex(0)
    save(qpixmap_to_pil(settings.grab()), "settings-receivers.png")
    tabs.setCurrentIndex(1)
    save(qpixmap_to_pil(settings.grab()), "settings-capture.png")

    print("完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
