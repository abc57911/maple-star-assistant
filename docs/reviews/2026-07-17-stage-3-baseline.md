# Stage 3 OCR／GUI 拆分 Baseline

> 實作計畫：[Stage 3 OCR 與 GUI 拆分實作計畫](../superpowers/plans/2026-07-17-stage-3-ocr-gui-decomposition-plan.md)

## 環境

- 日期：2026-07-17
- Python：3.14.3
- Executable：`C:\Python314\python.exe`
- 驗證命令：`python tools\verify.py performance`

## 結構

- `maple_star/models/experience.py`：5,162 LOC
- `maple_star/views/settings_gui.py`：3,854 LOC
- OCR manifest：80 samples
- OCR PNG：81 files；manifest 外圖片不視為有效 sample

30% 縮減完成門檻：

- `experience.py` 最多 3,613 LOC
- `settings_gui.py` 最多 2,697 LOC
- 新增手寫 module 各小於 2,000 LOC

## Performance baseline

- GUI startup samples：0.9813s、0.6223s、0.7145s
- GUI startup median：0.7145s
- Page-switch sample count：25
- Page-switch p95：20.4612ms
- Page-switch max：24.8529ms
- Control timing sample count：961
- Control lateness p95：0.2973ms
- Control lateness max：0.9308ms
- Control max status gap：100.5505ms
- 結果：全部通過既有 performance gate

## Batch 0 邊界

- 只新增 facade manifest、characterization tests 與本 baseline。
- 不修改 production code。
- 後續比較使用相同 Python 類型、硬體與 Windows 電源模式。
