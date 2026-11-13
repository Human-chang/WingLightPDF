# -*- coding: utf-8 -*-
"""
主視窗 (PDFMainWindow) — 極速單視窗多分頁 & 多視窗雙棲模式
支援：
- 「多個 PDF 開在同一個視窗」開關：可將多個 PDF 顯示在同一個程式視窗的分頁列中，也可隨時切換為獨立視窗模式
- 分頁自由拖拉：
  1. 把分頁往外拖出空白處，自動拆出成兩個獨立程式視窗
  2. 把 A 視窗的分頁拖進 B 視窗，自動合併至同一個程式視窗的多分頁下
- 左側縮圖列支援拉窄成單欄，或拉寬自動多排並列
- 支援直接拖放 (Drag & Drop) PDF 檔案進視窗開啟或插入
- 一鍵註冊 Windows PDF 預設開啟關聯 (WingLightPDF.exe)
- 淺色、深色兩套主題（WingLight 設計規範，見 ui/theme.py）
- 搜尋文字功能：預設直接搜尋內嵌文字與「已手動執行過 OCR 的快取文字」，絕不自動跑 OCR
"""

from __future__ import annotations
import os
import json
from typing import List, Optional, Tuple
import fitz

from PySide6.QtCore import Qt, QSize, QPoint, QRect, QMimeData, QByteArray, QUrl, QEvent
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QKeySequence,
    QImage,
    QPixmap,
    QPainter,
    QPen,
    QFont,
    QPageLayout,
    QColor,
    QDrag,
    QCursor,
    QIcon,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QToolBar,
    QStatusBar,
    QSplitter,
    QTabWidget,
    QTabBar,
    QLabel,
    QLineEdit,
    QSpinBox,
    QComboBox,
    QPushButton,
    QToolButton,
    QMenu,
    QFileDialog,
    QInputDialog,
    QMessageBox,
    QSizePolicy,
)

from core.pdf_engine import PDFEngine, parse_page_range_string
from ui.canvas_view import PDFCanvasView
from ui.thumbnail_panel import LeftNavigationPanel
from ui.stamp_panel import StampBoxPanel
from ui import theme
from ui.status_line import StatusBar

FASTPDF_TAB_MIME_TYPE = "application/x-fastpdf-doctab"


class PDFDocumentTab(QWidget):
    """單一 PDF 文件分頁容器（擁有獨立的 PDFEngine、縮圖導覽面板、畫布與搜尋狀態，可跨視窗無損搬移）"""

    def __init__(self, host_window: "PDFMainWindow") -> None:
        super().__init__(host_window)
        self.host_window: "PDFMainWindow" = host_window
        self.engine = PDFEngine()
        self.search_matches: List[Tuple[int, fitz.Rect, str]] = []
        self.search_cursor: int = -1
        self.last_search_kw: str = ""

        self.canvas = PDFCanvasView(self.engine, self)
        self.left_panel = LeftNavigationPanel(self.engine, self)

        self.splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.splitter.addWidget(self.left_panel)
        self.splitter.addWidget(self.canvas)
        # 預設左側縮圖為單欄緊湊寬度 (168px)，拉寬時自動變多欄並排！
        self.splitter.setSizes([168, 980])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.splitter)

        # 訊號透過 self.host_window 動態轉發，支援分頁跨視窗搬移時無縫接軌
        self.canvas.zoom_changed.connect(lambda z: self.host_window._on_canvas_zoom_changed(z))
        self.canvas.status_message.connect(lambda msg, kind: self.host_window.status_bar.show_status(msg, kind))
        self.canvas.page_modified.connect(lambda: self.host_window._on_document_modified())
        self.canvas.request_page_step.connect(lambda d: self.host_window.step_page(d))
        self.canvas.request_ocr_bytes.connect(lambda b, t: self.host_window._launch_ondemand_ocr_dialog(b, t))
        self.canvas.tool_mode_changed.connect(lambda m: self.host_window._sync_toolbar_mode_buttons(m))

        self.left_panel.page_selected.connect(lambda p: self.host_window.go_to_page(p))
        self.left_panel.pages_rotate_requested.connect(lambda idxs, a: self.host_window.action_rotate_pages(idxs, a))
        self.left_panel.pages_delete_requested.connect(lambda idxs: self.host_window.action_delete_pages(idxs))
        self.left_panel.pages_extract_requested.connect(
            lambda idxs: self.host_window.action_extract_selected_pages(idxs)
        )
        self.left_panel.pages_reorder_requested.connect(
            lambda order, moved: self.host_window.action_reorder_pages(order, moved)
        )
        self.left_panel.external_pdfs_dropped.connect(
            lambda ins, paths, cross: self.host_window.action_insert_dropped_pdfs(ins, paths, cross)
        )
        self.left_panel.insert_blank_requested.connect(lambda ins: self.host_window._insert_blank_at(ins))
        self.left_panel.insert_pdf_requested.connect(lambda ins: self.host_window._insert_pdf_at(ins))
        self.left_panel.toc_modified.connect(lambda: self.host_window._on_document_modified())
        self.left_panel.search_keyword_requested.connect(lambda kw: self.host_window.execute_keyword_search(kw))
        self.left_panel.search_match_clicked.connect(lambda idx: self.host_window.jump_to_search_index(idx))
        self.left_panel.full_ocr_requested.connect(lambda: self.host_window.action_ocr_full_document())

    def tab_display_title(self) -> str:
        if self.engine.doc is None:
            return "新分頁（未開啟）"
        fname = os.path.basename(self.engine.file_path or "未命名.pdf")
        star = " *" if self.engine.is_modified else ""
        return f"{fname}{star}"


class DraggableDocTabBar(QTabBar):
    """
    支援 Chrome 風格拖拉的 PDF 文件分頁列：
    1. 把分頁往外拖出，自動拆出成獨立的 WingLightPDF 視窗（一個程式拆成兩個程式）
    2. 把分頁拖到另一個 WingLightPDF 視窗，自動合併進該視窗的分頁列
    3. 拖曳縮圖頁面經過分頁標籤時，自動切換至該分頁以便跨分頁插入頁面
    """

    def __init__(self, host_window: "PDFMainWindow", parent=None) -> None:
        super().__init__(parent)
        self.host_window = host_window
        self.setAcceptDrops(True)
        self.setMovable(True)
        self.setTabsClosable(True)
        self.setExpanding(False)
        self.setElideMode(Qt.TextElideMode.ElideMiddle)
        self._press_pos: Optional[QPoint] = None
        self._pressed_tab_index: int = -1

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.position().toPoint()
            self._pressed_tab_index = self.tabAt(self._press_pos)
        elif event.button() == Qt.MouseButton.MiddleButton:
            idx = self.tabAt(event.position().toPoint())
            if idx >= 0:
                self.host_window.close_doc_tab(idx)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if (
            (event.buttons() & Qt.MouseButton.LeftButton)
            and self._press_pos is not None
            and self._pressed_tab_index >= 0
        ):
            pos = event.position().toPoint()
            # 當滑鼠拖出分頁列上下範圍超過 28px 或左右超出範圍時，啟動跨視窗分頁拖曳 (Tear-off / Merge)
            margin_rect = self.rect().adjusted(-20, -28, 20, 28)
            if not margin_rect.contains(pos):
                tab_idx = self.currentIndex() if self.currentIndex() >= 0 else self._pressed_tab_index
                self._press_pos = None
                self._pressed_tab_index = -1
                self._start_tab_drag(tab_idx)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._press_pos = None
        self._pressed_tab_index = -1
        super().mouseReleaseEvent(event)

    def _start_tab_drag(self, tab_index: int) -> None:
        doc_tab = self.host_window.get_doc_tab(tab_index)
        if doc_tab is None:
            return

        title = doc_tab.tab_display_title()
        payload = {
            "pid": os.getpid(),
            "source_win_id": id(self.host_window),
            "tab_id": id(doc_tab),
            "title": title,
            "file_path": doc_tab.engine.file_path or "",
        }
        mime = QMimeData()
        mime.setData(FASTPDF_TAB_MIME_TYPE, QByteArray(json.dumps(payload).encode("utf-8")))
        if doc_tab.engine.file_path and os.path.exists(doc_tab.engine.file_path):
            mime.setUrls([QUrl.fromLocalFile(doc_tab.engine.file_path)])

        PDFMainWindow._tab_drag_adopted = False
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self._create_tab_drag_pixmap(title))
        drag.setHotSpot(QPoint(36, 18))
        drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction, Qt.DropAction.MoveAction)

        # 若已經被目標視窗的 dropEvent 接收合併，即完成
        if PDFMainWindow._tab_drag_adopted:
            return

        global_pos = QCursor.pos()
        # 檢查放開滑鼠時，是否落在另一個開啟中的 PDFMainWindow 視窗範圍內，直接合併進該視窗！
        for other_win in list(PDFMainWindow._open_windows):
            if other_win is not self.host_window and other_win.isVisible():
                if other_win.frameGeometry().contains(global_pos):
                    other_win.adopt_tab_from_window(self.host_window, doc_tab)
                    other_win.activateWindow()
                    other_win.raise_()
                    return

        # 若放開在視窗外（或非分頁列區域），且目前視窗有 2 個以上分頁，拆出成獨立的新視窗！
        local_in_bar = self.mapFromGlobal(global_pos)
        if not self.rect().adjusted(-20, -30, 20, 30).contains(local_in_bar):
            if self.host_window.doc_tabs.count() > 1:
                self.host_window.detach_tab_to_new_window(doc_tab, global_pos)

    @staticmethod
    def _create_tab_drag_pixmap(title: str) -> QPixmap:
        pix = QPixmap(240, 42)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(theme.qcolor("accent", 238))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRect(2, 2, 236, 38), 8, 8)
        painter.setPen(theme.qcolor("on-accent"))
        painter.setFont(theme.ui_font("body", bold=True))
        painter.drawText(QRect(10, 2, 220, 38), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, title)
        painter.end()
        return pix

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if (
            mime.hasFormat(FASTPDF_TAB_MIME_TYPE)
            or mime.hasFormat("application/x-fastpdf-pages")
            or mime.hasUrls()
        ):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        mime = event.mimeData()
        pos = event.position().toPoint()
        hover_idx = self.tabAt(pos)
        # 當使用者拖曳縮圖頁面經過某個分頁標籤時，自動切換過去，方便直接把 A 分頁的頁面拖進 B 分頁！
        if mime.hasFormat("application/x-fastpdf-pages") and hover_idx >= 0 and hover_idx != self.currentIndex():
            self.setCurrentIndex(hover_idx)
        event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        mime = event.mimeData()
        pos = event.position().toPoint()
        target_idx = self.tabAt(pos)

        # 1. 接收來自另一個視窗拖過來的 PDF 分頁，合併至本視窗分頁列
        if mime.hasFormat(FASTPDF_TAB_MIME_TYPE):
            if self.host_window._handle_doctab_mime_drop(mime, insert_index=target_idx):
                event.acceptProposedAction()
                return

        # 2. 接收縮圖頁面直接丟在某個分頁標籤上，插入至該分頁末尾
        if mime.hasFormat("application/x-fastpdf-pages"):
            if target_idx >= 0:
                self.setCurrentIndex(target_idx)
            try:
                data = json.loads(bytes(mime.data("application/x-fastpdf-pages")).decode("utf-8"))
                temp_pdf = data.get("temp_pdf", "")
                is_same_list = (
                    data.get("pid") == os.getpid()
                    and data.get("widget_id") == id(self.host_window.left_panel.thumb_list)
                )
                if not is_same_list and temp_pdf and os.path.exists(temp_pdf):
                    ins_at = self.host_window.engine.page_count if self.host_window.engine.doc else 0
                    self.host_window.action_insert_dropped_pdfs(ins_at, [temp_pdf], is_cross_window_pages=True)
                    event.acceptProposedAction()
                    return
            except Exception:
                pass

        # 3. 接收外部 .pdf 檔案丟到分頁列上，直接開新分頁
        if mime.hasUrls():
            pdf_paths = [
                u.toLocalFile()
                for u in mime.urls()
                if u.toLocalFile().lower().endswith(".pdf") and os.path.exists(u.toLocalFile())
            ]
            if pdf_paths:
                for p in pdf_paths:
                    self.host_window.open_pdf_in_new_tab(p)
                event.acceptProposedAction()
                return

        super().dropEvent(event)


class PDFMainWindow(QMainWindow):
    """PDF 極速檢視與簡易編輯器主視窗（支援同視窗多分頁 & 多視窗拖拉合併/拆出）"""

    _open_windows: List["PDFMainWindow"] = []
    # 全域偏好：是否將多份 PDF 顯示在同一個程式視窗的分頁下（預設開啟）
    multi_tab_mode: bool = True
    _tab_drag_adopted: bool = False
    # 最後一個被使用者點選的視窗：從檔案總管再開 PDF 時加到這裡
    _last_active: Optional["PDFMainWindow"] = None

    def __init__(
        self,
        initial_pdf_path: Optional[str] = None,
        startup_ms: Optional[float] = None,
        _create_initial_tab: bool = True,
    ) -> None:
        super().__init__()
        theme.ensure_applied()
        PDFMainWindow._open_windows.append(self)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self.setWindowTitle("WingLightPDF — 輕快免安裝PDF檢視與編輯工具")
        self.resize(1420, 860)
        self.setAcceptDrops(True)

        import sys
        from PySide6.QtGui import QIcon
        if getattr(sys, "frozen", False):
            self.app_root = os.path.dirname(os.path.abspath(sys.executable))
        else:
            self.app_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        icon_file = os.path.join(self.app_root, "assets", "app_icon.ico")
        if os.path.exists(icon_file):
            self.setWindowIcon(QIcon(icon_file))
        stamps_dir = os.path.join(self.app_root, "stamps")
        self.stamp_panel = StampBoxPanel(stamps_dir=stamps_dir, parent=self)
        self.stamp_panel.setVisible(False)

        # 建立多 PDF 文件分頁區 (QTabWidget + 自訂可拖拉 DraggableDocTabBar)
        self.doc_tabs = QTabWidget(self)
        self.doc_tab_bar = DraggableDocTabBar(self, self.doc_tabs)
        self.doc_tab_bar.setObjectName("docTabBar")
        self.doc_tabs.setTabBar(self.doc_tab_bar)
        self.doc_tabs.setDocumentMode(True)
        self.doc_tabs.setMovable(True)
        self.doc_tabs.setTabsClosable(True)
        self.doc_tabs.currentChanged.connect(self._on_current_doc_tab_changed)
        self.doc_tabs.tabCloseRequested.connect(self.close_doc_tab)

        # 分頁列右側快捷按鈕：「開新分頁」與「拆出為獨立視窗」
        corner_bar = QWidget(self.doc_tabs)
        c_layout = QHBoxLayout(corner_bar)
        c_layout.setContentsMargins(4, 2, 6, 2)
        c_layout.setSpacing(4)

        self.btn_new_tab_corner = QPushButton("開新分頁")
        theme.bind_icon(self.btn_new_tab_corner, "plus")
        self.btn_new_tab_corner.setToolTip("在目前視窗新增一個 PDF 分頁 (Ctrl+T)")
        self.btn_new_tab_corner.setFlat(True)
        self.btn_new_tab_corner.clicked.connect(self.action_open_in_new_tab)

        self.btn_detach_tab_corner = QPushButton("拆出為獨立視窗")
        theme.bind_icon(self.btn_detach_tab_corner, "external")
        self.btn_detach_tab_corner.setToolTip("將目前分頁拆出成另一個獨立的 WingLightPDF 視窗（也可直接用滑鼠把分頁標籤往外拖出）")
        self.btn_detach_tab_corner.setFlat(True)
        self.btn_detach_tab_corner.clicked.connect(self.action_detach_current_tab)

        c_layout.addWidget(self.btn_new_tab_corner)
        c_layout.addWidget(self.btn_detach_tab_corner)
        self.doc_tabs.setCornerWidget(corner_bar, Qt.Corner.TopRightCorner)

        # 主分割版面：左側/中間為多文件分頁區 | 右側為常用圖章匣
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.main_splitter.addWidget(self.doc_tabs)
        self.main_splitter.addWidget(self.stamp_panel)
        self.main_splitter.setSizes([1200, 220])
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)
        self.setCentralWidget(self.main_splitter)

        if _create_initial_tab:
            self._create_and_add_doc_tab()

        self._build_menus_and_toolbars()
        self._build_statusbar(startup_ms)
        self._connect_signals()

        if initial_pdf_path and os.path.exists(initial_pdf_path):
            self.load_pdf_file(initial_pdf_path)

    # -------------------- 動態屬性代理至當前選取的 PDFDocumentTab --------------------

    @property
    def current_doc_tab(self) -> PDFDocumentTab:
        w = self.doc_tabs.currentWidget()
        if isinstance(w, PDFDocumentTab):
            return w
        if self.doc_tabs.count() > 0:
            w0 = self.doc_tabs.widget(0)
            if isinstance(w0, PDFDocumentTab):
                return w0
        return self._create_and_add_doc_tab()

    def get_doc_tab(self, index: int) -> Optional[PDFDocumentTab]:
        w = self.doc_tabs.widget(index)
        return w if isinstance(w, PDFDocumentTab) else None

    @property
    def engine(self) -> PDFEngine:
        return self.current_doc_tab.engine

    @property
    def canvas(self) -> PDFCanvasView:
        return self.current_doc_tab.canvas

    @property
    def left_panel(self) -> LeftNavigationPanel:
        return self.current_doc_tab.left_panel

    @property
    def _search_matches(self) -> List[Tuple[int, fitz.Rect, str]]:
        return self.current_doc_tab.search_matches

    @_search_matches.setter
    def _search_matches(self, value: List[Tuple[int, fitz.Rect, str]]) -> None:
        self.current_doc_tab.search_matches = value

    @property
    def _search_cursor(self) -> int:
        return self.current_doc_tab.search_cursor

    @_search_cursor.setter
    def _search_cursor(self, value: int) -> None:
        self.current_doc_tab.search_cursor = value

    @property
    def _last_search_kw(self) -> str:
        return self.current_doc_tab.last_search_kw

    @_last_search_kw.setter
    def _last_search_kw(self, value: str) -> None:
        self.current_doc_tab.last_search_kw = value

    # -------------------- 分頁新增、切換、關閉、拖出拆分、拖入合併 --------------------

    def _create_and_add_doc_tab(self, make_current: bool = True) -> PDFDocumentTab:
        tab = PDFDocumentTab(self)
        idx = self.doc_tabs.addTab(tab, theme.icon("file"), tab.tab_display_title())
        self.doc_tabs.setTabToolTip(idx, "可按住此分頁標籤往外拖出拆成兩個視窗，或拖進另一個視窗合併")
        if make_current:
            self.doc_tabs.setCurrentIndex(idx)
        return tab

    def _refresh_tab_titles(self) -> None:
        for i in range(self.doc_tabs.count()):
            tab = self.get_doc_tab(i)
            if tab is not None:
                self.doc_tabs.setTabText(i, tab.tab_display_title())
                tip = tab.engine.file_path or "未開啟檔案"
                self.doc_tabs.setTabToolTip(
                    i, f"{tip}\n按住分頁往外拖可以拆成獨立視窗，拖進其他視窗可以合併"
                )
        if hasattr(self, "btn_detach_tab_corner"):
            self.btn_detach_tab_corner.setEnabled(self.doc_tabs.count() > 1)

    def _on_current_doc_tab_changed(self, index: int) -> None:
        if index < 0 or not hasattr(self, "act_toggle_left"):
            return
        tab = self.get_doc_tab(index)
        if tab is None:
            return
        self.act_toggle_left.blockSignals(True)
        self.act_toggle_left.setChecked(not tab.left_panel.isHidden())
        self.act_toggle_left.blockSignals(False)

        self.act_invert.blockSignals(True)
        self.act_invert.setChecked(tab.canvas.invert_colors)
        self.act_invert.blockSignals(False)

        self.combo_zoom.blockSignals(True)
        self.combo_zoom.setCurrentText(f"{tab.canvas.zoom * 100:.0f}%")
        self.combo_zoom.blockSignals(False)

        self.txt_search.blockSignals(True)
        self.txt_search.setText(tab.last_search_kw)
        self.txt_search.blockSignals(False)

        total_m = len(tab.search_matches)
        if total_m > 0 and 0 <= tab.search_cursor < total_m:
            self.lbl_search_count.setText(f"{tab.search_cursor + 1}／{total_m}")
        else:
            self.lbl_search_count.setText("0／0")

        self._sync_toolbar_mode_buttons(tab.canvas.tool_mode)
        self._update_ui_state()

    def close_doc_tab(self, index: int) -> bool:
        tab = self.get_doc_tab(index)
        if tab is None:
            return False

        if tab.engine.is_modified:
            self.doc_tabs.setCurrentIndex(index)
            fname = os.path.basename(tab.engine.file_path or "未命名.pdf")
            ans = QMessageBox.question(
                self,
                "尚未儲存的變更",
                f"分頁「{fname}」有尚未儲存的編輯變更，是否在關閉前儲存？",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if ans == QMessageBox.StandardButton.Cancel:
                return False
            if ans == QMessageBox.StandardButton.Save:
                if not self.action_save_file():
                    return False

        tab.engine.close()
        self.doc_tabs.removeTab(index)
        tab.deleteLater()

        # 若關掉最後一個分頁，保留一個空白分頁供繼續使用
        if self.doc_tabs.count() == 0:
            self._create_and_add_doc_tab(make_current=True)
        self._update_ui_state()
        return True

    def detach_tab_to_new_window(self, doc_tab: PDFDocumentTab, global_pos: Optional[QPoint] = None) -> Optional["PDFMainWindow"]:
        """將指定分頁從目前視窗拆出成為一個全新的獨立 PDFMainWindow"""
        if self.doc_tabs.count() <= 1:
            self.status_bar.showMessage("目前視窗只有 1 個分頁，不用拆出")
            return None

        idx = self.doc_tabs.indexOf(doc_tab)
        if idx < 0:
            return None

        self.doc_tabs.removeTab(idx)
        new_win = PDFMainWindow(_create_initial_tab=False)
        new_win.adopt_tab_widget(doc_tab)
        if global_pos is not None:
            new_win.move(max(20, global_pos.x() - 120), max(20, global_pos.y() - 25))
        else:
            new_win.move(self.x() + 40, self.y() + 40)
        new_win.show()
        new_win.activateWindow()
        new_win.raise_()

        self._update_ui_state()
        self.status_bar.show_status(f"已將「{doc_tab.tab_display_title()}」拆出為獨立視窗（可以隨時拖回分頁列合併）", "ok")
        return new_win

    def action_detach_current_tab(self) -> None:
        if self.doc_tabs.count() <= 1:
            QMessageBox.information(
                self,
                "拆出分頁提示",
                "目前視窗只有 1 個分頁。\n當您開啟 2 個以上 PDF 分頁時，即可點擊此按鈕或直接把分頁往外拖出成兩個視窗！",
            )
            return
        self.detach_tab_to_new_window(self.current_doc_tab)

    def adopt_tab_widget(self, doc_tab: PDFDocumentTab, insert_index: int = -1) -> None:
        """將一個 PDFDocumentTab 掛載進本視窗的分頁列（保留所有開啟狀態與未儲存編輯）"""
        # 若本視窗目前只有一個空白未開啟的分頁，直接替換掉該空白分頁
        empty_tab_to_remove: Optional[int] = None
        if self.doc_tabs.count() == 1:
            first_tab = self.get_doc_tab(0)
            if first_tab is not None and first_tab.engine.doc is None and not first_tab.engine.is_modified:
                empty_tab_to_remove = 0

        doc_tab.host_window = self
        if 0 <= insert_index < self.doc_tabs.count():
            new_idx = self.doc_tabs.insertTab(insert_index, doc_tab, doc_tab.tab_display_title())
        else:
            new_idx = self.doc_tabs.addTab(doc_tab, doc_tab.tab_display_title())
        self.doc_tabs.setCurrentIndex(new_idx)

        if empty_tab_to_remove is not None and self.doc_tabs.count() > 1:
            rem_idx = self.doc_tabs.indexOf(first_tab)
            if rem_idx >= 0:
                self.doc_tabs.removeTab(rem_idx)
                first_tab.deleteLater()

        self._on_current_doc_tab_changed(self.doc_tabs.currentIndex())
        self._update_ui_state()

    def adopt_tab_from_window(
        self,
        source_win: "PDFMainWindow",
        doc_tab: PDFDocumentTab,
        insert_index: int = -1,
    ) -> bool:
        """從另一個 PDFMainWindow 將分頁移入本視窗合併；若來源視窗已無分頁則自動關閉來源視窗"""
        if source_win is self:
            return False
        src_idx = source_win.doc_tabs.indexOf(doc_tab)
        if src_idx < 0:
            return False

        PDFMainWindow._tab_drag_adopted = True
        source_win.doc_tabs.removeTab(src_idx)
        self.adopt_tab_widget(doc_tab, insert_index=insert_index)

        if source_win.doc_tabs.count() == 0:
            source_win.close()
        else:
            source_win._update_ui_state()

        self.status_bar.show_status(f"已將「{doc_tab.tab_display_title()}」合併到這個視窗", "ok")
        return True

    def _handle_doctab_mime_drop(self, mime: QMimeData, insert_index: int = -1) -> bool:
        try:
            data = json.loads(bytes(mime.data(FASTPDF_TAB_MIME_TYPE)).decode("utf-8"))
        except Exception:
            return False

        pid = data.get("pid")
        source_win_id = data.get("source_win_id")
        tab_id = data.get("tab_id")
        file_path = data.get("file_path", "")

        # 同一處理程序內的兩個視窗：直接轉移記憶體中的 PDFDocumentTab 物件（0 延遲、保留未儲存變更）
        if pid == os.getpid():
            for w in list(PDFMainWindow._open_windows):
                if id(w) == source_win_id:
                    if w is self:
                        # 同視窗分頁拖曳換位
                        for i in range(self.doc_tabs.count()):
                            t = self.get_doc_tab(i)
                            if t is not None and id(t) == tab_id:
                                if insert_index >= 0 and insert_index != i:
                                    self.doc_tab_bar.moveTab(i, insert_index)
                                return True
                        return False
                    for i in range(w.doc_tabs.count()):
                        t = w.get_doc_tab(i)
                        if t is not None and id(t) == tab_id:
                            return self.adopt_tab_from_window(w, t, insert_index=insert_index)
        # 跨處理程序視窗：以檔案路徑開啟為新分頁
        if file_path and os.path.exists(file_path):
            PDFMainWindow._tab_drag_adopted = True
            self.open_pdf_in_new_tab(file_path)
            return True
        return False

    def closeEvent(self, event) -> None:
        # 逐一檢查所有分頁是否有未儲存變更
        for i in range(self.doc_tabs.count()):
            tab = self.get_doc_tab(i)
            if tab is not None and tab.engine.is_modified:
                self.doc_tabs.setCurrentIndex(i)
                fname = os.path.basename(tab.engine.file_path or "未命名.pdf")
                ans = QMessageBox.question(
                    self,
                    "尚未儲存的變更",
                    f"分頁「{fname}」有尚未儲存的編輯變更，是否在關閉前儲存？",
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Save,
                )
                if ans == QMessageBox.StandardButton.Cancel:
                    event.ignore()
                    return
                if ans == QMessageBox.StandardButton.Save:
                    if not self.action_save_file():
                        event.ignore()
                        return

        for i in range(self.doc_tabs.count()):
            tab = self.get_doc_tab(i)
            if tab is not None:
                tab.engine.close()

        if self in PDFMainWindow._open_windows:
            PDFMainWindow._open_windows.remove(self)
        super().closeEvent(event)

    # -------------------- 介面與工具列建置 --------------------

    def _action(self, menu: QMenu, text: str, slot=None, shortcut=None, icon: str = "", icon_text: str = "",
                tip: str = "", checkable: bool = False, checked: bool = False) -> QAction:
        """選單項目：文字帶快速鍵字母，icon 用規範的線條圖示（沒有對應圖示的只放文字）。"""
        act = QAction(text, self)
        if icon:
            theme.bind_icon(act, icon)
        if icon_text:
            act.setIconText(icon_text)  # 工具列上的短名稱
        if shortcut is not None:
            act.setShortcut(QKeySequence(shortcut))
        if tip:
            act.setToolTip(tip)
        if checkable:
            act.setCheckable(True)
            act.setChecked(checked)  # 先設好初始狀態再連接，建立時不觸發動作
        if slot is not None:
            (act.toggled if checkable else act.triggered).connect(slot)
        menu.addAction(act)
        return act

    def _build_menus_and_toolbars(self) -> None:
        menubar = self.menuBar()
        A = self._action

        # 1. 檔案
        m = menubar.addMenu("檔案(&F)")
        act_open = A(m, "開啟 PDF 檔案(&O)…", self.action_open_file, QKeySequence.StandardKey.Open,
                     "folder-open", "開啟", "開啟 PDF 檔案（Ctrl+O）")
        act_open_tab = A(m, "在新分頁開啟(&T)…", self.action_open_in_new_tab, "Ctrl+T", "plus", "新分頁",
                         "在目前視窗的新分頁開啟 PDF（Ctrl+T）")
        A(m, "在新視窗開啟(&N)…", self.action_open_in_new_window, "Ctrl+N", "external")
        A(m, "將目前分頁拆出為獨立視窗(&D)", self.action_detach_current_tab, "Ctrl+Shift+N", "external")
        self.act_multi_tab_toggle = A(m, "多個 PDF 開在同一個視窗(&M)", self._on_multi_tab_mode_toggled,
                                      checkable=True, checked=PDFMainWindow.multi_tab_mode)
        m.addSeparator()
        act_save = A(m, "儲存檔案(&S)", self.action_save_file, QKeySequence.StandardKey.Save, "save", "儲存",
                     "儲存檔案（Ctrl+S）")
        A(m, "另存新檔(&A)…", self.action_save_as_file, "Ctrl+Shift+S")
        m.addSeparator()
        act_print = A(m, "列印(&P)…", self.action_print_pdf, QKeySequence.StandardKey.Print, icon_text="列印",
                      tip="列印（Ctrl+P）")
        m.addSeparator()
        A(m, "設為 Windows 預設 PDF 開啟程式(&W)…", self.action_register_default_pdf_viewer)
        m.addSeparator()
        A(m, "關閉目前分頁(&C)", lambda: self.close_doc_tab(self.doc_tabs.currentIndex()), "Ctrl+W", "close")
        A(m, "結束視窗(&X)", self.close, "Ctrl+Q")

        # 2. 編輯與搜尋
        m = menubar.addMenu("編輯與搜尋(&E)")
        self.act_undo = A(m, "復原(&U)", self.action_undo, QKeySequence.StandardKey.Undo, icon_text="復原",
                          tip="復原上一步（Ctrl+Z）")
        self.act_redo = A(m, "重做(&R)", self.action_redo, QKeySequence.StandardKey.Redo, icon_text="重做",
                          tip="重做（Ctrl+Y）")
        m.addSeparator()
        A(m, "搜尋文件內文字(&F)…", self.action_focus_search, QKeySequence.StandardKey.Find, "search")
        A(m, "尋找下一個(&N)", self.action_search_next, "F3")
        A(m, "尋找上一個(&P)", self.action_search_prev, "Shift+F3")
        m.addSeparator()
        A(m, "複製目前整頁文字(&C)", self.action_copy_whole_page_text, icon="copy")

        # 3. 頁面操作
        m = menubar.addMenu("頁面操作(&P)")
        act_rot_l = A(m, "向左旋轉 90°(&L)", lambda: self.action_rotate_current(-90), "Ctrl+Left",
                      icon_text="左轉", tip="向左旋轉 90°（Ctrl+左方向鍵）")
        act_rot_r = A(m, "向右旋轉 90°(&R)", lambda: self.action_rotate_current(90), "Ctrl+Right",
                      icon_text="右轉", tip="向右旋轉 90°（Ctrl+右方向鍵）")
        A(m, "旋轉 180°(&O)", lambda: self.action_rotate_current(180))
        m.addSeparator()
        A(m, "插入空白頁(&B)", self.action_insert_blank_page)
        A(m, "插入其他 PDF 的頁面(&I)…", self.action_insert_external_pdf)
        A(m, "擷取頁面另存新檔(&E)…", self.action_extract_pages_dialog)
        act_delete = A(m, "刪除目前頁面(&D)", self.action_delete_current_page, "Ctrl+Delete", "trash", "刪頁",
                       "刪除目前頁面（Ctrl+Delete，可以按 Ctrl+Z 復原）")
        m.addSeparator()
        act_merge = A(m, "合併多個 PDF 檔案(&M)…", self.action_merge_pdfs_dialog, icon_text="合併")
        act_split = A(m, "拆分 PDF 檔案(&S)…", self.action_split_pdf_dialog, icon_text="拆分")
        m.addSeparator()
        A(m, "批次重編頁碼(&N)…", lambda: self.action_page_num_watermark(0))
        A(m, "批次加浮水印(&W)…", lambda: self.action_page_num_watermark(1))

        # 4. 檢視：面板、護眼反相、縮放、深淺色主題（記在 WingLightPDF.json，第一次開啟跟著 Windows）
        m = menubar.addMenu("檢視(&V)")
        self.act_toggle_left = A(m, "左側縮圖與書籤(&S)", lambda on: self.left_panel.setVisible(on),
                                 icon_text="側欄", tip="顯示或隱藏左側的縮圖、書籤與搜尋結果", checkable=True,
                                 checked=True)
        self.act_invert = A(m, "護眼反相(&I)", self._toggle_dark_invert, icon_text="護眼反相",
                            tip="把頁面換成黑底白線，看 CAD 圖紙與長文比較不刺眼（只改顯示，不改檔案）",
                            checkable=True)
        m.addSeparator()
        A(m, "放大(&Z)", lambda: self.canvas.set_zoom(self.canvas.zoom * 1.2), QKeySequence.StandardKey.ZoomIn)
        A(m, "縮小(&O)", lambda: self.canvas.set_zoom(self.canvas.zoom / 1.2), QKeySequence.StandardKey.ZoomOut)
        A(m, "適應頁寬(&W)", lambda: self.canvas.fit_to_width())
        A(m, "適應整頁(&P)", lambda: self.canvas.fit_to_page())
        m.addSeparator()
        self.act_dark_theme = A(m, "深色主題(&D)", lambda on: theme.set_theme("dark" if on else "light"),
                                checkable=True, checked=theme.current() == "dark")
        theme.signals().changed.connect(self._on_theme_changed)

        # 5. 進階工具
        m = menubar.addMenu("進階工具(&T)")
        act_ocr_all = A(m, "文字辨識（OCR）：整份文件(&A)…", self.action_ocr_full_document)
        act_ocr_page = A(m, "文字辨識（OCR）：目前整頁(&P)…", self.action_ocr_current_page)
        act_ocr_area = A(m, "文字辨識（OCR）：圈選區域(&R)", lambda: self.canvas.set_tool_mode("clip_image"))
        m.addSeparator()
        A(m, "縮小檔案（最佳化 PDF）(&O)…", self.action_optimize_pdf, icon="package")
        A(m, "雙檔疊圖與同步捲動比對(&C)…", self.action_compare_pdfs)
        m.addSeparator()
        act_scale = A(m, "比例尺校正(&S)", lambda: self.canvas.set_tool_mode("measure_scale"))
        act_dist = A(m, "距離量測(&D)", lambda: self.canvas.set_tool_mode("measure_dist"))
        act_area = A(m, "多邊形面積與坪數量測(&M)", lambda: self.canvas.set_tool_mode("measure_area"))

        # 6. 說明
        m = menubar.addMenu("說明(&H)")
        A(m, "關於 WingLightPDF(&A)", self.action_show_about, icon="info")

        # ================= 工具列第 1 列：檔案、導覽、縮放、搜尋 =================
        tb_nav = QToolBar("導覽與檢視工具列", self)
        tb_nav.setMovable(False)
        tb_nav.setIconSize(QSize(16, 16))
        tb_nav.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb_nav)

        tb_nav.addAction(self.act_toggle_left)
        tb_nav.addSeparator()
        # 放不下的動作收進選單（規範 Toolbar）：「在新視窗開啟」在檔案選單（Ctrl+N）
        for act in (act_open, act_open_tab):
            tb_nav.addAction(act)
        tb_nav.addSeparator()
        tb_nav.addAction(act_save)
        tb_nav.addAction(act_print)
        tb_nav.addSeparator()
        tb_nav.addAction(self.act_undo)
        tb_nav.addAction(self.act_redo)
        tb_nav.addSeparator()

        btn_prev = self._icon_button("chevron-down", 90, "上一頁（PageUp）", lambda: self.step_page(-1))
        tb_nav.addWidget(btn_prev)
        self.spin_page = QSpinBox()
        self.spin_page.setObjectName("pageSpin")  # 旁邊已有上一頁、下一頁，不放微調鈕（樣式見 theme.py）
        self.spin_page.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spin_page.setRange(1, 1)
        self.spin_page.setFixedWidth(60)
        self.spin_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.spin_page.valueChanged.connect(lambda v: self.go_to_page(v - 1))
        tb_nav.addWidget(self.spin_page)
        self.lbl_total_pages = QLabel("／0 頁")
        tb_nav.addWidget(self.lbl_total_pages)
        btn_next = self._icon_button("chevron-down", -90, "下一頁（PageDown）", lambda: self.step_page(1))
        tb_nav.addWidget(btn_next)
        tb_nav.addSeparator()

        self.combo_zoom = QComboBox()
        self.combo_zoom.setEditable(True)
        self.combo_zoom.setFixedWidth(104)
        self.combo_zoom.setToolTip("縮放（Ctrl+滾輪也可以縮放）")
        self.combo_zoom.addItems(["50%", "75%", "100%", "125%", "150%", "200%", "300%", "適應頁寬", "適應整頁"])
        self.combo_zoom.setCurrentText("125%")
        self.combo_zoom.activated.connect(self._on_zoom_combo_activated)
        tb_nav.addWidget(self.combo_zoom)
        tb_nav.addAction(self.act_invert)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb_nav.addWidget(spacer)

        # 搜尋（預設只搜尋內嵌文字與已手動 OCR 的文字，不會自動跑 OCR）
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("搜尋文件內文字")
        self.txt_search.setToolTip("輸入後按 Enter 搜尋（Ctrl+F）；掃描檔要先用「文字辨識」才搜得到")
        self.txt_search.setMinimumWidth(140)
        self.txt_search.setMaximumWidth(220)
        search_icon = self.txt_search.addAction(QIcon(), QLineEdit.ActionPosition.LeadingPosition)
        theme.bind_icon(search_icon, "search")
        self.txt_search.returnPressed.connect(self.action_search_from_toolbar)
        tb_nav.addWidget(self.txt_search)
        tb_nav.addWidget(self._icon_button("chevron-down", 180, "上一個搜尋結果（Shift+F3）", self.action_search_prev))
        tb_nav.addWidget(self._icon_button("chevron-down", 0, "下一個搜尋結果（F3）", self.action_search_next))
        self.lbl_search_count = QLabel("0／0")
        self.lbl_search_count.setMinimumWidth(36)
        tb_nav.addWidget(self.lbl_search_count)

        # ================= 工具列第 2 列：互動模式、標註、頁面、文字辨識 =================
        self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
        tb_edit = QToolBar("編輯與功能工具列", self)
        tb_edit.setMovable(False)
        tb_edit.setIconSize(QSize(16, 16))
        tb_edit.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb_edit)

        self.mode_group = QActionGroup(self)
        self.mode_group.setExclusive(True)
        modes = (
            ("act_mode_pan", "瀏覽平移", "", "pan", "拖曳移動頁面；滾輪翻頁，Ctrl+滾輪縮放"),
            ("act_mode_text_sel", "選取文字", "", "select_text", "框選頁面上的文字，放開就複製"),
            ("act_mode_clip", "圈選截圖", "camera", "clip_image", "框選區域，放開後可以複製高解析圖、去背、加深線條或文字辨識"),
            ("act_mode_add_text", "加入文字", "", "add_text", "在頁面上點一下，加入中文文字標註"),
        )
        for attr, text, icon_name, mode, tip in modes:
            act = QAction(text, self)
            if icon_name:
                theme.bind_icon(act, icon_name)
            act.setToolTip(tip)
            act.setCheckable(True)
            act.triggered.connect(lambda _=False, md=mode: self.canvas.set_tool_mode(md))
            setattr(self, attr, act)
            self.mode_group.addAction(act)
            tb_edit.addAction(act)
        self.act_mode_pan.setChecked(True)

        self.combo_clip_dpi = QComboBox()
        self.combo_clip_dpi.setToolTip("圈選截圖的解析度（DPI 越高越清楚，檔案也越大）")
        for dpi in (300, 450, 600):
            self.combo_clip_dpi.addItem(f"截圖 {dpi} DPI", dpi)
        self.combo_clip_dpi.currentIndexChanged.connect(
            lambda _: setattr(self.canvas, "clip_dpi", self.combo_clip_dpi.currentData())
        )
        tb_edit.addWidget(self.combo_clip_dpi)
        tb_edit.addSeparator()

        act_image = QAction("加入圖片", self)
        theme.bind_icon(act_image, "image")
        act_image.setToolTip("選一張圖片放到頁面上，可以拖曳和縮放後寫入")
        act_image.triggered.connect(self.action_insert_image_overlay)
        tb_edit.addAction(act_image)
        self.act_stamp_box = QAction("圖章匣", self)
        self.act_stamp_box.setToolTip("顯示或隱藏右側的常用圖章與簽名")
        self.act_stamp_box.setCheckable(True)
        self.act_stamp_box.toggled.connect(self.stamp_panel.setVisible)
        tb_edit.addAction(self.act_stamp_box)
        tb_edit.addWidget(self._menu_button("量測", "ruler", "比例尺校正、距離與面積量測", [
            ("比例尺校正（點已知長度線段的兩端）", act_scale),
            ("距離量測（點起點和終點）", act_dist),
            ("多邊形面積與坪數（依序點頂點，右鍵或雙擊結束）", act_area),
        ]))
        tb_edit.addSeparator()

        # 擷取、插入頁面在「頁面操作」選單與縮圖的右鍵選單
        for act in (act_rot_l, act_rot_r, act_delete):
            tb_edit.addAction(act)
        tb_edit.addSeparator()
        tb_edit.addAction(act_merge)
        tb_edit.addAction(act_split)
        tb_edit.addSeparator()
        tb_edit.addWidget(self._menu_button("文字辨識", "", "掃描檔要先辨識才搜得到文字；只在按下去時執行", [
            ("整份文件（完成後可以全文搜尋）", act_ocr_all),
            ("目前整頁", act_ocr_page),
            ("圈選區域", act_ocr_area),
        ]))

    def _icon_button(self, icon_name: str, rotate: int, tip: str, slot) -> QToolButton:
        """只有圖示的按鈕一定要有滑鼠提示（規範 Button 元件）。"""
        btn = QToolButton()
        theme.bind_icon(btn, icon_name, rotate)
        btn.setToolTip(tip)
        btn.setAutoRaise(True)
        btn.clicked.connect(slot)
        return btn

    def _menu_button(self, text: str, icon_name: str, tip: str, items) -> QToolButton:
        """工具列上的下拉按鈕：選單項目沿用選單列的動作，只換成比較完整的說明文字。"""
        btn = QToolButton()
        btn.setText(text)
        if icon_name:
            theme.bind_icon(btn, icon_name)
        btn.setToolTip(tip)
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(btn)
        for label, act in items:
            menu.addAction(label, act.trigger)
        btn.setMenu(menu)
        return btn

    def _build_statusbar(self, startup_ms: Optional[float]) -> None:
        self.status_bar = StatusBar(self)
        self.setStatusBar(self.status_bar)
        self.lbl_page_info = QLabel("未開啟檔案")
        self.lbl_page_info.setProperty("muted", True)
        self.status_bar.addPermanentWidget(self.lbl_page_info)
        if startup_ms is not None:
            self.status_bar.showMessage(f"啟動完成｜{startup_ms:,.0f} 毫秒｜把 PDF 拖進視窗，或按 Ctrl+O 開啟")
        else:
            self.status_bar.showMessage("把 PDF 拖進視窗，或按 Ctrl+O 開啟")

    def action_show_about(self) -> None:
        from ui.about_dialog import AboutDialog
        AboutDialog(self).exec()

    def _connect_signals(self) -> None:
        # 單一文件分頁 (PDFDocumentTab) 的 canvas 與 left_panel 訊號已於分頁建立時自動轉發至 self.host_window
        self.stamp_panel.stamp_bytes_triggered.connect(
            lambda png_bytes: self.canvas.place_interactive_image(png_bytes, default_pdf_width=115.0)
        )

    def _on_theme_changed(self, name: str) -> None:
        # 任一視窗切換主題時，其他視窗的勾選狀態跟著更新
        self.act_dark_theme.blockSignals(True)
        self.act_dark_theme.setChecked(name == "dark")
        self.act_dark_theme.blockSignals(False)

    def _on_multi_tab_mode_toggled(self, checked: bool) -> None:
        PDFMainWindow.multi_tab_mode = checked
        for win in PDFMainWindow._open_windows:
            if hasattr(win, "act_multi_tab_toggle"):
                win.act_multi_tab_toggle.blockSignals(True)
                win.act_multi_tab_toggle.setChecked(checked)
                win.act_multi_tab_toggle.blockSignals(False)
        mode_msg = (
            "多個 PDF 開在同一個視窗：新開的檔案加到分頁（分頁可以拖出成兩個視窗，或拖進別的視窗合併）"
            if checked
            else "每個 PDF 開在自己的視窗（分頁仍然可以拖進別的視窗合併）"
        )
        self.status_bar.showMessage(mode_msg)

    # -------------------- 設為 Windows 預設 PDF 開啟程式 --------------------

    def action_register_default_pdf_viewer(self) -> None:
        exe_path = os.path.join(self.app_root, "WingLightPDF.exe")
        if not os.path.exists(exe_path):
            fallback = os.path.join(self.app_root, "FastPDF.exe")
            if os.path.exists(fallback):
                exe_path = fallback
            else:
                QMessageBox.warning(self, "找不到執行檔", f"找不到啟動器執行檔：\n{exe_path}")
                return

        try:
            from register_default import register_pdf_association
            exe_path = register_pdf_association()
        except Exception as e:
            QMessageBox.critical(self, "註冊失敗", f"寫入 Windows 檔案關聯時發生錯誤：\n{e}")
            return

        msg = (
            f"已將 WingLightPDF.exe 加到 Windows 的 PDF 開啟程式清單。\n\n"
            f"執行檔位置：\n{exe_path}\n\n"
            f"Windows 10／11 規定最後一步要由你自己確認，兩個方法擇一：\n"
            f"方法 A：對任何一個 PDF 檔案按右鍵，選「開啟檔案」裡的「選擇其他應用程式」，點「WingLightPDF」，再按「一律」。\n\n"
            f"方法 B：按「是」打開 Windows 的預設應用程式設定，搜尋 .pdf 後選 WingLightPDF。\n\n"
            f"是否現在打開 Windows 預設應用程式設定頁面？"
        )
        ans = QMessageBox.question(
            self,
            "已完成註冊 — 設定預設 PDF 開啟程式",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if ans == QMessageBox.StandardButton.Yes:
            os.startfile("ms-settings:defaultapps")

    # -------------------- 檔案、跨視窗分頁與頁面拖放支援 (Drag & Drop) --------------------

    def dragEnterEvent(self, event) -> None:
        mime = event.mimeData()
        if mime.hasFormat(FASTPDF_TAB_MIME_TYPE) or mime.hasFormat("application/x-fastpdf-pages"):
            event.acceptProposedAction()
            return
        if mime.hasUrls():
            for url in mime.urls():
                if url.toLocalFile().lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    return
        super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        mime = event.mimeData()

        # 0. 若是從另一個 FastPDF 視窗拖過來的「分頁標籤 (Tab)」， 直接合併進本視窗的分頁列！
        if mime.hasFormat(FASTPDF_TAB_MIME_TYPE):
            if self._handle_doctab_mime_drop(mime, insert_index=-1):
                event.acceptProposedAction()
                return

        # 1. 若是從另一個 FastPDF 視窗（或另一個分頁）拖過來的「選取頁面」
        if mime.hasFormat("application/x-fastpdf-pages"):
            try:
                data = json.loads(bytes(mime.data("application/x-fastpdf-pages")).decode("utf-8"))
                temp_pdf = data.get("temp_pdf", "")
                is_same_win = (
                    data.get("pid") == os.getpid()
                    and data.get("widget_id") == id(self.left_panel.thumb_list)
                )
                if not is_same_win and temp_pdf and os.path.exists(temp_pdf):
                    ins_at = (self.canvas.current_page_index + 1) if self.engine.doc else 0
                    self.action_insert_dropped_pdfs(ins_at, [temp_pdf], is_cross_window_pages=True)
                    event.acceptProposedAction()
                    return
            except Exception:
                pass

        # 2. 若是從 Windows 檔案總管拖進來的外部 .pdf 檔案
        pdf_paths = [
            u.toLocalFile()
            for u in mime.urls()
            if u.toLocalFile().lower().endswith(".pdf") and os.path.exists(u.toLocalFile())
        ]
        if not pdf_paths:
            return

        if self.engine.doc is None:
            self.load_pdf_file(pdf_paths[0])
            if len(pdf_paths) > 1:
                if PDFMainWindow.multi_tab_mode:
                    for extra in pdf_paths[1:]:
                        self.open_pdf_in_new_tab(extra)
                else:
                    for extra in pdf_paths[1:]:
                        win = PDFMainWindow(initial_pdf_path=extra)
                        win.show()
        else:
            # 目前分頁已有開啟的 PDF：彈出快捷選單讓使用者選擇「新增分頁開啟」、「插入頁面」或「開新視窗」
            curr_p = self.canvas.current_page_index + 1
            total_p = self.engine.page_count
            menu = QMenu(self)
            act_new_tab = menu.addAction(f"在這個視窗的新分頁開啟（{len(pdf_paths)} 個檔案）")
            menu.addSeparator()
            act_ins_after = menu.addAction(f"插入到目前文件第 {curr_p} 頁後面")
            act_ins_end = menu.addAction(f"加到目前文件最後面（第 {total_p} 頁後面）")
            act_ins_head = menu.addAction("插入到目前文件最前面")
            menu.addSeparator()
            act_new_win = menu.addAction("在新視窗開啟")

            global_pos = self.mapToGlobal(event.position().toPoint())
            chosen = menu.exec(global_pos)
            if chosen == act_new_tab:
                for p in pdf_paths:
                    self.open_pdf_in_new_tab(p)
            elif chosen == act_ins_after:
                self.action_insert_dropped_pdfs(curr_p, pdf_paths, is_cross_window_pages=False)
            elif chosen == act_ins_end:
                self.action_insert_dropped_pdfs(total_p, pdf_paths, is_cross_window_pages=False)
            elif chosen == act_ins_head:
                self.action_insert_dropped_pdfs(0, pdf_paths, is_cross_window_pages=False)
            elif chosen == act_new_win:
                for p in pdf_paths:
                    win = PDFMainWindow(initial_pdf_path=p)
                    win.show()

        event.acceptProposedAction()

    def action_insert_dropped_pdfs(
        self,
        insert_at: int,
        pdf_paths: List[str],
        is_cross_window_pages: bool = False,
    ) -> None:
        """將跨視窗拖曳過來的頁面或外部拖入的 PDF 檔案，直接插入至指定頁碼位置"""
        valid_paths = [p for p in pdf_paths if p and os.path.exists(p)]
        if not valid_paths:
            return

        if self.engine.doc is None:
            self.load_pdf_file(valid_paths[0])
            if len(valid_paths) == 1:
                return
            valid_paths = valid_paths[1:]
            insert_at = self.engine.page_count

        self.engine.push_undo_snapshot()
        pos = max(0, min(insert_at, self.engine.page_count))
        start_pos = pos
        total_inserted = 0

        for path in valid_paths:
            try:
                src_doc = fitz.open(path)
                cnt = len(src_doc)
                if cnt > 0:
                    self.engine.doc.insert_pdf(src_doc, start_at=pos)
                    pos += cnt
                    total_inserted += cnt
                src_doc.close()
            except Exception as e:
                QMessageBox.warning(self, "插入失敗", f"無法插入檔案 {os.path.basename(path)}：\n{e}")

        if total_inserted > 0:
            self.engine.is_modified = True
            inserted_rows = list(range(start_pos, start_pos + total_inserted))
            self.canvas.current_page_index = start_pos
            self.canvas.render_current_page(preserve_scroll=False)
            self.left_panel.reload_all(active_page=start_pos, selected_rows=inserted_rows)
            self._update_ui_state()
            src_label = "跨視窗拖曳頁面" if is_cross_window_pages else f"{len(valid_paths)} 個外部 PDF 檔"
            self.status_bar.show_status(
                f"已從{src_label}插入 {total_inserted:,} 頁到第 {start_pos + 1:,} 頁（可以按 Ctrl+Z 復原）", "ok"
            )

    # -------------------- 核心檔案與導覽操作 --------------------

    def load_pdf_file(self, path: str) -> None:
        import time
        t0 = time.perf_counter()
        try:
            self.engine.open_file(path)
        except Exception as e:
            QMessageBox.critical(self, "開啟失敗", f"無法開啟 PDF 檔案：\n{e}")
            return

        self._search_matches.clear()
        self._search_cursor = -1
        self._last_search_kw = ""
        self.lbl_search_count.setText("0／0")
        self.left_panel.populate_search_results("", [])

        self.canvas.current_page_index = 0
        self.canvas.render_current_page(preserve_scroll=False)
        self.left_panel.reload_all(active_page=0)
        self._update_ui_state()

        dt_ms = (time.perf_counter() - t0) * 1000.0
        self.status_bar.show_status(
            f"已開啟：{os.path.basename(path)}｜{self.engine.page_count:,} 頁｜耗時 {dt_ms:,.0f} 毫秒", "ok"
        )

    def open_pdf_in_new_tab(self, path: Optional[str] = None) -> PDFDocumentTab:
        """在目前視窗建立新分頁並載入 PDF（若目前分頁是空白未開啟狀態則直接複用）"""
        if self.engine.doc is None and not self.engine.is_modified:
            tab = self.current_doc_tab
        else:
            tab = self._create_and_add_doc_tab(make_current=True)
        if path and os.path.exists(path):
            self.load_pdf_file(path)
        self._refresh_tab_titles()
        return tab

    # -------------------- 從其他啟動要求轉來的檔案（單一執行個體） --------------------

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            PDFMainWindow._last_active = self
        super().changeEvent(event)

    @classmethod
    def _target_window(cls) -> Optional["PDFMainWindow"]:
        last = cls._last_active
        if last in cls._open_windows and last.isVisible():
            return last
        visible = [w for w in cls._open_windows if w.isVisible()]
        return visible[-1] if visible else None

    @classmethod
    def _find_open_tab(cls, path: str) -> Optional[Tuple["PDFMainWindow", int]]:
        key = os.path.normcase(os.path.abspath(path))
        for win in cls._open_windows:
            for i in range(win.doc_tabs.count()):
                tab = win.get_doc_tab(i)
                opened = tab.engine.file_path if tab is not None else None
                if opened and os.path.normcase(os.path.abspath(opened)) == key:
                    return win, i
        return None

    @classmethod
    def open_external_files(cls, paths: List[str]) -> None:
        """在檔案總管雙擊 PDF 等其他啟動要求轉來的檔案：開在最後使用的視窗分頁裡。
        已經開著的檔案直接切到那個分頁；沒有檔案時只把視窗帶到最前面。"""
        pdfs = [os.path.abspath(p) for p in paths if p.lower().endswith(".pdf") and os.path.isfile(p)]
        win = cls._target_window()
        if win is None:
            win = cls(initial_pdf_path=None)
            win.show()
        for p in pdfs:
            found = cls._find_open_tab(p)
            if found:
                win, index = found
                win.doc_tabs.setCurrentIndex(index)
            elif win.engine.doc is None and not win.engine.is_modified:
                win.load_pdf_file(p)
            elif cls.multi_tab_mode:
                win.open_pdf_in_new_tab(p)
            else:
                win = cls(initial_pdf_path=p)
                win.show()
        if win.isMinimized():
            win.showNormal()
        win.raise_()
        win.activateWindow()

    def _update_ui_state(self) -> None:
        self._refresh_tab_titles()
        has_doc = self.engine.doc is not None and self.engine.page_count > 0
        self.act_undo.setEnabled(self.engine.can_undo())
        self.act_redo.setEnabled(self.engine.can_redo())

        if not has_doc:
            self.setWindowTitle("WingLightPDF — 輕快免安裝PDF檢視與編輯工具")
            self.lbl_total_pages.setText("／0 頁")
            self.lbl_page_info.setText("未開啟檔案")
            return

        mod_star = " * [已修改]" if self.engine.is_modified else ""
        fname = os.path.basename(self.engine.file_path or "未命名.pdf")
        tab_cnt_str = f" (共 {self.doc_tabs.count()} 個分頁)" if self.doc_tabs.count() > 1 else ""
        self.setWindowTitle(f"{fname}{mod_star}{tab_cnt_str} — WingLightPDF — 輕快免安裝PDF檢視與編輯工具")

        total = self.engine.page_count
        curr = self.canvas.current_page_index + 1
        self.spin_page.blockSignals(True)
        self.spin_page.setRange(1, total)
        self.spin_page.setValue(curr)
        self.spin_page.blockSignals(False)
        self.lbl_total_pages.setText(f"／{total:,} 頁")

        pw, ph = self.engine.get_page_size(self.canvas.current_page_index)
        mm_w = pw * 25.4 / 72.0
        mm_h = ph * 25.4 / 72.0
        ocr_pages = len(self.engine.ocr_page_cache)
        ocr_tag = f"｜已辨識 {ocr_pages:,} 頁" if ocr_pages > 0 else ""
        self.lbl_page_info.setText(
            f"第 {curr:,}／{total:,} 頁｜{mm_w:.0f} × {mm_h:.0f} mm｜縮放 {self.canvas.zoom * 100:.0f}%{ocr_tag}"
        )

    def _on_document_modified(self) -> None:
        self._update_ui_state()
        self.left_panel.invalidate_pages([self.canvas.current_page_index])

    def go_to_page(self, page_index: int) -> None:
        if self.engine.doc is None:
            return
        clamped = max(0, min(page_index, self.engine.page_count - 1))
        if clamped == self.canvas.current_page_index and self.canvas._page_pixmap_item is not None:
            return
        self.canvas.current_page_index = clamped
        self.canvas.render_current_page(preserve_scroll=False)
        self.left_panel.set_active_page(clamped)
        self._update_ui_state()

    def step_page(self, delta: int) -> None:
        if self.engine.doc is None:
            return
        self.go_to_page(self.canvas.current_page_index + delta)

    def _on_zoom_combo_activated(self, _index: int) -> None:
        txt = self.combo_zoom.currentText().strip()
        if txt == "適應頁寬":
            self.canvas.fit_to_width()
        elif txt == "適應整頁":
            self.canvas.fit_to_page()
        else:
            try:
                val = float(txt.replace("%", "").strip()) / 100.0
                self.canvas.set_zoom(val)
            except ValueError:
                pass

    def _on_canvas_zoom_changed(self, new_zoom: float) -> None:
        self.combo_zoom.blockSignals(True)
        self.combo_zoom.setCurrentText(f"{new_zoom * 100:.0f}%")
        self.combo_zoom.blockSignals(False)
        self._update_ui_state()

    def _toggle_dark_invert(self, checked: bool) -> None:
        self.canvas.invert_colors = checked
        self.canvas.render_current_page(preserve_scroll=True)
        self.status_bar.showMessage("護眼反相：頁面改成黑底白線（只改顯示，不改檔案）" if checked else "護眼反相已關閉")

    def _sync_toolbar_mode_buttons(self, mode: str) -> None:
        mapping = {
            "pan": self.act_mode_pan,
            "select_text": self.act_mode_text_sel,
            "clip_image": self.act_mode_clip,
            "add_text": self.act_mode_add_text,
        }
        if mode in mapping:
            mapping[mode].setChecked(True)

    # -------------------- 檔案開啟 / 新分頁 / 多視窗 / 儲存 / 列印 --------------------

    def action_open_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "開啟 PDF 檔案（可多選）", "", "PDF 檔案 (*.pdf)")
        if not paths:
            return
        for p in paths:
            if self.engine.doc is None:
                self.load_pdf_file(p)
            elif PDFMainWindow.multi_tab_mode:
                self.open_pdf_in_new_tab(p)
            else:
                win = PDFMainWindow(initial_pdf_path=p)
                win.show()

    def action_open_in_new_tab(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "在新分頁開啟 PDF 檔案（可多選）", "", "PDF 檔案 (*.pdf)")
        if not paths:
            # 若使用者直接按取消但想開一個空白新分頁，或選擇了檔案
            return
        for p in paths:
            self.open_pdf_in_new_tab(p)

    def action_open_in_new_window(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "在新視窗開啟 PDF 檔案", "", "PDF 檔案 (*.pdf)")
        if path:
            win = PDFMainWindow(initial_pdf_path=path)
            win.show()

    def action_save_file(self) -> bool:
        if self.engine.doc is None:
            return False
        self.canvas.commit_all_pending_overlays()
        try:
            saved_path = self.engine.save()
            self._update_ui_state()
            self.status_bar.show_status(f"已儲存：{saved_path}", "ok")
            return True
        except Exception as e:
            QMessageBox.critical(self, "儲存失敗", f"無法寫入原檔案，請嘗試另存新檔：\n{e}")
            return self.action_save_as_file()

    def action_save_as_file(self) -> bool:
        if self.engine.doc is None:
            return False
        self.canvas.commit_all_pending_overlays()
        default_path = self.engine.file_path or "edited.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "另存 PDF 檔案", default_path, "PDF 檔案 (*.pdf)")
        if not path:
            return False
        try:
            saved_path = self.engine.save(path)
            self._update_ui_state()
            self.status_bar.show_status(f"已另存新檔：{saved_path}", "ok")
            return True
        except Exception as e:
            QMessageBox.critical(self, "另存失敗", str(e))
            return False

    def action_print_pdf(self) -> None:
        if self.engine.doc is None:
            return
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setFromTo(1, self.engine.page_count)
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle("列印 PDF（自動適應紙張邊界）")
        if dlg.exec() != QPrintDialog.DialogCode.Accepted:
            return

        from_p = max(1, printer.fromPage()) if printer.fromPage() > 0 else 1
        to_p = min(self.engine.page_count, printer.toPage()) if printer.toPage() > 0 else self.engine.page_count

        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, "列印失敗", "無法啟動印表機。")
            return

        try:
            for p_idx in range(from_p - 1, to_p):
                pw, ph = self.engine.get_page_size(p_idx)
                printer.setPageOrientation(
                    QPageLayout.Orientation.Landscape if pw > ph else QPageLayout.Orientation.Portrait
                )
                if p_idx > from_p - 1:
                    printer.newPage()

                target_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
                pix = self.engine.render_page_pixmap(p_idx, zoom=300.0 / 72.0, invert_colors=False, alpha=False)
                qimg = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
                scaled_img = qimg.scaled(
                    int(target_rect.width()),
                    int(target_rect.height()),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = (target_rect.width() - scaled_img.width()) / 2.0
                y = (target_rect.height() - scaled_img.height()) / 2.0
                painter.drawImage(int(x), int(y), scaled_img)
        finally:
            painter.end()

        self.status_bar.show_status(f"已送出第 {from_p}～{to_p} 頁到印表機", "ok")

    # -------------------- 復原 / 重做 / 搜尋文字（不自動 OCR，支援手動 OCR 後再搜尋） --------------------

    def action_undo(self) -> None:
        if self.engine.undo():
            self.canvas.render_current_page(preserve_scroll=True)
            self.left_panel.reload_all(active_page=self.canvas.current_page_index)
            self._update_ui_state()
            self.status_bar.showMessage("已復原上一步")

    def action_redo(self) -> None:
        if self.engine.redo():
            self.canvas.render_current_page(preserve_scroll=True)
            self.left_panel.reload_all(active_page=self.canvas.current_page_index)
            self._update_ui_state()
            self.status_bar.showMessage("已重做")

    def action_copy_whole_page_text(self) -> None:
        if self.engine.doc is None:
            return
        p_idx = self.canvas.current_page_index
        page = self.engine.doc[p_idx]
        txt = page.get_text("text", sort=True).strip()
        if not txt and p_idx in self.engine.ocr_page_cache:
            txt = "\n".join(t for _r, t in self.engine.ocr_page_cache[p_idx]).strip()
        if not txt:
            ans = QMessageBox.question(
                self,
                "此頁無原生文字",
                "此頁面似乎是掃描圖檔（無內嵌文字層）。\n是否立即對此頁啟動【按需 OCR 文字辨識】？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans == QMessageBox.StandardButton.Yes:
                self.action_ocr_current_page()
            return
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.clipboard().setText(txt)
        self.status_bar.show_status(f"已複製第 {p_idx + 1} 頁的文字｜{len(txt):,} 字", "ok")

    def action_focus_search(self) -> None:
        """Ctrl+F 快速聚焦搜尋框並展開左側搜尋結果分頁"""
        self.left_panel.setVisible(True)
        self.act_toggle_left.setChecked(True)
        self.left_panel.tabs.setCurrentWidget(self.left_panel.search_tab)
        self.txt_search.setFocus()
        self.txt_search.selectAll()

    def action_search_from_toolbar(self) -> None:
        kw = self.txt_search.text().strip()
        if kw == self._last_search_kw and self._search_matches:
            self.action_search_next()
        else:
            self.execute_keyword_search(kw)

    def execute_keyword_search(self, keyword: str) -> None:
        """執行關鍵字搜尋（僅搜尋原生文字 + 已手動執行過 OCR 的快取，絕不自動觸發 OCR）"""
        if self.engine.doc is None:
            return
        kw = keyword.strip()
        self.txt_search.setText(kw)
        self._last_search_kw = kw

        if not kw:
            self._search_matches.clear()
            self._search_cursor = -1
            self.lbl_search_count.setText("0／0")
            self.canvas.highlight_search_rects([])
            self.left_panel.populate_search_results("", [])
            return

        self._search_matches = self.engine.search_all_pages_with_snippets(kw)
        self.left_panel.setVisible(True)
        self.act_toggle_left.setChecked(True)
        self.left_panel.tabs.setCurrentWidget(self.left_panel.search_tab)

        if not self._search_matches:
            self._search_cursor = -1
            self.lbl_search_count.setText("0／0")
            self.canvas.highlight_search_rects([])
            self.left_panel.populate_search_results(kw, [])
            ocr_done = len(self.engine.ocr_page_cache)
            if ocr_done == 0:
                self.status_bar.show_status(
                    f"找不到「{kw}」。掃描檔要先用「文字辨識」的「整份文件」辨識後才搜尋得到", "warn"
                )
            else:
                self.status_bar.show_status(f"找不到「{kw}」（已搜尋內嵌文字和已辨識的 {ocr_done:,} 頁）", "warn")
            return

        self._search_cursor = 0
        self.left_panel.populate_search_results(kw, self._search_matches, active_index=0)
        self._jump_to_search_match()

    def jump_to_search_index(self, idx: int) -> None:
        if 0 <= idx < len(self._search_matches):
            self._search_cursor = idx
            self._jump_to_search_match()

    def action_search_next(self) -> None:
        kw = self.txt_search.text().strip()
        if not kw:
            self.action_focus_search()
            return
        if kw != self._last_search_kw or not self._search_matches:
            self.execute_keyword_search(kw)
            return
        self._search_cursor = (self._search_cursor + 1) % len(self._search_matches)
        self._jump_to_search_match()

    def action_search_prev(self) -> None:
        kw = self.txt_search.text().strip()
        if not kw:
            self.action_focus_search()
            return
        if kw != self._last_search_kw or not self._search_matches:
            self.execute_keyword_search(kw)
            return
        self._search_cursor = (self._search_cursor - 1) % len(self._search_matches)
        self._jump_to_search_match()

    def _jump_to_search_match(self) -> None:
        if not (0 <= self._search_cursor < len(self._search_matches)):
            return
        p_idx, target_rect, _snippet = self._search_matches[self._search_cursor]
        if p_idx != self.canvas.current_page_index:
            self.go_to_page(p_idx)
        page_rects = [r for pg, r, _s in self._search_matches if pg == p_idx]
        active_local = page_rects.index(target_rect) if target_rect in page_rects else 0
        self.canvas.highlight_search_rects(page_rects, active_idx=active_local)
        self.left_panel.set_active_search_row(self._search_cursor)
        total_m = len(self._search_matches)
        self.lbl_search_count.setText(f"{self._search_cursor + 1}／{total_m}")
        self.status_bar.showMessage(
            f"搜尋「{self._last_search_kw}」：第 {self._search_cursor + 1:,}／{total_m:,} 筆｜在第 {p_idx + 1:,} 頁"
        )

    # -------------------- 第一梯隊：頁面旋轉 / 刪除 / 排序 / 擷取 / 插入 / 合併 / 拆分 --------------------

    def action_rotate_current(self, angle_delta: int) -> None:
        if self.engine.doc is None:
            return
        selected = self.left_panel.selected_page_indices() or [self.canvas.current_page_index]
        self.action_rotate_pages(selected, angle_delta)

    def action_rotate_pages(self, page_indices: List[int], angle_delta: int) -> None:
        if self.engine.doc is None or not page_indices:
            return
        self.engine.rotate_pages(page_indices, angle_delta)
        self.canvas.render_current_page(preserve_scroll=True)
        self.left_panel.invalidate_pages(page_indices)
        self._update_ui_state()
        self.status_bar.show_status(f"已旋轉 {len(page_indices):,} 頁（{angle_delta:+d}°）", "ok")

    def action_delete_current_page(self) -> None:
        if self.engine.doc is None:
            return
        selected = self.left_panel.selected_page_indices() or [self.canvas.current_page_index]
        self.action_delete_pages(selected)

    def action_delete_pages(self, page_indices: List[int]) -> None:
        if self.engine.doc is None or not page_indices:
            return
        try:
            self.engine.delete_pages(page_indices)
            new_curr = min(self.canvas.current_page_index, self.engine.page_count - 1)
            self.canvas.current_page_index = new_curr
            self.canvas.render_current_page(preserve_scroll=False)
            self.left_panel.reload_all(active_page=new_curr)
            self._update_ui_state()
            self.status_bar.show_status(f"已刪除 {len(page_indices):,} 頁（可以按 Ctrl+Z 復原）", "ok")
        except ValueError as e:
            QMessageBox.warning(self, "無法刪除", str(e))

    def action_reorder_pages(self, new_order: List[int], moved_new_rows: Optional[List[int]] = None) -> None:
        if self.engine.doc is None:
            return
        try:
            old_active = self.canvas.current_page_index
            if moved_new_rows:
                new_active = moved_new_rows[0]
            else:
                new_active = new_order.index(old_active) if old_active in new_order else old_active
            self.engine.reorder_pages(new_order)
            self.canvas.current_page_index = new_active
            self.canvas.render_current_page(preserve_scroll=False)
            self.left_panel.reload_all(active_page=new_active, selected_rows=moved_new_rows)
            self._update_ui_state()
            cnt = len(moved_new_rows) if moved_new_rows else 1
            self.status_bar.show_status(f"已移動 {cnt:,} 頁的順序，目前在第 {new_active + 1:,} 頁（可以按 Ctrl+Z 復原）", "ok")
        except Exception as e:
            QMessageBox.warning(self, "排序失敗", str(e))

    def action_extract_pages_dialog(self) -> None:
        if self.engine.doc is None:
            return
        selected = self.left_panel.selected_page_indices()
        default_str = (
            ",".join(str(i + 1) for i in selected)
            if selected
            else str(self.canvas.current_page_index + 1)
        )
        range_str, ok = QInputDialog.getText(
            self,
            "擷取頁面另存新檔",
            f"請輸入要擷取的頁碼範圍（共 {self.engine.page_count} 頁，例如 1-3, 5, 8）：",
            text=default_str,
        )
        if not ok or not range_str.strip():
            return
        indices = parse_page_range_string(range_str, self.engine.page_count)
        if not indices:
            QMessageBox.warning(self, "頁碼無效", "請輸入有效的頁碼範圍。")
            return
        self.action_extract_selected_pages(indices)

    def action_extract_selected_pages(self, page_indices: List[int]) -> None:
        if self.engine.doc is None or not page_indices:
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self, "儲存擷取的頁面", f"擷取_{len(page_indices)}頁.pdf", "PDF 檔案 (*.pdf)"
        )
        if not out_path:
            return
        try:
            self.engine.extract_pages_to_file(page_indices, out_path)
            self.status_bar.show_status(f"已擷取 {len(page_indices):,} 頁到：{out_path}", "ok")
        except Exception as e:
            QMessageBox.critical(self, "擷取失敗", str(e))

    def action_insert_blank_page(self) -> None:
        if self.engine.doc is None:
            return
        self._insert_blank_at(self.canvas.current_page_index + 1)

    def _insert_blank_at(self, insert_at: int) -> None:
        if self.engine.doc is None:
            return
        self.engine.insert_blank_page(insert_at)
        self.canvas.current_page_index = insert_at
        self.canvas.render_current_page(preserve_scroll=False)
        self.left_panel.reload_all(active_page=insert_at)
        self._update_ui_state()
        self.status_bar.show_status(f"已在第 {insert_at + 1:,} 頁插入空白頁", "ok")

    def action_insert_external_pdf(self) -> None:
        if self.engine.doc is None:
            return
        self._insert_pdf_at(self.canvas.current_page_index + 1)

    def _insert_pdf_at(self, insert_at: int) -> None:
        if self.engine.doc is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "選擇要插入的外部 PDF 檔案", "", "PDF 檔案 (*.pdf)")
        if not path:
            return
        try:
            tmp_doc = fitz.open(path)
            ext_total = len(tmp_doc)
            tmp_doc.close()
        except Exception as e:
            QMessageBox.warning(self, "讀取失敗", str(e))
            return

        range_str, ok = QInputDialog.getText(
            self,
            "插入 PDF 頁面設定",
            f"外部檔案共 {ext_total} 頁。\n請輸入要插入的頁碼範圍（留空代表插入全部頁面，或輸入如 1-3, 5）：",
            text="",
        )
        if not ok:
            return
        page_range = parse_page_range_string(range_str, ext_total) if range_str.strip() else None
        count = self.engine.insert_external_pdf(path, insert_at=insert_at, page_range=page_range)
        if count > 0:
            self.canvas.current_page_index = insert_at
            self.canvas.render_current_page(preserve_scroll=False)
            self.left_panel.reload_all(active_page=insert_at)
            self._update_ui_state()
            self.status_bar.show_status(f"已插入 {count:,} 頁到第 {insert_at + 1:,} 頁", "ok")

    # -------------------- 進階對話框功能（按需延遲載入 UI 與 Worker） --------------------

    def action_insert_image_overlay(self) -> None:
        if self.engine.doc is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇要插入頁面的圖片或透明簽名檔", "", "圖片檔案 (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        with open(path, "rb") as f:
            data = f.read()
        self.canvas.place_interactive_image(data, default_pdf_width=140.0)

    def action_merge_pdfs_dialog(self) -> None:
        from ui.dialogs import MergePDFDialog

        dlg = MergePDFDialog(current_file=self.engine.file_path, parent=self)
        if dlg.exec() == MergePDFDialog.DialogCode.Accepted and dlg.merged_output_path:
            if dlg.chk_open_after.isChecked():
                if self.engine.doc is None:
                    self.load_pdf_file(dlg.merged_output_path)
                else:
                    win = PDFMainWindow(initial_pdf_path=dlg.merged_output_path)
                    win.show()

    def action_split_pdf_dialog(self) -> None:
        if self.engine.doc is None:
            return
        from ui.dialogs import SplitPDFDialog

        dlg = SplitPDFDialog(self.engine, self)
        dlg.exec()

    def action_page_num_watermark(self, initial_tab: int = 0) -> None:
        if self.engine.doc is None:
            return
        from ui.dialogs import PageNumberWatermarkDialog

        dlg = PageNumberWatermarkDialog(self.engine, initial_tab=initial_tab, parent=self)
        if dlg.exec() == PageNumberWatermarkDialog.DialogCode.Accepted:
            self.canvas.render_current_page(preserve_scroll=True)
            self.left_panel.reload_all(active_page=self.canvas.current_page_index)
            self._update_ui_state()
            self.status_bar.show_status("已套用頁碼／浮水印（可以按 Ctrl+Z 復原）", "ok")

    def action_optimize_pdf(self) -> None:
        if self.engine.doc is None:
            return
        from ui.dialogs import OptimizePDFDialog

        dlg = OptimizePDFDialog(self.engine, self)
        dlg.exec()

    def action_compare_pdfs(self) -> None:
        from ui.dialogs import ComparePDFWindow

        dlg = ComparePDFWindow(initial_file_a=self.engine.file_path, parent=self)
        dlg.show()

    def action_ocr_full_document(self) -> None:
        """使用者主動點選「辨識全部文件所有頁面」時，才啟動批次 OCR 並建立全文搜尋索引"""
        if self.engine.doc is None:
            QMessageBox.information(self, "提示", "請先開啟一個 PDF 檔案。")
            return
        from ui.dialogs import FullDocumentOCRDialog

        dlg = FullDocumentOCRDialog(engine=self.engine, parent=self)
        dlg.ocr_text_embedded.connect(self._update_ui_state)
        dlg.exec()
        self._update_ui_state()

        # 若搜尋框內已有剛才查不到的關鍵字，辨識完成後自動重新搜尋一次！
        pending_kw = self.txt_search.text().strip() or self.left_panel.txt_panel_search.text().strip()
        if pending_kw:
            self.execute_keyword_search(pending_kw)
        else:
            self.status_bar.show_status(
                f"文字辨識完成｜{len(self.engine.ocr_page_cache):,} 頁可以搜尋，在上方搜尋框輸入文字", "ok"
            )

    def action_ocr_current_page(self) -> None:
        """使用者主動點選時，才將當前頁面轉為 250 DPI 影像並啟動按需 OCR 視窗"""
        if self.engine.doc is None:
            return
        from ui.dialogs import OnDemandOCRDialog

        p_idx = self.canvas.current_page_index
        rect = self.engine.doc[p_idx].rect
        dpi = 250
        png_bytes = self.engine.render_clip_high_dpi(
            p_idx, rect, dpi=dpi, transparent_bg=False, enhance_lines=True
        )
        dlg = OnDemandOCRDialog(
            png_bytes=png_bytes,
            title_suffix=f"（第 {p_idx + 1} 頁整頁）",
            engine=self.engine,
            page_index=p_idx,
            render_dpi=dpi,
            parent=self,
        )
        dlg.exec()
        self._update_ui_state()

    def _launch_ondemand_ocr_dialog(self, png_bytes: bytes, title_suffix: str = "（圈選區域）") -> None:
        from ui.dialogs import OnDemandOCRDialog

        dlg = OnDemandOCRDialog(png_bytes=png_bytes, title_suffix=title_suffix, parent=self)
        dlg.exec()
