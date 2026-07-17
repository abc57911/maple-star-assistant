# 全專案 Code Review 與減肥設計

> 知識庫索引：[docs/INDEX.md](../../INDEX.md)

## 目標

- 保留一般使用者功能、設定格式、IPC schema 與公開 import path。
- 移除 OCR learning、pending case、promotion、dedupe 與 fixture 維護 CLI 等開發者工具。
- 縮小 PyInstaller 發行包，且維持 PaddleOCR fallback 可初始化並完成實際辨識。
- 降低巨型模組的維護成本；拆分後的單元必須有單一職責、明確介面與獨立測試。
- 以分批變更與量化基準控制 regression 風險。

## 非目標

- 不移除一般使用者可見功能、PaddleOCR fallback、Pixel OCR、OCR regression fixtures 或 runtime Pixel templates。
- 不修改 `settings.json` schema、profile migration、runtime command/status dataclass 或 multiprocessing ownership。
- 不破壞 `maple_star.controller`、`maple_star.experience`、`maple_star.gui`、`maple_star.settings` 等舊公開路徑。
- 不把減肥擴成 UI 重設計、OCR 演算法改寫或新設定頁。
- 第二階段已授權建立本機 baseline 與驗證 ZIP；未經使用者另行要求，不 commit、不建立 tag、不 push、不上傳，也不更新 GitHub Release。

## 執行策略

本工作分成四個可獨立驗證的階段。每一階段使用獨立實作計畫；前一階段通過驗證後才開始下一階段。若某階段失敗，只修正或撤回該階段，不混入後續重構。

每份階段實作計畫在修改前必須列出：精確檔案清單、public/re-export surface、constructor、method 或 `Protocol` 契約、輸入輸出型別、錯誤傳遞、process/thread/handle ownership、targeted tests、完整驗證 gate 與逐批 rollback 邊界。缺少其中一項時不得開始該階段。

### 第一階段：建立基準、修復 cleanup 邊界並移除開發者工具

- 先完成全 repository review gate，涵蓋 tracked source、入口與 facade、tests、build/release scripts、dependencies 及 docs。
- findings 依 Critical、Important、Minor 分級：Critical 代表資料損壞、安全、無法啟動或核心 runtime 失效；Important 代表可重現功能錯誤、資源洩漏或高維護風險；Minor 代表不影響正確性的局部簡化機會。每項列出檔案與行號、證據、影響、建議處置階段，或不處理／延後理由。未處置的 Critical finding 會阻擋後續修改。
- 先產出 findings，再據此建立或修訂四個階段的實作計畫；預先選定的巨型模組不能取代全專案盤點。
- 使用規格「量測定義」所列命令記錄 tracked Python 行數、最大檔案、主要 class 大小、測試時間及 `.venv-paddleocr` 依賴體積。
- 階段 1A 先修復 review 確認的 child process cleanup、controller best-effort cleanup 與 startup error handler；這些可靠性邊界通過獨立驗證後才開始刪碼。
- 階段 1B 再執行下列 developer tooling 與 dead code 移除。
- 刪除 `tools/experience_ocr_learning.py` 與 `maple_star/services/experience_ocr_learning.py`。
- 從 runtime 移除 learning case 自動儲存、pending directory、promotion metadata 與只服務 learning 的 helper。
- 停止讀寫既有 `%LOCALAPPDATA%\MapleStar\experience_ocr_pending`，但不主動刪除使用者電腦上的既有資料。
- 刪除只驗證 learning workflow 的測試；保留辨識正確性、continuity、Paddle fallback、Pixel templates 與 fixture regression。
- 更新 `docs/experience-ocr.md`、`docs/project-structure.md`、`docs/installation.md` 及相關索引敘述。

### 第二階段：發行包減肥

- 先產生未修改打包設定的 baseline ZIP 與 PyInstaller analysis；baseline 與修改後結果必須使用相同 Python、依賴版本及打包模式。
- 以 analysis 結果取代 `--collect-all paddleocr`、`--collect-all paddle` 與 `--collect-all paddlex` 的過度收集。
- 優先排除 training、serving、文件解析、GPU/TensorRT 與其他未被 EXP OCR runtime 載入的 PaddleX pipeline。
- 必要時新增專案內 PyInstaller hook；hook 只宣告實際需要的 submodule、data 與 metadata，不維護套件內部檔案逐項白名單。
- requirements 只有在 import、初始化及 OCR smoke 證明依賴不需要時才可移除。
- 第二階段更新 `docs/release.md` 與 `docs/verification.md`，記錄 analysis、artifact smoke 與 failure handling。

### 第三階段：拆分 OCR 與 GUI

- 將 `maple_star/models/experience.py` 逐步拆成 tracker、Paddle reader、Pixel OCR、影像前處理與文字解析單元。
- `maple_star/models/experience.py` 保留相容 re-export，避免既有 controller、test 與外部 import 同步大改。
- `AutoPotionSettingsGui` 保留視窗狀態、設定同步、事件協調與 lazy page lifecycle。
- 各設定頁的 widget 建構移到獨立 page builder；builder 接收明確的 GUI context，不直接讀取 controller runtime。

### 第四階段：拆分 AutoPotionController

- `AutoPotionController` 保留 lifecycle、主 update orchestration、runtime process coordination 與 cleanup ownership。
- 依耦合度由低到高抽出音效播放、控制熱鍵協調、HUD/bar detection、potion 狀態機與 EXP capture orchestration。
- 新單元不可共同持有同一 Win32 handle、MCI alias、thread 或 process；資源的建立者仍負責 cleanup。
- 不以 inheritance 或通用 manager class 隱藏依賴；controller 透過具名 collaborator 組合服務。

## 架構與資料流

既有頂層資料流保持不變：

`GUI -> AutoPotionController -> RuntimeProcessCoordinator -> potion / experience / control process`

- GUI 將設定寫回 `AutoPotionSettings`，controller 只在 signature 改變時送出 runtime command。
- runtime process 擁有自己的 capture、deadline 與輸入責任，並透過既有 status dataclass 回報 GUI process。
- HUD/bar detector 接收影像與幾何資料，回傳 detection result；它不送鍵、不更新 GUI、不管理 process。
- potion state 單元接收 percent sample、時間與設定，回傳待執行 action 或狀態轉移；controller/worker 保留實際 SendInput ownership。
- OCR reader 將 ROI 轉成 reading；tracker 接收 reading 並產生 snapshot。兩者不依賴 GUI。
- page builder 只建立 widget 並綁定 GUI callback；設定持久化仍由既有 GUI/controller 邊界負責。

## 相容性邊界

- facade 繼續匯出現有 public symbol；拆檔前先以 import smoke 固定這些 symbol。
- `settings.json` 的 key、default、migration 與 profile/global 分界不變。
- runtime command/status 的欄位、signature、heartbeat 與 bounded queue 語意不變。
- staged key、held potion key、MCI alias、GDI resource、thread 及 process 都必須保留明確 cleanup path。
- generated `experience_pixel_templates.py` 保留為 runtime source；移除 generator 後更新檔頭，避免指向已刪除的 CLI。
- facade smoke 使用固定 symbol manifest，至少涵蓋 `maple_star.controller`、`maple_star.experience`、`maple_star.gui`、`maple_star.settings`、`auto_potion.py` 與 `maple_gamepad_macro.py` 的現有公開入口。

## 錯誤處理與回復

- 找不到可安全排除的 Paddle/PaddleX 模組時，保留現有 collect 設定並回報 analysis 結果，不以移除 fallback 換取體積。
- 任何 package exclusion 若造成 import、`PaddleOCR(...)` 初始化或實際 OCR smoke 失敗，立即撤回該 exclusion。
- 抽取服務後若 characterization test 顯示行為差異，先恢復原行為；不在同一批順便修改功能。
- refactor 不新增廣泛 `except Exception: pass`。既有必要的隔離邊界必須記錄錯誤或保留可觀測狀態。
- 工作樹若出現非本任務修改，只 stage 或處理本任務檔案；未經要求不建立 commit。

## 驗證

### 第一階段

- `rg` 確認 learning API、CLI、pending path 與文件入口無殘留。
- 執行 `python tools\verify.py full`。
- 執行保留的 OCR fixture regression；涉及 Paddle runtime 時另執行 `python tools\verify.py ocr-slow`。

### 第二階段

- 執行 `python tools\verify.py full` 與 `python tools\verify.py ocr-slow`。
- 由乾淨打包輸出建立 ZIP，確認內容邊界符合 `docs/release.md`。
- 新增只在環境變數啟用的 artifact-side smoke 入口。驗證工具以 `MAPLE_STAR_RELEASE_OCR_SMOKE_IMAGE` 傳入 repository fixture 絕對路徑，以 `MAPLE_STAR_RELEASE_OCR_SMOKE_OUTPUT` 傳入暫存 JSON marker 路徑；正常啟動不進入此分支。
- smoke 入口從解壓後的 `MapleStar.exe` 載入 production `PaddleExperienceTextReader`，初始化 `PaddleOCR(...)`，再對固定 fixture `live_20260502_010734_001.png` 直接執行 production Paddle stage `_read_with_paddle()` 與 production parser。此 fixture 的既有期望值為 `3796880[99.08%]`，且在目前 baseline 環境已驗證 Paddle stage 可成功辨識。
- JSON marker 記錄 `backend="paddle"`、`paddle_predict_executed=true`、initialization、reading、elapsed time 與 traceback；驗證工具比對 `current_exp=3796880` 與 `percent=99.08`。未實際執行 Paddle predict 即判定 smoke 失敗，Pixel primary 的結果不能滿足此 gate。
- baseline 與修改後 artifact 使用相同、已預熱的 Paddle model cache，測試時禁止下載；單次 timeout 為 120 秒。EXE 非零退出、marker 缺失、初始化失敗、結果不符或 timeout 都算失敗。
- 每一組 package exclusion 分批套用；artifact smoke 失敗時，只撤回該批 exclusion，保留 JSON marker、startup error log 與 PyInstaller analysis 作為證據。
- 比較 baseline 與修改後 ZIP；目標至少縮小 15%。若安全最佳結果未達標，保留可驗證的縮減並記錄主要瓶頸。

### 第三、四階段

- 抽取前先以 characterization tests 固定公開 import、設定同步、IPC serialization、state transition 與 cleanup 行為。
- 第三、四階段都先執行 performance baseline；完成後在相同電源模式、Python 與硬體上重跑，依 `docs/verification.md` 的既有 gate 比較。
- 每個小批次先跑對應 targeted tests，再跑 `python tools\verify.py full`。
- OCR 批次另跑 `ocr-slow`；controller/runtime/GUI 架構批次依 `docs/verification.md` 執行 performance profile。

## 成功指標

- 一般使用者功能、Paddle fallback、公開 import、設定 migration 與 IPC schema 全部保留。
- OCR learning 與 fixture 維護工具及其 runtime side effect 全部移除。
- 發行 ZIP 在相同環境下縮小至少 15%，或留下已驗證的安全最佳結果與未達標證據。
- `auto_potion_controller.py`、`experience.py`、`settings_gui.py` 三個巨型檔案各縮小至少 30%。
- 新增的手寫實作模組不得超過 2,000 行；generated templates 不受此限制。若既有耦合使單一階段無法達標，該階段必須記錄具體阻礙、後續拆分處置與驗證證據，不能直接宣告成功。
- 不以刪除 regression coverage、吞掉例外或增加隱性共享狀態換取行數下降。

## 量測定義

- tracked Python LOC：以 `git ls-files '*.py'` 為輸入，逐檔計算實體行數；報告同時列出含 tests 與不含 tests 的總數。
- 最大手寫模組與 class：以 Python AST 計算 `lineno` 到 `end_lineno`；`maple_star/models/experience_pixel_templates.py` 明確列為 generated，不納入 30% 與 2,000 行 gate。
- dependency size：遞迴加總 `.venv-paddleocr/Lib/site-packages` 各 top-level package 的檔案 bytes，不把 model cache 算入 wheel/package 體積。
- ZIP size：使用 `release/MapleStar.zip` 的檔案 bytes；baseline 與修改後都由乾淨的 `build/`、`dist/`、`release/` 輸出建立。
- 測試與 performance 時間：使用驗證工具輸出的 wall time；前後比較採相同 profile 與環境。

## 交付物

- 全專案 code review findings，依嚴重度列出證據、影響與處置。
- 各階段精確刪除／新增／修改清單。
- 修改前後 LOC、最大模組、測試、依賴與 ZIP 體積比較。
- 驗證命令、結果及剩餘風險。
- 第一階段更新 `docs/INDEX.md`、`docs/project-structure.md`、`docs/experience-ocr.md` 與 `docs/installation.md`；第二階段更新 `docs/verification.md` 與 `docs/release.md`；第三、四階段若模組邊界再變動，逐階段同步更新 `docs/project-structure.md`。
