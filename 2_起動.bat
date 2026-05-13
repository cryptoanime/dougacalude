@echo off
cd /d "%~dp0"

echo ========================================
echo 講義動画生成ツール 起動
echo ========================================
echo.

if exist ".venv\Scripts\activate.bat" (
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

echo PCで開くURL:
echo http://localhost:8501
echo.
echo 同じWi-Fiのスマホで開くURL:
echo http://%LAN_IP%:8501
echo.
echo スマホからPDFを送る専用URL:
echo http://%LAN_IP%:8502
echo.

start "" /min python mobile_upload_server.py
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
pause
