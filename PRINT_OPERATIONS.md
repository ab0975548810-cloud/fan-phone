# Print Center operations

Print Phase 3.3 uses the A5 Desktop manual-confirmation workflow. After a new
order and its commerce transaction are committed, an eligible order is prepared
durably and a background dispatcher calls `receiveTask`. The website never calls
`startPrint` or `pushPrint`; physical printing still starts only after an operator
confirms the task inside Ruiyin.

Active flow:

`準備任務 → 送到銳印（receiveTask）→ 等待銳印確認 → 店員在銳印人工確認 → callback 1 打印中 → callback 2 完成`

## New-order automatic handoff

Automatic handoff applies only to a newly committed, non-void order that has a
production PNG, an immutable finance SKU, an active formal production profile,
complete vendor/public artwork configuration, and no active or successful print
attempt. Legacy bindings are never inferred or promoted by this flow.

The checkout transaction stores `auto_print_v1: true` in the same commerce
request record as its finance snapshot, inventory mutation, and idempotent
response. Only that durable marker makes a replay eligible: historical checkout
records without it can never trigger automatic handoff. After commit, checkout
persists a deterministic `prepare` request in the existing `print_requests`
table. If the process stops between commit and prepare, replaying the same
checkout key sees the marker and safely finishes preparation. The Gunicorn worker
then drains only request keys with the Phase 3.3 `auto-prepare-` marker and sends
their `PREPARED` jobs with a second
deterministic `send` request. This provides recovery after a process restart and
prevents checkout replay, worker retry, or redeploy from creating another active
job or calling `receiveTask` twice. It does not scan historical orders and needs
no schema migration.

The vendor call is outside the checkout response path. A disabled vendor,
missing profile, missing finance SKU, invalid artwork, storage failure, timeout,
or vendor rejection cannot roll back or fail the committed order. A definite
vendor rejection leaves the job `PREPARED` with its reason so an operator may use
the existing manual send action. A timeout, 5xx, malformed success, or unexpected
disconnect leaves the job `UNKNOWN`; reconcile it before any further send.

Durable preparation still validates and hashes the production PNG immediately
after the commerce commit, so checkout may include private-storage read latency.
It never includes the vendor's receive timeout. Moving artwork validation fully
off-request would require another durable queue record or schema change and is
outside this no-migration phase.

The compatibility endpoint `/api/admin/print/start` always fails closed with `DESKTOP_MANUAL_CONFIRMATION`. The A5 flow does not call vendor `startPrint` or `pushPrint`.

## A5 Desktop production rules

- Effective print area: **200 × 230 mm**.
- `width / height / left / top` use the jig coordinate system; origin is at the **bottom-right of the jig**.
- Channel is fixed at `1`.
- The website does not send `spot_color`; the operator chooses white/colour/varnish in Ruiyin.
- Copies default to `1`.
- Angle remains an explicit profile value and defaults to `0`; the vendor has not confirmed a universal angle.
- Vendor supports PNG / JPG / TIF. This system serves canonical production artwork as transparent PNG in RGB without an ICC profile.
- Vendor recommendations are under 20 MB, at most 8000 × 8000 pixels, and 300–900 DPI. Treat these as quality guidance, not hard upload limits.

The only editable production-profile entry is **手機品牌及型號 → 型號設定**. `print_x / print_y` are jig positions with the origin at the bottom-right; `print_w / print_h` are the physical print size, and `print_angle` defaults to `0`. Saving a model explicitly batch-upserts the same geometry to every active commerce SKU for that model. Channel is fixed at `1`, spot colour is empty, and an existing copies value is preserved (otherwise it defaults to `1`).

Print Center is read-only for production profiles. It shows the saved `W × H / X / Y` values or directs the operator back to **品牌及型號**. It cannot create or edit a profile. A missing formal profile blocks **準備任務**; model suggestions and legacy style `print_*` values are never promoted automatically. Existing style geometry remains stored for storefront compatibility, but the style editor no longer exposes those fields.

There is no deploy-time backfill. Existing profiles remain unchanged until the owner explicitly saves that model. A model save writes `shop_data` first and then performs an idempotent batch upsert of profiles. If profile synchronization fails, the API returns `PROFILE_SYNC_FAILED` and the model dialog remains available for the operator to retry; it must never report success. This operation does not write order finance, revenue, cost, stock, or inventory ledger data.

Per-style or per-colour geometry overrides and a model × style calibration matrix are deferred until real-device evidence requires them.

Legacy orders without `commerce_data.order_finance` must use **補綁列印 SKU** before they can enter this flow. The selection is stored only in `print_order_bindings`; it never creates or edits finance snapshots, revenue, cost, stock, or inventory ledger entries. Model/style matches and an old `style_name` colour suffix may preselect a candidate, but an operator must explicitly confirm it. A valid production profile must then be saved before a legacy order can be prepared.

## Required production configuration

Set these only in the server secret manager:

- `YUN_PRINT_DEVICE_ID`
- `YUN_PRINT_DEVICE_KEY`
- `YUN_PRINT_BASE_URL` (defaults to `https://open.yunweiyin.com`)
- `PRINT_ARTWORK_TOKEN_SECRET` (a long random, stable secret)
- `PRINT_PUBLIC_BASE_URL` (the public HTTPS origin used by vendor artwork and callbacks)

Keep `YUN_PRINT_ENABLED` unset or false until callback reachability, artwork fetching, profile calibration, and a supervised vendor test are complete. The device key must never appear in the database, browser, logs, fixtures, or Git history.

Provide this printer-status callback URL to the vendor for backend binding:

`https://fanphone.zeabur.app/api/print/printer-callback`

Task callbacks continue to use:

`https://fanphone.zeabur.app/api/print/callback`

Printer status code `6` remains raw-only until the vendor gives one consistent definition.

## Deployment order

1. Keep `YUN_PRINT_ENABLED=false` and take a restorable Supabase database snapshot.
2. Confirm the existing Print Phase 3.0 migration is present, then apply `20260921184801_print_order_bindings.sql`. Do not backfill bindings automatically.
3. Verify RLS remains enabled and `anon` / `authenticated` have no privileges on all print tables; run Supabase security and performance advisors.
4. Deploy the application with `YUN_PRINT_ENABLED=false` and the HTTPS/token settings present. Confirm the reverse proxy redacts `/api/print/artwork/*`; the repository Gunicorn config already omits request paths.
5. Calibrate one model in **品牌及型號**, then explicitly save it and verify every active SKU for that model shows the same read-only profile in Print Center. Do not accept guessed values without physical measurement.
6. Give the printer callback URL to the vendor for backend binding, then verify both callback endpoints and one job-scoped artwork URL with a vendor-approved sandbox or supervised device.
7. Confirm angle, every model/style position, callback clock tolerance, `getAllTasks` retention, and printer status code `6`.
8. Enable `YUN_PRINT_ENABLED=true` only in a supervised test window. Prepare and send one approved task, then perform the physical confirmation in Ruiyin.

## Cancel and ambiguous operations

A `QUEUED` job shown as **等待銳印確認** may call `cancelTask`. Once callback status `1` moves a job to `PRINTING`, the website does not offer cancellation.

If `receiveTask` or `cancelTask` times out, returns a server error, or gives an ambiguous response, the job moves to `UNKNOWN`. Never retry the physical operation as a new attempt. Use **查核雲端** (`getAllTasks`) and inspect the raw status. Absence from the unprinted queue does not prove that a task was never created or that it completed.

Stale `SENDING` and `CANCELING` states remain reconcilable. Legacy `STARTING` rows may also be reconciled, but Phase 3.1 never creates a new `STARTING` operation.

`pushPrint`, website-triggered `startPrint`, maintenance controls, and vendor channel stock are intentionally absent from the A5 active flow. Vendor channel stock is not store SKU inventory.
