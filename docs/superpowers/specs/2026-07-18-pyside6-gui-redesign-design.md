# PySide6 GUI 重設計

> 知識庫索引：[../../INDEX.md](../../INDEX.md)

## 背景

現有 GUI 使用 CustomTkinter。已建立頁面的切換只需約 `0.3–1.4 ms`，但冷啟動中位數約 `0.54 秒`，第一次建立自動喝水、小地圖巡航及手把組合頁分別約 `150 ms`、`94 ms`及 `418–605 ms`。手把組合頁一次建立約 `257` 個 Tk widget；profiler 顯示主要時間耗在 Tcl/Tk 呼叫、CustomTkinter 圓角繪製與按鈕建立。

問題源於 widget 建立成本與 GUI 架構，不是 Python 無法提供即時桌面介面。本次以 PySide6 重寫 view 層，保留 controller、runtime process、services、settings schema 與遊戲輸入邏輯。

## 目標

- 首次顯示與切頁不呈現控制項逐項繪製、跳動或重排。
- 使用 Qt 原生事件迴圈，不再以 GUI pump 執行全表單同步。
- 保留監控、自動喝水、小地圖巡航、手把組合及 Console 五個功能頁。
- 保留既有 runtime process、高精度 scheduler、OCR、Telegram、音效與按鍵 cleanup 邊界。
- 分階段遷移並保留可明確啟動的 legacy GUI，直到 Qt 功能對齊。
- Python 與打包 EXE 都有獨立、可重複的效能驗收。

## 非目標

- 不重寫自動喝水、巡航、OCR、Telegram 或 controller 業務邏輯。
- 不改變 `settings.json`、profile payload 或公開 import path。
- 不建立獨立 GUI process；Qt GUI 與主 controller 留在主 process。
- 不同時載入 PySide6 與 CustomTkinter。
- 不在第一批刪除 legacy GUI。
- 不為視覺效果加入大量動畫；響應速度優先。

## 架構選擇

採用 Qt 原生事件迴圈。`QApplication.exec()` 擁有主執行緒；`QTimer` 觸發現有 controller update。runtime process 與高精度輸入 scheduler 保持獨立，不移回 GUI thread。

不採用以下方案：

- **Qt 相容 pump**：只把 Tk `pump()` 換成 `QApplication.processEvents()`，會保留舊 GUI ownership 與全量同步問題。
- **GUI 獨立 process**：隔離較完整，但需要新增大量 IPC、序列化與 shutdown 協調，超出本次需求。

## 模組邊界

### Application host

新增 toolkit-neutral application host contract，composition root 建立 backend、GUI、controller 與 Console sink，再將窄介面注入 controller。Host 負責：

- 排程下一次主迴圈 callback。
- 啟動 GUI event loop。
- 判斷 GUI 是否關閉。
- 執行安全 close 與最後 callback cleanup。

Qt host 持有可停止的 single-shot `QTimer` instance 並使用 `QApplication.exec()`；不得使用無 handle 的靜態 `QTimer.singleShot()` 排主 tick。Legacy host 包裝 Tk `after()` 與 `mainloop()`。`gamepad_controller` 不再直接讀取 `gui.root`。

Host 唯一擁有 tick 排程與 shutdown：

- Tick 使用 monotonic deadline，目標 cadence 維持現況；逾期只排下一個未來 deadline，不補跑過期 backlog。
- `close()` 先禁止 reschedule，再停止 timer，最後呼叫 `shutdown_once()`。
- `shutdown_once()` 是唯一且冪等的 cleanup coordinator；`aboutToQuit`、關窗事件及最外層 `finally` 共用它。
- Callback 例外、重複 close 或 close 與 tick 同時發生時，child process 關閉與按鍵釋放都只能執行一次。

### GUI port

第 1 階段從 `AutoPotionController` 與 `gamepad_controller` 的實際使用面凍結 `RuntimeGuiPort` protocol。Port 不暴露 `root`、Qt widget、公開可變 `closed/settings/status/hp_percent` 欄位，也不包含 event processing。Frozen manifest 如下：

```python
class RuntimeGuiPort(Protocol):
    def exists(self) -> bool: ...
    def close(self) -> None: ...
    def is_window_interaction_active(self) -> bool: ...
    def is_detecting_key(self) -> bool: ...
    def is_key_detection_release_pending(self) -> bool: ...
    def consume_key_detection_finished(self) -> bool: ...
    def refresh_bar_preview_once(self) -> None: ...
    def set_bar_preview_provider(self, provider: BarPreviewProvider) -> None: ...
    def set_experience_reset_handler(self, handler: ExperienceResetHandler) -> None: ...
    def set_current_percentages(self, hp_percent: float | None, mp_percent: float | None) -> None: ...
    def set_bar_detection_debug(self, hp_debug: str, mp_debug: str) -> None: ...
    def set_experience_snapshot(self, snapshot: ExperienceSnapshot) -> None: ...
    def set_exp_efficiency_enabled(self, enabled: bool) -> None: ...
    def set_status(self, message: str) -> None: ...
    def show_toggle_notice(self, message: str) -> None: ...
    def set_runtime_info(
        self,
        *,
        scripts_enabled: bool,
        target_active: bool,
        foreground_title: str,
        macro_status: str,
        held_keys: str,
        last_action: str,
    ) -> None: ...
```

主 process 的 port 只能在 GUI main thread 呼叫；headless port 在各 runtime child 的 process main thread 呼叫，不跨 thread／process 傳遞 GUI object。Provider／handler callback 的 ownership 屬 composition root，GUI 不自行銷毀 controller service。狀態更新方向為 controller → GUI command，使用者設定方向為 GUI binding → `AutoPotionSettings` transaction。

Controller 去耦合契約：

- `AutoPotionController.update(now)` 移除 `pump_gui`，不得呼叫 `pump()`、`sync_after_event_processing()` 或任何 event processing。
- GUI 與 Console sink 由 composition root 建立並注入；controller 不再 import 或預設建立具體 GUI。
- Console 使用獨立窄 `ConsoleSink.write(text)`／`flush()` contract；stdout／stderr redirect 由 composition root 擁有，不納入 `RuntimeGuiPort`。
- Legacy adapter 在 controller tick 前提交 Tk 使用者修改；Qt 由 signal 即時提交。
- `HeadlessRuntimeGui` 實作同一窄 port；spawned runtime child 不 import Tk 或 Qt。
- Controller 與 runtime modules 的靜態驗收禁止 `views.*` import、`.root`、`pump()` 及 `sync_after_event_processing()`。

Port 涵蓋：

- 狀態、HP／MP、EXP、runtime 與 foreground 顯示。
- checkbox、設定欄位與 profile 同步。
- notice、音效關聯訊息與錯誤提示。
- 關閉狀態、視窗互動狀態及 key capture 狀態。

Legacy GUI 與 Qt GUI 都實作這個 contract。Controller 依賴 protocol，不 import 具體 toolkit class。第 1 階段同時凍結公開 API／import matrix，至少涵蓋 `maple_star`、`maple_star.controller`、`maple_star.gui`、`auto_potion.py` 與 `maple_gamepad_macro.py`；舊公開 import path 保留 compatibility export。

### Qt view

新增 `maple_star/views_qt/`：

- `application.py`：`QApplication`、Qt host、例外 hook 與啟動流程。
- `main_window.py`：主視窗、導航、`QStackedWidget` 與 page registry。
- `theme.py`：色彩、字型、間距、QSS 與 DPI 規則。
- `bindings.py`：settings signal binding、dirty tracking 與 widget value guard。
- `pages/monitor.py`
- `pages/potion.py`
- `pages/minimap.py`
- `pages/combo.py`
- `pages/console.py`
- `notices.py`：toggle notice、tooltip 及短暫訊息視窗。

每個 page builder 只接收 page context 與 callback，不 import controller。Page 回傳具名 refs，供主視窗實作 GUI port。

## 啟動與繪製

啟動流程分成以下階段：

1. Launcher 解析 GUI backend；第 1–4 階段預設 legacy，只有 `--qt-gui` import PySide6；第 5 階段切換後預設 Qt，只有 `--legacy-gui` import CustomTkinter。兩個參數同時出現時直接報錯。
2. 建立 `QApplication` 與輕量 splash／啟動外框。
3. 進入 Qt event loop，讓 splash 先完成首次 paint。
4. 透過 host 持有、可取消的 single-shot `QTimer` 在不可見主視窗建立 theme、導航與五頁。
5. 每完成一頁便讓回 event loop 處理 paint，避免 Windows 判定程式無回應。
6. 全部頁面、signal 與初始 state 完成後，原子顯示主視窗並關閉 splash。
7. 導航啟用後，切頁只呼叫 `QStackedWidget.setCurrentIndex()`，不得建立新 widget。

主視窗顯示前固定 size policy、minimum size 與 layout margins。顯示後不得以內容 requested size 反覆改寫主視窗高度。

若 splash 本身無法在 `200 ms`內顯示，先量測 PySide6 import、settings load 與其他 imports；不得用延遲或動畫掩蓋同步初始化工作。

## 版面重新設計

### 主視窗

- 左側使用固定寬度垂直導航，右側為 `QStackedWidget`。
- 導航包含監控、自動喝水、小地圖巡航、手把組合與 Console。
- 頂部只顯示應用名稱、全域狀態與必要操作，不重複頁面標題。
- 內容使用統一 spacing、section card 與 form row；避免為每個 label／entry 再建立一層容器。
- 一般頁面允許垂直捲動，不以內容高度調整整個視窗。

### 監控頁

- 第一區顯示 runtime、前景與主要開關狀態。
- 第二區顯示 EXP 統計。
- 第三區顯示 HP／MP 偵測與 preview。
- Profile、全域熱鍵及匯入匯出移到監控頁內的低頻設定 section，不新增第六頁，也不與高頻狀態混排。

### 自動喝水頁

- HP、MP 使用一致的左右 card；窄視窗改為上下排列。
- checkbox、門檻、藥水鍵與目前百分比保持同一視覺群組。
- Preview 圖像更新只替換 pixmap，不重建 label。

### 小地圖巡航頁

- 第一區放啟停、攻擊鍵、邊界校正與目前狀態。
- 第二區放邊界技能與停滯技能。
- 第三區以 table／grid 呈現五組週期鍵，避免五組重複 card。
- 警示音量與通知設定集中在警示區。

### 手把組合頁

- 組合 A、B 使用兩個可重用 `ComboEditor`，寬版左右並排、窄版上下排列。
- 每個 editor 使用 `QFormLayout`／小型 grid，不為每個欄位建立多層透明 frame。
- 秒數欄位使用 `QDoubleSpinBox`，取代 Entry、秒 label、加減兩個按鈕的組合。
- 說明使用標準 tool button／tooltip，避免高成本自繪圓角資訊按鈕。
- Script 改變時只切換相關 row visibility，不重建 editor。

### Console

- 使用 `QPlainTextEdit`，設為唯讀並限制最大 block count。
- Console writer 先寫入 bounded queue；Qt timer 每批追加，單次 flush 有行數上限。
- 清除、複製及自動捲到底部由 Console page 負責。

## 設定資料流

Qt widget 透過 signal 更新 `AutoPotionSettings`：

- 文字與數值欄位完成合法解析後才寫入 model。
- checkbox、combo 與 spin box 在 value changed 時立即更新 model。
- 程式主動同步 widget 時使用 signal blocker，避免把 controller state 誤當使用者修改。
- Model 更新後沿用 controller 現有 idle-save 邊界；GUI 不自行寫檔。
- 不再每個主迴圈呼叫完整 `apply_to_settings()`。
- Profile 切換使用單一 transaction：載入 model、阻擋 signals、同步全部 widget、解除 signals、送出一次 settings update。

GUI runtime state 採差異更新。相同文字、數值、勾選狀態或 pixmap 不重複寫入 widget。

## 主迴圈與 thread 邊界

- Qt GUI 只能在主 thread 建立與更新。
- Host timer 每次只呼叫一次 controller update，完成後依 monotonic deadline 計算下一個 delay；逾期跳過且不補 backlog。
- 不在 callback 內呼叫 `processEvents()` 或建立巢狀 event loop。
- OCR、potion 與 control runtime 保持 child process ownership。
- Preview 擷取若仍可能阻塞，沿用現有 runtime／service 結果；不得把 Windows capture 或 OpenCV 長工作直接搬入 paint handler。
- Controller update 發生例外時寫入 debug log、更新可用狀態，並排程下一輪；cleanup 例外不得阻止其他 shutdown step。

## Legacy 與啟動選擇

- 第 1–4 階段預設 backend 為 CustomTkinter，`--qt-gui` 明確 opt-in。
- 第 5 階段所有 parity、correctness、packaging 與效能 gates 通過後，Qt 才成為預設，`--legacy-gui` 啟動 CustomTkinter。
- `--qt-gui` 與 `--legacy-gui` 同時出現時直接報錯，不猜測優先順序。
- Launcher 延遲 import 選定的 backend，避免同時載入兩套 toolkit。
- 開發環境若 PySide6 import／初始化失敗，可顯示具體錯誤並提示 legacy 命令。
- Release build 缺少 Qt plugin、platform DLL 或 resources 時視為 release smoke failure；不得在 packaged EXE 靜默退回 legacy 而掩蓋包裝錯誤。
- 若 Qt 於版本 N 成為預設，legacy backend 與 packaging 至少保留於 N 及下一個 stable release N+1；最早只能於 N+2 經另一份移除規格刪除 CustomTkinter。

## 錯誤處理

- Page builder 失敗屬 recoverable：在對應 stack slot 顯示錯誤頁、記錄 traceback並繼續建立其他頁。任一 error page 存在時，parity gate 不得通過，也不得把 Qt 切為預設。
- Signal callback 失敗：統一交給 Qt exception hook 與現有 debug log，狀態列顯示摘要。
- 設定驗證失敗：保留上一個有效 model 值，將 widget 標記為錯誤並顯示具體原因。
- Preview 更新失敗：保留上一張有效 pixmap，顯示 unavailable 狀態。
- 關閉視窗：先禁止新互動與 timer reschedule，停止 timer，再由 `shutdown_once()` 呼叫 controller shutdown、釋放按鍵、停止 child process，最後結束 Qt event loop。
- `QApplication`、theme、main window 或 controller／composition 初始化失敗才屬 fatal startup failure：關閉 splash，顯示可複製的錯誤資訊與 legacy 啟動方式。

## 遷移階段

### 第 1 階段：Contract 與 Qt shell

- 建立功能 parity matrix、公開 import／API matrix及同機同電源模式的 legacy Python／EXE 效能 baseline。
- 定義 frozen GUI port、application host、composition root ownership 與 headless recorder contract。
- 移除 controller 的 GUI 建構、event pump 與 `.root` 依賴；由 legacy host 維持原行為。
- 讓 legacy GUI 通過 contract tests。
- 建立 Qt launcher、splash、main window、navigation、theme 與空頁。
- 保持 CustomTkinter 為預設，直到 Qt shell 可啟動及安全關閉。

### 第 2 階段：監控頁

- 遷移 runtime 狀態、EXP、HP／MP preview、profile 與全域操作。
- 建立 widget differential update 與 settings binding。
- 對照 legacy 行為與 public GUI contract。

### 第 3 階段：自動喝水與小地圖巡航

- 遷移所有設定、校正、key capture、音量與 runtime state。
- 確認 settings payload 與 controller command 不變。

### 第 4 階段：手把組合與 Console

- 使用 `ComboEditor` 與 `QDoubleSpinBox` 降低 widget 數量。
- 完成 script visibility、controller button、tooltip、bounded console 與 copy/clear。

### 第 5 階段：預設切換

- 完成功能 parity matrix、Python／EXE benchmark、DPI 與中文輸入 smoke；parity matrix 於各頁遷移完成時逐頁通過。
- Qt 成為預設，保留 `--legacy-gui`。
- 更新安裝、runtime compatibility、build 與 release 文件。

## Dependency 與 packaging

- `requirements.txt` 與 `requirements-release-lock.txt` 同步加入經環境驗證的 PySide6／Qt 套件 pin；legacy 期間保留 CustomTkinter。
- `build_release.bat` 加入 Qt import smoke、PyInstaller Qt hooks、platform plugin 與必要 resources。
- Python 與 packaged EXE 都分別測試 Qt／legacy backend；spawned potion、experience 與 control child 均不得載入任一 GUI toolkit。
- Release smoke 至少驗證 `QApplication`、主視窗建立、每頁切換及正常關閉。
- `qwindows.dll` 依實際 PyInstaller onedir layout 驗證；檔名檢查只作診斷，實際啟動 smoke 才是最終 gate。
- legacy 移除前不刪除 CustomTkinter packaging 規則。

## 測試

### Contract

- Legacy 與 Qt GUI 都通過同一組 GUI port contract tests。
- Controller 測試使用 protocol test double，不依賴 Tk 或 Qt widget。
- Application host 測試鎖定 schedule、close、exception 與 shutdown 次序。
- 測試 close 與 tick 同時發生、callback 例外及重複 close，確認按鍵釋放與 child process cleanup 僅執行一次。
- Subprocess import-isolation 測試確認 Qt backend 不載入 `customtkinter`、legacy backend 不載入 `PySide6`，spawn child 兩者皆不載入。
- 公開 facade／entrypoint import matrix 與 backend 選擇參數都納入 contract gate。

### Qt view

- 使用 offscreen Qt platform 測試五頁建立、導航、signal binding、profile transaction 與 error page。
- 測試 programmatic sync 使用 signal blocker，不回寫 settings。
- 測試使用者修改只更新對應欄位，不觸發全表單同步。
- 測試 ComboEditor script visibility 不重建 widget。
- 測試 Console block count 與 batch flush 上限。

### 真實 GUI smoke

- Windows 真實 GUI 驗證 splash、完整主視窗、五頁切換、resize、DPI、中文輸入法與 close cleanup。
- Smoke 必須在 `finally` 關閉視窗並檢查殘留 Python process。
- Python 與 packaged EXE 分開執行。

## 效能驗收

- 第 1 階段先在相同電腦、相同電源模式建立 legacy Python／EXE baseline；Python 與 EXE 各自至少執行 `7` 次 fresh-process cold start。
- `first visible shell` marker：legacy 在 Tk root 首次 exposed paint 後寫入，Qt 在 splash 首次 exposed paint 後寫入；Qt Python 模式其中位數 `<= 200 ms`。
- `main ready` marker 在主視窗 exposed、輸入啟用且該輪 queued callback 完成後寫入；Python 模式其中位數 `<= 700 ms`。
- 預載完成後切頁至少取 `100` samples，起點為導航 action，終點為目標頁下一次 paint；p95 `<= 16 ms`，最大值 `<= 50 ms`。
- 一般輸入、勾選與按鈕至少取 `100` samples，終點為目標 widget 可觀察狀態更新後的下一次 paint；p95 `<= 16 ms`。
- 主視窗顯示後不得建立 page widget；測試以建構計數鎖定。
- 閒置 controller tick 不執行全表單讀取或 widget 全量更新。
- Qt EXE 的 `first visible shell` 與 `main ready` cold-start 中位數各不得高於 legacy EXE 對應 marker baseline 的 `110%`，且 `7` 次不得出現 timeout 或 crash；不得用 Python 數據代替。
- Benchmark 報告分開保留 Python／EXE raw samples、marker 定義、median、p95、maximum、backend、mode、電源模式與環境資訊，並輸出各 gate pass／fail。

## 完成條件

- Qt 五頁功能與 legacy parity matrix 全部完成。
- Runtime、settings、profile、key capture、notice、preview、Console 與 shutdown 行為對齊。
- Python 與 EXE 通過各自效能 gate。
- Controller 不 import 具體 GUI toolkit，也不直接存取 Tk root 或 Qt widget。
- Qt 成為預設後，legacy 仍可用明確參數啟動。
- 未經另一份移除規格，不刪除 CustomTkinter GUI。
