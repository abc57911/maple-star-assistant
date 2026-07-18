# CustomTkinter DPI 與自適應視窗實作計畫

> 設計：[CustomTkinter DPI 與自適應視窗尺寸修正](../specs/2026-07-18-customtkinter-dpi-window-sizing-design.md)

## 批次 1：AdaptiveScrollHost

- 新增 `maple_star/views/adaptive_scroll.py`。
- 薄封裝 `CTkScrollableFrame`，提供完整 canvas content bbox、viewport logical height 與 overflow scrollbar 控制。
- 保留 inner frame 自然高度，只同步 canvas viewport 寬度。
- 測試 content height 不受 viewport clamp 影響，overflow 切換不重建 inner widgets。

## 批次 2：DPI 與工作區尺寸

- 在 `settings_gui.py` 新增 root logical geometry parser。
- 將 canvas physical content height 依實際 widget scaling 轉成 logical height。
- 以 root HWND、`MonitorFromWindow`、`GetMonitorInfoW` 與 outer rect 計算可用 logical client height。
- 所有 root size read-modify-write 改用 logical size；錯誤時 fail closed。
- 測試 125% logical／physical 分流、malformed geometry、work-area clamp 與動態 minsize。

## 批次 3：頁面與 resize ownership

- 四個非 Console lazy pages 改用 `AdaptiveScrollHost`，builders 接收 inner frame。
- 啟動、實際切頁、deferred build 與結構變更排一次 auto-fit。
- 所有 `geometry()`／`minsize()` mutation 經 generation coordinator。
- 使用者 resize 後同頁保留尺寸；重選同頁不奪回 ownership，切頁後恢復 auto-fit。
- Console 維持填滿；跨螢幕只在超出新 work area 時 clamp。
- 測試 lazy builder 單次建立、refs、duplicate configure、same-page reselect、高頁切回矮頁與 Console。

## 批次 4：驗證

- 執行 `python -m unittest tests.test_gui_notice_position tests.test_gui_page_builders`。
- 真實 GUI 依序測試 100%、125%、150%、175% widget／window scaling，保存並恢復原 scaling。
- 驗證監控頁下方無大面積空白、各頁切換、手動 resize ownership、overflow 可捲至底部與無殘留 Python process。
- 不執行全套測試、`python tools\verify.py`、`full`、`ocr-slow` 或 `performance`。

## 完成條件

- 125% 筆電預設頁貼合內容，不二次縮放。
- 四個設定頁自適應並可 overflow scrolling。
- 手動 resize、Console、跨螢幕與 lazy construction 行為符合規格。
- 直接相關測試與 scaling smoke 通過。
