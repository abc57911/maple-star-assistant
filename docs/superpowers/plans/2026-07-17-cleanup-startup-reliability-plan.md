# 階段 1A：Cleanup 與 Startup Reliability 實作計畫

> Review findings：[2026-07-17 全專案 Code Review](../../reviews/2026-07-17-project-code-review.md)
>
> 設計規格：[全專案 Code Review 與減肥設計](../specs/2026-07-17-project-slimming-design.md)

## 目的

修復 review 的 I1–I3，讓 child process、主 controller 與桌面入口在例外路徑仍保留原始錯誤，並完成其所擁有資源的 best-effort cleanup。本批不移除功能、不改設定、不改 IPC，也不開始 OCR learning 刪碼。

## 修改檔案

- `main.pyw`：將啟動失敗的標準庫 traceback 寫入與專案 logger 解耦。
- `maple_star/services/runtime_processes.py`：將 potion／experience child controller cleanup 移入 `finally`。
- `maple_star/controllers/auto_potion_controller.py`：將 cleanup 拆成具名、隔離失敗且只執行一次的步驟。
- `maple_star/controllers/gamepad_controller.py`：隔離父程序 finally 中彼此獨立的 cleanup owner。
- 新增 `tests/test_runtime_cleanup.py`：child entrypoint 與 controller cleanup regression tests。
- 新增 `tests/test_startup_error_handling.py`：以 subprocess 驗證 logging import 失敗時保留原始 traceback。
- 更新 `docs/reviews/2026-07-17-project-code-review.md`：完成後標記 I1–I3 的處置與驗證證據。
- 更新 `docs/INDEX.md`：加入本計畫入口。

## Public surface 與資料契約

- facade/re-export：不新增、不移除、不更名任何 public symbol。
- constructor/method：`AutoPotionController.cleanup() -> None` signature 不變；語意加強為 best-effort、可重複呼叫，且不向 caller 傳出 cleanup step exception。
- child entrypoint signature：`_run_potion_runtime_process()`、`_run_experience_stats_process()` 不變。
- IPC：`WorkerCrashed`、`PotionStatus`、`ExperienceStatus` 欄位與 queue 語意不變；原始 runtime exception 仍決定 `WorkerCrashed.message`。
- startup：`main.pyw` 仍在失敗時重新拋出原始 exception，並寫入同路徑 `startup_error.log`。

## Ownership 與錯誤傳遞

- potion child 擁有 child-local `AutoPotionController`；無論 constructor 後的 command、update、status serialization 或 queue 操作何處失敗，都先 best-effort 釋放 potion keys，再呼叫 controller cleanup。
- experience child 擁有 child-local `AutoPotionController`；無論 loop 何處失敗，都先 best-effort 取消 baseline calibration，再呼叫 controller cleanup。
- cleanup 自身失敗只記錄，不取代原始 runtime exception，也不阻止其他 cleanup step。
- `AutoPotionController.cleanup()` 依序處理：輸入鍵、runtime processes、hotkey workers、mouse observer、media、capture、executor、settings、MSS、GUI、stdout/stderr。每個 owner 是獨立 step。
- Controller 由 partial-safe factory 先取得 object ownership 再執行 `__init__`；初始化未完成時 cleanup 不得儲存 settings。
- `RuntimeProcessCoordinator` 自己負責 partial start rollback；queue、control signal、join、inspect、terminate 與 final join 分別隔離。
- controller cleanup 完成後設置內部完成狀態；後續呼叫直接返回，避免重複關閉 handle、executor、GUI 或重新寫設定。
- `gamepad_controller.main()` 的父程序 finally 分別執行 control release、parent-known key release、auto-potion cleanup、Telegram listener cleanup 與 controller worker cleanup；任何一步失敗只輸出具名錯誤。
- `main.pyw` 先用 `traceback.format_exc()` 捕捉原始內容，再用 `Path.write_text()` best-effort 寫檔；專案 logger 只有在 import 成功時才呼叫。

## 實作步驟

1. 先新增失敗測試：child `update()` 拋錯時 cleanup 仍執行；cleanup 第一個 step 拋錯時後續 owner 仍關閉；第二次 cleanup 不重複執行；logging import 拋指定錯誤時 subprocess stderr 與 `startup_error.log` 都保留該錯誤。
2. 在 runtime process entrypoint 使用初始化為 `None` 的 controller reference 與 `finally`；cleanup helper 各自捕捉並記錄 release/cancel/cleanup failure。
3. 在 `AutoPotionController` 增加小型 cleanup-step runner；不得以單一廣泛 `except: pass` 包住整段，也不得改變正常 cleanup 順序。
4. 將 controller 所擁有的可重複資源 reference 在 step 完成邊界清空，並以完成旗標保護重複呼叫。
5. 將父程序 finally 的獨立 owner 隔離，保留目前先要求 control release、再釋放 parent-known keys 的順序。
6. 修改 `main.pyw` 啟動錯誤處理，確保 logger import、logger 呼叫與 error-file 寫入任一失敗都不遮蔽原始 exception。
7. 更新 review 處置狀態與驗證結果；不在本批混入 dead code removal。

## Targeted tests

- `python -m unittest tests.test_runtime_cleanup tests.test_startup_error_handling`
- child tests 使用 fake local controller 與 in-memory queue，不建立 multiprocessing process、不送 Win32 input。
- controller tests 以 `AutoPotionController.__new__()` 建立最小 owner graph，所有外部 resource 都使用 mock，不啟動 GUI、thread、process、MSS 或 executor。
- startup test 在 temporary directory 執行 `main.pyw` copy，提供 import 時故意拋錯的 fake `maple_star.debug_logging`，比對 subprocess return code、stderr 與 log file。

## 完整驗證 gate

- `python -m unittest tests.test_runtime_cleanup tests.test_startup_error_handling`
- `python tools\verify.py full`
- `git diff --check`
- 本批不改 OCR 辨識、GUI layout 或 hot path，因此不需 `ocr-slow` 與 performance profile。

## Rollback 邊界

- Batch A：tests 與 `main.pyw` startup handler，可獨立撤回。
- Batch B：runtime child `finally` cleanup，可獨立撤回。
- Batch C：controller 與父程序 best-effort cleanup，若 characterization test 發現順序或 ownership 改變，只撤回本 batch。
- 任一 batch 若讓原始 exception 被 cleanup exception 取代、改變 IPC payload、或造成正常關閉失敗，即停止階段 1A；不得以吞例外或刪測試通過 gate。

## 完成條件

- I1–I3 都有失敗前會紅、修改後會綠的 regression coverage。
- child 與父程序 cleanup failure 不會遮蔽原始 runtime exception。
- controller cleanup 中任一 step 失敗時，其餘 owner 仍完成 cleanup，第二次呼叫沒有重複 side effect。
- full gate 通過，且 public import、settings 與 IPC schema 無差異。

## 完成紀錄

- Targeted：14 tests，OK。
- Full：691 tests，OK，1 skipped，61.3 秒。
- `git diff --check`：通過，僅 Git 的 LF／CRLF 提示。
- 獨立 code review：第三輪 Approved；Critical、Important、Minor 均無 confirmed finding。
