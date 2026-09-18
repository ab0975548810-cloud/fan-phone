# POS Phase 1 transaction and deployment notes

This extends PR #8's existing commerce model. Public catalog data stays in
`shop_data`; private SKUs, finance, receipts and the inventory ledger stay in
`app_store.commerce_data`. Orders continue to use the existing `orders` table.

## Transaction boundary

Every commerce mutation reads fresh database state and attempts a revision-based
commit. PostgreSQL `commerce_commit` locks the commerce row and commits the order
insert/status/deletion together with its finance snapshot, inventory balance,
ledger and idempotency receipt. A stale revision retries from fresh state; an
administrator saving an old screen receives HTTP 409 without saving anything.
No process lock or stale cache is used for commerce decisions.

`inventory_ledger` is an append-only array in the private commerce record. Entries
contain a unique transaction identity, SKU, signed quantity, resulting balance,
reason, order reference, UTC timestamp and source (`admin` or `checkout`). The
current shared-password admin has no individual employee identity. Creation,
void, restore and manual stock changes all record entries. Legacy balances are
the opening balance: migration does not invent historical transactions.

Orders record the original inventory quantity/reservation. Later changes to the
SKU tracking switch do not affect reversal. Unknown legacy finance remains
unknown; the prior PR's `stock_deducted` snapshot is used when present. Missing
historical SKUs block reversal instead of silently losing inventory.

Checkout requires a durable idempotency key. The browser saves it in the cart
before sending; retries and reloads keep it until confirmed success. The server
stores a request fingerprint and original success response. A key reused with
different content is rejected. Admin lifecycle requests also require a key and retain it while
their outcome is uncertain. Delayed retries cannot reverse a later operation.
Deleted orders retain their accounting and receipt, so replay cannot recreate
them. Deletion requires a prior void and performs best-effort image cleanup.

Images upload before the database transaction, under a unique attempt's order
ID. They are not deleted after an ambiguous database failure: a commit may have
succeeded even when its response was lost. This protects successful artwork but
can leave unreferenced uploads after failed attempts. A future retention job
must reconcile against committed order paths before removing these objects.
Database transactions cannot atomically include object-storage uploads.

Today's revenue/profit uses `Asia/Taipei` midnight through the next midnight.
Finance snapshots remain unchanged when current catalog costs/prices change.

## Before deploying after review

1. Back up `app_store`, `orders` and private storage. Confirm that production has
   `SUPABASE_URL`, a server-only service-role key and the private storage bucket.
2. Stop old application workers / pause checkout. Old versions write whole JSON
   documents without revision checks and must not run alongside the new writer.
3. Apply the checked-in `supabase/migrations/*_commerce_atomic_commit.sql` after
   the existing `supabase_setup.sql`. It is additive and uses SECURITY INVOKER;
   only `service_role` can execute it. Existing table RLS remains enabled.
4. Deploy all updated server and browser files together, then test a disposable
   SKU/order through create → void → restore and verify the ledger privately.
5. Resume checkout only after checking runtime configuration and storage paths.
   Missing RPC/database access causes an error, never fallback to local JSON.

No production migration or deployment is performed as part of this PR.
To roll back after new orders exist, pause writes first and restore a coordinated
backup or prepare a forward fix. Do not simply start the old unversioned writer.

## Local mode

SQLite (`COMMERCE_DB_PATH`, default `commerce.sqlite3`) commits orders and
commerce state together across processes. The first database initialization
imports existing local commerce/order JSON once; files are retained as backup.
It never silently switches from Supabase to SQLite on an error. Gunicorn sets
`BENFUWAN_PRODUCTION=1`; local commerce writes then require the explicit
`COMMERCE_DURABLE_LOCAL=1` acknowledgement of a persistent volume. This flag
does not provision or verify a durable disk. For multiple production hosts use
Supabase, not independent SQLite files. Local images still require durable disk.

## Verification and current limits

- `python smoke_test.py`: installed production middleware, catalog privacy,
  checkout, finance/stock lifecycle and workflow.
- `python test_commerce.py`: rollback fault injection, stale admin saves,
  idempotency, lost commit response, tracking switch, stock shortage, accounting
  retention, timezone boundary and two independent processes racing inventory.
- `python .github/tests/test_ai_editor_webkit.py`: editor/layout, AI mocked
  responses, admin lazy loading/POS and real checkout with lost response + reload.
- CI additionally runs the transaction suite on PostgreSQL 17 using the exact
  migration function under `service_role`, and checks RLS/function privileges.

The private JSON record serializes all commerce commits and grows with ledger
and receipts. This is a bounded Phase 1 architecture, not a high-volume ledger
schema. Monitor record size/latency and migrate to normalized tables before
volume grows substantially; do not prune idempotency receipts casually. Current
style price editing remains the existing separate catalog save. Its save and
private cost settings are not one combined administrative transaction; order
finance always snapshots the server-resolved price actually charged.

## POS Phase 2：資料模型與操作

沿用同一份 `app_store.commerce_data`、`orders`、`commerce_commit` 與庫存異動帳；
不新增第二套 POS 或庫存餘額。commerce schema version 升為 3。

- `skus[].target_stock`：非負整數或 null（尚未設定）；既有庫存、成本、警戒值保留。
- 系列沿用公開 catalog 的 style ID。售價沿用系列统一售價，成本逐 SKU 管理。
- 新訂單 finance 增加 `series_id` / `series_name` 成立時快照；既有快照不回填、不重算。
  舊快照缺系列名稱時使用原訂單保存的名稱；缺少者顯示舊系列 ID。
- 到貨以 `PURCHASE_RECEIVED +N` 寫入既有 inventory ledger，附 `receipt_id`、備註。
  原子提交最新餘額、異動與操作回條。重送使用相同 key，不重複入庫。
- `expenses` 以 ID 儲存日期、七種分類、金額、備註、版本與作廢狀態。
  `expense_ledger` 追加 before/after 紀錄；新增、修改、作廢與回條同一交易提交。
  編輯須比對版本，作廢不刪除原始紀錄。金額最多兩位小數。
- 補貨輸出為 `schema_version:1` 的 series groups / items 與純文字；可複製，
  未來 CSV／圖片可共用此結構，目前未實作檔案匯出。

### 店員介面與報表口徑

四個工作區：系列商品、補貨中心、營運報表、支出管理。型號／顏色以卡片呈現，
手機單欄，iPad／桌機多欄。庫存不在商品卡上直接編輯；到貨走到貨登記，
盤點校正另開視窗，差額仍寫 MANUAL_ADJUST 並檢查 revision。

缺貨＝0；低於警戒、剛好警戒、正常分別顯示。未追蹤另列，不自動建議入庫。
「需要補貨」包括缺貨／低於／剛好警戒；建議量為 max(0, 目標－庫存)，
未設定目標顯示未設定，不猜數量。商品設定變更須先儲存才能產生補貨清單。

所有日期使用 Asia/Taipei，週一至週日，月份／年度依曆法，自訂起訖日期皆包含。
訂單依成立日計入並排除目前作廢訂單；支出依登記日期計入並排除作廢支出。
這是店務營運統計，作廢舊訂單會更新該訂單成立期間的結果，未採用結帳封帳制度。

營業額、件數、訂單數、平均客單价使用訂單原始快照。成本、毛利使用原始成本快照；
舊單無快照時只使用該訂單原存售價，標示「成本未知」。只要區間／系列內有未知成本，
完整成本、毛利、毛利率、淨利回傳 null，保留已知成本小計與未知清單。
淨利＝營業額－商品成本－營運支出。支出不任意分攤系列，系列報表提供營業額／成本／毛利。
進貨款不得再次列營運支出而重複計算售出成本。報表金額以 Decimal 彙總再四捨五入到兩位。

瀏覽器將尚未確認的到貨／支出完整請求與 key 保存於 localStorage，跨同來源分頁、關頁與一般瀏覽器重啟保留。
Web Locks 保護多分頁的檢查／寫入／清除；未確認前不允許登記新操作。storage event 同步其他分頁提示。
只有成功或 API 明確的終止型 4xx 才清除，登入失效、限流、網路與伺服器錯誤仍保留原請求。
清除時比對原 key，避免較晚返回的舊請求刪掉下一筆。儲存不可用、資料損毀或不支援 Web Locks 時阻止新操作。
localStorage 不跨裝置／不同瀏覽器同步；使用者清除網站資料、私密瀏覽結束或瀏覽器清除資料仍可能遺失。
這些情境需先核對伺服器的入庫／支出紀錄再補登。此修正不改動資料庫 schema，無新增 migration。

### Phase 2 migration 與正式部署（待 review，未執行）

1. 備份現有 `app_store`、`orders` 與 storage；在 staging 以去識別資料驗證。
2. 安排維護時間，暫停下單／後台寫入，停止所有 Phase 1 workers。
3. 依序套用既有 migration，再套用
   `20260917163034_commerce_phase2_guard.sql`。保留 SECURITY INVOKER、service_role-only
   EXECUTE、既有 RLS；禁止舊 version 2 writer，防止覆蓋支出資料，支出帳只能追加。
   不新增 table、不改歷史金額、不推算歷史成本；v3 欄位在應用程式讀取時正規化，首次寫入持久化。
4. 部署本 PR 所有 server、JS、CSS，清除／更新資產快取；不可讓舊版 server 與新版混跑。
5. staging／部署後受控驗收：到貨 +N、重送、訂單作廢／恢復、支出修改／作廢、
   Taipei 日期區間、成本未知清單；確認所有交易成功、庫存與 ledger 相符，再恢復營業。
6. 回退需先停寫。不可直接回退到 Phase 1 writer；優先 forward fix，必要時協調完整資料備份回復。
   僅回退程式不會移除 SQL 的 v3 writer guard。

目前單一 JSON 文件會隨 ledger／支出回條增長；報表會讀取整份 finance，舊單查詢分頁。
需監控資料大小、鎖等待與查詢延遲。延續既有架構適用目前店務規模，尚未改為大量交易的分表帳本。
公開系列售價仍走原 catalog 儲存，不與私人成本設定綁成同一個後台交易；下單使用實際 server 售價快照。
沒有連接或修改正式資料庫，也未宣稱已驗證正式環境 RLS／部署設定。
