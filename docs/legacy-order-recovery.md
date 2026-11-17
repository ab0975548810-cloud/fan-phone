# 舊單恢復：證據先行

2026-11-17 唯讀正式盤點：213 筆；版本表 0 筆。157 筆圖片來源被移除，2 筆沒有設計資料，另外 54 筆保留來源引用，其中 2 筆僅有 blob 暫存來源。可繼續蒐集證據者至多 52 筆，**實際通過完整恢復驗證為 0 筆**，不可把候選數量當成恢復成功數量。

6 筆保留 228 × 468 的矩形 clipPath；54 筆候選中 44 筆有歷史 print job。215 筆 jobs 涉及 200 個 order，保留 W/H/X/Y 等輸出參數，但沒有歷史刀模、畫布／模板契約。私有 storage 426 檔只有每單 print.png／preview.png；沒有原始來源與刀模封存。app_store 只有現行 shop_data／templates／assets 等，Git 中沒有 shop_data.json／templates.json 歷史可用。未下載客戶圖片，未執行正式訂單／版本寫入或回填。

公開素材 URL 是否存在不等於它是當時同一份素材；矩形 clipPath 也不是帶鏡頭孔的歷史刀模。成品 alpha 包含圖案透明度，不能逆推出原刀模。不得用目前設定冒充歷史設定。

52 筆中有 7 筆直接引用 case-assets 公開檔案，路徑均可在 storage.objects 找到；其餘網址／內嵌來源仍不能證明歷史定位。使用者已指定不另提供備份，因此本次以現有證據判定，沒有宣稱任何正式舊單已通過恢復。

## 驗證路徑

完整新版快照走原有路徑。舊單走 legacy_order_designs：只讀 owner 管理的 ORDER_DESIGN_HISTORY_DIR/<order_id>/manifest.json 與同層素材檔，沒有網路抓取舊 URL、沒有讀取現行 catalog 補歷史。

證據包需要可追溯 archiveReference／archivedAt、orderId、originalDesignHash、originalPrintHash、歷史 logicalCanvas／production／editorContext／fontHashes（模板另需歷史 templateBinding／editorState／layer_contract_version），以及 sourceMap 和 assets 的 SHA256 清單。來源應由受信任歷史備份抽取並人工審查，不能把現行設定填入後宣稱歷史版本。沒有公開上傳或跳過驗證 API；本次沒有建立正式證據包。

adapter 只補缺失 metadata，不替換原始 objects 的位置、尺寸或文字。全部素材需通過 SHA256／解碼；原生產圖須有 720 DPI 與正確像素尺寸；使用隔離 renderer 重建後逐 RGBA 像素一致才進入原編輯器。任一步失敗拒絕，通過後另存獨立 V1 歸檔，修改再保存 V2；訂單與原列印檔不更新。

## 無法恢復時

顯示缺來源、blob 失效、歷史證據缺失或重建不一致等原因。管理員可明確確認「建立獨立重製草稿」：保留原始 legacy JSON／檔案引用為 V1，使用**目前設定**建立空白 V2，畫面明示這是全新重製而非原圖層恢復。不讀取客人 IndexedDB、不產生新銷售訂單、不送印。既有 V2 不能被重新製作入口覆蓋。

無新 migration；依賴 #108 的版本表。部署需另行核准。若找不到可信歷史備份，本次不能使 213 筆舊訂單自動恢復；需要取得備份後逐筆執行驗證，仍不可批次回填正式 orders。

## 隔離驗收

`test_legacy_order_designs.py` 驗證缺來源／blob／未登入拒絕、歷史 SHA 與訂單識別、720 DPI 不一致拒絕，以及重製併發保護。Commerce 執行不需瀏覽器的案例；既有 browser CI 執行完整 renderer 案例。

`.github/tests/test_order_design_browser.py --legacy-only` 使用合成歷史證據，涵蓋 WebKit／Chromium、手機與桌面視窗、手機殼／鏡頭底膜各自有無多圖層模板：移動單張貼紙、V1 不變、V2 保存、換工作階段重開、預覽像素不變與 720 DPI。另實際操作拒絕頁面 → 明確確認空白重製 V2 → 編輯保存 V3 → 桌面重開；驗證訂單、財務與 fake vendor calls 未改變。這些合成證據只驗證程式，不計入正式恢復數量。

復原 gate 使用 Chromium 生產 renderer 逐 RGBA 像素一致，刻意不使用容差；舊引擎／字型差異可能造成安全拒絕。WebKit 前後預覽逐像素一致，跨 WebKit／生產 Chromium 的文字驗收比對位置、字級與換行；Chromium 預覽與生產圖另逐像素一致。來源容量、像素、輸出尺寸、worker 時間與併發均有限制。
