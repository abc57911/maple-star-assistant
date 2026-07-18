# 全 App 最大效能架構重構

> 知識庫索引：[../../INDEX.md](../../INDEX.md)

## 決策狀態

本規格已由使用者核准。它取代 [PySide6 GUI 重設計](2026-07-18-pyside6-gui-redesign-design.md) 中「保留 legacy GUI」與「controller 留在 GUI process」的決策。既有 [自動巡航安全性、業務判斷與效能強化](2026-07-18-minimap-cruise-hardening-design.md) 仍是輸入安全與巡航業務契約；本規格只改變 process ownership、IPC、GUI 與效能驗收。

已核准的產品邊界：

- PySide6 全面取代 CustomTkinter；完成後刪除 legacy GUI 與依賴。
- GUI 關閉時停止全部自動化、釋放按鍵並結束全部 child process。
- 接受較高記憶體與啟動成本，以執行期響應、隔離及安全為優先。
- 以開發電腦作硬性效能 gate；筆電執行最終功能 smoke。
- 新版設定可調整 schema，但必須自動遷移舊 `settings.json` 與 profiles。
- 維持單一 App 與單一啟動入口；backend 與 worker 在內部隱藏執行。
- GUI 可重新設計資訊架構，但不得移除功能或設定能力。

## 背景

目前自動喝水、EXP 與控制 runtime 已分成 process，controller 也已拆出多個 service。主要殘留問題如下：

- CustomTkinter 建立大量 widget，首次建頁、切換與 DPI resize 成本高。
- GUI、controller orchestration 與 worker health 仍有耦合；部分狀態靠週期 pump 同步。
- potion heartbeat 每秒送出，watchdog 兩秒即重啟；工作延遲可能被誤判成 process dead。
- status、urgent event 與安全控制尚未形成一致的 backpressure 契約。
- 影像經 IPC 傳輸時若複製完整 frame，會增加 serialization、記憶體頻寬與延遲。
- 各 runtime 各自送鍵會增加 ownership、失焦與 shutdown cleanup 的推理成本。

本次重構建立 Qt-only GUI、獨立 backend supervisor、單一 realtime input owner、領域 worker、typed IPC 與可重複效能 gate。

## 目標

- GUI main thread 不執行 OCR、OpenCV、capture、網路、音效或同步 backend update。
- 巡航、手把組合、週期鍵與 potion action 不受 GUI、OCR 或通知負載阻塞。
- 任何時刻只有 realtime control process 能呼叫低階 Windows input。
- worker 可獨立 crash、重啟及量測；非安全關鍵 worker 不拖垮全 App。
- 使用 bounded channel、generation、deadline 與 immutable snapshot 防止 backlog、舊狀態及重繪風暴。
- 將 process liveness 與 work-loop progress 分開，消除 heartbeat 瞬間延遲造成的誤重啟。
- 舊設定與 profiles 自動、可回復地遷移到新版 schema。
- Python 與 packaged EXE 皆通過正確性、效能、壓力與 shutdown gate。

## 非目標

- 不支援 GUI 關閉後繼續 headless 自動化。
- 不拆成多個使用者可見 EXE 或 Windows service。
- 不支援多開楓之谷或多目標 HWND 自動切換。
- 不以 `REALTIME_PRIORITY_CLASS`、固定 CPU affinity 或無量測的 busy spin 追求數字。
- 不改變已核准的巡航按鍵持有時間、邊界判斷與安全停止語意。
- 不重寫已可獨立測試的 OCR、potion engine、minimap service 演算法；只有 profiling 證明 hot path 時才調整內部實作。
- 不保留 CustomTkinter runtime fallback。

## 方案選擇

採用領域 process 架構。Qt GUI 只負責顯示、輸入與 command；backend supervisor 管理 worker；CPU-heavy 與可能阻塞的工作各有明確 process owner。

不採用以下方案：

- **單一 backend process 加 thread pool**：OCR、capture 或 native library 卡住時仍會影響其他功能。
- **每個小 service 都建立 process**：IPC、記憶體、spawn、打包及錯誤恢復成本超過收益。
- **GUI 獨立但 controller 留在 GUI process**：Qt event loop 仍承擔 backend orchestration，不符合隔離目標。

## Process 與 thread ownership

### Qt GUI process

GUI process 擁有：

- `QApplication`、`QMainWindow`、所有 widget 與 signal/slot。
- Backend receiver 與 sender 各一條 `QThread`。Receiver可阻塞等待snapshot，sender消費GUI process內的bounded mailbox；兩者只能透過Qt queued signal回報main thread，不能直接操作widget。
- `QThreadPool`。只執行 GUI 局部短工作，例如 frame metadata 驗證、`QImage` 建構、設定 draft 驗證及 Console batch 整理。

GUI process 不 import 或建立 OCR engine、capture context、低階輸入 sender、Telegram client 或同步音效播放器。

### Backend supervisor process

Supervisor 擁有：

- worker 建立、健康狀態、有限重啟與 shutdown 次序。
- 設定 transaction、generation 分配與 target HWND 發布。
- worker snapshot 彙整、signature 去重與 GUI snapshot 發布。
- preview transport resource 的生命週期與 cleanup 協調；shared memory只有decision gate通過後才啟用。

Supervisor 不執行 OCR、capture、輸入排程或 GUI rendering。

### Input guardian process

Input guardian 是唯一低階 Windows input writer。它不執行 vision、業務判斷或複雜排程，只負責：

- 驗證 input command 的 session、incarnation、generation、deadline、target foreground 與 ownership token。
- 呼叫低階 `key_down`、`key_up`、controller input、staged tap與cursor mutation實作。
- 保存全 App held-key ownership、pending release 與最後已確認的輸入 sequence。
- 監聽獨立 terminal emergency event；shutdown、fatal crash、session lease失效時立即永久停止接受新command並 `release_all`。Terminal event在該guardian incarnation內永不clear。
- 使用 supervisor 可讀的 write-ahead ownership ledger。Guardian 在 `key_down` 前先登記 `may_be_held` 並取得ledger acknowledgement，送出成功後標記 `confirmed_held`；`key_up` 成功後才清除。Emergency release使用 `may_be_held ∪ confirmed_held`，因此guardian即使死在低階呼叫與checkpoint之間也不會漏放。
- 每次 ownership transition 都帶command sequence並向supervisor回報checkpoint；重複command不得重複改變ownership。
- 提供有deadline的cursor lease。Experience OCR申請lease後，guardian記錄原始cursor位置、移動並ack；OCR完成capture後release，guardian恢復位置。OCR crash、lease timeout或terminal emergency都會恢復cursor。OCR可讀cursor position做使用者移動檢查，但不能呼叫cursor mutation API。

只有 guardian role 可 import 低階 input implementation。正常 guardian 掛掉時，supervisor 必須先以 OS process handle 確認舊 instance 已退出，再啟動同一 guardian entrypoint 的 `emergency-release-only` instance，使用最後ledger與checkpoint對所有可能held VK執行冪等 `key_up`。兩個 guardian instance 不得同時存活。

### Realtime scheduler process

Realtime scheduler 擁有：

- 巡航、手把組合、週期鍵、potion action 與其他高解析 deadline state machine。
- 精確目標 HWND state、設定 generation 與 action intent 驗證。
- pygame controller adapter thread：只輪詢 SDL event，將 normalized controller state 放入 bounded mailbox，不送鍵。
- hotkey adapter thread：集中`GetAsyncKeyState` polling、長按確認及emergency-stop hotkey；emergency-stop先停止scheduler deadline，再透過獨立safety control pipe建立可恢復`SafetyFence`，不設定terminal event。
- GUI 全域 key-capture request 的狀態機與結果；Qt 自身聚焦時的文字／按鍵事件仍由 GUI main thread 處理。

Scheduler 將具 deadline 與 ownership role 的 `InputCommand` 送給 guardian。它不 import 低階 input implementation。pygame 或 hotkey adapter thread 卡住時只失去對應輸入來源，不得阻塞 scheduler deadline loop。

EXP tooltip capture transaction由Experience OCR process擁有，但cursor mutation透過guardian cursor lease完成。小地圖校正由GUI發出request，Potion／Realtime vision path回傳client-relative observation，GUI不直接建立capture context。

### Potion vision process

Potion vision 擁有 HP／MP HUD 定位、capture、百分比判讀、送鍵前確認所需的 vision state。它將具 deadline 的 potion action intent 送給 realtime scheduler，不直接送鍵。

### Experience OCR process

Experience OCR 擁有 EXP capture、Pixel OCR、PaddleOCR fallback、統計 tracker 與對應 native resources。它不 import GUI 或低階輸入模組。

### Notification/media process

Notification/media 擁有 Telegram、音效及其他可能阻塞的 I/O。它以 priority channel 接收事件；低優先重複事件可合併，安全與錯誤事件不可丟失。

### Process priority

- Input guardian 與 Realtime scheduler 使用 `ABOVE_NORMAL_PRIORITY_CLASS`。
- GUI、supervisor 與 potion vision 使用 Normal。
- Experience OCR 與 notification/media 預設使用 Normal；只有 benchmark 證明有益且不影響完成時間時才降為 Below Normal。
- 不使用 realtime priority。CPU affinity 必須有 profiling 報告及獨立驗收，不能作預設設定。

### Topology 與 interface 表

| Unit | Owned resources | Inbound | Outbound | Startup dependency | Failure policy |
| --- | --- | --- | --- | --- | --- |
| Qt GUI | widgets、Qt models、receiver/sender threads | GUI snapshot、urgent event、command ack | typed GUI command | supervisor session ready | GUI crash 觸發全域 shutdown |
| Supervisor | process handles、session epoch、settings truth、health registry | GUI command、worker health/snapshot/ack | lifecycle、prepare/commit、snapshot | 無 | fatal；不得讓 worker orphan |
| Input guardian | Win32 input handle、held-key/cursor ownership、terminal event | `InputCommand`、SafetyFence/Rearm、terminal stop | input ack、ownership checkpoint | supervisor session | fatal safety failure；先 release，禁止自動恢復 |
| Realtime scheduler | deadline heap、巡航/組合狀態、pygame/hotkey adapters | settings、target、potion intent、device state | `InputCommand`、control snapshot | guardian ready | fatal automation failure；guardian release |
| Potion vision | GDI/MSS/OpenCV capture state、HP/MP cache | settings、target、feature state | potion intent、potion snapshot、preview payload/descriptor | guardian 與 scheduler ready | degraded；有限重啟 |
| Experience OCR | EXP capture、cursor transaction、Pixel/Paddle OCR | settings、target、feature state | EXP snapshot、diagnostic frame | supervisor session | degraded；有限重啟 |
| Notification/media | Telegram client、media handles | priority event | delivery ack、health | supervisor session | degraded；有限重啟 |

每個 unit 都有獨立 entrypoint、Protocol、fake transport 與 process contract test。GUI process 只建立 supervisor；supervisor 必須以 non-daemon process 建立其他 worker。

## IPC 契約

所有跨 process payload 使用具名、可序列化、不可變 dataclass。每筆訊息包含：

- `session_epoch`：GUI 每次啟動產生的 UUID；舊 session 訊息一律拒絕。
- `worker_role` 與 `worker_incarnation`：supervisor 每次建立 worker 時遞增 incarnation。
- `stream_sequence`：每個 `(session_epoch, worker_role, incarnation, channel)` 從 1 遞增；incarnation 改變後可重設。
- `settings_generation` 與 `target_generation`：只表示已 commit 的 domain state，不取代 session/incarnation。
- monotonic `created_at`；action 另有 `expires_at`。

Receiver 先比 session，再比 role/incarnation，最後比較 sequence 與 generation。worker restart 時建立新 queue/pipe 或先 drain 舊 transport；即使舊訊息殘留，也會因 incarnation 不符被拒絕。模組邊界不得傳 controller、GUI、capture handle、Qt object 或可變 settings instance。

### Command channel

GUI 將 command 送給 supervisor，再由 supervisor 發布給 worker。設定、目標 HWND 與 feature enable state 使用 bounded latest-wins mailbox：

- queue 飽和時取代尚未消費的舊 snapshot。
- worker 拒絕較舊 generation。
- enable、target 與 settings 的相依狀態須由同一 transaction generation 表達。

### Realtime action channel

Potion vision 可直接將 `PotionActionIntent` 送到 realtime scheduler，避免 supervisor 多一跳。Intent 至少包含：

- bar type、key/VK 與產生原因。
- detected percent、confirm metadata 與 capture timestamp。
- settings generation、target generation、sequence。
- `expires_at`；過期 intent 必須丟棄，不能補發。

Realtime scheduler 在產生 `InputCommand` 前重查 feature enabled、target、generation、deadline 及 ownership 衝突；guardian 在實際送鍵前再檢查 session、incarnation、deadline、foreground 與 ownership token。

### Safety channel

Safety lifecycle分成可恢復fence與不可恢復terminal emergency：

- 可恢復的失焦、一般stop與feature disable使用control pipe上的`SafetyFence(operation_id, safety_generation)`。
- Guardian state固定為 `ARMED -> BLOCKING -> RELEASING -> SAFE -> REARMING -> ARMED`。收到fence後拒絕generation不高於fence的新input，完成release後回覆`Safe`。
- 重新聚焦或再次啟用時，Supervisor只有在target/settings已commit、scheduler無舊deadline、guardian ownership為空後，才送`Rearm(new safety_generation)`；Guardian ack後才接受新input。
- 同時到達的新fence或terminal event永遠優先於rearm。Guardian只接受嚴格遞增的safety generation，舊rearm不能clear新fence。
- 不可恢復的shutdown、fatal crash與session lease失效使用terminal emergency event；該incarnation不能rearm。

Safety control不與一般command/status共用queue：

- Terminal event提供不阻塞wakeup；重複set具冪等性且永不clear。
- Control message 帶 operation id；guardian 回覆 acknowledgement 與 ownership checkpoint。
- Supervisor 在 deadline 內重送相同 operation id，guardian 去重但重送 ack。
- 接收端hang時，supervisor先停止scheduler，再依guardian hang流程終止舊guardian並啟動emergency-release-only guardian；新guardian使用新incarnation且保持terminal mode。
- 「必須交付」指 safety outcome 必須完成或升級到 emergency guardian，不代表 bounded queue 的單次 `put` 永遠成功。

### Snapshot channel

Worker 發布 domain snapshot，supervisor 彙整成 GUI snapshot：

- channel bounded 且只保留最新 snapshot。
- 相同核心 signature 不重送。
- transient notice 與 Console 不屬於核心 signature。
- GUI 只套用最新 sequence；過期 snapshot 不得回寫 widget。

### Urgent event channel

錯誤 notice、Telegram、音效與 Console 使用 priority event；它不承擔 `release_all`、stop 或 shutdown：

- fatal error event必須交付或升級為worker failed state；安全控制只走Safety channel。
- 相同的一般 notice 可合併。
- Console 使用 bounded ring buffer；溢位時記錄 dropped count，不能無限成長。
- 音效與 Telegram 不得反向阻塞 realtime 或 vision worker。

### Preview image transport 決策 gate

第 1 批先量測實際 ROI/frame 大小、更新率、serialization CPU time、copy latency 與 queue memory。預設採 bounded serialized bytes；只有下列條件全部成立才切換 shared memory：

- preview serialization 或 copy 的 p95 超過 `2 ms`，或占該 producer CPU time `>= 5%`。
- Windows Python 與 packaged EXE spike 都通過 create、publish、consumer crash、producer restart、GUI crash 及 cleanup 測試。
- shared-memory p95 至少比 serialized path 快 `30%`，且沒有增加 torn frame 或 shutdown failure。

若啟用 shared memory，protocol 固定如下：

- Supervisor 建立具 `session_epoch + producer role + incarnation` 名稱的 segment，擁有 unlink；producer/consumer 只 close。
- 每個 slot 有 header seqlock。Producer 將奇數 version、payload、checksum、metadata、偶數 version 依序寫入，再透過 snapshot channel 發布 descriptor。
- Consumer 讀取前後比對相同偶數 version、frame id 與 checksum；不一致就丟棄 frame。
- GUI receiver 立即 deep-copy payload 到 owned `QImage` buffer，完成後才交給 GUI main thread，不讓 `QImage` 指向可覆寫 shared memory。
- Producer restart 使用新 incarnation 與新 segment；舊 segment 等所有 consumer detach 或 cleanup deadline 後由 supervisor unlink。
- Supervisor 維護 segment registry；啟動時只清理可證明屬於已終止 MapleStar session 的 stale segment。不得依模糊 prefix 刪除未知 segment。

## Health、逾時與重啟

Health 分成兩個訊號：

- **Process heartbeat**：輕量 health thread 回報 process 與 IPC thread 仍存活。
- **Work-loop progress**：業務 main loop 更新 phase、operation id、開始時間及最後完成時間。

第 1 批量測每種 phase 的正常 p50、p95、p99 與 maximum，並寫入 versioned health policy 表。任何 worker cutover 前，該表必須定義：heartbeat interval、stale threshold、phase deadline、grace period、最大重啟次數、退避序列及清零重啟計數所需的穩定期。初始安全下限為 heartbeat `1 s`、stale threshold 不低於 `5 s`、連續穩定 `60 s` 才清零 restart budget；phase deadline 不得小於 baseline p99 的兩倍。

Supervisor 不得因一次 heartbeat 延遲直接重啟 process。判斷規則如下：

- OS process 已退出：立即標記 crash。
- heartbeat stale，但 work progress 仍在合法 deadline 內：先記錄並等待。
- heartbeat 正常，但 work progress 超過 phase deadline：視為 work-loop hang。
- heartbeat 與 progress 都 stale：進入該 worker 的停止與重建流程。

每次判斷需記錄 PID、process creation time、session/incarnation、generation、phase、queue depth、heartbeat age 及 progress age。預設 restart budget 為同一 role 在十分鐘內三次，退避為 `0.5 s、2 s、10 s`；超過 budget 進入 failed/degraded 或 fatal state，不再自動重啟。第 1 批可依量測收緊，不得放寬到無限重試。

Input guardian 或 Realtime scheduler crash 屬 fatal safety failure：停止全部自動化、由存活 guardian或 emergency-release-only guardian 完成 release，且不自動恢復巡航。Potion、OCR 及 notification worker 可個別重啟；重啟後 feature 只有在設定 transaction 對齊且 supervisor 確認 ready 時才恢復。

## Startup 與 parent-death state machine

### Startup

App 使用 `CREATED -> STARTING -> READY | DEGRADED | FAILED -> STOPPING -> STOPPED`：

1. GUI launcher 建立 session epoch、control pipe 與 supervisor。
2. Supervisor 建立 input guardian並等待 `GuardianReady`。
3. Supervisor 建立 realtime scheduler，重播 committed settings/target snapshot，等待 scheduler 與 guardian互相確認 incarnation。
4. Supervisor 建立 potion vision、Experience OCR、notification/media；每個 worker先收 current committed snapshot，再回覆 ready。
5. Guardian 與 scheduler 未 ready 前，所有 automation command 都回覆 unavailable；potion intent 直接丟棄。
6. Guardian或scheduler啟動失敗為 `FAILED`。Potion、OCR、notification失敗可進 `DEGRADED`，GUI 顯示 unavailable feature 與原因。
7. Supervisor 發布完整 initial snapshot 後，GUI 才允許啟用 automation。

Worker restart 使用 `STOPPING -> STARTING(new incarnation) -> REPLAYING -> READY`。Supervisor 只重播最後 committed settings、target 與停用狀態；不得重播 action intent、held-key command 或週期 backlog。

### GUI crash 與 orphan cleanup

Supervisor 同時監聽 GUI control pipe EOF、launcher process handle 與 session lease。GUI 正常 close、crash、Task Manager 結束或 backend sender/receiver thread 永久失聯，都會使 lease 失效並觸發全域 shutdown。

Packaged Windows build使用一個只包含scheduler、potion、experience與notification的kill-on-close Worker Job Object。Supervisor是唯一job handle owner；GUI不持有或duplicate該handle。Input guardian不加入Worker Job，而是持有GUI與supervisor的waitable process handles；任一handle signaled時，guardian設定自己的terminal emergency、完成release並退出。Supervisor crash時，OS關閉Worker Job handle並終止非guardian workers；guardian仍可獨立release。正常shutdown時，Supervisor先完成guardian release/exit，再關閉最後job handle。Job kill只清除非guardian orphan，不取代guardian release protocol。

Supervisor 在 GUI lease 失效後不得繼續 headless automation。它設定 guardian terminal emergency，再依安全 shutdown 次序結束 worker。GUI 端 sender 與 receiver 各使用一條 `QThread`：main thread 只呼叫 non-blocking bounded local mailbox；sender thread 負責 pipe write，receiver thread負責 blocking read。Shutdown 先 close pipe 喚醒兩條 thread，再以有界 deadline join；不得以 `terminate()` 結束 `QThread`。

### Windows spawn 與 packaged child role

- `main.py` 與 `main.pyw` 的 `if __name__ == "__main__"` 先呼叫 `multiprocessing.freeze_support()`，再執行唯一 launcher。
- 所有 process target 都是可 import module 的 top-level function；不得使用 lambda、bound Qt method 或 closure。
- Launcher 透過不可由使用者偽造的 inherited bootstrap payload／multiprocessing spawn data 決定 `supervisor`、`guardian`、`scheduler`、`potion`、`experience` 或 `notification` role。Child role 不解析一般 GUI CLI，也不建立 `QApplication`。
- 單例鎖只由 GUI launcher取得。Child role不取得GUI singleton lock、不重設主log，也不遞迴啟動 supervisor。
- Qt、PaddleOCR、pygame與各native library在role entrypoint內lazy import；guardian不得載入Qt/Paddle，GUI不得載入Paddle或低階input adapter。
- Resource path使用統一 resolver，分開處理source tree與PyInstaller `_MEIPASS`；working directory不作resource truth。
- Supervisor及worker必須是non-daemon process，才能由supervisor建立與有序join。Packaged smoke檢查每個role的import graph、PID tree與正常close。

## 設定 transaction 與遷移

### Runtime transaction

設定使用coordinator-owned prepare／stage／activate protocol；Supervisor是唯一transaction coordinator：

1. GUI 將使用者輸入寫入 draft model並完成欄位級型別與範圍驗證。
2. Supervisor 建立 transaction id、candidate snapshot 及新 generation，狀態進入 `PREPARING`。
3. 各受影響 worker validate candidate、保留 prepared state，但不修改 active state；在 prepare deadline 內回覆 `Prepared` 或 `Rejected`。
4. 任一拒絕、逾時或 crash 時，Supervisor 發布 `Abort(transaction_id)`；worker 刪除 prepared state，全部保留舊 generation。
5. 全部prepared後，Supervisor先要求guardian/scheduler完成受影響的key release與deadline cancellation，再將candidate寫入`settings.pending.<transaction_id>.json`；pending檔不是啟動truth。
6. Supervisor發布`Stage(transaction_id, generation)`；worker原子交換到committed-but-inactive pointer並回覆`Staged`。Staged generation不得產生action或重新arm guardian。
7. Stage acknowledgement未齊時，Supervisor停用受影響feature、發布abort並重啟未確認worker；新worker只重播disk上的committed snapshot。Pending檔刪除或保留作診斷，但不能成為truth。
8. 全部staged後，Supervisor以temporary file + fsync + atomic replace更新正式`settings.json` committed record；成功後發布`Activate(transaction_id, generation)`。
9. Worker收到Activate才允許新generation產生action並回覆`Activated`。必要ack未齊時保持feature停用，重啟worker並重播已原子保存的新committed snapshot。
10. Supervisor收到全部必要Activated ack後才將transaction標為`COMMITTED`、刪除pending journal並通知GUI。

Supervisor crash不就地恢復automation；新的App session使用新epoch，只讀正式`settings.json` committed record，忽略或隔離pending journal，且所有feature預設停用。Prepare/Stage/Activate payload必須冪等，worker以transaction id去重。

### Disk schema migration

- 新 schema 必須有整數 `schema_version`。
- migration 以連續、可測試的 `vN -> vN+1` function 組成。
- 舊 `settings.json` 與 profiles 載入後先驗證，再遷移到目前版本。
- 寫入前在同目錄保留備份；新檔採 temporary file、flush、fsync 與 atomic replace。
- migration 失敗時保留原檔，App 進入可診斷的安全停用狀態；不得以空白預設值覆蓋使用者設定。
- Root schema 固定包含 `schema_version`、`global`、`profiles`、`selected_profile` 與 `migration` metadata。每個 profile payload 不另設獨立版本，統一由 root schema version 遷移，避免部分 profile 版本分裂。
- Migration 對全部 profiles 先在記憶體完成並驗證；任一 profile 失敗即整筆 abort，不允許部分成功。
- 已知欄位依 typed schema 正規化；未知欄位保存在 root `extensions` 或 profile `extensions`，避免新版誤刪未識別資料。與安全或輸入衝突的未知欄位不得啟用功能。
- 備份命名為 `settings.v<old>-<UTC timestamp>.bak.json`，至少保留最近三份；只有新檔 atomic replace 成功後才寫入 `migration.from_version`、`to_version` 與完成時間。
- 第 1 批必須產出 current schema 到 settings v2 的逐欄 mapping、預設值、global/profile ownership 與 round-trip fixtures；沒有 mapping 不得開始 production migration。

## PySide6 GUI

### 資訊架構

GUI 使用 `QMainWindow`、固定側邊導航與 `QStackedWidget`：

- **Dashboard**：全域啟停、目標視窗、worker health、HP／MP、EXP 與最近動作。
- **自動喝水**：HP／MP 門檻、藥水鍵、偵測狀態、HUD preview 與異常原因。
- **自動巡航**：邊界校正、攻擊／技能、週期鍵、紅點／測謊警示與即時狀態。
- **手把與組合**：組合 A/B、controller mapping 與 hold/tap timing。
- **診斷**：Console、worker health、IPC latency、capture/OCR timing、queue depth 與錯誤紀錄。

### Rendering 與 binding

- 啟動先顯示 shell，再分批建立頁面；正式啟用功能前完成全部 signal binding。
- 頁面建立完成後，切頁只呼叫 `setCurrentIndex()`。
- 週期鍵、組合欄位使用 `QAbstractTableModel`、delegate 與可重用 editor，避免數百個獨立 widget。
- 數值欄位使用 `QSpinBox` 或 `QDoubleSpinBox`。
- Console 使用 `QPlainTextEdit`、最大 block count 與有上限的 batch append。
- Preview 只替換最新 frame id 的 pixmap；相同內容不重畫。
- Backend 狀態由 queued signal 推送；GUI 不執行高頻全量 model pull。
- 程式同步 widget 使用 `QSignalBlocker`，不得誤觸使用者 transaction。
- resize、DPI、中文輸入法與切頁不得暫停 backend scheduler。

### Toolkit 移除

完成 Qt parity 與對應測試後，同一重構分支必須移除：

- CustomTkinter GUI modules、theme、layout 與 Tk console writer。
- `customtkinter` dependency 與 PyInstaller collect 規則。
- controller 對 `.root`、`after()`、`mainloop()`、`pump()` 或 Tk variable 的依賴。

不提供 `--legacy-gui`。回退只能透過版本控制或上一版 release，不能在同一 executable 內切換 backend。

## 模組邊界

預計新增或重整：

```text
maple_star/app/          launcher、composition root、Qt lifecycle
maple_star/backend/      supervisor、worker registry、health、shutdown
maple_star/ipc/          messages、channels、mailbox、shared frames
maple_star/views_qt/     main window、bindings、models、pages、notices
maple_star/workers/      realtime、potion vision、experience OCR、notification
maple_star/models/       settings v2、migration、domain snapshots
```

既有 `maple_star.controller`、`maple_star.experience`、`maple_star.gui`、`maple_star.settings`、`maple_star.win_input`、`auto_potion.py` 與 `maple_gamepad_macro.py` 保留 module import path。第 1 批建立逐 symbol API manifest，依下列規則處理：

- Models、解析器、常數與無副作用 helper 維持相容 export。
- GUI symbols 重新 export Qt implementation，不保留 Tk object 或 Tk-specific behavior。
- `key_down`、`key_up`、`tap_key`、cursor mutation等低階input symbol不得繼續直接呼叫Win32 input。若manifest證明有repository consumer，改成需要active session的guardian IPC client；若沒有consumer且不屬文件化public API，從general facade移除並在migration note列出。Read-only cursor/window query可留在domain adapter。
- 真正低階 implementation 移到 guardian-only private adapter。靜態測試只允許 guardian entrypoint/import graph 載入該 adapter；測試可注入 fake adapter。

Facade 不放新實作，也不得重新引入 Tk。相容性指 import path 與已確認 public contract，不代表保留會破壞唯一 input writer 的 direct-send side effect。

## 安全 shutdown

GUI close、fatal error、Ctrl+C、Windows session ending 與最外層 `finally` 共用單一冪等 shutdown coordinator：

1. GUI 禁止新 command，標記 closing。
2. Supervisor 發布 stopping generation，拒絕新 action intent。
3. Realtime scheduler 停止排程並取消 deadline；guardian 拒絕新 command並釋放全部按鍵。
4. Supervisor 等待明確的 `ReleaseAllCompleted`。Guardian 逾時時，先終止並確認舊 guardian PID 已退出，再啟動 emergency-release-only guardian；Supervisor 本身不送鍵。
5. 停止 potion、OCR 與 notification worker。
6. 關閉preview transport、queue、pipe、log handler與sender/receiver threads。
7. 確認無 child process 後退出 Qt event loop。

單一 cleanup step 失敗不得阻止後續 step。所有 process join 都有 deadline；terminate 只能在 graceful shutdown 失敗後使用。

## Implementation plans 與遷移 gate

本規格必須拆成四份 implementation plan。每份 plan 可再分小批 commit；下一份只能在上一份 exit gate 通過後開始。

### Plan 1：Baseline、API／settings schema、IPC 與 Windows feasibility

- **Entry**：目前 main branch、legacy App 可啟動、現有直接相關測試有記錄。
- **工作**：功能 parity matrix、逐 symbol API manifest、settings v2 mapping、Python／EXE baseline、session/incarnation messages、bounded transport spike、shared-memory decision spike、top-level spawn entrypoints 與 PyInstaller child-role smoke。
- **Production state**：production entrypoint、Tk GUI 與舊 runtime process contract不變；新 IPC只在 tests/spike 使用。
- **Exit**：所有 mapping/manifest 完整；Windows Python與EXE spawn smoke通過；health policy 表與 preview transport 決策有 raw evidence。
- **Rollback**：刪除未接入 production 的新 modules/tests；不需資料回復。

### Plan 2：Supervisor lifecycle、health、transaction 與 orphan cleanup

- **Entry**：Plan 1 exit gate 通過，session/incarnation schema凍結。
- **工作**：supervisor、worker registry、startup/restart state machine、prepare/stage/activate settings transaction、parent-death lease、Job Object、Qt-neutral client fake、ordered shutdown。
- **Production state**：legacy GUI/controller透過 adapter驅動新 supervisor；現有 domain worker business implementation先包裝成新 role，不改低階input owner。
- **Exit**：worker crash、GUI crash、orphan、prepare/commit crash、state replay及shutdown chaos tests通過；legacy App功能不退化。
- **Rollback**：composition root切回舊 `RuntimeProcessCoordinator` adapter；disk仍使用舊 schema或經驗證的雙讀 reader。

### Plan 3：Input guardian、Realtime scheduler 與 domain worker cutover

- **Entry**：Plan 2 lifecycle/transaction gate通過；guardian-only import contract已能執行。
- **工作**：input guardian、emergency guardian、scheduler、pygame/hotkey adapters、potion intent、Experience OCR與notification role、preview transport選定方案。
- **Production state**：legacy GUI仍可使用，但所有 automation經新 supervisor；每個 domain依序cutover，不允許同一功能同時由舊新worker送鍵。
- **Exit**：唯一 writer靜態/動態contract、失焦/停止/guardian crash cleanup、混合負載jitter、potion watchdog及domain restart tests通過。
- **Rollback**：每個 domain以feature adapter單獨切回舊worker；只有所有held keys已release且舊process已停後才能切換owner。

### Plan 4：Qt GUI、production cutover、packaging 與 soak

- **Entry**：Plan 3 backend與所有domain correctness/performance gate通過。
- **工作**：Qt shell、五頁、typed bindings、sender/receiver QThreads、settings migration UI、唯一入口、移除Tk/CustomTkinter、Qt packaging、benchmark與60分鐘soak。
- **Production state**：同一分支完成Qt parity後原子切換entrypoint；不發布Tk與Qt功能各半的artifact。
- **Exit**：功能parity、public manifest、Python/EXE、GUI、chaos、shutdown、60分鐘soak與筆電smoke全部通過。
- **Rollback**：在release前使用版本控制回到Plan 3最後通過點；release後回退上一版artifact，不在同一EXE保留legacy backend。

任一 plan 改變跨 process schema時，需先提供 backward-compatible reader，或在同一小批原子切換所有 producer／consumer。工作樹不得停在會把舊訊息誤讀成新 schema 的狀態。每份 plan 都要列出 intended files、精準測試、raw benchmark artifact、已知風險與 rollback command。

## 測試

### Unit 與 contract

- settings migration、atomic save、損壞檔案與 rollback。
- message serialization、generation、sequence、deadline 與 signature。
- latest-wins mailbox、priority channel、Console overflow 與 stale intent drop。
- 每個 worker 的 import isolation 與 public facade matrix。
- Guardian-only private adapter 與 unsafe facade symbol manifest 的靜態 contract。

### Process integration

- Windows `spawn` 啟動、ready、command、snapshot、graceful stop 與 forced termination fallback。
- worker crash、重啟、generation 切換與 state replay。
- Preview transport 的 serialized baseline；若decision gate選擇shared memory，再測frame publish、consumer detach、producer crash與stale segment cleanup。
- GUI command 到 worker，再回 GUI snapshot 的 end-to-end round trip。

### Safety 與 chaos

- heartbeat 延遲但 work-loop 正常，不得重啟。
- heartbeat 正常但 work-loop hang，必須按 phase deadline 恢復。
- queue 飽和時 safety command 仍可交付。
- close 與 action intent、settings commit、失焦或 worker crash 同時發生。
- 所有停止路徑都釋放或保留可重試的 held-key ownership。
- Input guardian或Realtime scheduler crash 後不自動恢復自動化。

### Qt GUI

- 五頁建立、導航、typed binding、`QSignalBlocker` 與設定 transaction。
- Table model／delegate 編輯不重建整頁。
- Console block count、batch 上限與 dropped count。
- Shared frame 更新、過期 frame drop 與 pixmap reuse。
- Windows 真實 GUI 的 DPI、resize、中文輸入、notice 位置及 close cleanup。

### Packaging

- PyInstaller runtime hook、Qt platform plugin、resources 與 multiprocessing freeze support。
- Packaged EXE 啟動全部 worker；child 不遞迴啟動 GUI。
- EXE close 後無殘留 MapleStar process 或 shared-memory segment。

## 效能驗收

硬性 gate 以相同開發電腦、相同 Windows 電源模式、相同 Python／release artifact 測量。Python 與 EXE 分開記錄，不能互相代替。

Benchmark harness 將 raw samples 輸出成帶環境 metadata 的 JSON。環境至少包含 commit、Python/EXE、CPU、logical cores、RAM、Windows build、DPI、電源模式、遊戲視窗尺寸、worker role PID/incarnation及warm/cold cache條件。

### GUI

- `first visible shell`：launcher entry開始，到Qt shell收到第一個exposed paint完成。Python至少七次fresh-process cold start，中位數 `<= 200 ms`。
- `main ready`：五頁widget與binding完成、GUI command可用、supervisor initial snapshot已套用、guardian與scheduler ready；可降級worker必須已ready或明確顯示degraded。Python至少七次，中位數 `<= 700 ms`。
- Packaged onedir EXE的兩個marker各自不得高於同機legacy EXE baseline的 `110%`；若legacy baseline低於Python絕對門檻，仍以Python門檻為下限，避免不合理地要求EXE快於source mode。每次不得timeout或crash。
- 預載後切頁與一般操作：至少 100 samples，p95 `<= 16 ms`，最大值 `<= 50 ms`。
- GUI main thread 不得執行單次超過 `16 ms` 且可移至 worker 的工作。

### Realtime

- Scheduler在建立due `InputCommand`時記錄logical deadline；guardian低階adapter回傳後記錄actual send timestamp。`deadline lateness = actual send - logical deadline`，包括scheduler到guardian的IPC成本。
- 混合負載固定為：100次交替切頁/設定編輯、HP/MP以production cadence capture、EXP Pixel OCR持續執行且每分鐘至少一次Paddle fallback、Telegram/media各每五秒一個事件、巡航與週期鍵使用synthetic target/input adapter。負載持續至少十分鐘，scheduler lateness p99 `<= 5 ms`。
- 過期週期事件不補發。
- `key_up` 與 `release_all` 零遺失。
- Action intent 從接收至低階輸入送出的延遲需保存 raw samples、median、p95、p99 與 maximum；第一批 baseline 後設定不寬於既有 production p99 的硬門檻。

### Runtime 與穩定性

- Cached HP／MP capture 與判讀不受 OCR 阻塞。
- 60分鐘soak沿用上述混合負載，另每十分鐘模擬一次GUI失焦/回焦、每十五分鐘切換一次功能設定generation、第三十分鐘延遲一次potion heartbeat但保持work progress。Harness每秒保存PID、incarnation、queue depth、heartbeat/progress age、held ownership與GUI event-loop stall。結果要求零watchdog誤重啟、零restart loop、零殘留按鍵。
- 正常 shutdown `<= 3 秒`，無殘留 child process。
- 記錄每個 process 的 peak working set、CPU time、queue depth 與 shared-memory 大小；第一批 baseline 後建立 regression gate。架構已明確接受較高 RAM，因此不以未量測的任意總記憶體上限阻擋設計。

### 筆電 smoke

筆電不使用硬性 latency 數字，但必須驗證：

- 全部頁面與設定可操作。
- 巡航與喝水同時執行時 GUI 不凍結。
- 不出現 heartbeat 誤判的「喝水 process 已重啟」。
- 失焦、停止與關閉後沒有殘留按鍵或 process。

## 文件、依賴與發行影響

- `requirements.txt` 與 release lock 加入經驗證的 PySide6 pin，移除 CustomTkinter。
- `build_release.bat` 與 release workflow 更新 Qt hooks、plugin、resources 及 worker spawn smoke。
- 更新 `docs/project-structure.md`、`docs/runtime-compatibility.md`、`docs/installation.md`、`docs/verification.md` 與 `docs/release.md`。
- 若 facade、啟動方式或 agent 執行邊界改變，更新 `AGENTS.md`。

## 完成條件

- PySide6 是唯一 GUI，repository 與 release artifact 不含 CustomTkinter runtime。
- GUI 關閉必定停止 backend、釋放按鍵並結束全部 worker。
- Input guardian role 是唯一 Windows input writer；任何時刻最多一個 guardian instance 存活。
- Potion、OCR、notification 與 GUI 負載不能阻塞 realtime scheduler。
- IPC backpressure、generation、deadline與health都有contract tests；若啟用shared memory，其lifecycle/cleanup也必須通過contract tests。
- 舊設定與 profiles 可自動遷移，失敗時不覆蓋原始資料。
- 全部既有功能在 Qt GUI 可操作，公開 facade 相容。
- Python 與 EXE 通過 correctness、效能、chaos、60 分鐘 soak 與 shutdown gate。
- 筆電 smoke 不再出現 potion watchdog 誤重啟、GUI freeze 或輸入殘留。
