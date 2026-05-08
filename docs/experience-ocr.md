# EXP OCR 與經驗效率

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## OCR 架構
- 經驗效率功能以 Maple EXP 固定像素字型辨識為 primary。
- 只有 Pixel OCR 失敗、低信心或候選衝突時才走 PaddleOCR fallback。
- `PaddleExperienceTextReader` 是相容名稱，內部應保留 Pixel primary + PaddleOCR fallback 的順序，不要再導入其他 OCR runtime 或依賴。
- Pixel OCR 不應以 EXP 位數作為可信條件；可信度應來自 glyph confidence、候選衝突、括號內百分比文字與 bar hint guard。
- EXP 百分比以 UI 括號內文字為主，綠條估算只做 guard，不用來改寫百分比。

## learning mode
- Pixel OCR learning pending bundle 預設寫入 `%LOCALAPPDATA%\MapleStar\experience_ocr_pending\`，不得直接污染 repo。
- 只有使用 `tools/experience_ocr_learning.py promote` 後的 fixture/template 才可提交。
- GUI 的 `OCR學習` 視窗可即時檢視 pending case、輸入正確 `EXP[percent%]`、套用並重建 Pixel template。
- 套用前仍需人工確認畫面文字正確。
- 建立 pending case 時需做去重：完全相同 ROI hash、或同 trigger / 同 EXP 文字 / 同 Pixel failure reason 的 pending case 不應重複新增。
- `tools/experience_ocr_learning.py dedupe` 可清理既有重複 pending case；`delete` 可刪單筆 pending case。
- Pixel OCR runtime template 需放在 package 內可打包資料或 module，不得依賴 `tests/fixtures` 才能辨識。

## PaddleOCR fallback
- PaddleOCR fallback 主要語言為繁體中文，模型設定預設使用 `chinese_cht` 與 PP-OCRv5 mobile det/rec。
- 本機開發優先使用 `.venv-paddleocr`；不要把 venv、模型 cache 或下載模型提交。
- 發行打包也必須使用 `.venv-paddleocr` 內的 Python 3.11-3.13；不要用系統 Python 3.14 打包，因為 PaddleOCR / PaddlePaddle 依賴不支援該環境。
- 重建 `.venv-paddleocr` 後需驗證 Python 版本、`pip check`、`cv2/numpy/paddle/paddleocr` import 與完整測試。
- PaddleOCR 初始化、辨識錯誤與低信心樣本應輸出到 GUI console 或狀態欄的短訊息，不應造成主 GUI 卡住。
- 啟動或初始化 PaddleOCR 時若間接啟動子程序，Windows 下需保持 hidden/no-window，避免短暫黑窗搶走遊戲前景。
- PaddleX 會用 `importlib.metadata` 判斷 `paddlex[ocr-core]` 是否可用；PyInstaller 打包時必須保留 `imagesize`、`opencv-contrib-python`、`pyclipper`、`pypdfium2`、`python-bidi`、`shapely` 的 metadata，否則包內會誤報 `OCR requires additional dependencies`。
- OpenCV 依賴需維持 `opencv-contrib-python==4.10.0.84`，除非已重新驗證 PaddleOCR / PaddleX 初始化與辨識路徑。

## EXP OCR 判讀規則
- OCR 背景工作需維持單 worker、低頻率擷取。
- 調整 `EXPERIENCE_CAPTURE_INTERVAL_SECONDS` 或 OCR 前處理時，需注意 CPU 佔用。
- EXP OCR 應優先抓 UI 顯示的 EXP 數字與百分比，不使用 EXP 綠條自行推算百分比。
- EXP OCR 前處理的主路徑應保留完整文字 ROI、補邊並放大。
- 二值化與 parser 容錯只作為 fallback，不應用 parser 掩蓋可在影像層修正的問題。
- EXP OCR parser 應以「可選 EXP 標籤、整數 EXP、可選正確千分位、EXP%」為可信結構。
- EXP 數字段含半形或全形英文字母、混用分隔符、錯誤千分位或結構分數過低時應拒絕，不應送入統計器。
- raw OCR 若在 EXP 數字前綴中出現空白，例如 `1504952 28[78.24X]`，應拒絕而不是移除空白後接受，避免把 PaddleOCR 斷字誤判送入統計器。

## 經驗效率統計
- 經驗效率統計應只採用可信樣本。
- 樣本需通過 EXP / EXP% 合理性檢查，包含 EXP% 回落、EXP 跳動過大、EXP 增量與百分比變化不一致、以及非升級條件下 EXP 回落。
- 經驗效率三個級距是當前效率換算值，不是歷史結算。
- 5m、10m、1h 皆使用時間窗內樣本做近期加權線性回歸，再套用平滑。
- 調整 half-life、smoothing alpha 或樣本拒絕條件時，需補回歸測試。
- 經驗效率統計應維持最後可信結果；功能停用、OCR 短暫失敗或樣本被拒絕時，不應直接清空 5m、10m、1h 或 ETA。
- OCR 解析失敗、低信心、結構不可信與統計器拒絕的異常樣本都應輸出到 GUI Console。
- 異常樣本 log 需包含 raw OCR text、confidence、解析出的 EXP 與 EXP%。
