# POS Phase 2

基於 main `9c7533ae2c76a1b83a1387c5ba538e26ea3620cc`，新 branch `backend-commerce-pos-v2-20260918`。
沿用現有 commerce／inventory ledger／Supabase，系列統一售價。

已完成系列商品卡、補貨狀態與建議清單、可重試到貨、台灣日期營運與系列報表、支出管理。
詳細資料模型、成本未知口徑、migration、部署與回退步驟見 `COMMERCE_OPERATIONS.md` 的 Phase 2 節。

驗證包含 Smoke、24 項交易測試（SQLite 其中 SQL guard 跳過；PostgreSQL 全數執行），
以及 WebKit 真實收貨回應遺失後重送、支出／報表／手機 iPad 桌機版面、原有前台與模板去背回歸。
最終結果以 PR 最新 commit CI 為準。正式 migration／部署／merge 均未執行。
