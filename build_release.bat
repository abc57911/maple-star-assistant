@echo off
setlocal
cd /d "%~dp0"

set "APP_NAME=MapleStar"
set "RELEASE_DIR=release"
set "DIST_APP_DIR=dist\%APP_NAME%"
set "ZIP_PATH=%RELEASE_DIR%\%APP_NAME%.zip"

set "PYTHON_EXE=python"
if exist ".venv-paddleocr\Scripts\python.exe" (
    set "PYTHON_EXE=.venv-paddleocr\Scripts\python.exe"
)

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info < (3, 14) else 1)" >nul 2>nul
if errorlevel 1 (
    echo Error: release build requires Python 3.11-3.13 with PaddleOCR dependencies.
    echo Create or repair .venv-paddleocr before packaging.
    exit /b 1
)

"%PYTHON_EXE%" -m py_compile main.py main.pyw maple_gamepad_macro.py auto_potion.py
if errorlevel 1 exit /b 1

"%PYTHON_EXE%" -m compileall -q maple_star
if errorlevel 1 exit /b 1

"%PYTHON_EXE%" -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    "%PYTHON_EXE%" -m pip install pyinstaller
    if errorlevel 1 exit /b 1
)

"%PYTHON_EXE%" -c "import customtkinter, PIL, pygame, mss, numpy, cv2, paddleocr, paddle, paddlex, imagesize, pyclipper, pypdfium2, bidi, shapely" >nul 2>nul
if errorlevel 1 (
    "%PYTHON_EXE%" -m pip install -r requirements.txt
    if errorlevel 1 exit /b 1
)

"%PYTHON_EXE%" -c "import customtkinter, PIL, pygame, mss, numpy, cv2, paddleocr, paddle, paddlex, imagesize, pyclipper, pypdfium2, bidi, shapely" >nul 2>nul
if errorlevel 1 (
    echo Error: release dependencies are incomplete. Check .venv-paddleocr.
    exit /b 1
)

for /f "delims=" %%I in ('%PYTHON_EXE% -c "import customtkinter, pathlib; print(pathlib.Path(customtkinter.__file__).resolve().parent)"') do set "CUSTOMTKINTER_DIR=%%I"
if not defined CUSTOMTKINTER_DIR exit /b 1
if not exist "%CUSTOMTKINTER_DIR%" exit /b 1

"%PYTHON_EXE%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --onedir ^
    --name "%APP_NAME%" ^
    --hidden-import PIL.Image ^
    --hidden-import paddleocr ^
    --hidden-import paddle ^
    --hidden-import paddlex ^
    --hidden-import imagesize ^
    --collect-all paddleocr ^
    --collect-all paddle ^
    --collect-all paddlex ^
    --copy-metadata imagesize ^
    --copy-metadata opencv-contrib-python ^
    --copy-metadata pyclipper ^
    --copy-metadata pypdfium2 ^
    --copy-metadata python-bidi ^
    --copy-metadata shapely ^
    --add-data "maple_star\assets;maple_star/assets" ^
    --add-data "%CUSTOMTKINTER_DIR%;customtkinter/" ^
    main.pyw
if errorlevel 1 exit /b 1

if not exist "%DIST_APP_DIR%" exit /b 1
copy /Y RELEASE_README.txt "%DIST_APP_DIR%\README.txt" >nul

if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"
if exist "%ZIP_PATH%" del "%ZIP_PATH%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%DIST_APP_DIR%\*' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 exit /b 1

echo Release package created: %ZIP_PATH%
