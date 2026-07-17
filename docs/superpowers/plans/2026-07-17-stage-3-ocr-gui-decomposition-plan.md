# Stage 3：OCR 與 GUI 拆分實作計畫

> 設計規格：[Stage 3 OCR 與 GUI 拆分設計](../specs/2026-07-17-stage-3-ocr-gui-decomposition-design.md)

## 目標

以實際 consumer manifest 固定相容邊界，分批把 `models/experience.py` 拆成 leaf types/constants、tracker 與 OCR services，再把 `views/settings_gui.py` 的五頁 widget construction 移入 page builders。每批先寫 characterization test，只搬移、不改行為，通過後才進下一批。

## 全程邊界

- 不改 OCR threshold、ROI、parser、continuity、fallback、GUI 文案、callback 時序、設定或 IPC schema。
- 不保留未列入 manifest 的 incidental exports。
- 不讓新 module import `models.experience` aggregator。
- 不改 `maple_star.controller`、`maple_star.experience`、import-mode `maple_gamepad_macro` 的 module alias identity。
- 不 commit、tag、push、build release 或發佈。
- 任一批失敗只回退該批；不得順手修演算法。

## Task 0：Baseline 與 facade contract

### 檔案

- 新增 `tests/public_facade_manifest.py`
- 新增 `tests/test_public_facades.py`
- 新增 `docs/reviews/2026-07-17-stage-3-baseline.md`
- 修改 `docs/INDEX.md`

### 步驟

1. 記錄目前兩個巨型檔 LOC、manifest/P​​NG count、Python executable、performance 輸出。
2. 將設計規格的 root/facade exports、分類與 canonical owner 寫成純資料 manifest。
3. 寫 object identity、精確 `__all__`、alias import order、canonical `__name__` 測試。
4. alias subprocess 使用 `python -I`，script 內明確插入 resolved repository root。
5. 確認此批不修改 production code。

### 驗證

```powershell
python -m unittest tests.test_public_facades
python tools\verify.py full
git diff --check
```

## Task 1：Leaf constants 與 dataclasses

### 檔案

- 新增 `maple_star/models/experience_constants.py`
- 新增 `maple_star/models/experience_types.py`
- 新增 `tests/test_experience_module_boundaries.py`
- 修改 `maple_star/models/experience.py`

### 步驟

1. 先寫 defaults、equality、pickle、identity、standalone import 失敗測試。
2. 移動原 26–159 行一般 constants 至 constants leaf。
3. 移動原 185–290 行 dataclasses 至 types leaf；types 只依賴 constants、stdlib 與 NumPy typing。
4. 160–182 行 Pixel prototypes/weights/cache 暫留 aggregator。
5. aggregator 依 `constants -> types` 順序 re-export 同一 object。

### 驗證

```powershell
python -m unittest tests.test_experience_module_boundaries tests.test_public_facades
python tools\verify.py full
python tools\verify.py ocr-slow
git diff --check
```

## Task 2：Tracker

### 檔案

- 新增 `maple_star/models/experience_tracker.py`
- 修改 `maple_star/models/experience.py`
- 修改 `tests/test_experience_module_boundaries.py`

### 步驟

1. 先固定 constructor/public method signatures、status、sample acceptance 與 snapshot identity。
2. 移動 formatters、`ExperienceEfficiencyTracker` 及其全部 private methods。
3. tracker 只 import leaf types/constants；不得 import OpenCV/Paddle/GUI/controller。
4. aggregator re-export tracker symbols。

### 驗證

```powershell
python -m unittest tests.test_experience tests.test_experience_module_boundaries
python tools\verify.py full
python tools\verify.py ocr-slow
git diff --check
```

## Task 3：Text parsing

### 檔案

- 新增 `maple_star/services/experience_text_parsing.py`
- 修改 `maple_star/models/experience.py`
- 修改 `tests/test_experience.py`
- 修改 `tests/test_experience_module_boundaries.py`

### 步驟

1. 固定 parser、Paddle-result traversal、candidate ranking 與 sentinel/reason output。
2. 移動 normalization、stat/tooltip/general parser、reading constructors、candidate selection，以及 parser/Pixel/burst 共用的 `_select_continuity_compatible_reading_group`／`_experience_ocr_continuity_status`／`_continuity_group_rank` pure helpers。
3. 將 parser internal patch seam 改到 canonical module。
4. aggregator 保留 required test-only re-export identity。

### 驗證

```powershell
python -m unittest tests.test_experience tests.test_experience_module_boundaries
python tools\verify.py full
python tools\verify.py ocr-slow
git diff --check
```

## Task 4：Image processing

### 檔案

- 新增 `maple_star/services/experience_image_processing.py`
- 修改 `maple_star/models/experience.py`
- 修改 `tests/test_experience_module_boundaries.py`

### 步驟

1. 固定 ROI coercion、crop/resize、mask、binary variants、bar estimation outputs。
2. 移動 image-only helpers；module 只依賴 leaf types/constants、NumPy/OpenCV。
3. aggregator re-export required public/test-only symbols。
4. 以 manifest 全集合驗證，不硬編 sample 數量。

### 驗證

```powershell
python -m unittest tests.test_experience tests.test_experience_module_boundaries
python tools\verify.py full
python tools\verify.py ocr-slow
git diff --check
```

## Task 5：Pixel OCR

### 檔案

- 新增 `maple_star/services/experience_pixel_ocr.py`
- 修改 `maple_star/models/experience.py`
- 修改 `tests/test_experience.py`
- 修改 `tests/test_experience_module_boundaries.py`

### 步驟

1. 固定 continuity guard、attempt、glyph/template、candidate/selection outputs。
2. 移動原 160–182 行 prototypes/weights/cache 與全部 Pixel OCR helpers。
3. 允許單向依賴 text parsing、image processing 與 `experience_pixel_templates`；continuity status/rank 不在 Pixel 重複定義。
4. 將兩個 Pixel internal patch seam 改到 canonical module。

### 驗證

```powershell
python -m unittest tests.test_experience tests.test_experience_module_boundaries
python tools\verify.py full
python tools\verify.py ocr-slow
git diff --check
```

## Task 6：Paddle reader 與 spawn worker

### 檔案

- 新增 `maple_star/services/experience_paddle_reader.py`
- 新增 `tests/test_experience_worker_spawn.py`
- 修改 `maple_star/models/experience.py`
- 修改 `maple_star/release_ocr_smoke.py`
- 修改 `tests/test_experience.py`
- 修改 `tests/test_release_ocr_smoke.py`
- 修改 `tests/test_experience_module_boundaries.py`

### 步驟

1. 先固定 constructor fallback、failure cache、variant continuation、suppression restoration 與 logging isolation。
2. 移動 reader、suppression contexts、worker cache/entries、跨策略 orchestration。
3. 更新 suppression/parser/logger patch seam 到 canonical module。
4. worker entry 保持 module-level/pickleable；parent cache 為 `None`，非空 reader 只在 child。
5. 用真實 `ProcessPoolExecutor(..., mp_context=spawn)` 驗證 type identity、回傳與 child cache reuse，不載真模型。
6. 更新 release smoke canonical import，不改 smoke output。

### 驗證

```powershell
python -m unittest tests.test_experience tests.test_experience_worker_spawn tests.test_experience_module_boundaries tests.test_release_ocr_smoke
python tools\verify.py full
python tools\verify.py ocr-slow
git diff --check
```

## Task 7：GUI theme 與 contracts

### 檔案

- 新增 `maple_star/views/gui_theme.py`
- 新增 `maple_star/views/pages/__init__.py`
- 新增 `maple_star/views/pages/contracts.py`
- 新增 `tests/test_gui_page_builders.py`
- 修改 `maple_star/views/settings_gui.py`

### 步驟

1. 寫 page context/ref construction、無 controller/queue field、standalone import tests。
2. 移動 immutable theme constants；`gui_theme` 不 import settings GUI。
3. 定義五頁與 monitor controls 的 frozen Context/Refs、窄 widget Protocol。
4. 此批不改 builder dispatch 或 runtime timing。

### 驗證

```powershell
python -m unittest tests.test_gui_page_builders tests.test_gui_notice_position
python tools\verify.py full
python tools\verify.py performance
git diff --check
```

## Task 8：Console 與 Potion builders

### 檔案

- 新增 `maple_star/views/pages/console_page.py`
- 新增 `maple_star/views/pages/potion_page.py`
- 修改 `maple_star/views/settings_gui.py`
- 修改 `tests/test_gui_page_builders.py`
- 修改 `tests/test_gui_notice_position.py`

### 步驟

1. 先寫 shell/text 兩階段、scrollbar refs、callback、partial failure/retry tests。
2. 移動 Console shell/text construction；成功後才 publish refs。
3. 移動 Potion page/cards；context 只帶 HP/MP vars 與該頁 callbacks。
4. close/cancel 時清除 after id、placeholder 與 partial widgets。

### 驗證

```powershell
python -m unittest tests.test_gui_page_builders tests.test_gui_notice_position
python tools\verify.py full
python tools\verify.py performance
git diff --check
```

## Task 9：Minimap 與 Combo builders

### 檔案

- 新增 `maple_star/views/pages/minimap_page.py`
- 新增 `maple_star/views/pages/combo_page.py`
- 修改 `maple_star/views/settings_gui.py`
- 修改 `tests/test_gui_page_builders.py`
- 修改 `tests/test_gui_notice_position.py`

### 步驟

1. 固定 collapse/visibility、callback binding、responsive layout 與 retry。
2. 移動 Minimap main page builder。
3. 移動 Combo main builder與 slot row/script/controller/seconds helpers。
4. GUI 只在完整成功後保存 refs並執行既有 visibility/collapse sync。

### 驗證

```powershell
python -m unittest tests.test_gui_page_builders tests.test_gui_notice_position
python tools\verify.py full
python tools\verify.py performance
git diff --check
```

## Task 10：Monitor builders 與 final gate

### 檔案

- 新增 `maple_star/views/pages/monitor_page.py`
- 新增 `docs/reviews/2026-07-17-stage-3-review.md`
- 修改 `maple_star/views/settings_gui.py`
- 修改 `tests/test_gui_page_builders.py`
- 修改 `tests/test_gui_notice_position.py`
- 修改 `docs/project-structure.md`
- 修改 `docs/INDEX.md`

### 步驟

1. 固定 primary monitor refs、`after(250)` controls、cancel/close、exception retry 與 compact visibility。
2. 移動 primary monitor builder；publish完整 refs後才進既有同步。
3. 移動獨立 `build_monitor_controls`；保留 `monitor_controls_after_id` 與 250ms timing。
4. 計算 final LOC、module DAG、manifest/fixture、startup/page-switch 結果並寫 review。
5. 確認 aggregator 無演算法實作、兩個巨型檔各縮小至少 30%、所有新手寫檔小於 2,000 行。

### 驗證

```powershell
python -m unittest tests.test_gui_page_builders tests.test_gui_notice_position
python tools\verify.py full
python tools\verify.py ocr-slow
python tools\verify.py performance
git diff --check
```

## 最終交付

- 報告各批結果、LOC、startup/page latency、OCR fixture 與 facade contract。
- 列出任何因安全邊界未抽取的 residual coupling。
- 保持所有變更 unstaged；未獲明確要求不 commit。
