# 驗證流程

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## 預設原則：修改哪裡，測試哪裡

日常修改只執行受影響子系統的精準測試：

```powershell
python -m unittest tests.test_<affected_subsystem>
```

依下列規則選擇範圍：

- 修改單一函式或模組時，先跑最接近該行為的 test class、test method 或 test module。
- 修改跨模組介面、共用資料契約或 cleanup ownership 時，只補跑直接依賴該介面的契約或整合測試。
- 測試失敗時，先重跑失敗案例。只有證據顯示影響跨出目前邊界時，才擴到最近的相依模組。
- 程式狀態未改變時，不重跑已通過的測試。
- 純文件修改只檢查文件 diff、連結與格式，不執行 runtime 測試。

不要把 `python tools\verify.py`、全套測試或下列專項 profile 當作日常預設。

## 跨子系統快速驗證

只有使用者明確要求，或修改同時影響多個核心子系統時，才執行：

```powershell
python tools\verify.py
```

此命令包含 entrypoint `py_compile`、`maple_star` compileall、精簡 smoke tests 與 `git diff --check`。

## 發行前

只有使用者明確要求時，才執行完整測試：

```powershell
python tools\verify.py full
```

## PaddleOCR 專項

只有使用者明確要求 OCR 專項 gate 時，才執行：

```powershell
python tools\verify.py ocr-slow
```

日常不執行 `full` 或 `ocr-slow`。

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

只有使用者明確要求效能 gate 時，才在目標筆電執行：

```powershell
python tools\verify.py performance
```

此 profile 會：

- 冷啟動 GUI 三次並輸出中位數；若要驗證 30% 改善，可另用 `python tools\benchmark_gui_startup.py --baseline-seconds <舊版秒數>`。
- 量測五頁切換的可見回應；gate 為 p95 ≤150ms。第一次進入頁面會先呈現載入狀態，再於 event loop 空檔完成 lazy build。
- 啟動 production control runtime process，使用 fake capture 與 no-op input sink 同時跑手把巨集、小地圖判讀、週期鍵、正式 command/status queue 與 10ms benchmark deadline；預設只跑 10 秒，不會對 Windows 送鍵。gate 為 lateness p95 ≤10ms、p99 ≤5ms、最大值 ≤25ms。

短時間開發 smoke 可執行：

```powershell
python tools\benchmark_control_timing.py --duration 5
```

完整架構重構另有以下明確 gate：

```powershell
python tools\verify_child_role_artifact.py
python tools\verify_qt_gui_smoke.py
python tools\verify_qt_gui_smoke.py --all-scales
python tools\benchmark_runtime_pipeline.py --duration 600
python tools\run_full_performance_soak.py --duration 3600
```

soak 同時限制 scheduler lateness 與 child RSS growth；不得用縮短 duration 的結果取代 60 分鐘 gate。

打包後的 EXE 冷啟動使用安全 ready-marker 模式，不會啟動 control/potion runtime。執行前先關閉既有 maple-star，並分別帶入舊版與新版 EXE 的中位數：

```powershell
python tools\benchmark_gui_startup.py --runs 3 --executable .\release\maple-star.exe
python tools\benchmark_gui_startup.py --runs 3 --executable .\release\maple-star.exe --baseline-seconds <舊版EXE秒數>
```

效能結果與硬體、電源模式及背景負載相關；正式數據需在相同筆電、相同 Windows 電源模式、相同 Python/EXE 類型下比較。若 gate 失敗，保留 JSON 輸出並先區分 OS scheduling、IPC saturation 或 control runtime 工作超時，不得直接放寬門檻。
