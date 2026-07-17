# 2026-07-17 全專案 Code Review

> 知識庫索引：[docs/INDEX.md](../INDEX.md)
>
> 執行計畫：[第一階段全專案 Code Review Gate](../superpowers/plans/2026-07-17-project-review-phase-1-plan.md)

## 結論

- Critical：0。
- Important：6。前三項屬 cleanup／startup reliability，應在大規模拆檔前修正。
- Minor：5 組。可與 OCR learning 移除及 controller 拆分一併處理。
- `python tools\verify.py full` baseline 通過：677 tests、1 skipped、48.823 秒。
- 目前沒有本機 `release/MapleStar.zip`，ZIP baseline 留到已授權的第二階段建立。
- 階段 1A 已完成 I1–I3：修改後 full gate 為 691 tests、1 skipped、61.3 秒；獨立 code review 第三輪 Approved。

## Baseline

| 指標 | 結果 |
|---|---:|
| HEAD | `ba9b440c2d1ce366cb8f4ea2dae434e289972a78` |
| 與 `origin/main` | ahead 1、behind 0 |
| tracked Python LOC | 42,869 |
| production LOC，不含 generated | 25,654 |
| tests LOC | 15,388 |
| tools LOC | 590 |
| generated Pixel templates LOC | 1,237 |
| tracked repository bytes | 4,888,784 |
| OCR fixtures | 82 files、1,016,236 bytes |
| `AutoPotionController` | 7,279 lines、368 methods、`__init__` 寫入 145 個 attributes |
| `AutoPotionSettingsGui` | 3,603 lines、169 methods、`__init__` 寫入 164 個 attributes |
| `ExperienceEfficiencyTracker` | 1,127 lines、55 methods |
| `MinimapCruiseRuntime` | 1,095 lines、67 methods |

`.venv-paddleocr` 最大 top-level packages：

| Package | Version | Size |
|---|---:|---:|
| paddle | 3.2.2 | 370.55 MB |
| OpenCV | 4.10.0.84 | 121.02 MB |
| pandas | 3.0.2 | 41.10 MB |
| numpy + numpy.libs | 2.3.5 | 44.16 MB |
| pygame-ce | 2.5.7 | 22.57 MB |
| modelscope | 1.36.3 | 22.14 MB |
| Pillow | 12.2.0 | 14.64 MB |
| PaddleX | 3.5.1 | 10.25 MB |

`pip check` 回報 `No broken requirements found`。PowerShell cp950 顯示 `pip show` metadata 時會因套件作者名稱產生 encoding logging error，因此版本改由 `importlib.metadata.version()` 讀取。

## Important findings

### I1. Potion／EXP child process 只在正常離開時 cleanup

**狀態：已於階段 1A 解決。** Child controller 改由 partial-safe factory 建立，release／cancel／cleanup 固定於 `finally`，crash logger 與 queue reporting 也各自隔離。

- 證據：`maple_star/services/runtime_processes.py` 的 `_run_potion_runtime_process()` 與 `_run_experience_stats_process()` 把 release／cancel／`controller.cleanup()` 放在 `try` 尾端；`controller.update()`、status serialization 或 queue 操作拋例外時，流程直接進入外層 `except`。
- 影響：Potion process 可能在 injected key 仍為 down 時崩潰；EXP process 可能未取消 calibration、未還原 cursor／capture resource。父程序雖會收到 `WorkerCrashed`，但 child cleanup 已錯過。
- 處置：階段 1A。以 `controller: AutoPotionController | None` 搭配 `finally` 做 best-effort release/cancel/cleanup；保留原始 crash status。
- 驗證：新增 child entrypoint exception tests，證明 update 失敗後仍依序呼叫 release/cancel 與 cleanup。

### I2. `AutoPotionController.cleanup()` 任一步失敗會中止後續釋放

**狀態：已於階段 1A 解決。** Controller cleanup 改為具名、可重試失敗 step 的 best-effort 流程；父程序從取得第一個 owner 起即註冊 lifecycle cleanup，`RuntimeProcessCoordinator` 亦處理 partial start 與逐 process stop。

- 證據：`maple_star/controllers/auto_potion_controller.py:7593` 起依序呼叫 pickup release、potion release、runtime stop、hotkey unregister、worker stop、mouse observer、media、capture、executor、settings、MSS 與 GUI；前半段多數沒有隔離例外。
- 影響：例如第一個 `key_up`、runtime stop 或 worker stop 失敗，後續 process、thread、MCI alias、GDI/MSS 與 stdout restoration 都不執行。`gamepad_controller.main()` 的 `finally` 又先呼叫 `auto_potion.cleanup()`，Telegram listener 與 controller worker cleanup 可能一併被跳過。
- 處置：階段 1A。將 cleanup 拆成具名、可觀測的 best-effort steps；每步記錄錯誤，最後仍完成其餘釋放。不得用單一廣泛 `except: pass` 包住整段。
- 驗證：注入各 cleanup step failure，確認後續步驟仍執行，並確認 cleanup 可重複呼叫。

### I3. `main.pyw` 的啟動錯誤 handler 可能遮蔽原始例外

**狀態：已於階段 1A 解決。** `startup_error.log` 改由標準庫先保存原始 traceback，專案 logger 與檔案寫入失敗均不取代原始 exception。

- 證據：`main.pyw:10-17` 在 `try` 內才 import `log_exception`；若 `maple_star.debug_logging` import 本身失敗，`except` 於第 21 行再次引用尚未綁定的 `log_exception`。
- 影響：真正的 startup exception 被 `UnboundLocalError` 取代，`startup_error.log` 也可能無法寫出。
- 處置：階段 1A。錯誤 handler 不依賴可能失敗的專案 import；先以標準庫寫 traceback，再 best-effort 呼叫 logger。
- 驗證：subprocess/import-failure test 比對原始 traceback 與 startup error file。

### I4. 相容 facade 暴露整個實作模組，public surface 無法界定

- 證據：`maple_star.controller` 與 `maple_star.experience` 以 `sys.modules[__name__] = _implementation` 取代 facade；`maple_star.gui`、`settings` 等使用 wildcard import。import smoke 顯示 controller、experience、gui 分別暴露 251、200、164 個非底線名稱，包含第三方 module、內部 constants 與 implementation helpers。
- 影響：任何內部刪碼都可能被視為外部 API break；facade 也無法提供穩定、最小的 `__all__` 契約。
- 處置：階段 3／4。先從 entrypoints、tests、docs 建立 compatibility symbol manifest，再改為明確 re-export；舊 import path 保留。
- 驗證：manifest-driven import smoke，逐 symbol 比對 identity 或 callable contract。

### I5. Controller 與 runtime service 存在循環依賴

- 證據：AST import graph 找到唯一 strongly connected component：`maple_star.controllers.auto_potion_controller` <-> `maple_star.services.runtime_processes`。service 透過 child entrypoint 內 local import controller 避開 import-time crash。
- 影響：service 無法獨立理解或測試；拆 controller 時容易把 multiprocessing bootstrap、GUI protocol 與 runtime ownership再度耦合。
- 處置：階段 4。將 child process composition root 移到 controller/runtime entrypoint 層，service 只保留 IPC models、coordinator 與明確 factory/protocol。
- 驗證：import graph 無 cycle；spawn child smoke 與 IPC serialization tests 通過。

### I6. Release 說明宣稱不存在的 GUI learning 功能

**狀態：已於階段 1B／B1 解決。** 已移除錯誤的 release 使用者說明；未新增替代 GUI workflow。

- 證據：`RELEASE_README.txt:15` 宣稱 learning cases 可從 GUI review、promote、dedupe；目前 GUI 沒有 learning 入口，`docs/experience-ocr.md` 也說 runtime pending 寫入已停用、工具只供離線維護。
- 影響：發行包 README 誤導一般使用者，且與 `docs/release.md` 的禁止條款衝突。
- 處置：階段 1B，移除該行並同步 OCR／installation／structure 文件。
- 驗證：`rg` 不再找到使用者可見 learning workflow 敘述。

## Minor findings

### M1. Control process 移轉後留下未使用的 parent-side helper

**狀態：已於階段 1B／B1 解決。** 六個 nested helper 與三個空 compatibility containers 已移除；active control child 邏輯保留。

- `gamepad_controller.main()` 內的 `sync_controller_button_bindings()`、`update_active_bindings()`、`any_combo_enabled()`、`ensure_controller_worker_state()`、`next_binding_deadline_at()`、`process_controller_events()` 沒有 call site。
- `all_button_bindings`、`controller_button_bindings`、`current_controller_button_settings` 只服務上述死路徑。
- 處置：階段 1B 移除；保留實際 control child process 的 binding 邏輯。

### M2. 三個 macro class 重複相同 key parser

**狀態：已於階段 1B／B1 解決。** 合併為 module-level pure helper，錯誤文字與解析邊界不變。

- `gamepad_controller.py:317`、`:460`、`:645` 的 `_parse_configured_key()` body 完全相同。
- 處置：階段 1B 抽成 module-level helper，傳入 macro name；不新增 inheritance hierarchy。

### M3. Potion console recorder 是無行為 wrapper

**狀態：已於階段 1B／B1 解決。** No-op recorder 與無 writer 的 urgent precheck 已移除；IPC `console_lines` 欄位保留。

- `runtime_processes._install_potion_console_recorder()` 只呼叫原 method，從未 append `HeadlessRuntimeGui.console_lines`；該 list 在 production potion runtime 沒有 writer。
- 處置：階段 1B 移除 no-op wrapper 與不可能成立的 `gui.console_lines` urgent branch；IPC `PotionStatus.console_lines` 暫時保留相容。

### M4. OCR learning code 已與 production 行為斷開，但仍佔用 API 與程式體積

**狀態：已於階段 1B／B2 解決。** 已移除 962 行 service、185 行 CLI、model pending writer/helpers、unused `record_learning` call chain 與 29 個 learning-only tests；保留 82 fixtures、Pixel template payload、Paddle constructor regression 及 `learning_case_id` IPC 相容欄位。

- `PaddleExperienceTextReader.read()` 接受 `record_learning` 卻不讀取此參數；runtime 沒有 `save_experience_ocr_learning_case()` call site。
- `experience.py` 仍保留 pending writer、fixture template generator；另有 962 行 service 與 185 行 CLI。
- 處置：階段 1B 移除 unused parameter、pending writer、developer service/CLI 與專用 tests；保留 runtime templates、82 個 fixtures 與 OCR regression。

### M5. 已確認的孤立 symbol 與巨型 test class

- `read_stat_window_exp_in_worker()` 在 repository 只有定義，沒有 call site；可於階段 1B 移除。
- `test_auto_potion_foreground_guard.py` 與 `test_experience.py` 分別為 6,847 與 3,975 行，單一 test class 分別為 6,761 與 3,901 行。
- 處置：孤立 symbol 直接移除；測試只拆檔與抽共用 fixture/helper，不刪 regression coverage，也不以測試檔行數作 production 減肥成果。
- B1 複查結果：`read_stat_window_exp_in_worker()` 雖無內部 call site，但由 dynamic facade 公開，因此已恢復並延後到階段 3 symbol manifest 後決定；巨型測試拆分亦尚未執行。

## Package 與 dependency findings

- `build_release.bat:61-63` 同時 `--collect-all paddleocr`、`paddle`、`paddlex`，是第二階段主要體積候選。
- `requirements.txt` 只有 CustomTkinter、OpenCV、Paddle、PaddleOCR 完全 pin；pygame-ce、Pillow、mss、numpy 使用 range，PaddleX 與其他 transitive packages 未 lock。
- GitHub release 使用 `windows-latest`、Python `3.11` 與每次重新 resolve 的 requirements；不同日期的 ZIP 內容與體積可能漂移。
- 處置：第二階段先建立 artifact baseline 與 PyInstaller analysis，再精簡 collect；同時產生可重現 lock/constraints，不在未驗證前任意移除 OCR extras。

### 階段 2A baseline

- 環境：Python 3.11.2、PyInstaller 6.21.0、PaddlePaddle 3.2.2、PaddleOCR 3.5.0、PaddleX 3.5.1、OpenCV 4.10.0.84、NumPy 2.3.5。
- `release/MapleStar.zip`：244,516,678 bytes，SHA256 `CB7377EDD7B1D8788D14F470FB33055FB2EACB1B905B77A2552C790BCF40065E`。
- ZIP：6,838 entries、669,419,588 uncompressed bytes；含 EXE/README，無 settings/spec/forbidden prefix。
- `dist/MapleStar/_internal`：626,211,213 bytes；主要為 Paddle 369,734,166、OpenCV 116,231,880、NumPy libs 20,978,768、PIL 13,370,368、pandas 13,096,084 bytes。
- PyInstaller analysis 明確掃入 Paddle distributed/fleet/quantization、PaddleOCR doc2md、PaddleX serving/repo APIs、ModelScope 與 pandas 等非 EXP OCR 路徑。
- 15% 目標：修改後 ZIP 不得高於 207,839,176 bytes。

### 階段 2B package slimming

- 新增 artifact-side OCR smoke；只有 EXE 內 production PaddleOCR 完成初始化、實際 predict 並讀出 `3796880 / 99.08%` 才通過。
- 移除 Paddle、PaddleOCR、PaddleX 的無界 `collect-all`；只保留 hidden imports、`mklml.dll`、PaddleX `OCR.yaml` 與既有 metadata。
- 排除未使用的 `Crypto`、`hf_xet`，並從 artifact 移除未使用的 OpenCV videoio FFmpeg DLL。
- `pypdfium2`、Shapely 排除實驗均由 artifact smoke 證明會破壞 PaddleOCR 初始化，因此已回退，未以 stub 掩蓋。
- 最終 `release/MapleStar.zip`：212,265,463 bytes，SHA256 `3F3434C4079FE973431AAFBE213CEFDC7039736796D55AF9AE8D9D0CF977B144`；較 2A baseline 減少 32,251,215 bytes（13.19%）。
- 15% 目標尚差 4,426,287 bytes。剩餘主要瓶頸為 Paddle runtime 及 PaddleX 啟動期硬載入的 pandas、PDF、Shapely、ModelScope；繼續排除需改寫第三方 initializer 或提供假 module，風險不符本階段邊界。
- 新增 `requirements-release-lock.txt` 固定本次 Windows/Python 3.11 build environment；日常直接依賴仍以 `requirements.txt` 為準。
- 最終驗證：no-download artifact OCR smoke 通過；`python tools\verify.py full` 為 668 tests、OK、63.0 秒；`python tools\verify.py ocr-slow` 為 668 tests、OK、73.2 秒，`pip check` 無 broken requirements。
- Stage 2B 獨立 code review 複查 smoke trigger、no-download、failure diagnostics 與 release lock 後 Approved，無剩餘 actionable finding。

## Reviewed areas without confirmed defects

- settings migration、profile/global 分界與 controller button normalization。
- control scheduler 的 absolute deadline 與 bounded timing samples。
- minimap cruise state machine、staged key release 與 challenge pause contract。
- controller event queue saturation 時的 `EVENT_RELEASE_ALL` reconciliation。
- Telegram sender/listener 的 bounded queue 與 background network boundary。
- Win32 input/window adapters、window style 與 key capture 的平台邊界。
- rotating debug/experience/Telegram logs 與 handler replacement。
- OCR Pixel primary、Paddle fallback、continuity guard 與保留 fixtures。

以上代表本次靜態、call-site 與測試 review 沒有形成 confirmed finding；不代表 Windows 遊戲實機行為已由本次 review 重新驗證。

## 後續執行順序

1. 階段 1A：修復 I1–I3，先建立可靠 cleanup 與 startup failure boundary。
2. 階段 1B：移除 OCR learning、M1–M4 死碼、修正 I6 文件，整理 tests。
3. 階段 2：建立 baseline ZIP、artifact-side Paddle smoke、精簡 PyInstaller 與 dependency lock。
4. 階段 3：拆 experience／GUI，建立明確 facade export manifest。
5. 階段 4：拆 AutoPotionController、解除 runtime cycle，再處理其餘巨型 state。

## 可重現命令

```powershell
python tools\verify.py full
git ls-files '*.py'
git status --short --branch
git rev-parse HEAD
git rev-list --left-right --count origin/main...HEAD
& .venv-paddleocr\Scripts\python.exe -m pip check
```

LOC、AST 與 package size 使用第一階段計畫「量測邊界」定義；generated template 與 model cache 明確分開計算。

階段 1A 驗證：

```powershell
python -m unittest tests.test_runtime_cleanup tests.test_startup_error_handling
# 14 tests，OK
python tools\verify.py full
# 691 tests，OK (skipped=1)，61.3 秒
git diff --check
```

階段 1B／B2 驗證：

```powershell
python -m unittest tests.test_experience tests.test_auto_potion_foreground_guard
# 458 tests，OK (skipped=2)
python tools\verify.py full
# 662 tests，OK (skipped=1)，56.6 秒
python tools\verify.py ocr-slow
# 662 tests，OK，62.2 秒；pip check 無 broken requirements
```

B2 production/test/docs/tool 合計刪除約 2,704 行、增加約 52 行；獨立 code review 修復兩個誤刪的 Paddle constructor regression 後 Approved。
