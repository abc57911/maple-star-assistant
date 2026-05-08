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
- 未經使用者明確要求，不要 commit、打包、建立 tag 或發佈 release。
- 使用者要求 commit 時，先確認 staged 清單不含本機設定、venv、模型 cache 或打包產物。

## 常用索引
- 專案結構與 facade：[docs/project-structure.md](docs/project-structure.md)
- 開發約束與 commit 邊界：[docs/development-guidelines.md](docs/development-guidelines.md)
- EXP OCR 與經驗效率：[docs/experience-ocr.md](docs/experience-ocr.md)
- GUI / 視窗 / ROI 相容性：[docs/runtime-compatibility.md](docs/runtime-compatibility.md)
- 驗證命令：[docs/verification.md](docs/verification.md)
- 發行流程：[docs/release.md](docs/release.md)

## 最低驗證
- 修改 Python 程式後至少執行：

```powershell
python -m py_compile main.py main.pyw maple_gamepad_macro.py auto_potion.py
python -m compileall -q maple_star
```

- 修改 MVC 結構、相容 facade、入口檔、EXP OCR、經驗統計、GUI pump、settings 遷移或 HP/MP 偵測時，依 [docs/verification.md](docs/verification.md) 補跑對應測試。
