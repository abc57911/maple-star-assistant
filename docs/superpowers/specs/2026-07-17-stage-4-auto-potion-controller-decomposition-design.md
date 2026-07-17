# Stage 4 AutoPotionController 拆分設計

> 知識庫索引：[docs/INDEX.md](../../INDEX.md)
>
> 上層設計：[全專案 Code Review 與減肥設計](2026-07-17-project-slimming-design.md)

## 目標

本階段拆分 7,723 行的 `maple_star/controllers/auto_potion_controller.py`。拆分以責任、依賴方向與資源 ownership 為成功標準，不設 controller LOC 硬門檻。

- `AutoPotionController` 保留 lifecycle、`update()` orchestration、runtime process coordination、GUI 狀態發布與 cleanup 排程。
- 依耦合度抽出 runtime composition、媒體播放、控制熱鍵、共用畫面擷取、HUD/bar detection、喝水狀態機與 EXP capture orchestration。
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

### Patch-point 相容策略

Stage 4 採單一策略：純契約`ControllerModuleAdapters`與`RuntimeMediaSink`定義在leaf module `maple_star/services/controller_collaborator_api.py`。Controller module建立adapter實例，每個adapter在**呼叫當下**解析controller module global；collaborator只import leaf契約並接收callables，不直接import controller或capture原函式object。因`maple_star.controller`與`maple_star.controllers.auto_potion_controller`維持同一module identity，patch任一路徑都會被動態adapter看見。

```python
@dataclass(frozen=True)
class ControllerModuleAdapters:
    monotonic: Callable[[], float]
    sleep: Callable[[float], None]
    thread_factory: Callable[..., threading.Thread]
    winmm_provider: Callable[[], object]
    user32_provider: Callable[[], object]
    beep: Callable[[int, int], None]
    message_beep: Callable[..., None]
    play_sound: Callable[..., None]
    key_down: Callable[[int], None]
    key_up: Callable[[int], None]
    tap_hotkey: Callable[..., None]
    save_settings: Callable[..., None]

class RuntimeMediaSink(Protocol):
    def play_media(self, path: Path, alias: str) -> None: ...
    def play_toggle_beep(self, pattern: tuple[tuple[int, int], ...]) -> None: ...
```

例如`monotonic=lambda: time.monotonic()`、`winmm_provider=lambda: ctypes.windll.winmm`、`beep=lambda *args: winsound.Beep(*args)`；禁止在constructor建立時寫成`monotonic=time.monotonic`，否則後續patch無法攔截。Controller private shim也在每次呼叫時查找當前collaborator，不快取bound method。

Batch 0由AST與tests產生完整manifest；每個現有patch point必須且只能分類為：

- dynamic adapter：`ctypes.windll`、`threading.Thread`、`time.monotonic`、`time.sleep`、`winsound.Beep`、`winsound.MessageBeep`、`winsound.PlaySound`、`user32`、`key_down`、`key_up`、`tap_hotkey`、`save_settings`及manifest找到的其他I/O globals。
- controller private shim：tests或production直接patch/call的`_play_*`、`_capture_*`、`_bar_*`、hotkey、potion與EXP methods。
- canonical re-export：facade constants、helpers、IPC types、signature helpers、`InlineExecutor`與factory symbol；object identity必須相同。

不得以修改tests patch路徑取代相容層。Runtime child的媒體差異使用明確`RuntimeMediaSink` dependency，不再靠instance monkey-patch。每批PR/diff需附該批搬移symbol的manifest分類；未分類symbol不得搬移。

## 架構

### 依賴方向

```text
controllers/gamepad_controller.py
          |
          v
controllers/auto_potion_factory.py -----> controllers/auto_potion_controller.py
          |                                         |
          v                                         +------> services/controller_collaborator_api.py
controllers/auto_potion_runtime_composition.py      |
          |                                         +------> services/runtime_api.py
          +------> services/runtime_processes.py    +------> services/media_playback.py
          +------> controllers/runtime_child_entrypoints.py
                                                    +------> services/screen_capture.py
                                                    +------> services/control_hotkey_coordinator.py
                                                    +------> services/hud_bar_detector.py
                                                    +------> services/potion_engine.py
                                                    +------> services/experience_capture_coordinator.py
```

規則：

- Collaborator 不 import `auto_potion_controller`、GUI 或 concrete runtime coordinator。
- `controller_collaborator_api.py`只含dataclass/Protocol/type aliases，不import controller、concrete service、Win32 resource或GUI；controller、media service與child entry共同依賴它。
- Controller 不 import `services/runtime_processes.py`；只依賴 `runtime_api.py` 的 IPC types、Protocol 與 injected factory callback。
- `runtime_processes.py` 只實作 concrete coordinator，不 import controller 或 factory，也不包含 child entry。
- `runtime_child_entrypoints.py` 的 module-level spawn targets 只在函式執行時 local-import canonical factory；因此 Windows `spawn` 載入 module 時不形成 reverse import edge。
- Collaborator 可依賴 leaf models、constants、adapters 與 Stage 3 canonical OCR services。
- `auto_potion_runtime_composition.py` 是唯一建立 concrete coordinator 的 production composition module；canonical controller factory 與 standalone constructor fallback 都呼叫此 module，不自行重複 wiring。
- Controller 是唯一的 domain orchestrator；HUD、potion 與 EXP domain collaborators 彼此平行，不互相呼叫或持有reference。HUD與EXP只可共同依賴無domain邏輯的`ScreenCapturePort` infrastructure dependency。

## Component 設計

### 0. Collaborator contracts

新增`maple_star/services/controller_collaborator_api.py`，canonical擁有`ControllerModuleAdapters`與`RuntimeMediaSink`兩個純契約。此module不得建立資源或提供default implementations；controller建立dynamic adapter instance，runtime child建立queue/no-op sink implementations，services只消費Protocol。舊公開facade不需re-export此Stage 4 internal contract。

### 1. Runtime composition root

新增：

- `maple_star/services/runtime_api.py`
- `maple_star/controllers/auto_potion_factory.py`
- `maple_star/controllers/auto_potion_runtime_composition.py`
- `maple_star/controllers/runtime_child_entrypoints.py`

`runtime_api.py` 擁有：

- 所有 runtime IPC dataclasses 的 canonical definitions：`SettingsUpdated`、`TargetWindowUpdated`、`PotionControl`、`ExperienceControl`、`ControlCommand`、`Shutdown`、`PotionStatus`、`ExperienceStatus`、`ControlStatus`、`WorkerCrashed`。
- `InlineExecutor`、`_potion_status_signature()`、`_experience_status_signature()` 的 canonical definitions；舊 module 只 re-export 同一 object。
- `RuntimeProcessPort` Protocol，完整列出 `start()`、`start_control(worker_target, *args)`、`send_settings()`、`send_target_window()`、`send_potion_control()`、`send_experience_control()`、`send_control()`、`request_control_release()`、三個 `drain_*_statuses()`、三個 `*_alive()`、`restart_potion()` 與 `stop()`。
- `RuntimeProcessFactory = Callable[..., RuntimeProcessPort]`。

Protocol 的參數、default與回傳型別逐字比照現有`RuntimeProcessCoordinator`；包括三個drain的`limit: int = 64`、`restart_potion(..., timeout: float = 1.0)`及`stop(timeout: float = 1.0)`。這可防止以過度寬鬆的`send/drain`抽象漏掉control child或restart契約。

`auto_potion_factory.py` 擁有 canonical `_create_auto_potion_controller(*args, **kwargs)`。Factory 採 partial-safe 建立：先 `__new__()`，再呼叫 `__init__()`；初始化中斷時仍執行已建立資源的 best-effort cleanup。它將 `auto_potion_runtime_composition.create_runtime_process_port` 作為 keyword dependency 傳入 controller。

`runtime_child_entrypoints.py` 擁有 potion/experience 的 module-level spawn targets。Target 在 child 內 local-import canonical factory，並透過新增的keyword-only `media_sink`參數注入具名`RuntimeMediaSink`：`play_media(path: Path, alias: str) -> None`與`play_toggle_beep(pattern) -> None`。Controller將此borrowed sink傳給`MediaPlaybackService`；service有sink時路由至sink，沒有時維持本機MCI/winsound行為。Potion child的`play_media`將alias送入既有status queue，experience child與兩者的beep使用no-op sink；sink不持有controller資源，controller cleanup只關閉service，不關閉borrowed sink。禁止再 monkey-patch controller 的 `_play_media_file` 或 `_play_toggle_beep`。`gamepad_controller.py` 不再 import concrete runtime IPC types，也不直接操作 `auto_potion.runtime_processes`；它透過controller的`start_control_runtime()`、`send_control_runtime()`、`request_control_release()`、`drain_control_runtime_statuses()`與`control_runtime_alive()`薄轉接呼叫完整`RuntimeProcessPort`。

Constructor 相容策略：

- `AutoPotionController.__init__()` 保留現有 positional/keyword 呼叫。
- 新增 `runtime_process_factory` 與 `media_sink` dependencies 僅能是 keyword-only。Canonical factory明確傳入 production runtime factory；直接呼叫 public constructor 且未傳入時，controller 在 `_start_runtime_processes()` call-time import同一個 `auto_potion_runtime_composition.create_runtime_process_port`，維持既有預設行為。`media_sink=None`維持現有本機媒體行為。
- Compatibility fallback 不含第二套 wiring；composition module只依賴 concrete coordinator、runtime API與無 import-time controller edge的spawn targets。因此任意 clean import order都不形成module cycle。
- `runtime_processes_enabled=False` 不建立 coordinator，語意不變。
- `runtime_processes` attribute 暫時保留為同一 `RuntimeProcessPort` 的 compatibility alias；新增的 `runtime_port` property 與 forwarding methods不建立第二份owner。Batch 8僅在manifest證明無外部依賴時才可移除alias，否則永久保留。

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
    def __init__(self, adapters: ControllerModuleAdapters, *, sink: RuntimeMediaSink | None = None) -> None: ...
    def preload(self) -> None: ...
    def play_toggle_beep(self, pattern: tuple[tuple[int, int], ...]) -> None: ...
    def play_system_notification(self) -> None: ...
    def play_media(self, path: Path, alias: str, *, volume_percent: object = 100) -> None: ...
    def play_lie_detector_alert(self, volume_percent: object) -> None: ...
    def close(self) -> None: ...
```

Ownership：沒有sink時，service建立並唯一持有MCI aliases、buffer與blocking alert thread；有sink時不建立這些本機資源，只轉送media/beep intent。Controller只呼叫service的`close()`，不直接關閉alias或borrowed sink。

相容：controller 的 `_play_*`、`_preload_media_files()`、`_close_media_files()` 留薄轉接。Service 接收下方「Patch-point 相容策略」定義的動態 adapters；不存在「context callback 或 forwarding」二選一。

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

### 4. ScreenCaptureService

新增 `maple_star/services/screen_capture.py`。

責任與 ownership：

- 唯一建立並持有 `mss.mss()`；所有 MSS `grab()` 經同一個 lock 序列化。
- 提供 `grab(region) -> np.ndarray` 與 idempotent `close()`，不包含 HUD、EXP 或 transition 判定。
- Controller 建立後傳入 HUD 與 EXP collaborators；兩者只借用此 port，不得關閉、替換或快取 raw MSS handle。
- 現有 foreground-client/stat baseline、EXP text、HUD search、preview、fade 與 loading capture 全部改走此 service。
- `DirectBarCaptureContext` 不屬於 MSS；它仍由 `HudBarDetector` 唯一持有。Controller cleanup registry負責依序呼叫 EXP close、HUD close、screen capture close，每個 resource只關閉一次。

```python
class ScreenCapturePort(Protocol):
    def grab(self, region: tuple[int, int, int, int]) -> np.ndarray: ...

class ScreenCaptureService:
    def grab(self, region: tuple[int, int, int, int]) -> np.ndarray: ...
    def close(self) -> None: ...
```

### 5. HudBarDetector

新增 `maple_star/services/hud_bar_detector.py`。

責任：

- 透過借用的 `ScreenCapturePort` 取得 MSS image；自己唯一持有 GDI direct-capture context。
- HUD label template cache與 geometry validation。
- bottom HUD search、HP/MP/EXP ROI 計算。
- direct capture、stable sample、bar mask與 percent estimate。
- preview image與 `BarDetectionDebug` payload。
- loading/fade/channel-transition image判定。

介面以具名資料型別傳遞：

```python
@dataclass(frozen=True)
class HudDetectionRequest:
    now: float
    target_hwnd: int
    target_client_rect: tuple[int, int, int, int] | None
    detect_hp: bool
    detect_mp: bool
    require_clear_tail_hp: bool
    require_clear_tail_mp: bool
    preview_requested: bool = False

@dataclass(frozen=True)
class HudDetectionResult:
    hp_percent: float | None
    mp_percent: float | None
    layout: BottomHudLayout | None
    hp_region: tuple[int, int, int, int] | None
    mp_region: tuple[int, int, int, int] | None
    exp_region: tuple[int, int, int, int] | None
    gameplay_hud_active: bool
    transition_kind: Literal["none", "loading", "fade"]
    preview_images: Mapping[str, np.ndarray]
    debug: dict[str, BarDetectionDebug]
```

Ownership：detector 建立並唯一持有 `DirectBarCaptureContext`、template caches、stable sample cache與 cached geometry。它只借用 `ScreenCapturePort`。Controller 不保留第二份 resource handle或mutable detection cache；只保留需跨 subsystem 分享的 immutable geometry/result snapshot。

相容：`current_bar_detection_regions()`、`capture_bar_preview_images()` 與 tests 直接呼叫的 `_capture_*`/`_bar_*` methods留轉接。Module patch points透過 constructor-injected adapter functions保留。

### 6. PotionEngine

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
class PotionBarConfig:
    enabled: bool
    key_name: str
    threshold_percent: float
    cooldown_seconds: float
    continuous_enabled: bool
    continuous_stop_percent: float
    no_effect_limit: int

@dataclass(frozen=True)
class PotionSample:
    now: float
    hp_percent: float | None
    mp_percent: float | None
    hp: PotionBarConfig
    mp: PotionBarConfig
    feature_enabled: bool
    scripts_enabled: bool
    target_active: bool
    challenge_paused: bool
    gameplay_hud_active: bool
    action_channel_ready: bool
    recent_damage_at: float | None

@dataclass(frozen=True)
class PotionCommand:
    command_id: int
    kind: Literal["tap", "hold", "release", "alert"]
    bar_type: Literal["hp", "mp"]
    key_name: str | None = None
    due_at: float | None = None
    reason: str = ""

@dataclass(frozen=True)
class PotionCommandResult:
    command_id: int
    outcome: Literal[
        "executed",
        "rejected_foreground",
        "invalid_key",
        "queue_full",
        "failed",
    ]
    completed_at: float
    held_vk: int = 0

@dataclass(frozen=True)
class PotionEngineSnapshot:
    next_due_at: float | None
    priority_defer_until: float | None
    hp_status: str
    mp_status: str
    hp_no_effect_count: int
    mp_no_effect_count: int
    hp_held_vk: int
    mp_held_vk: int

class PotionEngine:
    def update(self, sample: PotionSample) -> tuple[PotionCommand, ...]: ...
    def apply_result(self, result: PotionCommandResult) -> None: ...
    def snapshot(self) -> PotionEngineSnapshot: ...
    def clear(self, bar_type: str | None = None) -> None: ...
```

State：engine 可持有 potion-domain state dataclass；controller仍是 feature enable、settings、target foreground與orchestration state owner。Engine state不包含 Win32 handle、worker、thread或GUI object。HP與MP held state以兩個獨立VK欄位表示，允許兩者同時held，語意與現況一致。

Controller執行 `PotionCommand`，維持 SendInput/PotionActionWorker ownership與send前foreground recheck，並對每個command恰好呼叫一次`apply_result()`。Engine只在`executed`後推進cooldown、effect-attempt與held VK；foreground拒絕、key parse失敗、queue full或例外不假裝已送出。未知或重複`command_id`記錄既有logger並忽略，不二次推進state。Cleanup/cancel產生的release也走同一handshake；既有 `_maybe_drink_*`、effect-watch與priority methods留薄轉接。

### 7. ExperienceCaptureCoordinator

新增 `maple_star/services/experience_capture_coordinator.py`。

責任：

- baseline calibration UI sequence與cursor restoration。
- tooltip/bottom capture scheduling、burst state與image signature suppression。
- OCR executor submit/poll/cancel。
- EXP-10 checkpoint scheduling與failure/retry state。
- 將 canonical OCR reading交給既有 tracker；不重寫 parser/Pixel/Paddle。

輸入：

- immutable HUD geometry snapshot。
- target/cursor adapters與借用的`ScreenCapturePort`。
- Stage 3 OCR worker functions與tracker port。
- status/log callbacks。

Ownership：coordinator建立並唯一持有 OCR executor/future、capture-local cursor restoration state與EXP job state。它不持有或關閉MSS；所有image經借用的`ScreenCapturePort`取得。Controller在cleanup呼叫`close()`，不得直接shutdown同一executor。

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
        -> RuntimeProcessPort send/drain/alive watchdog (runtime mode)
        -> HudBarDetector.capture(now, ScreenCapturePort) (local mode)
        -> PotionEngine.update(sample)
        -> controller foreground recheck
        -> PotionActionWorker / SendInput
        -> PotionEngine.apply_result(command_result)
        -> ExperienceCaptureCoordinator.update(now, hud_snapshot, ScreenCapturePort)
        -> Stage 3 OCR workers / ExperienceEfficiencyTracker
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
- Manifest逐項標示dynamic adapter、controller shim或canonical re-export；另鎖定所有`self.sct.grab()`用途、GDI context與executor/MCI/thread/process owners。
- 建立無resource的collaborator contracts leaf module；以import test鎖定它不反向依賴controller或concrete services。

### Batch 1：Runtime composition

- 新增完整runtime API/Protocol、canonical factory、composition module與spawn-safe child entrypoints。
- 解除concrete controller/runtime雙向import。
- 加入clean-interpreter任意import順序、Windows spawn round-trip、舊symbol object identity及`RuntimeProcessPort`conformance tests。
- Rollback：恢復controller-local factory與concrete coordinator import；不混入其他抽取。

### Batch 2：Media

- 先測preload、volume、failure、thread與close，再移動；另測local default、potion queue sink與experience no-op sink，確認child不再覆寫instance methods。
- Rollback：controller重新取得aliases ownership並刪除service wiring。

### Batch 3：Control hotkeys

- 先測registration fallback、foreground、capture guard、hold/debounce與dispatch，再移動。
- Rollback：恢復controller worker ownership；不保留雙重poller。

### Batch 4：Screen capture ownership

- 建立唯一MSS owner，逐一遷移foreground/stat、EXP、HUD、preview、loading與fade的grab call sites。
- 測試序列化、partial-constructor cleanup、idempotent close，以及HUD/EXP不得關閉borrowed port。
- Rollback：所有MSS call sites一次性恢復controller owner；禁止service與controller同時持有MSS。

### Batch 5：HUD/bar detection

- 先測ROI/cache/direct capture/preview/loading/fade與GDI cleanup，再移動。
- Rollback：完整恢復single capture context；禁止controller與detector同時存活。

### Batch 6：Potion engine

- 先測threshold、continuous、pending send、effect watch、out-of-potion與priority defer，再移動；每種command outcome、duplicate/unknown result及HP/MP同時held都需characterization test。
- Rollback：將engine state一次性還原controller；不得保留雙寫bridge。

### Batch 7：EXP capture

- 先測baseline、cursor、burst、checkpoint、executor cancel與OCR result/status，再移動。
- Rollback：恢復controller executor/job ownership；Stage 3 OCR services不動。

### Batch 8：Facade cleanup與final review

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
- MSS、GDI、MCI、worker、thread、process與executor各有唯一owner；HUD與EXP共享的capture port只由screen capture service關閉。
- Public facade、canonical object identity、module patch points與必要private shims通過manifest。
- 行為、timing、status、settings與OCRfixture維持characterization結果。
- 新手寫module各小於2,000行；controller LOC只記錄，不作成功門檻。
- Full、OCR slow、performance與獨立code review全部通過。
