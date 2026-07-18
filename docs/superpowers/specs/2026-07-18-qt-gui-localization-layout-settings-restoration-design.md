# Qt GUI 繁中化、雙欄排版與設定恢復

> 知識庫索引：[../../INDEX.md](../../INDEX.md)

## 決策狀態

使用者已核准本規格。改版以目前 PySide6 GUI 為基礎，不改 backend、設定欄位名稱或 runtime 行為。

已核准的產品決策：

- 所有介面選項使用繁體中文。
- 保留 `HP／MP`、`EXP`、`PID`、`IPC`；其餘使用者可見的英文術語翻成繁體中文。
- 六頁使用自適應雙欄卡片；窄視窗自動降為單欄。
- 一般輸入元件限制合理寬度，不隨視窗無限制延展。
- 所有布林設定使用滑動 switch；一次性動作才使用按鈕。
- `P:\settings.json` 是改版前設定的唯一恢復來源。
- 不執行壓力測試或全套效能測試。

## 目標

- 移除介面中的 snake_case 欄位名稱與不必要英文。
- 讓導航、卡片、switch、輸入元件、表格與動作按鈕具有清楚的視覺層級。
- 在寬螢幕維持緊湊雙欄，在筆電窄視窗保持可讀與可操作。
- 完整恢復改版前的快捷鍵、喝水、巡航、手把組合、視窗位置與 profiles。
- 保持現有 typed binding、settings migration、runtime handler 與公開介面相容。

## 非目標

- 不修改 backend process、worker、IPC 或自動化演算法。
- 不更名 settings model 的 Python 欄位或 JSON key。
- 不引入 Qt Designer `.ui` 檔或新的 UI 建置流程。
- 不新增可切換語系。
- 不把一次性動作誤做成 switch。

## 元件架構

`maple_star/views_qt/` 新增共用 UI 元件與介面文字 metadata：

- `SettingsCard`：包含卡片標題、選填說明與內容區。
- `SettingsGrid`：寬視窗使用兩欄，窄視窗使用單欄；版面變更保持冪等。
- `SwitchControl`：以清楚的軌道、滑塊、開關色彩與鍵盤焦點表示表單中的布林狀態。
- `SwitchDelegate`：在週期按鍵與組合 slot 表格中繪製及編輯相同 switch 語意。
- 欄位 metadata：以現有 setting key 對應繁中標籤、說明與適用的輸入寬度。

共用元件只處理呈現與 layout。既有 `SettingsBinding` 繼續擁有 widget 與 model 的雙向同步；程式同步仍使用 `QSignalBlocker`。

## 資訊架構與排版

### 監控

- 左欄：執行狀態與自動撿取 switch。
- 右欄：自動喝水 switch、全域快捷鍵與撿取快捷鍵。

### 自動喝水

- 左欄：HP 設定與 HUD 預覽。
- 右欄：MP 設定、連續補充與重新擷取預覽動作。

### 小地圖巡航

- 左欄：巡航快捷鍵、攻擊鍵、邊界與偵測區域。
- 右欄：邊界技能、停滯技能、警示與週期按鍵表格。

### 手把組合

- 左欄：RB 組合設定。
- 右欄：LB 組合設定與組合 slot 表格。

### 經驗計算

- 左欄：EXP 狀態、EXP 效率 switch、重置動作與視窗設定。
- 右欄：EXP 統計、重置與角色能力值快捷鍵。
- 完整面板、精簡 EXP 視窗座標與「視窗保持最上層」集中於此頁。

### 診斷

- 顯示 worker／程序健康資訊。
- Console 橫跨內容寬度，保留垂直伸展能力。

頁面 viewport 可用寬度達 `820` logical pixels 時使用雙欄，低於 `820` 時使用單欄。卡片最小寬度為 `340`，最大寬度為 `480`；快捷鍵輸入框最大寬度為 `180`，一般文字輸入框為 `280`，整數與小數輸入框為 `140`。只有表格、Console 與預覽區可使用剩餘空間。頁面提供垂直捲動；表格內容超過欄寬時由表格提供水平捲動，不讓整頁產生水平捲動。額外視窗寬度分配給欄間留白與頁面邊距。

## 翻譯邊界

- 所有 field label 由集中 metadata 提供，不直接顯示 Python field name。
- `Workers` 翻成「背景程序」，`preview` 翻成「預覽」，`heartbeat` 翻成「心跳」，`queue` 翻成「佇列」。
- `HP／MP`、`EXP`、`PID`、`IPC` 保留縮寫；必要時在說明文字補充用途。
- 表格欄名、狀態文字、空值提示與按鈕文字一併檢查，避免只翻譯 form label。
- 顯示值另設 mapping：`left／right` 顯示「左／右」，組合 `script_id` 顯示繁中腳本名稱，`active／inactive`、`scripts／macro／held` 與 preview `ok` 等狀態顯示繁中。
- 外部視窗標題、使用者輸入、快捷鍵名稱、controller button 名稱、Console 原始 log 與 backend 自由格式診斷文字不屬翻譯保證；介面固定文案與結構化狀態必須翻譯。

## Switch 與按鈕語意

所有可見表單布林欄位使用 `SwitchControl`，包含 HP／MP 啟用、連續補充、EXP 效率、巡航技能與視窗置頂。舊收合欄位只保留設定載入相容性，不建立介面控制項。週期按鍵與組合 slot 表格的布林欄位使用 `SwitchDelegate`，不得保留 checkbox 或一般文字 cell。

下列 runtime 狀態也使用「文字標籤＋switch」：

- 自動喝水。
- 自動撿取。

這兩個 switch 保留既有 toggled handler 與程式同步行為。狀態同步不得產生遞迴 command。

一次性動作保留按鈕：

- 重置經驗統計。
- 重新擷取 HP／MP 預覽。
- 設定檔新增、刪除、匯入與匯出維持 menu action。它們是一次性 command，不是布林狀態，不需改成頁面按鈕。

## 設定恢復

`P:\settings.json` 是沒有 `schema_version`、使用 `active_profile` 與 flat root fields 的 legacy v1 文件。它是本次唯一合法來源。恢復後的 production 文件使用 settings v2；`active_profile` 必須語意等價映射到 `selected_profile`。

新增 `maple_star/services/settings_restoration.py` 擁有完整恢復 transaction。它公開可注入 path、clock 與 atomic writer 的純 Python service；`tools/restore_settings.py` 只負責命令列 preflight、呼叫 service 與輸出差異，不自行實作資料規則。測試可在 temporary directory 注入來源與 target。

恢復前必須關閉 MapleStar，並確認沒有 command line 指向本專案 `main.py`、`main.pyw` 或 `run_maple_star` 的存活程序。工具以 exclusive-create 取得同目錄 `settings.restore.lock`，transaction 與 rollback 完成前不釋放；lock 防止重複執行 restoration tool。現有 App 不認得此 lock，因此「無 App 程序」仍是必要前置條件，不能只靠 lock 判斷安全。

恢復流程如下：

1. 解析來源 raw JSON，要求 root、`profiles` 與每個 profile 都是 object。
2. 以 `GLOBAL_SETTING_KEYS`、`PROFILE_SETTING_KEYS` 與 legacy metadata key 建立完整欄位集合。缺少、未知、錯型別或超出 model 範圍時輸出逐欄差異並停止；不得以 fallback 或 clamp 通過驗證。legacy root 的 profile 欄位必須與 `profiles[active_profile]` 對應欄位相等；任一衝突都列出完整 key path 並停止，不採 root 或 profile 優先。
3. 使用 `load_settings(path, save_migrations=False)` 建立 canonical model，並比對 raw legacy 值與 canonical 值。只允許 `active_profile -> selected_profile`、settings v2 結構重排與 JSON 排序；本次來源的業務值不得正規化成不同值。
4. 將目前專案設定複製成同目錄 `settings.json.pre-restore.<UTC timestamp>.bak.json`。備份完成後重新解析並比對 SHA-256。
5. 以同目錄 pending file、flush、`fsync` 與 `os.replace` 原子寫入 v2 文件；沿用 production settings writer，不直接覆寫 target。
6. 重新載入 target，逐欄比對來源 canonical model、active／selected profile 與全部 profiles。
7. 再執行一次 save／load round trip，確認所有已知業務值不變。
8. 比對來源檔操作前後的 SHA-256，確認 `P:\settings.json` 全程唯讀且內容未變。

任一步驟失敗都停止恢復。流程不得部分套用設定，也不得以預設值覆蓋來源資料。

來源 legacy v1 沒有 root/profile `extensions`。本次恢復不宣稱從來源保留不存在的 extensions。一般 settings v2 的未知欄位保存契約維持現有 migration tests；若實作碰觸該契約，必須改用 `SettingsV2Document` 並補 production round-trip 測試，不得經 `AutoPotionSettings` 靜默丟失 extensions。

## 錯誤處理

- 缺少 field metadata 時，測試直接失敗；production 介面不得退回顯示 snake_case。
- 來源設定驗證失敗時，保留來源與目前設定，並回報具體欄位、型別、範圍或 schema 錯誤。
- target 原子替換失敗時刪除 pending file並保留 target；替換後驗證失敗時，用已驗證備份原子還原並再次驗證 checksum。
- 發現 MapleStar 仍在執行、restore lock 已存在或 legacy root/profile 值衝突時，在建立 target 備份前停止。
- widget 值格式錯誤時，沿用既有狀態列錯誤回報，不送出無效設定 transaction。
- 自適應 layout 只在欄數實際變化時重新排列，避免 resize event 造成重排循環。

## 驗收標準

### 翻譯

- 六頁固定文案、表格欄名、結構化狀態與動作不得顯示設定 key 或未核准英文術語。
- 保留的縮寫僅限 `HP／MP`、`EXP`、`PID`、`IPC` 與鍵盤／手把鍵名。
- 外部視窗標題、使用者資料、Console 與 backend 自由格式 log 不納入固定文案掃描。

### 排版

- viewport 寬度 `>= 820` 顯示兩欄；`< 820` 顯示單欄。
- 整頁沒有水平捲動；大型表格可使用自身水平捲動。
- 卡片與各類輸入欄位不超過已定義的 logical-pixel 上限。
- breakpoint 前後連續 resize 不重複加入 layout item，也不造成幾何振盪。
- 表格、Console 與預覽區正確使用剩餘空間。

### 控制元件

- 所有布林 settings widget 都是 `SwitchControl` 或 table `SwitchDelegate`。
- switch 支援滑鼠、Space 鍵、焦點提示與停用狀態。
- 自動喝水與自動撿取仍呼叫原 runtime handler。
- 程式同步 switch 不發出使用者 command。

### 設定

- `P:\settings.json` 載入後，已知欄位逐一相等。
- legacy `active_profile` 與 v2 `selected_profile` 語意相等，全部 profiles 的已知欄位完整保留。
- 儲存再載入後語意相等。
- GUI 初始值與恢復後 settings model 相等。
- 恢復前 target 備份可解析且 SHA-256 與原 target 相等。
- `P:\settings.json` 在 transaction 前後 SHA-256 相等。

## 驗證範圍

新增或更新直接相關測試：

- Qt field metadata 覆蓋率與繁中標籤。
- `SettingsGrid` 雙欄／單欄 breakpoint 與冪等重排。
- `SwitchControl` 狀態、鍵盤、binding 與 signal blocking。
- `SwitchDelegate` 的滑鼠、Space、停用狀態與 model update。
- 六頁 widget 類型、卡片分組與輸入寬度。
- 固定文案與結構化顯示值 mapping 覆蓋率。
- 自動喝水與自動撿取 handler parity。
- 使用 repository legacy fixture 與 temporary directory 測試載入、恢復、rollback、lock 與 round trip；自動測試不得依賴 `P:` 或修改真實設定。
- 對真實 `P:\settings.json` 只執行本機唯讀 preflight 與一次性恢復驗收，並確認來源 checksum 不變。

執行直接相關的 `test_qt_*`、settings migration／production 與 function parity 測試。使用無副作用 Qt 啟動模式檢查實際畫面。不執行壓力測試、效能 profile 或全套測試。

## 影響檔案

預計修改：

- `maple_star/views_qt/theme.py`
- `maple_star/views_qt/bindings.py`
- `maple_star/views_qt/main_window.py`
- `maple_star/views_qt/settings_gui.py`
- `maple_star/views_qt/pages/*.py`
- `maple_star/views_qt/models/combo_model.py`
- `maple_star/views_qt/models/periodic_key_model.py`
- `maple_star/views_qt/components.py`（新增）
- `maple_star/views_qt/delegates.py`（新增）
- `maple_star/views_qt/labels.py`（新增）
- `maple_star/services/settings_restoration.py`（新增）
- `tools/restore_settings.py`（新增）
- `tests/test_qt_*.py`
- `tests/test_settings_restoration.py`（新增）
- `settings.json`（本機設定恢復，不提交）
- `docs/INDEX.md`

## 完成條件

- 六頁介面完整繁中化。
- 自適應雙欄卡片在寬窄視窗都可用。
- 所有布林值呈現為 switch；一次性動作維持按鈕。
- `P:\settings.json` 的設定完整恢復且 round trip 不遺失。
- 直接相關測試與無副作用 GUI 檢查通過。
