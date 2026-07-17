# 專案結構

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## 入口與 facade
- `main.pyw`：無 console 視窗的 GUI 入口，發行版本主要使用此入口。
- `main.py`：一般 Python 入口，負責單例鎖、DPI awareness、啟動 logging，適合本機除錯。
- `auto_potion.py`：相容用 facade，對外匯出自動喝水相關 API。
- `maple_gamepad_macro.py`：相容用 facade，可直接執行，也對外保留手把巨集相關 API。
- `maple_star/controller.py`、`maple_star/experience.py`、`maple_star/gui.py`、`maple_star/settings.py`、`maple_star/win_input.py` 等舊路徑是相容 facade / module alias，不應再放新實作。
- `maple_star/__init__.py` 只匯出最常用相容 API；新增核心 API 時需同步確認 `auto_potion.py` 是否也要 re-export。

## package 分層
- `maple_star/`：主 package，採 MVC + services/adapters 結構。
- `maple_star/models/`：資料模型、設定模型、經驗效率模型、controller runtime state dataclass。
- `maple_star/views/`：GUI 與 console writer，包含 CustomTkinter view、theme 與 layout。
- `maple_star/controllers/`：主流程 orchestration，例如自動喝水 controller 與手把主 loop controller。
- `maple_star/services/`：純服務邏輯，例如 bar detection、settings store、hotkey worker、gamepad binding。
- `maple_star/adapters/`：外部系統邊界，例如 Win32 input/window API、SendInput helper、debug logging、pygame controller worker。
- `maple_star/constants.py`：跨模組共用常數，包含偵測節奏、狀態條定位、快捷鍵 ID 與 loading/fade guard。

## 主要模組職責
- `maple_star/controllers/auto_potion_controller.py`：自動喝水主流程、HUD/ROI 定位、HP/MP direct bar capture、EXP tooltip/bottom OCR orchestration、hotkey gating 與 cleanup。
- `maple_star/controllers/gamepad_controller.py`：GUI orchestration、control runtime entrypoint、RB/LB 巨集 state machine 與 runtime info refresh；實際 deadline 在 control process 執行。
- `maple_star/models/settings.py`：`settings.json` schema、profile migration、controller button alias、全域 UI 狀態與 profile-scoped potion/macro 設定。
- `maple_star/models/experience.py`：經驗效率 tracker、Pixel OCR、PaddleOCR fallback、tooltip/stat-window parser、OCR continuity guard 與 learning pending bundle helper。
- `maple_star/models/experience_pixel_templates.py`：runtime Pixel OCR template；檔案很大，應只由 `tools/experience_ocr_learning.py regen-templates` 或等效流程重建。
- `maple_star/models/controller_state.py`：controller 間共享的 dataclass，例如 HUD layout、OCR job/burst、potion effect attempt 與 out-of-potion hold。
- `maple_star/views/settings_gui.py`：CustomTkinter GUI、設定檔 UI、compact experience mode、toggle notice、console trim、狀態文字更新。
- `maple_star/services/runtime_processes.py`：potion、EXP 與 control runtime 的 multiprocessing coordinator、command/status dataclass、bounded queue、status signature 與 heartbeat。
- `maple_star/services/control_scheduler.py`：control runtime 的絕對 deadline、無 backlog cadence、高解析等待與 lateness 統計。
- `maple_star/services/potion_action_worker.py`：背景送鍵 worker；key-up 成功後才清除 held state，例外只記錄並保留可重試狀態。
- `maple_star/services/control_hotkey_worker.py`：全域控制熱鍵 worker；RegisterHotKey 失敗時仍保留 polling fallback。
- `maple_star/services/gamepad_bindings.py`：設定中的 controller button 名稱轉成 SDL button，並決定目前啟用的 RB/LB binding。
- `maple_star/services/experience_ocr_learning.py`：pending learning case 檢視、保守 promote、dedupe、fixture validation 與 template regeneration。
- `maple_star/services/bar_detection.py`：bar percent 正規化、threshold 判斷、loading 畫面指標與 preview PPM 轉換。
- `maple_star/adapters/win_input.py`：Win32 input/window/cursor/GDI ctypes 邊界、physical mouse observer、mouse lock、SendInput 與 window helpers。
- `maple_star/adapters/controller_worker.py`：pygame-ce / SDL controller 子程序事件來源，含 Joystick fallback。
- `maple_star/adapters/debug_logging.py`：`debug.log` 與 `experience_debug.log` rotating log、Tk/thread exception hook、JSONL experience debug event。
- `maple_star/adapters/window_target.py`：目標視窗判斷，應以 process executable name 為主。
- `maple_star/adapters/window_style.py`：輔助視窗 toolwindow/appwindow style，避免 toggle notice 顯示在工作列或 Alt-Tab。
- `maple_star/adapters/key_capture.py`：GUI key capture、detectable VK 與顯示名稱。

## Runtime 流程
- 主 GUI process 由 `gamepad_controller.main()` 驅動，建立 `AutoPotionSettingsGui`、`AutoPotionController` 與 SDL event worker。
- 預設啟用 `RuntimeProcessCoordinator`，分別管理 potion、experience 與 control child process；GUI 端只送 command、套用去重後的 status，不執行巨集或巡航 deadline。
- control runtime 消費 SDL event queue，負責手把組合、小地圖巡航、週期鍵與對應 SendInput；自動喝水送鍵仍由 potion runtime 擁有。
- potion runtime 使用 headless GUI recorder 執行自動喝水流程；experience runtime 使用 `experience_only_runtime=True`，只在 EXP 工作需要 HUD 時刷新 HUD，避免不必要的 HP/MP 擷取。
- runtime status 以 signature 去重，notice / urgent events / console lines 視為 urgent；即使狀態不變，也會用 heartbeat 維持 worker 存活可觀測性。
- GUI 端套用 runtime status 前也會比對 signature，避免重複 `StringVar.set()` 造成不必要 repaint。

## 專案資料
- `maple_star/assets/`：HUD label template，打包時需透過 `build_release.bat --add-data` 放進 package。
- `tests/fixtures/experience_ocr/`：OCR regression fixture 與 `manifest.json`；只有經驗 OCR fixture validation 需要依賴，不應作為 runtime template 來源。
- `media/`：自動喝水與拾取切換音效，controller 以 MCI alias 預載與重用。
- `tools/verify.py`：日常與慢速 OCR 驗證 profile 入口。
- `tools/experience_ocr_learning.py`：開發者離線維護 OCR pending case / fixture / Pixel template 的 CLI。

## 打包入口
- `build_release.bat`：PyInstaller 打包流程。
- 發行包以 `main.pyw` 作為 GUI 入口，避免 console 視窗。
