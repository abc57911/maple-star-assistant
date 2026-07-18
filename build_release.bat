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
    "%PYTHON_EXE%" -m pip install -r requirements-release-lock.txt
    if errorlevel 1 exit /b 1
)

"%PYTHON_EXE%" -c "import PySide6, PIL, pygame, mss, numpy, cv2, paddleocr, paddle, paddlex, imagesize, pyclipper, pypdfium2, bidi, shapely" >nul 2>nul
if errorlevel 1 (
    "%PYTHON_EXE%" -m pip install -r requirements-release-lock.txt
    if errorlevel 1 exit /b 1
)

"%PYTHON_EXE%" -c "import PySide6, PIL, pygame, mss, numpy, cv2, paddleocr, paddle, paddlex, imagesize, pyclipper, pypdfium2, bidi, shapely" >nul 2>nul
if errorlevel 1 (
    echo Error: release dependencies are incomplete. Check .venv-paddleocr.
    exit /b 1
)

for /f "delims=" %%I in ('%PYTHON_EXE% -c "import paddle, pathlib; print(pathlib.Path(paddle.__file__).resolve().parent / 'libs' / 'mklml.dll')"') do set "PADDLE_MKLML_DLL=%%I"
if not defined PADDLE_MKLML_DLL exit /b 1
if not exist "%PADDLE_MKLML_DLL%" exit /b 1

for /f "delims=" %%I in ('%PYTHON_EXE% -c "import paddlex, pathlib; print(pathlib.Path(paddlex.__file__).resolve().parent / 'configs' / 'pipelines' / 'OCR.yaml')"') do set "PADDLEX_OCR_CONFIG=%%I"
if not defined PADDLEX_OCR_CONFIG exit /b 1
if not exist "%PADDLEX_OCR_CONFIG%" exit /b 1

"%PYTHON_EXE%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --windowed ^
    --onedir ^
    --name "%APP_NAME%" ^
    --hidden-import PIL.Image ^
    --hidden-import PySide6.QtCore ^
    --hidden-import PySide6.QtGui ^
    --hidden-import PySide6.QtWidgets ^
    --hidden-import paddleocr ^
    --hidden-import paddle ^
    --hidden-import paddlex ^
    --hidden-import imagesize ^
    --exclude-module Crypto ^
    --exclude-module hf_xet ^
    --exclude-module tkinter ^
    --exclude-module _tkinter ^
    --copy-metadata imagesize ^
    --copy-metadata opencv-contrib-python ^
    --copy-metadata pyclipper ^
    --copy-metadata pypdfium2 ^
    --copy-metadata python-bidi ^
    --copy-metadata shapely ^
    --add-binary "%PADDLE_MKLML_DLL%;paddle/libs" ^
    --add-data "%PADDLEX_OCR_CONFIG%;paddlex/configs/pipelines" ^
    --add-data "maple_star\assets;maple_star/assets" ^
    main.pyw
if errorlevel 1 exit /b 1

if not exist "%DIST_APP_DIR%" exit /b 1
dir /s /b "%DIST_APP_DIR%\qwindows.dll" >nul 2>nul
if errorlevel 1 (
    echo Error: qwindows.dll is missing from the Qt release artifact.
    exit /b 1
)
if exist "%DIST_APP_DIR%\_internal\cv2\opencv_videoio_ffmpeg4100_64.dll" del /Q "%DIST_APP_DIR%\_internal\cv2\opencv_videoio_ffmpeg4100_64.dll"
if exist "%DIST_APP_DIR%\_internal\cv2\opencv_videoio_ffmpeg4100_64.dll" exit /b 1
copy /Y RELEASE_README.txt "%DIST_APP_DIR%\README.txt" >nul

if not exist "%RELEASE_DIR%" mkdir "%RELEASE_DIR%"
if exist "%ZIP_PATH%" del "%ZIP_PATH%"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%DIST_APP_DIR%\*' -DestinationPath '%ZIP_PATH%' -Force"
if errorlevel 1 exit /b 1

echo Release package created: %ZIP_PATH%
