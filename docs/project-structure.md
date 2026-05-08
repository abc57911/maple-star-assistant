# 專案結構

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## 入口與 facade
- `main.pyw`：無 console 視窗的 GUI 入口，發行版本主要使用此入口。
- `main.py`：一般 Python 入口，適合本機除錯。
- `auto_potion.py`：相容用 facade，對外匯出自動喝水相關 API。
- `maple_gamepad_macro.py`：相容用 facade，可直接執行，也對外保留手把巨集相關 API。
- `maple_star/controller.py`、`maple_star/experience.py`、`maple_star/gui.py`、`maple_star/settings.py`、`maple_star/win_input.py` 等舊路徑是相容 facade / module alias，不應再放新實作。

## package 分層
- `maple_star/`：主 package，採 MVC + services/adapters 結構。
- `maple_star/models/`：資料模型、設定模型、經驗效率模型、controller runtime state dataclass。
- `maple_star/views/`：GUI 與 console writer，包含 CustomTkinter view、theme 與 layout。
- `maple_star/controllers/`：主流程 orchestration，例如自動喝水 controller 與手把主 loop controller。
- `maple_star/services/`：純服務邏輯，例如 bar detection、settings store、hotkey worker、gamepad binding。
- `maple_star/adapters/`：外部系統邊界，例如 Win32 input/window API、SendInput helper、debug logging、pygame controller worker。
- `maple_star/constants.py`：跨模組共用常數，包含偵測節奏、狀態條定位、快捷鍵 ID 與 loading/fade guard。

## 打包入口
- `build_release.bat`：PyInstaller 打包流程。
- 發行包以 `main.pyw` 作為 GUI 入口，避免 console 視窗。
