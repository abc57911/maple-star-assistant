# 驗證流程

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## 日常修改

日常修改只執行：

```powershell
python tools\verify.py
```

此命令會完成：

- entrypoint `py_compile`
- `maple_star` compileall
- 精簡 smoke tests
- `git diff --check`

不需另外執行 `py_compile`、`compileall` 或個別 smoke test。

## 發行前

發行前執行完整測試：

```powershell
python tools\verify.py full
```

## PaddleOCR 專項

涉及 PaddleOCR runtime、fixture 準確率或 `.venv-paddleocr` 時執行：

```powershell
python tools\verify.py ocr-slow
```

日常不執行 `full` 或 `ocr-slow`；只在上述情境使用。

## Release artifact OCR

調整 PyInstaller、PaddleOCR / PaddleX 收集規則或 release dependencies 後，必須先打包，再直接驗證 ZIP 內 EXE：

```powershell
.\build_release.bat
python tools\verify_release_ocr.py release\MapleStar.zip
```

此 gate 不是 import smoke：它會先確認 mobile det/rec cache 的必要檔案完整，再解壓 ZIP、封鎖外部 provider endpoint/proxy、啟動 `MapleStar.exe`、初始化 production `PaddleExperienceTextReader`，並實際執行 Paddle predict。固定 fixture 預期為 `current_exp=3796880`、`percent=99.08`；cache 不完整時直接失敗，不在驗證期間下載。

重建 release venv 時使用 lock，不從日常 range requirements 重新 resolve：

```powershell
python -m venv .venv-release
.\.venv-release\Scripts\python.exe -m pip install -r requirements-release-lock.txt
```

## 筆電效能專項

完成 control runtime 或 GUI 架構變更後，在目標筆電執行：

```powershell
python tools\verify.py performance
```

此 profile 會：

- 冷啟動 GUI 三次並輸出中位數；若要驗證 30% 改善，可另用 `python tools\benchmark_gui_startup.py --baseline-seconds <舊版秒數>`。
- 量測五頁切換的可見回應；gate 為 p95 ≤150ms。第一次進入頁面會先呈現載入狀態，再於 event loop 空檔完成 lazy build。
- 啟動 production control runtime process，使用 fake capture 與 no-op input sink 同時跑手把巨集、小地圖判讀、週期鍵、正式 command/status queue 與 10ms benchmark deadline；預設只跑 10 秒，不會對 Windows 送鍵。gate 為 lateness p95 ≤10ms、最大值 ≤25ms。

短時間開發 smoke 可執行：

```powershell
python tools\benchmark_control_timing.py --duration 5
```

打包後的 EXE 冷啟動使用安全 ready-marker 模式，不會啟動 control/potion runtime。執行前先關閉既有 maple-star，並分別帶入舊版與新版 EXE 的中位數：

```powershell
python tools\benchmark_gui_startup.py --runs 3 --executable .\release\maple-star.exe
python tools\benchmark_gui_startup.py --runs 3 --executable .\release\maple-star.exe --baseline-seconds <舊版EXE秒數>
```

效能結果與硬體、電源模式及背景負載相關；正式數據需在相同筆電、相同 Windows 電源模式、相同 Python/EXE 類型下比較。若 gate 失敗，保留 JSON 輸出並先區分 OS scheduling、IPC saturation 或 control runtime 工作超時，不得直接放寬門檻。
