@echo off
setlocal
cd /d "%~dp0"

set APP_NAME=MapleStar
set RELEASE_DIR=release
set DIST_APP_DIR=dist\%APP_NAME%
set ZIP_PATH=%RELEASE_DIR%\%APP_NAME%.zip

python -m py_compile main.py main.pyw maple_gamepad_macro.py auto_potion.py
if errorlevel 1 exit /b 1

python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    python -m pip install pyinstaller
    if errorlevel 1 exit /b 1
)

python -m PyInstaller --noconfirm --clean --windowed --onedir --name "%APP_NAME%" main.pyw
if errorlevel 1 exit /b 1

if not exist "%DIST_APP_DIR%" exit /b 1
python -c "from pathlib import Path; from auto_potion import AutoPotionSettings, save_settings; save_settings(AutoPotionSettings(), Path(r'%DIST_APP_DIR%\settings.json'))"
if errorlevel 1 exit /b 1
copy /Y RELEASE_README.txt "%DIST_APP_DIR%\README.txt" >nul

if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"
if exist "%ZIP_PATH%" del "%ZIP_PATH%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%DIST_APP_DIR%\*' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 exit /b 1

echo Release package created: %ZIP_PATH%
