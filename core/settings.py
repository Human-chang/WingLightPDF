# -*- coding: utf-8 -*-
"""設定檔 WingLightPDF.json：存在程式旁邊，整個資料夾搬到別台電腦設定會跟著走；
那裡不能寫入時（例如 Program Files）改存到 %APPDATA%\\WingLightPDF。
裡面可能有使用者的資料夾路徑，已加進 .gitignore。
"""

from __future__ import annotations
import json
import os
import sys
from typing import Optional

APP_NAME = "WingLightPDF"
CONFIG_NAME = "WingLightPDF.json"
THEMES = ("light", "dark")


def app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _appdata_path() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME, CONFIG_NAME)


class Settings:
    def __init__(self, base_dir: Optional[str] = None) -> None:
        self.base_dir = base_dir or app_dir()
        self.path = os.path.join(self.base_dir, CONFIG_NAME)
        if not os.path.exists(self.path) and os.path.exists(_appdata_path()):
            self.path = _appdata_path()
        self.data = self._read(self.path) or {}

    @property
    def theme(self) -> Optional[str]:
        """使用者選過的主題；None 代表還沒選過，跟著 Windows。"""
        value = self.data.get("theme")
        return value if value in THEMES else None

    @theme.setter
    def theme(self, value: Optional[str]) -> None:
        if value in THEMES:
            self.data["theme"] = value
        else:
            self.data.pop("theme", None)

    @staticmethod
    def _read(path: str) -> Optional[dict]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            return None

    def save(self) -> None:
        try:
            self._write(self.path, self.data)
        except OSError:
            self.path = _appdata_path()
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            self._write(self.path, self.data)

    @staticmethod
    def _write(path: str, data: dict) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
