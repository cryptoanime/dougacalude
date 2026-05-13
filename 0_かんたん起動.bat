@echo off
cd /d "%~dp0"

echo ========================================
echo Lecture Video Tool - Easy Start
echo ========================================
echo.

if not exist "app.py" (
  echo Required files were not found.
  echo Please extract the ZIP first, then run this BAT file again.
  pause
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found.
  echo Install Python 3.11 or later from Microsoft Store or python.org.
  echo During install, enable "Add python.exe to PATH".
  pause
  exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo FFmpeg was not found. Trying to install it with winget.
  winget install -e --id Gyan.FFmpeg
)

where pdftoppm >nul 2>nul
if errorlevel 1 (
  echo Poppler was not found. Trying to install it with winget.
  winget install -e --id oschwartz10612.Poppler
)

if not exist ".venv\Scripts\activate.bat" (
  echo Running first-time setup.
  python -m venv .venv
  call ".venv\Scripts\activate.bat"
  python -m pip install --upgrade pip
  pip install -r requirements.txt
) else (
  call ".venv\Scripts\activate.bat"
)

for /f "tokens=2 delims=:" %%A in ('ipconfig ^| findstr /R /C:"IPv4.*192\\." /C:"IPv4.*10\\." /C:"IPv4.*172\\."') do (
  set LAN_IP=%%A
  goto :found_ip
)
:found_ip
set LAN_IP=%LAN_IP: =%

if "%LAN_IP%"=="" (
  set LAN_IP=localhost
)

echo.
echo Open on this PC:
echo http://localhost:8501
echo.
echo Open on smartphone using the same Wi-Fi:
echo http://%LAN_IP%:8501
echo.
echo Smartphone PDF upload URL:
echo http://%LAN_IP%:8502
echo.

start "" /min python mobile_upload_server.py
start "" cmd /c "timeout /t 5 >nul && start http://localhost:8501"
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
pause
