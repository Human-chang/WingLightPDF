# -*- coding: utf-8 -*-
"""
將當前資料夾下的 WingLightPDF.exe 註冊至 Windows 目前使用者的 .pdf 檔案關聯清單 (OpenWithProgids & Applications)
同時支援綠色免安裝打包版 (sys.frozen) 與原始碼開發模式，移到任何電腦或磁碟槽皆可自動定位路徑。
"""

import os
import sys
import winreg
import ctypes


def get_app_root_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def register_pdf_association() -> str:
    app_dir = get_app_root_dir()
    exe_path = os.path.join(app_dir, "WingLightPDF.exe")
    if not os.path.exists(exe_path):
        # 相容舊檔名
        fallback = os.path.join(app_dir, "FastPDF.exe")
        if os.path.exists(fallback):
            exe_path = fallback
        else:
            raise FileNotFoundError(f"找不到 {exe_path}")

    cmd_str = f'"{exe_path}" "%1"'
    friendly_name = "WingLightPDF — 輕快免安裝PDF檢視與編輯工具"

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\WingLightPDF.Document") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "PDF Document (WingLightPDF)")
        winreg.SetValueEx(k, "FriendlyTypeName", 0, winreg.REG_SZ, friendly_name)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\WingLightPDF.Document\DefaultIcon") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, f'"{exe_path}",0')

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\WingLightPDF.Document\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd_str)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\Applications\WingLightPDF.exe") as k:
        winreg.SetValueEx(k, "FriendlyAppName", 0, winreg.REG_SZ, friendly_name)

    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER, r"Software\Classes\Applications\WingLightPDF.exe\SupportedTypes"
    ) as k:
        winreg.SetValueEx(k, ".pdf", 0, winreg.REG_SZ, "")

    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER, r"Software\Classes\Applications\WingLightPDF.exe\shell\open\command"
    ) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, cmd_str)

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.pdf\OpenWithProgids") as k:
        winreg.SetValueEx(k, "WingLightPDF.Document", 0, winreg.REG_NONE, b"")

    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
    return exe_path


if __name__ == "__main__":
    p = register_pdf_association()
    print(f"Registered successfully: {p}")
