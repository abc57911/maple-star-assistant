# maple-star 知識庫索引

此目錄是專案長期知識庫。`AGENTS.md` 僅保留入口摘要；詳細規範與流程以本索引連到的文件為準。

## 分類索引
- [project-structure.md](project-structure.md)：專案結構、MVC + services/adapters 分層、facade 與舊 import path 相容。
- [development-guidelines.md](development-guidelines.md)：本機設定、ignore/commit 約束、共用常數、入口檔與相容性維護規則。
- [installation.md](installation.md)：Windows、Python、全部外部套件、AI agent 安裝順序、環境驗證與移機故障排除。
- [experience-ocr.md](experience-ocr.md)：Pixel OCR primary、PaddleOCR fallback、learning mode、經驗統計與 OCR guard 規則。
- [runtime-compatibility.md](runtime-compatibility.md)：GUI、遊戲視窗、DPI、HP/MP/EXP ROI、loading/fade 與前景切換注意事項。
- [verification.md](verification.md)：日常、發行前與 PaddleOCR 專項驗證命令。
- [release.md](release.md)：本機打包、GitHub Releases、ZIP 驗證與失敗處理流程。
- [緊湊 GUI 版面設計](superpowers/specs/2026-07-17-compact-gui-layout-design.md)：五頁字型、靠左分頁與內容驅動版面規格。

## 任務對照
- 查入口、facade、分層或模組職責：先讀 [project-structure.md](project-structure.md)。
- 改設定檔、快捷鍵、controller button、profile、log、ignore 或 commit 邊界：先讀 [development-guidelines.md](development-guidelines.md)。
- 在新電腦安裝、重建 venv、盤點套件、處理 Python/Paddle/OpenCV/Tk/DLL 問題：先讀 [installation.md](installation.md)。
- 改 HP/MP 偵測、HUD cache、前景 gating、runtime process 或 GUI 狀態刷新：先讀 [runtime-compatibility.md](runtime-compatibility.md)。
- 改 EXP OCR、tooltip 擷取、Pixel template、PaddleOCR fallback、EXP-10 或經驗效率統計：先讀 [experience-ocr.md](experience-ocr.md)。
- 改測試入口、fixture、驗證速度或 CI/release 前檢查：先讀 [verification.md](verification.md)。
- 改 `build_release.bat`、`.github/workflows/release.yml`、`RELEASE_README.txt` 或 ZIP 內容：先讀 [release.md](release.md)。

## 維護規則
- 新增知識文件時，必須加入本索引。
- 每個 `docs/*.md` 文件頂部必須連回本索引。
- 若文件內容會影響 agent 行為，確認 `AGENTS.md` 是否也需要補入口連結或摘要。
