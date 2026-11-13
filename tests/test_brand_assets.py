# -*- coding: utf-8 -*-
"""App 圖示與啟動畫面用的圖（tools/make_brand_assets.py 產生）符合規範 Logos 與 Splash。
執行：python -m unittest discover -s tests -t .
"""

from __future__ import annotations
import unittest
from pathlib import Path

from PIL import IcoImagePlugin, Image

ASSETS = Path(__file__).resolve().parent.parent / "assets"
SPEC_ICO_SIZES = {16, 24, 32, 48, 64, 128, 256}
PRODUCT_PDF = (0xD8, 0x43, 0x3B)


class AppIconTest(unittest.TestCase):
    def test_ico_has_every_spec_size(self) -> None:
        with open(ASSETS / "app_icon.ico", "rb") as f:
            ico = IcoImagePlugin.IcoFile(f)
            sizes = {w for w, h in ico.sizes() if w == h}
            self.assertEqual(sizes, SPEC_ICO_SIZES)
            for s in sorted(SPEC_ICO_SIZES):
                self.assertEqual(ico.getimage((s, s)).size, (s, s))

    def test_logo_is_512_with_transparent_corners(self) -> None:
        with Image.open(ASSETS / "logo.png") as im:
            self.assertEqual(im.size, (512, 512))
            rgba = im.convert("RGBA")
            # 規範的方塊在 120 畫格裡留 4 的邊；靠近角落各取一點
            self.assertEqual(rgba.getpixel((30, 30))[3], 0, "左上是大圓角，角落要透明")
            self.assertEqual(rgba.getpixel((488, 22))[3], 255, "右上幾乎是直角（羽毛形方塊）")
            r, g, b, _ = rgba.getpixel((256, 480))
            self.assertLess(abs(r - PRODUCT_PDF[0]) + abs(g - PRODUCT_PDF[1]) + abs(b - PRODUCT_PDF[2]), 12,
                            "底色要是 product-pdf 紅")


class SplashImageTest(unittest.TestCase):
    def test_bright_and_dim_firefly(self) -> None:
        bright = Image.open(ASSETS / "splash" / "firefly_bright.png").convert("RGB")
        dim = Image.open(ASSETS / "splash" / "firefly_dim.png").convert("RGB")
        self.assertEqual(bright.size, (440, 440))
        self.assertEqual(dim.size, bright.size)
        # 尾巴旁邊的光暈：亮的那張比暗的那張亮，其他地方（臉）一樣
        halo = (220, 400)
        self.assertGreater(sum(bright.getpixel(halo)), sum(dim.getpixel(halo)) + 30)
        face = (220, 185)
        self.assertEqual(bright.getpixel(face), dim.getpixel(face))


if __name__ == "__main__":
    unittest.main()
