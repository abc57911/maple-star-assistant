# Stage 4：AutoPotionController 拆分實作計畫

> 設計規格：[Stage 4 AutoPotionController 拆分設計](../specs/2026-07-17-stage-4-auto-potion-controller-decomposition-design.md)

## 目標

以契約 manifest、唯一 resource owner 與單向 import graph 為邊界，分九批拆分 `maple_star/controllers/auto_potion_controller.py`。每批先補 characterization tests，再移動單一責任；controller 保留 orchestration、runtime coordination、GUI publish、shared state 與 cleanup 排程。

## 全程邊界

- 不改 settings/IPC schema、GUI layout、OCR 判讀、喝水 threshold、timing、status 或 foreground guard 語意。
- 保留 `maple_star.controller` module alias identity、公開 import path、canonical object identity 與 manifest 列出的 private patch seams。
- Domain collaborator 不 import controller、GUI 或 concrete runtime coordinator；HUD、Potion、EXP 彼此不互調。
- MSS、GDI、MCI、worker、thread、process、executor 各只有一個 owner；borrowed port 不得由 borrower 關閉。
- 搬移 state 時不得建立雙寫 bridge；同一批完成 owner 切換與舊 owner 移除。
- 只修具穩定重現測試的窄 bug；其他問題記入 final review，不混入結構重構。
- 任一批失敗只回退該批。未經使用者明確要求，不 commit、push、build、tag 或 release。

## Task 0：Baseline、manifest 與 leaf contracts

### 檔案

- 新增 `maple_star/services/controller_collaborator_api.py`
- 新增 `tests/stage4_controller_manifest.py`
- 新增 `tests/test_stage4_controller_contracts.py`
- 新增 `docs/reviews/2026-07-17-stage-4-baseline.md`
- 修改 `tests/public_facade_manifest.py`
- 修改 `tests/test_public_facades.py`
- 修改 `docs/INDEX.md`

### 步驟

1. 記錄 controller LOC、method/field 數、`self.sct.grab()` call sites、resource owners、runtime import graph 與 performance baseline。
2. 以 AST 與明確 allowlist 建立 public/private/patch-point manifest；每個 symbol 分類為 dynamic adapter、controller shim 或 canonical re-export。
3. 定義 frozen `ControllerModuleAdapters` 與 `RuntimeMediaSink` Protocol；leaf module 只依賴 stdlib typing/dataclass/pathlib。
4. 寫 standalone import、無 controller/concrete service import、Protocol shape 與 facade identity tests。
5. 此批不改 controller production behavior，也不建立任何資源。

### 驗證

```powershell
python -m unittest tests.test_stage4_controller_contracts tests.test_public_facades
python tools\verify.py full
git diff --check
```

### Rollback

刪除 leaf contracts、manifest、tests 與 baseline索引；production code 不需還原。

## Task 1：Runtime composition 與 child entrypoints

### 檔案

- 新增 `maple_star/services/runtime_api.py`
- 新增 `maple_star/controllers/auto_potion_factory.py`
- 新增 `maple_star/controllers/auto_potion_runtime_composition.py`
- 新增 `maple_star/controllers/runtime_child_entrypoints.py`
- 新增 `tests/test_runtime_composition.py`
- 修改 `maple_star/services/runtime_processes.py`
- 修改 `maple_star/controllers/auto_potion_controller.py`
- 修改 `maple_star/controllers/gamepad_controller.py`
- 修改 `tests/test_control_scheduler.py`
- 修改 `tests/test_runtime_cleanup.py`
- 修改 `tests/test_gamepad_macro.py`
- 修改 `tests/test_public_facades.py`

### 步驟

1. 先固定所有 IPC dataclasses、`InlineExecutor`、status signature helpers 與 factory object identity。
2. 將上述 symbols 移至 `runtime_api.py`，舊 module/controller facade re-export同一 object。
3. 定義完整 `RuntimeProcessPort`，涵蓋 potion、experience、control child 的 start/send/drain/alive/restart/stop surface及現有 defaults。
4. 將 canonical `_create_auto_potion_controller` 移至 factory；保留 controller舊symbol identity與partial-constructor cleanup。
5. Concrete coordinator接受module-level spawn targets；child entrypoints以call-time import factory建立controller。
6. 新增keyword-only `runtime_process_factory`與`media_sink`；未傳入時維持standalone constructor既有行為。
7. Child以queue/no-op media sink取代instance monkey-patch。
8. Gamepad改走controller control-runtime forwarding methods；`runtime_processes`保留同一port的compatibility alias。
9. 驗證clean interpreter任意import順序、Windows spawn round-trip、Protocol conformance、bounded queue、generation filtering與cleanup。

### 驗證

```powershell
python -m unittest tests.test_runtime_composition tests.test_control_scheduler tests.test_runtime_cleanup tests.test_gamepad_macro tests.test_public_facades
python tools\verify.py full
python tools\verify.py performance
git diff --check
```

### Rollback

一次性恢復controller-local factory、concrete coordinator import與runtime child entries；刪除新runtime modules，不保留兩套composition wiring。

## Task 2：MediaPlaybackService

### 檔案

- 新增 `maple_star/services/media_playback.py`
- 新增 `tests/test_media_playback.py`
- 修改 `maple_star/controllers/auto_potion_controller.py`
- 修改 `tests/test_auto_potion_foreground_guard.py`
- 修改 `tests/test_runtime_composition.py`
- 修改 `tests/stage4_controller_manifest.py`

### 步驟

1. 先固定 preload、MCI open/play/volume/reopen/close、beep fallback、alert thread及failure behavior。
2. Controller建立dynamic adapters；所有callables在呼叫當下解析controller module globals。
3. 移動MCI aliases、buffer、preload與alert thread至service；controller `_play_*`/`_preload_*`/`_close_*`保留薄shim。
4. `media_sink=None`使用本機MCI/winsound；有sink時不建立本機資源，只轉送intent。
5. 驗證舊 `maple_star.controller.ctypes/winsound/threading` patch paths仍能攔截。
6. Cleanup只呼叫service `close()`一次，borrowed sink不由service關閉。

### 驗證

```powershell
python -m unittest tests.test_media_playback tests.test_auto_potion_foreground_guard tests.test_runtime_composition tests.test_public_facades tests.test_runtime_cleanup
python tools\verify.py full
git diff --check
```

### Rollback

Controller重新取得MCI aliases與alert thread ownership；刪除service wiring，禁止兩者同時close alias。

## Task 3：ControlHotkeyCoordinator

### 檔案

- 新增 `maple_star/services/control_hotkey_coordinator.py`
- 新增 `tests/test_control_hotkey_coordinator.py`
- 修改 `maple_star/controllers/auto_potion_controller.py`
- 修改 `tests/test_control_hotkey_worker.py`
- 修改 `tests/test_auto_potion_foreground_guard.py`
- 修改 `tests/stage4_controller_manifest.py`

### 步驟

1. 固定registration fallback、polling、foreground/capture guard、hold-to-disable、debounce、down-state reconciliation與dispatch順序。
2. 定義immutable hotkey settings/state snapshots及具名command callbacks。
3. 移動`ControlHotkeyWorker`、registered IDs與hotkey-local timing state至coordinator。
4. Controller保留feature enabled state、public toggles與GUI sync；private hotkey methods改為薄shim。
5. 保留dynamic `time/user32/key_down/key_up/tap_hotkey` patch interception。
6. Cleanup由coordinator唯一停止worker並release hotkey-local state。

### 驗證

```powershell
python -m unittest tests.test_control_hotkey_coordinator tests.test_control_hotkey_worker tests.test_auto_potion_foreground_guard tests.test_runtime_cleanup
python tools\verify.py full
python tools\verify.py performance
git diff --check
```

### Rollback

完整恢復controller worker ownership與poll loop；移除coordinator，不保留雙重poller。

## Task 4：ScreenCaptureService

### 檔案

- 新增 `maple_star/services/screen_capture.py`
- 新增 `tests/test_screen_capture_service.py`
- 修改 `maple_star/controllers/auto_potion_controller.py`
- 修改 `tests/test_auto_potion_foreground_guard.py`
- 修改 `tests/test_bar_detection_debug.py`
- 修改 `tests/test_experience.py`
- 修改 `tests/test_runtime_cleanup.py`
- 修改 `tests/stage4_controller_manifest.py`

### 步驟

1. 先盤點並鎖定foreground/stat baseline、EXP text、HUD search、preview、fade與loading的所有MSS grab行為。
2. Service唯一建立`mss.mss()`，以單一lock序列化`grab()`，並提供idempotent `close()`。
3. Controller、HUD舊邏輯與EXP舊邏輯先改為借用同一`ScreenCapturePort`；borrower不得存取raw handle或close。
4. Constructor建立service後立即註冊cleanup；驗證中途失敗也只關閉一次。
5. 此批不移動ROI、bar或OCR domain logic。

### 驗證

```powershell
python -m unittest tests.test_screen_capture_service tests.test_auto_potion_foreground_guard tests.test_bar_detection_debug tests.test_experience tests.test_runtime_cleanup
python tools\verify.py full
python tools\verify.py ocr-slow
git diff --check
```

### Rollback

所有grab call sites一次性恢復controller單一MSS owner；刪除service，禁止雙owner過渡狀態。

## Task 5：HudBarDetector

### 檔案

- 新增 `maple_star/services/hud_bar_detector.py`
- 新增 `tests/test_hud_bar_detector.py`
- 修改 `maple_star/controllers/auto_potion_controller.py`
- 修改 `tests/test_bar_detection_debug.py`
- 修改 `tests/test_auto_potion_foreground_guard.py`
- 修改 `tests/stage4_controller_manifest.py`

### 步驟

1. 建立具完整欄位的`HudDetectionRequest/Result`，先鎖定ROI、cache、stable sample、preview、loading/fade及debug payload。
2. 將`DirectBarCaptureContext`與GDI lifecycle移至detector，MSS只經borrowed `ScreenCapturePort`。
3. 移動template/geometry/stable-sample caches與direct capture/bar percent判定。
4. Controller只保留immutable latest result/geometry snapshot；不得同步維護mutable cache。
5. `current_bar_detection_regions()`、preview與manifest列出的`_capture_*`/`_bar_*`保留薄shim。
6. 驗證GDI重建、failure cleanup、module patch interception與rollback single-owner。

### 驗證

```powershell
python -m unittest tests.test_hud_bar_detector tests.test_bar_detection_debug tests.test_auto_potion_foreground_guard tests.test_runtime_cleanup
python tools\verify.py full
python tools\verify.py ocr-slow
git diff --check
```

### Rollback

一次性將GDI context、templates、geometry與stable samples還原controller；detector不得與controller owner並存。

## Task 6：PotionEngine

### 檔案

- 新增 `maple_star/services/potion_engine.py`
- 新增 `tests/test_potion_engine.py`
- 修改 `maple_star/controllers/auto_potion_controller.py`
- 修改 `tests/test_auto_potion_foreground_guard.py`
- 修改 `tests/stage4_controller_manifest.py`

### 步驟

1. 以`PotionBarConfig`、`PotionSample`、`PotionCommand`、`PotionCommandResult`、`PotionEngineSnapshot`固定完整資料契約。
2. 先鎖定threshold、continuous stop、cooldown、fast repeat、effect watch、recent damage、no-effect、out-of-potion與priority defer。
3. 移動potion-domain state；HP/MP held VK分開保存並測試可同時held。
4. Controller執行command並在foreground reject、invalid key、queue full、failure或success時恰好回覆一次result。
5. Engine只在`executed`後推進cooldown/effect/held state；duplicate/unknown command ID不二次推進。
6. SendInput/PotionActionWorker、send前foreground recheck與cleanup release仍由controller擁有。
7. Manifest列出的`_maybe_drink_*`、effect-watch與priority methods保留薄shim。

### 驗證

```powershell
python -m unittest tests.test_potion_engine tests.test_auto_potion_foreground_guard tests.test_runtime_cleanup
python tools\verify.py full
python tools\verify.py performance
git diff --check
```

### Rollback

將全部engine state一次性還原controller，刪除command/result wiring；不得保留雙寫或半套feedback bridge。

## Task 7：ExperienceCaptureCoordinator

### 檔案

- 新增 `maple_star/services/experience_capture_coordinator.py`
- 新增 `tests/test_experience_capture_coordinator.py`
- 修改 `maple_star/controllers/auto_potion_controller.py`
- 修改 `tests/test_experience.py`
- 修改 `tests/test_experience_worker_spawn.py`
- 修改 `tests/test_auto_potion_foreground_guard.py`
- 修改 `tests/test_runtime_cleanup.py`
- 修改 `tests/stage4_controller_manifest.py`

### 步驟

1. 先固定baseline calibration/cursor restoration、tooltip/bottom cadence、burst signature suppression、executor submit/poll/cancel與EXP-10 checkpoint。
2. Coordinator借用immutable HUD geometry與`ScreenCapturePort`，不得持有或關閉MSS。
3. 移動OCR executor/future、capture-local cursor restoration與EXP job state；Stage 3 parser/readers/tracker不重寫。
4. Controller保留public reset/toggle behavior、runtime status application及potion priority orchestration；private EXP methods保留薄shim。
5. Cleanup由coordinator唯一cancel future、shutdown executor及restore cursor；每步idempotent。
6. 驗證status/source/reason/telemetry、clock pause、spawn worker identity及OCR fixture不變。

### 驗證

```powershell
python -m unittest tests.test_experience_capture_coordinator tests.test_experience tests.test_experience_worker_spawn tests.test_auto_potion_foreground_guard tests.test_runtime_cleanup
python tools\verify.py full
python tools\verify.py ocr-slow
python tools\verify.py performance
git diff --check
```

### Rollback

一次性恢復controller executor/future/job owner；Stage 3 OCR services、tracker與capture service不動。

## Task 8：Facade cleanup、文件與 final gate

### 檔案

- 新增 `docs/reviews/2026-07-17-stage-4-review.md`
- 修改 `maple_star/controllers/auto_potion_controller.py`
- 修改 `tests/stage4_controller_manifest.py`
- 修改 `tests/test_stage4_controller_contracts.py`
- 修改 `tests/test_public_facades.py`
- 修改 `docs/project-structure.md`
- 修改 `docs/INDEX.md`

### 步驟

1. 依manifest移除無call site的temporary shim；required private shims與canonical re-exports永久保留。
2. 確認controller只含orchestration/shared state/runtime coordination/GUI publish/cleanup scheduling，無domain algorithm或resource duplicate owner。
3. 以clean subprocess驗證module DAG、alias import order、factory/IPC/helper object identity。
4. 記錄final LOC、method/field數、resource ownership、performance與各驗證gate。
5. 每個新手寫module確認小於2,000行；controller LOC只記錄，不作硬門檻。
6. 執行獨立code review，修完所有Correctness/Compatibility/Ownership findings。

### 驗證

```powershell
python -m unittest tests.test_stage4_controller_contracts tests.test_public_facades tests.test_runtime_cleanup
python tools\verify.py full
python tools\verify.py ocr-slow
python tools\verify.py performance
git diff --check
```

### Rollback

只回復facade cleanup與文件；不得回滾已通過前批的canonical owners。若final review發現較早批次ownership錯誤，回到該批邊界修正並重跑其後全部gate。

## 最終交付

- 報告九批結果、controller與新modules LOC、runtime import DAG、resource ownership及performance差異。
- 列出永久compatibility shims與任何因安全邊界保留的residual coupling。
- 確認working tree只包含Stage 4 intended paths；保持unstaged，除非使用者另行要求commit。
