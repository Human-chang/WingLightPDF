# -*- coding: utf-8 -*-
"""
按需延遲載入 (Lazy Loading) 的重度運算背景執行緒：
1. OptimizePDFWorker: 檔案縮小最佳化（無損結構清理 + 選用圖片降採樣壓縮）
2. OnDemandOCRWorker: 選用開啟才執行的單頁/局部區域文字辨識 (OCR)
3. FullDocumentOCRWorker: 選用開啟才執行的「全部文件所有頁面」批次 OCR（完成後自動建立全文搜尋索引與座標）
"""

from __future__ import annotations
import os
import io
from typing import List, Tuple
import fitz
from PySide6.QtCore import QThread, Signal


class OptimizePDFWorker(QThread):
    """背景執行 PDF 最佳化（縮小檔案體積）"""

    progress_msg = Signal(str)
    finished_ok = Signal(str, int, int)  # (output_path, old_size_bytes, new_size_bytes)
    failed_err = Signal(str)

    def __init__(
        self,
        source_bytes: bytes,
        original_file_size: int,
        output_path: str,
        level: str = "medium",
    ) -> None:
        super().__init__()
        self.source_bytes = source_bytes
        self.original_file_size = original_file_size
        self.output_path = output_path
        self.level = level

    def run(self) -> None:
        try:
            self.progress_msg.emit("正在讀取文件結構…")
            doc = fitz.open("pdf", self.source_bytes)

            if self.level in ("medium", "aggressive"):
                dpi_target = 150 if self.level == "medium" else 100
                dpi_threshold = 200 if self.level == "medium" else 140
                quality = 75 if self.level == "medium" else 60
                self.progress_msg.emit(f"正在壓縮內嵌圖片（{dpi_target} DPI，品質 {quality}%）…")
                if hasattr(doc, "rewrite_images"):
                    doc.rewrite_images(
                        dpi_threshold=dpi_threshold,
                        dpi_target=dpi_target,
                        quality=quality,
                        lossy=True,
                        lossless=True,
                        bitonal=True,
                        color=True,
                        gray=True,
                        set_to_gray=False,
                    )

            self.progress_msg.emit("正在清理沒用到的物件並壓縮資料…")
            if hasattr(doc, "subset_fonts"):
                try:
                    doc.subset_fonts()
                except Exception:
                    pass

            tmp_path = self.output_path + ".opt_tmp.pdf"
            doc.save(
                tmp_path,
                garbage=4,
                deflate=True,
                deflate_images=True,
                deflate_fonts=True,
                clean=True,
            )
            doc.close()
            os.replace(tmp_path, self.output_path)
            new_size = os.path.getsize(self.output_path)
            self.finished_ok.emit(self.output_path, self.original_file_size, self.output_path and new_size)
        except Exception as e:
            self.failed_err.emit(str(e))


# 模組級快取：只有當使用者主動按 OCR 時才初始化一次，啟動時為 None
_CACHED_OCR_ENGINE = None


def _create_ocr_engine():
    """
    依打包版本選擇 OCR 引擎，回傳 ocr(img_np) -> [(box, text, score), ...]（附 engine_name 屬性）：
    1. 完整版：rapidocr 3.x（內建 PP-OCRv6 多語模型，繁體中文不會被辨識成簡體，數字表格也準）
    2. 開發環境只有舊版 rapidocr_onnxruntime 時自動相容
    3. 輕量版（未打包 RapidOCR）：Windows 內建 OCR，不需任何模型檔
    模型檔皆隨套件打包，執行時不會連網下載。
    """
    try:
        from rapidocr import RapidOCR
    except ImportError:
        pass
    else:
        engine = RapidOCR(params={"Global.log_level": "error"})

        def _run(img_np):
            out = engine(img_np)
            if not out.txts or out.boxes is None:
                return []
            return list(zip(out.boxes.tolist(), out.txts, out.scores))

        _run.engine_name = "RapidOCR PP-OCRv6"
        return _run

    try:
        from rapidocr_onnxruntime import RapidOCR as LegacyRapidOCR
    except ImportError:
        pass
    else:
        legacy_engine = LegacyRapidOCR()

        def _run_legacy(img_np):
            result, _elapse = legacy_engine(img_np)
            return list(result or [])

        _run_legacy.engine_name = "RapidOCR (舊版 rapidocr_onnxruntime)"
        return _run_legacy

    from core.windows_ocr import WindowsOCR
    return WindowsOCR()


def _get_or_init_ocr_engine():
    global _CACHED_OCR_ENGINE
    if _CACHED_OCR_ENGINE is None:
        _CACHED_OCR_ENGINE = _create_ocr_engine()
    return _CACHED_OCR_ENGINE


class OnDemandOCRWorker(QThread):
    """
    按需啟動的單頁 / 圈選區域 OCR 文字辨識執行緒。
    只有在被呼叫時才會 import 辨識引擎，平時佔用 0 MB 記憶體與 0 ms 啟動時間。
    """

    status_changed = Signal(str)
    ocr_completed = Signal(str, list)  # (純文字結果, 詳細區塊清單 [(box, text, conf), ...])
    ocr_failed = Signal(str)

    def __init__(self, png_bytes: bytes) -> None:
        super().__init__()
        self.png_bytes = png_bytes

    def run(self) -> None:
        try:
            if _CACHED_OCR_ENGINE is None:
                self.status_changed.emit("第一次使用文字辨識，正在載入辨識引擎…")
            ocr_engine = _get_or_init_ocr_engine()

            self.status_changed.emit("正在辨識文字…")
            import numpy as np
            from PIL import Image

            img = Image.open(io.BytesIO(self.png_bytes)).convert("RGB")
            img_np = np.array(img)

            result = ocr_engine(img_np)
            if not result:
                self.ocr_completed.emit("（未偵測到任何文字）", [])
                return

            lines_text = []
            details = []
            for box, text, score in result:
                conf = float(score) if isinstance(score, (int, float, str)) else 0.0
                lines_text.append(text)
                details.append((box, text, conf))

            full_text = "\n".join(lines_text)
            self.ocr_completed.emit(full_text, details)
        except Exception as e:
            self.ocr_failed.emit(f"OCR 辨識發生錯誤：{e}")


class FullDocumentOCRWorker(QThread):
    """
    選用開啟才執行的「辨識全部文件所有頁面」背景執行緒。
    逐頁渲染並進行 OCR，將每個文字區塊換算回 PDF 頁面座標 (fitz.Rect)，
    讓使用者在辨識完成後可直接透過「搜尋文字」功能搜尋整份掃描 PDF 並高亮跳轉！
    """

    status_changed = Signal(str)
    page_done = Signal(int, int, str, list)  # (page_index, total_pages, page_text, [(fitz.Rect, text), ...])
    all_completed = Signal(int)              # 完成辨識的總頁數
    ocr_failed = Signal(str)

    def __init__(self, pdf_bytes: bytes, dpi: int = 200) -> None:
        super().__init__()
        self.pdf_bytes = pdf_bytes
        self.dpi = dpi

    def run(self) -> None:
        try:
            if _CACHED_OCR_ENGINE is None:
                self.status_changed.emit("第一次使用文字辨識，正在載入辨識引擎…")
            ocr_engine = _get_or_init_ocr_engine()

            import numpy as np

            doc = fitz.open("pdf", self.pdf_bytes)
            total = len(doc)
            scale = self.dpi / 72.0
            mat = fitz.Matrix(scale, scale)
            processed = 0

            for p_idx in range(total):
                if self.isInterruptionRequested():
                    self.status_changed.emit(f"已停止辨識（完成 {processed:,}／{total:,} 頁）")
                    break

                self.status_changed.emit(f"正在辨識第 {p_idx + 1:,}／{total:,} 頁…")
                page = doc[p_idx]
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_np = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)

                result = ocr_engine(img_np)
                page_lines: List[str] = []
                rect_items: List[Tuple[fitz.Rect, str]] = []

                if result:
                    for box, text, _score in result:
                        if not text or not str(text).strip():
                            continue
                        txt_str = str(text).strip()
                        page_lines.append(txt_str)
                        # box 為 4 個頂點 [[x0,y0], [x1,y1], [x2,y2], [x3,y3]] 的像素座標
                        xs = [pt[0] / scale for pt in box]
                        ys = [pt[1] / scale for pt in box]
                        pdf_rect = fitz.Rect(min(xs), min(ys), max(xs), max(ys))
                        rect_items.append((pdf_rect, txt_str))

                page_text = "\n".join(page_lines) if page_lines else "（此頁未偵測到文字）"
                processed += 1
                self.page_done.emit(p_idx, total, page_text, rect_items)

            doc.close()
            self.all_completed.emit(processed)
        except Exception as e:
            self.ocr_failed.emit(f"全文件 OCR 發生錯誤：{e}")
