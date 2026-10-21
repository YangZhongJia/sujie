"""生成应用图标 assets/shotbridge.ico（多尺寸），供 PyInstaller 与安装包使用。"""

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "assets"
OUT = OUT_DIR / "shotbridge.ico"

RED = (233, 79, 55)
DARK = (176, 48, 30)
WHITE = (255, 255, 255)


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size

    # 圆形底 + 径向渐变近似（用同心圆叠加）
    for i in range(s // 2, 0, -1):
        t = i / (s / 2)
        color = tuple(
            int(DARK[k] + (RED[k] - DARK[k]) * (1 - t) ** 0.6) for k in range(3)
        )
        d.ellipse([s / 2 - i, s / 2 - i, s / 2 + i, s / 2 + i], fill=color + (255,))

    # 白色描边
    d.ellipse([1, 1, s - 2, s - 2], outline=WHITE + (230,), width=max(1, s // 24))

    # 相机机身
    bw, bh = s * 0.46, s * 0.33
    x0, y0 = (s - bw) / 2, (s - bh) / 2 + s * 0.02
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=max(1, s // 14), fill=WHITE + (255,))
    # 镜头
    r = bw * 0.17
    cx, cy = x0 + bw * 0.5, y0 + bh * 0.5
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=RED + (255,))
    # 取景器凸起
    d.rounded_rectangle(
        [x0 + bw * 0.30, y0 - s * 0.045, x0 + bw * 0.55, y0 + s * 0.01],
        radius=max(1, s // 20),
        fill=WHITE + (255,),
    )
    return img


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [render(size) for size in sizes]
    images[-1].save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    # 同时留一张 png，方便文档使用
    images[-1].save(OUT_DIR / "shotbridge.png")
    print(f"已生成 {OUT} ({OUT.stat().st_size} 字节)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
