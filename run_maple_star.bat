@echo off
setlocal
cd /d "%~dp0"
set "PYTHONW=%~dp0.venv-paddleocr\Scripts\pythonw.exe"
if not exist "%PYTHONW%" set "PYTHONW=pythonw"
start "" "%PYTHONW%" "%~dp0main.pyw"
