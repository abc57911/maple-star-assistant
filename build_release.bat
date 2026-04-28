@echo off
setlocal
cd /d "%~dp0"

set APP_NAME=MapleStar
set RELEASE_DIR=release
set DIST_APP_DIR=dist\%APP_NAME%
set ZIP_PATH=%RELEASE_DIR%\%APP_NAME%.zip

python -m py_compile main.py main.pyw maple_gamepad_macro.py auto_potion.py
if errorlevel 1 exit /b 1

python -m compileall -q maple_star
if errorlevel 1 exit /b 1

python -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    python -m pip install pyinstaller
    if errorlevel 1 exit /b 1
)

for /f "usebackq delims=" %%I in (`python -c "import customtkinter, pathlib; print(pathlib.Path(customtkinter.__file__).resolve().parent)"`) do set CUSTOMTKINTER_DIR=%%I
if not defined CUSTOMTKINTER_DIR exit /b 1
if not exist "%CUSTOMTKINTER_DIR%" exit /b 1

python -m PyInstaller --noconfirm --clean --windowed --onedir --name "%APP_NAME%" --add-data "%CUSTOMTKINTER_DIR%;customtkinter/" main.pyw
if errorlevel 1 exit /b 1

if not exist "%DIST_APP_DIR%" exit /b 1
copy /Y RELEASE_README.txt "%DIST_APP_DIR%\README.txt" >nul

if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"
if exist "%ZIP_PATH%" del "%ZIP_PATH%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%DIST_APP_DIR%\*' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 exit /b 1

echo Release package created: %ZIP_PATH%
