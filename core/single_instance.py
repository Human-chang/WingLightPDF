# -*- coding: utf-8 -*-
"""
單一執行個體：已經有 WingLightPDF 在執行時，新開的 PDF 交給它加到分頁，不再從頭啟動一份。

- 用具名 Mutex 判斷誰是主程式（只靠 ctypes，不必先載入 Qt，判斷很快）。
- 主程式以 Python 內建的 multiprocessing.connection 開一條具名管道接收檔案路徑。
  不用 QLocalServer，因為打包時刻意排除了 QtNetwork（會連帶夾帶 OpenSSL）。
- 啟動器 WingLightPDF.exe（assets/launcher.cs）也會先試著把檔案交給主程式，
  成功就直接結束，連啟動畫面和 Python 核心都不用跑。
- 管道與 Mutex 名稱都以 Windows 登入工作階段區分，不同使用者互不干擾。
"""

import ctypes
import json
import os
import threading
import time
from ctypes import wintypes

MUTEX_NAME = "Local\\WingLightPDF.Primary"
_ERROR_ALREADY_EXISTS = 183
_ASFW_ANY = -1


def _session_id() -> int:
    sid = wintypes.DWORD(0)
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    return sid.value


def pipe_address() -> str:
    return "\\\\.\\pipe\\WingLightPDF-s" + str(_session_id())


class SingleInstance:
    def __init__(self) -> None:
        self._mutex = None
        self.is_primary = self.claim()

    def claim(self) -> bool:
        """搶主程式的位置；Mutex 一直開到程式結束，由系統自動釋放。"""
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = wintypes.HANDLE
        k32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        handle = k32.CreateMutexW(None, False, MUTEX_NAME)
        if not handle:
            return True  # 建不出 Mutex 就照舊當一般程式執行
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            k32.CloseHandle(handle)
            return False
        self._mutex = handle
        self.is_primary = True
        return True

    def send(self, files, timeout: float = 15.0) -> bool:
        """把檔案交給主程式；主程式可能還在啟動，最多等 timeout 秒。收到確認才算成功。"""
        return send_files(pipe_address(), files, timeout)

    def serve(self, on_files) -> bool:
        """在背景執行緒接收其他啟動要求。on_files(list[str]) 會在背景執行緒被呼叫。"""
        return start_server(pipe_address(), on_files)


def send_files(address: str, files, timeout: float = 15.0) -> bool:
    from multiprocessing.connection import Client

    # 讓主程式可以把視窗帶到最前面（Windows 只允許前景程式轉讓前景權）
    ctypes.windll.user32.AllowSetForegroundWindow(_ASFW_ANY)
    payload = json.dumps({"files": list(files)}, ensure_ascii=False).encode("utf-8")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            conn = Client(address, family="AF_PIPE")
        except OSError:
            time.sleep(0.1)  # 主程式還沒開始接收
            continue
        try:
            conn.send_bytes(payload)
            return bool(conn.poll(5)) and conn.recv_bytes(16) == b"OK"
        except (OSError, EOFError):
            return False
        finally:
            conn.close()
    return False


def start_server(address: str, on_files) -> bool:
    from multiprocessing.connection import Listener

    try:
        listener = Listener(address, family="AF_PIPE")
    except OSError:
        return False
    threading.Thread(target=_serve_forever, args=(listener, on_files), daemon=True,
                     name="WingLightPDF-single-instance").start()
    return True


def _serve_forever(listener, on_files) -> None:
    while True:
        try:
            conn = listener.accept()
        except OSError:
            time.sleep(0.2)
            continue
        try:
            if not conn.poll(5):
                continue
            message = json.loads(conn.recv_bytes(1 << 20).decode("utf-8"))
            files = [p for p in message.get("files", []) if isinstance(p, str)]
            on_files(files)
            conn.send_bytes(b"OK")
        except (OSError, EOFError, ValueError, AttributeError):
            pass
        finally:
            conn.close()
