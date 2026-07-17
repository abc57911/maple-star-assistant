# 階段 2B：Release Package Slimming 實作計畫

> Baseline：[階段 2A Release Package Baseline](2026-07-17-release-package-baseline-plan.md)

## 目的

以 artifact-side 真實 Paddle predict 作為硬 gate，移除 `collect-all` 帶入的非 EXP OCR 模組。Baseline ZIP 為 244,516,678 bytes；15% 目標上限為 207,839,176 bytes。

## 修改檔案

- `main.pyw`：在正常 GUI startup 前辨識只由環境變數啟用的 release OCR smoke；正常啟動路徑不變。
- 新增 `maple_star/release_ocr_smoke.py`：載入 production `PaddleExperienceTextReader`，直接執行 `_read_with_paddle()`，寫出 JSON marker。
- 新增 `tools/verify_release_ocr.py`：解壓 ZIP、以 warmed cache/no-download 環境啟動 EXE、120 秒 timeout、驗證 marker 與 expected reading。
- 新增 `tests/test_release_ocr_smoke.py`：marker、failure、environment trigger 與 tool result validation tests，不啟動真 Paddle。
- `build_release.bat`：逐批移除 `--collect-all paddle`，再移除 `--collect-all paddleocr`／`paddlex`；保留 hidden imports 與已確認 metadata。
- `requirements-release-lock.txt`：記錄本 baseline Windows/Python 3.11 release environment 的完整 pinned dependency snapshot。
- `docs/verification.md`、`docs/release.md`：加入 artifact smoke、baseline comparison、no-download 與 rollback 命令。
- `docs/reviews/2026-07-17-project-code-review.md`：記錄每批 ZIP、hash、smoke 與最終縮減率。

## Smoke contract

- Trigger：`MAPLE_STAR_RELEASE_OCR_SMOKE_IMAGE` 是 fixture 絕對路徑；`MAPLE_STAR_RELEASE_OCR_SMOKE_OUTPUT` 是 JSON marker 路徑。缺任一變數即走正常 GUI。
- 固定 fixture：`tests/fixtures/experience_ocr/live_20260502_010734_001.png`。
- Production path：建立 `PaddleExperienceTextReader`，呼叫 `_ensure_ocr()`，再對 `ExperienceOcrImage` 呼叫 `_read_with_paddle()`；不得由 Pixel primary 滿足。
- Expected：`current_exp=3796880`、`percent=99.08`。
- Marker 至少包含 `backend="paddle"`、`paddle_predict_executed=true`、initialization、reading、elapsed_seconds、success、traceback。
- Predict 呼叫返回後才可設定 `paddle_predict_executed=true`；初始化或 predict exception 需寫 failure marker 並讓 EXE 非零退出。
- Tool 設定 Paddle/ModelScope/HuggingFace offline/no-download 環境，沿用 warmed cache；timeout 120 秒。

## Exclusion batches

1. Smoke batch：collect 規則不變，先證明 baseline artifact 能完成真 Paddle predict。
2. Paddle batch：只移除 `--collect-all paddle`；保留其他 collect-all、hidden imports、metadata。重新 build、內容 gate、artifact smoke。
3. PaddleOCR/PaddleX batch：移除其 `collect-all`，先依 PyInstaller dependency graph 自然收集；缺少 data/submodule 時只新增具名 `--collect-submodules`／`--collect-data` 或 project hook，不回復無界 collect-all。
4. Lock batch：以通過 artifact smoke 的同一 venv 產生 release lock；不改日常 `requirements.txt` 的直接 dependency truth。

## Public、資料與 ownership

- settings、IPC、public facade、正常 GUI 行為不變。
- Smoke module 只在兩個環境變數同時存在時執行；不建立 controller、GUI、SendInput、runtime process 或設定檔。
- Tool 擁有 temp extraction directory 與 child EXE；timeout 時終止 child，保留 marker/startup log 證據後清理 temp。
- Model cache 不打包、不下載、不刪除；fixture 由 repository 路徑傳入，不加入 ZIP。

## 驗證與 rollback

- 每批：targeted smoke tests、`python tools\verify.py full`、`python tools\verify.py ocr-slow`、build、ZIP content gate、`python tools\verify_release_ocr.py release\MapleStar.zip`、`git diff --check`。
- 任一 batch 若 build、初始化、predict、expected reading、timeout 或 marker gate 失敗，只撤回該 batch collect change。
- 逐批保留 ZIP bytes/hash；達到至少 15% 才算 package target 完成，否則記錄安全最佳結果與剩餘 top-size bottleneck。
- 不 commit、不 tag、不 push、不上傳 release。

## 執行結果

- Baseline artifact smoke 通過：244,517,798 bytes，production Paddle predict 為 `3796880 / 99.08%`。
- 移除 `collect-all paddle` 後缺少 `mklml.dll`；改為只具名加入該 DLL，smoke 通過。
- 移除 `collect-all paddlex` 後缺少 OCR pipeline；改為只具名加入 `paddlex/configs/pipelines/OCR.yaml`，smoke 通過。
- 移除 `collect-all paddleocr` 後 smoke 通過。
- 排除 `pypdfium2` 或 `shapely` 會讓 PaddleOCR 在初始化前直接 import 失敗，已回退。
- 最終排除 `Crypto`、`hf_xet` 與 OpenCV videoio FFmpeg DLL；artifact smoke 通過。
- 最終 ZIP：212,265,463 bytes，SHA256 `3F3434C4079FE973431AAFBE213CEFDC7039736796D55AF9AE8D9D0CF977B144`，較正式 baseline 244,516,678 bytes 減少 32,251,215 bytes（13.19%）。
- 15% 目標未達。安全差額受限於 PaddleOCR 3.5 / PaddleX 3.5.1 啟動期硬 import 的 pandas、pypdfium2、Shapely 與全 pipeline initializer；不以第三方 stub 或 vendored patch 換取剩餘約 4.4 MB。
