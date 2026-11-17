# 訂單設計修改 V1：第一階段

## 範圍與唯讀盤點

2026-11-17 以 Railway 部署 metadata、Supabase SQL aggregate 進行唯讀盤點；未下載客戶圖層或原始圖片、未修改正式資料。
當時正式 main 為 `07ce814e010ee8a547144f9c1894edcf9b192797`。

- 正式 orders 共 213 筆：2 筆無 design_json；0 筆具有 editable-text-v1 完整契約、logicalCanvas 或持久 production.maskPath；0 筆 multilayer-v1。
- 遞迴圖片節點 647 個，其中 412 個缺少 src、9 個內嵌圖片；未找到 orders/.../sources/... 持久來源。
- 因此當時 213 筆均未達到「安全完整恢復」條件。此判斷來自結構盤點，不代表已逐張解碼驗證；本版不嘗試用單張成品 PNG 偽造可編輯圖層。
- case-assets 是公開素材庫；case-private 是私有訂單儲存。新訂單原始素材及版本素材只放 case-private，不產生公開網址。

## 資料流

新加入購物車的設計由既有固定字型／多圖層序列化器保存完整 Fabric objects、來源 PNG、描邊前原始素材與效果參數、裁切、位置、縮放、旋轉、透明度、順序、使用者鎖定、模板權限、空照片框與導引。結帳繼續使用既有 session-bound source receipts、完整驗證與 atomic commerce commit；新增原始預覽遮罩、商品類型、列印定位及模板初始權限快照。素材進入 orders/{id}/sources，沒有暫存 TTL，清理 receipt 不會移除已成立訂單來源。

後台重新編輯先驗證管理員 session，再將訂單快照與來源複製到獨立、內容雜湊命名的 order-design/{id}/ 私有空間。初次開啟以 compare-and-swap 建立版本表 V1；不改 orders.design_json 或原有成品。後續開啟不再依賴商品、模板目前版本或客人 IndexedDB。資源透過管理員驗證代理，no-store，不能僅靠訂單編號讀取。

工作副本在原前台完整編輯器中操作，使用 8 小時有效、登入者／訂單／基準版本綁定的簽章 token。此模式關閉一般草稿、購物車讀寫及送單入口；不建立另一筆銷售訂單。按「儲存修改」才 append V2（之後 V3…）。保留每版時間、操作 session 識別、內容 hash；使用現有共用管理員登入時，記錄的是 session 識別，並非新增具名員工帳號系統。

版本使用 PostgreSQL transaction advisory lock + expected version CAS；相同工作副本／相同內容重試會回傳同一版本。不同內容或過期基準回傳 409，畫布保留。SQLite 測試實作使用 BEGIN IMMEDIATE。模板權限以已保存版本為準，包含 renderer 的 normalizedGeometry，不能由提交的旗標放寬。

V2 不產生或取代 Print Center 正式圖，不建立 print job、重送、銳印任務，也不變更付款、庫存或營收。既有 720 DPI 預覽僅供本階段編輯驗證；生產確認與版本切換留在第二階段。

## 相容性與失敗行為

- 新版完整快照：一般照片／貼紙／文字與多圖層模板，手機殼及鏡頭底膜可恢復。
- 尚未用新版重新保存的舊購物車／舊訂單：不自動升級。缺來源、完整畫布／私有刀模、商品定位、模板權限或固定字型 hash 時顯示明確原因並拒絕開啟。
- 原始素材遺失或解碼失敗：拒絕恢復，不用預覽 PNG 代替。來源服務故障：503 可重試，原訂單不變。
- 不支援的濾鏡／字元／來源尺寸由既有 renderer 契約拒絕；錯誤會保留客人的原草稿。
- 已保存的素材不做 TTL 清理。備份／保留政策應同時涵蓋 orders、order_design_versions 與 case-private；人工刪除儲存檔案仍會造成不可恢復。

## Migration 與部署風險

需新增 `supabase/migrations/20261117082423_order_design_revisions_v1.sql`。只建立 order_design_versions 與 append RPC，不更新既有業務資料；RLS 啟用，anon/authenticated 無權限，service_role 僅 SELECT/INSERT，無 UPDATE/DELETE。不得在未確認前於正式資料庫執行。

建議核准後先備份並套用此 migration，再部署程式。尚未 migration 時後台版本功能會安全回傳 503；新訂單的完整快照仍走原訂單儲存，不依賴版本表。回退程式可停用 UI，保留版本表／私有檔案，不要 drop 或清除資料。

主要成本是每筆訂單持久保存原始圖層與遮罩；70 MiB／64M 總來源像素限制沿用既有契約。完整快照增加上傳與 DB JSON 容量；同張素材按 hash 去重。字型升級必須維持既有 hash 或另做版本化字型保留，不可默默換字型。

## 驗收

- test_order_designs.py：私有素材授權、偽造 token、V1/V2 保留、跨登入恢復、工作副本 replay/CAS、來源清理、舊單拒絕、模板權限與並行修改、業務狀態不變。
- .github/tests/test_order_design_browser.py：WebKit/Chromium iPhone 尺寸，以正常購物車序列化建立隔離訂單；兩種商品 × 一般／模板，修改一張貼紙、其他圖層不變，V2 另存再以獨立桌面瀏覽器 context 恢復，描邊原始素材仍可編輯。比對原預覽與 V1 恢復、V2 前後 720 DPI 解碼像素完全相同；直接呼叫隔離伺服器重建器核對 720 DPI 與文字佈局，Chromium 前台／伺服器逐像素一致；fake vendor 呼叫為零。
- .github/tests/test_order_design_postgres.py：隔離 PostgreSQL RLS/權限、immutable V1、8 個並行保存只一筆成功、重試不重建版本。
- 原有 Smoke、Commerce、Print Center、PostgreSQL、storage compatibility、完整 WebKit/Chromium 套件仍為 PR gates。CI 狀態以 PR 最新 SHA 為準。

## 第二階段建議

另建設計版本確認與生產版本關聯：展示 V1/V2 預覽差異，伺服器重建並驗證 720 DPI 後由管理員明確確認；以版本 ID + artwork hash 連結獨立列印任務，沿用既有人工重送授權、去重與未知狀態保護。新增原因／成本／操作員審計，不建立第二筆銷售訂單或重新扣庫存。這些動作需另行開發與核准，不由本 PR 觸發。

## 修改檔案

| 範圍 | 檔案 |
| --- | --- |
| 後端快照、授權與版本 | order_designs.py、editable_stickers.py、app.py |
| 後台訂單按鈕與資源版本 | admin_perf_patch.py、static/admin-orders-v3.js |
| 編輯器完整保存、私有來源與工作副本 | index.html、static/editable-sticker-core-v1.js、static/design-source-upload-v1.js、static/front-order-design-v1.js |
| 後台編輯模式隔離 | static/index-base-20260913.html、static/front-design-draft-v1.js、static/front-design-cart.js、static/front-home-v1.js、static/front-multilayer-template-v1.js |
| 版本資料表與 RLS | supabase/migrations/20261117082423_order_design_revisions_v1.sql |
| 測試與既有 CI 入口 | test_order_designs.py、test_commerce.py、.github/tests/test_order_design_browser.py、.github/tests/test_order_design_postgres.py、.github/tests/test_ai_editor_webkit.py |
| 盤點與操作文件 | docs/order-design-revisions-v1.md |
