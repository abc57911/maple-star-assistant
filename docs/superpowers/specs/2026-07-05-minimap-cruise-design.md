# 小地圖巡航設計

> 知識庫索引：[../../INDEX.md](../../INDEX.md)

## 背景

使用者需要一個獨立的全自動巡航腳本。腳本根據小地圖上的黃色角色點判斷角色位置。使用者用滑鼠點擊小地圖的左、右邊界後，腳本保存 X 軸範圍，並在角色靠近邊界時自動轉向。

此功能只支援同一層水平平台。邊界設定流程會保存左界 X、右界 X、偵測 Y、以及偵測帶高度。腳本不處理多層平台、爬繩、傳送點、NPC 互動、或路徑規劃。

## 目標

- 新增獨立「小地圖巡航」功能，不沿用 combo 設定。
- 提供可自訂的巡航啟停熱鍵。
- 提供獨立的巡航攻擊鍵，預設 `C`。
- 使用滑鼠點擊設定小地圖左、右邊界，並保存到 `settings.json`。
- 以約 1 秒一次的頻率偵測角色位置。
- 持續按住攻擊鍵；到邊界時先放開攻擊鍵，再短按相反方向鍵，最後重新按住攻擊鍵。
- 停用、失焦、快捷鍵設定中、HUD 不可用、或偵測失敗時釋放所有巡航持有按鍵。

## 非目標

- 不支援多層平台判斷。
- 不自動辨識藍色傳送點或綠色 NPC。
- 不沿用 `combo_slots` 的 `attack_key`。
- 不把主要邏輯放入舊 facade，例如 `maple_star.controller`、`maple_star.gui`、`maple_star.settings`。
- 不改變自動喝水、拾取、EXP OCR、或既有手把 combo 行為。

## 架構

採用獨立服務模組，避免擴大 `AutoPotionController` 職責。

- `maple_star/services/minimap_cruise.py`
  - 定義巡航 runtime 狀態機。
  - 管理攻擊鍵與方向鍵送出順序。
  - 擷取小地圖偵測帶。
  - 偵測黃色角色點中心。
  - 回傳狀態文字給 GUI runtime info。
- `maple_star/models/settings.py`
  - 新增巡航設定欄位與讀寫 migration。
  - 巡航設定屬於全域 UI/control state，不放入 profile payload。
- `maple_star/views/settings_gui.py`
  - 新增「小地圖巡航」區塊。
  - 新增啟停熱鍵、攻擊鍵、設定邊界按鈕、邊界狀態文字。
  - 設定邊界時暫停 action，沿用既有 key-capture/window-interaction guard。
- `maple_star/controllers/gamepad_controller.py`
  - 在主 GUI loop 建立並更新巡航 runtime。
  - 巡航不依賴手把事件；它只借用同一個主迴圈節奏與 foreground guard。
- `maple_star/adapters/win_input.py`
  - 若現有 API 不足，補小型 helper，例如 client/screen 座標轉換。
  - SendInput 邊界仍集中在 adapter。

## 設定模型

新增欄位：

- `minimap_cruise_toggle_hotkey: str | None`
- `minimap_cruise_attack_key: str`
- `minimap_cruise_left_x: int | None`
- `minimap_cruise_right_x: int | None`
- `minimap_cruise_detect_y: int | None`
- `minimap_cruise_detect_band_height: int`
- `minimap_cruise_last_direction: str`

預設值：

- `minimap_cruise_toggle_hotkey = None`
- `minimap_cruise_attack_key = "C"`
- 邊界與 Y 皆為 `None`
- `minimap_cruise_detect_band_height = 12`
- `minimap_cruise_last_direction = "right"`

保存規則：

- 邊界使用目標視窗 client-relative 座標。
- 左右界會正規化為 `left_x <= right_x`。
- 若沒有完整邊界，巡航不可啟動。
- 設定不寫入 profile payload，避免切換角色 profile 時意外改變巡航邊界。

## GUI

新增區塊「小地圖巡航」。內容維持緊湊：

- `啟停熱鍵`：可偵測單鍵，沿用現有 key capture 流程。
- `攻擊鍵`：可偵測單鍵，預設 `C`。
- `設定邊界`：按下後進入兩步驟滑鼠點擊流程。
- `邊界` 狀態：未設定、設定中、或 `X: 104-276 / Y: 205`。

邊界設定流程：

1. 使用者按「設定邊界」。
2. GUI 顯示「請點擊小地圖左邊界」。
3. 捕捉下一次滑鼠點擊，轉成目標視窗 client-relative 座標。
4. GUI 顯示「請點擊小地圖右邊界」。
5. 捕捉第二次滑鼠點擊，保存左、右 X 與平均 Y。
6. 結束設定流程並恢復 action。

若點擊時找不到目標視窗，或點擊位置不在目標 client area 內，GUI 顯示錯誤並要求重試。

## Runtime 狀態機

狀態：

- `stopped`：未啟用，沒有持有巡航按鍵。
- `starting`：熱鍵啟動後等待第一次偵測。
- `attacking`：持續按住攻擊鍵。
- `turning`：已放開攻擊鍵，準備短按方向鍵。
- `suspended`：失焦、HUD 不可用、快捷鍵設定中、或偵測失敗後暫停。

啟動條件：

- 巡航熱鍵已設定。
- 邊界完整。
- 攻擊鍵可解析。
- 目標遊戲視窗在前景。
- 總開關允許 action。
- GUI 沒有處於 key capture 或邊界設定流程。

初始方向：

- 第一次偵測到角色 X 後計算中線。
- `角色 X < 中線` 時往右。
- `角色 X > 中線` 時往左。
- 靠近中線時沿用 `minimap_cruise_last_direction`；若無效則用右。

更新節奏：

- 巡航 runtime 可每個 GUI loop tick 收到 `update(now)`。
- 角色位置偵測只在 `now >= next_detect_at` 時執行。
- `MINIMAP_CRUISE_DETECT_INTERVAL_SECONDS = 1.0`。
- 按鍵狀態只在啟動、停用、轉向、暫停、恢復時改變。

轉向流程：

1. 到左界且目前往左，或到右界且目前往右。
2. `key_up(attack_vk)`。
3. `tap_key(right_vk)` 或 `tap_key(left_vk)`。
4. 更新目前方向與 `minimap_cruise_last_direction`。
5. `key_down(attack_vk)`。

此流程不按住方向鍵，也不對攻擊鍵做高頻 reassert。

## 小地圖偵測

第一版使用顏色偵測，不使用 OCR。

輸入：

- 目標視窗 client bounds。
- 保存的 `left_x`、`right_x`、`detect_y`、`detect_band_height`。

擷取範圍：

- X 範圍使用 `[left_x - padding, right_x + padding]`。
- Y 範圍使用 `detect_y ± detect_band_height / 2`。
- padding 使用小常數，避免黃點半徑落在邊界外時被裁掉。

角色點偵測：

- 將截圖轉為 BGR/RGB array。
- 使用黃色 HSV 或 RGB 條件建立 mask。
- 進行簡單 morphology open/close。
- 用 connected components 找候選區。
- 過濾太小、太大、太扁、或離偵測帶中心太遠的元件。
- 取最佳元件中心 X，轉回 client-relative 座標。

邊界判斷：

- 使用角色點中心 X。
- 左界條件：`x <= left_x + tolerance`。
- 右界條件：`x >= right_x - tolerance`。
- `tolerance` 預設 2 至 4 client pixels，避免中心點抖動造成重複轉向。

## 失敗處理

- 偵測不到角色點：釋放攻擊鍵，進入 `suspended`，下次偵測再嘗試恢復。
- 連續偵測失敗：節流顯示「小地圖巡航：找不到角色點」。
- 視窗失焦：立即釋放攻擊鍵，保持巡航 enabled，但暫停 action。
- 總開關關閉或 emergency stop：停用巡航並釋放按鍵。
- 快捷鍵設定中或邊界設定中：停止巡航 action 並釋放按鍵。
- 攻擊鍵設定無效：不啟動，顯示狀態。
- 邊界缺失：不啟動，顯示「請先設定小地圖邊界」。

所有 key-up 失敗需記錄例外，但 runtime 狀態要保留可重試資訊，避免程式誤以為按鍵已釋放。

## 測試計畫

新增或擴充測試：

- `tests/test_settings_profiles.py`
  - 驗證巡航欄位 migration、保存與 profile 排除。
- `tests/test_settings_controller_buttons.py` 或新測試
  - 驗證 GUI apply_to_settings 會讀寫巡航熱鍵與攻擊鍵。
- `tests/test_gamepad_macro.py` 或新 `tests/test_minimap_cruise.py`
  - 未設定邊界不可啟動。
  - 攻擊鍵無效不可啟動。
  - 初始方向依角色位置決定。
  - 每秒偵測一次。
  - 到左界時依序 `key_up(attack) -> tap_key(right) -> key_down(attack)`。
  - 到右界時依序 `key_up(attack) -> tap_key(left) -> key_down(attack)`。
  - 停用、失焦、快捷鍵設定中會釋放攻擊鍵。
  - 偵測失敗會釋放攻擊鍵並暫停。
- `tests/test_auto_potion_foreground_guard.py`
  - 若主迴圈整合影響 `can_run_actions()` 或 emergency stop，補對應回歸測試。

最低驗證：

```powershell
python tools\verify.py
python -m unittest tests.test_gamepad_macro
python -m unittest tests.test_settings_profiles
```

若新增獨立測試檔，驗證命令需加入該檔。

## 實作順序

1. 新增 settings 欄位、讀寫、snapshot 與測試。
2. 新增 GUI 欄位與邊界設定流程。
3. 新增 `minimap_cruise.py` 服務與純單元測試。
4. 在 `gamepad_controller.py` 整合 runtime 建立、更新、狀態顯示與 emergency stop。
5. 補完整驗證，確認沒有本機設定或產物進入 git。

## 風險

- 小地圖背景也有大量黃色樹葉。第一版用 Y 偵測帶與 connected component 過濾降低誤判。
- 視窗縮放或小地圖位置改變後，保存的 client-relative 邊界可能失效。使用者可按「設定邊界」重設。
- 單次 `key_down(攻擊鍵)` 是否能被遊戲穩定視為 hold 需實測。若不穩，後續再加低頻 reassert，但第一版不預設加入。
- 轉向前必須確實釋放攻擊鍵。若 `key_up` 失敗，runtime 不應送方向鍵，避免狀態更亂。
