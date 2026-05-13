$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

Write-Host "Lecture Video Tool - Easy Start"
Write-Host ""

if (-not (Test-Path -LiteralPath "app.py")) {
    Write-Host "Required files were not found."
    Write-Host "Please extract the ZIP first, then run START_HERE.ps1 again."
    Read-Host "Press Enter to exit"
    exit 1
}

$listening8501 = netstat -ano | Select-String ":8501" | Select-String "LISTENING"
if ($listening8501) {
    Write-Host "The app is already running. Opening browser."
    Start-Process "http://localhost:8501"
    Read-Host "Press Enter to exit"
    exit 0
}

function Find-Python {
    $candidates = @(
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
        (Get-Command py -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
        "$env:LocalAppData\Programs\Python\Python313\python.exe",
        "$env:LocalAppData\Programs\Python\Python312\python.exe",
        "$env:LocalAppData\Programs\Python\Python311\python.exe",
        "$env:LocalAppData\Programs\Python\Python310\python.exe"
    )
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate)) {
            return $candidate
        }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host "Python was not found. Trying to install Python with winget."
    winget install -e --id Python.Python.3.13
    $python = Find-Python
}

if (-not $python) {
    Write-Host "Python was not found."
    Write-Host "Install Python 3.11 or later from Microsoft Store or python.org."
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Host "FFmpeg was not found. Trying to install it with winget."
    winget install -e --id Gyan.FFmpeg
}

if (-not (Get-Command pdftoppm -ErrorAction SilentlyContinue)) {
    Write-Host "Poppler was not found. Trying to install it with winget."
    winget install -e --id oschwartz10612.Poppler
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    Write-Host "Running first-time setup."
    & $python -m venv .venv
}

$venvPython = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath ".setup_done")) {
    Write-Host "Installing required Python packages. This may take several minutes the first time."
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r requirements.txt
    "setup complete" | Set-Content -LiteralPath ".setup_done"
}

$lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -match '^(192\.168\.|10\.|172\.)' } |
    Select-Object -First 1 -ExpandProperty IPAddress)
if (-not $lanIp) { $lanIp = "localhost" }

Write-Host ""
Write-Host "Open on this PC:"
Write-Host "http://localhost:8501"
Write-Host ""
Write-Host "Open on smartphone using the same Wi-Fi:"
Write-Host "http://$lanIp`:8501"
Write-Host ""
Write-Host "Smartphone PDF upload URL:"
Write-Host "http://$lanIp`:8502"
Write-Host ""

$listening8502 = netstat -ano | Select-String ":8502" | Select-String "LISTENING"
if (-not $listening8502) {
    Start-Process -WindowStyle Minimized -FilePath $venvPython -ArgumentList "mobile_upload_server.py"
}

Start-Job -ScriptBlock {
    Start-Sleep -Seconds 8
    Start-Process "http://localhost:8501"
} | Out-Null

& $venvPython -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
Read-Host "Press Enter to exit"
