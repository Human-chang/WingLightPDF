# -*- coding: utf-8 -*-
"""照 WingLight 設計規範檢查介面：不寫 emoji、圖示檔都在、選單有快速鍵字母、關於視窗、狀態列。
執行：python -m unittest discover -s tests -t .
"""

from __future__ import annotations
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from core.settings import Settings  # noqa: E402
from core.version import AUTHOR, AUTHOR_URL, VERSION  # noqa: E402
from ui import theme  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SOURCES = sorted(ROOT.glob("ui/*.py")) + sorted(ROOT.glob("core/*.py")) + [ROOT / "main.py"]
# emoji、箭頭、幾何圖形、打勾叉叉：介面文字只允許 ｜ … ／ （）（規範 Icons）
FORBIDDEN = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿←-⇿⏩-⏺■-◿️]")
ICON_USE = re.compile(r"""(?:bind_icon\([^,()]+,\s*|theme\.icon\(|_icon_button\(|_menu_button\([^,]+,\s*|icon=)["']([\w-]+)["']""")


class SourceTextTest(unittest.TestCase):
    def test_no_emoji_or_symbols_in_source(self) -> None:
        hits = []
        for path in SOURCES:
            for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if FORBIDDEN.search(line):
                    hits.append(f"{path.relative_to(ROOT)}:{no}: {line.strip()[:80]}")
        self.assertEqual(hits, [], "\n".join(hits))

    def test_every_icon_name_has_a_file(self) -> None:
        names = set()
        for path in SOURCES:
            names.update(ICON_USE.findall(path.read_text(encoding="utf-8")))
        names.discard("")
        self.assertGreater(len(names), 10)
        missing = sorted(n for n in names if not (ROOT / "assets" / "icons" / f"{n}.svg").exists())
        self.assertEqual(missing, [])


class _AppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication(sys.argv[:1])
        cls.tmp = tempfile.TemporaryDirectory()
        theme.init(Settings(base_dir=cls.tmp.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()


class MenuTest(_AppTest):
    def test_every_menu_item_has_an_access_key(self) -> None:
        from ui.main_window import PDFMainWindow

        win = PDFMainWindow()
        try:
            problems = []
            for top in win.menuBar().actions():
                self.assertRegex(top.text(), r"\(&[A-Z]\)$", top.text())
                letters = []
                for act in top.menu().actions():
                    if act.isSeparator():
                        continue
                    m = re.search(r"\(&([A-Z])\)", act.text())
                    if not m:
                        problems.append(f"{top.text()}：{act.text()} 沒有快速鍵字母")
                    else:
                        letters.append(m.group(1))
                dup = {x for x in letters if letters.count(x) > 1}
                if dup:
                    problems.append(f"{top.text()} 的快速鍵字母重複：{sorted(dup)}")
            self.assertEqual(problems, [])
            titles = [a.text() for a in win.menuBar().actions()]
            self.assertIn("檢視(&V)", titles)
            self.assertIn("說明(&H)", titles)
        finally:
            win.engine.is_modified = False
            win.close()


class AboutDialogTest(_AppTest):
    def test_shows_version_author_and_link(self) -> None:
        from ui.about_dialog import AboutDialog

        dlg = AboutDialog()
        self.assertIn(VERSION, dlg.version_label.text())
        texts = " ".join(w.text() for w in dlg.findChildren(type(dlg.version_label)))
        self.assertIn(AUTHOR, texts)
        self.assertIn(f'href="{AUTHOR_URL}"', dlg.link_label.text())
        self.assertTrue(dlg.link_label.openExternalLinks())
        self.assertFalse(dlg.mark.isHidden(), "系列標誌沒有載入")
        dlg.close()


class StatusLineTest(_AppTest):
    def test_each_kind_shows_icon_or_dot(self) -> None:
        from ui.status_line import StatusLine

        line = StatusLine()
        line.set_busy("辨識中")
        self.assertFalse(line.dot.isHidden())
        line.setText("正在辨識第 2／10 頁")  # 背景工作回報進度：還是處理中
        self.assertEqual(line.kind, "busy")
        for kind in ("ok", "warn", "error"):
            line.show_status("訊息", kind)
            self.assertTrue(line.dot.isHidden())
            self.assertFalse(line.icon_label.isHidden(), kind)
            self.assertFalse(line.icon_label.pixmap().isNull(), kind)
        line.show_status("一般說明", "info")
        self.assertTrue(line.icon_label.isHidden())

    def test_dot_is_steady_when_not_animating(self) -> None:
        from ui.status_line import GlowDot

        dot = GlowDot()
        self.assertEqual(dot.level(), 1.0)


if __name__ == "__main__":
    unittest.main()
