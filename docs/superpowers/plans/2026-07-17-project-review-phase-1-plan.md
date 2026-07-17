# 第一階段：全專案 Code Review Gate 實作計畫

> 設計規格：[全專案 Code Review 與減肥設計](../specs/2026-07-17-project-slimming-design.md)
>
> 知識庫索引：[docs/INDEX.md](../../INDEX.md)

## 目的

先完成全 repository review 與可重現 baseline，再決定實際刪碼與重構批次。本計畫不修改 runtime、測試、打包腳本或依賴。

## 修改檔案

- 新增 `docs/reviews/2026-07-17-project-code-review.md`：findings、baseline、處置分流與剩餘風險。
- 更新 `docs/INDEX.md`：加入 review report 入口。
- 必要時修訂本計畫與 umbrella spec 中被實際證據推翻的假設；不得以此擴大功能範圍。

## Public surface 與 ownership

- public/re-export surface：本階段不變更任何 Python symbol。
- constructor、method、`Protocol`、IPC schema：本階段不變更。
- process、thread、Win32 handle、MCI alias、GDI resource：本階段不建立、不轉移 ownership。
- 本階段只執行靜態分析、測試、import smoke 與檔案大小量測；不啟動會對遊戲送鍵的 production runtime。

## 工作項目

### 1. 固定工作樹與量測邊界

- 記錄 `git status --short --branch`、HEAD、與 `origin/main` 差異。
- 僅將已核准的 spec、plan、index 視為目前 intended changes；其他變更一律列為外部狀態。
- tracked Python LOC 以 `git ls-files '*.py'` 為集合，分別計算 production、tests、tools 與 generated templates。
- 以 Python AST 計算最大 module、class、function 及 method 長度。
- 量測 `.venv-paddleocr/Lib/site-packages` top-level package 大小；model cache 不納入。
- 以 `Measure-Command { python tools\verify.py full }` 記錄 full gate wall time。

### 2. 全 repository review

- 入口與 facade：`main.py`、`main.pyw`、`auto_potion.py`、`maple_gamepad_macro.py`、`maple_star/*.py` 相容層。
- models：settings migration、experience tracker/OCR、controller state、generated templates 邊界。
- controllers：GUI orchestration、runtime coordination、hotkey、potion、EXP capture、cleanup。
- services：IPC、scheduler、minimap、Telegram、worker、settings store、OCR learning。
- adapters：Win32 input/window、pygame、logging、key capture、resource cleanup。
- views：GUI lazy build、設定同步、callback ownership、重複 page construction。
- tests/fixtures：coverage、重複 helper、過度耦合 test double、fixture/runtime 邊界。
- tools/build/release：verification profiles、benchmark、PyInstaller collect、dependency 與 artifact boundary。
- docs：結構描述、驗證命令、OCR、安裝與發行說明是否符合目前程式。

### 3. 分析方法

- `rg` 搜尋 TODO、FIXME、deprecated、compat、wildcard import、廣泛 exception、重複 magic number 與 developer-only path。
- AST/import 分析尋找巨型單元、循環依賴、未被引用的 top-level symbol 與跨層 import。
- 比對 facade export、內部 import 與 tests import，避免把相容 API 誤判為死碼。
- 對疑似重複或死碼逐項讀取 call site；無 call-site 證據不得列為可直接刪除。
- 對 cleanup、IPC、SendInput、staged key 與 Paddle fallback findings，必須追蹤建立、使用、失敗與釋放路徑。

### 4. Finding 分級與處置

- Critical：資料損壞、安全、無法啟動或核心 runtime 失效；未處置即阻擋後續修改。
- Important：可重現功能錯誤、資源洩漏或高維護風險；排入明確階段，或提供延後理由。
- Minor：不影響正確性的局部簡化；只有低耦合且可驗證時才納入減肥批次。
- 每項 finding 必須包含檔案與行號、證據、影響、建議處置、目標階段及驗證方法。
- 無法證實的疑點列入「需進一步蒐證」，不得寫成 confirmed finding。

### 5. 產出後續階段輸入

- 將 findings 分流成：開發工具移除、package slimming、OCR/GUI 拆分、controller 拆分、暫不處理。
- 先建立階段 1A cleanup／startup reliability plan；通過後再建立階段 1B OCR learning 與 confirmed dead code removal plan。
- 根據 findings 修訂第一階段後半段「移除 OCR learning」的精確檔案與 symbol 清單。
- 第二、三、四階段仍各自建立獨立 plan；本計畫不預先授權其修改。

## 驗證

- `python tools\verify.py full`：建立修改前 baseline，確認現況可比較。
- facade import smoke：固定 `maple_star.controller`、`maple_star.experience`、`maple_star.gui`、`maple_star.settings`、`auto_potion.py` 與 `maple_gamepad_macro.py` 現有入口。
- `git diff --check`：確認新增文件無 whitespace error。
- review report 逐項檢查：每個 confirmed finding 都有證據、影響、階段、驗證與處置狀態。

## 錯誤處理與 rollback

- full gate 若失敗，先記錄為 baseline finding；本階段不順手修 runtime。
- 靜態工具若缺少，不安裝新 dependency；改用 Python AST、`rg` 與人工 call-site review，並記錄限制。
- 量測命令若受本機 encoding 或 Windows 路徑影響，保留原始 exit code，改用等價 PowerShell-native 命令重跑。
- 本階段只有文件變更；rollback 邊界為 review report、plan 與 index，不涉及 production code。

## 完成條件

- 全部 tracked 區域都完成 review，沒有未分類範圍。
- Critical finding 為零，或已有明確阻擋狀態與證據。
- baseline 與每項 finding 可由文件中的命令重現。
- findings 已映射到後續階段，且第一個實際刪碼批次具備精確 plan 輸入。
