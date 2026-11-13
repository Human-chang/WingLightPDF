# -*- coding: utf-8 -*-
"""
從 WingLight 設計規範的 SVG 產生 App 圖示與啟動畫面用的圖（開發時執行一次，產生的檔案跟著程式）：
- assets/logo.png           512px App 圖示（README 用）
- assets/app_icon.ico       16、24、32、48、64、128、256px（執行檔、視窗、工作列）
- assets/splash/firefly_bright.png、firefly_dim.png
                            啟動畫面的螢火蟲，尾巴光暈亮、暗兩張，C# 啟動器交替淡入淡出

來源：assets/logos/winglightpdf.svg、assets/logos/firefly.svg（規範 Logos 群組，沒有修改）。
規範允許 16、24px 拿掉高光和最細的線，讓小尺寸還認得出白色文件。

用法：.venv\\Scripts\\python.exe tools\\make_brand_assets.py
"""

from __future__ import annotations
import io
import os
import re
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ui.theme import svg_pixmap  # noqa: E402  (跟程式裡畫圖示用同一個函式，含 clip-path 的處理)
ASSETS = os.path.join(ROOT, "assets")
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
SPLASH_PX = 440  # 啟動畫面上畫成 220px，備 2 倍給 200% 縮放的螢幕


def render(svg: str, px: int) -> Image.Image:
    img = svg_pixmap(svg, px).toImage()
    buf = QByteArray()
    qbuf = QBuffer(buf)
    qbuf.open(QBuffer.OpenModeFlag.WriteOnly)
    img.save(qbuf, "PNG")
    qbuf.close()
    return Image.open(io.BytesIO(bytes(buf))).convert("RGBA")


def small_icon_svg(svg: str) -> str:
    """16、24px 用：拿掉左上角的高光和文件上的三條細線。"""
    svg = re.sub(r"<circle[^>]*fill-opacity=\"0\.12\"[^>]*></circle>", "", svg)
    svg = re.sub(r"<path d=\"M46 58h26[^>]*></path>", "", svg)
    return svg


def dim_firefly_svg(svg: str) -> str:
    """尾巴的兩圈光暈調暗（亮的那張是規範原圖）。"""
    svg = svg.replace('r="48" fill="#FFC83D" fill-opacity="0.16"', 'r="48" fill="#FFC83D" fill-opacity="0.03"')
    svg = svg.replace('r="34" fill="#FFC83D" fill-opacity="0.28"', 'r="34" fill="#FFC83D" fill-opacity="0.06"')
    return svg


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841 (QPixmap 需要)
    with open(os.path.join(ASSETS, "logos", "winglightpdf.svg"), encoding="utf-8") as f:
        icon_svg = f.read()
    with open(os.path.join(ASSETS, "logos", "firefly.svg"), encoding="utf-8") as f:
        firefly_svg = f.read()

    render(icon_svg, 512).save(os.path.join(ASSETS, "logo.png"))

    small = small_icon_svg(icon_svg)
    assert small != icon_svg, "找不到要在小尺寸拿掉的高光或細線，規範的 SVG 可能改了"
    frames = [render(small if px <= 24 else icon_svg, px) for px in ICO_SIZES]
    ico_path = os.path.join(ASSETS, "app_icon.ico")
    # 每個尺寸都用各自畫好的圖，不讓 Pillow 從大圖縮
    frames[-1].save(ico_path, format="ICO", sizes=[(px, px) for px in ICO_SIZES], append_images=frames[:-1])

    dim = dim_firefly_svg(firefly_svg)
    assert dim != firefly_svg, "找不到螢火蟲尾巴的光暈，規範的 SVG 可能改了"
    os.makedirs(os.path.join(ASSETS, "splash"), exist_ok=True)
    render(firefly_svg, SPLASH_PX).save(os.path.join(ASSETS, "splash", "firefly_bright.png"))
    render(dim, SPLASH_PX).save(os.path.join(ASSETS, "splash", "firefly_dim.png"))

    with Image.open(ico_path) as ico:
        print("app_icon.ico:", sorted(ico.info.get("sizes", [])))
    print("logo.png、splash 兩張已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
