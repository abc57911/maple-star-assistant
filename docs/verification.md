# 驗證流程

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## Python 基本驗證
修改 Python 程式後至少執行：

```powershell
python -m py_compile main.py main.pyw maple_gamepad_macro.py auto_potion.py
python -m compileall -q maple_star
```

## 功能回歸
若修改 settings 遷移、快捷鍵偵測、HP/MP 偵測、EXP OCR、經驗統計或 GUI pump，需補跑對應的最小回歸測試或 Python snippet。

若修改 MVC 目錄結構、相容 facade、入口檔或 import path，需至少補跑：

```powershell
python -m unittest discover -s tests
```

## PaddleOCR / 經驗效率
涉及 PaddleOCR 或經驗效率時，另外執行：

```powershell
.\.venv-paddleocr\Scripts\python.exe -m unittest discover -s tests
.\.venv-paddleocr\Scripts\python.exe -m pip check
```

重建 `.venv-paddleocr` 後另外確認：

```powershell
.\.venv-paddleocr\Scripts\python.exe --version
.\.venv-paddleocr\Scripts\python.exe -c "import cv2, numpy, paddle, paddleocr; print('ocr imports ok')"
```

## 發行、ignore 或 commit 前
若修改發行、ignore 或 commit 前狀態，需補跑：

```powershell
git diff --check
git status --short
```
