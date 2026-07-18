# 全 App 最大效能實作計畫 2：Backend Supervisor 與生命週期

> 知識庫索引：[../../INDEX.md](../../INDEX.md)  
> 設計：[全 App 最大效能架構重構](../specs/2026-07-18-full-app-performance-architecture-design.md)  
> 前置：[計畫 1：Baseline、契約與可行性](2026-07-18-full-performance-plan-1-foundation.md)

## 目標

建立 backend supervisor、worker registry、health policy、設定 transaction、parent-death cleanup 與 Qt-neutral client contract。此階段仍由 legacy GUI 驅動，domain business logic暫時包裝現有 worker。

## Entry gate

- Plan 1 Exit gate 全部通過。
- IPC schema、settings v2 mapping、public API manifest與 preview transport決策已凍結。
- 工作樹沒有未知 runtime 修改；先記錄 baseline tests與 benchmark artifact。

## 批次 1：Supervisor state machine 與 worker registry

### 檔案

- 新增 `maple_star/backend/__init__.py`。
- 新增 `maple_star/backend/supervisor.py`、`worker_registry.py`、`states.py`、`health.py`。
- 新增 `maple_star/backend/worker_ports.py`。
- 新增 `tests/test_backend_supervisor.py`、`tests/test_worker_registry.py`、`tests/test_worker_health.py`。

### 步驟

1. 先以 fake processes 鎖定 `CREATED/STARTING/READY/DEGRADED/FAILED/STOPPING/STOPPED`。
2. Registry 保存 PID、creation time、session、incarnation、ready、heartbeat、progress、restart budget與queue metrics。
3. Worker restart只重播 committed settings、target與停用狀態；不重播 action、held key或 backlog。
4. 套用 Plan 1 health policy 表，實作 phase deadline、三次 restart budget與 `0.5/2/10 s` backoff。
5. Guardian/scheduler failure先以 fake safety port標記 fatal；真實 guardian留到 Plan 3。

### 驗證

```powershell
python -m unittest tests.test_backend_supervisor tests.test_worker_registry tests.test_worker_health
```

## 批次 2：Prepare／Stage／Activate 設定 transaction

### 檔案

- 新增 `maple_star/backend/settings_transactions.py`。
- 擴充 `maple_star/ipc/messages.py` 的 transaction messages。
- 更新 `maple_star/services/settings_store.py`，加入 pending journal 與 committed atomic replace seam。
- 新增 `tests/test_settings_transactions.py`、`tests/test_settings_store_atomicity.py`。

### 步驟

1. 先測 prepare reject、timeout、worker crash、stage 部分 ack、disk replace失敗與activate部分ack。
2. Candidate先寫 `settings.pending.<transaction_id>.json`，不得作啟動 truth。
3. Worker stage後保持inactive；正式 `settings.json` atomic replace成功後才activate。
4. Supervisor crash測試需證明新session只讀 committed record，所有feature預設停用。
5. Migration失敗保留原檔與最近三份backup，不得回寫空白預設。
6. Legacy GUI adapter只在 transaction committed後更新顯示狀態。

### 驗證

```powershell
python -m unittest tests.test_settings_transactions tests.test_settings_store_atomicity tests.test_settings_profiles
```

## 批次 3：Client transport、snapshot 與 Console backpressure

### 檔案

- 新增 `maple_star/backend/client_port.py`、`snapshot_aggregator.py`。
- 新增 `maple_star/ipc/client_transport.py`、`urgent_events.py`。
- 新增 `tests/test_backend_client_transport.py`、`tests/test_snapshot_aggregator.py`、`tests/test_urgent_events.py`。

### 步驟

1. GUI inbound/outbound使用兩條transport；main-thread-facing API只能non-blocking enqueue。
2. Snapshot按session/incarnation/sequence過濾，相同signature不重送。
3. Console採bounded ring，overflow保留dropped count；fatal error交付失敗時worker進failed state。
4. Telegram/media事件不可阻塞supervisor snapshot loop。
5. 建立 Qt-neutral fake client，讓 legacy GUI與tests不 import PySide6。

### 驗證

```powershell
python -m unittest tests.test_backend_client_transport tests.test_snapshot_aggregator tests.test_urgent_events
```

## 批次 4：Parent-death、Worker Job 與 ordered shutdown

### 檔案

- 新增 `maple_star/backend/windows_job.py`、`parent_lease.py`、`shutdown.py`。
- 新增 `tests/test_parent_lease.py`、`tests/test_windows_job.py`、`tests/test_backend_shutdown.py`。
- 更新 `maple_star/controllers/auto_potion_runtime_composition.py`，加入新 supervisor adapter。

### 步驟

1. 以可注入 Win32 port 測試 Worker Job只有supervisor持有handle，且不包含guardian role。
2. Parent lease監聽GUI pipe EOF、launcher handle與心跳；任一失效都進全域stop。
3. Shutdown順序固定：停止新command、fake safety release ack、停domain workers、關transport、確認child退出。
4. 單一步驟失敗仍執行後續 cleanup；每個join有deadline。
5. Windows真實process smoke驗證GUI host被終止後沒有舊domain child；Plan 3再驗證guardian獨立release。

### 驗證

```powershell
python -m unittest tests.test_parent_lease tests.test_windows_job tests.test_backend_shutdown tests.test_runtime_cleanup
```

## 批次 5：Legacy adapter production 接線

### 檔案

- 更新 `maple_star/services/runtime_processes.py` 與 `runtime_api.py`，保留舊公開契約的adapter。
- 更新 `maple_star/controllers/runtime_child_entrypoints.py`、`auto_potion_runtime_composition.py`。
- 更新 `tests/test_runtime_composition.py`、`test_stage4_controller_contracts.py`、`test_auto_potion_foreground_guard.py` 的直接 contract cases。

### 步驟

1. Legacy GUI/controller透過adapter啟動supervisor；現有domain worker logic保持不變。
2. 舊`RuntimeProcessCoordinator`保留為rollback adapter，但同一次run只能啟動一種coordinator。
3. 驗證settings、target、enable、status、worker crash與cleanup對legacy consumer語意不變。
4. 收集新supervisor與舊coordinator的status latency、CPU與working set比較。
5. 若新adapter未達correctness或health gate，production composition切回舊coordinator，不進Plan 3。

### 驗證

```powershell
python -m unittest tests.test_runtime_composition tests.test_stage4_controller_contracts tests.test_runtime_cleanup
python -m unittest tests.test_auto_potion_foreground_guard.AutoPotionForegroundGuardTests.test_stale_runtime_potion_status_restarts_potion_process
```

## Exit gate

- Startup/restart/health/transaction/orphan/shutdown state machines有直接tests。
- Legacy GUI全部功能仍可使用；supervisor不載入GUI toolkit。
- GUI host crash會終止domain workers；沒有orphan process。
- Settings candidate在任一crash點都不會誤成committed truth。
- 新supervisor latency/CPU/working set有raw比較，未出現無界queue。

## Rollback

- Composition root切回舊`RuntimeProcessCoordinator` adapter。
- Disk reader在Plan 4 cutover前維持舊schema與v2雙讀；不得回寫無法被rollback版本讀取的唯一設定檔。
- Rollback前停止新supervisor並確認所有child已退出。
