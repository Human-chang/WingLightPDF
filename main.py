# -*- coding: utf-8 -*-
"""
WingLightPDF — 輕快免安裝PDF檢視與編輯工具
啟動入口：
- 支援命令列傳入一或多個 PDF 檔案路徑（可直接設為 Windows 預設 PDF 開啟程式）
- 支援多 PDF 同視窗分頁 & 自由拖拉拆出/合併視窗
- 啟動時僅載入基礎檢視核心，OCR 與壓縮最佳化皆為選用按需載入
"""

import sys
import os
import time


def _resolve_icon_path() -> str:
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
        cand1 = os.path.join(base, "assets", "app_icon.ico")
        if os.path.exists(cand1):
            return cand1
        cand2 = os.path.join(getattr(sys, "_MEIPASS", base), "assets", "app_icon.ico")
        return cand2
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "app_icon.ico")


def main() -> None:
    if "--self-test" in sys.argv:
        # 打包驗證：WingLightPDF_Core.bin --self-test <結果.json>（不顯示視窗）
        from core.selftest import run_self_test
        idx = sys.argv.index("--self-test")
        out_path = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "selftest_result.json"
        sys.exit(run_self_test(os.path.abspath(out_path)))

    t0 = time.perf_counter()
    cli_files = [
        os.path.abspath(arg)
        for arg in sys.argv[1:]
        if not arg.startswith("-") and os.path.exists(arg) and arg.lower().endswith(".pdf")
    ]

    # 已經有 WingLightPDF 在執行：把檔案交給它開在分頁，這份直接結束（不必載入 Qt）
    from core.single_instance import SingleInstance
    instance = SingleInstance()
    if not instance.is_primary:
        if instance.send(cli_files):
            return
        instance.claim()  # 主程式剛好在關閉：改由這份接手

    # Qt 在 Windows 預設用 DirectWrite 讀字型清單、找 emoji 的備援字型，字型裝得多的電腦
    # （實測 1260 個字型家族）光這兩步就要 1.8 秒；GDI 字型引擎只要 0.85 秒，emoji 一樣是彩色的
    os.environ.setdefault("QT_QPA_PLATFORM", "windows:fontengine=gdi")

    from PySide6.QtCore import QObject, Qt, Signal, Slot
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QIcon
    from ui.main_window import PDFMainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("WingLightPDF — 輕快免安裝PDF檢視與編輯工具")
    ico_path = _resolve_icon_path()
    if os.path.exists(ico_path):
        app.setWindowIcon(QIcon(ico_path))

    # 深淺色主題與字型：讀 WingLightPDF.json，沒選過就跟著 Windows
    from ui import theme
    theme.init()

    startup_ms = (time.perf_counter() - t0) * 1000.0

    if not cli_files:
        win = PDFMainWindow(initial_pdf_path=None, startup_ms=startup_ms)
        win.show()
    elif PDFMainWindow.multi_tab_mode:
        win = PDFMainWindow(initial_pdf_path=cli_files[0], startup_ms=startup_ms)
        for extra_pdf in cli_files[1:]:
            win.open_pdf_in_new_tab(extra_pdf)
        win.show()
    else:
        for i, pdf_path in enumerate(cli_files):
            win = PDFMainWindow(
                initial_pdf_path=pdf_path,
                startup_ms=startup_ms if i == 0 else None,
            )
            win.show()

    if instance.is_primary:
        class _ExternalOpenBridge(QObject):
            """背景執行緒收到的檔案，排進主執行緒再開啟。"""
            files_received = Signal(list)

            def __init__(self) -> None:
                super().__init__()
                self.files_received.connect(self._open, Qt.ConnectionType.QueuedConnection)

            @Slot(list)
            def _open(self, files) -> None:
                PDFMainWindow.open_external_files(files)

        bridge = _ExternalOpenBridge()
        instance.serve(bridge.files_received.emit)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
