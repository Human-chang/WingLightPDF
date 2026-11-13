# -*- coding: utf-8 -*-
"""「關於」視窗：產品名與版本、作者、可以點的 GitHub 連結（用預設瀏覽器開啟）。
左上放 WingLight 系列標誌（規範：標誌用在系列介紹、關於視窗、作者頁面）。
"""

from __future__ import annotations
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.version import APP_NAME, AUTHOR, AUTHOR_URL, SUBTITLE, VERSION
from ui import theme


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"關於 {APP_NAME}")
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 16)
        layout.setSpacing(16)

        head = QHBoxLayout()
        head.setSpacing(16)
        self.mark = QLabel()
        self.mark.setFixedSize(64, 64)
        mark_path = os.path.join(theme.assets_dir(), "logos", "winglight-mark.svg")
        try:
            with open(mark_path, encoding="utf-8") as f:
                pix = theme.svg_pixmap(f.read(), 128)
            pix.setDevicePixelRatio(2.0)
            self.mark.setPixmap(pix)
        except OSError:
            self.mark.hide()
        head.addWidget(self.mark, alignment=Qt.AlignmentFlag.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(4)
        title = QLabel(APP_NAME)
        title.setFont(theme.ui_font("page-title", bold=True))
        subtitle = QLabel(SUBTITLE)
        subtitle.setProperty("muted", True)
        self.version_label = QLabel(f"版本 {VERSION}")
        self.version_label.setProperty("muted", True)
        info.addWidget(title)
        info.addWidget(subtitle)
        info.addWidget(self.version_label)
        info.addSpacing(8)
        info.addWidget(QLabel(f"作者：{AUTHOR}"))
        self.link_label = QLabel(f'<a href="{AUTHOR_URL}" style="color: {theme.color("accent")};">{AUTHOR_URL}</a>')
        self.link_label.setTextFormat(Qt.TextFormat.RichText)
        self.link_label.setOpenExternalLinks(True)  # 交給 Windows 用預設瀏覽器開啟
        self.link_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        info.addWidget(self.link_label)
        head.addLayout(info, stretch=1)
        layout.addLayout(head)

        buttons = QHBoxLayout()
        buttons.addStretch()
        btn_close = QPushButton("關閉")
        btn_close.setDefault(True)
        theme.mark_primary(btn_close)
        btn_close.clicked.connect(self.accept)
        buttons.addWidget(btn_close)
        layout.addLayout(buttons)
