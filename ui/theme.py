# -*- coding: utf-8 -*-
"""
WingLight 設計規範第 6 版（方向 B）的色票與 Qt 樣式表。

- 淺色、深色兩套主題；第一次開啟跟著 Windows，使用者在「檢視」選單切換後記在 WingLightPDF.json。
- 色票名稱與 tokens.json 相同，每個值是 (淺色, 深色)。
- 樣式表裡用 @色票名 代入目前主題的顏色；icon(圖示, 色票[, 旋轉角度]) 代入換好顏色的線條圖示檔。
"""

from __future__ import annotations
import hashlib
import os
import re
import tempfile
from functools import lru_cache
from typing import Optional

import shiboken6
from PySide6.QtCore import QByteArray, QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

T = {
    "bg": ("#F6F5F3", "#1C1B1A"),
    "panel": ("#FFFFFF", "#272625"),
    "chrome": ("#EEECE8", "#141312"),
    "input": ("#F6F5F3", "#1C1B1A"),
    "hover": ("#E6E3DD", "#33312F"),
    "soft": ("#E6ECFB", "#2A3152"),
    "line": ("#E3E0DB", "#3D3B38"),
    "text": ("#1F1E1C", "#F2F0EC"),
    "muted": ("#5F5B55", "#B0ABA3"),
    "disabled": ("#A39E96", "#6E6A64"),
    "accent": ("#2B55D4", "#8FA8FF"),
    "accent-hover": ("#2347B8", "#A9BCFF"),
    "on-accent": ("#FFFFFF", "#10142B"),
    "ok": ("#1B7550", "#6FD3A6"),
    "warn": ("#8A5300", "#F2C46B"),
    "hi": ("#C2362F", "#FF8A80"),
    # 只用在 App 圖示、啟動畫面，深淺色相同
    "product-pdf": ("#D8433B", "#D8433B"),
    "glow": ("#FFC83D", "#FFC83D"),
    "splash-bg": ("#151A2E", "#151A2E"),
    "splash-text": ("#F2F0EC", "#F2F0EC"),
    "splash-muted": ("#B0ABA3", "#B0ABA3"),
    # 規範沒有定義：PDF 頁面後面的底色。白色頁面在淺色的 bg 上分不出邊界，改用深一階的 hover
    "canvas": ("#E6E3DD", "#141312"),
}

THEMES = ("light", "dark")
FONT_UI = "Microsoft JhengHei UI"
FONT_MONO = "Consolas"
FONT_PX = {"page-title": 20, "card-title": 14, "body": 13, "caption": 12, "overline": 11}

QSS = """
QMainWindow, QDialog { background-color: @bg; }
QWidget { color: @text; }
QLabel { background-color: transparent; }
QLabel[muted="true"] { color: @muted; font-size: 12px; }
QLabel[accent="true"] { color: @accent; font-weight: bold; }

QToolTip {
    background-color: @text; color: @bg; border: none;
    padding: 4px 8px; font-size: 12px;
}

/* ---------- MenuBar ---------- */
QMenuBar {
    background-color: @chrome; border-bottom: 1px solid @line;
    padding: 4px 8px; spacing: 2px;
}
QMenuBar::item { background-color: transparent; color: @text; padding: 4px 10px; border-radius: 6px; }
QMenuBar::item:selected, QMenuBar::item:pressed { background-color: @hover; }
QMenu {
    background-color: @panel; color: @text; border: 1px solid @line; padding: 4px;
}
QMenu::item { background-color: transparent; padding: 6px 24px 6px 32px; border-radius: 6px; }
QMenu::icon, QMenu::indicator { left: 8px; }
QMenu::indicator { width: 16px; height: 16px; }
QMenu::indicator:checked { image: url(icon(check, accent)); }
QMenu::item:selected { background-color: @hover; color: @text; }
QMenu::item:disabled { color: @disabled; }
QMenu::separator { height: 1px; background-color: @line; margin: 4px 6px; }

/* ---------- 次要按鈕（預設） ---------- */
QPushButton, QToolButton {
    background-color: @panel; color: @text; border: 1px solid @line; border-radius: 8px;
    padding: 5px 12px;
}
QPushButton:hover, QToolButton:hover { background-color: @hover; }
QPushButton:focus { border: 2px solid @accent; padding: 4px 11px; }
QPushButton:checked, QToolButton:checked { background-color: @soft; color: @accent; font-weight: bold; }
QPushButton:disabled, QToolButton:disabled { background-color: @bg; color: @disabled; }

/* ---------- 主要按鈕：一個畫面只有一個 ---------- */
QPushButton[primary="true"] {
    background-color: @accent; color: @on-accent; border: 1px solid @accent; font-weight: bold;
    padding: 6px 24px;
}
QPushButton[primary="true"]:hover { background-color: @accent-hover; border-color: @accent-hover; }
QPushButton[primary="true"]:focus { border: 2px solid @accent-hover; padding: 5px 23px; }
QPushButton[primary="true"]:disabled { background-color: @bg; color: @disabled; border-color: @line; }

/* ---------- Toolbar：按鈕平常沒有底色和外框 ---------- */
QToolBar {
    background-color: @chrome; border: none; border-bottom: 1px solid @line;
    padding: 6px 8px; spacing: 2px;
}
QToolBar::separator { background-color: @line; width: 1px; margin: 6px 6px; }
QToolBar QToolButton, QToolBar QPushButton, QPushButton[flat="true"] {
    background-color: transparent; border: 1px solid transparent; padding: 5px 10px;
}
QToolBar QToolButton:hover, QToolBar QPushButton:hover, QPushButton[flat="true"]:hover {
    background-color: @hover;
}
QToolBar QToolButton:checked, QToolBar QPushButton:checked, QPushButton[flat="true"]:checked {
    background-color: @soft; color: @accent; font-weight: bold;
}
QToolBar QToolButton:disabled, QToolBar QPushButton:disabled, QPushButton[flat="true"]:disabled {
    background-color: transparent; color: @disabled;
}
QToolBar QPushButton:focus, QPushButton[flat="true"]:focus { border: 1px solid transparent; padding: 5px 10px; }
QToolBar QLabel { color: @muted; }

/* ---------- Input ---------- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: @panel; color: @text; border: 1px solid @line; border-radius: 8px;
    padding: 4px 8px; selection-background-color: @soft; selection-color: @text;
}
QTextEdit, QPlainTextEdit {
    background-color: @panel; color: @text; border: 1px solid @line; border-radius: 8px;
    padding: 4px; selection-background-color: @soft; selection-color: @text;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 2px solid @accent; padding: 3px 7px;
}
QTextEdit:focus, QPlainTextEdit:focus { border: 2px solid @accent; padding: 3px; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled,
QTextEdit:disabled, QPlainTextEdit:disabled { background-color: @bg; color: @disabled; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url(icon(chevron-down, muted)); width: 14px; height: 14px; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
    subcontrol-origin: border; width: 18px; border: none; background-color: transparent;
}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover { background-color: @hover; border-radius: 4px; }
QAbstractSpinBox::up-arrow { image: url(icon(chevron-down, muted, 180)); width: 12px; height: 12px; }
QAbstractSpinBox::down-arrow { image: url(icon(chevron-down, muted)); width: 12px; height: 12px; }
QAbstractSpinBox { padding-right: 22px; }
QSpinBox#pageSpin { padding: 4px 6px; }
QSpinBox#pageSpin:focus { padding: 3px 5px; }
QSpinBox#pageSpin::up-button, QSpinBox#pageSpin::down-button { width: 0; margin: 0; }
QComboBox QAbstractItemView {
    background-color: @panel; color: @text; border: 1px solid @line; padding: 4px; outline: 0;
    selection-background-color: @soft; selection-color: @accent;
}

/* ---------- List ---------- */
QListView, QTreeView, QTableView {
    background-color: @panel; color: @text; border: 1px solid @line; border-radius: 8px;
    alternate-background-color: @bg; outline: 0;
}
QListView::item { padding: 4px; border-radius: 6px; }
QTreeView::item { padding: 3px 0; }
QListView::item:hover, QTreeView::item:hover { background-color: @hover; }
QListView::item:selected, QTreeView::item:selected, QTableView::item:selected {
    background-color: @soft; color: @text;
}
QHeaderView::section {
    background-color: @bg; color: @muted; border: none; border-bottom: 1px solid @line;
    padding: 4px 8px; font-size: 12px;
}

/* ---------- Tabs：軌道上一塊白色，目前分頁用靛藍粗體字 ---------- */
QTabWidget::pane { background-color: @panel; border: 1px solid @line; border-radius: 10px; top: -1px; }
QTabBar { background-color: transparent; }
QTabBar::tab {
    background-color: transparent; color: @muted; border: none; border-radius: 8px;
    padding: 6px 12px; margin: 4px 1px;
}
QTabBar::tab:hover { background-color: @hover; color: @text; }
QTabBar::tab:selected { background-color: @panel; color: @accent; font-weight: bold; }
QTabBar#docTabBar { background-color: @chrome; border-radius: 10px; }
QTabBar QToolButton { background-color: @chrome; border: none; border-radius: 6px; padding: 0; }
QTabBar QToolButton:hover { background-color: @hover; }
QTabBar QToolButton::left-arrow { image: url(icon(chevron-down, muted, 90)); width: 14px; height: 14px; }
QTabBar QToolButton::right-arrow { image: url(icon(chevron-down, muted, -90)); width: 14px; height: 14px; }
QTabBar#navTabBar::tab { padding: 6px 8px; }

/* ---------- Panel ---------- */
QGroupBox {
    background-color: @panel; border: 1px solid @line; border-radius: 10px;
    margin-top: 12px; padding: 14px 16px 12px 16px; font-size: 14px; font-weight: bold;
}
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; color: @text; }
QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QRadioButton { font-size: 13px; font-weight: normal; }

QProgressBar {
    background-color: @input; border: 1px solid @line; border-radius: 6px; text-align: center;
    color: @text; font-size: 12px; min-height: 16px;
}
QProgressBar::chunk { background-color: @accent; border-radius: 5px; }

QCheckBox { spacing: 8px; }
QCheckBox::indicator {
    width: 16px; height: 16px; border: 1px solid @muted; border-radius: 4px; background-color: @panel;
}
QCheckBox::indicator:checked { background-color: @accent; border-color: @accent; image: url(icon(check, on-accent)); }
QCheckBox::indicator:disabled { background-color: @bg; border-color: @disabled; }

QToolButton[popupMode="2"] { padding-right: 22px; }
QToolButton::menu-indicator {
    image: url(icon(chevron-down, muted)); width: 12px; height: 12px;
    subcontrol-origin: padding; subcontrol-position: center right; right: 6px;
}

QSplitter::handle { background-color: @bg; }

/* ---------- StatusBar ---------- */
QStatusBar { background-color: @chrome; border-top: 1px solid @line; color: @text; font-size: 12px; }
QStatusBar::item { border: none; }
QStatusBar QLabel { font-size: 12px; }
QStatusBar QLabel[muted="true"] { padding: 0 8px; }
"""

_TOKEN_RE = re.compile(r"@([a-z][a-z-]*)")
_ICON_RE = re.compile(r"icon\(([\w-]+),\s*([\w-]+)(?:,\s*(-?\d+))?\)")
_SVG_STROKE_RE = re.compile(r'stroke="[^"]*"')


class _ThemeSignals(QObject):
    changed = Signal(str)


_signals: Optional[_ThemeSignals] = None
_settings = None
_current = "light"
_applied = False


def signals() -> _ThemeSignals:
    global _signals
    if _signals is None:
        _signals = _ThemeSignals()
    return _signals


def windows_prefers_dark() -> bool:
    """讀 Windows「選擇您的應用程式模式」：AppsUseLightTheme = 0 代表深色。"""
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except (OSError, ImportError):
        return False


def current() -> str:
    return _current


def color(name: str, theme: Optional[str] = None) -> str:
    light, dark = T[name]
    return dark if (theme or _current) == "dark" else light


def qcolor(name: str, alpha: int = 255) -> QColor:
    c = QColor(color(name))
    c.setAlpha(alpha)
    return c


def assets_dir() -> str:
    from core.settings import app_dir
    return os.path.join(app_dir(), "assets")


@lru_cache(maxsize=None)
def _read_icon(name: str) -> str:
    with open(os.path.join(assets_dir(), "icons", f"{name}.svg"), encoding="utf-8") as f:
        return f.read()


def icon_svg(name: str, hex_color: str, size: int = 16, rotate: int = 0) -> str:
    """規範的線條圖示（assets/icons/<name>.svg）換成指定的筆畫顏色與大小。"""
    head, _, body = _read_icon(name).partition(">")
    head = _SVG_STROKE_RE.sub(f'stroke="{hex_color}"', head)
    head = re.sub(r'(?<![\w-])width="[^"]*"', f'width="{size}"', head)  # 不能動到 stroke-width
    head = re.sub(r'(?<![\w-])height="[^"]*"', f'height="{size}"', head)
    if rotate:
        body = body.replace("</svg>", "</g></svg>")
        body = f'<g transform="rotate({rotate} 12 12)">' + body
    return head + ">" + body


def _icon_file(name: str, token: str, theme: str, rotate: int = 0) -> str:
    """樣式表的 image: url() 只吃檔案：換好顏色的圖示寫到暫存資料夾，同一個組合只寫一次。"""
    folder = os.path.join(tempfile.gettempdir(), "WingLightPDF-icons")
    try:
        svg = icon_svg(name, color(token, theme), rotate=rotate)
        # 檔名用內容的雜湊：圖示或顏色改了就是新檔名，不會讀到舊版留下的檔案
        path = os.path.join(folder, f"{name}-{hashlib.sha1(svg.encode('utf-8')).hexdigest()[:10]}.svg")
        if not os.path.exists(path):
            os.makedirs(folder, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
    except OSError:
        return ""  # 找不到圖示或暫存資料夾不能寫：少一個箭頭，不影響使用
    return path.replace("\\", "/")


def stylesheet(theme: str) -> str:
    # 先代入色票再代入圖示路徑：暫存資料夾的路徑裡就算有 @ 也不會被當成色票
    qss = _TOKEN_RE.sub(lambda m: color(m.group(1), theme), QSS)
    return _ICON_RE.sub(lambda m: _icon_file(m.group(1), m.group(2), theme, int(m.group(3) or 0)), qss)


_ICON_PX = (16, 32)  # 100% 用 16，150%～200% 縮放時 Qt 從 32 縮小
_icon_cache: dict = {}
_bound: list = []


def svg_pixmap(svg: str, px: int) -> QPixmap:
    from PySide6.QtSvg import QSvgRenderer

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pix = QPixmap(px, px)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    return pix


def icon(name: str, rotate: int = 0, token: str = "muted") -> QIcon:
    """規範的線條圖示：平常用 token 色（預設 muted）、勾選中 accent、停用 disabled。"""
    key = (name, rotate, token, _current)
    cached = _icon_cache.get(key)
    if cached is not None:
        return cached
    result = QIcon()
    try:
        for mode, state, tok in (
            (QIcon.Mode.Normal, QIcon.State.Off, token),
            (QIcon.Mode.Normal, QIcon.State.On, "accent"),
            (QIcon.Mode.Disabled, QIcon.State.Off, "disabled"),
            (QIcon.Mode.Disabled, QIcon.State.On, "disabled"),
        ):
            svg = icon_svg(name, color(tok), rotate=rotate)
            for px in _ICON_PX:
                result.addPixmap(svg_pixmap(svg, px), mode, state)
    except OSError:
        result = QIcon()  # 找不到圖示檔：只顯示文字
    _icon_cache[key] = result
    return result


def bind_icon(target, name: str, rotate: int = 0) -> None:
    """設定按鈕或動作的圖示，切換深淺色時自動換成新顏色。"""
    target.setIcon(icon(name, rotate))
    _bound.append((target, name, rotate))


def _rebind_icons() -> None:
    alive = []
    for target, name, rotate in _bound:
        if shiboken6.isValid(target):
            target.setIcon(icon(name, rotate))
            alive.append((target, name, rotate))
    _bound[:] = alive


def ui_font(size: str = "body", bold: bool = False) -> QFont:
    font = QFont(FONT_UI)
    font.setPixelSize(FONT_PX[size])
    font.setBold(bold)
    return font


def _palette(theme: str) -> QPalette:
    """樣式表管不到的地方（訊息框、捲軸、勾選框）也跟著主題。"""
    def c(name: str) -> QColor:
        return QColor(color(name, theme))

    pal = QPalette()
    for role, name in (
        (QPalette.ColorRole.Window, "bg"),
        (QPalette.ColorRole.WindowText, "text"),
        (QPalette.ColorRole.Base, "panel"),
        (QPalette.ColorRole.AlternateBase, "bg"),
        (QPalette.ColorRole.Text, "text"),
        (QPalette.ColorRole.Button, "panel"),
        (QPalette.ColorRole.ButtonText, "text"),
        (QPalette.ColorRole.Highlight, "accent"),
        (QPalette.ColorRole.HighlightedText, "on-accent"),
        (QPalette.ColorRole.ToolTipBase, "text"),
        (QPalette.ColorRole.ToolTipText, "bg"),
        (QPalette.ColorRole.PlaceholderText, "muted"),
        (QPalette.ColorRole.Link, "accent"),
        (QPalette.ColorRole.Light, "panel"),
        (QPalette.ColorRole.Midlight, "line"),
        (QPalette.ColorRole.Mid, "line"),
        (QPalette.ColorRole.Dark, "muted"),
    ):
        pal.setColor(role, c(name))
    for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, c("disabled"))
    return pal


def _apply(theme: str) -> None:
    global _current, _applied
    _current = theme
    _applied = True
    app = QApplication.instance()
    if app is None:
        return
    try:
        # 標題列、捲軸這些由 Windows 畫的部分跟著深淺色（Qt 6.8 起）
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark if theme == "dark" else Qt.ColorScheme.Light)
    except AttributeError:
        pass
    app.setPalette(_palette(theme))
    app.setStyleSheet(stylesheet(theme))
    _rebind_icons()


def init(settings=None) -> None:
    """建立 QApplication 之後、建立視窗之前呼叫；settings 為 None 時讀程式旁邊的 WingLightPDF.json。"""
    global _settings
    if settings is None:
        from core.settings import Settings
        settings = Settings()
    _settings = settings
    app = QApplication.instance()
    if app is not None:
        app.setFont(ui_font())
    _apply(settings.theme or ("dark" if windows_prefers_dark() else "light"))


def ensure_applied() -> None:
    if not _applied:
        init()


def set_theme(theme: str) -> None:
    if theme not in THEMES or theme == _current:
        return
    if _settings is not None:
        _settings.theme = theme
        try:
            _settings.save()
        except OSError:
            pass  # 存不了設定不影響這次切換
    _apply(theme)
    signals().changed.emit(theme)


def mark_primary(button) -> None:
    """標記畫面上唯一的主要按鈕（靛藍填色）。"""
    button.setProperty("primary", True)
    button.style().unpolish(button)
    button.style().polish(button)
