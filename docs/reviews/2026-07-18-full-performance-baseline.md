# 全 App 效能重構 Baseline

> 知識庫索引：[../INDEX.md](../INDEX.md)

- 基準 commit：`566c8b42d0df039b704ed45979f7dc0a8eadfbfd`
- 環境：Windows 11 build 26200、Intel Family 6 Model 183、24 logical cores、約 34 GB RAM、96 DPI、Bitsum Highest Performance。
- legacy Python 冷程序啟動中位數：`0.5134484 s`。
- legacy 五頁 visible p95：`15.1709 ms`；usable p95：`497.3137 ms`。
- control deadline p95：`0.0516 ms`；最大：`0.1105 ms`。
- raw evidence：[baseline.json](artifacts/full-performance-plan-1/baseline.json)。

EXE baseline 未在重構前取得，因此 final EXE 只報絕對數值，不宣稱相對改善。
