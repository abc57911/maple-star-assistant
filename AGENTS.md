# maple-star 專案指引

完整知識庫入口：[docs/INDEX.md](docs/INDEX.md)

## 使用方式
- 修改前先查 `docs/INDEX.md`，依任務類型讀取對應知識文件。
- `AGENTS.md` 只保留 agent 執行時最常用的邊界；長期規範與流程以 `docs/` 為準。
- 回覆與專案文件預設使用繁體中文。

## 核心邊界
- 遵循既有 MVC + services/adapters 結構；新實作不要放回舊 facade。
- 保留舊公開 import path 相容性，例如 `maple_star.controller`、`maple_star.experience`、`maple_star.gui`、`maple_star.settings`。
- `settings.json`、`.venv*/`、`.paddleocr/`、根目錄 `/models/`、`build/`、`dist/`、`release/`、`*.spec` 都不應提交。
- 優化 EXP OCR 時，優先提升 ROI、前處理與 OCR 判讀正確性；guard 只能作為最後防線，不應用來取代可在影像層或辨識流程修正的解析錯誤。
- 未經使用者明確要求，不要 commit、打包、建立 tag 或發佈 release。
- 使用者要求 commit 時，先確認 staged 清單不含本機設定、venv、模型 cache 或打包產物。

## 常用索引
- 專案結構與 facade：[docs/project-structure.md](docs/project-structure.md)
- 開發約束與 commit 邊界：[docs/development-guidelines.md](docs/development-guidelines.md)
- 安裝、移機與環境重建：[docs/installation.md](docs/installation.md)
- EXP OCR 與經驗效率：[docs/experience-ocr.md](docs/experience-ocr.md)
- GUI / 視窗 / ROI 相容性：[docs/runtime-compatibility.md](docs/runtime-compatibility.md)
- 驗證命令：[docs/verification.md](docs/verification.md)
- 發行流程：[docs/release.md](docs/release.md)

## 驗證原則
- 預設只執行受本次修改直接影響的測試；修改哪個子系統，就測哪個子系統。
- 跨模組介面、共用契約或 cleanup ownership 有變動時，只補跑直接相關的契約或整合測試。
- 測試失敗時，先重跑失敗案例；需要擴大範圍時，只擴到最近的相依邊界。
- 程式狀態未改變時，不重跑已通過的測試。
- 文件修改只檢查文件 diff、連結與格式，不執行 runtime 測試。
- 不要預設執行全套測試、`python tools\verify.py`、`full`、`ocr-slow` 或 `performance`。只有使用者明確要求時，才依 [docs/verification.md](docs/verification.md) 執行對應 profile。
