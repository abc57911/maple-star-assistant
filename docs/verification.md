# 驗證流程

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## 快速驗證
一般 Python 修改優先執行：

```powershell
python tools/verify.py
```

此 profile 會執行：

- entrypoint `py_compile`
- `maple_star` compileall
- 精簡 smoke tests
- `git diff --check`

精簡 smoke tests 只跑日常最常碰到的低成本模組：

```powershell
python -m unittest tests.test_control_hotkey_worker tests.test_gamepad_macro tests.test_minimap_cruise tests.test_settings_profiles tests.test_win_input
```

此 profile 不會跑完整 controller、EXP OCR、GUI notice 或 HUD 偵測回歸；需要完整回歸時改跑 `python tools/verify.py full`。

只改 `docs/` 時，至少執行：

```powershell
git diff --check -- docs
```

## 功能回歸
若修改 settings 遷移、快捷鍵偵測、HP/MP 偵測、EXP OCR、經驗統計或 GUI pump，先跑快速驗證，再視改動補跑對應測試檔：

```powershell
python -m unittest tests.test_auto_potion_foreground_guard
python -m unittest tests.test_experience
python -m unittest tests.test_gamepad_macro
python -m unittest tests.test_settings_profiles
```

若修改 MVC 目錄結構、相容 facade、入口檔或 import path，需至少跑 `python tools/verify.py`，並依影響範圍補跑指定測試。

需要包含慢速 OCR fixture 時執行：

```powershell
python tools/verify.py full
```

## 測試對照
- `tests.test_auto_potion_foreground_guard`：controller 主流程、runtime process status、foreground gating、HP/MP capture、potion effect、EXP OCR orchestration、HUD layout。
- `tests.test_experience`：EXP parser、Pixel OCR、Paddle fallback、tracker、learning service、fixture validation；慢速 fixture accuracy 需 `MAPLE_STAR_RUN_SLOW_OCR_TESTS=1`。
- `tests.test_bar_detection_debug`：HUD/bar locator、preview、transition/loading guard、target process name。
- `tests.test_gamepad_macro`：controller button binding、RB/LB binding 切換與 GUI 設定同步。
- `tests.test_control_hotkey_worker`：全域熱鍵註冊、polling fallback、duplicate suppression。
- `tests.test_settings_profiles`、`tests.test_settings_controller_buttons`：settings migration、profile scope、controller button alias。
- `tests.test_gui_notice_position`、`tests.test_window_style`：GUI notice、console trim、compact/window position 與 auxiliary window style。
- `tests.test_win_input`：physical mouse observer 與 temporary mouse input lock。
- `tests.test_debug_logging`：debug / experience debug rotating log、reset 與 console mirror。

## PaddleOCR / 經驗效率
涉及 PaddleOCR runtime、OCR fixture 準確率或 `.venv-paddleocr` 時，另外執行：

```powershell
python tools/verify.py ocr-slow
```

重建 `.venv-paddleocr` 後另外確認：

```powershell
.\.venv-paddleocr\Scripts\python.exe --version
.\.venv-paddleocr\Scripts\python.exe -c "import cv2, numpy, paddle, paddleocr; print('ocr imports ok')"
```

## 發行、ignore 或 commit 前
若修改發行、ignore 或準備 release，需補跑：

```powershell
python tools/verify.py full
git status --short
```

一般 commit 前可先跑 `python tools/verify.py`；若該 commit 影響 controller 主流程、EXP OCR、HUD 偵測、GUI pump 或發行流程，再升級為 `python tools/verify.py full`。

注意：`git diff --check` 不會檢查 untracked files。新增檔案準備 commit 前，先確認檔案會被納入 diff 或改用精確路徑檢查。
