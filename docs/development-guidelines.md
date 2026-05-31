# 開發規範

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## 本機與提交邊界
- `settings.json` 是使用者本機設定檔，應由程式自動建立或補齊。
- `settings.json` 不應提交，也不應打包進 release。
- `.venv*/`、`.paddleocr/`、根目錄 `/models/`、`build/`、`dist/`、`release/`、`*.spec` 都是本機或打包產物，不應提交。
- `.venv-paddleocr` 是可重建的本機 OCR 開發環境；需要時可刪除重建，但不得提交。
- `maple_star/models/` 是正式原始碼目錄，必須可追蹤，不可被視為模型 cache。
- `debug.log` 與 `experience_debug.log` 是本機診斷檔；每次 app 啟動會清空目前檔案與輪替備份，執行期間每個檔案達 1MB 會自動輪替並保留固定備份數，避免長時間執行時無限增長。
- 未經使用者明確要求，不要執行打包。
- 未經使用者明確要求，不要 commit。
- 使用者要求 commit 時，先確認 staged 清單不含本機設定、venv、model cache 或打包產物。
- 若 worktree 已有無關修改，只 stage 使用者要求範圍內的檔案；docs 更新不得順手捲入 runtime、fixture 或 release 產物。

## 實作位置
- 修改 `auto_potion.py` 時需保留向後相容匯出，避免破壞既有 import。
- 修改 `maple_gamepad_macro.py` 時需保留直接執行行為與既有 import API。
- 新增或調整自動喝水功能時，優先放在 `maple_star/controllers/`、`maple_star/services/`、`maple_star/models/`、`maple_star/views/` 或 `maple_star/adapters/` 的合適模組。
- 新增或調整共用常數時，優先放在 `maple_star/constants.py`，避免在 controller、GUI 或測試中散落 magic number。
- Win32 input、按鍵顯示名稱、SendInput key tap/down/up 等平台邊界應集中在 `maple_star/adapters/win_input.py`；controller 只保留流程狀態與 orchestration，不重複定義 ctypes 結構。
- 新增實作時不要把主要邏輯放回舊 facade；舊 facade 只負責 re-export 或 module alias。
- 調整舊公開 import path 時需保留相容性，例如 `from maple_star.controller import AutoPotionController`、`from maple_star.gui import AutoPotionSettingsGui`、`from maple_star.experience import ExperienceEfficiencyTracker`、`from maple_star.settings import AutoPotionSettings`。
- 新增長期可重用流程時，先判斷應放在 `services/`、`adapters/` 或 `models/`；`controllers/auto_potion_controller.py` 已很大，只應保留 orchestration 與狀態流程。
- GUI 文字狀態更新優先使用「值有變才 set」的 pattern，避免高頻 runtime status 造成 repaint 或 flicker。
- 使用 GDI / Win32 handle / MCI alias / worker thread/process 時，必須有 cleanup path，並在 `AutoPotionController.cleanup()` 或對應 stop/close helper 補釋放。

## 快捷鍵
- 快捷鍵設定目前設計為單鍵。
- 設定快捷鍵時必須暫時攔截腳本功能，避免按鍵設定動作同時觸發暫停、停止或經驗統計切換。
- 控制熱鍵事件應先通過 debounce 與 key-capture guard。
- 自動喝水、經驗統計、拾取、經驗統計重置與總開關的控制熱鍵必須要求楓星目標視窗或 maple-star app 自身在前景；若兩者都不在前景，必須靜默忽略，不得攔截按鍵、顯示提示、送鍵、播放切換音效或改變 enabled state。
- 長按停用自動喝水或拾取時，若按住期間楓星與 app 都失去前景，應取消該次停用動作並清除 pending hold。

## 設定與 profile
- `AutoPotionSettings` 的 `profiles` 只保存 potion/macro/EXP 功能設定。
- 控制熱鍵、拾取鍵、console collapse、combo group collapse、compact experience mode、window topmost 與視窗座標是全域 UI / control state，不應寫進單一 profile payload。
- 讀取舊 flat settings 時要自動 migration 到 `Default` profile，並可用 `load_settings(..., save_migrations=False)` 做不落盤測試。
- HP/MP cooldown 讀取時需 clamp 到 `POTION_MIN_COOLDOWN_SECONDS`，避免舊設定造成高頻送鍵。
- Controller button 名稱需經 `normalize_controller_button_name()`，接受 `right shoulder`、`dpad-left` 等 alias，未知值回 fallback。

## 記錄與診斷
- `debug.log` 與 `experience_debug.log` 使用 rotating log；目前 `debug.log` 單檔上限為 1MB，`experience_debug.log` 單檔上限為 5MB。
- App 啟動時 `main.py` / `main.pyw` 都應 reset `debug.log*` 與 `experience_debug.log*`，避免上一輪診斷污染。
- Experience debug 使用 JSONL event；新增 OCR / tracker / runtime 診斷時優先寫入 structured payload。
- GUI console 只保留有限行數與字元數；高頻或可重複訊息需節流，不應洗掉真正重要的 OCR / runtime 異常。
