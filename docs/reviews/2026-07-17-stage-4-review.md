# Stage 4 AutoPotionController 拆分 Review

> Baseline：[Stage 4 AutoPotionController 拆分 Baseline](2026-07-17-stage-4-baseline.md)

## 結果

- `auto_potion_controller.py`：7,723 → 5,733 LOC，減少1,990行（25.8%）。
- Controller methods：369 → 390；public 23 → 29；private 346 → 361。新增 methods 主要是永久相容 shim，domain/resource ownership 已移出。
- Controller stored fields：152 → 115，減少37個（24.3%）。
- `self.sct.grab()`：7 → 0。
- Stage 4 新增手寫 module 最大為`hud_bar_detector.py` 1,973行，全部低於2,000行門檻。

## Canonical ownership

| Resource / domain | Owner |
| --- | --- |
| MSS backend | `ScreenCaptureService._backend` |
| GDI direct capture / HUD geometry | `HudBarDetector` |
| Control hotkey worker | `ControlHotkeyCoordinator` |
| Potion decision / command state | `PotionEngine` |
| Potion SendInput worker | `AutoPotionController.potion_action_worker` |
| EXP OCR executor、future、signature、cursor state | `ExperienceCaptureCoordinator` |
| Runtime child processes | `AutoPotionController.runtime_processes` |
| MCI aliases / alert thread | `MediaPlaybackService` |

`ExperienceCaptureCoordinator`借用既有 image/HUD geometry，不持有或關閉MSS。Controller保留公開 reset/toggle、runtime status application、potion priority與GUI publish；舊 private 存取點由descriptor或薄shim維持相容。

## 結構與相容

- Runtime API、factory、composition與spawn child entrypoints已拆開，移除controller/runtime concrete reverse import edge。
- 舊 facade import path、module identity、patch points、constructor與public signatures由manifest鎖定。
- Hotkey、media、screen capture、HUD、potion及EXP executor均只有一個 lifecycle owner。
- `PotionActionWorker`在實際送鍵前執行foreground guard，Engine只在completion result回來後提交cooldown/effect/held狀態。
- EXP executor submit/poll/result、job fields、signature建立與重複影像 gate已移至coordinator；cleanup逐資源best-effort且可重試cursor restore。

## 驗證證據

- Task 6 potion completion/foreground/controller shape：34個直接測試通過。
- Task 7 coordinator、EXP reader與spawn：170個直接測試通過，2個依條件skip。
- Task 7 EXP baseline/checkpoint/signature/pending/cleanup：直接案例通過。
- Final facade/contracts/cleanup gate：28個測試通過。
- `git diff --check`：通過；僅既有Windows LF/CRLF提示。
- 獨立review依Task分批執行；Critical findings為0，Important findings修正後才關閉該批。

依專案驗證規範，本次未重跑全套`python tools\verify.py`、`full`、`ocr-slow`或`performance`。前述命令僅在使用者明確要求時執行；本review不把未執行項目記為通過。

## Residual coupling

- Controller仍保留大量HUD/EXP private shim，以維持既有tests與外部consumer相容；manifest將其視為永久compatibility surface，不以無證據方式刪除。
- Controller methods數增加但stored state與resource owners明顯下降。後續若要再縮methods，應先遷移consumer，再同步縮減manifest，避免破壞patch seam。
