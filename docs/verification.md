# 驗證流程

> 知識庫索引：[docs/INDEX.md](INDEX.md)

## 日常修改

日常修改只執行：

```powershell
python tools\verify.py
```

此命令會完成：

- entrypoint `py_compile`
- `maple_star` compileall
- 精簡 smoke tests
- `git diff --check`

不需另外執行 `py_compile`、`compileall` 或個別 smoke test。

## 發行前

發行前執行完整測試：

```powershell
python tools\verify.py full
```

## PaddleOCR 專項

涉及 PaddleOCR runtime、fixture 準確率或 `.venv-paddleocr` 時執行：

```powershell
python tools\verify.py ocr-slow
```

日常不執行 `full` 或 `ocr-slow`；只在上述情境使用。
