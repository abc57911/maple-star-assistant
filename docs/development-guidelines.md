# 開發規範

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## 本機與提交邊界
- `settings.json` 是使用者本機設定檔，應由程式自動建立或補齊。
- `settings.json` 不應提交，也不應打包進 release。
- `.venv*/`、`.paddleocr/`、根目錄 `/models/`、`build/`、`dist/`、`release/`、`*.spec` 都是本機或打包產物，不應提交。
- `.venv-paddleocr` 是可重建的本機 OCR 開發環境；需要時可刪除重建，但不得提交。
- `maple_star/models/` 是正式原始碼目錄，必須可追蹤，不可被視為模型 cache。
- `debug.log` 與 `experience_debug.log` 是本機診斷檔，程式會自動輪替保留固定備份數，避免長時間執行時無限增長。
- 未經使用者明確要求，不要執行打包。
- 未經使用者明確要求，不要 commit。
- 使用者要求 commit 時，先確認 staged 清單不含本機設定、venv、model cache 或打包產物。

## 實作位置
- 修改 `auto_potion.py` 時需保留向後相容匯出，避免破壞既有 import。
- 修改 `maple_gamepad_macro.py` 時需保留直接執行行為與既有 import API。
- 新增或調整自動喝水功能時，優先放在 `maple_star/controllers/`、`maple_star/services/`、`maple_star/models/`、`maple_star/views/` 或 `maple_star/adapters/` 的合適模組。
- 新增或調整共用常數時，優先放在 `maple_star/constants.py`，避免在 controller、GUI 或測試中散落 magic number。
- Win32 input、按鍵顯示名稱、SendInput key tap/down/up 等平台邊界應集中在 `maple_star/adapters/win_input.py`；controller 只保留流程狀態與 orchestration，不重複定義 ctypes 結構。
- 新增實作時不要把主要邏輯放回舊 facade；舊 facade 只負責 re-export 或 module alias。
- 調整舊公開 import path 時需保留相容性，例如 `from maple_star.controller import AutoPotionController`、`from maple_star.gui import AutoPotionSettingsGui`、`from maple_star.experience import ExperienceEfficiencyTracker`、`from maple_star.settings import AutoPotionSettings`。

## 快捷鍵
- 快捷鍵設定目前設計為單鍵。
- 設定快捷鍵時必須暫時攔截腳本功能，避免按鍵設定動作同時觸發暫停、停止或經驗統計切換。
