@echo off
rem Jarvis (Windows 11): bu klasorun .venv'i ile calisan server.py ve daemon.py sureclerini kapatir.
cd /d "%~dp0"
powershell -NoProfile -Command "$venv = Join-Path '%~dp0' '.venv\*'; Get-CimInstance Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { ($_.CommandLine -like '*server.py*' -or $_.CommandLine -like '*daemon.py*') -and $_.ExecutablePath -like $venv } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
if exist data\daemon.pid del data\daemon.pid
echo Jarvis kapatildi.
