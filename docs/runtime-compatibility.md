# Runtime 相容性注意事項

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## GUI 與視窗
- GUI 需能在遊戲切換前景、拖曳視窗、中文輸入法啟用時維持穩定。
- 遊戲視窗辨識應優先使用較精準的視窗條件與可恢復的 hwnd cache；不要只依賴容易撞名的標題字串。
- 刷新 HP/MP 預覽時可短暫將遊戲視窗置頂並等待畫面穩定後再截圖。
- 若偵測失敗，不要更新既有範圍或預覽圖。
- Runtime info 顯示需要節流，目前 GUI 主迴圈只需約每 0.25 秒刷新一次前景、狀態與 held keys。
- 狀態文字若內容未變，不應重複寫入 `StringVar`；runtime child process 也應用 status signature 去重，避免 GUI repaint 壓力。
- Toggle notice 是輔助視窗，顯示前需套用 background toolwindow style，位置以目標遊戲 client 中心為主，失敗才回螢幕中心並 clamp 到可視範圍。
- Compact experience mode 與 full panel 都有獨立位置；Windows minimized sentinel `(-32000, -32000)` 或不可見座標不可保存。

## 偵測環境
- 自動喝水偵測需考慮視窗模式。
- 需考慮 Windows DPI scaling。
- 需考慮非 16:9 遊戲視窗。
- 需考慮地圖切換漸暗 / 漸亮過場。
- 需考慮切換頻道 loading 畫面。
- 控制熱鍵只允許在楓星遊戲或 maple-star app 自身為前景時啟停自動喝水、拾取、經驗統計、重置 EXP 或切換總開關；其他前景視窗必須靜默忽略，不得攔截按鍵、顯示提示或改變 enabled state。
- 啟停熱鍵的長按確認若中途離開楓星遊戲與 app 前景，要取消 pending disable，避免使用者切窗時誤停功能。

## HP/MP/EXP ROI
- HP/MP 條與 EXP OCR 範圍需能隨遊戲視窗縮放或重開自動重新定位。
- 不要依賴固定預設座標。
- 底部 HUD 定位優先使用 `HP.` / `MP.` / `EXP.` label 的 multi-scale template matching，再用紅/藍/綠條色彩驗證；label 失敗時才回到舊的色條配對 fallback。
- 沿用 cached/stale HP/MP ROI 前，需確認 HP/MP 成對幾何合理且兩條都能通過取色驗證；不可只因其中一條成功就沿用整組舊座標。
- HP/MP 自動喝水前需允許短暫偵測失敗重試。
- 實際送鍵前需做 confirm capture，確認失敗時可用相近的 unchecked fallback，但差異過大時必須放棄送鍵。
- 道具 tooltip 或其他浮動 UI 遮住 HP/MP ROI 時，讀值應視為不確定並略過自動喝水；不可把深色 tooltip 面板誤當成 0% 空條。
- HP/MP 條不穩定 log 需節流，避免偵測抖動時洗掉 GUI Console 內真正重要的 OCR 與異常樣本資訊。
- HP/MP 已有 cached HUD geometry 時，用 direct GDI capture 對 HP/MP track 做同一張 union capture，再裁成各 bar，減少 screenshot 壓力。
- screenshot、label 與 template matching 只能用來定位 HP/MP 座標與 HUD 幾何；自動喝水的 HP/MP 百分比讀值必須 direct-only。
- direct bar capture 失敗或 geometry 不可信時，可先用 screenshot 重新定位；定位後仍只能再走 direct 讀值，仍失敗就視為不確定、略過本輪喝水。
- direct 連續失敗需節流警告 GUI status、toggle notice 與 console log，不得用 screenshot crop 百分比替代。
- direct bar capture context 會重用 DC、bitmap 與 buffer；修改此路徑時必須確認 resize、failure 與 cleanup 都釋放 GDI resources。
- `require_clear_tail=True` 的送鍵前確認也維持 direct-only；direct 無法做 screenshot tail 驗證時，以 direct 百分比與 fallback delta 做保守確認。
- Experience-only runtime 不應為了 EXP 統計每 tick 擷取 HP/MP；只有缺 HUD cache、下一次 EXP OCR/baseline/checkpoint 到期，或 HUD geometry 失效時才刷新 HUD。

## Runtime process
- 主 process 負責 GUI 與 controller input；potion runtime 與 experience runtime 由 `RuntimeProcessCoordinator` 管理。
- 子程序 command 包含 settings、target hwnd、feature enable/pause、release-all 與 shutdown；新增 command field 時需同步 dataclass、handler 與測試。
- 子程序 status 需包含 generation；GUI 端收到舊 generation 或功能已關閉後的 status 時不得覆蓋目前畫面。
- potion status 的 signature 不包含 transient notice / console lines；這兩者需作 urgent delivery，但不應讓核心狀態去重失效。
- experience status signature 需追蹤 snapshot 的 EXP、percent、EXP-10、rates、ETA、elapsed、OCR/sample success rate、status 與 generation。
- worker crash 時應停用對應功能並回報 GUI；potion status heartbeat 用於判斷 runtime 是否 stale。
