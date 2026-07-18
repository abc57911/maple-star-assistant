# 全 App 最大效能實作計畫 4：PySide6 GUI 與 Production Cutover

> 知識庫索引：[../../INDEX.md](../../INDEX.md)  
> 設計：[全 App 最大效能架構重構](../specs/2026-07-18-full-app-performance-architecture-design.md)  
> 前置：[計畫 3：Input Guardian 與領域 Workers](2026-07-18-full-performance-plan-3-runtime-workers.md)

## 目標

以PySide6全面取代CustomTkinter，完成設定migration、單一入口、packaging、效能與soak gate。此計畫完成後repository與release不提供legacy GUI fallback。

## Entry gate

- Plan 3 Exit gate 全部通過。
- 新backend可由legacy GUI操作全部功能；混合負載與安全gate通過。
- Settings v2 mapping、public facade manifest與Qt功能parity matrix已凍結。
- 開始前記錄legacy Python GUI baseline；EXE baseline依打包授權取得。

## 批次 1：Qt application lifecycle 與 transport threads

### 檔案

- 新增 `maple_star/app/application.py`、`launcher.py`、`composition.py`、`resource_paths.py`。
- 新增 `maple_star/views_qt/__init__.py`、`main_window.py`、`theme.py`、`backend_threads.py`、`bindings.py`。
- 新增 `tests/test_qt_application.py`、`tests/test_qt_backend_threads.py`、`tests/test_qt_import_isolation.py`。
- 更新 `requirements.txt`；pin需先在開發與release環境驗證。

### 步驟

1. 使用`QT_QPA_PLATFORM=offscreen`建立QApplication lifecycle tests。
2. GUI main thread只操作widget；sender/receiver QThreads經bounded local mailbox與queued signals通訊。
3. Close先關pipe喚醒threads，再有界join；不得使用`QThread.terminate()`。
4. 建立shell、固定側邊導航、QStackedWidget、global status與error surface。
5. Child role import不得建立QApplication；GUI process不得importPaddle或guardian mutation adapter。

### 驗證

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest tests.test_qt_application tests.test_qt_backend_threads tests.test_qt_import_isolation
Remove-Item Env:QT_QPA_PLATFORM
```

## 批次 2：Dashboard、自動喝水與自動巡航

### 檔案

- 新增 `views_qt/pages/dashboard.py`、`potion.py`、`cruise.py`。
- 新增 `views_qt/models/runtime_models.py`、`preview.py`、`notices.py`。
- 新增 `tests/test_qt_dashboard.py`、`tests/test_qt_potion_page.py`、`tests/test_qt_cruise_page.py`。

### 步驟

1. Dashboard呈現全域啟停、target、worker health、HP/MP、EXP與最近動作。
2. Potion頁完成所有threshold/key/cooldown、HUD preview與具體failure reason。
3. Cruise頁完成boundary calibration、attack/skill、periodic keys、red-player與lie detector設定。
4. Widget programmatic sync使用`QSignalBlocker`；只有合法使用者輸入建立settings transaction。
5. Preview只處理最新frame id；QImage擁有自己的buffer。
6. Notice顯示前套用Windows toolwindow style，位置以target client為主並clamp。

### 驗證

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest tests.test_qt_dashboard tests.test_qt_potion_page tests.test_qt_cruise_page
Remove-Item Env:QT_QPA_PLATFORM
```

## 批次 3：手把組合、診斷與設定 migration UI

### 檔案

- 新增 `views_qt/pages/combo.py`、`diagnostics.py`。
- 新增 `views_qt/models/combo_model.py`、`periodic_key_model.py`、`console_model.py`。
- 更新 `models/settings_v2.py`、`settings_migrations.py` 與 `services/settings_store.py` 接production。
- 新增 `tests/test_qt_combo_page.py`、`tests/test_qt_diagnostics_page.py`、`tests/test_qt_settings_binding.py`。

### 步驟

1. Combo與periodic keys使用QAbstractTableModel/delegate，不建立數百個重複widget。
2. Console使用QPlainTextEdit、maximumBlockCount與bounded batch flush。
3. 診斷頁顯示PID/incarnation、heartbeat/progress age、queue depth、IPC/capture/OCR timing與dropped count。
4. 首次Qt production啟動自動執行settings v2 migration；失敗時保留原檔、停用automation並顯示可複製錯誤。
5. Profile切換用單一transaction；global/profile ownership依Plan 1 mapping。

### 驗證

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m unittest tests.test_qt_combo_page tests.test_qt_diagnostics_page tests.test_qt_settings_binding tests.test_settings_v2_migrations
Remove-Item Env:QT_QPA_PLATFORM
```

## 批次 4：功能 parity、唯一入口與移除 Tk

### 檔案

- 更新 `main.py`、`main.pyw`、`maple_star/gui.py`、`auto_potion.py`、`maple_gamepad_macro.py`。
- 更新public facade manifests與entrypoint tests。
- 刪除 `maple_star/views/` 中已無consumer的CustomTkinter modules與tests；精確清單由`rg`與manifest決定。
- 從`requirements.txt`移除`customtkinter`。
- 更新 `tests/test_public_facades.py`、`test_startup_error_handling.py`，新增 `tests/test_qt_function_parity.py`。

### 步驟

1. 逐項完成五頁parity matrix：設定、key capture、notice、preview、profile、console、close。
2. `main.py`／`main.pyw`只啟動Qt launcher；不提供`--legacy-gui`。
3. `maple_star.gui.AutoPotionSettingsGui`相容export指向Qt class；不得洩漏Tk contract。
4. 以`rg`確認controller/backend不讀`.root`、`after()`、`mainloop()`、`pump()`或Tk variable。
5. 只有parity與direct tests通過後才刪CustomTkinter files/dependency；同一批保留可由版本控制rollback的清楚邊界。

### 驗證

```powershell
python -m unittest tests.test_qt_function_parity tests.test_public_facades tests.test_startup_error_handling
python -m unittest tests.test_full_backend_integration tests.test_runtime_cleanup
```

## 批次 5：真實 GUI、DPI 與效能 gate

### 檔案

- 更新 `tools/benchmark_gui_startup.py`、`benchmark_gui_latency.py`、`benchmark_runtime_pipeline.py`。
- 新增 `tools/verify_qt_gui_smoke.py`、`tools/run_full_performance_soak.py`。
- 新增 `docs/reviews/2026-07-18-full-performance-final.md` 與精簡 raw JSON artifacts。

### 步驟

1. 真實Windows GUI驗證100/125/150/175% DPI、resize、中文輸入、五頁、notice、close與無殘留process。
2. Python fresh-process至少七次：first visible shell median `<= 200 ms`、main ready median `<= 700 ms`。
3. 預載後切頁與一般操作各100 samples：p95 `<= 16 ms`、max `<= 50 ms`。
4. 執行十分鐘混合負載；scheduler lateness p99 `<= 5 ms`、release零遺失。
5. 執行60分鐘soak；每十分鐘失焦/回焦、每十五分鐘settings generation切換、第三十分鐘延遲potion heartbeat。
6. 保存PID、incarnation、queue、heartbeat/progress、ownership、event-loop stall、CPU與working set。

### 驗證

```powershell
python tools\verify_qt_gui_smoke.py
python tools\benchmark_gui_startup.py --runs 7
python tools\benchmark_gui_latency.py
python tools\benchmark_runtime_pipeline.py --duration 600
python tools\run_full_performance_soak.py --duration 3600
```

## 批次 6：Packaging 與筆電 smoke

### 前置授權

依專案規範，執行打包、`python tools\verify.py full` 或release artifact驗證前，必須取得使用者當次明確同意。未取得授權時，只完成packaging規則與測試，不宣稱EXE gate通過。

### 檔案

- 更新 `requirements-release-lock.txt`、`build_release.bat`、`.github/workflows/release.yml` 與release docs。
- 新增/更新Qt plugin、resource與child-role artifact smoke。
- 更新 `docs/installation.md`、`runtime-compatibility.md`、`verification.md`、`release.md`、`project-structure.md`；必要時更新`AGENTS.md`。

### 步驟

1. Pin PySide6，驗證qwindows plugin、resources、multiprocessing freeze support與child role lazy import。
2. 建立onedir release artifact；EXE markers不得高於legacy EXE baseline的110%。
3. EXE close後不得殘留MapleStar process或preview transport resource。
4. 筆電執行全部頁面、巡航+喝水、失焦/停止/關閉smoke。
5. 筆電不得出現potion watchdog誤重啟、GUI freeze、殘留按鍵或process。

### 需授權的驗證

```powershell
python tools\verify.py full
.\build_release.bat
python tools\verify_release_ocr.py release\MapleStar.zip
python tools\verify_qt_gui_smoke.py --executable .\release\MapleStar.exe
```

## Exit gate

- PySide6是唯一GUI；repository與artifact不含CustomTkinter runtime。
- 五頁parity與settings migration全部通過。
- GUI close必定停止backend、guardian release並結束全部workers。
- Python效能、混合負載與60分鐘soak gate通過。
- 取得打包授權後，EXE與release OCR gate通過。
- 筆電smoke沒有watchdog誤判、GUI freeze、輸入或process殘留。

## Rollback

- Release前回到Plan 3最後通過commit；不在同一EXE保留legacy backend。
- Release後使用上一版artifact，並保留settings migration backup。
- 若Qt cutover已寫入settings v2，rollback reader必須能讀v2或先以已驗證工具從backup復原；不得手動覆蓋唯一設定檔。
