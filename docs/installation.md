# 安裝與環境重建

> 知識庫索引：[docs/INDEX.md](INDEX.md)

本文件供 Windows 電腦上的開發者或 AI agent 從專案原始碼重建 MapleStar。安裝套件時，以根目錄的 `requirements.txt` 為唯一版本與來源真相；本文件負責說明系統前置、套件用途、執行順序、驗證與故障排除。

## 支援範圍

- 作業系統：Windows 10/11 x64。
- Python：CPython 3.11 x64，專案與 CI 的首選版本。
- Python 3.12、3.13 可依現有專案邊界嘗試，但首次移機應使用 3.11。
- Python 3.14 以上不支援目前的 `paddlepaddle==3.2.2`，也會被 `build_release.bat` 拒絕。
- PaddlePaddle：CPU 版；不需 CUDA、cuDNN 或獨立 GPU runtime。
- 建議可用空間：只執行原始碼至少保留 2 GB；若還要打包，至少保留 5 GB。
- 首次安裝套件與首次初始化 PaddleOCR 模型時需要網路。

本專案使用 Win32 API、GDI、MCI、Qt 與 SDL controller，不能把 Linux、WSL 或 macOS 當作等效執行環境。

## 外部依賴總表

### 電腦層級

| 項目 | 必要性 | 安裝來源或 winget ID | 用途 |
| --- | --- | --- | --- |
| CPython 3.11 x64 | 必要 | `Python.Python.3.11` | app、測試、venv 與打包執行環境。 |
| Git for Windows | 驗證必要 | `Git.Git` | `tools/verify.py` 會執行 `git diff --check`；單純啟動 app 不依賴 Git。 |
| Microsoft Visual C++ 2015-2022 Redistributable x64 | 建議安裝 | `Microsoft.VCRedist.2015+.x64` | PaddlePaddle、OpenCV、NumPy、pygame 等 Windows binary wheel 的 native runtime。 |
| MapleStory Worlds | 實際使用時必要 | 使用者另行安裝 | MapleStar 的目標應用程式，不是 Python 套件，也不由本專案安裝。 |

GUI 使用 PySide6；release artifact 明確排除 Tcl/Tk。

### 直接 Python 依賴

以下項目全部由 `requirements.txt` 安裝。不要把此表轉成另一組手動安裝命令。

| 套件 | requirements 約束 | import 名稱 | 專案用途 |
| --- | --- | --- | --- |
| `pygame-ce` | `>=2.5.0` | `pygame` | SDL2 controller 偵測、按鈕事件與 Joystick fallback。 |
| `PySide6` | `==6.11.1` | `PySide6` | Qt 主 GUI、QTimer、QThreadPool、widgets 與 qwindows platform plugin。 |
| `Pillow` | `>=10.0.0` | `PIL` | GUI 內的影像預覽與圖片轉換。 |
| `mss` | `>=10.0.0` | `mss` | Windows 螢幕與遊戲畫面擷取。 |
| `numpy` | `>=2.0.0,<2.4` | `numpy` | ROI、bar、minimap 與 OCR 影像陣列運算。 |
| `opencv-contrib-python` | `==4.10.0.84` | `cv2` | template matching、影像前處理、輪廓與 OCR 輔助。不可同環境混裝其他 OpenCV wheel。 |
| `paddlepaddle` | `==3.2.2` 且 Python `<3.14` | `paddle` | PaddleOCR 的 CPU inference engine。wheel 由 requirements 內的 Paddle CPU index 取得。 |
| `paddleocr` | `==3.5.0` | `paddleocr` | Pixel OCR 失敗時的繁體中文 PP-OCRv5 fallback。 |

`requirements.txt` 內的 Paddle CPU extra index 必須保留。不要自行改裝 `paddlepaddle-gpu`。

### 關鍵轉移依賴與工具

下列套件不應逐一手動安裝；`pip install -r requirements.txt` 會透過上表自動解析。之所以列出，是因為 runtime 或 PyInstaller metadata 會直接檢查它們。

| 套件 | 來源 | 用途 |
| --- | --- | --- |
| `paddlex` | `paddleocr` | PaddleOCR 3.x pipeline 與模型管理。 |
| `imagesize` | PaddleX OCR extras | PaddleX runtime 與打包 metadata。 |
| `pyclipper` | PaddleX OCR extras | OCR polygon 處理。 |
| `pypdfium2` | PaddleX OCR extras | PaddleX OCR extras；打包時需保留 metadata。 |
| `python-bidi` | PaddleX OCR extras | 雙向文字處理；import 名稱是 `bidi`。 |
| `shapely` | PaddleX OCR extras | OCR 幾何處理。 |
| `shiboken6`、`PySide6-Essentials`、`PySide6-Addons` | `PySide6` | Qt binding 與 runtime components。 |
| `PyInstaller` | 開發工具，未列入 requirements | 只有執行 `build_release.bat` 時需要；腳本缺少時會自動安裝。 |

截至 2026-07-14，使用 Python 3.11 依 `requirements.txt` 解出的其他轉移依賴名稱如下。這是盤點清單，不是鎖檔；版本與實際集合仍以新電腦安裝後的 pip resolver 為準。

```text
aistudio-sdk, annotated-doc, annotated-types, anyio, bce-python-sdk,
certifi, chardet, charset-normalizer, click, colorama, colorlog, crc32c,
filelock, fsspec, future, h11, hf-xet, httpcore, httpx, huggingface-hub,
idna, markdown-it-py, mdurl, modelscope, networkx, opt-einsum, pandas,
prettytable, protobuf, psutil, py-cpuinfo, pycryptodome, pydantic,
pydantic-core, Pygments, python-dateutil, PyYAML, requests, rich,
ruamel.yaml, safetensors, shellingham, six, tqdm, typer,
typing-extensions, typing-inspection, tzdata, ujson, urllib3, wcwidth
```

`pip`、`setuptools` 與 `wheel` 是環境建置工具，也應在安裝 requirements 前更新。

### 不需安裝

- AutoHotkey：此 app 是 Python 程式，資料夾名稱不代表 runtime 依賴 AutoHotkey。
- Tesseract 或其他 OCR executable：OCR 由專案內 Pixel OCR 與 PaddleOCR 完成。
- CUDA、cuDNN、TensorRT 或 GPU 版 PaddlePaddle：目前走 CPU runtime。
- Node.js、npm、Java、Docker、Visual Studio Build Tools。
- 獨立 SDL2：`pygame-ce` 的 Windows wheel 已包含所需 SDL runtime。
- `requests` 作為 MapleStar Telegram client：Telegram service 使用 Python 標準庫 `urllib`；環境中出現的 `requests` 是 Paddle stack 的轉移依賴。

## 複製專案到新電腦

### 必須保留

- `maple_star/`，尤其是 `maple_star/assets/` 與 `maple_star/models/`。
- `media/` 內的 MP3 音效。
- `docs/`、`tools/`、`tests/`。
- `requirements.txt`、`main.py`、`main.pyw`、`run_maple_star.bat`、`run_maple_star.vbs`。
- 若需打包，另保留 `build_release.bat` 與 `RELEASE_README.txt`。
- 若需執行專案驗證，保留 `.git/`；若沒有 `.git/`，`tools/verify.py` 的 `git diff --check` 無法執行。

### 不可直接沿用

- `.venv*/`：venv 內含舊電腦的 Python 路徑，跨電腦不具可攜性，必須重建。
- `.paddleocr/`、根目錄 `models/`、`%USERPROFILE%\.paddlex/`：模型與 cache 應在新電腦重新下載。
- `build/`、`dist/`、`release/`、`*.spec`：本機打包產物，不是原始碼安裝來源。
- `__pycache__/`、`*.pyc`、`debug.log*`、`experience_debug.log*`、`startup_error.log`、`telegram_reply.log*`。

根目錄的 `models/` 是 cache；`maple_star/models/` 是正式原始碼。AI agent 不得混淆或刪除後者。

### 本機設定與秘密

- `settings.json` 會在首次啟動時自動建立。新電腦建議先讓 app 產生新檔，避免沿用失效的視窗座標或硬體狀態。
- 若必須保留既有 profile，可在安裝完成後備份並複製 `settings.json`，再由 app 執行既有 migration。
- `secrets/telegram_bot.json` 是可選的 Telegram 設定，必須用安全方式另行搬移，不得提交 Git 或寫進本文。
- Telegram 不需額外 pip 套件，但需要 HTTPS 網路存取 `api.telegram.org`。

## AI agent 標準安裝流程

AI agent 應依序執行本節，不得跳過版本、路徑與驗證檢查。

### 1. 確認工作目錄與來源

在 64-bit PowerShell 中切到實際專案根目錄：

```powershell
Set-Location -LiteralPath 'C:\path\to\maple-star'
Get-Location
Test-Path -LiteralPath '.\requirements.txt'
Test-Path -LiteralPath '.\maple_star\assets'
Test-Path -LiteralPath '.\media'
```

三個 `Test-Path` 都必須回傳 `True`。路徑含空白時仍使用 `-LiteralPath`，不要自行拼接未加引號的 shell command。

### 2. 安裝電腦層級依賴

先檢查，不要重複安裝：

```powershell
py -0p
git --version
```

缺少項目時，使用 winget：

```powershell
winget install --exact --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements
winget install --exact --id Git.Git --accept-package-agreements --accept-source-agreements
winget install --exact --id Microsoft.VCRedist.2015+.x64 --accept-package-agreements --accept-source-agreements
```

若系統沒有 winget，從 Python、Git 與 Microsoft 官方網站安裝相同 x64 版本。Python installer 必須啟用 `pip` 與 `py launcher`。安裝後關閉並重開 PowerShell，再執行：

```powershell
py -3.11 --version
py -3.11 -c "import struct, sys; assert sys.platform == 'win32'; assert struct.calcsize('P') * 8 == 64; print(sys.version)"
git --version
```

### 3. 隔離搬移過來的 venv

若專案副本包含 `.venv-paddleocr`，不要執行其中的 Python。先把它改名保留，確認新環境可用後再清除：

```powershell
if (Test-Path -LiteralPath '.\.venv-paddleocr') {
    $backup = '.venv-paddleocr.copied-' + (Get-Date -Format 'yyyyMMddHHmmss')
    Move-Item -LiteralPath '.\.venv-paddleocr' -Destination $backup
}
```

不要遞迴移動或刪除專案根目錄，也不要觸碰 `maple_star\models`。

### 4. 建立專案 venv

不需啟用 venv；後續一律使用明確的 Python 路徑，可避開 PowerShell execution policy 與誤用全域 pip。

```powershell
py -3.11 -m venv .venv-paddleocr
$Python = (Resolve-Path -LiteralPath '.\.venv-paddleocr\Scripts\python.exe').Path
& $Python --version
& $Python -m pip install --upgrade pip setuptools wheel
```

版本必須顯示 Python 3.11.x。

### 5. 安裝全部 runtime 套件

```powershell
& $Python -m pip install -r .\requirements.txt
```

不要拆成多個 `pip install`，也不要移除 Paddle CPU extra index。若沒有明確的 release 打包要求，不要安裝 PyInstaller。

### 6. 驗證套件與 import

```powershell
& $Python -m pip check
& $Python -c "import PySide6, cv2, mss, numpy, paddle, paddleocr, paddlex, pygame, imagesize, pyclipper, pypdfium2, bidi, shapely; from importlib.metadata import version; from PIL import Image; print('IMPORT_OK'); print('Python', __import__('sys').version.split()[0]); print('Qt', version('PySide6')); print('NumPy', version('numpy')); print('OpenCV', version('opencv-contrib-python')); print('Paddle', version('paddlepaddle')); print('PaddleOCR', version('paddleocr'))"
```

成功條件：

- `pip check` 輸出 `No broken requirements found.`。
- import command 輸出 `IMPORT_OK`，且 exit code 為 0。
- `opencv-contrib-python` 必須是 `4.10.0.84`。
- PaddlePaddle 與 PaddleOCR 必須分別是 `3.2.2`、`3.5.0`。

### 7. 執行專案驗證

至少執行日常驗證：

```powershell
& $Python .\tools\verify.py
```

首次完整建置建議再執行：

```powershell
& $Python .\tools\verify.py full
& $Python .\tools\verify.py ocr-slow
```

`ocr-slow` 會固定使用 `.venv-paddleocr\Scripts\python.exe`，並再次執行 PaddleOCR 測試與 `pip check`。三個命令都必須 exit 0；失敗時先保留完整輸出，不要用跳過測試或改 requirements 掩蓋錯誤。

### 8. 初始化 PaddleOCR 模型

首次 OCR 初始化會下載 `PP-OCRv5_mobile_det` 與 `PP-OCRv5_mobile_rec`。在網路可用時執行一次：

```powershell
& $Python -c "from maple_star.models.experience import PaddleExperienceTextReader; reader=PaddleExperienceTextReader(); ok=reader._ensure_ocr(); print('PADDLEOCR_INIT_OK' if ok else reader.unavailable_reason); raise SystemExit(0 if ok else 1)"
```

模型通常會進入 `%USERPROFILE%\.paddlex`。這是可重建 cache，不要複製進 repo。成功條件是輸出 `PADDLEOCR_INIT_OK` 且 exit code 為 0。

### 9. 啟動 app

一般 GUI 啟動使用：

```powershell
.\run_maple_star.bat
```

或直接以無 console 的 interpreter 啟動：

```powershell
Start-Process -FilePath '.\.venv-paddleocr\Scripts\pythonw.exe' -ArgumentList '.\main.pyw' -WorkingDirectory (Get-Location).Path -WindowStyle Hidden
```

確認：

- MapleStar GUI 正常開啟，沒有額外黑色 console 視窗。
- 關閉後可在專案根目錄看到新建立的 `settings.json`。
- controller 功能需要 Windows 已辨識控制器；不需額外 Python driver。
- 送鍵、hook 或擷取被權限阻擋時，讓 MapleStar 與目標程式使用相同 Windows 權限層級；不要預設以系統管理員執行。

## 可選：release 打包環境

只有使用者明確要求打包或發佈時才執行：

```powershell
$Python = (Resolve-Path -LiteralPath '.\.venv-paddleocr\Scripts\python.exe').Path
& $Python -m pip install pyinstaller
& $Python -m PyInstaller --version
.\build_release.bat
```

`build_release.bat` 會優先使用 `.venv-paddleocr`、拒絕 Python 3.14+，並收集 PaddleOCR、PaddleX、PySide6 Qt plugin 與 OCR extras metadata，同時排除 Tcl/Tk。後續 ZIP 檢查與禁止提交項目依 [release.md](release.md) 執行。

## 常見失敗

### `py` 或 `python` 找不到

- 關閉並重開 PowerShell，重新執行 `py -0p`。
- 若仍找不到，修復 Python 3.11 安裝並啟用 Python Launcher。
- 不要改用 Microsoft Store 的不明版本 `python.exe` alias。

### `No module named PySide6`

- 確認使用專案 venv，重新執行 `& $Python -m pip install -r .\requirements.txt`。
- 不要用 pip 單獨安裝不相容的 Qt component 版本；PySide6、Essentials、Addons 與 shiboken6 必須一致。

### `No matching distribution found for paddlepaddle`

- 確認是 Windows x64、Python 3.11 x64。
- 確認安裝命令使用未修改的 `requirements.txt`，且 Paddle CPU extra index 可連線。
- 確認不是 Python 3.14。
- 不要用 `--no-deps` 或自行改裝 GPU wheel。

### `DLL load failed`、`WinError 126` 或 native import 失敗

- 安裝或修復 Microsoft Visual C++ 2015-2022 Redistributable x64。
- 確認 Python 與全部 wheels 都是 x64。
- 執行 `& $Python -m pip check`，再重跑 import smoke test。
- 若 venv 曾從舊電腦複製，隔離後完整重建。

### OpenCV 衝突

同一 venv 不得同時存在 `opencv-python`、`opencv-python-headless`、`opencv-contrib-python-headless` 與本專案指定的 `opencv-contrib-python`。若發現混裝，最穩定的修復是隔離整個 venv，依本文件重建，不要局部猜測卸載順序。

### PaddleOCR 顯示缺少 `ocr-core`

- 確認 `paddlex`、`imagesize`、`opencv-contrib-python`、`pyclipper`、`pypdfium2`、`python-bidi`、`shapely` 都能 import 或被 pip metadata 找到。
- 重新執行 `& $Python -m pip install -r .\requirements.txt`。
- 若只在打包成品失敗，檢查 `build_release.bat` 的 `--copy-metadata` 與 `--collect-all`，不要只看原始碼 venv。

### 首次 OCR 模型下載失敗

- 確認 HTTPS、DNS、proxy 與防火牆允許 Python 下載模型。
- 保留完整錯誤，不要提交下載到一半的 `.paddlex` cache。
- 網路恢復後重跑「初始化 PaddleOCR 模型」命令。

### GUI 沒有開啟

- 先讀根目錄 `startup_error.log`，再讀 `debug.log`。
- 用 venv 的 console Python 執行 `& $Python .\main.py` 取得完整 traceback。
- 不要先更換 GUI framework 或移除 PaddleOCR；先依 traceback 修正缺失環境。

## AI agent 完成回報

AI agent 完成安裝後，至少回報：

- Windows edition 與 x64 狀態。
- `py -3.11 --version` 與 venv Python 路徑。
- `pip check` 結果。
- import smoke、`tools/verify.py` 與 PaddleOCR 初始化的 exit code。
- 是否實際啟動 GUI。
- 未執行項目及原因，例如沒有使用者授權所以未打包。

安裝過程產生的 `.venv*/`、cache、logs、`settings.json`、`secrets/`、`build/`、`dist/`、`release/` 與 `*.spec` 都不得提交。未經使用者明確要求，AI agent 也不得 commit、打包、建立 tag 或發佈 release。
