# 全 App 最大效能實作計畫 3：Input Guardian 與領域 Workers

> 知識庫索引：[../../INDEX.md](../../INDEX.md)  
> 設計：[全 App 最大效能架構重構](../specs/2026-07-18-full-app-performance-architecture-design.md)  
> 前置：[計畫 2：Backend Supervisor 與生命週期](2026-07-18-full-performance-plan-2-supervisor.md)

## 目標

集中所有低階輸入副作用、拆分 realtime scheduler 與 guardian，並逐一 cutover potion、EXP、notification workers。此計畫保留 legacy GUI，但 production automation改由新 backend ownership執行。

## Entry gate

- Plan 2 Exit gate 全部通過。
- Supervisor/transaction/parent-death schema凍結。
- Input facade manifest、低階 adapter consumers與現行 held-key cleanup tests已盤點。

## 批次 1：Input guardian 與 write-ahead ownership ledger

### 檔案

- 新增 `maple_star/workers/input_guardian.py`。
- 新增 `maple_star/adapters/guardian_win_input.py`，由現行 `adapters/win_input.py` 抽取唯一mutation implementation。
- 新增 `maple_star/services/input_ownership.py`、`cursor_lease.py`。
- 擴充 `maple_star/ipc/messages.py`：`InputCommand`、ack、checkpoint、SafetyFence、Rearm、terminal stop。
- 新增 `tests/test_input_guardian.py`、`tests/test_input_ownership.py`、`tests/test_cursor_lease.py`、`tests/test_input_import_boundaries.py`。

### 步驟

1. 先以fake input adapter測key-down前`may_be_held` ledger ack、成功後confirmed、key-up後clear。
2. Guardian state實作`ARMED/BLOCKING/RELEASING/SAFE/REARMING`；terminal event永不clear。
3. Safety generation嚴格遞增；舊Rearm不得越過新fence。
4. Guardian crash時，supervisor先確認舊PID退出，再啟動emergency-release-only incarnation。
5. Cursor lease記錄原位置、move ack、timeout、OCR crash與terminal restore。
6. 靜態contract只允許guardian role import mutation adapter；其他facade改proxy或依manifest移除unsafe symbol。

### 驗證

```powershell
python -m unittest tests.test_input_guardian tests.test_input_ownership tests.test_cursor_lease tests.test_input_import_boundaries tests.test_win_input
```

## 批次 2：Realtime scheduler、pygame 與 hotkey adapters

### 檔案

- 新增 `maple_star/workers/realtime_scheduler.py`。
- 新增 `maple_star/services/device_poll_adapter.py`、`hotkey_poll_adapter.py`。
- 遷移／包裝 `maple_star/controllers/gamepad_controller.py`、`services/minimap_cruise.py`、`services/control_hotkey_coordinator.py`。
- 更新 `services/runtime_processes.py` 與 `controllers/runtime_child_entrypoints.py`。
- 新增 `tests/test_realtime_scheduler.py`、`tests/test_device_poll_adapter.py`、`tests/test_realtime_guardian_integration.py`。

### 步驟

1. Scheduler只產生`InputCommand`，不得import低階mutation adapter。
2. pygame polling與hotkey polling各在adapter thread，透過bounded latest-state mailbox交給scheduler。
3. Emergency-stop hotkey先取消scheduler deadline，再建立可恢復SafetyFence。
4. 巡航、組合、週期鍵與recovery deadline沿用現有業務契約；過期事件不補發。
5. Target/settings generation切換前先fence/release，commit後才rearm。
6. 將input process設為Above Normal；不使用realtime priority或固定affinity。

### 驗證

```powershell
python -m unittest tests.test_realtime_scheduler tests.test_device_poll_adapter tests.test_realtime_guardian_integration
python -m unittest tests.test_control_scheduler tests.test_minimap_cruise tests.test_gamepad_macro tests.test_control_hotkey_coordinator tests.test_control_hotkey_worker
python tools\benchmark_control_timing.py --duration 5
```

## 批次 3：Potion vision intent cutover

### 檔案

- 新增 `maple_star/workers/potion_vision.py`、`maple_star/models/potion_intent.py`。
- 更新 `maple_star/services/potion_engine.py`、`potion_action_worker.py`、`hud_bar_detector.py`。
- 更新 `controllers/auto_potion_controller.py` 的orchestration shim，不保留直接送鍵。
- 新增 `tests/test_potion_intent.py`、`tests/test_potion_worker_process.py`、`tests/test_potion_guardian_integration.py`。

### 步驟

1. Potion worker只擷取、判讀、confirm並產生帶expiry/session/generation的intent。
2. Scheduler驗證feature/target/generation/deadline；guardian再驗證foreground/ownership後送鍵。
3. Intent queue滿或過期時drop並計metric，不補送。
4. 將potion heartbeat與work-loop progress分離，加入phase timing log。
5. 模擬capture超過舊2秒門檻但progress合法；不得重啟worker。
6. 套用Plan 1選定的preview transport，不無條件導入shared memory。

### 驗證

```powershell
python -m unittest tests.test_potion_intent tests.test_potion_worker_process tests.test_potion_guardian_integration
python -m unittest tests.test_potion_engine tests.test_hud_bar_detector tests.test_auto_potion_foreground_guard
```

## 批次 4：Experience OCR、cursor transaction 與 notification/media

### 檔案

- 新增 `maple_star/workers/experience_ocr.py`、`notification_media.py`。
- 更新 `services/experience_capture_coordinator.py`，cursor mutation改走lease port。
- 更新 `services/telegram_bot.py`、`media_playback.py`。
- 新增 `tests/test_experience_worker_runtime.py`、`tests/test_notification_media_worker.py`、`tests/test_cursor_guardian_integration.py`。

### 步驟

1. OCR process擁有capture、Pixel/Paddle與read-only cursor query；cursor mutation由guardian lease完成。
2. OCR crash、timeout、使用者移動cursor與session stop都恢復cursor並釋放lease。
3. Notification/media worker採priority event；一般重複事件合併，錯誤delivery失敗轉worker failed state。
4. Telegram與音效不得反向阻塞scheduler、potion或supervisor snapshot。
5. 子程序import isolation禁止Qt/Tk，guardian禁止Paddle/pygame。

### 驗證

```powershell
python -m unittest tests.test_experience_worker_runtime tests.test_cursor_guardian_integration tests.test_notification_media_worker
python -m unittest tests.test_experience_worker_spawn tests.test_experience_capture_coordinator tests.test_telegram_bot tests.test_media_playback
```

## 批次 5：Production backend cutover 與混合負載

### 檔案

- 更新 `controllers/auto_potion_runtime_composition.py`、`gamepad_controller.py` 與app composition seam。
- 更新直接相關runtime contracts與benchmark tools。
- 新增 `tests/test_full_backend_integration.py`、`tests/test_backend_chaos.py`。

### 步驟

1. 同一次run只允許新backend或舊adapter，不能雙重送鍵。
2. Legacy GUI透過client adapter操作新backend；全部domain snapshot回GUI。
3. Chaos測guardian/scheduler/domain crash、queue滿、heartbeat delay、settings transaction與GUI host loss。
4. 執行十分鐘synthetic混合負載，保存deadline lateness、intent latency、queue depth、CPU與working set。
5. p99 scheduler lateness需`<= 5 ms`，key-up/release-all零遺失；否則不進Plan 4。

### 驗證

```powershell
python -m unittest tests.test_full_backend_integration tests.test_backend_chaos tests.test_runtime_cleanup
python tools\benchmark_runtime_pipeline.py --duration 600
```

## Exit gate

- Guardian role是唯一keyboard/controller/cursor mutation writer；任一時刻最多一個incarnation。
- Guardian/scheduler crash後自動化保持停用，release與cursor restore完成。
- Potion長工作不再被heartbeat誤判；無restart loop。
- OCR、Telegram與media負載不阻塞scheduler。
- Legacy GUI可操作全部新backend功能，且混合負載gate通過。

## Rollback

- 每個domain以adapter分批切回舊worker；切換前必須fence、release並確認舊owner退出。
- 不允許在同一session混用新舊input writer。
- 若guardian cutover失敗，整個production composition回到Plan 2最後通過點，不只局部繞過guardian。
