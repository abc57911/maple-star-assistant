# 自動巡航安全性、業務判斷與效能強化實作計畫

> 設計：[自動巡航安全性、業務判斷與效能強化](../specs/2026-07-18-minimap-cruise-hardening-design.md)

## 批次 1：前景與狀態機

- 收緊目標 HWND 判斷。
- 每次新 `key_down` 前檢查前景，cleanup `key_up` 不受阻擋。
- 紅點計時在 suspend 或觀察中斷時重設。
- 邊界技能按滿 `2.0 秒`，角色 probe 限制為每 `0.2 秒`一次。
- recovery 改以 best X 判定淨進度。
- 測試：`tests.test_minimap_cruise`、直接相關 foreground guard 案例。

## 批次 2：按鍵生命週期

- 集中巡航 key-down/key-up helper 與 pending release retry。
- pending release 清空前阻擋新輸入與重新啟用。
- 週期鍵改為 `0.05 秒`非阻塞 staged tap。
- stop、suspend、測謊及 shutdown 清理 staged tap。
- 測試：`tests.test_minimap_cruise`、直接相關 scheduler 案例。

## 批次 3：設定交易與驗證

- 新增可重用的巡航按鍵與邊界驗證。
- GUI 校正拒絕寬度小於 `20 px`或 Y 差大於 `30 px`。
- `apply_settings()` 採 validate-before-commit，清除舊排程後才恢復。
- `TargetWindowUpdated` 先清理舊鍵再更新 HWND。
- 測試：巡航、settings、GUI/controller 直接相關案例。

## 批次 4：辨識快取與清理

- 快取測謊各 scale template/mask。
- 移除未參與決策的狀態與區域變數。
- 測試：測謊辨識與巡航直接案例。

## 完成條件

- 各批修改後只跑直接受影響測試。
- 程式狀態未變時不重跑已通過測試。
- 不執行 `python tools\verify.py`、`full`、`ocr-slow` 或 `performance`。
- 最後檢查 diff、未追蹤檔案與敏感路徑；未經明確要求不提交實作。
