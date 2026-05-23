# EXP OCR 與經驗效率

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## OCR 架構
- 經驗效率功能以 Maple EXP 固定像素字型辨識為 primary。
- 只有 Pixel OCR 失敗、低信心或候選衝突時才走 PaddleOCR fallback。
- `PaddleExperienceTextReader` 是相容名稱，內部應保留 Pixel primary + PaddleOCR fallback 的順序，不要再導入其他 OCR runtime 或依賴。
- Pixel OCR 不應以 EXP 位數作為可信條件；可信度應來自 glyph confidence、候選衝突、括號內百分比文字與 bar hint guard。
- EXP 百分比以 UI 括號內文字為主，綠條估算只做 guard，不用來改寫百分比。

## learning mode
- Runtime 已停用 Pixel OCR learning pending bundle 寫入，不再要求使用者日常人工校正。
- GUI 不提供 `OCR學習` / 校正入口；日常穩定性應依賴 Pixel OCR、Paddle fallback、OCR continuity guard 與 tracker rejection。
- `tools/experience_ocr_learning.py` 與 `maple_star.services.experience_ocr_learning` 僅保留作為開發者離線維護 fixture/template 的工具。
- 只有使用 `tools/experience_ocr_learning.py promote` 後，並通過 fixture validation 的 fixture/template 才可提交。
- 若開發者手動套用後 Pixel validation 仍失敗，必須回滾新增 fixture，避免同一張不適合的 ROI 反覆污染 template。
- `EXP OCR 模糊數字候選不一致`、`ocr_continuity_rejected`、`tracker_rejected` 與 glyph ambiguity case 不得自動套用，避免把綠底誤讀學成 template。
- 既有 pending case 若需保留，只作為診斷證據；`tools/experience_ocr_learning.py dedupe` 可清理既有重複 pending case，`delete` 可刪單筆 pending case。
- Pixel OCR runtime template 需放在 package 內可打包資料或 module，不得依賴 `tests/fixtures` 才能辨識。
- `auto-promote` 必須保守：只有高 confidence、足夠 gap、matching attempts 合理且 validation 成功的 case 才能 promote；validation 失敗需 rollback。

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
- 日常更新、初始 baseline 與 EXP-10 checkpoint 應先嘗試滑鼠指向 EXP 條尾端產生的浮動 EXP tooltip；tooltip 擷取或 OCR 失敗時只可等待下一輪或 fallback 到既有底部 EXP OCR。
- tooltip OCR 成功時，EXP 百分比應直接由浮動 UI 的 `current_exp / total_exp * 100` 計算；初始 baseline 也需保留此 percent，不再丟棄後等待底部百分比 OCR 補齊。
- 偵測到實體滑鼠移動、點擊或滾輪時，EXP 讀取需延後到滑鼠閒置 5 秒後再執行；此延後只暫停取樣，不暫停經驗統計時間。
- 滑鼠閒置延後期間的 GUI status 更新需節流，預設跟 `EXPERIENCE_CAPTURE_INTERVAL_SECONDS` 同節奏，避免倒數文字每個 tick 造成 EXP 統計區快速跳動。
- 擷取浮動 EXP tooltip 時不送出滑鼠按鍵事件；只保存原座標，並在同一個短鎖定區間內完成游標定位、tooltip 停留、ROI 截圖。若截圖前後游標偏離 EXP 目標點，需丟棄該張 ROI 並重試，截圖完成後立即解除鎖定並還原滑鼠位置；OCR 解析應在截圖後的背景工作執行。
- 能力值窗 EXP 讀取已棄用；經驗統計不應要求能力值快捷鍵，也不應開啟能力值窗作為 baseline 或 EXP-10 fallback。
- EXP OCR 前處理的主路徑應保留完整文字 ROI、補邊並放大。
- Pixel OCR 百分比數字需先以白字前景 mask 與 glyph topology 判讀；`6/8/0/9/3/5` 這類近似 glyph 若無法由拓樸與模板同向支持，應 fail closed，不可只靠綠條或最高模板分數改寫。
- 二值化與 parser 容錯只作為 fallback，不應用 parser 掩蓋可在影像層修正的問題。
- EXP OCR parser 應以「可選 EXP 標籤、整數 EXP、可選正確千分位、EXP%」為可信結構。
- EXP 數字段含半形或全形英文字母、混用分隔符、錯誤千分位或結構分數過低時應拒絕，不應送入統計器。
- raw OCR 若在 EXP 數字前綴中出現空白，例如 `1504952 28[78.24X]`，應拒絕而不是移除空白後接受，避免把 PaddleOCR 斷字誤判送入統計器。

## Tooltip OCR
- `prepare_experience_tooltip_ocr_images(image)` 預設只產生 base variants；contrast / sharpen retry variants 只有 `include_retry=True` 時才加入。
- `PaddleExperienceTextReader.read_tooltip_exp()` 應先跑 base variants，只有全部失敗才產生 retry variants，避免每次 tooltip OCR 都走完整慢路徑。
- tooltip OCR 成功後應立即停止後續 variants；需記錄 `predict_count`、`variant_count`、`selected_variant_index`、`elapsed_ms`、`success` 與 `reason` 到 `experience_debug.log`。
- tooltip OCR telemetry 是效能診斷資料，不應影響 parser/tracker 的可信度判斷。

## 經驗效率統計
- 經驗效率統計應只採用可信樣本。
- 樣本需通過 EXP / EXP% 合理性檢查，包含 EXP% 回落、EXP 跳動過大、EXP 增量與百分比變化不一致、以及非升級條件下 EXP 回落。
- 經驗效率三個級距是當前效率換算值，不是歷史結算。
- 5m、10m、1h 皆使用時間窗內樣本做近期加權線性回歸，再套用平滑。
- 調整 half-life、smoothing alpha 或樣本拒絕條件時，需補回歸測試。
- 經驗效率統計應維持最後可信結果；功能停用、OCR 短暫失敗或樣本被拒絕時，不應直接清空 5m、10m、1h 或 ETA。
- OCR 解析失敗、低信心、結構不可信與統計器拒絕的異常樣本都應輸出到 GUI Console。
- 異常樣本 log 需包含 raw OCR text、confidence、解析出的 EXP 與 EXP%。
- 所有 pause 分支需使用同一套 effective-time axis：手動停用、HUD missing、target inactive、OCR pending/burst 等都要停住 tracker elapsed/rate/ETA，不只停 capture。
- resume 後的下一筆可信 OCR sample 要排除 pause duration；pending OCR job / burst 在 pause 時要 cancel 或停止回寫，避免 stale ROI 污染統計。
- 首筆可信 EXP OCR 若已通過 tracker 且 `exp_10m_checkpoint_exp` 尚未建立，需 seed EXP-10 checkpoint，但不得直接產生 gain。
- EXP-10 checkpoint OCR 失敗可播放一次提示；重複同狀態不應每次 runtime status 都重新播放。
