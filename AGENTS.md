# maple-star 專案指引

## 專案結構
- `main.pyw`：無 console 視窗的 GUI 入口，發行版本主要使用此入口。
- `main.py`：一般 Python 入口，適合本機除錯。
- `auto_potion.py`：相容用 facade，對外匯出自動喝水相關 API。
- `maple_star/`：自動喝水、GUI、settings、Windows input、key capture 等模組化實作。
- `maple_gamepad_macro.py`：手把 RB/LB 巨集與主流程整合。
- `build_release.bat`：PyInstaller 打包流程。

## 專案約束
- `settings.json` 是使用者本機設定檔，應由程式自動建立或補齊。
- `settings.json` 不應提交，也不應打包進 release。
- 未經使用者明確要求，不要執行打包。
- 修改 `auto_potion.py` 時需保留向後相容匯出，避免破壞既有 import。
- 新增或調整自動喝水功能時，優先放在 `maple_star/` 內合適模組。

## 相容性注意事項
- GUI 需能在遊戲切換前景、拖曳視窗、中文輸入法啟用時維持穩定。
- 快捷鍵設定目前設計為單鍵，不需要支援組合鍵。
- 自動喝水偵測需考慮：
  - 視窗模式
  - Windows DPI scaling
  - 非 16:9 遊戲視窗
  - 地圖切換漸暗 / 漸亮過場
  - 切換頻道 loading 畫面

## 驗證
修改 Python 程式後至少執行：

```powershell
python -m py_compile main.py main.pyw maple_gamepad_macro.py auto_potion.py
python -m compileall -q maple_star
```

若修改 settings 遷移、快捷鍵偵測、HP/MP 偵測或 GUI pump，需補跑對應的最小回歸測試或 Python snippet。

## 發行
- 只有使用者明確要求打包時，才執行 `build_release.bat`。
- 打包前確認 `build_release.bat` 仍會檢查入口檔與 `maple_star` package。
- 發行包不應依賴預先存在的 `settings.json`。
