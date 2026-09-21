# 本福丸訂製 — Product & System Blueprint

這份文件描述「本福丸訂製」最終要做成什麼，不只是目前有哪些功能。

任何重大開發、重構、資料模型、POS、庫存、模板、高清出圖或打印整合，在動手前都應先讀本文件與 `AGENTS.md`。

---

## 1. 最終營運目標

最終希望把整個流程做成一套完整、低人工操作的訂製手機殼生產系統：

**客人掃 QR Code → 選手機型號/殼款/顏色 → 在前台完成設計 → 下單 → 後台產生可生產的高清打印檔 → 員工確認訂單與列印 → 系統送打印任務到銳印/雲打印 → A5 UV 打印機生產 → 訂單/庫存/營收/利潤同步更新。**

營運標準：

- 客人只需要負責選商品、設計與送出訂單。
- 員工主要負責看訂單、確認生產、送到銳印，並在銳印軟體人工確認打印。
- 尺寸、高清圖、檔案格式、訂單資料、成本、庫存、打印任務與狀態盡量由系統自動處理。
- 不要把前台、後台、POS、庫存、打印拆成彼此不相干的系統；它們應共用一致的商品、訂單與生產資料模型。

---

## 2. 系統總體架構

建議把系統視為下列幾個清楚邊界的模組：

1. **Customer Frontend / 設計前台**
2. **Product Catalog / 商品與規格**
3. **Order Center / 訂單中心**
4. **Commerce & POS / 售價、成本、毛利**
5. **Inventory / 庫存與異動**
6. **Asset Library / 素材庫**
7. **Template Library & Editor / 模板庫與後台模板編輯器**
8. **Print-ready Artwork Pipeline / 高清生產圖產生器**
9. **Print Center / 打印任務中心**
10. **Vendor Cloud Print Integration / 銳印雲打印 API**
11. **Reports / 營收、毛利、淨利與營運報表**

模組可以共享資料，但不要把所有狀態塞進同一個欄位或同一段前端 JS。

---

## 3. Customer Frontend / 設計前台

前台目前已接近成熟，未來以穩定、手機/iPad 操作、畫質與生產可靠度為優先，不做沒有必要的大改版。

### 必須保留

- 手機品牌/型號/材質/顏色選擇
- 商品售價顯示
- Fabric.js 設計器
- 圖片上傳、移動、縮放、旋轉
- 調整、翻轉、複製、往前、描邊、刪除
- 貼紙、素材、背景、文字
- undo / redo
- 圖層
- 模板套用
- AI 去背
- 生產用高清圖輸出
- 設計預覽圖
- 下單流程

### UX 原則

- 選到物件時，主工具列仍可直接操作。
- 上一步/下一步/圖層/模板與物件工具列都不得蓋住手機殼畫布。
- 特別保護 Safari / iPad 橫向使用情境。
- 正常客人照片不應因 Fabric JSON 重複嵌入 Base64 而導致下單失敗。

### 已放棄功能

`AI 大頭 / AI head cutout / MediaPipe guided cutout` 已經放棄並從 runtime 移除。除非未來明確重新提出需求，否則禁止重新啟用舊腳本。

---

## 4. Product Catalog / 商品、型號、材質與 SKU

商品資料是前台、POS、庫存、訂單與打印流程共同的基礎。

### 公開商品資料

可以讓客人端取得：

- 品牌
- 型號
- 手機殼材質/款式
- 顏色/variant
- 客人售價
- 商品/預覽圖片
- 是否上架

### 私人商務資料

只存在後台/伺服器：

- SKU
- 成本
- 目前庫存
- 低庫存警戒值
- 是否追蹤庫存
- 採購/補貨與庫存異動資料
- 毛利/報表資料

### SKU 原則

穩定 SKU 應能唯一代表實際可販售/可生產的規格，基礎概念為：

**model + material/style + color/variant**

未來若打印需要另外的機台 channel、治具或生產設定，可以做 SKU → production config mapping，不應直接破壞 SKU identity。

---

## 5. Order Center / 訂單中心

訂單是商務資料與生產資料的中心，但「訂單狀態」與「打印任務狀態」必須分開。

### 訂單流程概念

`待處理 → 製作中 → 待列印 → 列印中 → 已完成`

`作廢` 為獨立動作/狀態。

不要沒有實際需求就增加大量狀態。

### 每張訂單必須保存歷史快照

訂單成立後，必須保存當下實際使用的：

- SKU / 型號 / 材質 / 顏色
- 售價
- 成本
- 數量
- 單筆營收
- 成本總額
- 毛利
- 付款方式
- 客人/取件必要資料
- 預覽圖
- 生產高清圖或其 canonical source
- 設計結構必要資料

**未來商品調價或成本改變，不得改寫舊訂單的歷史毛利。**

---

## 6. Commerce / POS / 利潤

後台要像真正 POS/營運系統，而不是只有訂單列表。

### 核心管理能力

- 商品售價
- 商品成本
- 單件毛利 = 售價 - 成本
- 毛利率
- 庫存數量
- 低庫存警戒
- 是否追蹤庫存
- 今日/日期區間營收
- 今日/日期區間成本（COGS）
- 毛利
- 付款方式統計

### 未來報表

在核心資料穩定後再做：

- 日報
- 月報
- 商品/型號/材質銷售排行
- 毛利分析
- 支出/租金等營運費用
- 淨利 = 營收 - 銷貨成本 - 營運費用
- 可下載/分享的報表圖或檔案

不要在成本資料還不可靠時先做漂亮圖表。

---

## 7. Inventory / 庫存

庫存不能只是一個可以任意覆寫的 `stock_qty`；長期要能追溯為什麼增加或減少。

### 基本規則

- 追蹤庫存 SKU：訂單成功成立/保留時扣庫存一次。
- 作廢訂單：回補一次。
- 恢復訂單：重新扣一次。
- retry / refresh / 重複點擊不能造成重複扣除或回補。
- 庫存不足要阻止不合理的扣庫存結果。
- 低庫存要有警示。

### 長期建議

維護 inventory transaction / ledger，例如：

- sale reservation
- void restore
- restore deduction
- manual adjustment
- restock/purchase
- correction

每筆異動至少保留 SKU、數量變化、原因、order reference、時間、操作者/來源與 idempotency identity。

---

## 8. Asset Library / 素材庫

素材庫服務前台與模板編輯器。

應支援：

- 類別
- 上架/下架
- 排序
- 圖片資產
- 前台可用性
- 後台管理

資產 URL/存儲必須適合 production，不應依賴可能因部署而消失的暫存檔。

---

## 9. Template Library & Editor / 模板庫

目標是讓後台模板編輯器最後跟前台設計器一樣穩定、完整、順手。

### 長期方向

前台與後台模板編輯器應逐步共享共同的 Editor Core，而不是兩套功能一直各自修 bug。

可以共享：

- 圖片物件行為
- 文字
- 素材
- 圖層
- move/scale/rotate
- outline
- AI 去背
- undo/redo
- 座標/序列化規則

不要為了「程式漂亮」提前做大重構；等功能/生產風險穩定後再逐步抽共用核心。

---

## 10. Print-ready Artwork Pipeline / 高清生產圖

這是「畫面看起來漂亮」與「真的能 UV 打印」之間的關鍵層。

### 原則

- 不可以只把手機畫面 screenshot 放大當生產檔。
- 使用穩定 canonical coordinate system 保存設計。
- 根據實際手機殼打印區域、mask/cutout 與實體尺寸產生 print-ready artwork。
- 預覽圖與生產圖是不同用途。

### A5 Desktop 已確認規格

- Vendor 支援 PNG / JPG / TIF；本站 canonical production artwork 維持 PNG。
- 支援透明 PNG，使用 RGB，不指定 ICC。
- 建議檔案小於 20 MB、像素尺寸不超過 8000 × 8000、300–900 DPI；這些是品質建議，不是網站 hard limit。
- A5 有效打印範圍為 200 × 230 mm。
- `width / height / left / top` 依治具坐標，原點在治具右下角。
- A5 Desktop 的 channel 固定為 `1`。
- 網站不指定 spot color；白彩與光油由店員在銳印實際打印時選擇。
- 每個手機型號與殼款仍需以真機校正實際尺寸與定位，angle 也尚未獲得正式確認。

不要把 DPI 建議或既有通用 `80 × 160` fallback 當成已完成的真機校正。

---

## 11. Print Center / 打印中心

不要把「打印」做成訂單卡片上一個沒有狀態管理的按鈕。

建立獨立的 `print_jobs` / print task domain。

### Print Job 建議保存

- internal print job id
- order id
- vendor taskid
- artwork URL
- artwork hash/version
- width / height
- left / top
- copies
- spot_color
- channel
- angle
- printer/device config snapshot
- internal state
- vendor raw status
- vendor raw message
- sent/start/completed timestamps
- retry/error info

### 重要原則

- Order lifecycle 與 Print Job lifecycle 分離。
- 一張訂單未來可以安全地處理失敗、重印等情況，而不破壞訂單商務資料。
- 準備任務與真正開始實體打印分開。
- A5 Desktop 在網站送出 `receiveTask` 後，由店員到銳印軟體人工確認；網站不呼叫 `startPrint` 或 `pushPrint`。
- 一旦已開始物理打印，不應假設取消一定有效。
- 必須有 idempotency / duplicate-print protection；重試 API 不能變成印兩次。

---

## 12. 銳印 / 云打印開放平台 API

目前已確認文件描述的是 cloud HTTPS API，目標連線應為：

**fanphone Zeabur backend → `open.yunweiyin.com` → vendor cloud / 已綁定設備 → A5 UV / 銳印**

若廠商確認現有機台/銳印已綁定雲平台，就不需要另外做 Windows localhost Print Agent。

### 認證

每台設備有：

- `device_id`
- device `key`

簽名流程使用：

- device_id
- key
- random once
- Unix time
- vendor-required MD5 sign

即使 MD5 本身不是現代安全雜湊，仍需按照廠商協議實作；設備 key 僅能放 server-side environment variable，不得進前端 JS / Git。

建議 Zeabur secrets：

- `YUN_PRINT_DEVICE_ID`
- `YUN_PRINT_DEVICE_KEY`
- `YUN_PRINT_BASE_URL`

### 已知主要 API

- `POST /api/Device/receiveTask`：建立/推送打印任務
- `POST /api/Device/startPrint`：其他機型可能使用；A5 Desktop active workflow 禁止呼叫
- `POST /api/Device/cancelTask`：取消尚未打印任務
- `POST /api/Device/cancelAllTask`
- `POST /api/Device/getAllTasks`：取得未打印任務，適合 reconciliation
- `POST /api/Device/getStocks`：設備/channel stock；不要直接等同店內 SKU 庫存
- `POST /api/Device/pushPrint`：偏自助機流程；A5 Desktop 不使用
- 清噴頭 / restart / shutdown / maintenance mode 等設備控制 API，非第一階段必要功能

### receiveTask 重要資料

包含：

- order_id
- task name
- file URL
- copies
- width / height (mm)
- left / top (mm)
- channel（A5 Desktop 固定為 `1`）
- angle
- callback URL

`file` 是 URL，不是直接上傳 binary。因此最終高清檔必須能被 vendor server 存取，需確認 public URL 或 signed URL 的可用方式與有效時間。

### Task callback

系統需要類似：

`/api/print/callback`

接收 taskid 與打印狀態。A5 Desktop 店員在銳印確認後會先回傳 `1=打印中`，完成後回傳 `2=打印完成`；其他失敗狀態繼續保存 raw status/msg。

Callback 必須：

- 驗證 vendor signature
- idempotent
- 保存 raw status/msg
- 不盲目信任 callback payload
- 可重複收到同一 callback 而不造成副作用

### Printer status callback

也要提供 printer callback URL 給廠商綁定，用於設備：

- offline
- idle
- printing
- fault
- maintenance
- cleaning 等狀態

目前廠商文件對 printer status code `6` 的表格與文字說明有矛盾，實作前必須向廠商確認；在確認前保存 raw code + raw msg，不要硬轉成錯誤語意。

### 仍需真機確認

1. 各 model + style 的 `width / height / left / top` 實際校正值。
2. angle 的實際值；確認前保留店員明確設定或預設 `0`。
3. 是否有不會出墨的 sandbox / test device。
4. `getAllTasks` 的任務保留範圍與已打印任務行為。
5. printer status code `6` 的正式語意。

---

## 13. 建議完整生產流程

最終流程應接近：

1. 客人在前台完成設計。
2. 系統建立訂單並鎖定 SKU / 售價 / 成本 / 數量快照。
3. 庫存透過 idempotent inventory transaction 扣除。
4. 系統根據 canonical design 產生真正的 print-ready 高清檔。
5. 後台顯示「可生產/缺資料/生產檔錯誤」等準備狀態。
6. 員工按「準備打印」。
7. Backend 呼叫 `receiveTask`，保存 vendor `taskid`。
8. 打印中心顯示「等待銳印確認」與設備狀態。
9. 店員在銳印軟體人工確認後，A5 Desktop 才開始實體打印。
10. Vendor callback `1` 將 Print Job 與訂單同步為打印中，callback `2` 同步為完成。
11. callback 遺失或服務重啟時，可用 `getAllTasks` 等 API 做 reconciliation；不得盲目重送。

---

## 14. Data / Persistence 原則

這套系統會管理真實訂單、成本、庫存與打印，因此正式資料不可依賴 ephemeral Zeabur filesystem。

長期資料應存 durable database/storage，例如 Supabase/Postgres + 適合的 object storage。

至少應穩定保存：

- products / models / styles / variants
- SKUs
- pricing/current cost
- orders + immutable snapshots
- inventory balances + transactions
- assets
- templates
- print-ready artwork references
- print_jobs
- printer status/events
- reporting/accounting events

圖片/高清生產檔應使用 durable object storage，資料庫保存 reference/metadata，不要把巨大圖片 Base64 長期塞進一般資料欄位。

---

## 15. 開發優先順序

目前整體方向：

### 已完成/接近完成

- 前台設計器主要功能
- AI 去背
- 前台 toolbar/layout 關鍵 UX 修正
- 下單 payload 過大修正
- 訂單中心基礎流程

### 現在

**POS Phase 1 / PR #8**

先把：

- 售價
- 成本
- 毛利/毛利率
- SKU
- 庫存
- 低庫存
- 訂單價格/成本/毛利快照
- 訂單扣庫存/作廢回補/恢復再扣
- durable persistence
- idempotency

做穩。

### 接著

1. 商品/型號/材質/顏色管理整理成穩定 product/SKU model
2. 庫存異動 ledger、補貨/盤點
3. 素材庫整理
4. 模板庫/模板編輯器穩定化與逐步共享 Editor Core
5. print-ready artwork spec 與產生 pipeline
6. Print Center / print_jobs
7. 銳印 cloud API safe scaffold
8. 真機 sandbox/test 驗證
9. 人工確認後的一鍵打印流程
10. 日/月營收、毛利、費用、淨利與報表

不要因為打印 API 很吸引人就跳過 durable data、print-ready spec、idempotency 與真機測試。

---

## 16. 三方合作方式：Owner + ChatGPT + Codex

- **Owner**：決定店內真正想要的操作方式與商業需求。
- **ChatGPT**：整理產品需求、架構、驗收條件、風險與 review。
- **Codex**：主力 repo 實作、測試、修正、PR。
- **GitHub main / PR / CI / 本文件**：唯一可查證的工程事實來源。

不要靠人肉在不同 AI 之間轉述細節。

Codex 每次開始重大工作時應：

1. 讀最新 `AGENTS.md`。
2. 讀最新 `PROJECT_BLUEPRINT.md`。
3. 拉最新 `main`。
4. 查看正在處理的 PR/branch 與周邊程式碼。
5. 只做當次明確 scope。
6. 跑測試。
7. 停在 PR 等 review，不自行把重大功能直接合進 main。

如果目前程式實作與 Blueprint 衝突，不要靜默選一邊；先指出差異與風險，再提出 migration/修正方案。
