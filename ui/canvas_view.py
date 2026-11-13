# -*- coding: utf-8 -*-
"""
互動式 PDF 畫布檢視器 (PDFCanvasView)
負責：
- 高速單頁渲染與深色反相模式
- 滾輪縮放、手型拖曳平移、上一頁/下一頁滾動銜接
- 文字框選與即時反白複製
- 圈選高解析圖面截圖（標準 / 一鍵去背透明 / 去背+線條加深 / 區域按需 OCR / 另存圖檔）
- 互動式圖片/圖章擺放預覽框（可自由拖曳、拉角縮放，按 Enter 或右鍵寫入底層 PDF）
- 比例尺校正、距離量測、多邊形面積量測
"""

from __future__ import annotations
import math
from typing import List, Tuple, Optional
import fitz

from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QByteArray, QMimeData
from PySide6.QtGui import (
    QImage,
    QPixmap,
    QPainter,
    QPen,
    QColor,
    QBrush,
    QFont,
    QCursor,
    QPolygonF,
    QGuiApplication,
    QWheelEvent,
    QMouseEvent,
    QKeyEvent,
)
from PySide6.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsItem,
    QGraphicsPolygonItem,
    QGraphicsPathItem,
    QGraphicsTextItem,
    QMenu,
    QInputDialog,
    QFileDialog,
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QPushButton,
    QColorDialog,
    QComboBox,
)


class InteractiveImageOverlayItem(QGraphicsItem):
    """
    可拖曳、可拉右下角縮放的圖片/圖章預覽框。
    雙擊或按右鍵選「寫入頁面」即可將目前座標換算回 PDF 並永久寫入。
    """

    HANDLE_SIZE = 14.0

    def __init__(
        self,
        pixmap: QPixmap,
        png_bytes: bytes,
        initial_rect: QRectF,
        on_commit_callback,
        on_cancel_callback,
    ) -> None:
        super().__init__()
        self.pixmap = pixmap
        self.png_bytes = png_bytes
        self._rect = QRectF(0, 0, initial_rect.width(), initial_rect.height())
        self.setPos(initial_rect.topLeft())
        self.on_commit_callback = on_commit_callback
        self.on_cancel_callback = on_cancel_callback

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(50)
        self._resizing = False
        self._aspect_ratio = (
            initial_rect.width() / initial_rect.height()
            if initial_rect.height() > 1
            else 1.0
        )

    def boundingRect(self) -> QRectF:
        return self._rect.adjusted(-4, -26, 4, 4)

    def scene_target_rect(self) -> QRectF:
        pos = self.pos()
        return QRectF(pos.x(), pos.y(), self._rect.width(), self._rect.height())

    def _handle_rect(self) -> QRectF:
        return QRectF(
            self._rect.width() - self.HANDLE_SIZE,
            self._rect.height() - self.HANDLE_SIZE,
            self.HANDLE_SIZE,
            self.HANDLE_SIZE,
        )

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(self._rect.toRect(), self.pixmap)

        # 虛線外框與頂部操作提示條
        pen = QPen(QColor(0, 120, 215), 2.0, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(self._rect)

        # 頂部提示標籤
        banner_rect = QRectF(0, -24, max(self._rect.width(), 190), 22)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 120, 215, 220))
        painter.drawRoundedRect(banner_rect, 4, 4)
        painter.setPen(QColor(255, 255, 255))
        font = QFont("Microsoft JhengHei", 9, QFont.Weight.Bold)
        painter.setFont(font)
        painter.drawText(banner_rect.adjusted(6, 0, -6, 0), Qt.AlignmentFlag.AlignVCenter, "雙擊或按 Enter 寫入｜右鍵選單｜拉右下角縮放")

        # 右下角縮放控制點
        painter.setPen(QPen(QColor(255, 255, 255), 1.5))
        painter.setBrush(QColor(0, 120, 215))
        painter.drawRect(self._handle_rect())

    def hoverMoveEvent(self, event) -> None:
        if self._handle_rect().contains(event.pos()):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        else:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._handle_rect().contains(event.pos()):
            self._resizing = True
            event.accept()
            return
        if event.button() == Qt.MouseButton.RightButton:
            menu = QMenu()
            act_commit = menu.addAction("✓ 確定蓋印 / 寫入此頁 (Enter / 雙擊)")
            act_cancel = menu.addAction("✕ 取消移除 (Esc / Delete)")
            chosen = menu.exec(event.screenPos())
            if chosen == act_commit:
                self.on_commit_callback(self)
            elif chosen == act_cancel:
                self.on_cancel_callback(self)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing:
            self.prepareGeometryChange()
            new_w = max(24.0, event.pos().x())
            # 預設等比例縮放（若按住 Shift 則自由縮放）
            if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                new_h = max(24.0, new_w / self._aspect_ratio)
            else:
                new_h = max(24.0, event.pos().y())
            self._rect.setWidth(new_w)
            self._rect.setHeight(new_h)
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing:
            self._resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.on_commit_callback(self)
            event.accept()


class TextAnnotationDialog(QDialog):
    """新增文字標註設定視窗"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("加入文字標註（內嵌中文字型）")
        self.resize(400, 300)
        self.text_color = QColor(215, 15, 15)
        self.bg_color = QColor(255, 255, 235)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("輸入文字內容（支援多行與繁體中文）："))
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("請在此輸入要加到頁面上的文字...")
        layout.addWidget(self.text_edit)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("字體大小 (pt)："))
        self.spin_size = QDoubleSpinBox()
        self.spin_size.setRange(6.0, 96.0)
        self.spin_size.setValue(14.0)
        row1.addWidget(self.spin_size)

        self.btn_color = QPushButton("文字顏色")
        self._update_color_btn()
        self.btn_color.clicked.connect(self._pick_text_color)
        row1.addWidget(self.btn_color)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.chk_bg = QCheckBox("加上底色背景")
        self.chk_bg.setChecked(False)
        row2.addWidget(self.chk_bg)

        self.btn_bg_color = QPushButton("選擇底色")
        self.btn_bg_color.clicked.connect(self._pick_bg_color)
        row2.addWidget(self.btn_bg_color)

        self.chk_border = QCheckBox("加上外框線")
        self.chk_border.setChecked(False)
        row2.addWidget(self.chk_border)
        layout.addLayout(row2)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton("確定加入")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_ok)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

    def _update_color_btn(self) -> None:
        self.btn_color.setStyleSheet(
            f"background-color: {self.text_color.name()}; color: white; font-weight: bold; padding: 4px 10px;"
        )

    def _pick_text_color(self) -> None:
        col = QColorDialog.getColor(self.text_color, self, "選擇文字顏色")
        if col.isValid():
            self.text_color = col
            self._update_color_btn()

    def _pick_bg_color(self) -> None:
        col = QColorDialog.getColor(self.bg_color, self, "選擇背景底色")
        if col.isValid():
            self.bg_color = col


class PDFCanvasView(QGraphicsView):
    """
    核心 PDF 頁面檢視與互動畫布
    互動模式 (tool_mode)：
    - 'pan': 手型平移與檢視、調整待蓋印圖片
    - 'select_text': 框選並複製原生文字
    - 'clip_image': 圈選高解析截圖（含一鍵去背、加深線條、區域按需 OCR）
    - 'add_text': 點擊位置加入中文文字標註
    - 'measure_scale': 點兩點設定比例尺
    - 'measure_dist': 點兩點量測實際距離
    - 'measure_area': 點多點量測多邊形面積与周長
    """

    zoom_changed = Signal(float)
    status_message = Signal(str)
    page_modified = Signal()
    request_page_step = Signal(int)  # +1 下一頁, -1 上一頁
    request_ocr_bytes = Signal(bytes)  # 傳送圈選區域的 PNG bytes 執行按需 OCR
    tool_mode_changed = Signal(str)

    def __init__(self, engine, parent=None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.scene_obj = QGraphicsScene(self)
        self.setScene(self.scene_obj)

        self.current_page_index: int = 0
        self.zoom: float = 1.25
        self.invert_colors: bool = False
        self.tool_mode: str = "pan"

        # 預設高畫質圈選截圖參數
        self.clip_dpi: int = 300
        self.clip_transparent: bool = False
        self.clip_enhance_lines: bool = False

        # 畫布圖層項目
        self._page_pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._search_highlight_items: List[QGraphicsRectItem] = []
        self._word_highlight_items: List[QGraphicsRectItem] = []
        self._pending_image_items: List[InteractiveImageOverlayItem] = []
        self._measure_items: List[QGraphicsItem] = []

        # 滑鼠框選狀態
        self._rubber_origin: Optional[QPointF] = None
        self._rubber_rect_item: Optional[QGraphicsRectItem] = None
        self._cached_words: List[Tuple[float, float, float, float, str]] = []

        # 量測點集合 (儲存 PDF 座標 (x, y))
        self._measure_pdf_points: List[Tuple[float, float]] = []
        self._temp_measure_line: Optional[QGraphicsPathItem] = None

        # 畫布視覺外觀
        self.setBackgroundBrush(QBrush(QColor(45, 48, 52)))
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        # 讓外部 PDF 檔案與跨視窗頁面拖放事件直接傳遞給主視窗處理
        self.setAcceptDrops(False)
        self.viewport().setAcceptDrops(False)

    # -------------------- 模式切換与畫面渲染 --------------------

    def set_tool_mode(self, mode: str) -> None:
        self.tool_mode = mode
        self._clear_rubber_band()
        self._clear_word_highlights()
        self._measure_pdf_points.clear()

        if mode == "pan":
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            self.status_message.emit("模式：瀏覽平移（滾輪翻頁或 Ctrl+滾輪縮放；可拖曳調整圖章位置）")
        elif mode == "select_text":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.IBeamCursor)
            if self.engine.doc is not None:
                self._cached_words = self.engine.get_page_words(self.current_page_index)
            self.status_message.emit("模式：選取文字（請在頁面上拖曳框選文字，放開即可複製）")
        elif mode == "clip_image":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            self.status_message.emit("模式：圈選複製圖面（拖曳框選區域，放開後可選擇標準/一鍵去背/線條加深/區域OCR）")
        elif mode == "add_text":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            self.status_message.emit("模式：加入文字（請在頁面上欲插入文字的位置點一下滑鼠左鍵）")
        elif mode == "measure_scale":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            self.status_message.emit("模式：比例尺校正（請在已知長度的圖面線段兩端各點一下）")
        elif mode == "measure_dist":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            scale_info = self._get_current_scale_label()
            self.status_message.emit(f"模式：距離量測 [{scale_info}]（請在起點與終點各點一下）")
        elif mode == "measure_area":
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            scale_info = self._get_current_scale_label()
            self.status_message.emit(f"模式：面積量測 [{scale_info}]（依序點擊多邊形頂點，點右鍵或雙擊完成閉合計算）")

        self.tool_mode_changed.emit(mode)

    def _get_current_scale_label(self) -> str:
        if self.current_page_index in self.engine.page_scales:
            pts_per_unit, unit = self.engine.page_scales[self.current_page_index]
            return f"已校正: {pts_per_unit:.2f} pt/{unit}"
        return "預設單位: mm (可先點『比例尺校正』設定圖面比例)"

    def render_current_page(self, preserve_scroll: bool = True) -> None:
        """極速渲染眼前這一頁（Viewport Lazy Rendering）"""
        if self.engine.doc is None or self.engine.page_count == 0:
            self.scene_obj.clear()
            self._page_pixmap_item = None
            return

        h_val = self.horizontalScrollBar().value()
        v_val = self.verticalScrollBar().value()

        self.current_page_index = max(0, min(self.current_page_index, self.engine.page_count - 1))
        pix = self.engine.render_page_pixmap(
            self.current_page_index,
            zoom=self.zoom,
            invert_colors=self.invert_colors,
            alpha=False,
        )
        qimg = QImage(
            pix.samples,
            pix.width,
            pix.height,
            pix.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        qpix = QPixmap.fromImage(qimg)

        self.scene_obj.clear()
        self._search_highlight_items.clear()
        self._word_highlight_items.clear()
        self._pending_image_items.clear()
        self._measure_items.clear()
        self._rubber_rect_item = None

        self._page_pixmap_item = self.scene_obj.addPixmap(qpix)
        self._page_pixmap_item.setZValue(0)
        self.scene_obj.setSceneRect(QRectF(0, 0, qpix.width(), qpix.height()))

        if self.tool_mode == "select_text":
            self._cached_words = self.engine.get_page_words(self.current_page_index)

        if preserve_scroll:
            self.horizontalScrollBar().setValue(h_val)
            self.verticalScrollBar().setValue(v_val)

    def set_zoom(self, new_zoom: float) -> None:
        clamped = max(0.2, min(6.0, new_zoom))
        if abs(clamped - self.zoom) < 0.005:
            return
        self.zoom = clamped
        self.render_current_page(preserve_scroll=True)
        self.zoom_changed.emit(self.zoom)

    def fit_to_width(self) -> None:
        if self.engine.doc is None:
            return
        pw, _ = self.engine.get_page_size(self.current_page_index)
        view_w = max(200, self.viewport().width() - 36)
        self.set_zoom(view_w / pw)

    def fit_to_page(self) -> None:
        if self.engine.doc is None:
            return
        pw, ph = self.engine.get_page_size(self.current_page_index)
        view_w = max(200, self.viewport().width() - 36)
        view_h = max(200, self.viewport().height() - 36)
        self.set_zoom(min(view_w / pw, view_h / ph))

    def highlight_search_rects(self, pdf_rects: List[fitz.Rect], active_idx: int = -1) -> None:
        """在畫面上繪製搜尋關鍵字的高亮方框"""
        for item in self._search_highlight_items:
            self.scene_obj.removeItem(item)
        self._search_highlight_items.clear()

        for i, r in enumerate(pdf_rects):
            sr = QRectF(r.x0 * self.zoom, r.y0 * self.zoom, r.width * self.zoom, r.height * self.zoom)
            item = QGraphicsRectItem(sr)
            if i == active_idx:
                item.setPen(QPen(QColor(255, 80, 0), 2.0))
                item.setBrush(QBrush(QColor(255, 140, 0, 110)))
                self.ensureVisible(sr, 80, 80)
            else:
                item.setPen(QPen(QColor(230, 180, 0), 1.0))
                item.setBrush(QBrush(QColor(255, 235, 0, 85)))
            item.setZValue(15)
            self.scene_obj.addItem(item)
            self._search_highlight_items.append(item)

    # -------------------- 放置互動式圖片 / 圖章預覽框 --------------------

    def place_interactive_image(self, png_bytes: bytes, default_pdf_width: float = 120.0) -> None:
        """在畫面中央放上一個可拖曳、可縮放的圖片/圖章預覽框"""
        if self.engine.doc is None:
            return
        qpix = QPixmap()
        qpix.loadFromData(png_bytes)
        if qpix.isNull():
            return

        aspect = qpix.height() / max(1, qpix.width())
        scene_w = default_pdf_width * self.zoom
        scene_h = scene_w * aspect

        # 置於目前視窗可見範圍的中心
        center_scene = self.mapToScene(self.viewport().rect().center())
        scene_rect = self.scene_obj.sceneRect()
        cx = max(10.0, min(center_scene.x() - scene_w / 2, scene_rect.width() - scene_w - 10))
        cy = max(25.0, min(center_scene.y() - scene_h / 2, scene_rect.height() - scene_h - 10))

        self.set_tool_mode("pan")
        item = InteractiveImageOverlayItem(
            pixmap=qpix,
            png_bytes=png_bytes,
            initial_rect=QRectF(cx, cy, scene_w, scene_h),
            on_commit_callback=self._commit_image_overlay,
            on_cancel_callback=self._cancel_image_overlay,
        )
        self.scene_obj.addItem(item)
        self._pending_image_items.append(item)
        self.status_message.emit("已放置圖片/圖章預覽框：可拖曳移動、拉右下角縮放，雙擊或按 Enter 即可寫入 PDF！")

    def _commit_image_overlay(self, item: InteractiveImageOverlayItem) -> None:
        if self.engine.doc is None:
            return
        sr = item.scene_target_rect()
        pdf_rect = fitz.Rect(
            sr.left() / self.zoom,
            sr.top() / self.zoom,
            sr.right() / self.zoom,
            sr.bottom() / self.zoom,
        )
        self.engine.add_image_to_page(
            self.current_page_index,
            pdf_rect,
            item.png_bytes,
            keep_proportion=False,
        )
        if item in self._pending_image_items:
            self._pending_image_items.remove(item)
        self.render_current_page(preserve_scroll=True)
        self.page_modified.emit()
        self.status_message.emit("✓ 已將圖片/圖章寫入頁面（可按 Ctrl+Z 復原）")

    def _cancel_image_overlay(self, item: InteractiveImageOverlayItem) -> None:
        if item in self._pending_image_items:
            self._pending_image_items.remove(item)
        self.scene_obj.removeItem(item)
        self.status_message.emit("已取消放置圖片/圖章")

    def commit_all_pending_overlays(self) -> None:
        for item in list(self._pending_image_items):
            self._commit_image_overlay(item)

    # -------------------- 鍵盤與滑鼠事件 --------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._pending_image_items:
            self.commit_all_pending_overlays()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            if self._pending_image_items:
                for item in list(self._pending_image_items):
                    self._cancel_image_overlay(item)
            self.set_tool_mode("pan")
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self.engine.doc is None:
            return
        # Ctrl + 滾輪：以滑鼠游標為中心無段縮放
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            factor = 1.15 if delta > 0 else (1.0 / 1.15)
            self.set_zoom(self.zoom * factor)
            event.accept()
            return

        # 一般滾輪：捲動頁面，若已到頂或到底則自動切換上一頁/下一頁（SumatraPDF 流暢翻頁體驗）
        # 第一頁頂端、最後一頁底端沒有頁可翻，停在原地，不要把捲軸拉到另一端（否則畫面會來回跳）
        vbar = self.verticalScrollBar()
        delta_y = event.angleDelta().y()
        if delta_y < 0 and vbar.value() >= vbar.maximum():
            if self.current_page_index < self.engine.page_count - 1:
                self.request_page_step.emit(1)
                vbar.setValue(vbar.minimum())
            event.accept()
            return
        elif delta_y > 0 and vbar.value() <= vbar.minimum():
            if self.current_page_index > 0:
                self.request_page_step.emit(-1)
                vbar.setValue(vbar.maximum())
            event.accept()
            return

        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self.engine.doc is None:
            super().mousePressEvent(event)
            return

        # 中鍵隨時支援平移
        if event.button() == Qt.MouseButton.MiddleButton:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            fake = QMouseEvent(
                event.type(),
                event.position(),
                event.globalPosition(),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                event.modifiers(),
            )
            super().mousePressEvent(fake)
            return

        scene_pt = self.mapToScene(event.pos())

        # 面積量測右鍵閉合
        if self.tool_mode == "measure_area" and event.button() == Qt.MouseButton.RightButton:
            if len(self._measure_pdf_points) >= 3:
                self._finish_area_measurement()
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if self.tool_mode in ("select_text", "clip_image"):
                self._rubber_origin = scene_pt
                self._clear_rubber_band()
                self._clear_word_highlights()
                pen_col = QColor(0, 120, 215) if self.tool_mode == "select_text" else QColor(0, 175, 90)
                fill_col = QColor(0, 120, 215, 45) if self.tool_mode == "select_text" else QColor(0, 175, 90, 40)
                self._rubber_rect_item = QGraphicsRectItem(QRectF(scene_pt, scene_pt))
                self._rubber_rect_item.setPen(QPen(pen_col, 1.8, Qt.PenStyle.DashLine))
                self._rubber_rect_item.setBrush(QBrush(fill_col))
                self._rubber_rect_item.setZValue(30)
                self.scene_obj.addItem(self._rubber_rect_item)
                event.accept()
                return

            elif self.tool_mode == "add_text":
                pdf_x = scene_pt.x() / self.zoom
                pdf_y = scene_pt.y() / self.zoom
                self._prompt_and_add_text((pdf_x, pdf_y))
                event.accept()
                return

            elif self.tool_mode in ("measure_scale", "measure_dist", "measure_area"):
                pdf_pt = (scene_pt.x() / self.zoom, scene_pt.y() / self.zoom)
                self._handle_measure_click(pdf_pt)
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._rubber_origin is not None and self._rubber_rect_item is not None:
            curr_pt = self.mapToScene(event.pos())
            rect = QRectF(self._rubber_origin, curr_pt).normalized()
            # 限制在頁面範圍內
            rect = rect.intersected(self.scene_obj.sceneRect())
            self._rubber_rect_item.setRect(rect)

            if self.tool_mode == "select_text":
                self._update_word_highlights(rect)
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.set_tool_mode(self.tool_mode)
            super().mouseReleaseEvent(event)
            return

        if event.button() == Qt.MouseButton.LeftButton and self._rubber_origin is not None:
            rect = self._rubber_rect_item.rect() if self._rubber_rect_item else QRectF()
            self._rubber_origin = None

            if rect.width() < 6 or rect.height() < 6:
                self._clear_rubber_band()
                self._clear_word_highlights()
                return

            pdf_rect = fitz.Rect(
                rect.left() / self.zoom,
                rect.top() / self.zoom,
                rect.right() / self.zoom,
                rect.bottom() / self.zoom,
            )

            if self.tool_mode == "select_text":
                self._clear_rubber_band()
                self._finish_text_selection(pdf_rect, event.globalPosition().toPoint())
            elif self.tool_mode == "clip_image":
                self._finish_clip_selection(pdf_rect, event.globalPosition().toPoint())
                self._clear_rubber_band()
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if self.tool_mode == "measure_area" and len(self._measure_pdf_points) >= 3:
            self._finish_area_measurement()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # -------------------- 選取文字與圈選圖面處理 --------------------

    def _clear_rubber_band(self) -> None:
        if self._rubber_rect_item is not None:
            self.scene_obj.removeItem(self._rubber_rect_item)
            self._rubber_rect_item = None

    def _clear_word_highlights(self) -> None:
        for item in self._word_highlight_items:
            self.scene_obj.removeItem(item)
        self._word_highlight_items.clear()

    def _update_word_highlights(self, scene_rect: QRectF) -> None:
        self._clear_word_highlights()
        pdf_rect = fitz.Rect(
            scene_rect.left() / self.zoom,
            scene_rect.top() / self.zoom,
            scene_rect.right() / self.zoom,
            scene_rect.bottom() / self.zoom,
        )
        for x0, y0, x1, y1, _word in self._cached_words:
            w_rect = fitz.Rect(x0, y0, x1, y1)
            if w_rect.intersects(pdf_rect):
                sr = QRectF(x0 * self.zoom, y0 * self.zoom, (x1 - x0) * self.zoom, (y1 - y0) * self.zoom)
                hl = QGraphicsRectItem(sr)
                hl.setPen(Qt.PenStyle.NoPen)
                hl.setBrush(QBrush(QColor(0, 120, 215, 90)))
                hl.setZValue(20)
                self.scene_obj.addItem(hl)
                self._word_highlight_items.append(hl)

    def _finish_text_selection(self, pdf_rect: fitz.Rect, global_pos) -> None:
        extracted = self.engine.extract_text_in_rect(self.current_page_index, pdf_rect)
        if not extracted:
            menu = QMenu(self)
            act_ocr = menu.addAction("此區域無原生文字 → 點此執行【按需 OCR 辨識】")
            chosen = menu.exec(global_pos)
            if chosen == act_ocr:
                png_bytes = self.engine.render_clip_high_dpi(self.current_page_index, pdf_rect, dpi=300)
                self.request_ocr_bytes.emit(png_bytes)
            self._clear_word_highlights()
            return

        QGuiApplication.clipboard().setText(extracted)
        preview = extracted.replace("\n", " ")[:45]
        self.status_message.emit(f"✓ 已複製選取文字 ({len(extracted)} 字)：「{preview}...」")

    def _finish_clip_selection(self, pdf_rect: fitz.Rect, global_pos) -> None:
        """彈出圈選圖面處理選單：支援標準高畫質複製、一鍵去背、去背+加深線條、按需 OCR、另存 PNG"""
        menu = QMenu(self)
        menu.setTitle("圈選圖面操作")
        act_std = menu.addAction(f"📋 複製高解析圖面 ({self.clip_dpi} DPI 原色)")
        act_trans = menu.addAction(f"✨ 一鍵去背複製 (白底轉透明 PNG, {self.clip_dpi} DPI)")
        act_enhance = menu.addAction(f"🖋️ 一鍵去背 + 線條加深複製 (貼入簡報/Word 最清晰)")
        menu.addSeparator()
        act_ocr = menu.addAction("🔍 對此圈選區域執行 OCR 文字辨識 (選用開啟)")
        menu.addSeparator()
        act_save = menu.addAction("💾 另存圈選區域為 PNG 圖片檔...")
        act_stamp = menu.addAction("📌 將此圈選區域轉為透明圖章貼在頁面上")

        chosen = menu.exec(global_pos)
        if chosen is None:
            return

        if chosen == act_std:
            png_bytes = self.engine.render_clip_high_dpi(
                self.current_page_index, pdf_rect, dpi=self.clip_dpi, transparent_bg=False, enhance_lines=False
            )
            self._copy_png_bytes_to_clipboard(png_bytes)
            self.status_message.emit(f"✓ 已複製 {self.clip_dpi} DPI 高解析圖面至剪貼簿！")

        elif chosen == act_trans:
            png_bytes = self.engine.render_clip_high_dpi(
                self.current_page_index, pdf_rect, dpi=self.clip_dpi, transparent_bg=True, enhance_lines=False
            )
            self._copy_png_bytes_to_clipboard(png_bytes)
            self.status_message.emit("✓ 已複製【一鍵去背透明背景 PNG】至剪貼簿！")

        elif chosen == act_enhance:
            png_bytes = self.engine.render_clip_high_dpi(
                self.current_page_index, pdf_rect, dpi=self.clip_dpi, transparent_bg=True, enhance_lines=True
            )
            self._copy_png_bytes_to_clipboard(png_bytes)
            self.status_message.emit("✓ 已複製【去背透明 + 線條加深強化圖面】至剪貼簿！")

        elif chosen == act_ocr:
            png_bytes = self.engine.render_clip_high_dpi(
                self.current_page_index, pdf_rect, dpi=300, transparent_bg=False, enhance_lines=True
            )
            self.request_ocr_bytes.emit(png_bytes)

        elif chosen == act_save:
            path, _ = QFileDialog.getSaveFileName(self, "另存圈選圖面", "圈選截圖.png", "PNG 圖片 (*.png)")
            if path:
                png_bytes = self.engine.render_clip_high_dpi(
                    self.current_page_index,
                    pdf_rect,
                    dpi=self.clip_dpi,
                    transparent_bg=self.clip_transparent,
                    enhance_lines=self.clip_enhance_lines,
                )
                with open(path, "wb") as f:
                    f.write(png_bytes)
                self.status_message.emit(f"✓ 已儲存高解析截圖：{path}")

        elif chosen == act_stamp:
            png_bytes = self.engine.render_clip_high_dpi(
                self.current_page_index, pdf_rect, dpi=300, transparent_bg=True, enhance_lines=True
            )
            self.place_interactive_image(png_bytes, default_pdf_width=pdf_rect.width)

    @staticmethod
    def _copy_png_bytes_to_clipboard(png_bytes: bytes) -> None:
        """同時以 PNG MIME 格式（保留透明背景供 Word/PowerPoint 使用）與 QImage 寫入系統剪貼簿"""
        qimg = QImage.fromData(png_bytes, "PNG")
        mime = QMimeData()
        mime.setImageData(qimg)
        mime.setData("image/png", QByteArray(png_bytes))
        QGuiApplication.clipboard().setMimeData(mime)

    # -------------------- 加入中文文字標註 --------------------

    def _prompt_and_add_text(self, pdf_pos: Tuple[float, float]) -> None:
        dlg = TextAnnotationDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = dlg.text_edit.toPlainText().strip()
        if not text:
            return

        c = dlg.text_color
        color_rgb = (c.redF(), c.greenF(), c.blueF())
        bg_rgb = None
        if dlg.chk_bg.isChecked():
            bc = dlg.bg_color
            bg_rgb = (bc.redF(), bc.greenF(), bc.blueF())
        border_rgb = color_rgb if dlg.chk_border.isChecked() else None

        self.engine.add_text_annotation_to_page(
            page_index=self.current_page_index,
            pdf_pos=pdf_pos,
            text=text,
            font_size=dlg.spin_size.value(),
            color_rgb=color_rgb,
            bg_color_rgb=bg_rgb,
            border_color_rgb=border_rgb,
        )
        self.render_current_page(preserve_scroll=True)
        self.page_modified.emit()
        self.status_message.emit("✓ 已寫入中文文字標註（可按 Ctrl+Z 復原）")

    # -------------------- 比例尺校正與距離/面積量測 --------------------

    def _draw_measure_marker(self, pdf_pt: Tuple[float, float]) -> None:
        sx, sy = pdf_pt[0] * self.zoom, pdf_pt[1] * self.zoom
        dot = self.scene_obj.addEllipse(
            sx - 4, sy - 4, 8, 8, QPen(QColor(220, 20, 20), 2), QBrush(QColor(255, 255, 0))
        )
        dot.setZValue(35)
        self._measure_items.append(dot)

        if len(self._measure_pdf_points) >= 2:
            p1 = self._measure_pdf_points[-2]
            p2 = self._measure_pdf_points[-1]
            line = self.scene_obj.addLine(
                p1[0] * self.zoom,
                p1[1] * self.zoom,
                p2[0] * self.zoom,
                p2[1] * self.zoom,
                QPen(QColor(220, 20, 20), 2.2),
            )
            line.setZValue(34)
            self._measure_items.append(line)

    def _get_page_scale(self) -> Tuple[float, str]:
        """取得當前頁面的 (points_per_unit, unit_name)，若未校正則預設以 PDF 實際毫米 (72/25.4 pt/mm) 計算"""
        if self.current_page_index in self.engine.page_scales:
            return self.engine.page_scales[self.current_page_index]
        return (72.0 / 25.4, "mm")

    def _handle_measure_click(self, pdf_pt: Tuple[float, float]) -> None:
        self._measure_pdf_points.append(pdf_pt)
        self._draw_measure_marker(pdf_pt)

        if self.tool_mode == "measure_scale" and len(self._measure_pdf_points) == 2:
            p1, p2 = self._measure_pdf_points[0], self._measure_pdf_points[1]
            pt_dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            self._measure_pdf_points.clear()
            if pt_dist < 1.0:
                return
            val_str, ok = QInputDialog.getText(
                self,
                "比例尺校正",
                "請輸入這段基準線代表的【實際長度與單位】\n（例如：10 m、500 cm、2400 mm）：",
                text="10 m",
            )
            if ok and val_str.strip():
                parts = val_str.strip().split()
                try:
                    real_len = float(parts[0])
                    unit = parts[1] if len(parts) > 1 else "m"
                    if real_len > 0:
                        pts_per_unit = pt_dist / real_len
                        self.engine.page_scales[self.current_page_index] = (pts_per_unit, unit)
                        self.status_message.emit(
                            f"✓ 已完成第 {self.current_page_index + 1} 頁比例尺校正：1 {unit} = {pts_per_unit:.2f} PDF pt，已自動切換至【距離量測】"
                        )
                        self.set_tool_mode("measure_dist")
                except ValueError:
                    QMessageBox.warning(self, "格式錯誤", "請輸入數字加上單位，例如：10 m 或 350 cm")

        elif self.tool_mode == "measure_dist" and len(self._measure_pdf_points) == 2:
            p1, p2 = self._measure_pdf_points[0], self._measure_pdf_points[1]
            pts = list(self._measure_pdf_points)
            self._measure_pdf_points.clear()

            pt_dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            pts_per_unit, unit = self._get_page_scale()
            real_dist = pt_dist / pts_per_unit
            label = f"{real_dist:.2f} {unit}"

            # 在畫布中心顯示量測標籤
            cx = (p1[0] + p2[0]) / 2 * self.zoom
            cy = (p1[1] + p2[1]) / 2 * self.zoom
            txt_item = self.scene_obj.addText(label, QFont("Microsoft JhengHei", 10, QFont.Weight.Bold))
            txt_item.setDefaultTextColor(QColor(180, 0, 0))
            txt_item.setPos(cx, cy - 20)
            txt_item.setZValue(36)
            self._measure_items.append(txt_item)

            self.status_message.emit(f"📏 量測距離：{label}")
            ans = QMessageBox.question(
                self,
                "距離量測結果",
                f"量測距離為： {label}\n\n是否將此尺寸標註線寫入 PDF 頁面？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ans == QMessageBox.StandardButton.Yes:
                self.engine.draw_measurement_on_page(self.current_page_index, pts, label, is_polygon=False)
                self.render_current_page(preserve_scroll=True)
                self.page_modified.emit()

    def _finish_area_measurement(self) -> None:
        pts = list(self._measure_pdf_points)
        self._measure_pdf_points.clear()
        if len(pts) < 3:
            return

        # 閉合多邊形視覺顯示
        poly = QPolygonF([QPointF(px * self.zoom, py * self.zoom) for px, py in pts])
        poly_item = QGraphicsPolygonItem(poly)
        poly_item.setPen(QPen(QColor(220, 20, 20), 2.0))
        poly_item.setBrush(QBrush(QColor(220, 20, 20, 45)))
        poly_item.setZValue(33)
        self.scene_obj.addItem(poly_item)
        self._measure_items.append(poly_item)

        # Shoelace 公式計算多邊形面積与周長
        pts_per_unit, unit = self._get_page_scale()
        area_pt2 = 0.0
        perim_pt = 0.0
        n = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            area_pt2 += x1 * y2 - x2 * y1
            perim_pt += math.hypot(x2 - x1, y2 - y1)
        area_pt2 = abs(area_pt2) / 2.0

        real_area = area_pt2 / (pts_per_unit ** 2)
        real_perim = perim_pt / pts_per_unit

        # 換算平方公尺與台灣常用「坪數」(1 m² = 0.3025 坪)
        ping_str = ""
        if unit.lower() == "m":
            ping = real_area * 0.3025
            ping_str = f" (約 {ping:.2f} 坪)"
        elif unit.lower() == "cm":
            m2 = real_area / 10000.0
            ping_str = f" ({m2:.2f} m² / 約 {m2 * 0.3025:.2f} 坪)"
        elif unit.lower() == "mm":
            m2 = real_area / 1_000_000.0
            ping_str = f" ({m2:.2f} m² / 約 {m2 * 0.3025:.2f} 坪)"

        label = f"面積: {real_area:.2f} {unit}²{ping_str} | 周長: {real_perim:.2f} {unit}"
        self.status_message.emit(f"📐 {label}")

        ans = QMessageBox.question(
            self,
            "面積量測結果",
            f"{label}\n\n是否將此多邊形面積標註寫入 PDF 頁面？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            short_label = f"{real_area:.2f} {unit}²{ping_str}"
            self.engine.draw_measurement_on_page(self.current_page_index, pts, short_label, is_polygon=True)
            self.render_current_page(preserve_scroll=True)
            self.page_modified.emit()
