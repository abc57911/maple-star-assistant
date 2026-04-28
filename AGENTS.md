# maple-star 專案指引

## 專案結構
- `main.pyw`：無 console 視窗的 GUI 入口，發行版本主要使用此入口。
- `main.py`：一般 Python 入口，適合本機除錯。
- `auto_potion.py`：相容用 facade，對外匯出自動喝水相關 API。
- `maple_star/`：自動喝水、GUI、settings、Windows input、key capture、經驗效率等模組化實作。
- `maple_star/constants.py`：跨模組共用常數，包含偵測節奏、狀態條定位、快捷鍵 ID 與 loading/fade guard。
- `maple_star/controller.py`：主控制流程，整合 GUI、視窗擷取、自動喝水、快捷鍵、HP/MP 預覽與經驗 OCR 背景工作。
- `maple_star/experience.py`：經驗效率統計、PaddleOCR adapter、EXP OCR 前處理與 OCR 文字解析。
- `maple_star/settings.py`：設定檔、設定檔遷移、profile 與快捷鍵預設值。
- `maple_gamepad_macro.py`：手把 RB/LB 巨集與主流程整合。
- `build_release.bat`：PyInstaller 打包流程。

## 專案約束
- `settings.json` 是使用者本機設定檔，應由程式自動建立或補齊。
- `settings.json` 不應提交，也不應打包進 release。
- `.venv*/`、`.paddleocr/`、`models/`、`build/`、`dist/`、`release/`、`*.spec` 都是本機或打包產物，不應提交。
- 未經使用者明確要求，不要執行打包。
- 未經使用者明確要求，不要 commit；使用者要求 commit 時，先確認 staged 清單不含本機設定、venv、model cache 或打包產物。
- 修改 `auto_potion.py` 時需保留向後相容匯出，避免破壞既有 import。
- 新增或調整自動喝水功能時，優先放在 `maple_star/` 內合適模組。
- 新增或調整共用常數時，優先放在 `maple_star/constants.py`，避免在 controller、GUI 或測試中散落 magic number。
- 快捷鍵設定目前設計為單鍵；設定快捷鍵時必須暫時攔截腳本功能，避免按鍵設定動作同時觸發暫停、停止或經驗統計切換。

## PaddleOCR 與經驗效率
- 經驗效率功能使用 PaddleOCR，主要語言為繁體中文，模型設定預設使用 `chinese_cht` 與 PP-OCRv5 mobile det/rec。
- 本機開發優先使用 `.venv-paddleocr`；不要把 venv、模型 cache 或下載模型提交。
- PaddleOCR 初始化、辨識錯誤與低信心樣本應輸出到 GUI console 或狀態欄的短訊息，不應造成主 GUI 卡住。
- OCR 背景工作需維持單 worker、低頻率擷取；調整 `EXPERIENCE_CAPTURE_INTERVAL_SECONDS` 或 OCR 前處理時，需注意 CPU 佔用。
- EXP OCR 應優先抓 UI 顯示的 EXP 數字與百分比，不使用 EXP 綠條自行推算百分比。
- EXP OCR 前處理的主路徑應保留完整文字 ROI、補邊並放大；二值化與 parser 容錯只作為 fallback，不應用 parser 掩蓋可在影像層修正的問題。
- 經驗效率統計應維持最後可信結果；功能停用、OCR 短暫失敗或樣本被拒絕時，不應直接清空 1m、5m、1h 或 ETA。

## 相容性注意事項
- GUI 需能在遊戲切換前景、拖曳視窗、中文輸入法啟用時維持穩定。
- 自動喝水偵測需考慮：
  - 視窗模式
  - Windows DPI scaling
  - 非 16:9 遊戲視窗
  - 地圖切換漸暗 / 漸亮過場
  - 切換頻道 loading 畫面
- HP/MP 條與 EXP OCR 範圍需能隨遊戲視窗縮放或重開自動重新定位；不要依賴固定預設座標。
- 刷新 HP/MP 預覽時可短暫將遊戲視窗置頂並等待畫面穩定後再截圖；若偵測失敗，不要更新既有範圍或預覽圖。
- 遊戲視窗辨識應優先使用較精準的視窗條件與可恢復的 hwnd cache；不要只依賴容易撞名的標題字串。

## 驗證
修改 Python 程式後至少執行：

```powershell
python -m py_compile main.py main.pyw maple_gamepad_macro.py auto_potion.py
python -m compileall -q maple_star
```

若修改 settings 遷移、快捷鍵偵測、HP/MP 偵測、EXP OCR、經驗統計或 GUI pump，需補跑對應的最小回歸測試或 Python snippet。

涉及 PaddleOCR 或經驗效率時，另外執行：

```powershell
.\.venv-paddleocr\Scripts\python.exe -m unittest discover -s tests
.\.venv-paddleocr\Scripts\python.exe -m pip check
```

若修改發行、ignore 或 commit 前狀態，需補跑：

```powershell
git diff --check
git status --short
```

## 發行
- 只有使用者明確要求打包時，才執行 `build_release.bat`。
- 打包前確認 `build_release.bat` 仍會檢查入口檔與 `maple_star` package。
- 發行包不應依賴預先存在的 `settings.json`。
- 打包後確認 `release/MapleStar.zip` 存在，且 ZIP 內含 `MapleStar.exe` 與 `README.txt`。
- 打包後再次確認 `git status --short`，避免 `*.spec`、`build/`、`dist/` 或 `release/` 污染工作樹。
