# CustomTkinter DPI 與自適應視窗尺寸修正

> 知識庫索引：[../../INDEX.md](../../INDEX.md)

## 問題

筆電使用 Windows 125% 顯示縮放時，預設監控頁下方出現大量空白。真實 GUI trace 已重現同一問題：同步邏輯計算的目標高度為 `692`，實際 root 高度卻成為 `865`，比例正好是 `1.25`。

CustomTkinter 的 `CTk.geometry()` 與 `CTk.minsize()` 接收邏輯尺寸，並自行套用 window scaling。Tk 的 `winfo_width()`、`winfo_height()` 與 configure event 則回報實體像素。現有程式讀取實體像素後，再交給 `geometry()`，因此重複套用 DPI 縮放。

## 目標

- 125%、150% 與 175% 顯示縮放下，視窗高度與內容目標一致。
- 啟動、切頁及頁面結構改變後，視窗自動貼合目前內容。
- 內容超過目前螢幕工作區時限制視窗高度，改由頁面垂直捲動。
- 使用者手動調整視窗後，同一頁不再強制縮放；切頁後重新自動貼合。
- 修正監控頁、Console 頁、Console 收合、經驗模式切換與視窗尺寸記憶的同類問題。
- 保留現有版面、設定格式、視窗位置與 CustomTkinter backend。
- 不改動 PySide6 遷移規格。

## 非目標

- 不重設欄位分組或視覺樣式。
- 不保存新的視窗寬高設定。
- 不使用固定 `1.25` 除數或讀取單一螢幕 DPI。
- 不修改既有 widget responsive breakpoint；只新增頁面 overflow fallback。

## 設計

### 尺寸單位

新增單一私有 helper，透過 `CTk.geometry()` getter 取得 CustomTkinter 已反向換算的邏輯寬高。Helper 解析 geometry 字串開頭的 `width x height`，成功時回傳 `(width, height)`，失敗時回傳 `None`。

停用所有高度回寫後的校準 trace 顯示，100%／125%／150% 下的 Tk raw bbox 高度分別為 `496 / 628 / 744` physical pixels；Tk bbox 不是 logical size。實作後的內容高度來源改為 active `AdaptiveScrollHost` 的完整 canvas content bbox，避免 viewport clamp 污染量測。

新增第二個窄 helper，使用已 pin 版本 CustomTkinter 提供的 `_reverse_widget_scaling()` 轉換 canvas bbox 的完整 physical height，並以 `round()` 產生 logical integer。若 content bbox 不存在、轉換 API 不存在、丟出例外、回傳非有限值或小於等於零，helper 回傳 `0`。程式不再用 viewport bbox 或同為 physical pixels 的 `winfo_reqheight()` fallback。呼叫端收到 `0` 時沿用目前視窗尺寸並等待下一次既有 layout sync。

所有會把目前 root 尺寸重新寫回 `geometry()` 的路徑都改用此 helper：

- Console 頁 minimum-height 調整。
- 記憶展開視窗寬度。
- 記憶完整面板尺寸。
- 只改寬度時保留目前高度。
- 依左側內容同步完整視窗高度。

`winfo_x()`、`winfo_y()` 與 notice／tooltip 座標維持實體螢幕座標，不做轉換。`<Configure>` event 仍只用於判斷尺寸是否改變，不把 event size 寫回 geometry。

### 自動貼合與使用者 ownership

新增 `auto_fit_pending`、`user_resized_current_page` 與 programmatic resize generation：

- App 啟動、active page 實際切換、deferred page build 完成及明確的收合／展開操作會設定 `auto_fit_pending`。
- 重選目前頁面不清除 user-resized flag，也不重新取得尺寸 ownership。
- Auto-fit 完成後清除 pending；同一 layout signature 不重複寫入 geometry。
- 所有 `geometry()` 與 `minsize()` mutation 都經同一 coordinator。Coordinator 保存 generation、logical target 與前一個 programmatic target。
- Generation 存續期間的全部 configure event 都視為 programmatic；idle settle 讀取最終 logical geometry 後才關閉 generation。Generation 關閉後，與前一個 target 相同的 duplicate event仍忽略，第一個不同尺寸才取得 user ownership。
- 非 programmatic 的 root size configure event 視為使用者 resize，設定 `user_resized_current_page=True`。
- 同一頁收到一般狀態更新、preview 更新或 repaint 時，若使用者已調整尺寸便跳過 auto-fit。
- 切頁與明確的頁面結構改變會清除 user-resized flag，重新計算一次合理尺寸。
- 已有 user ownership 時跨螢幕，若目前尺寸仍落在新 work area 便保留；只有超出新 work area 時才執行必要 clamp，不重新完整 auto-fit。

這個 ownership 規則避免背景 status refresh 持續把使用者拉回內容高度，也避免使用時間常數猜測 programmatic resize 是否完成。

### 工作區與 overflow

使用目前 root HWND 的 `MonitorFromWindow`／`GetMonitorInfoW` 取得所在螢幕 work area，排除工作列。Work area 與 outer window rect 都是 physical pixels：

1. 以 outer rect 減去 client `winfo_height()`，取得 non-client frame physical height。
2. 以目前 outer top 到 work-area bottom 的距離，扣除 non-client height 與小型 edge margin；不得只使用 work-area 總高度。
3. 依 CustomTkinter 實際 window scaling 轉成 maximum logical client height。
4. Auto-fit target 為 `min(logical content target, maximum logical client height)`。

監控、自動喝水、小地圖巡航與手把組合頁使用共用的 `AdaptiveScrollHost`。Host 擁有 canvas、垂直 scrollbar 與自然 propagation 的 inner content frame；page builder 只接收 inner frame。Layout 完成後以 canvas `bbox("all")` 取得未裁切的完整 physical content extent，再換算為 logical height。量測不得使用已被 clamp 的 viewport 或外層 `controls_frame.grid_bbox()`。

Canvas configure 時只把 viewport 寬度同步到 inner window item；inner height 維持自然 propagation。如此既能讓既有 responsive breakpoint 依可用寬度運作，也不會讓 viewport 高度回寫並污染自然內容量測。

內容低於上限時，viewport 貼合 inner content 且不保留多餘高度；內容超過上限時，viewport 填滿可用高度並啟用滾動。Console 頁留在 scroll host 外，維持填滿剩餘空間的行為，不依文字內容縮放。

Root minimum height 依頁面類型動態設定，且永遠不得高於 clamped target：一般 scroll page 使用 `COMPACT_WINDOW_MIN_HEIGHT` 作可捲動 usability floor，Console 使用 `CONSOLE_PAGE_MIN_HEIGHT`，compact experience mode 沿用其專用 floor。Coordinator 在高頁、矮頁、overflow 與切頁後都重新設定對應 floor；若工作區低於 floor，minimum 使用 maximum logical client height。

Scroll host 只改 page container；既有 page builder 仍接收內容 frame，lazy page construction、widget refs 與 public GUI contract 不變。

### 資料流

1. Active page layout 以 physical pixels 回報 content bbox。
2. Widget helper 依 CustomTkinter 實際 widget scaling 將 bbox 轉成 logical content height。
3. Work-area helper 計算 maximum logical client height。
4. Root helper 從 `root.geometry()` 讀取目前 logical window size。
5. Auto-fit coordinator 檢查 pending、user ownership 與 layout signature。Signature 至少包含 active page、logical content height、monitor identity、work area、effective widget／window scaling 與 overflow state。
6. 同步程式選擇 content target 或 work-area 上限，並更新 scroll overflow 狀態。
7. `_set_window_size()` 將 logical size 交給 CustomTkinter。
8. CustomTkinter 僅套用一次 Windows DPI scaling。

### 錯誤處理

Root geometry 無法解析、widget scaling 轉換失敗或 content bbox 無效時，本輪 read-modify-write 與尺寸記憶直接跳過。工作區取得失敗時，只使用 content target 與既有 `minsize()`，不猜測螢幕高度。下一次 deferred build、切頁或 resize settle 會再次同步。程式不得把 `winfo_width()`、`winfo_height()`、`grid_bbox()` 或 `winfo_reqheight()` 的 physical pixels 直接當作 logical size。

## 驗證

### 單元測試

- geometry 含正座標、負座標或無座標時，都能解析 logical width／height。
- malformed geometry 回傳 `None`，尺寸同步與記憶不寫入 geometry。
- 明確模擬 125%：`root.geometry()` 回報 logical `992x692`，`winfo` 回報 physical `1240x865`。目標仍為 `692` 時不得呼叫 setter；目標高度改變時必須寫入 `992x<logical target>`。
- `_sync_full_window_height_to_left_panel()` 比較並寫回 logical size，不使用實體 `winfo` 尺寸。
- `_set_window_width()` 改寬時保留目前 logical height。
- Console 頁、寬度記憶與完整面板尺寸記憶使用同一 helper。
- 100%／125%／150% 的完整 canvas physical bbox 經實際 widget scaling 轉換後，logical content height 在 rounding 容差內一致，且不受 viewport clamp 影響。
- `grid_bbox()` 或 scaling 轉換無效時跳過同步，不使用 physical `winfo_reqheight()` fallback。
- 啟動與切頁各只 auto-fit 一次；相同 layout signature 不重複寫入 geometry。
- 使用者 resize 後，status、preview 與 repaint 不改寫視窗尺寸；下一次切頁恢復 auto-fit。
- Programmatic resize 的 configure event 不得誤標記為 user resize。
- Programmatic geometry、minsize 引發的 intermediate／duplicate configure event 都保留原 generation ownership。
- 重選同一頁不清除 user resize；active page 真正改變後才恢復 auto-fit。
- Work area 計算扣除工作列與 non-client frame；跨螢幕後使用 root 所在螢幕。
- 視窗靠近工作區底部時，以目前 outer top 到 work-area bottom 計算可用高度，不覆蓋工作列。
- Content 低於上限時 viewport 不留空白；超過上限時 root 被 clamp，active page 可捲至最後一個控制項。
- Overflow 時 `minsize height <= clamped target`；從高頁切回矮頁時恢復矮頁 floor 與 content-fit height。
- Lazy builder 每頁仍只執行一次，builder parent 為 inner content frame，既有公開 refs 仍可操作。
- Console 頁不依文字量改變 root 高度。

### 真實 GUI smoke

只執行受影響的 GUI 尺寸 smoke：

- 自動 smoke 同時設定 widget／window scaling，分別模擬 100%、125%、150% 與 175%，各建立預設監控頁；每案透過 `ScalingTracker` 讀取實際有效 widget／window scaling，不假設測試輸入值等於有效倍率，並在 `finally` 恢復測試前的全域 scaling。125% 筆電另作人工確認。
- 等待 deferred monitor controls 完成。
- 驗證監控頁下緣與 root client 下緣只保留設計 padding，不出現截圖中的大面積空白。
- 切換四個設定頁，確認每頁依內容重新貼合；手動拉高其中一頁後，狀態刷新不會縮回。
- 模擬內容超過 work area，確認可滾動至最後一個控制項且視窗不覆蓋工作列。
- 驗證 height sync 與 width-only 更新後，未修改維度的 logical 值保持不變。
- 同時驗證 `winfo` physical size 除以實際有效 window scaling 後，與 logical geometry 相差不超過 `1 px`；不得只比較 `root.geometry()` getter 與內部 target。
- 關閉 GUI 並確認無殘留測試程序。

不執行全套測試、`python tools\verify.py`、`full`、`ocr-slow` 或 `performance`。

## 完成條件

- 125% 筆電縮放不再讓 root 尺寸二次放大。
- 所有 root size read-modify-write 路徑使用 logical size。
- 啟動與切頁自動貼合內容，手動 resize ownership 穩定。
- 內容超過工作區時可完整捲動，Console 維持填滿頁面。
- 視窗位置、notice、tooltip 與既有 responsive breakpoint 行為不變。
- 直接相關測試與真實 GUI scaling smoke 通過。
