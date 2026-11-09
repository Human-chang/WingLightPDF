<div align="center">

<img src="assets/logo.png" alt="WingLightPDF Logo" width="148" />

# ⚡ WingLightPDF — 輕快免安裝PDF檢視與編輯工具
### WingLightPDF — Feather-Light Portable PDF Viewer & Precision Editor

**[🇹🇼 繁體中文說明](#-繁體中文介紹-traditional-chinese) ｜ [🇺🇸 English Documentation](#-english-documentation)**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-0078D6.svg)](#)
[![Privacy: 100% Offline](https://img.shields.io/badge/Privacy-100%25%20純本機離線%20%2F%20Offline-10b981.svg)](#)
[![Build: GitHub Actions](https://img.shields.io/badge/Release-GitHub%20Actions%20Automated-22c55e.svg)](../../actions)

</div>

---

## 🇹🇼 繁體中文介紹 (Traditional Chinese)

> **「為什麼只是想快速看個圖紙、抽換兩頁、蓋個章或截張清晰的圖，卻得忍受肥大緩慢的商業軟體，或冒著資安風險把機密公文上傳到來路不明的線上網站？」**

**WingLightPDF** 是一款專為**辦公室日常、工程圖紙審閱、公文與合約處理**打造的輕量級開源 PDF 工具。基於 `PySide6` 與 C 語言底層的 `PyMuPDF` 引擎開發，兼具**「如羽翼般輕盈秒開 (Wing-Light)」**與**「直覺強悍的頁面／標註／工程量測功能」**。

### 🌟 三大安心承諾

1. **📦 免安裝綠色版（Portable）：** 無須安裝 Python 或任何外部環境，從右側 **[Releases](../../releases)** 下載 `.zip` 解壓縮即可直接雙擊 `WingLightPDF.exe` 使用。
2. **🔒 100% 純本機離線運作：** 程式絕不連網、絕不將任何檔案上傳雲端。處理政府公文、地籍圖、工程設計圖紙與商業機密合約最安心。
3. **🛡️ 原始碼公開 & 官方雲端自動編譯：** 完整 Python 原始碼 100% 透明可查；Releases 發佈的 `.zip` 免安裝包皆由 **GitHub Actions 官方雲端伺服器**直接從公開原始碼自動編譯打包，杜絕人為加料與後門風險。

### 🚀 核心功能亮點

| 功能分類 | 實戰細節與解決痛點 |
| :--- | :--- |
| **⚡ 極速檢視與護眼模式** | • 毫秒級開啟大檔案、支援 `Ctrl+滾輪` 縮放、手型平移<br>• **深色反相護眼模式**：一鍵轉為黑底白線（類似 CAD 介面），長時間審閱工程圖紙與長文不傷眼 |
| **🗂️ 多PDF同視窗分頁 & 自由拖拉** | • **同視窗多分頁／多視窗雙棲**：可將多個 PDF 顯示於同一視窗分頁列，0 延遲切換<br>• **像 Chrome 一樣自由拆分與合併**：按住分頁往視窗外拉即可**拆成兩個獨立視窗**；把 A 視窗分頁拖進 B 視窗即可**無損合併為一個視窗** |
| **📄 彈性縮圖列與跨檔管理** | • 左側縮圖列支援**拉窄成單欄**或**拉寬自動多排並排網格**<br>• 支援 `Ctrl` / `Shift` 多頁滑鼠拖曳排序、**跨分頁／跨視窗互拖頁面插入**，或從檔案總管直接把外部 PDF 拖進縮圖列任意位置合併<br>• 一鍵旋轉、刪除、擷取頁面、多檔合併與拆分、批次頁碼與浮水印 |
| **✂️ 600 DPI 高解析截圖去背** | • 拒絕螢幕像素模糊截圖！直接從 PDF 底層向量以 **300~600 DPI** 重新渲染局部圖面，貼入 Word／簡報極致銳利<br>• 支援**「一鍵去背透明 PNG」**與**「去背 + 線條加深」**，貼上表格或有色背景不遮擋 |
| **💮 標註與常用圖章/簽名匣** | • 新增繁體中文文字（自動內嵌系統字型，存檔絕不變亂碼或空白框）、插入圖片<br>• 內建**「核准、已審閱、機密、今日日期章」**，並支援匯入簽名照片**自動白底去背**收藏於 `stamps\` 資料夾隨時取用 |
| **📐 工程圖紙比例尺量測** | • 支援**兩點比例尺校正**：在圖上已知長度線段點兩下即可完成校正<br>• 直接量測實際距離、多邊形面積，並自動完成 **平方公尺 ($m^2$) 與「台灣坪數」換算**！ |
| **🔍 雙檔案疊圖差異比對** | • **左右並排同步捲動縮放**：對照前後版文件不再眼花<br>• **紅藍疊圖差異高亮比對**：一秒抓出新版圖紙或合約偷偷修改、位移了哪裡 |
| **🧠 按需 OCR 文字辨識** | • 預設 `Ctrl+F` 毫秒級搜尋內嵌文字，**絕不在背景自動偷跑 OCR 拖慢電腦**<br>• 遇到掃描檔時，可手動點選「🔍 按需 OCR ▾」辨識局部區域、單頁或整份文件，並可將**可搜尋透明文字層永久寫入 PDF**！ |

### 📥 一般使用者下載與使用方式

1. 前往本頁面右側的 **[Releases（發行版本）](../../releases)** 專區，依需求下載其中一個版本（兩版功能相同，只差 OCR 引擎）：
   | 版本 | 下載大小 | OCR 引擎 | 適合 |
   |---|---|---|---|
   | `WingLightPDF_綠色免安裝版.zip`（完整版） | 約 135 MB | RapidOCR PP-OCRv6 | 常需辨識掃描的數字表格、工程規範 |
   | `WingLightPDF_綠色免安裝版_輕量版.zip` | 約 62 MB | Windows 內建 OCR | 一般公文與內文；密集數字表格容易漏字 |
2. 解壓縮至電腦任意位置，直接雙擊資料夾內的 **`WingLightPDF.exe`** 即可開啟程式。
3. **📌 設為電腦預設 PDF 軟體（選用）：**
   - 打開 `WingLightPDF.exe` 後，點擊右上角工具列的 **「📌 設為預設PDF」** 按鈕。
   - 對電腦裡任意一個 `.pdf` 檔案按右鍵 ➔「開啟檔案」➔「選擇其他應用程式」➔ 選取「**WingLightPDF — 輕快免安裝PDF檢視與編輯工具**」並點選 **「永遠 (Always)」**。

### 🛠️ 開發者指南（從原始碼執行）

```bash
# 1. 複製專案
git clone https://github.com/Human-chang/WingLightPDF.git
cd WingLightPDF

# 2. 安裝依賴套件
pip install -r requirements.txt

# 3. 啟動程式
python main.py
```

打包綠色免安裝版：直接執行 `打包綠色免安裝版.bat`。它會在專案內建立乾淨的打包環境 `.venv`，依 `WingLightPDF_Core.spec` 編譯，並在組裝前以 `--self-test` 自動驗證介面、PDF、印章與 OCR 是否正常。

---

## 🇺🇸 English Documentation

> **"Why tolerate bloated, sluggish commercial PDF suites—or risk uploading confidential contracts and engineering blueprints to unknown online tools—just to view a document, reorder a few pages, stamp a signature, or take a crisp high-DPI snapshot?"**

**WingLightPDF** is an ultra-fast, 100% offline, portable open-source PDF viewer and lightweight editor built for **daily office workflows, engineering blueprint review, and confidential document processing**. Powered by `PySide6` and the C-based `PyMuPDF` engine, it delivers **instant startup speed** alongside practical page manipulation, CAD-style measurement, and visual diff tools.

### 🌟 Three Core Guarantees

1. **📦 True Portable App:** No Python installation or admin rights required. Download the `.zip` archive from **[Releases](../../releases)**, extract anywhere, and run `WingLightPDF.exe`.
2. **🔒 100% Offline & Private:** Zero network requests, zero telemetry, and zero cloud uploads. Your confidential contracts, legal filings, and engineering drawings never leave your machine.
3. **🛡️ Auditable Source & Automated Cloud Builds:** Every portable release `.zip` is automatically compiled directly from public source code on clean **GitHub Actions** runners—ensuring complete transparency and safety.

### 🚀 Key Features

| Category | Capabilities |
| :--- | :--- |
| **⚡ Instant Viewing & Eye Care** | • Millisecond startup & rendering, smooth `Ctrl+Wheel` zoom, pan tool<br>• **CAD-Style Dark Invert Mode**: One-click dark background with crisp white lines to reduce eye strain during long blueprint or document reviews |
| **🗂️ Chrome-Style Multi-Tabs & Tear-Off Windows** | • **Multi-Tab Workspace**: Open multiple PDFs in tabs within a single window with zero-latency switching<br>• **Drag-Out to Split / Drag-In to Merge**: Drag any tab out of the tab bar to detach it into a separate window, or drag a tab from one window into another to merge them seamlessly |
| **📄 Responsive Thumbnail Grid & Page Dragging** | • Shrink the left thumbnail panel to a compact **single-column strip**, or widen it to automatically reflow into a **multi-column grid**<br>• Multi-page (`Ctrl` / `Shift`) drag-and-drop reordering, **cross-tab / cross-window page dragging**, and direct external `.pdf` file dropping<br>• Rotate, delete, extract pages, merge multiple PDFs, split documents, and batch-apply page numbers or watermarks |
| **✂️ 600 DPI Vector Re-Rendered Clipping & Auto-Cutout** | • Say goodbye to blurry screen captures: re-renders selected regions directly from PDF vector data at **300–600 DPI**<br>• One-click **Transparent Background PNG** and **Line Darkening/Enhancement** for crystal-clear pasting into Word or PowerPoint |
| **💮 Annotations & Stamp / Signature Box** | • Insert CJK/Unicode text (with automatic system font embedding so saved PDFs never show garbled characters) and images<br>• Built-in dynamic date & approval stamps, plus one-click **automatic white-background removal** for imported handwritten signatures |
| **📐 Engineering Scale Calibration & Measurement** | • **Two-Point Scale Calibration**: Click two points of known distance on a drawing to calibrate scale<br>• Measure real-world distances and polygon areas with automatic conversion between **square meters ($m^2$) and Ping (坪)** |
| **🔍 Dual-PDF Sync Scroll & Red/Blue Diff Overlay** | • **Side-by-Side Synchronized Pan & Zoom** for comparing document revisions<br>• **Red/Blue Pixel Diff Overlay** that immediately highlights subtle drawing shifts or text edits between two PDF versions |
| **🧠 On-Demand Offline OCR** | • Instant `Ctrl+F` native text search that **never runs background OCR without your permission**<br>• Manually trigger offline ONNX OCR (`rapidocr` with the bundled PP-OCRv6 model, native Traditional Chinese support) for a selected region, current page, or entire document—and optionally **embed an invisible searchable text layer** permanently into the PDF |

### 📥 Quick Start (For End Users)

1. Go to the **[Releases](../../releases)** section and download one edition (identical features, different OCR engine):
   - `WingLightPDF_綠色免安裝版.zip` — Full (~135 MB): bundled RapidOCR PP-OCRv6, accurate on Traditional Chinese and dense numeric tables.
   - `WingLightPDF_綠色免安裝版_輕量版.zip` — Lite (~62 MB): uses the built-in Windows OCR; fast and accurate on regular text, weaker on dense numeric tables.
2. Extract the folder anywhere on your Windows 10/11 PC and double-click **`WingLightPDF.exe`**.
3. **Set as Default PDF Viewer (Optional):** Click the **`📌 設為預設PDF`** button on the top toolbar, then right-click any `.pdf` file ➔ *Open with* ➔ *Choose another app* ➔ select **WingLightPDF** and click **Always**.

### 🛠️ Run from Source (For Developers)

```bash
# 1. Clone the repository
git clone https://github.com/Human-chang/WingLightPDF.git
cd WingLightPDF

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch WingLightPDF
python main.py
```

To build the portable edition, run `打包綠色免安裝版.bat`. It creates an isolated `.venv`, builds from `WingLightPDF_Core.spec`, and runs a headless `--self-test` (UI, PDF, stamps, OCR) before assembling the folder.

---

## 📄 License / 開源授權

Released under the **[MIT License](LICENSE)** — Copyright (c) 2026 **[Human-chang](https://github.com/Human-chang)**.
If **WingLightPDF** saves you time at work, please consider giving this repository a ⭐ **Star**!
