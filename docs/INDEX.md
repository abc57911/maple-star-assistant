# maple-star 知識庫索引

此目錄是專案長期知識庫。`AGENTS.md` 僅保留入口摘要；詳細規範與流程以本索引連到的文件為準。

## 分類索引
- [project-structure.md](project-structure.md)：專案結構、MVC + services/adapters 分層、facade 與舊 import path 相容。
- [development-guidelines.md](development-guidelines.md)：本機設定、ignore/commit 約束、共用常數、入口檔與相容性維護規則。
- [experience-ocr.md](experience-ocr.md)：Pixel OCR primary、PaddleOCR fallback、learning mode、經驗統計與 OCR guard 規則。
- [runtime-compatibility.md](runtime-compatibility.md)：GUI、遊戲視窗、DPI、HP/MP/EXP ROI、loading/fade 與前景切換注意事項。
- [verification.md](verification.md)：一般修改、OCR/經驗效率、發行/commit 前驗證命令。
- [release.md](release.md)：本機打包、GitHub Releases、ZIP 驗證與失敗處理流程。

## 維護規則
- 新增知識文件時，必須加入本索引。
- 每個 `docs/*.md` 文件頂部必須連回本索引。
- 若文件內容會影響 agent 行為，確認 `AGENTS.md` 是否也需要補入口連結或摘要。
