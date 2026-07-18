# 發行流程

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## 發行邊界
- PR、branch push 或 commit 不會更新 GitHub Releases 的 `MapleStar.zip`；只有推送 `v*` tag 才會觸發 `.github/workflows/release.yml` 打包並上傳 ZIP。
- 只有使用者明確要求「打包」、「更新 release ZIP」或「發佈 release」時，才執行 `build_release.bat`、建立 tag 或更新 GitHub Release。
- 未經使用者明確要求，不要對未合併的 feature branch 建 release tag。
- release tag 使用 `vYYYY.MM.DD`；同日重發可用 `vYYYY.MM.DD.N`，不要覆蓋既有 tag，除非使用者明確要求修正同一 release。

## 發行前檢查
確認目前狀態：

```powershell
git status --short --branch
git log --oneline --decorate -5
```

release 前 staged/commit 範圍不得包含 `settings.json`、`.venv*/`、`.paddleocr/`、`models/`、`build/`、`dist/`、`release/`、`*.spec`、本機 DB 或模型 cache。

至少執行：

```powershell
python tools/verify.py full
git status --short
```

若本次變更涉及 PaddleOCR、PaddleX、PyInstaller、requirements 或經驗效率，另外執行：

```powershell
python tools/verify.py ocr-slow
```

## 本機打包
本機打包前確認 `build_release.bat` 仍會：
- 優先使用 `.venv-paddleocr\Scripts\python.exe`。
- 拒絕 Python 3.14+。
- 編譯檢查 `main.py`、`main.pyw`、`maple_gamepad_macro.py`、`auto_potion.py` 與 `maple_star` package。
- 以 `main.pyw` 作為 PyInstaller GUI 入口，產出無 console 視窗的主程式。
- 使用 `--windowed --onedir --name MapleStar`。
- 保留 PySide6 Qt platform plugin 與 PaddleOCR / Paddle / PaddleX hidden import；排除 `tkinter` / `_tkinter`，不要恢復無界 `collect-all`。
- 只具名加入 Paddle runtime 必要的 `mklml.dll` 與 PaddleX `OCR.yaml`。
- 排除未使用的 `Crypto`、`hf_xet`，並在壓縮前移除 OpenCV videoio FFmpeg DLL；本專案不支援 PDF、影音檔或替代 model hoster 的行為不得由此推論。
- 保留 PaddleX `ocr-core` 需要的 metadata：`imagesize`、`opencv-contrib-python`、`pyclipper`、`pypdfium2`、`python-bidi`、`shapely`。
- 以 `RELEASE_README.txt` 複製成 ZIP 內的 `README.txt`；若 runtime 行為改變，release 前必須同步檢查這份說明。

本機打包命令：

```powershell
.\build_release.bat
python tools\verify_release_ocr.py release\MapleStar.zip
```

打包後必須驗證：
- `release/MapleStar.zip` 存在。
- ZIP 根目錄含 `MapleStar.exe` 與 `README.txt`。
- ZIP 不含 `settings.json`、`MapleStar.spec`、`build/`、`dist/` 或 `release/`。
- 發行包不依賴預先存在的 `settings.json`。
- ZIP 內 `README.txt` 不應描述已移除的 GUI 功能，例如使用者可見的 EXP OCR learning / 校正入口。
- 可從解壓後資料夾啟動 `MapleStar.exe`，並確認主 GUI 是 MapleStar 主程式，不是 debug 入口或 console 入口。
- 若調整 PaddleOCR、PaddleX、PyInstaller 或 requirements，打包後需用打包產物或等效 smoke test 驗證 `PaddleOCR(...)` 初始化成功；不能只檢查 ZIP 內是否有 `paddleocr` 目錄。
- `tools\verify_release_ocr.py` 會解壓 ZIP、在 warmed model cache 與 no-download 環境啟動 EXE，並要求 production Paddle predict 讀出固定 fixture 的 `3796880 / 99.08%`；timeout 為 120 秒。
- 可重現 release dependency lock 位於 `requirements-release-lock.txt`；`build_release.bat` 缺套件時也只從此 lock 安裝。更新 lock 後必須重跑 build、artifact smoke、full 與 ocr-slow。
- PyInstaller 可能列出 `lxml`、serving、TensorRT、GPU 或 doc parser 相關 warning；只要 `paddlex[ocr-core]` 依賴可用且 `PaddleOCR(...)` 初始化通過，這些選配 warning 不應視為 EXP OCR 發行阻斷。
- 本機打包後再次確認 `git status --short`。

`build/`、`dist/`、`release/` 與 `*.spec` 是打包產物，不應提交；若只是本機驗證產生，保留未追蹤或清理，不能混入 release commit。

## GitHub Releases ZIP 更新
1. 確認 release commit 已在 `main`，且 CI/本機驗證已通過。
2. 建立新 tag：

```powershell
git switch main
git pull --ff-only origin main
git tag vYYYY.MM.DD
git push origin vYYYY.MM.DD
```

3. 等待 GitHub Actions 的 `Release / Build and publish ZIP` 完成。
4. 確認該 release 的 `MapleStar.zip` asset 已更新，release notes 的 commit SHA 等於 tag 指向的 commit。
5. 下載 release asset，確認 ZIP 內含 `MapleStar.exe` 與 `README.txt`，並記錄 SHA256。

## GitHub Actions release 失敗
- 先看 `Run tests`、`Build release package`、`Verify release package` 或 `Publish GitHub Release` 哪一步失敗。
- 測試或打包失敗時修程式或 `build_release.bat`，再用新 commit 與新 tag 重發。
- 只有 release asset 上傳失敗且 commit/ZIP 已確認正確時，才可重跑 workflow 或用同 tag 補上 asset。
- 不要在未確認 ZIP 內容前手動上傳本機 ZIP 覆蓋 release。
