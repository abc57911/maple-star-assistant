# 全 App 最大效能重構 Final Review

> 知識庫索引：[../INDEX.md](../INDEX.md)

## Production 架構

- PySide6 是唯一 GUI；正式 tick 由 single-shot `QTimer` 與 monotonic deadline 擁有。
- supervisor registry 管理 guardian、potion、EXP 與 scheduler PID/incarnation/health。
- guardian 是唯一鍵盤、滑鼠與 cursor mutation writer；generation fence 會淘汰所有舊命令。
- potion heartbeat 與 work progress 分離為 2 秒／30 秒 health boundary，避免高負載誤重啟。
- domain workers 位於 Windows kill-on-close Job；guardian 排除 Job並監測 parent handle，最後釋放輸入後退出。
- preview serialized p95 低於 2 ms，故不引入 shared memory。

## 已通過證據

- correctness：`835 tests`，`1 skipped`。
- Python 冷程序啟動 7 次：first visible shell 中位數 `0.1608 s`；main ready 中位數 `0.3588 s`，較 legacy `0.5134 s` 改善 `30.12%`。
- 五頁 visible p95 `0.597 ms`；usable p95 `6.047 ms`。
- control scheduler 5 秒 final smoke：p95 `0.054 ms`、p99 `0.225 ms`、max `0.225 ms`。
- 前次 600 秒 mixed pipeline（舊 schema，尚缺 p99 欄位）：scheduler p95 `0.055 ms`、max `0.688 ms`、status gap max `500.299 ms`、RSS 成長 `45,547,520 bytes`。
- release ZIP 無 Tk、含 qwindows.dll；artifact Paddle predict 為 `3796880 / 99.08%`。
- raw evidence：[final.json](artifacts/full-performance-plan-4/final.json)。

依使用者指示，不執行新版 600 秒 p99 pipeline 與 3600 秒 soak；raw JSON 明確標記為 `skipped-by-user`，不宣稱長時間壓力 gate 通過。
