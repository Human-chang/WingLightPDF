# -*- coding: utf-8 -*-
"""
常用圖章 / 簽名快速匣 (StampBoxPanel)
提供：
1. 內建快速公文章（核准、已審閱、機密、今日日期章，自動帶入當天日期）
2. 自訂文字印章產生器（可選紅/藍/綠印泥顏色、是否附加今日日期）
3. 常用圖片簽名檔 / 公司章收藏匣（自動保存在本地 stamps 資料夾，並支援匯入時自動白底去背轉透明 PNG！）
"""

from __future__ import annotations
import os
import io
import datetime
from typing import Optional
from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QPixmap, QIcon
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QMessageBox,
    QLabel,
)
from core.pdf_engine import generate_stamp_png_bytes


class StampBoxPanel(QWidget):
    """右側可收合的常用圖章與簽名快速匣"""

    stamp_bytes_triggered = Signal(bytes)  # 發送透明 PNG bytes 放置到當前 PDF 頁面上

    def __init__(self, stamps_dir: str, parent=None) -> None:
        super().__init__(parent)
        self.stamps_dir = stamps_dir
        os.makedirs(self.stamps_dir, exist_ok=True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # 1. 一鍵快速日期章與公文章
        quick_group = QGroupBox("⚡ 一鍵公文章 / 今日日期")
        q_layout = QVBoxLayout(quick_group)
        self.chk_with_date = QCheckBox("自動帶入今日日期")
        self.chk_with_date.setChecked(True)
        q_layout.addWidget(self.chk_with_date)

        row1 = QHBoxLayout()
        btn_approved = QPushButton("💮 核准")
        btn_reviewed = QPushButton("💮 已審閱")
        btn_approved.clicked.connect(lambda: self._emit_builtin_stamp("核 准", (210, 25, 25)))
        btn_reviewed.clicked.connect(lambda: self._emit_builtin_stamp("已審閱", (20, 90, 200)))
        row1.addWidget(btn_approved)
        row1.addWidget(btn_reviewed)
        q_layout.addLayout(row1)

        row2 = QHBoxLayout()
        btn_secret = QPushButton("💮 機密文件")
        btn_date_only = QPushButton("📅 今日日期章")
        btn_secret.clicked.connect(lambda: self._emit_builtin_stamp("機 密", (200, 20, 20)))
        btn_date_only.clicked.connect(self._emit_date_only_stamp)
        row2.addWidget(btn_secret)
        row2.addWidget(btn_date_only)
        q_layout.addLayout(row2)
        layout.addWidget(quick_group)

        # 2. 自訂文字印章產生器
        custom_group = QGroupBox("🖋️ 自訂文字印章")
        c_layout = QVBoxLayout(custom_group)
        self.txt_custom = QLineEdit()
        self.txt_custom.setPlaceholderText("輸入印章文字（如：急件、王小明）")
        c_layout.addWidget(self.txt_custom)

        c_row = QHBoxLayout()
        self.combo_color = QComboBox()
        self.combo_color.addItems(["朱紅色印泥", "公文藍印泥", "審核綠印泥", "深黑色"])
        c_row.addWidget(self.combo_color)
        btn_gen = QPushButton("產生並蓋章")
        btn_gen.clicked.connect(self._emit_custom_text_stamp)
        c_row.addWidget(btn_gen)
        c_layout.addLayout(c_row)
        layout.addWidget(custom_group)

        # 3. 常用圖片簽名檔 / 印章快速匣
        lib_group = QGroupBox("📁 常用透明簽名檔 / 圖章匣")
        l_layout = QVBoxLayout(lib_group)
        l_layout.addWidget(QLabel("點擊下方圖章即可放到頁面上拖曳定位："))

        self.stamp_list = QListWidget()
        self.stamp_list.setIconSize(QSize(120, 64))
        self.stamp_list.itemClicked.connect(self._on_saved_stamp_clicked)
        l_layout.addWidget(self.stamp_list)

        lib_btns = QHBoxLayout()
        btn_add_img = QPushButton("+ 匯入簽名/圖章")
        btn_del_img = QPushButton("🗑 移除")
        btn_add_img.clicked.connect(self._import_signature_image)
        btn_del_img.clicked.connect(self._delete_selected_stamp)
        lib_btns.addWidget(btn_add_img)
        lib_btns.addWidget(btn_del_img)
        l_layout.addLayout(lib_btns)
        layout.addWidget(lib_group, stretch=1)

        self.reload_saved_stamps()

    def _today_str(self) -> str:
        return datetime.date.today().strftime("%Y-%m-%d")

    def _emit_builtin_stamp(self, title: str, rgb: tuple) -> None:
        sub = self._today_str() if self.chk_with_date.isChecked() else ""
        png_bytes = generate_stamp_png_bytes(title, subtext=sub, color_rgb=rgb)
        self.stamp_bytes_triggered.emit(png_bytes)

    def _emit_date_only_stamp(self) -> None:
        png_bytes = generate_stamp_png_bytes(self._today_str(), subtext="", color_rgb=(20, 85, 195))
        self.stamp_bytes_triggered.emit(png_bytes)

    def _emit_custom_text_stamp(self) -> None:
        txt = self.txt_custom.text().strip()
        if not txt:
            QMessageBox.information(self, "提示", "請先輸入印章文字。")
            return
        colors = [
            (210, 25, 25),
            (20, 90, 200),
            (20, 140, 60),
            (40, 40, 40),
        ]
        rgb = colors[self.combo_color.currentIndex()]
        sub = self._today_str() if self.chk_with_date.isChecked() else ""
        png_bytes = generate_stamp_png_bytes(txt, subtext=sub, color_rgb=rgb)
        self.stamp_bytes_triggered.emit(png_bytes)

    def reload_saved_stamps(self) -> None:
        self.stamp_list.clear()
        if not os.path.exists(self.stamps_dir):
            return
        for fname in sorted(os.listdir(self.stamps_dir)):
            if fname.lower().endswith((".png", ".jpg", ".jpeg")):
                fpath = os.path.join(self.stamps_dir, fname)
                pix = QPixmap(fpath)
                if not pix.isNull():
                    item = QListWidgetItem(QIcon(pix), os.path.splitext(fname)[0])
                    item.setData(Qt.ItemDataRole.UserRole, fpath)
                    self.stamp_list.addItem(item)

    def _on_saved_stamp_clicked(self, item: QListWidgetItem) -> None:
        fpath = item.data(Qt.ItemDataRole.UserRole)
        if fpath and os.path.exists(fpath):
            with open(fpath, "rb") as f:
                self.stamp_bytes_triggered.emit(f.read())

    def _import_signature_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇簽名檔或印章圖片", "", "圖片檔案 (*.png *.jpg *.jpeg *.bmp)"
        )
        if not path:
            return
        ans = QMessageBox.question(
            self,
            "自動一鍵去背",
            "是否自動將圖片的淺白色背景轉為「透明背景 PNG」？\n（若為白紙手寫簽名或掃描印章，強烈建議選「是」）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        base_name = os.path.splitext(os.path.basename(path))[0]
        target_path = os.path.join(self.stamps_dir, f"{base_name}.png")

        try:
            import numpy as np
            from PIL import Image

            img = Image.open(path).convert("RGBA")
            if ans == QMessageBox.StandardButton.Yes:
                arr = np.array(img, dtype=np.uint8)
                lum = (
                    0.299 * arr[:, :, 0].astype(np.float32)
                    + 0.587 * arr[:, :, 1].astype(np.float32)
                    + 0.114 * arr[:, :, 2].astype(np.float32)
                )
                # 將亮度高於 225 的白底轉為透明
                alpha = np.where(lum >= 225, 0, arr[:, :, 3]).astype(np.uint8)
                arr[:, :, 3] = alpha
                img = Image.fromarray(arr, mode="RGBA")
            img.save(target_path, format="PNG")
            self.reload_saved_stamps()
        except Exception as e:
            QMessageBox.warning(self, "匯入錯誤", f"無法處理圖片：{e}")

    def _delete_selected_stamp(self) -> None:
        curr = self.stamp_list.currentItem()
        if curr is None:
            return
        fpath = curr.data(Qt.ItemDataRole.UserRole)
        if fpath and os.path.exists(fpath):
            try:
                os.remove(fpath)
                self.reload_saved_stamps()
            except Exception as e:
                QMessageBox.warning(self, "刪除失敗", str(e))
