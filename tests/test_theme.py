# -*- coding: utf-8 -*-
"""深淺色主題與設定檔。執行：python -m unittest discover -s tests -t ."""

from __future__ import annotations
import json
import os
import re
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.settings import CONFIG_NAME, Settings  # noqa: E402
from ui import theme  # noqa: E402


class SettingsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_no_file_means_follow_windows(self) -> None:
        self.assertIsNone(Settings(base_dir=self.dir).theme)

    def test_roundtrip_keeps_other_keys(self) -> None:
        with open(os.path.join(self.dir, CONFIG_NAME), "w", encoding="utf-8") as f:
            json.dump({"之後的設定": [1, 2]}, f)
        s = Settings(base_dir=self.dir)
        s.theme = "dark"
        s.save()
        again = Settings(base_dir=self.dir)
        self.assertEqual(again.theme, "dark")
        self.assertEqual(again.data["之後的設定"], [1, 2])

    def test_unknown_theme_is_ignored(self) -> None:
        with open(os.path.join(self.dir, CONFIG_NAME), "w", encoding="utf-8") as f:
            json.dump({"theme": "blue"}, f)
        self.assertIsNone(Settings(base_dir=self.dir).theme)

    def test_broken_file_falls_back(self) -> None:
        with open(os.path.join(self.dir, CONFIG_NAME), "w", encoding="utf-8") as f:
            f.write("{不是 JSON")
        s = Settings(base_dir=self.dir)
        self.assertIsNone(s.theme)
        s.theme = "light"
        s.save()  # 壞掉的檔案直接蓋掉
        self.assertEqual(Settings(base_dir=self.dir).theme, "light")


class StylesheetTest(unittest.TestCase):
    def test_every_token_is_filled_in(self) -> None:
        for name in theme.THEMES:
            qss = theme.stylesheet(name)
            self.assertIsNone(re.search(r"@[a-z]", qss), f"{name} 還有沒代入的色票")

    def test_each_theme_uses_its_own_colors(self) -> None:
        light, dark = theme.stylesheet("light"), theme.stylesheet("dark")
        self.assertIn("#F6F5F3", light)
        self.assertNotIn("#F6F5F3", dark)
        self.assertIn("#1C1B1A", dark)
        self.assertIn(theme.T["accent"][1], dark)

    def test_icon_recolor_keeps_stroke_width(self) -> None:
        svg = theme.icon_svg("chevron-down", "#2B55D4", size=14, rotate=90)
        self.assertIn('stroke="#2B55D4"', svg)
        self.assertIn('stroke-width="1.75"', svg)  # 只換圖示大小，筆畫寬度不能跟著變
        self.assertIn('width="14"', svg)
        self.assertIn('rotate(90 12 12)', svg)
        self.assertNotIn("#77726A", svg)

    def test_tokens_have_light_and_dark(self) -> None:
        for name, value in theme.T.items():
            self.assertEqual(len(value), 2, name)
            for c in value:
                self.assertRegex(c, r"^#[0-9A-F]{6}$", name)


class SetThemeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])

    def test_switch_saves_and_notifies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            theme.init(Settings(base_dir=tmp))
            start = theme.current()
            other = "light" if start == "dark" else "dark"
            heard = []
            theme.signals().changed.connect(heard.append)
            try:
                theme.set_theme(other)
                self.assertEqual(theme.current(), other)
                self.assertEqual(Settings(base_dir=tmp).theme, other)
                self.assertIn(theme.color("bg", other), self.app.styleSheet())
                theme.set_theme(other)  # 已經是這個主題：不重複通知
                self.assertEqual(heard, [other])
            finally:
                theme.signals().changed.disconnect(heard.append)
                theme.set_theme(start)


if __name__ == "__main__":
    unittest.main()
