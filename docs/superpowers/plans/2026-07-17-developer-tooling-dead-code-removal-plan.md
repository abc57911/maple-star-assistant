# 階段 1B：Developer Tooling 與 Dead Code 移除計畫

> Review findings：[2026-07-17 全專案 Code Review](../../reviews/2026-07-17-project-code-review.md)
>
> 前置階段：[Cleanup 與 Startup Reliability](2026-07-17-cleanup-startup-reliability-plan.md)

## 目的

移除已與 production 斷開的 EXP OCR learning 工具，以及 review 確認無 call site 的 controller/runtime dead code。保留一般使用者功能、82 個 OCR fixtures、generated Pixel templates、OCR regression、公開 import path、settings 與 IPC schema。

## Batch B1：低耦合 dead code

### 修改檔案與 symbol

- `maple_star/controllers/gamepad_controller.py`
  - 移除 `main()` 內無 call site 的 `sync_controller_button_bindings()`、`update_active_bindings()`、`any_combo_enabled()`、`ensure_controller_worker_state()`、`next_binding_deadline_at()`、`process_controller_events()`。
  - 移除只服務上述函式的 `all_button_bindings`、`controller_button_bindings`、`current_controller_button_settings` 與失去用途的 imports。
  - 將三個 macro class 的 `_parse_configured_key()` 合併為 module-level `_parse_configured_macro_key(name, key_name)`；保留各 caller 的錯誤文字與 VK 解析結果。
- `maple_star/services/runtime_processes.py`
  - 移除 no-op `_install_potion_console_recorder()` 及 call site。
  - potion status 排程不再檢查沒有 writer 的 `gui.console_lines`；`PotionStatus.console_lines` 欄位與 serialization 保留，值仍為空 tuple。
- `maple_star/models/experience.py`
  - 移除 repository 無 call site 的 `read_stat_window_exp_in_worker()`。
- `RELEASE_README.txt`
  - 移除不存在的 GUI learning review／promotion／dedupe 敘述。
- 測試：更新 `tests/test_gamepad_macro.py`、`tests/test_experience.py` 與 runtime tests，只移除已刪 dead helper 的直接測試，不刪行為 regression。

### 契約與 ownership

- `ControlCommand`／`ControlStatus`／`PotionStatus` schema 不變。
- control child process 繼續擁有所有 active macro bindings；parent 不重新建立 binding。
- module-level key parser 是 pure function，不持有 key、process、thread 或 GUI resource。
- B1 不改 OCR parser、Paddle fallback、Pixel template 或 capture ownership。

### 驗證

- `python -m unittest tests.test_gamepad_macro tests.test_runtime_cleanup tests.test_experience`
- `python tools\verify.py full`
- `rg` 確認上述 dead symbol 只剩計畫／review 歷史敘述。
- `git diff --check`

## Batch B2：EXP OCR learning 移除

### 刪除檔案

- `tools/experience_ocr_learning.py`
- `maple_star/services/experience_ocr_learning.py`

### 修改 production 檔案

- `maple_star/models/experience.py`
  - 移除 `experience_ocr_learning_pending_dir()`、`save_experience_ocr_learning_case()`、pending bundle writer、dedupe/hash/actionability helpers 與只服務 fixture generation/promotion 的 helpers。
  - 移除 `PaddleExperienceTextReader.read()`、burst/frame worker 與內部 reader 的 unused `record_learning` parameter 及所有 call arguments。
  - 保留 `ExperienceTextReading.learning_case_id` 相容欄位，production 永遠回傳空字串，避免既有 debug/IPC payload 欄位變動。
  - 保留 production text parser、ROI/image preprocessing、Paddle/Pixel readers、continuity hint 與 fixture regression loader。
- `maple_star/models/experience_pixel_templates.py`
  - 僅把檔頭改為 repository-maintained generated runtime data，不再指向已刪 CLI；template payload 不變。
- `tests/test_experience.py`
  - 刪除 pending writer、promotion、validation、auto-promotion、dedupe、fixture mutation 與 CLI/service 專用 tests。
  - 更新 reader/worker assertions，不再傳或檢查 `record_learning`。
  - 保留 82 fixtures regression、Paddle fallback、Pixel primary、continuity、tracker 與 parsing coverage。
- `tests/test_auto_potion_foreground_guard.py`
  - 保留既有 debug payload 的 `learning_case_id == ""` assertion，證明 IPC compatibility。

### 文件

- `docs/experience-ocr.md`：移除 pending／promotion／dedupe／regen CLI，明確說明 fixtures 與 generated templates 仍是保留的 regression/runtime assets。
- `docs/project-structure.md`：移除 learning service/tool，更新模型責任。
- `docs/installation.md`：移除 learning 工具安裝／維護敘述（若存在）。
- `docs/INDEX.md`：同步入口描述，不新增一般使用者 learning workflow。

### Public、資料與 ownership 邊界

- 保留 `maple_star.experience` import path 與所有 production OCR/tracker symbols。
- 刪除明確屬 developer tooling 的 learning service/module API；這是使用者已授權的相容性例外。
- 不讀、不寫、不搬移、不刪除 `%LOCALAPPDATA%\MapleStar\experience_ocr_pending` 既有資料。
- 不改 settings、runtime command/status dataclass、multiprocessing queue、capture、Paddle model cache 或 fixture manifest schema。

### 驗證

- `rg` 在 production、tools 與 active docs 中不再找到 `record_learning`、`experience_ocr_learning_pending_dir`、`save_experience_ocr_learning_case` 或 `services.experience_ocr_learning`。
- `python -m unittest tests.test_experience tests.test_auto_potion_foreground_guard`
- `python tools\verify.py full`
- `python tools\verify.py ocr-slow`，因 B2 修改 Paddle/Pixel reader signature 與 OCR model source。
- `git diff --check`

## Rollback

- B1 與 B2 是獨立 rollback 邊界；B1 全綠後才開始 B2。
- B2 內先刪專用 service/CLI/tests，再改 model call chain；任一 production OCR regression 失敗即整批撤回，不以修改 expected fixture 或刪 regression 通過。
- generated template payload 若產生任何 byte/AST data 差異，除檔頭外全部撤回。
- 不清除使用者 pending directory，不執行 fixture promotion、dedupe 或 regeneration。

## 完成條件

- B1 confirmed dead symbols 全數移除，control/runtime 行為測試與 full gate 通過。
- B2 developer learning code、CLI、runtime side effect 與專用 tests 全數移除，保留 fixture/Paddle/Pixel regression。
- settings、IPC dataclass 與 public production import smoke 無差異。
- 記錄刪除 LOC、測試數與 full/ocr-slow 驗證結果，交由獨立 code review 通過。

## Batch B1 完成紀錄

- `read_stat_window_exp_in_worker()` 經獨立 review 證實是 dynamic facade 公開 symbol，已從 B1 刪除清單撤回；延後到階段 3 建立 symbol manifest 後處理。
- Targeted：221 tests，OK，2 skipped。
- Full：691 tests，OK，1 skipped，58.7 秒。
- `git diff --check`：通過，僅 Git 的 LF／CRLF 提示。
- 獨立 code review：修復 1 個 facade compatibility finding 後 Approved；Critical、Important、Minor 均無 confirmed finding。
- 此紀錄建立當下 Batch B2 尚未開始；後續完成狀態如下節。

## Batch B2 完成紀錄

- 刪除 `maple_star/services/experience_ocr_learning.py` 962 行與 `tools/experience_ocr_learning.py` 185 行。
- 移除 model pending writer/helpers、unused `record_learning` parameter/calls 與 learning-only tests；B2 合計約刪 2,704 行、增 52 行。
- 保留 82 個 fixtures、Pixel template payload、`learning_case_id` 相容欄位，以及 PP-OCRv5／legacy language constructor regression。
- Targeted：458 tests，OK，2 skipped。
- Full：662 tests，OK，1 skipped，56.6 秒。
- OCR slow：662 tests，OK，62.2 秒；Paddle venv `pip check` 無 broken requirements。
- Active source／tests／tools／docs 已無 learning API、CLI 或 pending path 引用；既有使用者 pending 資料未讀取、搬移或刪除。
- 獨立 code review：恢復兩個誤刪的 Paddle constructor tests 後 Approved；Critical、Important、Minor 均無 confirmed finding。
