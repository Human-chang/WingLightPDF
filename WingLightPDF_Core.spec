# -*- mode: python ; coding: utf-8 -*-
"""
WingLightPDF 核心程式打包設定（PyInstaller onedir）
用法：python -m PyInstaller --noconfirm --clean --distpath _dist_tmp --workpath build_tmp WingLightPDF_Core.spec -- --edition full
  --edition full：完整版，OCR 使用 RapidOCR PP-OCRv6（繁體與數字表格都準）
  --edition lite：輕量版，不打包 RapidOCR / OpenCV / onnxruntime，OCR 改用 Windows 內建引擎

瘦身原則：程式只用到 QtCore / QtGui / QtWidgets / QtPrintSupport，
移除 OpenCV 影片解碼、Qt 軟體 OpenGL、Qt Quick/Qml/Pdf/Network、翻譯檔等用不到的執行期元件。
"""
import argparse
import os
from fnmatch import fnmatch

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(SPECPATH)

parser = argparse.ArgumentParser()
parser.add_argument("--edition", choices=["full", "lite"], default="full")
EDITION = parser.parse_args().edition

hiddenimports = []
datas = []
if EDITION == "full":
    # rapidocr 以 importlib 延遲載入 .main 等子模組，需明確列出；排除未使用的推論後端
    RAPIDOCR_UNUSED_BACKENDS = (".openvino", ".paddle", ".pytorch", ".tensorrt", ".mnn")
    hiddenimports += collect_submodules(
        "rapidocr", filter=lambda name: not any(b in name for b in RAPIDOCR_UNUSED_BACKENDS)
    )
    # PP-OCRv6 small 模型檔與設定檔隨套件打包，執行時不會連網下載
    datas += collect_data_files("rapidocr")

EXCLUDES = [
    "PySide6.QtNetwork",  # 只因 PySide6 模組清單被誤判引用；載入它還會讓 PyInstaller 從 PATH 夾帶 OpenSSL
    "setuptools",
    "_distutils_hack",
    "pydoc_data",
    "tkinter",
    "PIL._avif",
    "PIL.AvifImagePlugin",
    "rapidocr_onnxruntime",
    "matplotlib",
    "pandas",
    "scipy",
    "IPython",
    "pytest",
]
if EDITION == "lite":
    EXCLUDES += ["rapidocr", "onnxruntime", "cv2"]

# 用不到的執行期檔案（比對 _internal 內的相對路徑，不分大小寫）
DROP_PATTERNS = [
    "cv2/opencv_videoio_ffmpeg*.dll",  # OpenCV 影片解碼，OCR 用不到
    "PySide6/opengl32sw.dll",  # Qt 軟體 OpenGL 備援，畫布未使用 OpenGL
    "PySide6/Qt6Quick*.dll",
    "PySide6/Qt6Qml*.dll",
    "PySide6/Qt6VirtualKeyboard*.dll",
    "PySide6/Qt6Pdf*.dll",  # PDF 由 PyMuPDF 處理
    "PySide6/Qt6Network*.dll",
    "PySide6/Qt6OpenGL*.dll",
    "PySide6/plugins/platforminputcontexts/*",
    "PySide6/plugins/tls/*",
    "PySide6/plugins/networkinformation/*",
    "PySide6/plugins/generic/*",
    "PySide6/plugins/imageformats/qpdf.dll",
    "PySide6/translations/*",  # 程式未載入 Qt 翻譯
    "libcrypto-3-x64.dll",  # 防止從 PATH（例如 Git 的 ucrt64）夾帶第二份 OpenSSL
    "libssl-3-x64.dll",
]


def _keep(entry):
    dest = entry[0].replace("\\", "/").lower()
    return not any(fnmatch(dest, p.lower()) for p in DROP_PATTERNS)


a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=0,
)
a.binaries = [e for e in a.binaries if _keep(e)]
a.datas = [e for e in a.datas if _keep(e)]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WingLightPDF_Core",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "assets", "app_icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="WingLightPDF_Core",
)
