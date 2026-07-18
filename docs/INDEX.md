# maple-star 知識庫索引

此目錄是專案長期知識庫。`AGENTS.md` 僅保留入口摘要；詳細規範與流程以本索引連到的文件為準。

## 分類索引
- [project-structure.md](project-structure.md)：專案結構、MVC + services/adapters 分層、facade 與舊 import path 相容。
- [development-guidelines.md](development-guidelines.md)：本機設定、ignore/commit 約束、共用常數、入口檔與相容性維護規則。
- [installation.md](installation.md)：Windows、Python、全部外部套件、AI agent 安裝順序、環境驗證與移機故障排除。
- [experience-ocr.md](experience-ocr.md)：Pixel OCR primary、PaddleOCR fallback、learning mode、經驗統計與 OCR guard 規則。
- [runtime-compatibility.md](runtime-compatibility.md)：GUI、遊戲視窗、DPI、HP/MP/EXP ROI、loading/fade 與前景切換注意事項。
- [verification.md](verification.md)：精準測試原則、跨子系統、發行前與 PaddleOCR 專項驗證命令。
- [release.md](release.md)：本機打包、GitHub Releases、ZIP 驗證與失敗處理流程。
- [2026-07-18 全 App 效能 Baseline](reviews/2026-07-18-full-performance-baseline.md)：重構前同機效能與環境證據。
- [Settings v2 Mapping Review](reviews/2026-07-18-settings-v2-mapping.md)：global/profile/extension mapping 與 migration 邊界。
- [2026-07-18 全 App 最大效能 Final Review](reviews/2026-07-18-full-performance-final.md)：Qt、supervisor、guardian、效能與 release gates。
- [緊湊 GUI 版面設計](superpowers/specs/2026-07-17-compact-gui-layout-design.md)：五頁字型、靠左分頁與內容驅動版面規格。
- [全專案 Code Review 與減肥設計](superpowers/specs/2026-07-17-project-slimming-design.md)：開發工具移除、發行包減肥、巨型模組拆分與分批驗證規格。
- [自動巡航安全性、業務判斷與效能強化](superpowers/specs/2026-07-18-minimap-cruise-hardening-design.md)：巡航輸入安全、按鍵 ownership、邊界技能兩秒契約、回界判斷與辨識節流規格。
- [自動巡航安全性、業務判斷與效能強化實作計畫](superpowers/plans/2026-07-18-minimap-cruise-hardening-plan.md)：依前景狀態機、按鍵生命週期、設定交易與辨識快取分批實作。
- [PySide6 GUI 重設計](superpowers/specs/2026-07-18-pyside6-gui-redesign-design.md)：Qt 原生事件迴圈、五頁重新設計、toolkit-neutral contract、分階段遷移與效能驗收規格。
- [CustomTkinter DPI 與自適應視窗尺寸修正](superpowers/specs/2026-07-18-customtkinter-dpi-window-sizing-design.md)：統一 logical size、內容貼合、工作區 clamp 與 overflow scrolling，避免筆電頁面下方空白。
- [CustomTkinter DPI 與自適應視窗實作計畫](superpowers/plans/2026-07-18-customtkinter-adaptive-window-implementation-plan.md)：分批實作 scroll host、DPI/work-area 換算、resize ownership 與精準驗證。
- [Stage 3 OCR 與 GUI 拆分設計](superpowers/specs/2026-07-17-stage-3-ocr-gui-decomposition-design.md)：實際 public API manifest、OCR 責任拆分、GUI page builder 與逐批 rollback 規格。
- [Stage 3 OCR 與 GUI 拆分實作計畫](superpowers/plans/2026-07-17-stage-3-ocr-gui-decomposition-plan.md)：依 facade、OCR leaf/service 與 GUI page builder 分成十批執行與驗證。
- [Stage 4 AutoPotionController 拆分設計](superpowers/specs/2026-07-17-stage-4-auto-potion-controller-decomposition-design.md)：runtime composition、media、hotkey、HUD、potion 與 EXP capture 的責任、ownership、相容與分批 rollback 規格。
- [Stage 4 AutoPotionController 拆分實作計畫](superpowers/plans/2026-07-17-stage-4-auto-potion-controller-decomposition-plan.md)：依 contracts、runtime、media、hotkey、capture、HUD、potion 與 EXP 分九批實作、驗證及 rollback。
- [第一階段全專案 Code Review Gate 計畫](superpowers/plans/2026-07-17-project-review-phase-1-plan.md)：全 repository review、baseline、findings 分級與後續階段分流。
- [2026-07-17 全專案 Code Review](reviews/2026-07-17-project-code-review.md)：全 repository baseline、分級 findings、證據與減肥階段分流。
- [Stage 3 OCR／GUI 拆分 Baseline](reviews/2026-07-17-stage-3-baseline.md)：拆分前 LOC、fixture 數量與 GUI/control performance 比較基準。
- [Stage 3 OCR／GUI 拆分 Review](reviews/2026-07-17-stage-3-review.md)：拆分後 LOC、模組責任、效能比較、驗證證據與 residual coupling。
- [Stage 4 AutoPotionController 拆分 Baseline](reviews/2026-07-17-stage-4-baseline.md)：拆分前controller結構、runtime import、resource ownership、patch seam與performance比較基準。
- [Stage 4 AutoPotionController 拆分 Review](reviews/2026-07-17-stage-4-review.md)：拆分後結構、canonical ownership、相容邊界、分批驗證證據與residual coupling。
- [階段 1A Cleanup 與 Startup Reliability 計畫](superpowers/plans/2026-07-17-cleanup-startup-reliability-plan.md)：child process、controller、父程序與桌面入口的例外 cleanup 邊界。
- [階段 1B Developer Tooling 與 Dead Code 移除計畫](superpowers/plans/2026-07-17-developer-tooling-dead-code-removal-plan.md)：低耦合 dead code 與 EXP OCR learning 分批刪除邊界。
- [階段 2A Release Package Baseline 計畫](superpowers/plans/2026-07-17-release-package-baseline-plan.md)：未修改 collect 規則的 ZIP、PyInstaller analysis 與 dependency baseline。
- [階段 2B Release Package Slimming 計畫](superpowers/plans/2026-07-17-release-package-slimming-plan.md)：artifact Paddle smoke、逐批移除 collect-all、lock 與 15% ZIP gate。

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
