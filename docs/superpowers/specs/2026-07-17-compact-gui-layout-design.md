# 緊湊 GUI 版面設計

> 知識庫索引：[docs/INDEX.md](../../INDEX.md)

## 目標

- 分頁列使用適合 Windows 中文介面的無襯線字型。
- 分頁按鈕靠左、維持緊湊寬度，不再填滿整個視窗。
- 五個頁面的內容依實際控制項排列，移除不必要的固定高度、固定欄寬與空白區。
- 保留 CustomTkinter、五頁 lazy loading、Console buffer 與既有 runtime 行為。

## 版面

- 分頁列改用獨立容器，按鈕依文字長度設定固定寬度並靠左排列。
- 只有分頁按鈕改用 `Microsoft JhengHei UI`；其他控制項與 Console 維持既有字型，避免擴大變更範圍。
- 主內容 frame 使用 `sticky="new"` 與內容驅動高度。頁面不以視窗剩餘高度撐開控制項。
- 監控頁：全域熱鍵與設定檔各占一列；經驗計算與偵測診斷以約 3:2 的雙欄排列；runtime 狀態列占滿有效寬度。
- 自動喝水頁：藥水監控與 HP/MP 觸發設定以左右雙欄排列。
- 小地圖巡航頁：主要啟停／邊界控制在左欄，週期鍵與進階設定入口在右欄。
- 手把組合頁：組合 A 與組合 B 左右並排，各欄內維持相同欄位順序。
- 預設視窗寬度採上述雙欄；寬度不足時改為上下單欄，不得裁切、重疊或產生水平捲動。
- Console 頁仍可填滿可用空間，因為文字紀錄需要伸縮高度。

## 行為邊界

- 不修改設定 schema、profile payload、runtime process、SendInput 或計時邏輯。
- 監控頁啟動時建立；其餘四頁首次選取時建立並快取，未曾開啟的頁面不建立 widget。已建立頁面維持既有狀態同步。Console 首次開啟前只使用 bounded buffer，且不排程 repaint。
- compact experience mode 與視窗位置保存語意保持相容。

## 驗收

- 真實 Tk smoke 確認初始 `page_built == {"監控"}`；四個延遲頁面各只建立一次，切走再切回不重建，Console 開啟前 bounded buffer 行為不變。
- 除 Console 外，各 section 不設固定高度；空白 grid row 不設 `weight` 或 `minsize`；section requested height 由內容決定。
- 以截圖輔助檢查分頁靠左、字型一致、預設寬度採雙欄且窄視窗無裁切或重疊。
- 執行 GUI 單元測試與 `python tools\verify.py`；不執行長時間 benchmark。
