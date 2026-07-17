# 階段 2A：Release Package Baseline 計畫

> 設計規格：[全專案 Code Review 與減肥設計](../specs/2026-07-17-project-slimming-design.md)
>
> 前置階段：[Developer Tooling 與 Dead Code 移除](2026-07-17-developer-tooling-dead-code-removal-plan.md)

## 目的

在不修改現有 PyInstaller collect 規則的前提下，建立可重現的 baseline ZIP、analysis、內容與 dependency snapshot。Baseline 是後續 15% 縮減目標及逐批 rollback 的比較基準。

## 修改與產物路徑

- 新增本計畫並更新 `docs/INDEX.md`。
- 執行既有 `build_release.bat`；不修改腳本。
- 本機 ignored 產物：`build/MapleStar/`、`dist/MapleStar/`、`release/MapleStar.zip`、`MapleStar.spec`。
- 後續將 baseline 數據寫入 `docs/reviews/2026-07-17-project-code-review.md`；本批不新增 packaging hook、runtime hook 或 dependency lock。

## Public surface 與 ownership

- Python public/re-export、constructor、method、settings、IPC schema 全部不變。
- 不啟動 production GUI、control/potion process 或 Win32 input。
- PyInstaller process 只建立本機 build artifact；Paddle model cache 使用既有 warmed cache，不下載、不刪除、不提交。
- 不 commit、不 tag、不 push、不上傳 release。

## 執行步驟

1. 記錄 `.venv-paddleocr` Python、PyInstaller、Paddle、PaddleOCR、PaddleX、OpenCV 與 NumPy 版本。
2. 記錄目前 requirements hash、HEAD、工作樹與現有 `release/MapleStar.zip` 是否存在。
3. 執行未修改的 `build_release.bat`。
4. 記錄 ZIP bytes、SHA256、entry count、解壓後 bytes，以及 `dist/MapleStar/_internal` top-level 目錄／檔案體積。
5. 保存 PyInstaller `warn-MapleStar.txt`、`xref-MapleStar.html` 與 Analysis TOC 的位置；分析 Paddle/PaddleX 被收集的 top-level pipeline、training、serving、GPU/TensorRT、document parser 候選。
6. 驗證 ZIP 根目錄、禁止檔案與 `README.txt`；本 baseline 不以直接啟動 GUI 取代後續 artifact OCR smoke。
7. 根據 analysis 建立階段 2B exact-file 計畫，逐批列出 hook/collect/exclusion、artifact smoke、rollback 與 15% 比較方式。

## 驗證

- `python tools\verify.py full` 與 `python tools\verify.py ocr-slow` 沿用階段 1B 同一 implementation state 的 fresh 證據；若 baseline 過程改變 tracked file，必須重跑。
- `build_release.bat` exit 0。
- `release/MapleStar.zip` 存在，含 `MapleStar.exe`、`README.txt`，不含 `settings.json`、`MapleStar.spec`、`build/`、`dist/`、`release/`。
- ZIP SHA256、bytes、entry count 與解壓後 bytes 都有記錄。
- `git status --short` 不出現 build/dist/release/spec tracked change。

## Failure handling 與 rollback

- 打包失敗時保留 PyInstaller log、warn/xref/TOC；不安裝或移除額外 OCR dependency 來掩蓋 baseline 問題。
- 若 `build_release.bat` 嘗試下載 model，停止該 process並記錄；baseline 只使用既有 cache。
- 若產物包含禁止檔案，標記 baseline finding，不在 2A 順手改腳本。
- 本批 tracked rollback 只有 plan/index/report；build/dist/release/spec 都是 ignored 本機產物。

## 完成條件

- 未修改 collect 規則的 baseline ZIP 成功建立並量測。
- Analysis 足以將後續 exclusion 分成可獨立驗證的小批次。
- 階段 2B 計畫包含 exact files、artifact-side Paddle predict smoke、120 秒 timeout、warmed-cache/no-download 與逐批 rollback。

## 完成紀錄

- Baseline build exit 0；首次依既有腳本在本機 venv 安裝 PyInstaller 6.21.0。
- ZIP：244,516,678 bytes、6,838 entries、669,419,588 uncompressed bytes。
- SHA256：`CB7377EDD7B1D8788D14F470FB33055FB2EACB1B905B77A2552C790BCF40065E`。
- 內容 gate 通過：含 `MapleStar.exe`、`README.txt`，無 settings/spec/forbidden prefix。
- Top size 與 analysis 已寫入 code review report；build/dist/release/spec 均維持 ignored，未出現在 git status。
