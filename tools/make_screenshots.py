# -*- coding: utf-8 -*-
"""
README 用的介面截圖：docs/screenshot-light.png、docs/screenshot-dark.png（1280 × 800）。
範例 PDF 由這支程式產生（虛構的「範例道路改善工程」），不含真實案名、地籍或公文字號。
用 QWidget.grab() 抓視窗本身，不抓螢幕，不會抓到蓋在上面的其他視窗。

用法：.venv\\Scripts\\python.exe tools\\make_screenshots.py
"""

from __future__ import annotations
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=gdi")

import fitz  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.pdf_engine import get_system_cjk_font_path  # noqa: E402
from core.settings import Settings  # noqa: E402
from ui import theme  # noqa: E402

A3 = (1191, 842)


def _text(page, font, pos, text, size, color=(0.1, 0.1, 0.1)):
    tw = fitz.TextWriter(page.rect, color=color)
    tw.append(pos, text, font=font, fontsize=size)
    tw.write_text(page)


def _title_block(page, font, title, sheet, total):
    w, h = A3
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(20, 20, w - 20, h - 20))
    shape.draw_rect(fitz.Rect(w - 330, h - 110, w - 20, h - 20))
    for y in (h - 80, h - 50):
        shape.draw_line((w - 330, y), (w - 20, y))
    shape.finish(color=(0.15, 0.15, 0.15), width=1.0)
    shape.commit()
    _text(page, font, (w - 320, h - 88), "範例道路改善工程（虛構範例）", 13)
    _text(page, font, (w - 320, h - 58), title, 15)
    _text(page, font, (w - 320, h - 30), f"比例尺 1/500｜圖號 範例-{sheet:02d}｜第 {sheet}／{total} 張", 10)


def make_plan(path):
    font = fitz.Font(fontfile=get_system_cjk_font_path())
    doc = fitz.open()
    for sheet in range(1, 5):
        page = doc.new_page(width=A3[0], height=A3[1])
        _title_block(page, font, "平面圖", sheet, 4)
        shape = page.new_shape()
        y0 = 330 + sheet * 6
        for off, width in ((-60, 1.2), (-20, 0.6), (20, 0.6), (60, 1.2)):  # 路緣與車道線
            shape.draw_bezier((80, y0 + off), (400, y0 + off - 40), (760, y0 + off + 50), (1100, y0 + off))
            shape.finish(color=(0.15, 0.15, 0.15), width=width, closePath=False,
                         dashes="[8 6] 0" if abs(off) == 20 else None)
        shape.draw_bezier((80, y0), (400, y0 - 40), (760, y0 + 50), (1100, y0))  # 中心線
        shape.finish(color=(0.75, 0.15, 0.12), width=0.8, dashes="[18 5 3 5] 0", closePath=False)
        for i, x in enumerate(range(120, 1100, 140)):  # 樁號
            shape.draw_line((x, y0 - 90), (x, y0 - 75))
            shape.finish(color=(0.2, 0.2, 0.2), width=0.8, closePath=False)
            _text(page, font, (x - 22, y0 - 95), f"{sheet - 1}K+{i * 20:03d}", 9)
        for x, y in ((240, 520), (520, 540), (820, 515)):  # 排水溝與人孔
            shape.draw_circle((x, y), 9)
            shape.finish(color=(0.1, 0.35, 0.7), width=1.0)
        shape.draw_polyline([(150, 180), (150, 120), (138, 140), (162, 140), (150, 120)])  # 指北
        shape.finish(color=(0.1, 0.1, 0.1), width=1.0, closePath=False)
        shape.commit()
        _text(page, font, (144, 196), "N", 12)
        _text(page, font, (80, 610), "圖例：紅色點鏈線為道路中心線，藍色圓為人孔（範例資料，非實際工程）", 10)
    doc.save(path)
    doc.close()


def make_profile(path):
    font = fitz.Font(fontfile=get_system_cjk_font_path())
    doc = fitz.open()
    for sheet in range(1, 3):
        page = doc.new_page(width=A3[0], height=A3[1])
        _title_block(page, font, "縱斷面圖", sheet, 2)
        shape = page.new_shape()
        for x in range(100, 1100, 50):
            shape.draw_line((x, 200), (x, 560))
        for y in range(200, 561, 40):
            shape.draw_line((100, y), (1050, y))
        shape.finish(color=(0.82, 0.82, 0.82), width=0.4, closePath=False)
        shape.draw_polyline([(100, 420), (300, 400), (520, 360), (760, 380), (1050, 330)])
        shape.finish(color=(0.15, 0.15, 0.15), width=1.4, closePath=False)
        shape.commit()
    doc.save(path)
    doc.close()


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="winglightpdf_shots_")
    plan = os.path.join(tmp, "範例道路平面圖.pdf")
    profile = os.path.join(tmp, "範例縱斷面圖.pdf")
    make_plan(plan)
    make_profile(profile)

    app = QApplication(sys.argv[:1])
    theme.init(Settings(base_dir=tmp))  # 設定檔放暫存資料夾，不動使用者的設定
    from ui.main_window import PDFMainWindow

    win = PDFMainWindow(initial_pdf_path=profile)
    win.open_pdf_in_new_tab(plan)
    win.resize(1280, 800)
    win.move(-6000, -6000)
    win.show()
    out_dir = os.path.join(ROOT, "docs")
    os.makedirs(out_dir, exist_ok=True)

    def shoot():
        try:
            for name in ("light", "dark"):
                theme.set_theme(name)
                for _ in range(5):
                    app.processEvents()
                win.canvas.fit_to_page()
                for _ in range(5):
                    app.processEvents()
                path = os.path.join(out_dir, f"screenshot-{name}.png")
                win.grab().save(path)
                print("saved", path)
        finally:
            for i in range(win.doc_tabs.count()):
                win.get_doc_tab(i).engine.is_modified = False
            win.close()
            app.quit()

    QTimer.singleShot(400, shoot)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
