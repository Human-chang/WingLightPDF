@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal
set "ROOT=%~dp0"
set "PY=%ROOT%.venv\Scripts\python.exe"
rem 參數：full 或 lite 只打包一版；--no-pause 跑完不停下來（自動化用）
set "WHICH=all"
set "NOPAUSE="
for %%A in (%*) do (
  if /i "%%~A"=="--no-pause" (set "NOPAUSE=1") else set "WHICH=%%~A"
)

echo ========================================================
echo 正在打包 WingLightPDF 綠色免安裝版 (供無 Python 電腦直接解壓使用)
echo   完整版：WingLightPDF_綠色免安裝版         (OCR：RapidOCR PP-OCRv6)
echo   輕量版：WingLightPDF_綠色免安裝版_輕量版  (OCR：Windows 內建)
echo   只打包其中一版：打包綠色免安裝版.bat full  或  打包綠色免安裝版.bat lite
echo   跑完不停下來：加上 --no-pause
echo ========================================================

rem 使用專案內的乾淨打包環境 .venv，避免把全域 Python 的其他套件一起打包
if not exist "%PY%" (
  echo 第一次打包：建立打包專用環境 .venv ...
  python -m venv .venv || goto :fail
)
echo 確認打包環境套件...
"%PY%" -m pip install -q -r requirements.txt pyinstaller || goto :fail

echo 執行單元測試...
"%PY%" -m unittest discover -s tests -t . -q || goto :fail

rem 啟動器執行檔不放進原始碼庫，每次都用 Windows 內建的 C# 編譯器從 assets\launcher.cs 重新編譯（不到一秒）
echo 編譯原生啟動器 WingLightPDF.exe ...
"%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /target:winexe /win32icon:"assets\app_icon.ico" /out:"WingLightPDF.exe" /r:System.dll,System.Core.dll,System.Drawing.dll,System.Windows.Forms.dll "assets\launcher.cs" || goto :fail

if /i not "%WHICH%"=="lite" (
  call :build full "WingLightPDF_綠色免安裝版" || goto :fail
)
if /i not "%WHICH%"=="full" (
  call :build lite "WingLightPDF_綠色免安裝版_輕量版" || goto :fail
)

echo ========================================================
echo 打包完成！請直接將資料夾壓縮為 .zip 分享即可！
echo ========================================================
if not defined NOPAUSE pause
exit /b 0

:build
set "EDITION=%~1"
set "OUT=%~2"
echo.
echo -------- [%EDITION%] %OUT% --------
echo [%EDITION% 1/3] 編譯核心程式 (設定見 WingLightPDF_Core.spec)...
if exist "build_tmp" rmdir /s /q "build_tmp"
if exist "_dist_tmp" rmdir /s /q "_dist_tmp"
"%PY%" -m PyInstaller --noconfirm --clean --log-level WARN --distpath "_dist_tmp" --workpath "build_tmp" WingLightPDF_Core.spec -- --edition %EDITION% || exit /b 1

echo [%EDITION% 2/3] 執行打包成品自我測試 (不會顯示視窗)...
start "" /wait "_dist_tmp\WingLightPDF_Core\WingLightPDF_Core.exe" --self-test "%ROOT%build_tmp\selftest_result.json"
if errorlevel 1 (
  echo 自我測試失敗！詳細內容請看 build_tmp\selftest_result.json
  exit /b 1
)

echo [%EDITION% 3/3] 組裝 %OUT% ...
if exist "%OUT%" rmdir /s /q "%OUT%"
rem 自我測試剛結束時，防毒軟體可能短暫鎖住剛執行過的檔案，移動失敗就稍等重試
set /a TRIES=0
:move_retry
move "_dist_tmp\WingLightPDF_Core" "%OUT%" >nul 2>&1 && goto :moved
set /a TRIES+=1
if %TRIES% geq 15 (
  echo 無法移動 _dist_tmp\WingLightPDF_Core（可能被防毒軟體暫時鎖定），請稍後再執行一次。
  exit /b 1
)
ping -n 2 127.0.0.1 >nul
goto :move_retry
:moved
rmdir /s /q "_dist_tmp"
rmdir /s /q "build_tmp"

move /y "%OUT%\WingLightPDF_Core.exe" "%OUT%\WingLightPDF_Core.bin" >nul
copy /y "WingLightPDF.exe" "%OUT%\WingLightPDF.exe" >nul
copy /y "使用說明.txt" "%OUT%\使用說明.txt" >nul
copy /y "LICENSE" "%OUT%\LICENSE.txt" >nul

mkdir "%OUT%\assets" 2>nul
rem 連同 assets\icons 子資料夾一起複製
xcopy /e /i /y /q "assets" "%OUT%\assets\" >nul

mkdir "%OUT%\stamps" 2>nul
if exist "stamps\*.png" copy /y "stamps\*.png" "%OUT%\stamps\" >nul

mkdir "%OUT%\source_code\core" 2>nul
mkdir "%OUT%\source_code\ui" 2>nul
copy /y "main.py" "%OUT%\source_code\" >nul
copy /y "register_default.py" "%OUT%\source_code\" >nul
copy /y "WingLightPDF_Core.spec" "%OUT%\source_code\" >nul
copy /y "README.md" "%OUT%\source_code\" >nul
copy /y "LICENSE" "%OUT%\source_code\" >nul
copy /y "requirements.txt" "%OUT%\source_code\" >nul
copy /y "core\*.py" "%OUT%\source_code\core\" >nul
copy /y "ui\*.py" "%OUT%\source_code\ui\" >nul
exit /b 0

:fail
echo ========================================================
echo 打包失敗，請檢查上方錯誤訊息。
echo ========================================================
if not defined NOPAUSE pause
exit /b 1
