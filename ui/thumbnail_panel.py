# -*- coding: utf-8 -*-
"""
左側導覽與管理面板 (LeftNavigationPanel)：
Tab 1 - 頁面縮圖：
  - 採用「可視範圍延遲載入 (Viewport Lazy Rendering)」，開啟千頁大檔也瞬間完成不卡頓
  - 支援三種拖放模式：
    1. 【同檔案內單頁/多頁拖曳排序】：按住 Ctrl 或 Shift 多選頁面後上下拖曳，顯示亮藍色插入線改變頁序
    2. 【跨視窗 / 跨檔案拖曳頁面】：從 A 視窗縮圖列選取單頁或多頁，直接拖過來到 B 視窗的縮圖列（或主畫面）任意位置插入！
    3. 【從電腦資料夾拖入外部 PDF】：直接從檔案總管把一或多個 .pdf 拖進縮圖列的任意兩頁之間插入！
Tab 2 - 書籤目錄 (TOC)：
  - 點擊跳轉章節、新增/修改/刪除書籤、調整階層、匯出與匯入目錄結構
Tab 3 - 搜尋文字：
  - 一開始即直接搜尋 PDF 內建文字與「已手動執行過 OCR 的快取文字」，絕不自動跑 OCR
"""

from __future__ import annotations
import os
import json
import tempfile
from typing import List, Set, Tuple, Optional
import fitz
from PySide6.QtCore import (
    Qt,
    QSize,
    QTimer,
    QPoint,
    QRect,
    QUrl,
    QMimeData,
    QByteArray,
    Signal,
    QItemSelectionModel,
)
from PySide6.QtGui import (
    QImage,
    QPixmap,
    QIcon,
    QColor,
    QPainter,
    QPen,
    QFont,
    QDrag,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QListWidget,
    QListWidgetItem,
    QAbstractItemView,
    QTreeWidget,
    QTreeWidgetItem,
    QPushButton,
    QLineEdit,
    QLabel,
    QMenu,
    QInputDialog,
    QFileDialog,
    QMessageBox,
)

from ui import theme

FASTPDF_MIME_TYPE = "application/x-fastpdf-pages"


class LazyThumbnailListWidget(QListWidget):
    """
    支援：
    1. 同視窗單頁/多頁選取上下拖曳改變頁序
    2. 跨視窗 / 跨程序拖曳選取頁面插入至另一份 PDF
    3. 從檔案總管拖入外部 .pdf 直接插入指定頁碼位置
    """

    # 同視窗改變頁序: (new_order: List[int], moved_new_rows: List[int])
    order_dropped = Signal(list, list)
    # 跨視窗頁面或外部 PDF 檔案拖入: (insert_at: int, pdf_paths: List[str], is_cross_window_pages: bool)
    external_pdfs_dropped = Signal(int, list, bool)
    viewport_resized = Signal()

    def __init__(self, engine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.setViewMode(QListWidget.ViewMode.IconMode)
        # LeftToRight + Wrapping=True + Adjust：窄面板時單欄垂直排列，拉寬面板時自動多欄並排！
        self.setFlow(QListWidget.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Static)
        self.setIconSize(QSize(116, 154))
        self.setGridSize(QSize(136, 182))
        self.setMinimumWidth(148)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

        # 關閉 Qt 內建 QListView 拖曳（避免清空多選或拒絕 Static 放置），改由自訂 OLE QDrag 與 Drop 事件處理
        self.setDragEnabled(False)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setSpacing(4)

        self._press_pos: Optional[QPoint] = None
        self._pressed_on_already_selected: bool = False
        self._clicked_item_on_press: Optional[QListWidgetItem] = None
        self._dragged_rows: List[int] = []
        self._drop_insert_index: Optional[int] = None
        self._drop_line_y: Optional[int] = None
        self._drop_vert_line: Optional[Tuple[int, int, int]] = None  # (x, top, bottom) 多欄模式垂直插入線
        self._drop_badge_text: str = ""

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.viewport_resized.emit()

    def _is_multi_column_mode(self) -> bool:
        if self.count() < 2:
            return False
        r0 = self.visualItemRect(self.item(0))
        r1 = self.visualItemRect(self.item(1))
        return abs(r0.center().y() - r1.center().y()) < 30

    def _compute_insert_index_and_y(self, pos: QPoint) -> Tuple[int, int]:
        """根據滑鼠在 viewport 的座標，計算要插入到哪一頁之前 (0 ~ count) 以及指示線位置（相容單欄與多欄並排）"""
        cnt = self.count()
        self._drop_vert_line = None
        if cnt == 0:
            return (0, 10)

        if not self._is_multi_column_mode():
            for i in range(cnt):
                rect = self.visualItemRect(self.item(i))
                mid_y = rect.center().y()
                if pos.y() < mid_y:
                    line_y = max(4, rect.top() - 3)
                    return (i, line_y)

            last_rect = self.visualItemRect(self.item(cnt - 1))
            return (cnt, last_rect.bottom() + 3)

        # 多欄網格模式：根據滑鼠所在列 (Row Y) 與欄 (Col X) 定位插入點
        for i in range(cnt):
            rect = self.visualItemRect(self.item(i))
            if pos.y() < rect.top() - 8:
                x = max(4, rect.left() - 3)
                self._drop_vert_line = (x, rect.top() + 4, rect.bottom() - 4)
                return (i, rect.center().y())
            if rect.top() - 8 <= pos.y() <= rect.bottom() + 8:
                if pos.x() < rect.center().x():
                    x = max(4, rect.left() - 3)
                    self._drop_vert_line = (x, rect.top() + 4, rect.bottom() - 4)
                    return (i, rect.center().y())
                # 若是該列最後一個項目且滑鼠在右半邊
                is_row_end = (i == cnt - 1) or (
                    abs(self.visualItemRect(self.item(i + 1)).center().y() - rect.center().y()) >= 30
                )
                if is_row_end and pos.x() <= rect.right() + 24:
                    x = min(self.viewport().width() - 4, rect.right() + 3)
                    self._drop_vert_line = (x, rect.top() + 4, rect.bottom() - 4)
                    return (i + 1, rect.center().y())

        last_rect = self.visualItemRect(self.item(cnt - 1))
        x = min(self.viewport().width() - 4, last_rect.right() + 3)
        self._drop_vert_line = (x, last_rect.top() + 4, last_rect.bottom() - 4)
        return (cnt, last_rect.center().y())

    # -------------------- 滑鼠按壓與啟動跨視窗/同視窗 OLE 拖曳 --------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            item = self.itemAt(pos)
            self._press_pos = pos
            self._clicked_item_on_press = item

            modifiers = event.modifiers()
            has_mod = bool(
                modifiers & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
            )

            # 若已多選多頁，且直接按左鍵在已選取的某頁上準備拖曳：保留多選狀態不清空
            if item is not None and item.isSelected() and not has_mod and len(self.selectedItems()) > 1:
                self._pressed_on_already_selected = True
                self._dragged_rows = sorted(set(self.row(it) for it in self.selectedItems()))
                event.accept()
                return

            self._pressed_on_already_selected = False
            super().mousePressEvent(event)
            self._dragged_rows = sorted(set(self.row(it) for it in self.selectedItems()))
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (event.buttons() & Qt.MouseButton.LeftButton) and self._press_pos is not None:
            pos = event.position().toPoint()
            if (pos - self._press_pos).manhattanLength() >= 6 and self._dragged_rows:
                rows_to_drag = sorted(set(self._dragged_rows))
                self._press_pos = None
                self._pressed_on_already_selected = False
                self._start_ole_page_drag(rows_to_drag)
                event.accept()
                return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = None
            if self._pressed_on_already_selected and self._clicked_item_on_press is not None:
                self._pressed_on_already_selected = False
                row = self.row(self._clicked_item_on_press)
                self.clearSelection()
                self.setCurrentRow(row)
                event.accept()
                return

        super().mouseReleaseEvent(event)

    def _start_ole_page_drag(self, rows: List[int]) -> None:
        """
        啟動系統級 QDrag：
        既可在同一個縮圖列內放開改變頁序，也可直接拖出視窗外丟進另一個 FastPDF 視窗！
        """
        if self.engine is None or self.engine.doc is None or not rows:
            return

        # 將選取的頁面極速匯出至暫存 PDF，供跨視窗或跨處理程序拖放直接讀取
        tmp_dir = os.path.join(tempfile.gettempdir(), "fastpdf_drag")
        os.makedirs(tmp_dir, exist_ok=True)
        tmp_pdf = os.path.join(tmp_dir, f"drag_{os.getpid()}_{id(self)}.pdf")
        try:
            self.engine.extract_pages_to_file(rows, tmp_pdf)
        except Exception:
            return

        payload = {
            "pid": os.getpid(),
            "widget_id": id(self),
            "rows": rows,
            "temp_pdf": tmp_pdf,
            "count": len(rows),
        }

        mime = QMimeData()
        mime.setData(FASTPDF_MIME_TYPE, QByteArray(json.dumps(payload).encode("utf-8")))
        mime.setUrls([QUrl.fromLocalFile(tmp_pdf)])

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._create_drag_cursor_pixmap(rows))
        drag.setHotSpot(QPoint(24, 20))
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)

        # 拖曳結束後清除基準線
        self._drop_insert_index = None
        self._drop_line_y = None
        self.viewport().update()

    def _create_drag_cursor_pixmap(self, rows: List[int]) -> QPixmap:
        """產生跟隨滑鼠游標的半透明縮圖與頁數提示圖示"""
        pix = QPixmap(145, 44)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(theme.qcolor("accent", 235))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRect(2, 2, 141, 40), 8, 8)
        painter.setPen(theme.qcolor("on-accent"))
        painter.setFont(theme.ui_font("body", bold=True))
        label = f"拖曳 {len(rows)} 頁" if len(rows) > 1 else f"拖曳第 {rows[0] + 1} 頁"
        painter.drawText(QRect(2, 2, 141, 40), Qt.AlignmentFlag.AlignCenter, label)
        painter.end()
        return pix

    # -------------------- 接收同視窗、跨視窗與外部檔案總管 Drop 事件 --------------------

    @staticmethod
    def _extract_valid_pdf_urls(mime: QMimeData) -> List[str]:
        if not mime.hasUrls():
            return []
        paths = []
        for u in mime.urls():
            local = u.toLocalFile()
            if local and local.lower().endswith(".pdf") and os.path.exists(local):
                paths.append(local)
        return paths

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasFormat(FASTPDF_MIME_TYPE) or self._extract_valid_pdf_urls(mime):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:
        mime = event.mimeData()
        has_internal = mime.hasFormat(FASTPDF_MIME_TYPE)
        pdf_urls = self._extract_valid_pdf_urls(mime)
        if not has_internal and not pdf_urls:
            event.ignore()
            return

        pos = event.position().toPoint()
        ins_idx, line_y = self._compute_insert_index_and_y(pos)
        self._drop_insert_index = ins_idx
        self._drop_line_y = line_y

        if has_internal:
            try:
                data = json.loads(bytes(mime.data(FASTPDF_MIME_TYPE)).decode("utf-8"))
                cnt = data.get("count", 1)
                is_same = data.get("pid") == os.getpid() and data.get("widget_id") == id(self)
                if is_same:
                    self._drop_badge_text = f"移動 {cnt} 頁至此處"
                else:
                    self._drop_badge_text = f"從其他視窗插入 {cnt} 頁到這裡"
            except Exception:
                self._drop_badge_text = "插入頁面到這裡"
        else:
            self._drop_badge_text = f"插入 {len(pdf_urls)} 個 PDF 檔到這裡"

        # 靠近上下邊緣時自動捲動縮圖列
        vbar = self.verticalScrollBar()
        if pos.y() < 40:
            vbar.setValue(vbar.value() - 16)
        elif pos.y() > self.viewport().height() - 40:
            vbar.setValue(vbar.value() + 16)

        self.viewport().update()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._drop_insert_index = None
        self._drop_line_y = None
        self._drop_vert_line = None
        self.viewport().update()
        event.accept()

    def dropEvent(self, event) -> None:
        mime = event.mimeData()
        pos = event.position().toPoint()
        insert_pos, _ = self._compute_insert_index_and_y(pos)

        self._drop_insert_index = None
        self._drop_line_y = None
        self._drop_vert_line = None
        self.viewport().update()

        # 1. 來自 FastPDF 縮圖列的拖曳（同視窗排序 或 跨視窗頁面插入）
        if mime.hasFormat(FASTPDF_MIME_TYPE):
            try:
                data = json.loads(bytes(mime.data(FASTPDF_MIME_TYPE)).decode("utf-8"))
                is_same_list = data.get("pid") == os.getpid() and data.get("widget_id") == id(self)
                dragged_rows = sorted(set(int(r) for r in data.get("rows", [])))
                temp_pdf = data.get("temp_pdf", "")

                if is_same_list:
                    total = self.count()
                    remaining = [i for i in range(total) if i not in dragged_rows]
                    target_slot = sum(1 for i in remaining if i < insert_pos)
                    new_order = remaining[:target_slot] + dragged_rows + remaining[target_slot:]
                    moved_new_rows = list(range(target_slot, target_slot + len(dragged_rows)))
                    if new_order != list(range(total)):
                        self.order_dropped.emit(new_order, moved_new_rows)
                else:
                    if temp_pdf and os.path.exists(temp_pdf):
                        self.external_pdfs_dropped.emit(insert_pos, [temp_pdf], True)

                event.acceptProposedAction()
                return
            except Exception:
                pass

        # 2. 來自 Windows 檔案總管拖入的外部 .pdf 檔案
        pdf_paths = self._extract_valid_pdf_urls(mime)
        if pdf_paths:
            self.external_pdfs_dropped.emit(insert_pos, pdf_paths, False)
            event.acceptProposedAction()
            return

        event.ignore()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_line_y is not None:
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            w = self.viewport().width()
            y = self._drop_line_y

            pen = QPen(theme.qcolor("accent"), 4.0)
            painter.setPen(pen)
            if self._drop_vert_line is not None:
                vx, vtop, vbot = self._drop_vert_line
                painter.drawLine(vx, vtop, vx, vbot)
                painter.setBrush(theme.qcolor("accent"))
                painter.drawEllipse(QPoint(vx, vtop), 5, 5)
                painter.drawEllipse(QPoint(vx, vbot), 5, 5)
                center_x = vx
            else:
                painter.drawLine(8, y, w - 8, y)
                painter.setBrush(theme.qcolor("accent"))
                painter.drawEllipse(QPoint(10, y), 5, 5)
                painter.drawEllipse(QPoint(w - 10, y), 5, 5)
                center_x = w // 2

            badge_text = self._drop_badge_text or "在此處插入"
            badge_w = min(w - 12, max(116, len(badge_text) * 12))
            badge_h = 24
            bx = max(4, min(center_x - badge_w // 2, w - badge_w - 4))
            by = max(2, min(y - badge_h // 2, self.viewport().height() - badge_h - 2))
            badge_rect = QRect(bx, by, badge_w, badge_h)

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.qcolor("accent", 240))
            painter.drawRoundedRect(badge_rect, 6, 6)

            painter.setPen(theme.qcolor("on-accent"))
            painter.setFont(theme.ui_font("caption", bold=True))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)
            painter.end()


class LeftNavigationPanel(QWidget):
    """包含「頁面縮圖」、「書籤目錄」、「搜尋文字」的左側面板（支援縮至單欄極窄寬度，或拉寬自動多欄排列）"""

    page_selected = Signal(int)
    pages_rotate_requested = Signal(list, int)
    pages_delete_requested = Signal(list)
    pages_extract_requested = Signal(list)
    pages_reorder_requested = Signal(list, list)        # (new_order, moved_new_rows)
    external_pdfs_dropped = Signal(int, list, bool)     # (insert_at, pdf_paths, is_cross_window_pages)
    insert_blank_requested = Signal(int)
    insert_pdf_requested = Signal(int)
    toc_modified = Signal()
    search_keyword_requested = Signal(str)
    search_match_clicked = Signal(int)
    full_ocr_requested = Signal()

    def __init__(self, engine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self._rendered_thumbs: Set[int] = set()
        self._placeholder_icon = self._create_placeholder_icon()
        theme.signals().changed.connect(self._on_theme_changed)
        self._suppress_selection_signal = False
        self.setMinimumWidth(154)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(150)
        self.tabs.setUsesScrollButtons(False)
        self.tabs.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabBar().setObjectName("navTabBar")
        layout.addWidget(self.tabs)

        # -------- Tab 1: 頁面縮圖 --------
        self.thumb_tab = QWidget()
        t_layout = QVBoxLayout(self.thumb_tab)
        t_layout.setContentsMargins(3, 3, 3, 3)
        t_layout.setSpacing(3)

        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(2)
        self.btn_up = QPushButton()
        theme.bind_icon(self.btn_up, "chevron-down", 180)
        self.btn_up.setToolTip("選取的頁面往前移")
        self.btn_down = QPushButton()
        theme.bind_icon(self.btn_down, "chevron-down")
        self.btn_down.setToolTip("選取的頁面往後移")
        self.btn_rot_l = QPushButton("左轉")
        self.btn_rot_l.setToolTip("選取的頁面向左旋轉 90°")
        self.btn_rot_r = QPushButton("右轉")
        self.btn_rot_r.setToolTip("選取的頁面向右旋轉 90°")
        self.btn_del = QPushButton()
        theme.bind_icon(self.btn_del, "trash")
        self.btn_del.setToolTip("刪除選取的頁面（可以按 Ctrl+Z 復原）")

        for b in (self.btn_up, self.btn_down, self.btn_rot_l, self.btn_rot_r, self.btn_del):
            b.setMinimumWidth(24)
            b.setStyleSheet("padding: 3px 4px;")
            btn_bar.addWidget(b)
        t_layout.addLayout(btn_bar)

        hint_lbl = QLabel("面板可以拉寬成多欄；拖曳縮圖可以調整頁序，或拖到其他視窗")
        hint_lbl.setWordWrap(True)
        hint_lbl.setMinimumWidth(130)
        hint_lbl.setProperty("muted", True)
        hint_lbl.setStyleSheet("padding: 1px 2px;")
        t_layout.addWidget(hint_lbl)

        self.thumb_list = LazyThumbnailListWidget(self.engine, self)
        self.thumb_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t_layout.addWidget(self.thumb_list)
        self.tabs.addTab(self.thumb_tab, "縮圖")

        # -------- Tab 2: 書籤目錄 (TOC) --------
        self.toc_tab = QWidget()
        b_layout = QVBoxLayout(self.toc_tab)
        b_layout.setContentsMargins(3, 3, 3, 3)
        b_layout.setSpacing(3)

        toc_btn_row1 = QHBoxLayout()
        toc_btn_row1.setSpacing(2)
        self.btn_toc_add = QPushButton("+書籤")
        self.btn_toc_sub = QPushButton("+子節")
        self.btn_toc_edit = QPushButton("編輯")
        self.btn_toc_edit.setToolTip("編輯選取的書籤名稱與頁碼")
        self.btn_toc_del = QPushButton()
        theme.bind_icon(self.btn_toc_del, "trash")
        self.btn_toc_del.setToolTip("刪除選取的書籤")
        for b in (self.btn_toc_add, self.btn_toc_sub, self.btn_toc_edit, self.btn_toc_del):
            b.setMinimumWidth(24)
            b.setStyleSheet("padding: 3px 4px;")
            toc_btn_row1.addWidget(b)
        b_layout.addLayout(toc_btn_row1)

        toc_btn_row2 = QHBoxLayout()
        toc_btn_row2.setSpacing(2)
        self.btn_toc_export = QPushButton("匯出")
        self.btn_toc_import = QPushButton("匯入")
        for b in (self.btn_toc_export, self.btn_toc_import):
            b.setMinimumWidth(40)
            b.setStyleSheet("padding: 3px 4px;")
            toc_btn_row2.addWidget(b)
        b_layout.addLayout(toc_btn_row2)

        self.toc_tree = QTreeWidget()
        self.toc_tree.setHeaderLabels(["章節標題", "頁碼"])
        self.toc_tree.setColumnWidth(0, 105)
        self.toc_tree.setColumnWidth(1, 36)
        self.toc_tree.setMinimumWidth(130)
        self.toc_tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        b_layout.addWidget(self.toc_tree)
        self.tabs.addTab(self.toc_tab, "書籤")

        # -------- Tab 3: 搜尋文字 --------
        self.search_tab = QWidget()
        s_layout = QVBoxLayout(self.search_tab)
        s_layout.setContentsMargins(4, 4, 4, 4)
        s_layout.setSpacing(4)

        s_input_row = QHBoxLayout()
        s_input_row.setSpacing(2)
        self.txt_panel_search = QLineEdit()
        self.txt_panel_search.setMinimumWidth(70)
        self.txt_panel_search.setPlaceholderText("搜尋文字")
        self.txt_panel_search.returnPressed.connect(self._trigger_panel_search)
        self.btn_panel_search = QPushButton()
        theme.bind_icon(self.btn_panel_search, "search")
        self.btn_panel_search.setToolTip("搜尋（Enter）")
        self.btn_panel_search.setMinimumWidth(28)
        self.btn_panel_search.clicked.connect(self._trigger_panel_search)
        s_input_row.addWidget(self.txt_panel_search, stretch=1)
        s_input_row.addWidget(self.btn_panel_search)
        s_layout.addLayout(s_input_row)

        self.lbl_search_summary = QLabel("直接搜尋內嵌文字（不自動跑 OCR）")
        self.lbl_search_summary.setWordWrap(True)
        self.lbl_search_summary.setMinimumWidth(130)
        self.lbl_search_summary.setProperty("muted", True)
        s_layout.addWidget(self.lbl_search_summary)

        self.search_result_list = QListWidget()
        self.search_result_list.setMinimumWidth(130)
        self.search_result_list.currentRowChanged.connect(self._on_search_item_clicked)
        s_layout.addWidget(self.search_result_list, stretch=1)

        self.btn_manual_ocr_for_search = QPushButton("辨識整份文件後再搜尋")
        self.btn_manual_ocr_for_search.setMinimumWidth(120)
        self.btn_manual_ocr_for_search.setToolTip("掃描檔搜尋不到字時，先用文字辨識（OCR）辨識整份文件")
        self.btn_manual_ocr_for_search.clicked.connect(self.full_ocr_requested.emit)
        s_layout.addWidget(self.btn_manual_ocr_for_search)

        self.tabs.addTab(self.search_tab, "搜尋")

        # 延遲渲染計時器
        self._lazy_timer = QTimer(self)
        self._lazy_timer.setSingleShot(True)
        self._lazy_timer.setInterval(30)
        self._lazy_timer.timeout.connect(self._render_visible_thumbnails)

        # 事件綁定
        self.thumb_list.verticalScrollBar().valueChanged.connect(lambda _: self._lazy_timer.start())
        self.thumb_list.viewport_resized.connect(lambda: self._lazy_timer.start())
        self.thumb_list.currentRowChanged.connect(self._on_thumb_row_changed)
        self.thumb_list.customContextMenuRequested.connect(self._show_thumb_context_menu)
        self.thumb_list.order_dropped.connect(self.pages_reorder_requested.emit)
        self.thumb_list.external_pdfs_dropped.connect(self.external_pdfs_dropped.emit)

        self.btn_up.clicked.connect(lambda: self._move_selected_pages(-1))
        self.btn_down.clicked.connect(lambda: self._move_selected_pages(1))
        self.btn_rot_l.clicked.connect(lambda: self.pages_rotate_requested.emit(self.selected_page_indices(), -90))
        self.btn_rot_r.clicked.connect(lambda: self.pages_rotate_requested.emit(self.selected_page_indices(), 90))
        self.btn_del.clicked.connect(lambda: self.pages_delete_requested.emit(self.selected_page_indices()))

        self.toc_tree.itemClicked.connect(self._on_toc_item_clicked)
        self.btn_toc_add.clicked.connect(lambda: self._add_bookmark(as_child=False))
        self.btn_toc_sub.clicked.connect(lambda: self._add_bookmark(as_child=True))
        self.btn_toc_edit.clicked.connect(self._edit_selected_bookmark)
        self.btn_toc_del.clicked.connect(self._delete_selected_bookmark)
        self.btn_toc_export.clicked.connect(self._export_bookmarks)
        self.btn_toc_import.clicked.connect(self._import_bookmarks)

        self._current_active_page: int = 0

    def _on_theme_changed(self, _name: str) -> None:
        self._placeholder_icon = self._create_placeholder_icon()

    @staticmethod
    def _create_placeholder_icon() -> QIcon:
        pix = QPixmap(120, 160)
        pix.fill(theme.qcolor("bg"))
        painter = QPainter(pix)
        painter.setPen(theme.qcolor("line"))
        painter.drawRect(0, 0, 119, 159)
        painter.setPen(theme.qcolor("muted"))
        painter.setFont(theme.ui_font("caption"))
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "載入中...")
        painter.end()
        return QIcon(pix)

    # -------------------- 搜尋面板互動 --------------------

    def _trigger_panel_search(self) -> None:
        kw = self.txt_panel_search.text().strip()
        self.search_keyword_requested.emit(kw)

    def populate_search_results(
        self,
        keyword: str,
        matches_with_snippets: List[Tuple[int, fitz.Rect, str]],
        active_index: int = 0,
    ) -> None:
        self.txt_panel_search.blockSignals(True)
        self.txt_panel_search.setText(keyword)
        self.txt_panel_search.blockSignals(False)

        self.search_result_list.blockSignals(True)
        self.search_result_list.clear()

        if not keyword:
            self.lbl_search_summary.setText("請輸入關鍵字進行搜尋（預設僅搜尋原生文字與已手動 OCR 之頁面）")
            self.search_result_list.blockSignals(False)
            return

        if not matches_with_snippets:
            ocr_cnt = len(self.engine.ocr_page_cache) if self.engine else 0
            hint = f"（已辨識 {ocr_cnt:,} 頁）" if ocr_cnt > 0 else "。掃描檔可以按下方按鈕先辨識整份文件"
            self.lbl_search_summary.setText(f"找不到「{keyword}」{hint}")
            self.search_result_list.blockSignals(False)
            return

        self.lbl_search_summary.setText(f"找到 {len(matches_with_snippets):,} 筆「{keyword}」，點一下跳過去：")
        for idx, (p_idx, _rect, snippet) in enumerate(matches_with_snippets):
            item = QListWidgetItem(f"第 {p_idx + 1} 頁｜{snippet}")
            item.setData(Qt.ItemDataRole.UserRole, idx)
            self.search_result_list.addItem(item)

        if 0 <= active_index < self.search_result_list.count():
            self.search_result_list.setCurrentRow(active_index)
        self.search_result_list.blockSignals(False)

    def set_active_search_row(self, match_index: int) -> None:
        if 0 <= match_index < self.search_result_list.count():
            self.search_result_list.blockSignals(True)
            self.search_result_list.setCurrentRow(match_index)
            self.search_result_list.scrollToItem(self.search_result_list.item(match_index))
            self.search_result_list.blockSignals(False)

    def _on_search_item_clicked(self, row: int) -> None:
        if row >= 0:
            self.search_match_clicked.emit(row)

    # -------------------- 縮圖延遲載入與多頁選取同步 --------------------

    def reload_all(self, active_page: int = 0, selected_rows: Optional[List[int]] = None) -> None:
        self._current_active_page = active_page
        self._suppress_selection_signal = True
        self.thumb_list.clear()
        self._rendered_thumbs.clear()

        if self.engine.doc is not None:
            for i in range(self.engine.page_count):
                item = QListWidgetItem(self._placeholder_icon, f"第 {i + 1} 頁")
                item.setData(Qt.ItemDataRole.UserRole, i)
                item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
                self.thumb_list.addItem(item)

            if selected_rows:
                self.thumb_list.clearSelection()
                for r in selected_rows:
                    if 0 <= r < self.thumb_list.count():
                        self.thumb_list.item(r).setSelected(True)
                first_r = selected_rows[0]
                if 0 <= first_r < self.thumb_list.count():
                    self.thumb_list.setCurrentItem(
                        self.thumb_list.item(first_r),
                        QItemSelectionModel.SelectionFlag.NoUpdate,
                    )
                    self.thumb_list.scrollToItem(self.thumb_list.item(first_r))
            elif 0 <= active_page < self.thumb_list.count():
                self.thumb_list.setCurrentRow(active_page)

        self._suppress_selection_signal = False
        self._lazy_timer.start()
        self.reload_toc()

    def set_active_page(self, page_index: int) -> None:
        self._current_active_page = page_index
        if not (0 <= page_index < self.thumb_list.count()):
            return
        if self.thumb_list.currentRow() == page_index:
            return
        self._suppress_selection_signal = True
        if len(self.thumb_list.selectedItems()) <= 1:
            self.thumb_list.setCurrentRow(page_index)
        else:
            self.thumb_list.setCurrentItem(
                self.thumb_list.item(page_index),
                QItemSelectionModel.SelectionFlag.NoUpdate,
            )
        self.thumb_list.scrollToItem(self.thumb_list.item(page_index))
        self._suppress_selection_signal = False
        self._lazy_timer.start()

    def invalidate_pages(self, page_indices: List[int]) -> None:
        for idx in page_indices:
            self._rendered_thumbs.discard(idx)
        self._lazy_timer.start()

    def _render_visible_thumbnails(self) -> None:
        if self.engine.doc is None or self.thumb_list.count() == 0:
            return
        viewport_rect = self.thumb_list.viewport().rect().adjusted(0, -240, 0, 240)
        rendered_in_batch = 0

        for i in range(self.thumb_list.count()):
            if i in self._rendered_thumbs:
                continue
            item = self.thumb_list.item(i)
            item_rect = self.thumb_list.visualItemRect(item)
            if viewport_rect.intersects(item_rect):
                self._render_single_thumb(i, item)
                self._rendered_thumbs.add(i)
                rendered_in_batch += 1
                if rendered_in_batch >= 10:
                    self._lazy_timer.start()
                    break

    def _render_single_thumb(self, page_idx: int, item: QListWidgetItem) -> None:
        if self.engine.doc is None or not (0 <= page_idx < self.engine.page_count):
            return
        pw, ph = self.engine.get_page_size(page_idx)
        scale = min(120.0 / max(1.0, pw), 160.0 / max(1.0, ph))
        pix = self.engine.render_page_pixmap(page_idx, zoom=scale, invert_colors=False, alpha=False)
        qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        qpix = QPixmap.fromImage(qimg)
        item.setIcon(QIcon(qpix))

    def selected_page_indices(self) -> List[int]:
        indices = [self.thumb_list.row(it) for it in self.thumb_list.selectedItems()]
        if not indices and self.thumb_list.currentRow() >= 0:
            indices = [self.thumb_list.currentRow()]
        return sorted(set(indices))

    def _on_thumb_row_changed(self, row: int) -> None:
        if not self._suppress_selection_signal and row >= 0:
            self._current_active_page = row
            self.page_selected.emit(row)

    def _move_selected_pages(self, delta: int) -> None:
        if self.engine.doc is None:
            return
        selected = self.selected_page_indices()
        if not selected:
            return
        total = self.engine.page_count
        if delta < 0 and selected[0] == 0:
            return
        if delta > 0 and selected[-1] >= total - 1:
            return

        remaining = [i for i in range(total) if i not in selected]
        if delta < 0:
            insert_slot = max(0, sum(1 for i in remaining if i < selected[0]) - 1)
        else:
            insert_slot = min(len(remaining), sum(1 for i in remaining if i < selected[-1]) + 1)

        new_order = remaining[:insert_slot] + selected + remaining[insert_slot:]
        moved_new_rows = list(range(insert_slot, insert_slot + len(selected)))
        self.pages_reorder_requested.emit(new_order, moved_new_rows)

    def _show_thumb_context_menu(self, pos) -> None:
        if self.engine.doc is None:
            return
        selected = self.selected_page_indices()
        if not selected:
            return
        count_label = f"選取的 {len(selected)} 頁" if len(selected) > 1 else f"第 {selected[0] + 1} 頁"

        menu = QMenu(self)
        act_rot_r = menu.addAction(f"向右旋轉 90°（{count_label}）")
        act_rot_l = menu.addAction(f"向左旋轉 90°（{count_label}）")
        act_rot_180 = menu.addAction(f"旋轉 180°（{count_label}）")
        menu.addSeparator()
        act_ins_blank = menu.addAction(f"在第 {selected[-1] + 1} 頁後面插入空白頁")
        act_ins_pdf = menu.addAction(f"在第 {selected[-1] + 1} 頁後面插入其他 PDF…")
        menu.addSeparator()
        act_extract = menu.addAction(f"擷取{count_label}另存新檔…")
        act_delete = menu.addAction(theme.icon("trash"), f"刪除{count_label}")

        chosen = menu.exec(self.thumb_list.viewport().mapToGlobal(pos))
        if chosen == act_rot_r:
            self.pages_rotate_requested.emit(selected, 90)
        elif chosen == act_rot_l:
            self.pages_rotate_requested.emit(selected, -90)
        elif chosen == act_rot_180:
            self.pages_rotate_requested.emit(selected, 180)
        elif chosen == act_ins_blank:
            self.insert_blank_requested.emit(selected[-1] + 1)
        elif chosen == act_ins_pdf:
            self.insert_pdf_requested.emit(selected[-1] + 1)
        elif chosen == act_extract:
            self.pages_extract_requested.emit(selected)
        elif chosen == act_delete:
            self.pages_delete_requested.emit(selected)

    # -------------------- 書籤目錄 (TOC) 管理 --------------------

    def reload_toc(self) -> None:
        self.toc_tree.clear()
        if self.engine.doc is None:
            return
        toc = self.engine.get_toc()
        stack: List[Tuple[int, QTreeWidgetItem]] = []
        for lvl, title, pno in toc:
            node = QTreeWidgetItem([title, str(pno)])
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            if not stack:
                self.toc_tree.addTopLevelItem(node)
            else:
                stack[-1][1].addChild(node)
            stack.append((lvl, node))
        self.toc_tree.expandAll()

    def _collect_toc_from_tree(self) -> List[List]:
        toc_list: List[List] = []

        def traverse(item: QTreeWidgetItem, level: int) -> None:
            title = item.text(0).strip() or "未命名章節"
            try:
                pno = int(item.text(1))
            except ValueError:
                pno = 1
            toc_list.append([level, title, pno])
            for i in range(item.childCount()):
                traverse(item.child(i), level + 1)

        for i in range(self.toc_tree.topLevelItemCount()):
            traverse(self.toc_tree.topLevelItem(i), 1)
        return toc_list

    def _save_tree_to_engine(self) -> None:
        if self.engine.doc is None:
            return
        toc_list = self._collect_toc_from_tree()
        self.engine.set_toc(toc_list)
        self.toc_modified.emit()

    def _on_toc_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        try:
            pno = int(item.text(1))
            self.page_selected.emit(max(0, pno - 1))
        except ValueError:
            pass

    def _add_bookmark(self, as_child: bool = False) -> None:
        if self.engine.doc is None:
            return
        default_page = self._current_active_page + 1
        title, ok = QInputDialog.getText(self, "新增書籤", f"請輸入書籤章節名稱（指向第 {default_page} 頁）：")
        if not ok or not title.strip():
            return
        new_item = QTreeWidgetItem([title.strip(), str(default_page)])
        curr = self.toc_tree.currentItem()
        if as_child and curr is not None:
            curr.addChild(new_item)
            curr.setExpanded(True)
        elif curr is not None and curr.parent() is not None:
            curr.parent().addChild(new_item)
        else:
            self.toc_tree.addTopLevelItem(new_item)
        self._save_tree_to_engine()

    def _edit_selected_bookmark(self) -> None:
        curr = self.toc_tree.currentItem()
        if curr is None or self.engine.doc is None:
            return
        new_title, ok1 = QInputDialog.getText(self, "修改書籤名稱", "章節標題：", text=curr.text(0))
        if not ok1 or not new_title.strip():
            return
        try:
            old_p = int(curr.text(1))
        except ValueError:
            old_p = 1
        new_page, ok2 = QInputDialog.getInt(
            self, "修改指向頁碼", "對應頁碼：", value=old_p, minValue=1, maxValue=max(1, self.engine.page_count)
        )
        if not ok2:
            return
        curr.setText(0, new_title.strip())
        curr.setText(1, str(new_page))
        self._save_tree_to_engine()

    def _delete_selected_bookmark(self) -> None:
        curr = self.toc_tree.currentItem()
        if curr is None:
            return
        parent = curr.parent()
        if parent is not None:
            parent.removeChild(curr)
        else:
            idx = self.toc_tree.indexOfTopLevelItem(curr)
            self.toc_tree.takeTopLevelItem(idx)
        self._save_tree_to_engine()

    def _export_bookmarks(self) -> None:
        if self.engine.doc is None:
            return
        toc = self._collect_toc_from_tree()
        if not toc:
            QMessageBox.information(self, "匯出書籤", "目前沒有任何書籤可匯出。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "匯出書籤目錄", "bookmarks.json", "JSON 書籤檔 (*.json);;純文字目錄 (*.txt)"
        )
        if not path:
            return
        if path.lower().endswith(".txt"):
            lines = [f"{'  ' * (lvl - 1)}{title} .... 第 {pno} 頁" for lvl, title, pno in toc]
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        else:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(toc, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "匯出完成", f"已匯出 {len(toc)} 筆書籤至：\n{path}")

    def _import_bookmarks(self) -> None:
        if self.engine.doc is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "匯入書籤目錄", "", "JSON 書籤檔 (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                toc_data = json.load(f)
            if isinstance(toc_data, list):
                self.engine.set_toc(toc_data)
                self.reload_toc()
                self.toc_modified.emit()
        except Exception as e:
            QMessageBox.warning(self, "匯入失敗", f"無法讀取書籤檔案：{e}")
