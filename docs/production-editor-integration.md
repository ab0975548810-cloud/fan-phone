# 自動交接、重新編輯與修改版重印整合驗收

## 範圍與正式站唯讀證據（2026-11-17）

基底 main `faec9cdd87128f7915cef40f9084ed2130496b01`；完整包含 Draft #109 `5efca27905cd6c5002649c42f80a89e09b7cc065`，未改其分支。正式 Railway 部署 `e2c01a7b-55b6-449c-ab0d-74a696bdb6d0` 為 SUCCESS，來源仍為上述 main。Supabase 健康，沒有執行正式資料回填、DDL、訂單更新或 vendor 測試。

訂單 `20261117121311-322234` 的查核結果：

- 自動交接 REVIEW／PRODUCTION_REBUILD_FAILED／4 次；原普通任務 PREPARED。
- 獨立人工任務 Task ID `20282064` 已經 COMPLETED（較問題回報時的 QUEUED 更新）；不得再自動補送。
- 10 個影像物件引用 3 張持久原圖，約 4.07M 像素，沒有文字物件；11 個固定字型雜湊全部與 main 相同。
- 來源、列印 mask、原 print／preview、後來成功的 rendered PNG 都存在，建立時間與最後修改時間一致。列印快照 W=61、H=37、X=71、Y=30、angle=0；本修復沒有改動它們。
- UTC 12:13:35–12:20:35 的來源存取有成功 200 紀錄；UTC 12:13:39 同時出現暫存清理 `Server disconnected`。清理只針對 design-temp，不能據此宣稱原圖被刪。
- UTC 12:21:14 已成功產生 SHA-256 `550e74ff1bb0e12c139fb16555d87a37bb60f15fd9b27999c873877715070903` 的生產圖，人工任務沿用此圖。UTC 12:22:10 自動交接停在 REVIEW。
- 所查 Railway 資源區間記憶體最高約 0.476 GB／8 GB，未見 OOM 證據。資源快照與缺少的 renderer trace 不能排除單次瞬間故障。

**事件限制：舊版將 worker timeout／crash／部分讀取錯誤壓成同一個錯誤，且取得的正式紀錄沒有內層例外。因此不能證明該筆第一次故障究竟是網路中斷或 renderer 逾時，也不能宣稱已在隔離環境重現那筆私有圖片的同一故障。** 已重現並修正下列程式缺陷；保留首次故障觸發原因未能追溯的驗收限制。

## 已確認的程式原因與修復

1. **重建與交接**：Storage SDK 單次 GET 的 transport error 沒有重試；renderer 原先抹除錯誤階段，交接將重建錯誤一律 REVIEW，暫時故障無法恢復。現在只對 immutable GET 的 transport error 有限重試，錯誤保留安全代碼／階段／耗時；可重試重建最多 8 次，有退避；權限、遺失、字型、幾何與不合法圖仍拒絕。任何失敗都不交給 vendor。
2. **租約與防重送**：原先一次 claim 20 筆、90 秒租約，再依序處理，來源讀取及 90 秒 renderer 上限可能超過租約，後段工作甚至尚未開始。現在開始前才逐筆 claim 600 秒；若期間有新 checkout，重新讀取其原子收據。任務建立／send 仍受冪等鍵與資料庫鎖保護。跨租約競爭、人工 QUEUED／UNKNOWN／COMPLETED 都有回歸。
3. **後台導覽**：真實 WebKit 點擊 `_blank` 會產生新頁面，原頁停在後台。改 `_self`，更新靜態快取版本；實測登入、完整圖層恢復、V2 保存與重載、舊訂單拒絕及匿名素材存取拒絕。
4. **修改版整合**：#109 的原圖像素修補保留；新增完整圖層 V2 的相同比較／確認／獨立送印流程。完整圖層路徑先驗證私有素材與模板權限，以封存資料重建 V1，必須與歷史任務 PNG 雜湊完全相符才取得歷史定位。禁止使用現在的 catalog 冒充原定位。
5. **確認後競爭**：送出時再次鎖定檢查最新版本／hash 與其他 active／UNKNOWN 任務。一般人工重送不能複製修改版任務而遺失版本授權。旗標關閉時修改版不能送印；失敗重播不會以新操作鍵偷送。

## 驗收入口

- `test_print_center.py`：普通任務、重試、UNKNOWN、回報競爭、人工任務、交接恢復與發送冪等；串接 Storage、renderer、send guards。
- `test_renderer_recovery.py`：字型／幾何／素材／worker 故障分類；實際背景與同步 720 DPI PNG 一致；實際背景 outbox → renderer → 假 receiveTask，一次送出、帳務不變。實際 Chromium 案例由 `RUN_REAL_RENDERER_TEST=1` 啟用，已接既有兩引擎 CI。
- `test_production_storage.py`：真實 SDK 搭配 MockTransport，有限網路重試、預算、權限／404／非 PNG 拒絕。
- `test_order_designs.py`、`test_pixel_orders.py`、`test_revision_reprints.py`：私有封存、V1 不可變、V2 CAS、原像素與 alpha、歷史定位證據、旗標、原因／成本、草稿與帳務保護。
- `.github/tests/test_admin_order_edit_navigation.py`、`test_pixel_order_browser.py`、`test_revision_reprint_browser.py`：WebKit／Chromium 真實完整編輯器，手機殼／鏡頭底膜，保存／重載／比較／假送印。
- `.github/tests/setup_commerce_postgres.py` 與原 Commerce PostgreSQL 入口：在一次性 PostgreSQL 17 套用全部 migrations，驗證權限、鎖、併發及版本送出。
- 既有 Smoke、Commerce、Print Center、checkout safety、WebKit、Chromium 全套保留。CI 結果以 PR 最終 HEAD checks 為準。

## Migration、部署風險與建議順序

仍保持 Draft，不能把本文件視為部署授權。`ORDER_PIXEL_REPRINT_ENABLED` 正式環境目前未設定，預設關閉；部署後也必須維持未設定或 `false`，直到店主正式核准。

需要兩份尚未部署的 migration，僅建立／替換函式、權限及不可變保護，不回填正式訂單：

1. #109 的 `20261117111435_pixel_order_reprint.sql`（整合版同時支援完整圖層修改稿）。
2. `20261117142936_production_handoff_send_safety.sql`（普通任務與修改版送出鎖、版本檢查及人工複製防繞路）。

建議只驗收並合併此整合 PR；它包含 #109 的全部提交，再將 #109 標記為已整合，避免各自以不同實作重複合併。若先合 #109，必須保留相同 ancestry 並重新跑整合 PR CI。不得在未核准下執行其中任何步驟。

主要風險：完整圖層 V2 保存需額外兩次 renderer（V1 證明與 V2），耗時及資源比單純 JSON 保存大；驗證不可用時仍保存草稿但禁止送印。租約不代表無限 Storage 串流的硬截止；超長工作仍由持久冪等與 send 鎖阻止重複交接。不同 renderer／字型／PNG 編碼版本造成的歷史 SHA 不符會安全拒絕，不能宣稱所有舊訂單都可送印。缺少歷史定位者可以像素修補／保存／比較，仍不能送印。

合併後 main 會觸發 Railway，因此 migration 與程式發布必須由核准的維護時段協調：先保持修改版旗標關閉；套用並驗證安全函式後才發布相應程式。先在隔離環境使用假 vendor 完整驗收，正式環境不得用這筆已有人工任務的訂單試送。

## 正式回退方案（僅方案，尚未執行）

發生異常時先經授權關閉自動交接 `YUN_AUTO_PRINT_ENABLED`，修改版旗標保持關閉；回退 Railway 至部署 `e2c01a7b-55b6-449c-ab0d-74a696bdb6d0`／main `faec9cdd…`。**保留新增資料與安全鎖函式，不逆向刪除 V1／V2、任務或稽核資料。** 新函式對原普通人工流程相容，保留它們才能防止舊程式複製 V2 繞過授權。核對 UNKNOWN、SENDING 與 vendor 已受理任務，禁止用重送來驗證回退。任何恢復自動交接與修改版送印都需再次核准。
