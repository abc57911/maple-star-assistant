# Stage 3：OCR 與 GUI 拆分設計

> 知識庫索引：[docs/INDEX.md](../../INDEX.md)
>
> 上層規格：[全專案 Code Review 與減肥設計](2026-07-17-project-slimming-design.md)

## 狀態與決策

- 狀態：待獨立規格審查與使用者書面確認；未通過前不得修改 production code。
- 方案：contract-first，只凍結 repository、文件與既有 entrypoint 實際使用的 API。
- 相容層：保留 `maple_star.controller`、`maple_star.experience` 與 import-mode `maple_gamepad_macro` 的 module alias identity。
- Internal test seam：底線 helper、logger 與 suppression patch path 不屬於公開 API；函式搬家時，測試改 patch canonical owner，不保證舊 aggregator patch interception。
- 行為邊界：不改 OCR 演算法、GUI 外觀、設定、IPC schema、callback 順序或 resource ownership。
- 尺寸門檻：`models/experience.py` 與 `views/settings_gui.py` 各縮小至少 30%；新增手寫模組均小於 2,000 行。

## 非目標

- 不重寫 controller alias、不重設 GUI、不新增設定、不改 worker 數量。
- 不調整 ROI、threshold、parser、continuity guard、Pixel template 或 Paddle model。
- 不把 `cv2`、`numpy`、`time`、logger、imported module 或無 consumer 的名稱凍結成 API。
- 不以 wrapper 吞例外、複製 dataclass、延遲 import failure 或轉移 cleanup 責任換取拆檔。

## Facade manifest

新增 `tests/public_facade_manifest.py` 作為資料檔，新增 `tests/test_public_facades.py` 執行 assertion。分類定義：

- `public`：文件、package root 或 production entrypoint 使用；保留 path、object identity 與 signature。
- `test-only`：repository test 直接 import；保留 import 與 object identity，但不是第三方承諾。
- `patch-only`：測試依賴 patch interception；只在指定 canonical module 保證生效。
- `incidental`：無 repository consumer；不寫入 required manifest，可在拆分時消失。

### Module alias

| entrypoint | canonical module | assertion |
|---|---|---|
| `maple_star.controller` | `maple_star.controllers.auto_potion_controller` | clean interpreter 中兩種 import order 皆為同一 module object |
| `maple_star.experience` | `maple_star.models.experience` | clean interpreter 中兩種 import order 皆為同一 module object |
| `maple_gamepad_macro`（非 `__main__`） | `maple_star.controllers.gamepad_controller` | clean interpreter 中兩種 import order 皆為同一 module object |

`maple_star.gui`、`maple_star.settings` 是 star-import wrapper；`auto_potion` 是多來源 re-export，三者不要求 module identity。`maple_gamepad_macro` 以 `__main__` 執行時仍只呼叫 canonical `main()`。

### Package root `maple_star`

`maple_star.__all__` 必須精確等於下列 12 個 `public` symbol；identity 皆與 canonical owner 相同：

| symbols | canonical owner |
|---|---|
| `AutoPotionController` | `controllers.auto_potion_controller` |
| `loading_screen_metrics`、`normalize_bar_percent` | `services.bar_detection` |
| `AutoPotionSettings`、`SETTINGS_PATH`、`app_base_dir`、`load_settings`、`save_settings` | `models.settings` |
| `key_down`、`key_up`、`parse_vk_key`、`tap_hotkey` | `adapters.win_input` |

### `maple_star.controller`

| symbol | 分類 | canonical owner |
|---|---|---|
| `AutoPotionController` | public | `controllers.auto_potion_controller` |
| `loading_screen_metrics` | public | `services.bar_detection` |
| `normalize_bar_percent` | public | `services.bar_detection` |
| `AUTO_DRINK_POTION_CHECK_SOUND_PATH` | test-only | `controllers.auto_potion_controller` |
| `AUTO_DRINK_START_SOUND_PATH` | test-only | `controllers.auto_potion_controller` |
| `AUTO_DRINK_STOP_SOUND_PATH` | test-only | `controllers.auto_potion_controller` |
| `AUTO_PICKUP_START_SOUND_PATH` | test-only | `controllers.auto_potion_controller` |
| `AUTO_PICKUP_STOP_SOUND_PATH` | test-only | `controllers.auto_potion_controller` |
| `ExperienceOcrJob` | test-only | `models.controller_state` |
| `LIE_DETECTOR_ALERT_SOUND_PATH` | test-only | `controllers.auto_potion_controller` |
| `MINIMAP_CRUISE_START_WAV_PATH` | test-only | `controllers.auto_potion_controller` |
| `MINIMAP_CRUISE_STOP_WAV_PATH` | test-only | `controllers.auto_potion_controller` |
| `BarDetectionDebug` | test-only | `models.controller_state` |
| `bgra_image_to_ppm_data` | test-only | `services.bar_detection` |

以下為 `patch-only`，其 canonical module 固定為 `controllers.auto_potion_controller`：`ctypes.windll`、`key_down`、`key_up`、`save_settings`、`tap_hotkey`、`threading.Thread`、`time.monotonic`、`time.sleep`、`user32.GetAsyncKeyState`、`winsound.Beep`、`winsound.MessageBeep`、`winsound.PlaySound`。因 facade 是 module alias，舊 patch path 必須持續攔截 canonical globals。

### `maple_star.experience`

下表的 canonical owner 是 Stage 3 完成狀態；每個 symbol 在中間批次仍由 aggregator re-export 同一 object。

| symbols | 分類 | canonical owner |
|---|---|---|
| `ExperienceEfficiencyTracker` | public | `models.experience_tracker` |
| `ExperienceSnapshot`、`ExperienceTextReading`、`ExperienceOcrImage` | public | `models.experience_types` |
| `read_experience_burst_frames_in_worker`、`read_experience_tooltip_in_worker` | public | `services.experience_paddle_reader` |
| `ExperienceOcrContinuityHint` | public | `models.experience_types` |
| `ExperiencePixelFontAttempt` | test-only | `models.experience_types` |
| `PaddleExperienceTextReader` | public | `services.experience_paddle_reader` |
| `EXP_LEVEL_WRAP_HIGH_PERCENT` | public | `models.experience_constants` |
| `EXP_RATE_1H_HALF_LIFE_SECONDS` | test-only | `models.experience_constants` |
| `PADDLEOCR_DETECTION_MODEL_NAME`、`PADDLEOCR_LANGUAGE`、`PADDLEOCR_RECOGNITION_MODEL_NAME` | test-only | `models.experience_constants` |
| `format_exp`、`format_duration`、`format_eta`、`format_exp_10m_gain`、`format_exp_rate`、`format_ocr_success_rate`、`format_rate_confidence` | public | `models.experience_tracker` |
| `read_stat_window_exp_in_worker` | test-only | `services.experience_paddle_reader` |
| `parse_stat_window_exp_text`、`parse_experience_tooltip_text`、`parse_exp_percent_text`、`parse_current_exp_text` | test-only | `services.experience_text_parsing` |
| `reading_from_paddle_result`、`reading_from_stat_window_text`、`reading_from_tooltip_paddle_result`、`reading_from_tooltip_text`、`extract_paddle_text_items` | test-only | `services.experience_text_parsing` |
| `prepare_experience_ocr_image`、`prepare_experience_tooltip_ocr_images`、`prepare_experience_ocr_images`、`estimate_experience_bar_percent` | test-only | `services.experience_image_processing` |
| `_binarize_experience_text`、`_clean_experience_text_mask`、`_erase_experience_green_bar_to_text_image`、`_suppress_experience_green_bar_background` | test-only | `services.experience_image_processing` |
| `_apply_experience_ocr_continuity_guard` | test-only | `services.experience_pixel_ocr` |
| `_experience_ocr_continuity_status` | test-only | `services.experience_text_parsing` |
| `_decode_experience_pixel_font_text_candidates`、`_experience_pixel_font_runtime_attempts`、`_read_experience_pixel_font_adaptive`、`_pixel_font_text_reading`、`_select_pixel_font_success`、`_structured_pixel_font_text_candidates` | test-only | `services.experience_pixel_ocr` |
| `_experience_should_read_secondary_roi` | test-only | `services.experience_paddle_reader` |
| `_experience_text_structure_score` | test-only | `services.experience_text_parsing` |
| `suppress_subprocess_windows` | test-only | `services.experience_paddle_reader` |

未列出的底線 helper 是 `incidental`。現有五組舊 patch seam 的處理如下：

| 舊 patch path | 決策 | 新 canonical patch path |
|---|---|---|
| `models.experience._decode_experience_pixel_font_text_candidates` | 不保留 patch interception；保留 test-only re-export identity | `services.experience_pixel_ocr...` |
| `models.experience._read_experience_pixel_font_adaptive` | 同上 | `services.experience_pixel_ocr...` |
| `models.experience.suppress_subprocess_windows` | 同上 | `services.experience_paddle_reader...` |
| `models.experience.reading_from_tooltip_paddle_result` | 同上 | `services.experience_text_parsing...`，Paddle reader 以 module import 查找 |
| `models.experience.log_experience_debug` | 舊名稱可消失，不列 re-export | `services.experience_paddle_reader.log_experience_debug` |

每次移動 seam 與呼叫端必須同批更新測試。這些決策只縮小 internal testing surface，不改 runtime output。

### `maple_star.settings`

所有 required symbol 的 canonical owner 均為 `models.settings`：

| symbol | 分類 |
|---|---|
| `AutoPotionSettings`、`SETTINGS_PATH`、`app_base_dir`、`load_settings`、`save_settings` | public |
| `COMBO_SCRIPT_HOLD_JUMP_ATTACK_LOOP`、`COMBO_SCRIPT_REPEATING_JUMP_SKILL`、`COMBO_SCRIPT_SINGLE_JUMP_SKILL` | test-only |
| `MINIMAP_CRUISE_DEFAULT_LIE_DETECTOR_ALERT_VOLUME_PERCENT`、`MINIMAP_CRUISE_DEFAULT_STATIONARY_MIN_FORWARD_PIXELS` | test-only |
| `normalize_controller_button_name` | test-only |

### `maple_star.gui`

| symbol | 分類 | canonical owner |
|---|---|---|
| `AutoPotionSettingsGui` | public | `views.settings_gui` |
| `GuiConsoleWriter` | public | `views.settings_gui` |

`FlowLayout` 無 repository import，列為 `incidental`，不進 manifest。

### `auto_potion`

`auto_potion.__all__` 必須精確等於下表，不增加 incidental export：

| symbols | 分類 | canonical owner |
|---|---|---|
| `AutoPotionController` | public | `controllers.auto_potion_controller` |
| `loading_screen_metrics`、`normalize_bar_percent` | public | `services.bar_detection` |
| `AutoPotionSettings`、`SETTINGS_PATH`、`app_base_dir`、`load_settings`、`save_settings` | public | `models.settings` |
| `AutoPotionSettingsGui`、`GuiConsoleWriter` | public | `views.settings_gui` |
| `key_down`、`key_up`、`parse_vk_key`、`tap_hotkey` | public | `adapters.win_input` |
| `event_to_hotkey`、`pressed_detectable_vks`、`vk_to_key_name` | public | `adapters.key_capture` |

### `maple_gamepad_macro`

| symbol | 分類 | canonical owner |
|---|---|---|
| `DEFAULT_ATTACK_KEY_HOLD_SECONDS` | test-only | `controllers.gamepad_controller` |
| `HoldJumpAttackLoopMacro` | test-only | `controllers.gamepad_controller` |
| `build_controller_button_bindings` | test-only | `controllers.gamepad_controller` |
| `effective_hold_jump_attack_interval_seconds` | test-only | `controllers.gamepad_controller` |
| `effective_repeating_jump_interval_seconds` | test-only | `controllers.gamepad_controller` |
| `first_enabled_controller_binding` | test-only | `controllers.gamepad_controller` |
| `sync_runtime_settings_before_controller_events` | test-only | `controllers.gamepad_controller` |

### Manifest assertion semantics

- `public` 與 `test-only`：`getattr(entrypoint, name) is getattr(canonical, name)`。
- wrapper `__all__`：若 module 定義 `__all__`，驗證精確集合；未定義者只驗證 required names，不凍結 `dir()`。
- alias：分別啟動 `python -I -c`，script 先用 resolved repository root literal 執行 `sys.path.insert(0, root)`，再測 canonical-first 與 facade-first；比對 `is`、`sys.modules`，並要求 alias object 的 `__name__` 等於 canonical module name。不得依賴 cwd 或外部 `PYTHONPATH`。
- standalone import：每個新 module 以 clean process 直接 import，且 `sys.modules` 不得因反向依賴出現 partially initialized aggregator。
- repository consumer 掃描出現新直接 import 時，必須分類為 `public` 或 `test-only`；只有無 consumer 的洩漏名稱可標 `incidental`。

## OCR 模組與單向 DAG

先建立 leaf types/constants，再移任何 consumer。每個 dataclass 只定義一次；aggregator 只做 re-export。所有新 module 禁止 import `maple_star.models.experience`。

```text
models.experience_constants ───────────> stdlib
models.experience_types ───────────────> constants + stdlib + numpy typing
models.experience_tracker ─────────────> types + constants
services.experience_text_parsing ──────> types + constants
services.experience_image_processing ──> types + constants
services.experience_pixel_ocr ─────────> types + constants + text_parsing + image_processing + experience_pixel_templates
services.experience_paddle_reader ─────> types + constants + parsing + image_processing + pixel_ocr + debug_logging
models.experience (aggregator) ─────────> all extracted modules
```

禁止任何箭頭反向指向 aggregator；`services` 之間只能依上圖方向 import。

### 型別與常數 owner

- `models/experience_types.py`：`ExperienceTextReading`、`ExperienceOcrImage`、`ExperienceOcrContinuityHint`、`ExperiencePixelFontAttempt`、`ExperienceTextCandidate`、`ExperienceSample`、`RateEstimate`、`PendingExperienceRebase`、`PendingExperienceBaseline`、`ExperienceSnapshot`。
- `models/experience_constants.py`：目前 26–150 行所有 `EXP_*`、`PADDLEOCR_*` 與 `PADDLEOCR_ENV_DEFAULTS`。`ExperienceOcrImage.bar_crop_left_ratio` 由這個 leaf import `EXP_OCR_BAR_CROP_LEFT_RATIO`，不依賴 aggregator。
- `models/experience_tracker.py`：formatters、`ExperienceEfficiencyTracker` 及 tracker 私有計算。
- `services/experience_text_parsing.py`：Paddle result traversal、normalization、stat/tooltip/general parser、candidate ranking，以及 parser、Pixel 與 burst selection 共用的 continuity group selection/status/rank pure helpers。
- `services/experience_image_processing.py`：ROI coercion/crop、resize、green-bar mask、binary variants、bar estimation。
- `services/experience_pixel_ocr.py`：continuity guard、attempt generation、Pixel prototypes/feature weights/template cache、template matching、glyph segmentation/classification、selection；continuity status/rank 由 parsing 單向提供。
- `services/experience_paddle_reader.py`：reader、runtime suppression、worker cache/entry、跨策略 orchestration。
- `models/experience.py`：相容 aggregator；完成後不得再有演算法或 stateful class 實作。

## OCR 公開契約

### Tracker

`ExperienceEfficiencyTracker` 的 constructor 與 public methods 原樣保留：

```python
ExperienceEfficiencyTracker() -> None
reset() -> None
clear_transient_rejection() -> None
record_ocr_result(success: bool) -> None
record_exp_10m_checkpoint(current_exp: int) -> None
add_reading(
    now: float,
    current_exp: int,
    percent: float | None,
    *,
    confidence: float | None = None,
    require_initial_confirmation: bool = False,
) -> bool
snapshot(now: float) -> ExperienceSnapshot
level_total_deviation_ratio(current_exp: int | None, percent: float | None) -> float | None
```

不新增 `reading/sample` wrapper，不改 mutable state、status 字串、sample acceptance 或 reset semantics。

### Reader 與 worker

```python
PaddleExperienceTextReader() -> None
read_burst(images, *, continuity_hint=None) -> ExperienceTextReading
read_burst_frames(image_frames, *, continuity_hint=None) -> ExperienceTextReading
read(image, *, continuity_hint=None) -> ExperienceTextReading
read_stat_window_exp(image) -> ExperienceTextReading
read_tooltip_exp(image, *, continuity_hint=None) -> ExperienceTextReading

read_experience_burst_frames_in_worker(image_frames, continuity_hint=None) -> ExperienceTextReading
read_stat_window_exp_in_worker(image) -> ExperienceTextReading
read_experience_tooltip_in_worker(image, continuity_hint=None) -> ExperienceTextReading
```

- worker entry 的 canonical `__module__` 是 `maple_star.services.experience_paddle_reader`；legacy aggregator re-export 同一 function object。
- 三個 entry 均為 module-level、可 pickle；輸入/輸出 dataclass 可用 `multiprocessing.get_context("spawn")` round-trip。
- `_EXPERIENCE_WORKER_READER` global 在 parent 可存在但值必須為 `None`；非空 reader instance 只存在 spawned child 的 canonical module，首次 worker call 初始化一次；parent import/submit 不得建 Paddle model。
- 真實 `ProcessPoolExecutor(max_workers=1, mp_context=spawn)` characterization 以 fake reader/不載模型路徑驗證回傳 `ExperienceTextReading`、type identity 與第二次 call reuse child cache。

### Paddle 錯誤與 fallback

- `_ensure_ocr()`：`ocr` 非空回 `True`；`unavailable_reason` 非空永久回 `False`，不重試同一 reader。
- import Paddle 失敗：`success=False`，`reason="未安裝 PaddleOCR：{exc}"`；stat/tooltip 額外保留各自 `source`。
- 新 constructor 只有拋 `TypeError` 時才嘗試 legacy `PaddleOCR(lang=..., use_angle_cls=False, show_log=False)`；其他 exception 不降級。
- 新/舊 constructor 失敗均 cache `unavailable_reason="PaddleOCR 初始化失敗：{exc}"`，不洩漏 partially initialized `ocr`。
- general `_read_with_paddle` 的 predict exception 設 `reason="PaddleOCR 辨識失敗：{exc}"` 並中止該 variant pass；是否進 retry 完全沿用現有 `_should_retry_experience_ocr`。
- stat/tooltip predict exception 分別產生 `能力值 EXP OCR 辨識失敗：...`／`浮動 EXP OCR 辨識失敗：...`，記錄 failure 後繼續下一 variant；成功立即依既有規則返回。
- stat/tooltip/general 的 `source`、`reason`、`confidence`、telemetry 與最佳 failure selection 不變。
- `suppress_subprocess_windows` 與 output suppression 在正常、body exception、constructor exception 三條路徑都必須於 `finally` 恢復 `subprocess.Popen` 與 stdout/stderr FD。
- `_log_tooltip_ocr_telemetry` 仍隔離 logging exception；logging failure 不改 reader result。

## GUI builder 契約

### 共用邊界

- 新增 `views/gui_theme.py`：只放 immutable color/font/size/layout constants，不 import `settings_gui`。
- 新增 `views/pages/contracts.py`：page-specific frozen context/ref dataclass 與窄 `Protocol`；不 import controller/settings store。
- 新增 `views/pages/{monitor,potion,minimap,combo,console}_page.py` 與 `views/pages/__init__.py`。
- 所有 builder 只在 Tk event loop 執行：`build_x_page(parent: ctk.CTkFrame, context: XPageContext) -> XPageRefs`。
- context 只含該頁 `Variable`、callback、純 widget factory；禁止傳 `AutoPotionSettingsGui`、controller、queue 或含未使用 methods 的通用 service locator。
- builder 不回寫 GUI。`AutoPotionSettingsGui` 收到完整 refs 後一次性保存；refs 的 widget lifecycle 仍由 GUI/root 擁有。

### 精確頁面 surface

| builder | context 欄位 | refs |
|---|---|---|
| `build_monitor_page` | EXP enable/reset vars/callbacks、診斷 vars、capture callbacks、status/runtime text vars、compact/topmost/console callbacks、`MonitorWidgets` | `monitor_frame`、`exp_section`、`detection_section`、`bar_preview_labels`、`monitor_responsive_relayout`、`panel_mode_button`、`topmost_button`、`console_restore_button`、初始 `full_panel_widgets` |
| `build_monitor_controls` | `active_profile`、toggle/emergency/experience-toggle/experience-reset/character-stat/pickup-toggle/pickup-key vars、pickup enabled var/callback、key-detection callback、`profile_names: Callable[[], list[str]]`、switch/create/delete/import/export callbacks、`MonitorControlsWidgets` | `hotkey_section`、`profile_section`、`profile_select`、新增至 `full_panel_widgets` 的 tuple |
| `build_potion_page` | auto-drink callback；HP/MP 各自 enabled/threshold/threshold_text/key/cooldown/continuous/stop_margin/current vars；key-detection、percent-apply callbacks；`PotionWidgets` | `header`、`cards`、`hp_section`、`mp_section`、兩個 threshold entry |
| `build_minimap_page` | toggle/attack/status vars；boundary、extra-settings、key-detection、collapse callbacks；`MinimapWidgets` | `section`、`body`、`title_label`、toggle/attack entries、primary/actions frames |
| `build_combo_page` | A/B `ComboSlotContext`（enabled/controller/script/jump/skill/attack/delay/hold/interval vars + description callback）；collapse、visibility callbacks；`ComboWidgets` | `section`、`body`、`title_label`、A/B card 與 slot-specific entry/select refs |
| `build_console_page` | clear callback；`ConsoleWidgets` | `section`、`title_label`、`clear_button`、`frame`、`container` |
| `build_console_text` | console font/color constants | `ConsoleTextRefs(text, scrollbar)` |

每個 `*Widgets` Protocol 只列該頁實際使用的 `section/title_label/label/entry/checkbox/button/responsive_columns` 工廠；combo 另有 `seconds_stepper/script_select/controller_button_select`，不得暴露 settings、controller 或其他頁方法。

### Lazy-build atomicity

1. `show_page` 建 placeholder，排一個 `after(1)`；切頁先 cancel 前一個 id。
2. `_finish_page_build` 先確認 `not closed` 且仍為 active page；不符合時保留未建立狀態，placeholder 可於下次切入重用或重建。
3. 呼叫 builder 時 placeholder 仍保留；builder 完整成功後，GUI 才保存 refs、destroy placeholder、加入 `page_built`，再執行既有頁面同步 callback，最後排 height sync。
4. builder exception：destroy 此次建立的 top-level page children、清除 pending refs，不加入 `page_built`，保留/重建 placeholder，讓下次切入可 retry；exception 不吞掉，交由既有 Tk error boundary/logging。
5. cancel/close：cancel `page_build_after_id`、destroy placeholder/partial widgets；不呼叫 callback，不留下 refs。
6. callback 綁定發生在 widget 全部建立但 refs 尚未 publish 時；首次 publish 後同步順序固定為：page-specific visibility/collapse sync → console/height sync。
7. `Console` shell 與 `tk.Text` 仍分兩階段 lazy build；只有 shell 完成才 publish `ConsolePageRefs`，只有 text 完成才設定 `self.console`。
8. Monitor 保留既有兩階段 timing：`build_monitor_page` 在 constructor 建立主要 EXP／diagnostic/runtime 區；`monitor_controls_after_id = root.after(250, ...)` 才建立全域熱鍵與設定檔。不得合併兩階段。
9. Monitor controls callback 先檢查 `not closed`、page 存在且 `profile_select is None`。builder 完整成功後才一次 publish `profile_select` 並 prepend `full_panel_widgets`；若失敗，destroy 本次兩個 section、保持 refs 未設定，重新排一次 `after(250)` 供 retry，例外仍交由既有 Tk error boundary。
10. `close()` 必須 cancel `monitor_controls_after_id` 與 `page_build_after_id`；cancel 後不得執行 builder 或 publish refs。第二階段成功後先依 `compact_experience_mode` 決定 section visibility，再排既有 height sync。

## 實作批次與 rollback

每批先保留 baseline，再移動 symbol；aggregator 的 import 順序固定為 `constants -> types -> tracker -> parsing -> image -> pixel -> paddle`，只 import 已存在的 module。

### Batch 0：Baseline 與 facade

- 新增：`tests/public_facade_manifest.py`、`tests/test_public_facades.py`、`docs/reviews/2026-07-17-stage-3-baseline.md`。
- 修改：`docs/INDEX.md`，加入 baseline 文件索引。
- 命令：`python -m unittest tests.test_public_facades`。
- Rollback：只刪本批三個新檔並還原索引；production 不變。

### Batch 1：Leaf schema

- 新增：`maple_star/models/experience_constants.py`、`maple_star/models/experience_types.py`、`tests/test_experience_module_boundaries.py`。
- 修改：`maple_star/models/experience.py`，移動目前 26–159 行一般 constants 至 constants leaf、185–290 行 dataclasses 至 types leaf並 re-export；160–182 行 Pixel prototypes/feature weights/template cache 暫留 aggregator。
- 命令：`python -m unittest tests.test_experience_module_boundaries tests.test_public_facades`。
- Tests：defaults/equality、identity、pickle round-trip、兩種 alias import order、所有新 module standalone import。
- Rollback：還原 aggregator 定義，刪兩個 leaf 與 boundary test；保留 Batch 0。

### Batch 2：Tracker

- 新增：`maple_star/models/experience_tracker.py`。
- 修改：`maple_star/models/experience.py`、`tests/test_experience_module_boundaries.py`。
- 移動：全部 formatter、`ExperienceEfficiencyTracker` 與其完整 private methods。
- 命令：`python -m unittest tests.test_experience tests.test_experience_module_boundaries`。
- Rollback：還原 class/formatters，刪 tracker，還原本批 boundary assertions；保留 leaf schema。

### Batch 3：Parsing

- 新增：`maple_star/services/experience_text_parsing.py`。
- 修改：`maple_star/models/experience.py`、`tests/test_experience.py`、`tests/test_experience_module_boundaries.py`。
- 移動：result traversal、reading constructors、normalization、stat/tooltip/general parser、candidate ranking、`_select_continuity_compatible_reading_group`、`_experience_ocr_continuity_status` 與 `_continuity_group_rank`；更新 parser patch owner。
- 命令：`python -m unittest tests.test_experience tests.test_experience_module_boundaries`。
- Rollback：還原 parsing symbols與舊 test patch path，刪 parsing module。

### Batch 4：Image processing

- 新增：`maple_star/services/experience_image_processing.py`。
- 修改：`maple_star/models/experience.py`、`tests/test_experience_module_boundaries.py`。
- 移動：coercion、ROI/crop/resize、green suppression、binary variants、bar estimation。
- 命令：`python -m unittest tests.test_experience tests.test_experience_module_boundaries`；另依 OCR gate 執行 manifest 全集合。
- Rollback：還原 image symbols/import，刪 image module。

### Batch 5：Pixel OCR

- 新增：`maple_star/services/experience_pixel_ocr.py`。
- 修改：`maple_star/models/experience.py`、`tests/test_experience.py`、`tests/test_experience_module_boundaries.py`。
- 移動：160–182 行 Pixel prototypes/feature weights/template cache，以及 continuity guard、attempts、glyph/template/candidate/selection；由 parsing import continuity status/rank，並更新兩個 pixel patch owner。
- 命令：`python -m unittest tests.test_experience tests.test_experience_module_boundaries`；另依 OCR gate 執行 manifest 全集合。
- Rollback：還原 pixel symbols與舊 test seam，刪 pixel module。

### Batch 6：Paddle reader 與 worker

- 新增：`maple_star/services/experience_paddle_reader.py`、`tests/test_experience_worker_spawn.py`。
- 修改：`maple_star/models/experience.py`、`maple_star/release_ocr_smoke.py`、`tests/test_experience.py`、`tests/test_release_ocr_smoke.py`、`tests/test_experience_module_boundaries.py`。
- 移動：reader、suppression、worker cache/entry、跨策略 orchestration；更新 suppression/parser/logger patch owner 與 release smoke canonical import。
- 命令：`python -m unittest tests.test_experience tests.test_experience_worker_spawn tests.test_experience_module_boundaries tests.test_release_ocr_smoke`。
- Tests：constructor/failure cache、variant fallback、suppression restoration、真實 spawn、child cache reuse、parent reader remains `None`。
- Rollback：還原 reader/worker/release smoke import 與 patch path，刪 paddle module及 spawn test；worker canonical path 同批回退。

### Batch 7：GUI contracts 與 theme

- 新增：`maple_star/views/gui_theme.py`、`maple_star/views/pages/contracts.py`、`maple_star/views/pages/__init__.py`、`tests/test_gui_page_builders.py`。
- 修改：`maple_star/views/settings_gui.py`，改由 leaf theme import immutable constants；尚不改 dispatch。
- 命令：`python -m unittest tests.test_gui_page_builders tests.test_gui_notice_position`。
- Rollback：把 constants 還原到 settings GUI，刪四個新檔。

### Batch 8：Console 與 Potion

- 新增：`maple_star/views/pages/console_page.py`、`maple_star/views/pages/potion_page.py`。
- 修改：`maple_star/views/settings_gui.py`、`tests/test_gui_page_builders.py`、`tests/test_gui_notice_position.py`。
- 命令：`python -m unittest tests.test_gui_page_builders tests.test_gui_notice_position`。
- Tests：console shell/text 兩階段、scrollbar refs、clear callback、potion vars/key/percent callbacks、exception cleanup/retry。
- Rollback：還原 methods/dispatch/refs，刪兩頁檔；保留 contracts/theme。

### Batch 9：Minimap 與 Combo

- 新增：`maple_star/views/pages/minimap_page.py`、`maple_star/views/pages/combo_page.py`。
- 修改：`maple_star/views/settings_gui.py`、`tests/test_gui_page_builders.py`、`tests/test_gui_notice_position.py`。
- 移動：main builders 與 combo-specific row/select/stepper helpers。
- 命令：`python -m unittest tests.test_gui_page_builders tests.test_gui_notice_position`。
- Tests：collapse/visibility、callback binding、responsive layout、exception cleanup/retry。
- Rollback：還原 methods/dispatch/refs，刪兩頁檔。

### Batch 10：Monitor 與 final review

- 新增：`maple_star/views/pages/monitor_page.py`、`docs/reviews/2026-07-17-stage-3-review.md`。
- 修改：`maple_star/views/settings_gui.py`、`tests/test_gui_page_builders.py`、`tests/test_gui_notice_position.py`、`docs/project-structure.md`、`docs/INDEX.md`。
- 移動：primary monitor builder 與獨立 `build_monitor_controls`；保留 `after(250)`。
- 命令：`python -m unittest tests.test_gui_page_builders tests.test_gui_notice_position`，再執行下方 performance gate。
- Tests：primary refs、delayed controls refs、cancel/close、exception retry、compact visibility、settings/profile sync。
- Rollback：還原兩階段 monitor methods/dispatch/refs，刪頁檔與 final review，還原 structure/index；保留已通過批次與 baseline。

每批新增 module 都跑 clean-process standalone-import gate。任何批次若 characterization 顯示輸出、timing 或 ownership 差異，只回退該批，不順手改演算法。

## 驗證與量測

### Batch 0 前基準

- 在同一 checkout、Python、硬體與電源模式記錄：
  - `python tools\verify.py performance` 的 startup 三次與 GUI latency；
  - `models/experience.py`、`views/settings_gui.py` 的實體 LOC；
  - `tests/fixtures/experience_ocr/manifest.json` 的 sample count 與實際 PNG count。
- OCR fixture gate 永遠以 manifest 全集合為準；不硬編「82 個」。manifest 外 PNG 另列，不假設為有效 sample。

### 每批

- targeted unittest module/case；
- `python tools\verify.py full`；
- facade、兩種 import order、standalone import；
- `git diff --check`。

### OCR 批次 1–6

- `python tools\verify.py ocr-slow`；
- manifest-driven fixtures、Pixel template、Paddle constructor/fallback；
- batch 1 與 batch 6 各跑 dataclass pickle；batch 6 跑真實 spawn worker characterization。

### GUI 批次 7–10

- `tests/test_gui_notice_position.py` 的 import、position、lazy page、settings synchronization 與新增 failure/retry tests；
- `python tools\verify.py performance`；完成後以 batch 0 相同環境比較 startup/page-switch，不接受超過既有 gate 的 regression。

## 成功條件

- manifest 所有 `public`、`test-only`、`patch-only` assertion 通過；incidental 名稱不被誤凍結。
- OCR output、Paddle fallback、spawn IPC、GUI callback/lazy lifecycle、設定與 ownership 無 regression。
- `experience.py` 與 `settings_gui.py` 各縮小至少 30%，新增手寫模組各小於 2,000 行。
- aggregator 無演算法實作，新 module 無反向 import/cycle。
- full、ocr-slow、performance、facade 與 standalone-import gates 全數通過。

## 停止條件

- 新 module 必須反向 import aggregator 才能運作。
- GUI context 必須取得整個 GUI/controller/queue 才能建頁。
- spawn worker function 無法保持 module-level pickle 或 parent 被迫初始化 Paddle。
- 需要改 OCR output、設定 schema、callback timing 或 ownership 才能通過測試。

命中任一項即停止該批、回退其變更，另提新設計，不把行為修正混入結構拆分。
