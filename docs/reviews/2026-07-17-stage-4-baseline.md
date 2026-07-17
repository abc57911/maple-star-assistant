# Stage 4 AutoPotionController 拆分 Baseline

> 實作計畫：[Stage 4 AutoPotionController 拆分實作計畫](../superpowers/plans/2026-07-17-stage-4-auto-potion-controller-decomposition-plan.md)

## 環境

- 日期：2026-07-17
- Python：3.14.3
- Executable：`C:\Python314\python.exe`
- Performance命令：`python tools\verify.py performance`

## 結構

- `maple_star/controllers/auto_potion_controller.py`：7,723 LOC
- `AutoPotionController`：369 methods，其中public 23、private 346
- `self`寫入欄位：152
- `self.sct.grab()`：7個call sites，位於原始行3412、3920、5854、6934、7313、7470、7497
- Stage 4新增手寫module限制：各小於2,000 LOC
- Controller完成後只記錄LOC，不設硬縮減門檻

## 目前 resource owners

| Resource | Owner |
| --- | --- |
| MSS | `AutoPotionController.sct` |
| GDI capture | `AutoPotionController.direct_bar_capture_context` |
| Control hotkey worker | `AutoPotionController.control_hotkey_worker` |
| Potion action worker | `AutoPotionController.potion_action_worker` |
| OCR executor/future | `AutoPotionController.experience_ocr_executor`／job fields |
| Runtime child processes | `AutoPotionController.runtime_processes` |
| MCI aliases | `AutoPotionController._media_alias_paths` |
| Lie-detector alert thread | `AutoPotionController._lie_detector_alert_thread` |

## Runtime import baseline

```text
gamepad_controller
    -> auto_potion_controller
    -> runtime_processes

auto_potion_controller
    -> runtime_processes

runtime_processes child entries
    -> auto_potion_controller._create_auto_potion_controller (call-time import)
```

目前存在controller/runtime concrete雙向dependency。Task 1完成門檻是clean interpreter任意import順序與Windows spawn都不形成reverse module edge。

## Patch 與 private compatibility baseline

- `maple_star.controller`與canonical controller維持同一module identity。
- 既有module patch literals共22個：facade alias 12個、canonical controller path 10個，全部分類為dynamic adapter。
- 直接由tests或production使用的private methods共110個，另有3個private state attributes（含factory partial-init flag）；均由AST consumer scan與manifest等值比較鎖定。
- 152個stored fields、facade/runtime canonical re-exports、resource owners與7個MSS call sites均由Stage 4 contract tests鎖定完整集合。
- Constructor及23個public methods的參數順序、kind、defaults與annotations均鎖定；Task 1新增dependency只能是設計核准的keyword-only參數。

## Performance baseline

- GUI startup samples：0.9329s、0.5306s、0.5423s
- GUI startup median：0.5423s
- Page-switch sample count：25
- Page-switch p95：14.5783ms
- Page-switch max：18.3249ms
- Control timing sample count：970
- Control lateness p95：0.1254ms
- Control lateness max：0.3965ms
- Control max status gap：100.2045ms
- 結果：全部通過既有performance gate

## Task 0 邊界

- 只新增leaf contracts、manifest、characterization tests、baseline與文件索引。
- 不修改controller production behavior，不建立runtime/capture/media資源。
- 後續比較使用相同Python類型、硬體與Windows電源模式。
