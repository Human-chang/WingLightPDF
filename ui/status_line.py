# -*- coding: utf-8 -*-
"""
狀態列與對話框裡的「現在在做什麼」（WingLight 設計規範 StatusBar 元件）：
最前面一個 14px 的狀態圖示，後面一句話。四種狀態一定同時有圖示和字：
- busy：8px 的 glow 圓點慢慢一明一暗（2.2 秒一個週期），Windows 關掉動畫效果時只顯示亮的
- ok：ok 色的打勾
- warn：warn 色的警告圖示
- error：hi 色的警告圖示
info 是一般說明，不放圖示。
"""

from __future__ import annotations
import ctypes
import math
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QStatusBar, QWidget

from ui import theme

KINDS = ("info", "busy", "ok", "warn", "error")
_STATUS_ICON = {"ok": ("check", "ok"), "warn": ("warning", "warn"), "error": ("warning", "hi")}


def animations_enabled() -> bool:
    """Windows「顯示 Windows 中的動畫」(SPI_GETCLIENTAREAANIMATION)；讀不到時當作開著。"""
    try:
        value = ctypes.c_int(1)
        ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0)
        return bool(value.value)
    except (AttributeError, OSError):
        return True


class GlowDot(QWidget):
    PERIOD_S = 2.2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.update)

    def start(self) -> None:
        self._t0 = time.monotonic()
        if animations_enabled():
            self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()

    def level(self) -> float:
        if not self._timer.isActive():
            return 1.0
        phase = (time.monotonic() - self._t0) / self.PERIOD_S
        return 0.3 + 0.7 * (0.5 - 0.5 * math.cos(2 * math.pi * phase))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.qcolor("glow", int(255 * self.level())))
        painter.drawEllipse(QRectF(3, 3, 8, 8))
        painter.end()


class StatusLine(QWidget):
    def __init__(self, text: str = "", kind: str = "info", parent=None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(14, 14)
        self.dot = GlowDot()
        self.text_label = QLabel()
        self.text_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.icon_label)
        layout.addWidget(self.dot)
        layout.addWidget(self.text_label, stretch=1)
        self.kind = "info"
        theme.signals().changed.connect(self._refresh_icon)
        self.show_status(text, kind)

    def show_status(self, text: str, kind: str = "info") -> None:
        if kind not in KINDS:
            kind = "info"
        self.kind = kind
        self.text_label.setText(text)
        if kind == "busy":
            self.dot.show()
            self.dot.start()
        else:
            self.dot.stop()
            self.dot.hide()
        self._refresh_icon()

    def setText(self, text: str) -> None:
        """背景工作回報的進度文字：維持目前的狀態（處理中還是處理中）。"""
        self.show_status(text, self.kind)

    def text(self) -> str:
        return self.text_label.text()

    def set_busy(self, text: str) -> None:
        self.show_status(text, "busy")

    def set_ok(self, text: str) -> None:
        self.show_status(text, "ok")

    def set_warn(self, text: str) -> None:
        self.show_status(text, "warn")

    def set_error(self, text: str) -> None:
        self.show_status(text, "error")

    def _refresh_icon(self, _name: str = "") -> None:
        spec = _STATUS_ICON.get(self.kind)
        if spec is None:
            self.icon_label.clear()
            self.icon_label.hide()
            return
        name, token = spec
        self.icon_label.setPixmap(theme.icon(name, token=token).pixmap(14, 14))
        self.icon_label.show()


class StatusBar(QStatusBar):
    """主視窗的狀態列：左邊是 StatusLine，showMessage 照舊可以用（當作一般說明）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizeGripEnabled(True)
        self.line = StatusLine()
        self.line.setContentsMargins(12, 0, 0, 0)
        self.addWidget(self.line, 1)

    def showMessage(self, text: str, timeout: int = 0) -> None:  # noqa: N802 (Qt 的名稱)
        self.line.show_status(text, "info")

    def show_status(self, text: str, kind: str = "info") -> None:
        self.line.show_status(text, kind)

    def currentMessage(self) -> str:  # noqa: N802
        return self.line.text()
