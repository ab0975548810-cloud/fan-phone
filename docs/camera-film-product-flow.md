# 鏡頭底膜商品分流

## 契約

沿用 `shop_data` JSON、model × style profiles、既有 Commerce SKU 與 Print Center。
不新增資料表或 migration，不改原始 PNG、720 DPI、校準值或送印 API。

- `model.product_type`: `phone_case`（舊資料預設）或 `camera_film`。
- `model.direct_style_id`: 底膜唯一綁定的獨立商品 ID。
- 對應 `style.product_type = camera_film`；有自己的售價，`colors=[]`、`model_colors={}`。
- `model.case_profiles[direct_style_id]`: 底膜自己的完整預覽、刀模及 W/H/X/Y/angle。
- SKU 仍是 model + style + color；底膜固定空 color。只補缺少 SKU，不重寫舊庫存或成本。
- 未來底膜模板可使用同一商品類型及 model/style 契約；本版不開放模板入口。

識別不看型號名稱或品牌文字。既有兩個底膜 model ID
`m_1792558304007`、`m_1792566644739` 僅作單向舊資料辨識，沒有獨立設定前禁止下單。
任意新型號必須由後台明確選擇商品類型。

## 經批准上線後的設定步驟（本 PR 不執行正式寫入）

1. 編輯每款底膜型號，選「鏡頭底膜（直接設計）」。
2. 底膜商品名稱可調整；獨立售價預設 **490 元**（店主確認）。
3. 舊資料的刀模目前位於該型號的晶彩 profile。核對它確實是這款底膜的刀模，
   再按「確認帶入本型號的…刀模」並確認。只帶入該型號已存的數值，不重新校準。
   不會自動使用晶彩 root、其他型號或其他商品的 profile。
4. 儲存沿用 catalog CAS → 補 SKU → 同步該型號／獨立商品 production profile。
   `PROFILE_SYNC_FAILED` 表示部分成功，應留在視窗重試，不能視為已可營業。
5. 從伺服器重新讀取成功後，驗證前台底膜直接進入空白編輯器、售價 490。

原有手機殼 style、歷史 SKU、成本、庫存、訂單與舊 profile 均保留，不自動重新綁單。
舊底膜草稿仍引用晶彩 style，會安全拒絕恢復，不能冒用新底膜 SKU。
歷史底膜訂單如果仍引用晶彩 style，不會自動改列印參數；需由店主個別查核。
正式合併／部署／上述商品設定仍需店主批准。

## 隔離驗證

- `test_print_center.py`: 真實本機建單、SKU 隔離、490 元售價、profile 數值、同 key 重送、錯誤商品配對拒絕。
- `.github/tests/test_film_viewport.py`: 後台明確帶入／儲存、前台真實下一步點擊、無款式／顏色／模板、照片拖曳及縮放、草稿恢復。
- 保留 DPR 1/2/3、390/768/1180 viewport、720 DPI 實際 PNG 與預覽像素／鏡頭孔透明比對。
- 既有完整手機殼、checkout、模板、Commerce、Print Center、Smoke 回歸照常執行。

測試不寫正式資料、不呼叫真實銳印。瀏覽器自動化不等同實體 iPhone 或印刷尺寸量測。
