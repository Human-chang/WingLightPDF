# -*- coding: utf-8 -*-
"""
進階功能對話框集合 (dialogs.py)：
1. MergePDFDialog: 合併多個 PDF（支援各檔案自訂頁碼範圍與順序調整）
2. SplitPDFDialog: 拆分 PDF（每 N 頁、指定頁碼區間、依書籤章節）
3. PageNumberWatermarkDialog: 批次重編頁碼與批次加浮水印
4. OptimizePDFDialog: 檔案最佳化瘦身（按需背景執行緒）
5. OnDemandOCRDialog: 選用開啟才執行的單頁/局部區域 OCR 文字辨識視窗
6. FullDocumentOCRDialog: 選用開啟才執行的「辨識全部文件所有頁面」批次 OCR 視窗（自動建立全文搜尋索引）
7. ComparePDFWindow: 雙檔案「疊圖差異高亮 / 左右同步捲動比對」視窗
"""

from __future__ import annotations
import os
from typing import List, Tuple, Optional
import fitz

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QImage, QPixmap, QGuiApplication, QFont
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QTabWidget,
    QWidget,
    QLabel,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox,
    QCheckBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QFileDialog,
    QMessageBox,
    QTextEdit,
    QProgressBar,
    QGraphicsView,
    QGraphicsScene,
    QSplitter,
    QRadioButton,
    QGroupBox,
)

from core.pdf_engine import PDFEngine
from core.lazy_workers import OptimizePDFWorker, OnDemandOCRWorker, FullDocumentOCRWorker
from ui import theme
from ui.status_line import StatusLine


# =====================================================================
# 1. 合併多個 PDF 對話框
# =====================================================================
class MergePDFDialog(QDialog):
    def __init__(self, current_file: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("合併多個 PDF 檔案")
        self.resize(660, 420)
        self.merged_output_path: Optional[str] = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("請加入要合併的 PDF 檔案（可雙擊「頁碼範圍」欄設定局部頁面，空白代表全部頁面）："))

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["檔案名稱與路徑", "總頁數", "頁碼範圍 (如 1-5, 8；空白=全部)"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        btn_add = QPushButton("加入 PDF 檔案…")
        theme.bind_icon(btn_add, "plus")
        btn_up = QPushButton("上移")
        btn_down = QPushButton("下移")
        btn_remove = QPushButton("移除選取")
        theme.bind_icon(btn_remove, "trash")
        btn_add.clicked.connect(self._add_files)
        btn_up.clicked.connect(lambda: self._move_row(-1))
        btn_down.clicked.connect(lambda: self._move_row(1))
        btn_remove.clicked.connect(self._remove_selected)
        for b in (btn_add, btn_up, btn_down, btn_remove):
            btn_row.addWidget(b)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        bottom = QHBoxLayout()
        self.chk_open_after = QCheckBox("合併完成後立即開新視窗檢視")
        self.chk_open_after.setChecked(True)
        bottom.addWidget(self.chk_open_after)
        bottom.addStretch()
        btn_run = QPushButton("開始合併並另存新檔…")
        btn_run.setDefault(True)
        theme.mark_primary(btn_run)
        btn_cancel = QPushButton("關閉")
        btn_run.clicked.connect(self._execute_merge)
        btn_cancel.clicked.connect(self.reject)
        bottom.addWidget(btn_run)
        bottom.addWidget(btn_cancel)
        layout.addLayout(bottom)

        if current_file and os.path.exists(current_file):
            self._append_file_row(current_file)

    def _append_file_row(self, path: str) -> None:
        try:
            doc = fitz.open(path)
            cnt = len(doc)
            doc.close()
        except Exception:
            return
        row = self.table.rowCount()
        self.table.insertRow(row)
        it_path = QTableWidgetItem(path)
        it_path.setFlags(it_path.flags() & ~Qt.ItemFlag.ItemIsEditable)
        it_cnt = QTableWidgetItem(str(cnt))
        it_cnt.setFlags(it_cnt.flags() & ~Qt.ItemFlag.ItemIsEditable)
        it_range = QTableWidgetItem("")
        self.table.setItem(row, 0, it_path)
        self.table.setItem(row, 1, it_cnt)
        self.table.setItem(row, 2, it_range)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "選擇要合併的 PDF 檔案", "", "PDF 檔案 (*.pdf)")
        for p in paths:
            self._append_file_row(p)

    def _move_row(self, delta: int) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        target = row + delta
        if not (0 <= target < self.table.rowCount()):
            return
        for col in range(3):
            a = self.table.takeItem(row, col)
            b = self.table.takeItem(target, col)
            self.table.setItem(row, col, b)
            self.table.setItem(target, col, a)
        self.table.selectRow(target)

    def _remove_selected(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _execute_merge(self) -> None:
        if self.table.rowCount() == 0:
            QMessageBox.information(self, "提示", "請至少加入一個 PDF 檔案。")
            return
        out_path, _ = QFileDialog.getSaveFileName(self, "儲存合併後的 PDF", "合併結果.pdf", "PDF 檔案 (*.pdf)")
        if not out_path:
            return
        specs: List[Tuple[str, Optional[str]]] = []
        for r in range(self.table.rowCount()):
            fpath = self.table.item(r, 0).text()
            rstr = self.table.item(r, 2).text().strip()
            specs.append((fpath, rstr if rstr else None))
        try:
            total = PDFEngine.merge_pdfs(specs, out_path)
            self.merged_output_path = out_path
            QMessageBox.information(self, "合併成功", f"已成功合併為 {total} 頁的 PDF：\n{out_path}")
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "合併失敗", str(e))


# =====================================================================
# 2. 拆分 PDF 對話框
# =====================================================================
class SplitPDFDialog(QDialog):
    def __init__(self, engine: PDFEngine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("拆分 PDF 檔案")
        self.resize(460, 310)

        layout = QVBoxLayout(self)
        total = self.engine.page_count
        layout.addWidget(QLabel(f"目前文件總頁數：共 {total} 頁"))

        group = QGroupBox("選擇拆分方式")
        g_layout = QVBoxLayout(group)

        self.rad_every = QRadioButton("固定每 N 頁拆成一個檔案：")
        self.rad_every.setChecked(True)
        row_n = QHBoxLayout()
        row_n.addWidget(self.rad_every)
        self.spin_n = QSpinBox()
        self.spin_n.setRange(1, max(1, total))
        self.spin_n.setValue(1)
        row_n.addWidget(self.spin_n)
        row_n.addWidget(QLabel("頁 / 檔"))
        row_n.addStretch()
        g_layout.addLayout(row_n)

        self.rad_ranges = QRadioButton("依指定頁碼區間拆分（每段以分號 ; 隔開，例如 1-3; 4-8; 9-12）：")
        g_layout.addWidget(self.rad_ranges)
        self.txt_ranges = QLineEdit()
        self.txt_ranges.setPlaceholderText(f"例如：1-2; 3-{total}")
        g_layout.addWidget(self.txt_ranges)

        self.rad_toc = QRadioButton("依第一層書籤（目錄章節）自動拆分為多個檔案")
        g_layout.addWidget(self.rad_toc)

        layout.addWidget(group)

        btns = QHBoxLayout()
        btns.addStretch()
        btn_ok = QPushButton("選擇輸出資料夾並開始拆分…")
        btn_ok.setDefault(True)
        theme.mark_primary(btn_ok)
        btn_cancel = QPushButton("取消")
        btn_ok.clicked.connect(self._execute_split)
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(btn_ok)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)

    def _execute_split(self) -> None:
        out_dir = QFileDialog.getExistingDirectory(self, "選擇拆分後 PDF 的輸出資料夾")
        if not out_dir:
            return
        try:
            if self.rad_every.isChecked():
                files = self.engine.split_pdf(out_dir, mode="every_n", every_n=self.spin_n.value())
            elif self.rad_ranges.isChecked():
                raw = self.txt_ranges.text().replace("；", ";")
                ranges = [s.strip() for s in raw.split(";") if s.strip()]
                if not ranges:
                    QMessageBox.warning(self, "提示", "請輸入頁碼區間。")
                    return
                files = self.engine.split_pdf(out_dir, mode="ranges", custom_ranges=ranges)
            else:
                files = self.engine.split_pdf(out_dir, mode="bookmarks")

            QMessageBox.information(self, "拆分完成", f"已成功拆分出 {len(files)} 個 PDF 檔案至：\n{out_dir}")
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "拆分失敗", str(e))


# =====================================================================
# 3. 批次重編頁碼 / 加浮水印對話框
# =====================================================================
class PageNumberWatermarkDialog(QDialog):
    def __init__(self, engine: PDFEngine, initial_tab: int = 0, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("批次重編頁碼 / 加浮水印")
        self.resize(460, 340)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: 批次頁碼
        tab_pno = QWidget()
        f1 = QFormLayout(tab_pno)
        self.combo_fmt = QComboBox()
        self.combo_fmt.setEditable(True)
        self.combo_fmt.addItems([
            "第 {p} 頁 / 共 {n} 頁",
            "第 {p} 頁",
            "{p} / {n}",
            "- {p} -",
        ])
        f1.addRow("頁碼文字格式：", self.combo_fmt)

        self.combo_pos = QComboBox()
        self.combo_pos.addItem("底部置中", "bottom_center")
        self.combo_pos.addItem("底部靠右", "bottom_right")
        self.combo_pos.addItem("底部靠左", "bottom_left")
        self.combo_pos.addItem("頂部置中", "top_center")
        self.combo_pos.addItem("頂部靠右", "top_right")
        f1.addRow("頁碼位置：", self.combo_pos)

        self.spin_start = QSpinBox()
        self.spin_start.setRange(1, 9999)
        self.spin_start.setValue(1)
        f1.addRow("起始頁碼數字：", self.spin_start)

        self.spin_pno_size = QDoubleSpinBox()
        self.spin_pno_size.setRange(7.0, 36.0)
        self.spin_pno_size.setValue(10.5)
        f1.addRow("字體大小 (pt)：", self.spin_pno_size)

        self.chk_clear_old = QCheckBox("自動以白底遮蓋原位置舊頁碼（合併檔案後重編頁碼必備）")
        self.chk_clear_old.setChecked(True)
        f1.addRow("", self.chk_clear_old)

        btn_apply_pno = QPushButton("為整份文件加上頁碼")
        theme.mark_primary(btn_apply_pno)
        btn_apply_pno.clicked.connect(self._apply_page_numbers)
        f1.addRow("", btn_apply_pno)
        self.tabs.addTab(tab_pno, "批次重編頁碼")

        # Tab 2: 批次浮水印
        tab_wm = QWidget()
        f2 = QFormLayout(tab_wm)
        self.txt_wm = QLineEdit("機密文件 請勿外流")
        f2.addRow("浮水印文字：", self.txt_wm)

        self.spin_wm_size = QDoubleSpinBox()
        self.spin_wm_size.setRange(14.0, 120.0)
        self.spin_wm_size.setValue(44.0)
        f2.addRow("字體大小 (pt)：", self.spin_wm_size)

        self.spin_wm_angle = QDoubleSpinBox()
        self.spin_wm_angle.setRange(-90.0, 90.0)
        self.spin_wm_angle.setValue(35.0)
        f2.addRow("旋轉角度 (°)：", self.spin_wm_angle)

        self.spin_wm_opacity = QDoubleSpinBox()
        self.spin_wm_opacity.setRange(0.05, 0.90)
        self.spin_wm_opacity.setSingleStep(0.05)
        self.spin_wm_opacity.setValue(0.22)
        f2.addRow("不透明度 (0.05~0.9)：", self.spin_wm_opacity)

        self.chk_wm_tiled = QCheckBox("滿版重複鋪排浮水印")
        self.chk_wm_tiled.setChecked(False)
        f2.addRow("", self.chk_wm_tiled)

        btn_apply_wm = QPushButton("為整份文件加上浮水印")
        theme.mark_primary(btn_apply_wm)
        btn_apply_wm.clicked.connect(self._apply_watermark)
        f2.addRow("", btn_apply_wm)
        self.tabs.addTab(tab_wm, "批次加浮水印")

        self.tabs.setCurrentIndex(initial_tab)

    def _apply_page_numbers(self) -> None:
        self.engine.batch_add_page_numbers(
            format_str=self.combo_fmt.currentText(),
            position=self.combo_pos.currentData(),
            font_size=self.spin_pno_size.value(),
            start_number=self.spin_start.value(),
            clear_existing_area=self.chk_clear_old.isChecked(),
        )
        self.accept()

    def _apply_watermark(self) -> None:
        text = self.txt_wm.text().strip()
        if not text:
            QMessageBox.warning(self, "提示", "請輸入浮水印文字。")
            return
        self.engine.batch_add_watermark(
            text=text,
            font_size=self.spin_wm_size.value(),
            angle=self.spin_wm_angle.value(),
            opacity=self.spin_wm_opacity.value(),
            tiled=self.chk_wm_tiled.isChecked(),
        )
        self.accept()


# =====================================================================
# 4. 最佳化（縮小檔案）對話框
# =====================================================================
class OptimizePDFDialog(QDialog):
    def __init__(self, engine: PDFEngine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setWindowTitle("最佳化 PDF（縮小檔案體積）")
        self.resize(480, 260)
        self.worker: Optional[OptimizePDFWorker] = None

        layout = QVBoxLayout(self)
        orig_size = os.path.getsize(engine.file_path) if (engine.file_path and os.path.exists(engine.file_path)) else 0
        self.orig_size = orig_size
        layout.addWidget(QLabel(f"原始檔案大小：{orig_size / (1024 * 1024):.2f} MB ({orig_size:,} bytes)"))

        layout.addWidget(QLabel("選擇最佳化壓縮等級："))
        self.combo_level = QComboBox()
        self.combo_level.addItem("輕度無損最佳化（清理廢棄物件、字型子集化、重壓縮資料流）", "lossless")
        self.combo_level.addItem("標準瘦身（推薦：內嵌大圖降至 150 DPI + 品質 75% + 結構清理）", "medium")
        self.combo_level.addItem("極限瘦身（內嵌圖片降至 100 DPI + 品質 60%，適合傳送郵件）", "aggressive")
        self.combo_level.setCurrentIndex(1)
        layout.addWidget(self.combo_level)

        self.lbl_status = StatusLine("選好壓縮等級後按「開始最佳化」")
        layout.addWidget(self.lbl_status)

        btns = QHBoxLayout()
        btns.addStretch()
        self.btn_start = QPushButton("開始最佳化並另存新檔…")
        self.btn_start.setDefault(True)
        theme.mark_primary(self.btn_start)
        self.btn_close = QPushButton("關閉")
        self.btn_start.clicked.connect(self._start_optimize)
        self.btn_close.clicked.connect(self.reject)
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_close)
        layout.addLayout(btns)

    def _start_optimize(self) -> None:
        if self.engine.doc is None:
            return
        default_name = "最佳化_" + os.path.basename(self.engine.file_path or "document.pdf")
        out_path, _ = QFileDialog.getSaveFileName(self, "儲存縮小後的 PDF", default_name, "PDF 檔案 (*.pdf)")
        if not out_path:
            return

        self.btn_start.setEnabled(False)
        self.lbl_status.set_busy("最佳化中…")
        raw_bytes = self.engine.doc.tobytes()
        orig_sz = self.orig_size or len(raw_bytes)

        self.worker = OptimizePDFWorker(
            source_bytes=raw_bytes,
            original_file_size=orig_sz,
            output_path=out_path,
            level=self.combo_level.currentData(),
        )
        self.worker.progress_msg.connect(self.lbl_status.setText)
        self.worker.finished_ok.connect(self._on_finished)
        self.worker.failed_err.connect(self._on_failed)
        self.worker.start()

    def _on_finished(self, out_path: str, old_sz: int, new_sz: int) -> None:
        self.btn_start.setEnabled(True)
        ratio = (1.0 - (new_sz / max(1, old_sz))) * 100.0
        msg = (
            f"最佳化完成！\n\n"
            f"原始大小：{old_sz / (1024 * 1024):.2f} MB\n"
            f"瘦身後大小：{new_sz / (1024 * 1024):.2f} MB\n"
            f"減少比例：{ratio:.1f}%\n\n"
            f"儲存位置：{out_path}"
        )
        self.lbl_status.set_ok(f"完成｜縮小 {ratio:.1f}%")
        QMessageBox.information(self, "最佳化成功", msg)
        self.accept()

    def _on_failed(self, err: str) -> None:
        self.btn_start.setEnabled(True)
        self.lbl_status.set_error("最佳化失敗，原因見訊息視窗")
        QMessageBox.critical(self, "最佳化失敗", err)


# =====================================================================
# 5. 選用開啟才執行的單頁 / 局部區域 OCR 文字辨識視窗
# =====================================================================
class OnDemandOCRDialog(QDialog):
    """
    只有在使用者主動點擊「OCR 辨識」時才會建立此對話框並在背景載入辨識模型。
    若為整頁辨識，會自動將辨識出的文字與座標寫入 engine.ocr_page_cache，立即可供「搜尋文字」使用！
    """

    def __init__(
        self,
        png_bytes: bytes,
        title_suffix: str = "",
        engine: Optional[PDFEngine] = None,
        page_index: Optional[int] = None,
        render_dpi: int = 250,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"文字辨識 (OCR) — 選用按需執行 {title_suffix}")
        self.resize(740, 500)
        self.png_bytes = png_bytes
        self.engine = engine
        self.page_index = page_index
        self.render_dpi = render_dpi
        self.worker: Optional[OnDemandOCRWorker] = None

        layout = QVBoxLayout(self)

        self.lbl_status = StatusLine("準備文字辨識引擎…", "busy")
        layout.addWidget(self.lbl_status)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left_box = QWidget()
        l_lay = QVBoxLayout(left_box)
        l_lay.addWidget(QLabel("辨識來源影像："))
        self.lbl_img = QLabel()
        self.lbl_img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap()
        pix.loadFromData(png_bytes)
        if not pix.isNull():
            self.lbl_img.setPixmap(
                pix.scaled(300, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        l_lay.addWidget(self.lbl_img, stretch=1)
        splitter.addWidget(left_box)

        right_box = QWidget()
        r_lay = QVBoxLayout(right_box)
        r_lay.addWidget(QLabel("辨識結果文字（可直接修改、複製或於主視窗搜尋）："))
        self.txt_result = QTextEdit()
        self.txt_result.setFont(theme.ui_font("card-title"))
        r_lay.addWidget(self.txt_result, stretch=1)
        splitter.addWidget(right_box)

        layout.addWidget(splitter, stretch=1)

        btn_row = QHBoxLayout()
        btn_copy = QPushButton("複製全部文字")
        theme.bind_icon(btn_copy, "copy")
        btn_save = QPushButton("另存為 .txt…")
        theme.bind_icon(btn_save, "save")
        btn_close = QPushButton("關閉")
        btn_copy.clicked.connect(self._copy_all)
        btn_save.clicked.connect(self._save_txt)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_save)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._start_ocr()

    def _start_ocr(self) -> None:
        self.worker = OnDemandOCRWorker(self.png_bytes)
        self.worker.status_changed.connect(self.lbl_status.setText)
        self.worker.ocr_completed.connect(self._on_ocr_done)
        self.worker.ocr_failed.connect(self._on_ocr_error)
        self.worker.start()

    def _on_ocr_done(self, text: str, details: list) -> None:
        self.txt_result.setPlainText(text)

        # 若為整頁 OCR，將座標與文字存入 engine.ocr_page_cache，立即可供「搜尋文字」找到！
        if self.engine is not None and self.page_index is not None and details:
            scale = self.render_dpi / 72.0
            rect_items: List[Tuple[fitz.Rect, str]] = []
            for box, line_txt, _conf in details:
                if not line_txt or not str(line_txt).strip():
                    continue
                xs = [pt[0] / scale for pt in box]
                ys = [pt[1] / scale for pt in box]
                rect_items.append((fitz.Rect(min(xs), min(ys), max(xs), max(ys)), str(line_txt).strip()))
            self.engine.store_ocr_page_items(self.page_index, rect_items)
            self.lbl_status.set_ok(
                f"辨識完成｜{len(details):,} 行｜已加入第 {self.page_index + 1:,} 頁的搜尋，可以直接搜尋"
            )
        else:
            self.lbl_status.set_ok(f"辨識完成｜{len(details):,} 行")

    def _on_ocr_error(self, err: str) -> None:
        self.lbl_status.set_error("辨識失敗，原因寫在下方")
        self.txt_result.setPlainText(err)

    def _copy_all(self) -> None:
        QGuiApplication.clipboard().setText(self.txt_result.toPlainText())
        self.lbl_status.set_ok("已複製辨識文字到剪貼簿")

    def _save_txt(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "另存 OCR 文字", "OCR辨識結果.txt", "文字檔 (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_result.toPlainText())


# =====================================================================
# 6. 選用開啟才執行的「辨識全部文件所有頁面」批次 OCR 視窗
# =====================================================================
class FullDocumentOCRDialog(QDialog):
    """
    對整份 PDF 所有頁面進行批次 OCR 文字辨識。
    每完成一頁即自動寫入 engine.ocr_page_cache，辨識後可直接在主視窗用「搜尋文字」搜尋整份掃描檔，
    亦可一鍵將透明文字層嵌入 PDF 存檔！
    """

    ocr_text_embedded = Signal()

    def __init__(self, engine: PDFEngine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        total = self.engine.page_count
        self.setWindowTitle(f"文字辨識（OCR）：整份文件，共 {total:,} 頁")
        self.resize(780, 560)
        self.worker: Optional[FullDocumentOCRWorker] = None

        layout = QVBoxLayout(self)

        top_info = QHBoxLayout()
        self.total_pages = total
        self.lbl_status = StatusLine(f"準備辨識整份文件（共 {total:,} 頁）…", "busy")
        top_info.addWidget(self.lbl_status, stretch=1)

        self.btn_stop = QPushButton("停止辨識")
        self.btn_stop.clicked.connect(self._stop_ocr)
        top_info.addWidget(self.btn_stop)
        layout.addLayout(top_info)

        self.progress = QProgressBar()
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(0)
        self.progress.setFormat("第 %v／%m 頁")
        layout.addWidget(self.progress)

        layout.addWidget(QLabel("各頁辨識文字結果（辨識期間已同步建立全文搜尋索引，完成後可直接搜尋關鍵字）："))
        self.txt_all = QTextEdit()
        self.txt_all.setFont(theme.ui_font("body"))
        layout.addWidget(self.txt_all, stretch=1)

        btn_row = QHBoxLayout()
        self.btn_embed = QPushButton("把辨識文字寫入 PDF（存檔後下次不用再辨識就能搜尋）")
        self.btn_embed.setEnabled(False)
        self.btn_embed.clicked.connect(self._embed_into_pdf)

        btn_copy = QPushButton("複製全部文字")
        theme.bind_icon(btn_copy, "copy")
        btn_save = QPushButton("另存為 .txt…")
        theme.bind_icon(btn_save, "save")
        btn_close = QPushButton("完成並回到搜尋")
        btn_close.setDefault(True)
        theme.mark_primary(btn_close)

        btn_copy.clicked.connect(self._copy_all)
        btn_save.clicked.connect(self._save_txt)
        btn_close.clicked.connect(self.accept)

        btn_row.addWidget(self.btn_embed)
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_save)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        self._start_full_ocr()

    def _start_full_ocr(self) -> None:
        if self.engine.doc is None:
            return
        raw_bytes = self.engine.doc.tobytes()
        self.worker = FullDocumentOCRWorker(pdf_bytes=raw_bytes, dpi=200)
        self.worker.status_changed.connect(self.lbl_status.setText)
        self.worker.page_done.connect(self._on_page_done)
        self.worker.all_completed.connect(self._on_all_completed)
        self.worker.ocr_failed.connect(self._on_failed)
        self.worker.start()

    def _stop_ocr(self) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.btn_stop.setEnabled(False)

    def _on_page_done(self, p_idx: int, total: int, page_text: str, rect_items: list) -> None:
        self.progress.setValue(p_idx + 1)
        self.engine.store_ocr_page_items(p_idx, rect_items)
        header = f"==================== 第 {p_idx + 1} / {total} 頁 ====================\n"
        self.txt_all.append(header + page_text + "\n")
        self.btn_embed.setEnabled(True)

    def _on_all_completed(self, processed_count: int) -> None:
        stopped = self.worker is not None and self.worker.isInterruptionRequested()
        self.btn_stop.setEnabled(False)
        if stopped:
            self.lbl_status.set_warn(f"已停止辨識｜完成 {processed_count:,}／{self.total_pages:,} 頁")
        else:
            self.lbl_status.set_ok(f"辨識完成｜{processed_count:,} 頁｜回到主視窗就可以搜尋全文")

    def _on_failed(self, err: str) -> None:
        self.btn_stop.setEnabled(False)
        self.lbl_status.set_error("辨識中斷，原因見訊息視窗")
        QMessageBox.warning(self, "OCR 錯誤", err)

    def _embed_into_pdf(self) -> None:
        pages_cnt = self.engine.embed_ocr_cache_into_pdf()
        if pages_cnt > 0:
            self.ocr_text_embedded.emit()
            self.lbl_status.set_ok(f"已把 {pages_cnt:,} 頁的辨識文字寫入 PDF，記得儲存檔案")
            QMessageBox.information(
                self,
                "已寫入可搜尋文字層",
                f"已把 {pages_cnt:,} 頁的辨識文字寫入 PDF。\n回到主視窗按「儲存檔案」後，下次開啟這個 PDF 不用再辨識，就能直接搜尋和選取文字。",
            )

    def _copy_all(self) -> None:
        QGuiApplication.clipboard().setText(self.txt_all.toPlainText())
        self.lbl_status.set_ok("已複製整份文件的辨識文字到剪貼簿")

    def _save_txt(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "另存全文件 OCR 文字", "全文件OCR結果.txt", "文字檔 (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.txt_all.toPlainText())

    def closeEvent(self, event) -> None:
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption()
            self.worker.wait(1500)
        super().closeEvent(event)


# =====================================================================
# 7. 雙檔案「疊圖 / 同步捲動比對」獨立視窗
# =====================================================================
class ComparePDFWindow(QDialog):
    def __init__(self, initial_file_a: Optional[str] = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("雙檔案「疊圖差異高亮 / 同步捲動比對」工具")
        self.resize(1220, 780)
        self.doc_a: Optional[fitz.Document] = None
        self.doc_b: Optional[fitz.Document] = None
        self.page_idx: int = 0
        self.zoom: float = 1.15
        self._syncing_scroll: bool = False

        layout = QVBoxLayout(self)

        top_bar = QHBoxLayout()
        self.btn_load_a = QPushButton("載入基準檔 A（舊版）…")
        theme.bind_icon(self.btn_load_a, "folder-open")
        self.lbl_a = QLabel("未載入 A 檔")
        self.btn_load_b = QPushButton("載入對照檔 B（新版）…")
        theme.bind_icon(self.btn_load_b, "folder-open")
        self.lbl_b = QLabel("未載入 B 檔")

        self.btn_load_a.clicked.connect(self._pick_file_a)
        self.btn_load_b.clicked.connect(self._pick_file_b)

        top_bar.addWidget(self.btn_load_a)
        top_bar.addWidget(self.lbl_a, stretch=1)
        top_bar.addWidget(self.btn_load_b)
        top_bar.addWidget(self.lbl_b, stretch=1)
        layout.addLayout(top_bar)

        ctrl_bar = QHBoxLayout()
        ctrl_bar.addWidget(QLabel("比對模式："))
        self.combo_mode = QComboBox()
        self.combo_mode.addItems([
            "左右並排同步捲動（A 左／B 右）",
            "疊圖找差異（紅＝只有 A｜藍＝B 新增或修改｜灰＝沒變）",
        ])
        self.combo_mode.currentIndexChanged.connect(self._refresh_views)
        ctrl_bar.addWidget(self.combo_mode)

        ctrl_bar.addSpacing(16)
        btn_prev = QPushButton("上一頁")
        self.lbl_page = QLabel("第 1 頁")
        btn_next = QPushButton("下一頁")
        btn_prev.clicked.connect(lambda: self._step_page(-1))
        btn_next.clicked.connect(lambda: self._step_page(1))
        ctrl_bar.addWidget(btn_prev)
        ctrl_bar.addWidget(self.lbl_page)
        ctrl_bar.addWidget(btn_next)

        ctrl_bar.addSpacing(16)
        btn_zoom_out = QPushButton("縮小")
        btn_zoom_in = QPushButton("放大")
        btn_zoom_out.clicked.connect(lambda: self._change_zoom(1 / 1.2))
        btn_zoom_in.clicked.connect(lambda: self._change_zoom(1.2))
        ctrl_bar.addWidget(btn_zoom_out)
        ctrl_bar.addWidget(btn_zoom_in)
        ctrl_bar.addStretch()
        layout.addLayout(ctrl_bar)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.scene_left = QGraphicsScene(self)
        self.view_left = QGraphicsView(self.scene_left)
        self.view_left.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

        self.scene_right = QGraphicsScene(self)
        self.view_right = QGraphicsView(self.scene_right)
        self.view_right.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)

        self.splitter.addWidget(self.view_left)
        self.splitter.addWidget(self.view_right)
        layout.addWidget(self.splitter, stretch=1)

        self.view_left.horizontalScrollBar().valueChanged.connect(
            lambda v: self._sync_scroll(self.view_right.horizontalScrollBar(), v)
        )
        self.view_left.verticalScrollBar().valueChanged.connect(
            lambda v: self._sync_scroll(self.view_right.verticalScrollBar(), v)
        )
        self.view_right.horizontalScrollBar().valueChanged.connect(
            lambda v: self._sync_scroll(self.view_left.horizontalScrollBar(), v)
        )
        self.view_right.verticalScrollBar().valueChanged.connect(
            lambda v: self._sync_scroll(self.view_left.verticalScrollBar(), v)
        )

        if initial_file_a and os.path.exists(initial_file_a):
            self._open_a(initial_file_a)

    def _sync_scroll(self, target_bar, val: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        target_bar.setValue(val)
        self._syncing_scroll = False

    def _pick_file_a(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "選擇基準檔 A", "", "PDF 檔案 (*.pdf)")
        if path:
            self._open_a(path)

    def _pick_file_b(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "選擇對照檔 B", "", "PDF 檔案 (*.pdf)")
        if path:
            if self.doc_b:
                self.doc_b.close()
            self.doc_b = fitz.open(path)
            self.lbl_b.setText(os.path.basename(path))
            self._refresh_views()

    def _open_a(self, path: str) -> None:
        if self.doc_a:
            self.doc_a.close()
        self.doc_a = fitz.open(path)
        self.lbl_a.setText(os.path.basename(path))
        self._refresh_views()

    def _step_page(self, delta: int) -> None:
        max_p = max(
            len(self.doc_a) if self.doc_a else 1,
            len(self.doc_b) if self.doc_b else 1,
        )
        self.page_idx = max(0, min(self.page_idx + delta, max_p - 1))
        self._refresh_views()

    def _change_zoom(self, factor: float) -> None:
        self.zoom = max(0.3, min(4.0, self.zoom * factor))
        self._refresh_views()

    def _refresh_views(self) -> None:
        self.scene_left.clear()
        self.scene_right.clear()
        self.lbl_page.setText(f"第 {self.page_idx + 1} 頁")

        is_overlay = self.combo_mode.currentIndex() == 1
        self.view_right.setVisible(not is_overlay)

        if not is_overlay:
            if self.doc_a and self.page_idx < len(self.doc_a):
                pix_a = self.doc_a[self.page_idx].get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
                qimg_a = QImage(pix_a.samples, pix_a.width, pix_a.height, pix_a.stride, QImage.Format.Format_RGB888).copy()
                self.scene_left.addPixmap(QPixmap.fromImage(qimg_a))
                self.scene_left.setSceneRect(QRectF(0, 0, pix_a.width, pix_a.height))
            if self.doc_b and self.page_idx < len(self.doc_b):
                pix_b = self.doc_b[self.page_idx].get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), alpha=False)
                qimg_b = QImage(pix_b.samples, pix_b.width, pix_b.height, pix_b.stride, QImage.Format.Format_RGB888).copy()
                self.scene_right.addPixmap(QPixmap.fromImage(qimg_b))
                self.scene_right.setSceneRect(QRectF(0, 0, pix_b.width, pix_b.height))
        else:
            if not (self.doc_a and self.doc_b):
                return
            if self.page_idx >= len(self.doc_a) or self.page_idx >= len(self.doc_b):
                return
            import numpy as np
            from PIL import Image

            mat = fitz.Matrix(self.zoom, self.zoom)
            pa = self.doc_a[self.page_idx].get_pixmap(matrix=mat, alpha=False)
            pb = self.doc_b[self.page_idx].get_pixmap(matrix=mat, alpha=False)

            w = min(pa.width, pb.width)
            h = min(pa.height, pb.height)
            img_a = np.frombuffer(pa.samples, dtype=np.uint8).reshape(pa.height, pa.width, 3)[:h, :w]
            img_b = np.frombuffer(pb.samples, dtype=np.uint8).reshape(pb.height, pb.width, 3)[:h, :w]

            gray_a = 0.299 * img_a[:, :, 0] + 0.587 * img_a[:, :, 1] + 0.114 * img_a[:, :, 2]
            gray_b = 0.299 * img_b[:, :, 0] + 0.587 * img_b[:, :, 1] + 0.114 * img_b[:, :, 2]

            ink_a = gray_a < 215
            ink_b = gray_b < 215

            only_a = ink_a & (~ink_b)
            only_b = ink_b & (~ink_a)
            both = ink_a & ink_b

            out = np.full((h, w, 3), 255, dtype=np.uint8)
            out[both] = [175, 175, 175]
            out[only_a] = [235, 30, 30]
            out[only_b] = [15, 105, 240]

            pil_out = Image.fromarray(out, mode="RGB")
            raw = pil_out.tobytes("raw", "RGB")
            qimg = QImage(raw, w, h, w * 3, QImage.Format.Format_RGB888).copy()
            self.scene_left.addPixmap(QPixmap.fromImage(qimg))
            self.scene_left.setSceneRect(QRectF(0, 0, w, h))
