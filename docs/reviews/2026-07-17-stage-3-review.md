# Stage 3 OCR／GUI 拆分 Review

> 知識庫索引：[docs/INDEX.md](../INDEX.md)
> 比較基準：[Stage 3 Baseline](2026-07-17-stage-3-baseline.md)

## 結果

- `maple_star/models/experience.py`：5,162 → 29 LOC，縮小 99.4%。
- `maple_star/views/settings_gui.py`：3,854 → 2,679 LOC，縮小 30.5%。
- OCR manifest 維持 80 samples；PNG 維持 81 files。
- 所有新增手寫 module 均小於 2,000 LOC；最大為 `experience_text_parsing.py` 1,250 LOC。
- 舊公開 import path 與 symbol identity 由 `tests/public_facade_manifest.py`、clean `python -I` import-order tests 保護。

## OCR 責任分層

- `models/experience.py`：29 LOC 相容 aggregator，不含演算法或 stateful class 實作。
- `models/experience_constants.py`：OCR 常數。
- `models/experience_types.py`：跨層 frozen/mutable dataclass 型別。
- `models/experience_tracker.py`：經驗統計 tracker 與 formatter。
- `services/experience_text_parsing.py`：文字 traversal、parser、candidate ranking 與 continuity pure helpers。
- `services/experience_image_processing.py`：ROI、resize、mask、binary variant 與 bar estimate。
- `services/experience_pixel_ocr.py`：Pixel template、segmentation、classification 與 continuity guard。
- `services/experience_paddle_reader.py`：Paddle reader、fallback orchestration 與 spawn-safe worker entry。

## GUI 責任分層

- `views/settings_gui.py`：GUI lifecycle、狀態同步、callback 接線與舊屬性 facade。
- `views/gui_theme.py`：immutable theme/layout constants。
- `views/gui_presentation.py`：共用 widget factory、responsive layout、tooltip 與 Minimap 進階設定呈現。
- `views/pages/contracts.py`：frozen page context/ref contracts。
- `views/pages/{monitor,potion,minimap,combo,console}_page.py`：各頁 widget construction；builder 完成後才由 facade 發布 refs。
- lazy page placeholder、Monitor `after(250)` controls、partial failure cleanup/retry 與 close cancellation 均保留。

## Final performance

| 指標 | Baseline | Final | 結果 |
|---|---:|---:|---|
| GUI startup median | 0.7145s | 0.4806s | 通過 |
| Page-switch p95 | 20.4612ms | 13.5113ms | 通過 |
| Page-switch max | 24.8529ms | 18.3543ms | 通過 |
| Control lateness p95 | 0.2973ms | 0.1438ms | 通過 |
| Control lateness max | 0.9308ms | 0.4745ms | 通過 |
| Control max status gap | 100.5505ms | 100.1846ms | 通過 |

## 驗證證據

- `python tools\verify.py full`：698 tests，`OK (skipped=1)`，exit 0。
- `python tools\verify.py ocr-slow`：692 tests，`OK`；`pip check` 顯示 `No broken requirements found.`。
- `python tools\verify.py performance`：三個 benchmark 均 `passed: true`。
- `git diff --check`：exit 0；僅 Windows LF/CRLF 提示。

## Final code review

- 獨立 reviewer 未發現 Critical。
- 已修正 Minimap／Combo／Monitor controls 在 page-specific sync 失敗時先發布 refs 的 transaction 缺口。
- 已補 builder failure cleanup/retry、placeholder retention、Monitor retry、close cancellation、page-specific widget Protocol 與 canonical owner mapping tests。
- 修正後 GUI／facade 定向 48 tests 與 full 698 tests 全數通過；沒有剩餘 Important finding。

## Residual coupling

- `settings_gui.py` 仍擁有大量 Tk `Variable` 初始化與 `apply_to_settings()` schema mapping；這是 facade 的狀態 owner，Stage 3 未拆成另一套 view-model，避免改變保存語意。
- `gui_presentation.py` 的 mixin 依賴 facade 提供 root、狀態欄位與 callback；依賴方向單向，且不 import `settings_gui`。
- Pixel OCR template 本體仍在 `experience_pixel_templates.py`；屬 repository-maintained runtime 資料，不納入本階段演算法拆分。

## Git 狀態

- 本階段變更保持 unstaged、未 commit；未執行打包、tag 或 release。
