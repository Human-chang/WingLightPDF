# -*- coding: utf-8 -*-
"""
PDF 底層核心引擎 (基於 PyMuPDF / fitz)
設計原則：
1. 啟動時僅載入輕量核心 (fitz, os, io)
2. 圖像濾鏡 (PIL / numpy) 與重度功能僅在呼叫對應方法時延遲載入 (Lazy Import)
3. 支援記憶體快照 Undo/Redo，讓旋轉、刪除、排序、標註寫入都可隨時復原
4. 搜尋文字預設僅搜尋原生文字與「已手動執行過 OCR 的快取文字」，絕不自動觸發 OCR
"""

from __future__ import annotations
import os
import io
import math
import datetime
from typing import List, Tuple, Optional, Dict, Any
import fitz  # PyMuPDF


def get_system_cjk_font_path() -> Optional[str]:
    """取得 Windows 系統內建的繁體中文字型路徑（優先微軟正黑體，次選標楷體/新細明體）"""
    windir = os.environ.get("WINDIR", r"C:\Windows")
    fonts_dir = os.path.join(windir, "Fonts")
    candidates = [
        "msjh.ttc",     # 微軟正黑體
        "msjhbd.ttc",   # 微軟正黑體粗體
        "kaiu.ttf",     # 標楷體
        "mingliu.ttc",  # 細明體
        "simsun.ttc",   # 宋體
        "arialuni.ttf",
    ]
    for name in candidates:
        path = os.path.join(fonts_dir, name)
        if os.path.exists(path):
            return path
    return None


class PDFEngine:
    """管理單一視窗開啟的 PDF 文件與所有底層操作"""

    def __init__(self) -> None:
        self.doc: Optional[fitz.Document] = None
        self.file_path: Optional[str] = None
        self.is_modified: bool = False
        self._undo_stack: List[bytes] = []
        self._redo_stack: List[bytes] = []
        self._max_undo: int = 12
        # 各頁面的比例尺校正設定: {page_index: (pixels_per_unit_at_72dpi, unit_name)}
        self.page_scales: Dict[int, Tuple[float, str]] = {}
        # 手動執行 OCR 後的文字與座標快取: {page_index: [(fitz.Rect, text), ...]}
        self.ocr_page_cache: Dict[int, List[Tuple[fitz.Rect, str]]] = {}

    @property
    def page_count(self) -> int:
        return len(self.doc) if self.doc is not None else 0

    def open_file(self, path: str) -> None:
        """極速開啟 PDF 檔案（僅讀取檔頭與交叉引用表，不預先渲染，也不自動執行 OCR）"""
        if not os.path.exists(path):
            raise FileNotFoundError(f"找不到檔案：{path}")
        if self.doc is not None:
            self.doc.close()
        self.doc = fitz.open(path)
        self.file_path = os.path.abspath(path)
        self.is_modified = False
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.page_scales.clear()
        self.ocr_page_cache.clear()

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
            self.doc = None
        self.file_path = None
        self.is_modified = False
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.ocr_page_cache.clear()

    # -------------------- Undo / Redo 快照管理 --------------------

    def push_undo_snapshot(self) -> None:
        """在執行修改操作前，將當前 PDF 狀態存入記憶體快照（極速增量序列化）"""
        if self.doc is None:
            return
        try:
            data = self.doc.tobytes(garbage=0, deflate=False)
            self._undo_stack.append(data)
            if len(self._undo_stack) > self._max_undo:
                self._undo_stack.pop(0)
            self._redo_stack.clear()
        except Exception:
            pass

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def undo(self) -> bool:
        if not self.can_undo() or self.doc is None:
            return False
        current_bytes = self.doc.tobytes(garbage=0, deflate=False)
        self._redo_stack.append(current_bytes)
        prev_bytes = self._undo_stack.pop()
        self.doc.close()
        self.doc = fitz.open("pdf", prev_bytes)
        self.is_modified = True
        return True

    def redo(self) -> bool:
        if not self.can_redo() or self.doc is None:
            return False
        current_bytes = self.doc.tobytes(garbage=0, deflate=False)
        self._undo_stack.append(current_bytes)
        next_bytes = self._redo_stack.pop()
        self.doc.close()
        self.doc = fitz.open("pdf", next_bytes)
        self.is_modified = True
        return True

    # -------------------- 儲存檔案 --------------------

    def save(self, target_path: Optional[str] = None) -> str:
        """儲存或另存 PDF（若覆寫原檔，採用暫存檔原子替換避免損毀）"""
        if self.doc is None:
            raise RuntimeError("尚未開啟任何 PDF 檔案")
        out_path = os.path.abspath(target_path or self.file_path or "")
        if not out_path:
            raise ValueError("未指定儲存路徑")

        if self.file_path and os.path.normcase(out_path) == os.path.normcase(self.file_path):
            tmp_path = out_path + ".tmp_saving.pdf"
            self.doc.save(tmp_path, garbage=2, deflate=True)
            self.doc.close()
            os.replace(tmp_path, out_path)
            self.doc = fitz.open(out_path)
        else:
            self.doc.save(out_path, garbage=2, deflate=True)
            self.file_path = out_path

        self.is_modified = False
        return out_path

    # -------------------- 渲染引擎（支援深色反相護眼模式） --------------------

    def render_page_pixmap(
        self,
        page_index: int,
        zoom: float = 1.0,
        invert_colors: bool = False,
        alpha: bool = False,
    ) -> fitz.Pixmap:
        """將指定頁碼渲染為 PyMuPDF Pixmap"""
        if self.doc is None:
            raise RuntimeError("尚未開啟 PDF")
        page = self.doc[page_index]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=alpha)
        if invert_colors:
            pix.invert_irect(pix.irect)
        return pix

    def get_page_size(self, page_index: int) -> Tuple[float, float]:
        """取得頁面在 72 DPI (1.0x) 下的寬高 (points)"""
        if self.doc is None or page_index < 0 or page_index >= len(self.doc):
            return (595.0, 842.0)
        rect = self.doc[page_index].rect
        return (rect.width, rect.height)

    # -------------------- 第一梯隊：頁面結構指針操作 --------------------

    def rotate_pages(self, page_indices: List[int], angle_delta: int = 90) -> None:
        """旋轉指定頁碼（+90, -90, 180），僅修改 Metadata，毫秒級完成"""
        if self.doc is None or not page_indices:
            return
        self.push_undo_snapshot()
        for idx in page_indices:
            if 0 <= idx < len(self.doc):
                page = self.doc[idx]
                new_rot = (page.rotation + angle_delta) % 360
                page.set_rotation(new_rot)
        self.is_modified = True

    def delete_pages(self, page_indices: List[int]) -> None:
        """刪除指定頁碼（至少保留 1 頁）"""
        if self.doc is None or not page_indices:
            return
        unique_indices = sorted(set(i for i in page_indices if 0 <= i < len(self.doc)), reverse=True)
        if len(unique_indices) >= len(self.doc):
            raise ValueError("無法刪除全部頁面，PDF 至少需保留一頁。")
        self.push_undo_snapshot()
        for idx in unique_indices:
            self.doc.delete_page(idx)
            self.ocr_page_cache.pop(idx, None)
        self.is_modified = True

    def extract_pages_to_file(self, page_indices: List[int], output_path: str) -> None:
        """擷取指定頁碼另存為新 PDF"""
        if self.doc is None or not page_indices:
            raise ValueError("未選擇要擷取的頁面")
        new_doc = fitz.open()
        for idx in page_indices:
            if 0 <= idx < len(self.doc):
                new_doc.insert_pdf(self.doc, from_page=idx, to_page=idx)
        new_doc.save(output_path, garbage=3, deflate=True)
        new_doc.close()

    def reorder_pages(self, new_order: List[int]) -> None:
        """依照新的頁碼索引順序重新排列頁面（用於左側縮圖拖曳排序）"""
        if self.doc is None:
            return
        if len(new_order) != len(self.doc) or set(new_order) != set(range(len(self.doc))):
            raise ValueError("頁面排序索引不完整")
        if new_order == list(range(len(self.doc))):
            return
        self.push_undo_snapshot()
        # 同步更新手動 OCR 快取的頁碼映射
        new_ocr_cache: Dict[int, List[Tuple[fitz.Rect, str]]] = {}
        for new_idx, old_idx in enumerate(new_order):
            if old_idx in self.ocr_page_cache:
                new_ocr_cache[new_idx] = self.ocr_page_cache[old_idx]
        self.ocr_page_cache = new_ocr_cache

        self.doc.select(new_order)
        self.is_modified = True

    def move_page(self, from_index: int, to_index: int) -> None:
        """移動單一頁面至新位置"""
        if self.doc is None:
            return
        n = len(self.doc)
        if not (0 <= from_index < n and 0 <= to_index < n) or from_index == to_index:
            return
        order = list(range(n))
        item = order.pop(from_index)
        order.insert(to_index, item)
        self.reorder_pages(order)

    def insert_blank_page(
        self,
        insert_at: int,
        width: Optional[float] = None,
        height: Optional[float] = None,
    ) -> None:
        """在指定索引處插入空白頁（預設同當前頁尺寸）"""
        if self.doc is None:
            return
        self.push_undo_snapshot()
        if width is None or height is None:
            ref_idx = min(max(0, insert_at), len(self.doc) - 1)
            w, h = self.get_page_size(ref_idx)
        else:
            w, h = width, height
        self.doc.new_page(pno=insert_at, width=w, height=h)
        self.is_modified = True

    def insert_external_pdf(
        self,
        source_pdf_path: str,
        insert_at: int,
        page_range: Optional[List[int]] = None,
    ) -> int:
        """將外部 PDF 的全部或指定頁面插入至當前文件的指定位置，回傳插入頁數"""
        if self.doc is None:
            return 0
        self.push_undo_snapshot()
        src_doc = fitz.open(source_pdf_path)
        inserted_count = 0
        try:
            if page_range is None:
                self.doc.insert_pdf(src_doc, start_at=insert_at)
                inserted_count = len(src_doc)
            else:
                pos = insert_at
                for p in page_range:
                    if 0 <= p < len(src_doc):
                        self.doc.insert_pdf(src_doc, from_page=p, to_page=p, start_at=pos)
                        pos += 1
                        inserted_count += 1
        finally:
            src_doc.close()
        if inserted_count > 0:
            self.is_modified = True
        return inserted_count

    @staticmethod
    def merge_pdfs(
        file_specs: List[Tuple[str, Optional[str]]],
        output_path: str,
    ) -> int:
        merged = fitz.open()
        try:
            for path, range_str in file_specs:
                src = fitz.open(path)
                try:
                    if not range_str or not range_str.strip():
                        merged.insert_pdf(src)
                    else:
                        indices = parse_page_range_string(range_str, len(src))
                        for idx in indices:
                            merged.insert_pdf(src, from_page=idx, to_page=idx)
                finally:
                    src.close()
            merged.save(output_path, garbage=3, deflate=True)
            total = len(merged)
        finally:
            merged.close()
        return total

    def split_pdf(
        self,
        output_dir: str,
        mode: str = "every_n",
        every_n: int = 1,
        custom_ranges: Optional[List[str]] = None,
    ) -> List[str]:
        if self.doc is None:
            raise RuntimeError("尚未開啟 PDF")
        os.makedirs(output_dir, exist_ok=True)
        base_name = os.path.splitext(os.path.basename(self.file_path or "document.pdf"))[0]
        created_files: List[str] = []
        total = len(self.doc)

        if mode == "every_n":
            step = max(1, every_n)
            for start in range(0, total, step):
                end = min(total - 1, start + step - 1)
                out_file = os.path.join(output_dir, f"{base_name}_第{start+1}-{end+1}頁.pdf")
                sub = fitz.open()
                sub.insert_pdf(self.doc, from_page=start, to_page=end)
                sub.save(out_file, garbage=2, deflate=True)
                sub.close()
                created_files.append(out_file)

        elif mode == "ranges" and custom_ranges:
            for i, r_str in enumerate(custom_ranges, 1):
                indices = parse_page_range_string(r_str, total)
                if not indices:
                    continue
                safe_label = r_str.strip().replace(" ", "").replace(",", "_")
                out_file = os.path.join(output_dir, f"{base_name}_part{i}_({safe_label}).pdf")
                sub = fitz.open()
                for idx in indices:
                    sub.insert_pdf(self.doc, from_page=idx, to_page=idx)
                sub.save(out_file, garbage=2, deflate=True)
                sub.close()
                created_files.append(out_file)

        elif mode == "bookmarks":
            toc = self.doc.get_toc()
            top_bookmarks = [(title, pno - 1) for lvl, title, pno in toc if lvl == 1 and 1 <= pno <= total]
            if not top_bookmarks:
                raise ValueError("此 PDF 沒有第一層書籤可供拆分。")
            for i, (title, start_idx) in enumerate(top_bookmarks):
                end_idx = (top_bookmarks[i + 1][1] - 1) if (i + 1 < len(top_bookmarks)) else (total - 1)
                end_idx = max(start_idx, end_idx)
                safe_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip() or f"章節{i+1}"
                out_file = os.path.join(output_dir, f"{base_name}_{i+1:02d}_{safe_title}.pdf")
                sub = fitz.open()
                sub.insert_pdf(self.doc, from_page=start_idx, to_page=end_idx)
                sub.save(out_file, garbage=2, deflate=True)
                sub.close()
                created_files.append(out_file)

        return created_files

    # -------------------- 手動 OCR 結果快取與寫入可搜尋文字層 --------------------

    def store_ocr_page_items(self, page_index: int, items: List[Tuple[fitz.Rect, str]]) -> None:
        """將手動 OCR 辨識出的 (PDF 座標矩形, 文字) 存入當前工作階段快取，立即可供搜尋文字功能使用"""
        self.ocr_page_cache[page_index] = items

    def embed_ocr_cache_into_pdf(self) -> int:
        """
        將目前已手動辨識的 OCR 快取文字，以「透明可搜尋文字層 (Invisible Searchable Text)」寫入 PDF 底層！
        寫入並存檔後，以後直接開啟此 PDF 就能直接搜尋與框選文字，不需再次 OCR。
        回傳寫入的頁數。
        """
        if self.doc is None or not self.ocr_page_cache:
            return 0
        self.push_undo_snapshot()
        font_path = get_system_cjk_font_path()
        font_obj = fitz.Font(fontfile=font_path) if font_path else fitz.Font("helv")
        embedded_pages = 0

        for p_idx, items in self.ocr_page_cache.items():
            if not (0 <= p_idx < len(self.doc)) or not items:
                continue
            page = self.doc[p_idx]
            # 使用極低不透明度寫入文字層，不影響原本圖面外觀，但可被 PDF 搜尋與選取
            tw = fitz.TextWriter(page.rect, opacity=0.01)
            for rect, text in items:
                if not text.strip():
                    continue
                fsize = max(6.0, min(rect.height * 0.85, 36.0))
                tw.append((rect.x0, rect.y1 - 1.5), text, font=font_obj, fontsize=fsize)
            tw.write_text(page)
            embedded_pages += 1

        if embedded_pages > 0:
            self.is_modified = True
        return embedded_pages

    # -------------------- 文字搜尋與選取複製（原生文字 + 已手動 OCR 快取） --------------------

    def search_in_page(self, page_index: int, keyword: str) -> List[fitz.Rect]:
        """在指定頁面搜尋關鍵字（搜尋原生文字 + 已手動 OCR 的快取文字，絕不自動觸發 OCR）"""
        if self.doc is None or not keyword.strip() or not (0 <= page_index < len(self.doc)):
            return []
        kw_lower = keyword.strip().lower()
        rects = list(self.doc[page_index].search_for(keyword))

        # 同時搜尋該頁已手動執行過 OCR 的快取
        if page_index in self.ocr_page_cache:
            for r, txt in self.ocr_page_cache[page_index]:
                if kw_lower in txt.lower():
                    # 避免與已嵌入的文字重複加入相同位置
                    if not any(abs(r.x0 - er.x0) < 4 and abs(r.y0 - er.y0) < 4 for er in rects):
                        rects.append(r)
        return rects

    def search_all_pages(self, keyword: str) -> List[Tuple[int, fitz.Rect]]:
        """全文件搜尋關鍵字，回傳 [(page_index, fitz.Rect), ...]"""
        if self.doc is None or not keyword.strip():
            return []
        results: List[Tuple[int, fitz.Rect]] = []
        for idx in range(len(self.doc)):
            for r in self.search_in_page(idx, keyword):
                results.append((idx, r))
        return results

    def search_all_pages_with_snippets(self, keyword: str) -> List[Tuple[int, fitz.Rect, str]]:
        """
        全文件搜尋關鍵字並附帶上下文摘要片段，供左側「搜尋文字」面板列表顯示。
        回傳: [(page_index, fitz.Rect, snippet_text), ...]
        """
        if self.doc is None or not keyword.strip():
            return []
        kw = keyword.strip()
        kw_lower = kw.lower()
        results: List[Tuple[int, fitz.Rect, str]] = []

        for idx in range(len(self.doc)):
            page = self.doc[idx]
            # 1. 原生文字搜尋
            native_rects = page.search_for(kw)
            if native_rects:
                blocks = page.get_text("blocks")
                for r in native_rects:
                    snippet = kw
                    for b in blocks:
                        brect = fitz.Rect(b[0], b[1], b[2], b[3])
                        if brect.intersects(r) and isinstance(b[4], str):
                            line_txt = " ".join(b[4].strip().splitlines())
                            snippet = line_txt[:60]
                            break
                    results.append((idx, r, snippet))

            # 2. 手動 OCR 快取搜尋
            if idx in self.ocr_page_cache:
                for r, txt in self.ocr_page_cache[idx]:
                    if kw_lower in txt.lower():
                        if not any(abs(r.x0 - er.x0) < 4 and abs(r.y0 - er.y0) < 4 for _, er, _ in results if _ == idx):
                            results.append((idx, r, f"[OCR] {txt[:60]}"))

        return results

    def extract_text_in_rect(self, page_index: int, pdf_rect: fitz.Rect) -> str:
        """擷取頁面指定矩形區域內的原生文字（若無原生文字則檢查手動 OCR 快取）"""
        if self.doc is None or not (0 <= page_index < len(self.doc)):
            return ""
        page = self.doc[page_index]
        native = page.get_text("text", clip=pdf_rect, sort=True).strip()
        if native:
            return native
        if page_index in self.ocr_page_cache:
            matched = [txt for r, txt in self.ocr_page_cache[page_index] if r.intersects(pdf_rect)]
            return "\n".join(matched).strip()
        return ""

    def get_page_words(self, page_index: int) -> List[Tuple[float, float, float, float, str]]:
        """取得頁面上所有文字區塊座標 (x0, y0, x1, y1, word) 供選取文字高亮使用"""
        if self.doc is None or not (0 <= page_index < len(self.doc)):
            return []
        words = [(w[0], w[1], w[2], w[3], w[4]) for w in self.doc[page_index].get_text("words")]
        if page_index in self.ocr_page_cache:
            for r, txt in self.ocr_page_cache[page_index]:
                words.append((r.x0, r.y0, r.x1, r.y1, txt))
        return words

    # -------------------- 圈選高解析截圖 + 一鍵去背 / 線條加深 --------------------

    def render_clip_high_dpi(
        self,
        page_index: int,
        pdf_rect: fitz.Rect,
        dpi: int = 300,
        transparent_bg: bool = False,
        enhance_lines: bool = False,
        white_threshold: int = 235,
    ) -> bytes:
        if self.doc is None or not (0 <= page_index < len(self.doc)):
            raise RuntimeError("無效的頁面")

        page = self.doc[page_index]
        scale = dpi / 72.0
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, clip=pdf_rect, alpha=False)

        if not transparent_bg and not enhance_lines:
            return pix.tobytes("png")

        import numpy as np
        from PIL import Image

        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        arr = np.array(img, dtype=np.uint8)

        luminance = (
            0.299 * arr[:, :, 0].astype(np.float32)
            + 0.587 * arr[:, :, 1].astype(np.float32)
            + 0.114 * arr[:, :, 2].astype(np.float32)
        )

        if enhance_lines:
            mask_ink = luminance < white_threshold
            for c in range(3):
                channel = arr[:, :, c].astype(np.float32)
                channel[mask_ink] = np.clip((channel[mask_ink] - 35.0) * 0.75, 0, 255)
                arr[:, :, c] = channel.astype(np.uint8)

        if transparent_bg:
            rgba = np.zeros((pix.height, pix.width, 4), dtype=np.uint8)
            rgba[:, :, :3] = arr
            alpha_channel = np.where(
                luminance >= white_threshold,
                0,
                np.where(
                    luminance >= white_threshold - 25,
                    ((white_threshold - luminance) / 25.0 * 255.0).clip(0, 255),
                    255,
                ),
            ).astype(np.uint8)
            rgba[:, :, 3] = alpha_channel
            out_img = Image.fromarray(rgba, mode="RGBA")
        else:
            out_img = Image.fromarray(arr, mode="RGB")

        buf = io.BytesIO()
        out_img.save(buf, format="PNG")
        return buf.getvalue()

    # -------------------- 疊加型編輯：加入文字 / 加入圖片 / 蓋章 --------------------

    def add_text_annotation_to_page(
        self,
        page_index: int,
        pdf_pos: Tuple[float, float],
        text: str,
        font_size: float = 14.0,
        color_rgb: Tuple[float, float, float] = (0.85, 0.05, 0.05),
        bg_color_rgb: Optional[Tuple[float, float, float]] = None,
        border_color_rgb: Optional[Tuple[float, float, float]] = None,
        record_undo: bool = True,
    ) -> None:
        if self.doc is None or not (0 <= page_index < len(self.doc)) or not text.strip():
            return
        if record_undo:
            self.push_undo_snapshot()

        page = self.doc[page_index]
        font_path = get_system_cjk_font_path()
        font_obj = fitz.Font(fontfile=font_path) if font_path else fitz.Font("helv")

        lines = text.splitlines()
        line_height = font_size * 1.28
        max_w = max((font_obj.text_length(line, fontsize=font_size) for line in lines), default=font_size)
        total_h = line_height * len(lines)

        x0, y0 = pdf_pos
        padding = 4.0
        box_rect = fitz.Rect(x0 - padding, y0 - padding, x0 + max_w + padding * 2, y0 + total_h + padding)

        if bg_color_rgb is not None or border_color_rgb is not None:
            shape = page.new_shape()
            shape.draw_rect(box_rect)
            shape.finish(
                color=border_color_rgb,
                fill=bg_color_rgb,
                width=1.0 if border_color_rgb else 0.0,
            )
            shape.commit()

        tw = fitz.TextWriter(page.rect)
        for i, line in enumerate(lines):
            baseline_y = y0 + (i + 1) * font_size + i * (line_height - font_size)
            tw.append((x0, baseline_y), line, font=font_obj, fontsize=font_size)
        tw.write_text(page, color=color_rgb)
        self.is_modified = True

    def add_image_to_page(
        self,
        page_index: int,
        pdf_rect: fitz.Rect,
        image_bytes_or_path: bytes | str,
        keep_proportion: bool = False,
        record_undo: bool = True,
    ) -> None:
        if self.doc is None or not (0 <= page_index < len(self.doc)):
            return
        if record_undo:
            self.push_undo_snapshot()
        page = self.doc[page_index]
        if isinstance(image_bytes_or_path, bytes):
            page.insert_image(pdf_rect, stream=image_bytes_or_path, keep_proportion=keep_proportion, overlay=True)
        else:
            page.insert_image(pdf_rect, filename=image_bytes_or_path, keep_proportion=keep_proportion, overlay=True)
        self.is_modified = True

    def draw_measurement_on_page(
        self,
        page_index: int,
        points: List[Tuple[float, float]],
        label_text: str,
        is_polygon: bool = False,
        color_rgb: Tuple[float, float, float] = (0.9, 0.1, 0.1),
    ) -> None:
        if self.doc is None or not (0 <= page_index < len(self.doc)) or len(points) < 2:
            return
        self.push_undo_snapshot()
        page = self.doc[page_index]
        shape = page.new_shape()
        fitz_pts = [fitz.Point(px, py) for px, py in points]
        if is_polygon and len(fitz_pts) >= 3:
            shape.draw_polyline(fitz_pts + [fitz_pts[0]])
            shape.finish(color=color_rgb, fill=(color_rgb[0], color_rgb[1], color_rgb[2]), fill_opacity=0.15, width=1.5)
        else:
            shape.draw_polyline(fitz_pts)
            shape.finish(color=color_rgb, width=1.8)
        shape.commit()

        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        self.add_text_annotation_to_page(
            page_index=page_index,
            pdf_pos=(cx, cy - 8),
            text=label_text,
            font_size=11.0,
            color_rgb=color_rgb,
            bg_color_rgb=(1.0, 1.0, 0.9),
            border_color_rgb=color_rgb,
            record_undo=False,
        )

    # -------------------- 批次重編頁碼 / 加浮水印 --------------------

    def batch_add_page_numbers(
        self,
        format_str: str = "第 {p} 頁 / 共 {n} 頁",
        position: str = "bottom_center",
        font_size: float = 10.5,
        start_number: int = 1,
        margin: float = 24.0,
        color_rgb: Tuple[float, float, float] = (0.2, 0.2, 0.2),
        clear_existing_area: bool = True,
    ) -> None:
        if self.doc is None or len(self.doc) == 0:
            return
        self.push_undo_snapshot()
        font_path = get_system_cjk_font_path()
        font_obj = fitz.Font(fontfile=font_path) if font_path else fitz.Font("helv")
        total = len(self.doc)

        for idx, page in enumerate(self.doc):
            p_num = start_number + idx
            text = format_str.replace("{p}", str(p_num)).replace("{n}", str(total + start_number - 1))
            text_w = font_obj.text_length(text, fontsize=font_size)
            rect = page.rect

            if "left" in position:
                x = rect.x0 + margin
            elif "right" in position:
                x = rect.x1 - margin - text_w
            else:
                x = rect.x0 + (rect.width - text_w) / 2.0

            if "top" in position:
                y = rect.y0 + margin + font_size
            else:
                y = rect.y1 - margin

            if clear_existing_area:
                pad_x, pad_y = 8.0, 4.0
                bg_rect = fitz.Rect(x - pad_x, y - font_size - pad_y, x + text_w + pad_x, y + pad_y + 2.0)
                shape = page.new_shape()
                shape.draw_rect(bg_rect)
                shape.finish(color=None, fill=(1.0, 1.0, 1.0))
                shape.commit()

            tw = fitz.TextWriter(rect)
            tw.append((x, y), text, font=font_obj, fontsize=font_size)
            tw.write_text(page, color=color_rgb)

        self.is_modified = True

    def batch_add_watermark(
        self,
        text: str,
        font_size: float = 42.0,
        angle: float = 35.0,
        opacity: float = 0.22,
        color_rgb: Tuple[float, float, float] = (0.6, 0.6, 0.6),
        tiled: bool = False,
    ) -> None:
        if self.doc is None or not text.strip():
            return
        self.push_undo_snapshot()
        font_path = get_system_cjk_font_path()
        font_obj = fitz.Font(fontfile=font_path) if font_path else fitz.Font("helv")

        for page in self.doc:
            rect = page.rect
            tw = fitz.TextWriter(rect, opacity=opacity, color=color_rgb)
            text_w = font_obj.text_length(text, fontsize=font_size)

            if tiled:
                step_x = max(text_w + 90.0, 220.0)
                step_y = max(font_size * 3.5, 160.0)
                y = rect.y0 + 60.0
                while y < rect.y1:
                    x = rect.x0 + 40.0
                    while x < rect.x1:
                        tw.append((x, y), text, font=font_obj, fontsize=font_size)
                        x += step_x
                    y += step_y
                center = fitz.Point(rect.width / 2.0, rect.height / 2.0)
                tw.write_text(page, morph=(center, fitz.Matrix(angle)))
            else:
                cx = rect.x0 + (rect.width - text_w) / 2.0
                cy = rect.y0 + (rect.height + font_size * 0.4) / 2.0
                pivot = fitz.Point(rect.width / 2.0, rect.height / 2.0)
                tw.append((cx, cy), text, font=font_obj, fontsize=font_size)
                tw.write_text(page, morph=(pivot, fitz.Matrix(angle)))

        self.is_modified = True

    # -------------------- 書籤（目錄 TOC）讀取與編輯 --------------------

    def get_toc(self) -> List[List[Any]]:
        if self.doc is None:
            return []
        return self.doc.get_toc(simple=True)

    def set_toc(self, toc_list: List[List[Any]]) -> None:
        if self.doc is None:
            return
        self.push_undo_snapshot()
        cleaned: List[List[Any]] = []
        prev_lvl = 1
        for item in toc_list:
            lvl = max(1, int(item[0]))
            if not cleaned:
                lvl = 1
            elif lvl > prev_lvl + 1:
                lvl = prev_lvl + 1
            prev_lvl = lvl
            title = str(item[1]).strip() or "未命名書籤"
            pno = min(max(1, int(item[2])), max(1, len(self.doc)))
            cleaned.append([lvl, title, pno])
        self.doc.set_toc(cleaned)
        self.is_modified = True


def parse_page_range_string(range_str: str, max_pages: int) -> List[int]:
    indices: List[int] = []
    parts = [p.strip() for p in range_str.replace("，", ",").split(",") if p.strip()]
    for part in parts:
        if "-" in part:
            sub = part.split("-", 1)
            try:
                start = int(sub[0].strip())
                end = int(sub[1].strip())
                step = 1 if end >= start else -1
                for p in range(start, end + step, step):
                    if 1 <= p <= max_pages:
                        indices.append(p - 1)
            except ValueError:
                continue
        else:
            try:
                p = int(part)
                if 1 <= p <= max_pages:
                    indices.append(p - 1)
            except ValueError:
                continue
    return indices


def generate_stamp_png_bytes(
    text: str,
    subtext: str = "",
    color_rgb: Tuple[int, int, int] = (210, 30, 30),
    shape: str = "rect",
) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    font_path = get_system_cjk_font_path()
    w, h = (360, 150) if subtext else (320, 110)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    r, g, b = color_rgb
    border_col = (r, g, b, 230)

    draw.rounded_rectangle([6, 6, w - 7, h - 7], radius=14, outline=border_col, width=6)
    draw.rounded_rectangle([14, 14, w - 15, h - 15], radius=9, outline=border_col, width=2)

    main_size = 44 if subtext else 48
    sub_size = 24
    try:
        main_font = ImageFont.truetype(font_path, main_size) if font_path else ImageFont.load_default()
        sub_font = ImageFont.truetype(font_path, sub_size) if font_path else ImageFont.load_default()
    except Exception:
        main_font = ImageFont.load_default()
        sub_font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), text, font=main_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if subtext:
        draw.text(((w - tw) / 2, 22), text, fill=border_col, font=main_font)
        draw.line([(24, 88), (w - 24, 88)], fill=border_col, width=2)
        sbbox = draw.textbbox((0, 0), subtext, font=sub_font)
        stw = sbbox[2] - sbbox[0]
        draw.text(((w - stw) / 2, 98), subtext, fill=border_col, font=sub_font)
    else:
        draw.text(((w - tw) / 2, (h - th) / 2 - 6), text, fill=border_col, font=main_font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
