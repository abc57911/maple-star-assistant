# 自動巡航安全性、業務判斷與效能強化

> 知識庫索引：[../../INDEX.md](../../INDEX.md)

## 背景

自動巡航已具備邊界轉向、邊界前技能、原地位移技、週期按鍵、紅點通知與測謊暫停。現行直接相關測試皆通過，但輸入送出與內部狀態之間仍有時序缺口；部分業務判斷也會把未觀察時間或短距離震盪誤認為有效狀態。

本次強化限於單一楓之谷視窗。系統不支援也不處理多開自動切換；巡航始終綁定控制程序收到的目標 HWND。

## 目標

- 切換到其他程式後，不再送出新的巡航動作。
- 停止、失焦、測謊或例外時，可靠釋放巡航持有的按鍵。
- 防止攻擊、技能與週期鍵互相放開或遮蔽按下事件。
- 執行中更新設定時，立即套用一致的新狀態。
- 紅點通知只計算有效觀察時間。
- 回邊界判斷要求時間窗口內的淨進度，避免原地震盪。
- 拒絕無效邊界校正。
- 降低邊界技能與測謊辨識的重複影像處理成本。
- 保留既有邊界技能施放契約：攻擊鍵持續按住，技能鍵持續按住約 `2.0 秒`。

## 非目標

- 不支援多開楓之谷或自動切換巡航目標。
- 不調整邊界技能的 `2.0 秒`持有時間。
- 不改變原地位移技的 `0.8 秒`持有時間與 `0.2 秒`後搖。
- 不新增可調整的進階 GUI 參數。
- 不重構自動喝水、EXP OCR 或其他控制器的輸入架構。
- 不執行全套、`full`、`ocr-slow` 或 `performance` 驗證。

## 方案

採用巡航內部窄幅強化。`MinimapCruiseRuntime` 繼續擁有巡航狀態；控制程序提供精確前景判斷與低階輸入函式。這個方案不建立全專案通用輸入管理層，避免擴大到其他功能。

## 設計

### 1. 精確前景保護

`_is_target_hwnd_active()` 只接受目標 HWND、其 child window 或 owner chain。它不再以「同屬楓之谷視窗」作為替代條件。

巡航在每個會產生新輸入的動作前呼叫 `is_target_window_active`：

- 攻擊鍵與方向鍵 `key_down`。
- 邊界技能與原地位移技能 `key_down`。
- 週期短按的 `key_down`。
- recovery 或轉向階段的新按鍵。

檢查失敗時，runtime 進入既有 suspend 流程。清理用的 `key_up` 不受前景 guard 阻擋；即使使用者已切到其他程式，系統仍須放開先前按住的實體鍵。

目標 HWND 只由 `TargetWindowUpdated` 更新。前景出現其他視窗時，巡航等待原目標恢復焦點，不自動改綁。

巡航啟用期間收到 `TargetWindowUpdated` 時，控制程序先 suspend runtime、取消所有 deadline，並釋放舊鍵，再更新 target HWND。若釋放失敗，runtime 保持 suspended；pending release 清空後才能依新 HWND 恢復。

### 2. 巡航按鍵 ownership

runtime 以角色名稱追蹤持有鍵，包括 attack、turn、pre-boundary skill、stationary skill、recovery 與 periodic tap。所有按下及放開都通過內部 helper；helper 只有在低階輸入成功後才更新 ownership。

釋放失敗時：

1. 保留該鍵的 ownership。
2. 記錄待重試鍵。
3. 繼續嘗試釋放其他持有鍵，不讓單一例外中止 cleanup。
4. 設定 `pending_release_retry_at = now + 0.05 秒`；scheduler 即使在 stopped 或 suspended 狀態也納入這個 deadline。
5. 每 `0.05 秒`重試，成功後移除該鍵；pending release 清空前禁止任何新 `key_down`，也不得重新啟用巡航。
6. 一般 stop 不終止 retry；process shutdown 只執行最後一次 best-effort cleanup，並在失敗時回報 worker cleanup error。
7. 對外回報可診斷的狀態或錯誤訊息。

設定驗證拒絕無法正確表達的組合：

- 攻擊鍵不得與方向鍵、邊界技能鍵、原地位移技能鍵或任何啟用的週期鍵相同。
- 啟用的週期鍵彼此不得相同，也不得與方向鍵或任一技能鍵相同。
- 邊界技能與原地位移技能分屬互斥階段，可以使用同一鍵。

GUI 儲存時顯示聚焦錯誤。runtime 啟用時仍執行同一驗證，防止舊設定或手動修改的 `settings.json` 繞過 GUI。

### 3. 週期鍵改為非阻塞短按

現行 `tap_key` 同批送出 down/up，可能短到遊戲無法辨識。每個週期 slot 改用 deadline 狀態：

1. deadline 到達且前景有效時送出 `key_down`。
2. 保存 held VK 與 release deadline。
3. 固定短暫持有後送出 `key_up`。
4. stop、suspend、測謊或設定更新立即取消 deadline 並釋放按鍵。

短按不阻塞 scheduler，不使用 `sleep`。新增固定常數 `MINIMAP_CRUISE_PERIODIC_KEY_HOLD_SECONDS = 0.05`。release 條件使用 `now >= key_up_at`；截止點前不得放開。這與既有 jump staged input 的 `0.05 秒`一致，但巡航服務保有自己的常數，避免跨 controller 相依。

### 4. 執行中套用設定

新增 `MinimapCruiseRuntime.apply_settings(settings, now)`，取代控制程序直接替換 `runtime.settings`。

套用流程採 validate-before-commit 的原子交易：

1. 先驗證完整 candidate settings，不修改 runtime 或現行設定。
2. candidate 無效時拒絕整筆更新；runtime 繼續使用上一份有效設定，並回報具體原因。
3. candidate 有效時，記錄巡航是否啟用，取消 deadline，並釋放所有巡航持有鍵與 pending tap。
4. cleanup 成功後才替換完整 settings；接著清除舊週期排程、技能 deadline、停滯追蹤與 recovery 進度。
5. cleanup 產生 pending release 時，保存 candidate，但不提交、不恢復巡航，也不送出任何新 `key_down`。
6. pending release 清空後提交 candidate；先前啟用時，以新設定重建排程並恢復巡航。

這個 controlled restart 避免舊 VK 或舊 interval 在更新後再執行一次。

### 5. 邊界技能時序與辨識節流

邊界技能開始前，runtime 確認攻擊鍵已持有；接著按下技能鍵。整段 `2.0 秒`內同時維持攻擊鍵與技能鍵。

技能持有時間與小地圖取樣頻率分開：

- `pre_boundary_skill_key_up_at` 保持 `now + 2.0 秒`。
- 新增 `pre_boundary_probe_at`，每 `0.2 秒`才擷取一次角色位置；probe 只更新最後有效位置與超界觀察，不改變技能 deadline。
- scheduler deadline 納入下一次 probe 與技能 release deadline。
- probe 發現角色超界時仍繼續持有攻擊鍵與技能鍵。`now >= pre_boundary_skill_key_up_at` 後才放開技能鍵，再以當下擷取位置決定是否轉向；當下擷取或角色辨識失敗時直接 suspend，不依舊 probe 送出新方向鍵。
- stop、suspend、測謊或設定更新清除兩個 deadline 並釋放技能鍵。

節流只減少影像辨識次數，不縮短技能按壓，也不放開攻擊鍵。

### 6. 紅點有效觀察時間

紅點「連續 20 秒」定義為巡航具備有效前景、成功取得紅點 ROI，且每次觀察都判定紅點存在的累計時間。

- suspend、失焦、擷取失敗或巡航停用會清除 `red_player_present_since`。
- 紅點消失時清除計時。
- 恢復觀察後重新累計 20 秒。
- 通知送出後沿用既有去重或重複通知規則。

未觀察期間不算入連續時間。

### 7. 回邊界淨進度

recovery 不再只比較相鄰兩幀。runtime 保存 recovery 起點、目前最佳位置與連續無進度次數。沿用 `MINIMAP_CRUISE_OUT_OF_BOUNDS_RECOVERY_INTERVAL_SECONDS = 0.5`，並將 `MINIMAP_CRUISE_RECOVERY_STUCK_CONFIRMATIONS = 2` 定義為連續兩次取樣沒有刷新最佳位置。

- 從右側回界時，`character_x <= best_x - 1` 才算改善。
- 從左側回界時，`character_x >= best_x + 1` 才算改善。
- 改善時更新 best X，並把無進度次數清為 `0`。
- 未改善時把無進度次數加 `1`。
- 無進度次數達 `2` 時，沿用既有 fallback：放開攻擊鍵，按住朝邊界內側的方向鍵，直到角色回到有效邊界內；不再切換成遠離邊界的方向。
- `280 → 279 → 280 → 279` 只在第一次到達 `279` 時算進度，之後不會無限重設計時。

到達有效邊界內仍立即結束 recovery，不等待 progress deadline。

### 8. 邊界校正驗證

新增固定常數：

- `MINIMAP_CRUISE_MIN_BOUNDARY_WIDTH_PIXELS = 20`
- `MINIMAP_CRUISE_MAX_BOUNDARY_Y_DELTA_PIXELS = 30`

邊界座標皆為目標 client-relative，左、上界包含，右、下界不包含。設 client size 為 `client_width × client_height`，邊界必須符合：

- `0 <= left_x < right_x < client_width`。
- `right_x - left_x >= 20`；此值也大於兩側 `3 px` tolerance 的總和。
- `abs(first_y - second_y) <= 30`。
- `detect_y = round((first_y + second_y) / 2)`，且 `0 <= detect_y < client_height`。
- capture 可沿用既有 client bounds clamp，不要求完整 detect band 遠離視窗上下緣。

`left_x`、`right_x`、`detect_y` 全為 `None` 是合法的 dormant settings，其他設定仍可儲存及套用，但巡航不得啟用。三者只有部分為 `None` 是無效 candidate，整筆更新依 Section 4 拒絕。三者完整時才執行上述幾何驗證。

GUI 在儲存校正前驗證；runtime 啟用與 `apply_settings()` 再驗證一次。驗證失敗時保留上一組有效邊界，不啟動巡航，並要求重新校正。

### 9. 測謊模板快取

測謊辨識第一次載入模板時，同步建立各固定 scale 的 template 與 mask。後續辨識重用快取，只對當前畫面執行 `matchTemplate`。

快取以模板來源與 scale 集合為 key。測試可注入模板時，注入或重設會清除快取。這次不新增背景執行緒，也不改變辨識 threshold、scale 集合或通知語意。

### 10. 清理既有無效狀態

- 移除未參與判斷的 `forced_direction` 區域變數。
- 若 `consecutive_detection_failures` 仍採首次失敗即 suspend，移除無效累計欄位；若直接相依流程確實使用它，則保留並補上明確門檻。不得保留只增減、不影響決策的狀態。

## 錯誤處理

- 新動作前景檢查失敗：suspend，取消 deadline，best-effort 釋放全部持有鍵。
- `key_down` 失敗：不登記 ownership，停止本次動作並 suspend。
- `key_up` 失敗：保留 ownership 與 retry 資料，繼續清理其他鍵。
- 設定更新驗證失敗：拒絕 candidate、保留上一份有效設定與當前啟用狀態，並顯示具體衝突或校正錯誤。若使用者正在嘗試從停用狀態啟用巡航，則維持停用。
- 擷取或角色辨識失敗：沿用既有安全暫停，不送出新的移動或技能輸入。
- 測謊模板快取建立失敗：沿用目前的辨識失敗處理，不影響 cleanup。

## 影響範圍

- `maple_star/services/minimap_cruise.py`
  - 狀態機、按鍵 ownership、短按 deadline、設定套用、紅點與 recovery、辨識節流及模板快取。
- `maple_star/controllers/gamepad_controller.py`
  - 呼叫 `apply_settings()`、傳遞精確前景 guard、整合新增 deadline。
- `maple_star/services/runtime_processes.py`
  - 收緊目標 HWND 前景判斷。
- `maple_star/models/settings.py`
  - 可重用的巡航設定驗證與正規化。
- `maple_star/views/settings_gui.py`
  - 顯示按鍵衝突與邊界校正錯誤。
- `tests/test_minimap_cruise.py`
  - 狀態機、時序、cleanup、業務判斷及效能節流單元測試。
- 直接相關的 controller、foreground guard 與 settings 測試。

## 測試範圍

新增或更新以下案例：

- 切到非目標程式後不產生新 key-down，已持有鍵仍會 key-up。
- 每種 `key_up` 失敗都保留 retry ownership，且其他鍵仍完成清理。
- stopped 或 suspended 狀態仍每 `0.05 秒`重試 pending release；清空前拒絕重新啟用及所有新 `key_down`。
- `TargetWindowUpdated` 先取消 deadline 並清理舊鍵；pending release 清空後才允許使用新 HWND 恢復。
- 攻擊、技能、方向與週期鍵衝突會被 GUI 與 runtime 拒絕。
- 週期鍵依 deadline 執行 down/hold/up；stop 與失焦會取消並釋放。
- 設定更新不會送出舊 pending VK，並按新 interval 重建排程。
- 邊界技能全程維持攻擊鍵，技能鍵按滿約 `2.0 秒`。
- 邊界技能持有期間每 `0.2 秒`最多執行一次角色 probe。
- suspend 超過 20 秒後，紅點不會立即通知。
- recovery 震盪不會重複刷新淨進度期限，真正向內移動會刷新。
- 相同邊界點、寬度小於 `20 px`、Y 差大於 `30 px` 與超出 client bounds 會被拒絕。
- 測謊多次辨識只建立一次縮放模板快取，辨識結果維持一致。

只執行直接受影響的測試模組。程式狀態未改變時，不重跑已通過案例；不執行全套 profile。

## 驗收條件

- 使用者切到其他程式後，巡航不再按下任何新鍵。
- 所有停止路徑都能釋放或保留可重試的按鍵 ownership。
- 合法設定下，不會有一個巡航角色意外放開另一角色持有的鍵。
- 執行中設定更新後，不會再送出舊鍵。
- 邊界技能在攻擊持有狀態下連續按住技能鍵約 `2.0 秒`。
- 邊界技能期間的角色辨識頻率不高於正常 `0.2 秒`取樣節奏。
- 紅點通知只在有效觀察滿 20 秒後送出。
- 無淨進度的 recovery 震盪會進入既有 fallback。
- 無效邊界無法啟動巡航。
- 測謊辨識不再於每次呼叫重建全部縮放模板。
