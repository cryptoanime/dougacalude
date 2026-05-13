@echo off
setlocal
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

netstat -ano | findstr ":8501" | findstr "LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo The app is already running. Opening browser.
  start http://localhost:8501
  pause
  exit /b 0
)

call :find_python
if "%PYTHON_EXE%"=="" (
  echo Python was not found. Trying to install Python with winget.
  winget install -e --id Python.Python.3.13
  call :find_python
)

if "%PYTHON_EXE%"=="" (
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

if not exist ".venv\Scripts\python.exe" (
  echo Running first-time setup.
  "%PYTHON_EXE%" -m venv .venv
)

set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
if not exist ".setup_done" (
  echo Installing required Python packages. This may take several minutes the first time.
  "%PYTHON_EXE%" -m pip install --upgrade pip
  "%PYTHON_EXE%" -m pip install -r requirements.txt
  echo setup complete > ".setup_done"
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

netstat -ano | findstr ":8502" | findstr "LISTENING" >nul 2>nul
if errorlevel 1 (
  start "" /min "%PYTHON_EXE%" mobile_upload_server.py
)
start "" cmd /c "timeout /t 8 >nul && start http://localhost:8501"
"%PYTHON_EXE%" -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
pause
exit /b

:find_python
set "PYTHON_EXE="
for /f "delims=" %%P in ('where python 2^>nul') do (
  set "PYTHON_EXE=%%P"
  exit /b
)
for /f "delims=" %%P in ('where py 2^>nul') do (
  set "PYTHON_EXE=%%P"
  exit /b
)
for %%P in (
  "%LocalAppData%\Programs\Python\Python313\python.exe"
  "%LocalAppData%\Programs\Python\Python312\python.exe"
  "%LocalAppData%\Programs\Python\Python311\python.exe"
  "%LocalAppData%\Programs\Python\Python310\python.exe"
) do (
  if exist "%%~P" (
    set "PYTHON_EXE=%%~P"
    exit /b
  )
)
exit /b
