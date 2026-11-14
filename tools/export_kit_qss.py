# -*- coding: utf-8 -*-
"""
從 ui/theme.py 匯出 WingLight 設計規範 kit 用的 winglight.qss（樣式表範本＋色票表＋用法與踩過的坑）。
放回規範的 project/kit/winglight.qss 之前要先問使用者，並先重讀規範最新版。

用法：.venv\\Scripts\\python.exe tools\\export_kit_qss.py <輸出路徑>
"""

from __future__ import annotations
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from ui import theme  # noqa: E402

HEADER = """/*
 * WingLight 設計規範第 6 版（方向 B）的 Qt 樣式表範本，淺色、深色共用同一份。
 * 第一個實際使用的是 WingLightPDF v1.2.0（2026-11，PySide6 6.12，Windows 11 實測過深淺兩種主題）。
 *
 * 用法（完整程式見 WingLightPDF 的 ui/theme.py）：
 *   1. @色票名 換成目前主題的值（下表，名稱與 tokens.json 相同）。
 *   2. icon(圖示, 色票[, 旋轉角度]) 換成「規範 Icons 的 SVG 改成該色票筆畫顏色」後存成的檔案路徑。
 *      Qt 的 image: url() 只吃檔案；規範只有 chevron-down，上、左、右用旋轉 180、90、-90。
 *   3. QApplication.setStyleSheet() 套用，同時設定 QPalette 與 styleHints().setColorScheme()，
 *      訊息框、捲軸、標題列才會跟著深淺色。字型用 Microsoft JhengHei UI 13px（app.setFont）。
 *   4. 主要按鈕：button.setProperty("primary", True)；次要說明文字：label.setProperty("muted", True)。
 *      工具列上的按鈕平常沒有底色，滑鼠移過才浮出來；分頁列的軌道加 objectName "docTabBar"。
 *
 * 實際踩過的坑：
 *   - 介面文字裡的 emoji 會讓 Qt 第一次畫面多花約 0.8 秒找彩色字型（GDI 字型引擎也一樣），改用線條圖示後
 *     WingLightPDF 從原始碼建立主視窗由約 1.25 秒降到約 0.45 秒。
 *   - QAbstractSpinBox::up-button／down-button 寫 subcontrol-position 與 margin 時，
 *     NoButtons 的微調框裡面的輸入欄會變成 1px 寬，數字看不到。用 Qt 預設位置即可。
 *   - 用 border 畫三角形當箭頭在 Qt 不行（只會畫成一條橫線），一定要用圖示檔。
 *   - QMenu、QToolTip 是彈出視窗，border-radius 只會畫出直角，這裡不設圓角。
 *   - Qt 的 SVG 不支援 clip-path：App 圖示的高光會漏到圓角外，要自己裁（見 theme.svg_pixmap）。
 *
 *   色票           淺色      深色
{rows}
 *   canvas        {canvas_light}  {canvas_dark}  （規範沒有定義，PDF 頁面後面的底色）
 */

"""


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    rows = "\n".join(f" *   {name:<13} {light}  {dark}" for name, (light, dark) in theme.T.items() if name != "canvas")
    header = HEADER.format(rows=rows, canvas_light=theme.T["canvas"][0], canvas_dark=theme.T["canvas"][1])
    with open(sys.argv[1], "w", encoding="utf-8", newline="\n") as f:
        f.write(header + theme.QSS.strip() + "\n")
    print("已輸出", sys.argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main())
