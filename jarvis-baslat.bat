@echo off
rem Jarvis (Windows 11): sunucuyu ve "Hey Jarvis" servisini arka planda baslatir, arayuzu acar.
rem Ilk calistirmada .venv kurar. Kapatmak icin: jarvis-durdur.bat
setlocal
cd /d "%~dp0"
if not exist "data" mkdir data
if not exist ".venv\Scripts\python.exe" (
  echo Ilk kurulum yapiliyor, 1-2 dakika surebilir...
  py -3 -m venv .venv || python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt
)
curl -sf -o nul --max-time 1 http://127.0.0.1:4700/boot
if errorlevel 1 (
  start "" /b ".venv\Scripts\pythonw.exe" -u server.py 1>>data\sunucu.log 2>&1
  timeout /t 3 /nobreak >nul
)
if not "%JARVIS_NO_DAEMON%"=="1" start "" /b ".venv\Scripts\pythonw.exe" -u daemon.py --tray 1>>data\daemon.log 2>&1
start "" http://127.0.0.1:4700/
