# Stage 4 AutoPotionController 拆分設計

> 知識庫索引：[docs/INDEX.md](../../INDEX.md)
>
> 上層設計：[全專案 Code Review 與減肥設計](2026-07-17-project-slimming-design.md)

## 目標

本階段拆分 7,723 行的 `maple_star/controllers/auto_potion_controller.py`。拆分以責任、依賴方向與資源 ownership 為成功標準，不設 controller LOC 硬門檻。

- `AutoPotionController` 保留 lifecycle、`update()` orchestration、runtime process coordination、GUI 狀態發布與 cleanup 排程。
- 依耦合度抽出 runtime composition、媒體播放、控制熱鍵、HUD/bar detection、喝水狀態機與 EXP capture orchestration。
- 保留公開 API、舊 import path、module patch points，以及已被 tests 或外部程式直接使用的 private methods。
- 新增模組各小於 2,000 行；generated payload 不受此限制。
- 拆分不改喝水、OCR、HUD、熱鍵 timing、判定門檻或狀態機語意。
- 若發現可重現的既有 bug，只做具測試的窄修正，不擴大本階段設計。

## 非目標

- 不改 `settings.json` schema、profile/global 邊界或 GUI layout。
- 不重寫 Stage 3 的 OCR services、tracker 或 GUI page builders。
- 不新增通用 manager、service locator、inheritance hierarchy 或 dependency injection framework。
- 不讓兩個物件共同持有同一 Win32 handle、MCI alias、thread、process、executor 或 capture context。
- 不以 retry、debounce 或新 timing 常數掩蓋拆分回歸。
- 不打包、不建立 tag、不發佈 release；未經使用者要求不 push。

## Baseline 與契約盤點

### 結構 baseline

- `AutoPotionController`：7,723 LOC。
- `DirectBarCaptureContext`：controller module 內的 GDI capture owner。
- `RuntimeProcessCoordinator`：`services/runtime_processes.py` 的 child-process owner。
- `AutoPotionController` 目前直接 import runtime coordinator、IPC types、hotkey worker、potion worker、OCR services、GUI、settings、Win32 adapters、OpenCV、MSS 與 MCI。
- `runtime_processes.py` 的 potion/experience child entry 反向 import `_create_auto_potion_controller`，形成 controller/runtime 雙向依賴。

### 必須保留的公開 surface

- `AutoPotionController` constructor 與所有 public methods。
- `maple_star.controller` module alias identity。
- `maple_star.__init__`、`auto_potion.py` 的 `AutoPotionController` object identity。
- `_create_auto_potion_controller` 舊 import path；實作可移動，但舊 symbol 必須指向同一 canonical function object。
- `loading_screen_metrics`、`normalize_bar_percent` 與 controller facade 既有 constants。

### Private compatibility

實作前建立 Stage 4 manifest，盤點下列 private surface：

- tests 直接呼叫的 unbound methods，例如 `_capture_bar_percent()`。
- tests 使用 `patch("maple_star.controllers.auto_potion_controller.<name>")` 的 module patch points。
- `gamepad_controller.py`、`runtime_processes.py` 與其他 production call sites 使用的 private methods/attributes。
- `AutoPotionController.__new__()` test doubles 預設存在的 state attributes。

搬移 private implementation 時，controller 保留薄轉接；轉接不得複製狀態機或資源 ownership。

## 架構

### 依賴方向

```text
controllers/gamepad_controller.py
          |
          v
controllers/auto_potion_factory.py -----> controllers/auto_potion_controller.py
          |                                         |
          v                                         v
services/runtime_processes.py             services/runtime_api.py
                                                    |
            +---------------+-----------------------+------------------+
            |               |                       |                  |
            v               v                       v                  v
  media_playback.py  control_hotkeys.py    hud_bar_detector.py  potion_engine.py
                                                                       |
                                                                       v
                                                  experience_capture_coordinator.py
```

規則：

- Collaborator 不 import `auto_potion_controller`、GUI 或 concrete runtime coordinator。
- Controller 不 import `services/runtime_processes.py`；只依賴 `runtime_api.py` 的 IPC types、Protocol 與 factory callback。
- `runtime_processes.py` 可在 child entry 經 composition root 建立 controller，controller 不再反向 import該 module。
- Collaborator 可依賴 leaf models、constants、adapters 與 Stage 3 canonical OCR services。
- `auto_potion_factory.py` 是唯一可同時認識 controller concrete class 與 runtime concrete coordinator 的 composition root。

## Component 設計

### 1. Runtime composition root

新增：

- `maple_star/services/runtime_api.py`
- `maple_star/controllers/auto_potion_factory.py`

`runtime_api.py` 擁有：

- controller 使用的 runtime IPC types 或其 canonical re-export。
- `RuntimeProcessPort` Protocol，只列 controller 實際呼叫的 `start/stop/send/drain/restart` surface。
- `RuntimeProcessFactory = Callable[..., RuntimeProcessPort]`。

`auto_potion_factory.py` 擁有 canonical `_create_auto_potion_controller(*args, **kwargs)`。Factory 採 partial-safe 建立：先 `__new__()`，再呼叫 `__init__()`；初始化中斷時仍執行已建立資源的 best-effort cleanup。

Constructor 相容策略：

- `AutoPotionController.__init__()` 保留現有 positional/keyword 呼叫。
- 新增 dependency 僅能是 keyword-only 且具行為相同的 default factory。
- default factory 位於 `runtime_api.py`，以 call-time import 建立 concrete coordinator；module import graph 不形成反向 edge。
- `runtime_processes_enabled=False` 不建立 coordinator，語意不變。

舊 controller module re-export canonical factory，確保 object identity 不變。

### 2. MediaPlaybackService

新增 `maple_star/services/media_playback.py`。

責任：

- preload media files。
- MCI alias open/play/volume/close。
- toggle beep、system notification 與 blocking lie-detector playback。
- potion/minimap toggle sound routing。

介面：

```python
class MediaPlaybackService:
    def preload(self) -> None: ...
    def play_toggle_beep(self, pattern: tuple[tuple[int, int], ...]) -> None: ...
    def play_system_notification(self) -> None: ...
    def play_media(self, path: Path, alias: str, *, volume_percent: object = 100) -> None: ...
    def play_lie_detector_alert(self, volume_percent: object) -> None: ...
    def close(self) -> None: ...
```

Ownership：service 建立並唯一持有 MCI aliases、buffer 與 blocking alert thread。Controller 只呼叫 `close()`，不直接關閉 alias。

相容：controller 的 `_play_*`、`_preload_media_files()`、`_close_media_files()` 留薄轉接。既有 module-level WinMM patch points由 service context callback或 controller forwarding patch保留。

### 3. ControlHotkeyCoordinator

新增 `maple_star/services/control_hotkey_coordinator.py`。

責任：

- hotkey normalization、registration/unregistration 與 polling fallback。
- worker event drain、cached down-state reconciliation 與 key-capture suspension。
- foreground gating、hold-to-disable、debounce 與 action dispatch timing。

輸入：

- hotkey settings snapshot。
- `is_allowed_foreground()`、`is_key_capture_blocking()` callbacks。
- 具名 command callbacks：emergency stop、toggle scripts、toggle/reset EXP、toggle pickup、toggle minimap。

輸出：

- `emergency_stop_requested` flag 或 consume method。
- down-state、pending hold 與 last-dispatch timestamps的明確 state snapshot。

Ownership：coordinator 建立並唯一持有 `ControlHotkeyWorker`、registered hotkey IDs 與 hotkey-local timing state。Controller 保留 feature enabled state與 GUI sync。

相容：所有 controller public toggle methods不變；既有 `_try_*`、`poll_control_hotkeys()` 與 worker-state private methods留薄轉接。

### 4. HudBarDetector

新增 `maple_star/services/hud_bar_detector.py`。

責任：

- GDI/MSS screen capture。
- HUD label template cache與 geometry validation。
- bottom HUD search、HP/MP/EXP ROI 計算。
- direct capture、stable sample、bar mask與 percent estimate。
- preview image與 `BarDetectionDebug` payload。
- loading/fade/channel-transition image判定。

介面以具名資料型別傳遞：

```python
@dataclass(frozen=True)
class HudDetectionRequest: ...

@dataclass(frozen=True)
class HudDetectionResult:
    hp_percent: float | None
    mp_percent: float | None
    layout: BottomHudLayout | None
    debug: dict[str, BarDetectionDebug]
```

Ownership：detector 建立並唯一持有 `DirectBarCaptureContext`、MSS capture object、template caches、stable sample cache與 cached geometry。Controller 不保留第二份 resource handle；只保留需跨 subsystem 分享的 immutable geometry/result snapshot。

相容：`current_bar_detection_regions()`、`capture_bar_preview_images()` 與 tests 直接呼叫的 `_capture_*`/`_bar_*` methods留轉接。Module patch points透過 constructor-injected adapter functions保留。

### 5. PotionEngine

新增 `maple_star/services/potion_engine.py`。

責任：

- threshold與 continuous stop判定。
- pending sends、cooldown與fast-repeat scheduling。
- effect-watch attempts、stability confirmation與recent-damage pressure。
- no-effect counting、out-of-potion hold與priority defer。
- 產生 tap/hold/release意圖，不直接操作 GUI。

介面：

```python
@dataclass(frozen=True)
class PotionSample: ...

@dataclass(frozen=True)
class PotionCommand:
    kind: Literal["tap", "hold", "release", "alert"]
    bar_type: Literal["hp", "mp"]
    key_name: str | None = None

class PotionEngine:
    def update(self, sample: PotionSample) -> tuple[PotionCommand, ...]: ...
    def next_due_at(self) -> float | None: ...
    def clear(self, bar_type: str | None = None) -> None: ...
```

State：engine 可持有 potion-domain state dataclass；controller仍是 feature enable、settings、target foreground與orchestration state owner。Engine state不包含 Win32 handle、worker、thread或GUI object。

Controller執行 `PotionCommand`，維持 SendInput/PotionActionWorker ownership與send前foreground recheck。既有 `_maybe_drink_*`、effect-watch與priority methods留薄轉接。

### 6. ExperienceCaptureCoordinator

新增 `maple_star/services/experience_capture_coordinator.py`。

責任：

- baseline calibration UI sequence與cursor restoration。
- tooltip/bottom capture scheduling、burst state與image signature suppression。
- OCR executor submit/poll/cancel。
- EXP-10 checkpoint scheduling與failure/retry state。
- 將 canonical OCR reading交給既有 tracker；不重寫 parser/Pixel/Paddle。

輸入：

- immutable HUD geometry snapshot。
- target/cursor/capture adapters。
- Stage 3 OCR worker functions與tracker port。
- status/log callbacks。

Ownership：coordinator建立並唯一持有 OCR executor/future、capture-local cursor restoration state與EXP job state。Controller在cleanup呼叫`close()`，不得直接shutdown同一executor。

相容：`reset_experience_statistics()`、EXP enabled public behavior與tests直接使用的 private methods留controller轉接。Existing status、source、reason、telemetry與clock pause語意不變。

## Controller 保留的狀態

`AutoPotionController` 最終保留：

- `settings`、`gui`與closed/enabled flags。
- target window與allowed-foreground orchestration。
- runtime process generation/status signatures與watchdog timestamps。
- collaborator references。
- main-loop cadence、settings save schedule與跨domain priority sequencing。
- GUI publish去重與runtime status application。
- cleanup step registry與failure reporting。

Domain-local caches與state移至唯一 collaborator；controller只保存不可變snapshot或轉接property。不得在controller與collaborator同步維護兩份mutable truth。

## 主資料流

```text
GUI / gamepad_controller
    -> AutoPotionController.update(now)
        -> ControlHotkeyCoordinator.poll(now)
        -> RuntimeProcessPort.update/drain (runtime mode)
        -> HudBarDetector.capture(now) (local mode)
            -> PotionEngine.update(sample)
                -> controller foreground recheck
                -> PotionActionWorker / SendInput
            -> ExperienceCaptureCoordinator.update(now, hud_snapshot)
                -> Stage 3 OCR workers
                -> ExperienceEfficiencyTracker
        -> GUI/runtime status publish
```

Controller明確決定domain執行順序，collaborators不得互相呼叫。跨domain資訊只經controller傳遞，例如potion priority deadline延後EXP capture。

## 錯誤處理

- Collaborator只捕捉既有可降級錯誤；未知例外往controller既有error boundary傳遞。
- Status、reason、logging文字與frequency維持現況，characterization tests先鎖定。
- Child crash、stale heartbeat、generation filtering與bounded queue語意不變。
- SendInput前景recheck、held-key release與cursor restoration保留`finally`。
- 每個`close()`必須idempotent。單一close失敗不能阻止其他cleanup steps。
- Constructor partial failure沿用Stage 1A策略：從第一個resource owner建立後即註冊cleanup。
- 未知錯誤不以`except: pass`吞掉；best-effort failure寫入既有logger。

## 分批順序與 rollback

### Batch 0：Baseline與manifest

- 記錄controller LOC、method/field manifest、module patch points、runtime import graph與performance baseline。
- 新增characterization tests，不改production code。

### Batch 1：Runtime composition

- 新增runtime API/Protocol與canonical factory。
- 解除concrete controller/runtime雙向import。
- Rollback：恢復controller-local factory與concrete coordinator import；不混入其他抽取。

### Batch 2：Media

- 先測preload、volume、failure、thread與close，再移動。
- Rollback：controller重新取得aliases ownership並刪除service wiring。

### Batch 3：Control hotkeys

- 先測registration fallback、foreground、capture guard、hold/debounce與dispatch，再移動。
- Rollback：恢復controller worker ownership；不保留雙重poller。

### Batch 4：HUD/bar detection

- 先測ROI/cache/direct capture/preview/loading/fade與GDI cleanup，再移動。
- Rollback：完整恢復single capture context；禁止controller與detector同時存活。

### Batch 5：Potion engine

- 先測threshold、continuous、pending send、effect watch、out-of-potion與priority defer，再移動。
- Rollback：將engine state一次性還原controller；不得保留雙寫bridge。

### Batch 6：EXP capture

- 先測baseline、cursor、burst、checkpoint、executor cancel與OCR result/status，再移動。
- Rollback：恢復controller executor/job ownership；Stage 3 OCR services不動。

### Batch 7：Facade cleanup與final review

- 移除無call site的temporary shims；manifest要求的shims永久保留。
- 更新`docs/project-structure.md`與Stage 4 review。
- 獨立code review確認ownership、import graph與failure rollback。

## 驗證

每批至少執行：

```powershell
python -m unittest <該 subsystem targeted tests> tests.test_public_facades tests.test_runtime_cleanup
python tools\verify.py full
git diff --check
```

下列批次加跑：

- Runtime、hotkey、potion、EXP cadence變更：`python tools\verify.py performance`。
- HUD或EXP capture變更：`python tools\verify.py ocr-slow`。
- Factory/worker變更：Windows `spawn` round-trip與parent/child resource ownership tests。

Final gate：

```powershell
python tools\verify.py full
python tools\verify.py ocr-slow
python tools\verify.py performance
git diff --check
```

## 成功條件

- Controller只保留orchestration、shared state、runtime coordination、GUI publish與cleanup排程。
- 各collaborator可獨立理解、測試與cleanup；沒有controller back-reference。
- 同一resource只有一個owner，所有close皆idempotent。
- Runtime concrete import graph無cycle。
- Public facade、canonical object identity、module patch points與必要private shims通過manifest。
- 行為、timing、status、settings與OCRfixture維持characterization結果。
- 新手寫module各小於2,000行；controller LOC只記錄，不作成功門檻。
- Full、OCR slow、performance與獨立code review全部通過。
