@echo off
cd /d "%~dp0"

echo ========================================
echo 講義動画生成ツール 初回セットアップ
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo Python が見つかりません。
  echo Microsoft Store または python.org から Python 3.11 以上をインストールしてください。
  echo インストール時は "Add python.exe to PATH" にチェックを入れてください。
  pause
  exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo FFmpeg が見つかりません。
  echo winget で FFmpeg のインストールを試します。
  winget install -e --id Gyan.FFmpeg
)

where pdftoppm >nul 2>nul
if errorlevel 1 (
  echo Poppler が見つかりません。
  echo winget で Poppler のインストールを試します。
  winget install -e --id oschwartz10612.Poppler
)

if not exist ".venv" (
  python -m venv .venv
)

call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo セットアップが完了しました。
echo 次回からは「2_起動.bat」を実行してください。
pause
