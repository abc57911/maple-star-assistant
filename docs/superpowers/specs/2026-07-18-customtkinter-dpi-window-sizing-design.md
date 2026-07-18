# CustomTkinter DPI 視窗尺寸修正

> 知識庫索引：[../../INDEX.md](../../INDEX.md)

## 問題

筆電使用 Windows 125% 顯示縮放時，預設監控頁下方出現大量空白。真實 GUI trace 已重現同一問題：同步邏輯計算的目標高度為 `692`，實際 root 高度卻成為 `865`，比例正好是 `1.25`。

CustomTkinter 的 `CTk.geometry()` 與 `CTk.minsize()` 接收邏輯尺寸，並自行套用 window scaling。Tk 的 `winfo_width()`、`winfo_height()` 與 configure event 則回報實體像素。現有程式讀取實體像素後，再交給 `geometry()`，因此重複套用 DPI 縮放。

## 目標

- 125%、150% 與 175% 顯示縮放下，視窗高度與內容目標一致。
- 修正監控頁、Console 頁、Console 收合、經驗模式切換與視窗尺寸記憶的同類問題。
- 保留現有版面、設定格式、視窗位置與 CustomTkinter backend。
- 不改動 PySide6 遷移規格。

## 非目標

- 不重設頁面布局或視覺樣式。
- 不保存新的視窗寬高設定。
- 不使用固定 `1.25` 除數或讀取單一螢幕 DPI。
- 不修改 widget responsive breakpoint；本次只處理 root window size 的單位邊界。

## 設計

### 尺寸單位

新增單一私有 helper，透過 `CTk.geometry()` getter 取得 CustomTkinter 已反向換算的邏輯寬高。Helper 解析 geometry 字串開頭的 `width x height`，成功時回傳 `(width, height)`，失敗時回傳 `None`。

內容高度保留 `controls_frame.grid_bbox()` 作為唯一來源，但先透過 CustomTkinter 的有效 widget scaling 轉成 logical pixels。停用所有高度回寫後的校準 trace 顯示，100%／125%／150% 下的 raw bbox 高度分別為 `496 / 628 / 744` physical pixels；它不是 logical size。

新增第二個窄 helper，使用已 pin 版本 CustomTkinter 提供的 `_reverse_widget_scaling()` 轉換 bbox 的 `top + height`，並以 `round()` 產生 logical integer。若轉換 API 不存在、丟出例外、回傳非有限值或小於等於零，helper 回傳 `0`。`_left_panel_content_height()` 不再用同為 physical pixels 的 `winfo_reqheight()` fallback。呼叫端收到 `0` 時沿用目前視窗尺寸並等待下一次既有 layout sync。

所有會把目前 root 尺寸重新寫回 `geometry()` 的路徑都改用此 helper：

- Console 頁 minimum-height 調整。
- 記憶展開視窗寬度。
- 記憶完整面板尺寸。
- 只改寬度時保留目前高度。
- 依左側內容同步完整視窗高度。

`winfo_x()`、`winfo_y()` 與 notice／tooltip 座標維持實體螢幕座標，不做轉換。`<Configure>` event 仍只用於判斷尺寸是否改變，不把 event size 寫回 geometry。

### 資料流

1. Tk layout 以 physical pixels 回報 content bbox。
2. Widget helper 依 CustomTkinter 實際 widget scaling 將 bbox 轉成 logical content height。
3. Root helper 從 `root.geometry()` 讀取目前 logical window size。
4. 同步程式比較 logical current size 與 logical target size。
5. `_set_window_size()` 將 logical size 交給 CustomTkinter。
6. CustomTkinter 僅套用一次 Windows DPI scaling。

### 錯誤處理

Root geometry 無法解析、widget scaling 轉換失敗或 content bbox 無效時，本輪 read-modify-write 與尺寸記憶直接跳過。既有 `minsize()` 保留視窗可用下限，下一次 deferred build、切頁或 resize settle 會再次同步。程式不得把 `winfo_width()`、`winfo_height()`、`grid_bbox()` 或 `winfo_reqheight()` 的 physical pixels 直接當作 logical size。

## 驗證

### 單元測試

- geometry 含正座標、負座標或無座標時，都能解析 logical width／height。
- malformed geometry 回傳 `None`，尺寸同步與記憶不寫入 geometry。
- 明確模擬 125%：`root.geometry()` 回報 logical `992x692`，`winfo` 回報 physical `1240x865`。目標仍為 `692` 時不得呼叫 setter；目標高度改變時必須寫入 `992x<logical target>`。
- `_sync_full_window_height_to_left_panel()` 比較並寫回 logical size，不使用實體 `winfo` 尺寸。
- `_set_window_width()` 改寬時保留目前 logical height。
- Console 頁、寬度記憶與完整面板尺寸記憶使用同一 helper。
- 100%／125%／150% 的 physical bbox 經實際 widget scaling 轉換後，logical content height 在 rounding 容差內一致。
- `grid_bbox()` 或 scaling 轉換無效時跳過同步，不使用 physical `winfo_reqheight()` fallback。

### 真實 GUI smoke

只執行受影響的 GUI 尺寸 smoke：

- 自動 smoke 同時設定 widget／window scaling，分別模擬 100%、125%、150% 與 175%，各建立預設監控頁；每案透過 `ScalingTracker` 讀取實際有效 widget／window scaling，不假設測試輸入值等於有效倍率，並在 `finally` 恢復測試前的全域 scaling。125% 筆電另作人工確認。
- 等待 deferred monitor controls 完成。
- 驗證 height sync 與 width-only 更新後，未修改維度的 logical 值保持不變。
- 同時驗證 `winfo` physical size 除以實際有效 window scaling 後，與 logical geometry 相差不超過 `1 px`；不得只比較 `root.geometry()` getter 與內部 target。
- 關閉 GUI 並確認無殘留測試程序。

不執行全套測試、`python tools\verify.py`、`full`、`ocr-slow` 或 `performance`。

## 完成條件

- 125% 筆電縮放不再讓 root 尺寸二次放大。
- 所有 root size read-modify-write 路徑使用 logical size。
- 視窗位置、notice、tooltip 與 responsive widget 行為不變。
- 直接相關測試與真實 GUI scaling smoke 通過。
