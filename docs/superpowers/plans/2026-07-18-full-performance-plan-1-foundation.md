# 全 App 最大效能實作計畫 1：Baseline、契約與可行性

> 知識庫索引：[../../INDEX.md](../../INDEX.md)  
> 設計：[全 App 最大效能架構重構](../specs/2026-07-18-full-app-performance-architecture-design.md)

## 目標

建立後續重構所需的 truth：功能 parity、公開 API、settings v2 mapping、效能 baseline、IPC identity 與 Windows frozen-process 可行性。本計畫不切換 production entrypoint，也不改變現有 runtime ownership。

## Entry gate

- `git status --short` 只含已知文件變更。
- 記錄 `git rev-parse HEAD`、Python 版本、Windows build、電源模式與硬體。
- 現有 App 可從 `main.py` 啟動並正常關閉。
- 先執行直接相關 baseline tests，不預設跑 `full`。

## 批次 1：功能與效能 baseline

### 檔案

- 修改 `tools/benchmark_gui_startup.py`、`tools/benchmark_gui_latency.py`、`tools/benchmark_control_timing.py`，只補 marker、raw JSON 與環境 metadata。
- 新增 `tools/benchmark_runtime_pipeline.py`，量測 status、capture、OCR、potion intent 模擬路徑與 queue latency。
- 新增 `docs/reviews/2026-07-18-full-performance-baseline.md`。
- 新增 `docs/reviews/artifacts/full-performance-plan-1/` 下的精簡 JSON 結果。

### 步驟

1. 先以測試鎖定現有 benchmark CLI 與 JSON schema。
2. 定義 `first_visible_shell`、`main_ready`、GUI latency、scheduler deadline、preview serialization 與 process working-set marker。
3. 在相同電源模式執行 Python baseline；EXE baseline 只在使用者明確允許打包或提供既有 artifact 時執行。
4. 保存 raw samples、median、p95、p99、maximum 與環境 metadata。
5. 報告需分清楚「已量測」、「尚未量測」與「不適用」，不得用 unit test 推論效能。

### 驗證

```powershell
python -m unittest tests.test_control_scheduler tests.test_gui_page_builders
python tools\benchmark_control_timing.py --duration 5
```

## 批次 2：公開 API 與 settings v2 mapping

### 檔案

- 更新 `tests/public_facade_manifest.py`，加入逐 symbol 分類：保留、Qt re-export、guardian IPC proxy、移除候選。
- 新增 `tests/full_performance_settings_manifest.py`。
- 新增 `docs/reviews/2026-07-18-settings-v2-mapping.md`。
- 先新增 `maple_star/models/settings_v2.py` 與 `maple_star/models/settings_migrations.py` 的純 model／migration prototype，不接 production loader。
- 新增 `tests/test_settings_v2_migrations.py`。

### 步驟

1. 由現行 `AutoPotionSettings.to_json_dict()`、`GLOBAL_SETTING_KEYS`、profiles 與 fixtures 產生欄位 inventory。
2. 為每個欄位指定 v2 path、型別、預設值、global/profile ownership、normalizer 與未知欄位政策。
3. 建立 root `schema_version/global/profiles/selected_profile/extensions/migration` model。
4. 以 copy-on-write migration 實作舊 flat、現行 profile schema與 settings v2 的 round trip。
5. 任一 profile 失敗時整筆 migration 失敗；測試不得寫入真正 `settings.json`。
6. 掃描 `auto_potion.py`、`maple_star.win_input` 等 facade 的低階 input exports 與 repository consumers，固定 Plan 3 cutover policy。

### 驗證

```powershell
python -m unittest tests.test_settings_profiles tests.test_settings_v2_migrations tests.test_public_facades
```

## 批次 3：IPC identity、message 與 bounded transport

### 檔案

- 新增 `maple_star/ipc/__init__.py`。
- 新增 `maple_star/ipc/identity.py`：session epoch、worker role、incarnation、stream sequence。
- 新增 `maple_star/ipc/messages.py`：只放 immutable、spawn-safe dataclasses。
- 新增 `maple_star/ipc/mailbox.py`：latest-wins、bounded FIFO、priority safety transport fake。
- 新增 `maple_star/ipc/serialization.py`。
- 新增 `tests/test_ipc_identity.py`、`tests/test_ipc_mailbox.py`、`tests/test_ipc_messages.py`。

### 步驟

1. 先寫 stale session、stale incarnation、sequence reset 與 generation ordering tests。
2. 實作 messages，不 import controller、GUI、capture handle 或 native toolkit。
3. latest-wins mailbox 飽和時替換舊 snapshot；action FIFO 飽和時拒絕並回報 metric。
4. Safety protocol 只先建立 fake contract；production pipe/event 留到 Plan 2/3。
5. 以 Windows `spawn` round trip 驗證每種 message 可 pickle，且 child import graph 不載入 Qt、Tk、Paddle或 pygame。

### 驗證

```powershell
python -m unittest tests.test_ipc_identity tests.test_ipc_mailbox tests.test_ipc_messages tests.test_runtime_composition
```

## 批次 4：Preview transport 決策 spike

### 檔案

- 新增 `maple_star/ipc/preview_transport.py` 的 Protocol、serialized implementation 與測試 fake。
- 新增 `tools/benchmark_preview_transport.py`。
- 新增 `tests/test_preview_transport.py`。
- 更新 baseline review，記錄 shared-memory decision。

### 步驟

1. 使用實際 HP/MP ROI、preview 尺寸與更新 cadence 測量 bytes serialization/copy。
2. 建立 shared-memory spike：session/incarnation 命名、雙 slot、seqlock、checksum、consumer deep copy。
3. 測試 producer restart、consumer crash、GUI crash 模擬及 stale segment registry。
4. 只有 serialized p95 `> 2 ms` 或 CPU占比 `>= 5%`，且 shared-memory p95 改善 `>= 30%` 時，才選 shared memory。
5. Spike 未達門檻就刪除 production shared-memory implementation，只保留 decision report與serialized path。

### 驗證

```powershell
python -m unittest tests.test_preview_transport
python tools\benchmark_preview_transport.py
```

## 批次 5：Windows／PyInstaller child-role feasibility

### 檔案

- 新增 `maple_star/app/child_roles.py` 與 top-level no-op role targets。
- 新增 `tests/test_child_role_spawn.py`、`tests/test_child_import_isolation.py`。
- 更新 `main.py`、`main.pyw` 僅在不改現有啟動語意的前提下集中 `freeze_support()` seam。
- 新增 `tools/verify_child_role_artifact.py`；打包規則留到 Plan 4。

### 步驟

1. 測試 child role 不取得 GUI singleton lock、不建立 GUI、不重設主 log、不遞迴 spawn。
2. 驗證 top-level target、resource resolver、source／frozen path 與 lazy imports。
3. 驗證 supervisor role可建立 non-daemon no-op child並有序 join。
4. 若使用者允許 feasibility artifact，建立最小 onedir spike；否則將 EXE gate標為待 Plan 4 執行，不宣稱通過。

### 驗證

```powershell
python -m unittest tests.test_child_role_spawn tests.test_child_import_isolation tests.test_startup_error_handling
```

## Exit gate

- Baseline report含 raw evidence與未執行項目。
- 公開 API manifest與 settings v2逐欄 mapping完整。
- IPC identity/message/mailbox通過 Windows spawn round trip。
- Preview transport有明確、可重現的選擇結論。
- Health policy 表可由 baseline填入，不含任意「稍後再定」值。
- Production runtime ownership、GUI與入口仍維持現況。

## Rollback

- 新 IPC、settings v2與 child-role prototype尚未接 production；可移除新增 modules/tests/reviews。
- `main.py`／`main.pyw` 若只新增 seam，回退該 seam 後應與 baseline 行為一致。
- 不修改或覆蓋使用者 `settings.json`。
