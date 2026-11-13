# -*- coding: utf-8 -*-
"""
打包驗證用自我測試：WingLightPDF_Core.bin --self-test <結果.json>
不顯示任何視窗（Qt offscreen），用來檢查打包瘦身後是否缺少執行期元件：
1. 建立主視窗、開啟測試 PDF、搜尋文字（Qt 介面 + PyMuPDF）
2. 深淺色主題切換，設定寫進暫存資料夾的 WingLightPDF.json（不碰使用者的設定檔）
3. 匯入所有按需載入的模組（對話框、列印、預設程式註冊）
4. 加入中文文字標註、產生印章圖片（系統字型 + Pillow）
5. 對含繁體中文的測試頁執行 OCR，確認辨識結果為正確的繁體字
結果寫入 JSON 檔；全部通過回傳 0，否則回傳 1。
"""

from __future__ import annotations
import json
import os
import sys
import tempfile
import time
import traceback

SAMPLE_TEXT = "審查會議紀錄 單一車道 ABC 123"
EXPECTED_OCR_WORDS = ["審查會議紀錄", "單一車道", "ABC"]


def _make_sample_pdf(path: str) -> None:
    import fitz
    from core.pdf_engine import get_system_cjk_font_path

    doc = fitz.open()
    page = doc.new_page()
    font_path = get_system_cjk_font_path()
    font = fitz.Font(fontfile=font_path) if font_path else fitz.Font("china-t")
    tw = fitz.TextWriter(page.rect)
    tw.append((60, 120), SAMPLE_TEXT, font=font, fontsize=26)
    tw.write_text(page)
    doc.save(path)
    doc.close()


def run_self_test(out_path: str) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    steps = {}
    tmp_dir = tempfile.mkdtemp(prefix="winglightpdf_selftest_")
    pdf_path = os.path.join(tmp_dir, "selftest.pdf")
    ctx = {}

    def step(name, fn):
        t0 = time.perf_counter()
        try:
            detail = fn()
            steps[name] = {"ok": True, "ms": round((time.perf_counter() - t0) * 1000), "detail": detail}
        except Exception:
            steps[name] = {"ok": False, "ms": round((time.perf_counter() - t0) * 1000), "error": traceback.format_exc()}

    def QApplication_instance():
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            from core.settings import Settings
            from ui import theme
            app = QApplication(sys.argv[:1])
            # 設定檔放暫存資料夾，自我測試不讀也不改使用者的設定
            ctx["settings"] = Settings(base_dir=tmp_dir)
            theme.init(ctx["settings"])
        return app

    def gui():
        from ui.main_window import PDFMainWindow

        _make_sample_pdf(pdf_path)
        ctx["app"] = QApplication_instance()
        win = PDFMainWindow(initial_pdf_path=pdf_path)
        win.show()
        ctx["app"].processEvents()
        win.execute_keyword_search("ABC")
        pages, matches = win.engine.page_count, len(win._search_matches)
        win.engine.is_modified = False
        win.close()
        if pages != 1 or matches < 1:
            raise RuntimeError(f"頁數 {pages}、搜尋結果 {matches}，不符預期")
        return f"開啟 {pages} 頁，搜尋到 {matches} 筆"

    def theme_switch():
        from core.settings import Settings
        from ui import theme
        from ui.main_window import PDFMainWindow

        ctx["app"] = QApplication_instance()
        win = PDFMainWindow(initial_pdf_path=pdf_path)
        win.show()
        start = theme.current()
        other = "light" if start == "dark" else "dark"
        results = [start]
        for name in (other, start):  # 兩次都是真的切換，才會寫進設定檔
            win.act_dark_theme.setChecked(name == "dark")
            ctx["app"].processEvents()
            bg = win.canvas.backgroundBrush().color().name().upper()
            saved = Settings(base_dir=tmp_dir).theme
            if theme.current() != name or bg != theme.color("canvas", name) or saved != name:
                raise RuntimeError(f"切到 {name}：目前 {theme.current()}、畫布 {bg}、設定檔 {saved}")
            if theme.color("bg", name) not in ctx["app"].styleSheet():
                raise RuntimeError(f"切到 {name} 後樣式表沒有換")
            results.append(name)
        win.engine.is_modified = False
        win.close()
        if os.path.dirname(ctx["settings"].path) != tmp_dir:
            raise RuntimeError(f"設定檔不在暫存資料夾：{ctx['settings'].path}")
        return f"{'、'.join(results)}，設定存在暫存資料夾"

    def about():
        from core.version import AUTHOR_URL, VERSION
        from ui.about_dialog import AboutDialog

        ctx["app"] = QApplication_instance()
        dlg = AboutDialog()
        ok = VERSION in dlg.version_label.text() and AUTHOR_URL in dlg.link_label.text() and not dlg.mark.isHidden()
        dlg.close()
        if not ok:
            raise RuntimeError("關於視窗缺少版本、連結或系列標誌（assets 裡的 logos 資料夾有沒有打包進去？）")
        return f"版本 {VERSION}、{AUTHOR_URL}、系列標誌"

    def lazy_modules():
        import ui.dialogs  # noqa: F401
        import register_default  # noqa: F401
        from PySide6.QtPrintSupport import QPrinter  # noqa: F401
        return "ui.dialogs / register_default / QtPrintSupport"

    def text_and_stamp():
        from core.pdf_engine import PDFEngine, generate_stamp_png_bytes

        eng = PDFEngine()
        eng.open_file(pdf_path)
        eng.add_text_annotation_to_page(0, (60, 200), "中文標註測試", record_undo=False)
        png = generate_stamp_png_bytes("核准", "2026-01-01")
        eng.close()
        if not png.startswith(b"\x89PNG"):
            raise RuntimeError("印章圖片不是 PNG")
        return f"印章 PNG {len(png)} bytes"

    def ocr():
        import threading
        import fitz
        import numpy as np
        from core.lazy_workers import _get_or_init_ocr_engine

        doc = fitz.open(pdf_path)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72), alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        doc.close()

        # 與 App 相同：在背景執行緒初始化並辨識，再由另一條執行緒重複使用快取的引擎
        texts, errors = [], []

        def worker():
            try:
                engine = _get_or_init_ocr_engine()
                texts.append((getattr(engine, "engine_name", "?"),
                              "".join(str(t) for _box, t, _s in engine(img)).replace(" ", "")))
            except Exception:
                errors.append(traceback.format_exc())

        for _ in range(2):
            th = threading.Thread(target=worker)
            th.start()
            th.join()
        if errors:
            raise RuntimeError(errors[0])

        engine_name, text = texts[-1]
        # 沒有中文辨識語言的 Windows（例如英文版雲端打包機）只檢查英數字
        cjk_capable = "RapidOCR" in engine_name or "(zh" in engine_name
        expected = EXPECTED_OCR_WORDS if cjk_capable else ["ABC", "123"]
        missing = [w for w in expected if w not in text]
        if missing:
            raise RuntimeError(f"{engine_name} 結果缺少 {missing}：{text}")
        return f"{engine_name}：{text}"

    def single_instance():
        from core.single_instance import pipe_address, send_files, start_server
        from ui.main_window import PDFMainWindow

        address = f"{pipe_address()}-selftest-{os.getpid()}"
        received = []
        if not start_server(address, received.extend):
            raise RuntimeError("無法建立具名管道")
        if not send_files(address, [pdf_path], timeout=5) or received != [pdf_path]:
            raise RuntimeError(f"管道傳送失敗，收到 {received}")

        second = os.path.join(tmp_dir, "selftest_2.pdf")
        _make_sample_pdf(second)
        ctx["app"] = QApplication_instance()
        win = PDFMainWindow(initial_pdf_path=pdf_path)
        win.show()
        PDFMainWindow.open_external_files([second, pdf_path])
        ctx["app"].processEvents()
        tabs = win.doc_tabs.count()
        current = os.path.basename(win.engine.file_path or "")
        for i in range(tabs):
            win.get_doc_tab(i).engine.is_modified = False
        win.close()
        if tabs != 2 or current != "selftest.pdf":
            raise RuntimeError(f"分頁數 {tabs}、目前分頁 {current}，不符預期")
        return "管道傳送正常；新檔加到分頁，重複的檔案切回原分頁"

    step("gui", gui)
    step("theme", theme_switch)
    step("about", about)
    step("lazy_modules", lazy_modules)
    step("single_instance", single_instance)
    step("text_and_stamp", text_and_stamp)
    step("ocr", ocr)

    ok = all(s["ok"] for s in steps.values())
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"ok": ok, "frozen": bool(getattr(sys, "frozen", False)), "steps": steps}, f, ensure_ascii=False, indent=2)
    return 0 if ok else 1
