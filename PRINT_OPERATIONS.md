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

The checkout transaction stores `auto_print_v1: true`, the release-specific
`auto_print_handoff_v1` marker, and one `print_handoffs` outbox row in the same
database transaction as its order, finance snapshot, inventory mutation, and
idempotent response. A worker claims at most 20 due rows with a database lease,
validates the exact immutable receipt/response, runs the canonical prepare
preflight, and then drains the existing deterministic `auto-prepare-*` /
`auto-send-*` requests. A crash after order commit, storage or Supabase outage,
process restart, or competing worker therefore cannot lose the handoff or create
a second job/vendor request.

`YUN_PRINT_ENABLED=false` is a durable operational pause. New eligible orders
remain `PENDING` with `attempt_count=0`; workers do not claim, age out, or mark
them `REVIEW`. After a later process starts with complete vendor configuration,
the same outbox rows resume through normal claim/preflight exactly once.

The migration records a `release_cutoff`. Existing `auto_print_v1` receipts that
predate the release and have no job are written as `legacy-auto-print-v1 /
REVIEW`. Claim RPCs structurally exclude those rows. They appear only in the
read-only Print Center alert and are never auto-prepared or auto-sent merely
because code is deployed or a worker restarts. An operator must compare the
order, Ruiyin history and physical output before deciding any separate manual
recovery action.

The vendor call is outside the checkout response path. A disabled vendor,
missing profile, missing finance SKU, invalid artwork, storage failure, timeout,
or vendor rejection cannot roll back or fail the committed order. A definite
vendor rejection leaves the job `PREPARED` with its reason so an operator may use
the existing manual send action. A timeout, 5xx, malformed success, or unexpected
disconnect leaves the job `UNKNOWN`; reconcile it before any further send.

Durable preparation validates and hashes the production PNG in the worker. The
checkout response path only wakes the dispatcher and never contacts Ruiyin.
Transient recovery failures use bounded exponential backoff with deterministic
jitter; one bad row cannot stop the rest of a bounded cycle. After eight failed
claims the row becomes `FAILED` for manual review instead of looping forever.

The compatibility endpoint `/api/admin/print/start` always fails closed with `DESKTOP_MANUAL_CONFIRMATION`. The A5 flow does not call vendor `startPrint` or `pushPrint`.

### Historical missed-handoff review runbook

Rows labelled `legacy-auto-print-v1 / REVIEW` are evidence for an operator; they
are not a retry queue. For each alert, an authorised operator must first match
the customer order against Print Center history, Ruiyin's task history and any
physical output already produced. Record the observed task ID/status and the
physical check outside the automatic dispatcher. If any task or physical output
may exist, leave the row in review and use the existing reconcile/escalation
path; never create or send a replacement automatically. If all sources prove
that no task was accepted, obtain the store owner's explicit approval before a
separate audited manual recovery. This release intentionally provides no button
that turns a historical review row into `PENDING`, `PREPARED`, or a vendor call.

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

1. Keep `YUN_PRINT_ENABLED=false`, stop/hold checkout traffic and old application workers, then take and verify a restorable Supabase database snapshot. This pause prevents an old worker from committing an order between the migration cutoff and the new application release.
2. Confirm the existing Print migrations are present. Apply `20261019193000_print_handoff_outbox.sql`; never run it from an application boot hook.
3. Verify `print_handoff_control.release_cutoff`, `print_handoffs`, and both RPCs exist. Confirm RLS is enabled; `public`, `anon`, and `authenticated` have no table or function access; only `service_role` can select/write and execute. Run Supabase security/performance advisors.
4. Verify pre-cutoff marker/no-job candidates are `REVIEW` and that `claim_print_handoffs(20,60)` never returns them. Do not change those rows to `PENDING` during deployment.
5. Deploy the application with `YUN_PRINT_ENABLED=false`. Create one isolated post-cutoff order in a non-production environment and verify exactly one `PENDING` outbox row with zero attempts survives a worker restart and no job is created. Confirm no `receiveTask`, `startPrint`, or `pushPrint` call occurs while disabled. In the isolated environment only, enable the vendor fixture and verify that same row becomes one linked PREPARED job and is submitted at most once.
6. Resume checkout only after every worker runs the new release. Confirm the reverse proxy redacts `/api/print/artwork/*`; the repository Gunicorn config already omits request paths.
7. If rollback is required, disable the dispatcher/vendor first and roll the application back. Keep the new tables and RPCs in place so committed outbox evidence is not destroyed. Do not drop or rewrite handoff rows. Re-deploy the fixed release to resume; review any `PENDING/RETRY/CLAIMED` rows before re-enabling vendor handoff.
8. Calibrate one model in **品牌及型號**, then explicitly save it and verify every active SKU for that model shows the same read-only profile in Print Center. Do not accept guessed values without physical measurement.
9. Give the printer callback URL to the vendor for backend binding, then verify both callback endpoints and one job-scoped artwork URL with a vendor-approved sandbox or supervised device.
10. Confirm angle, every model/style position, callback clock tolerance, `getAllTasks` retention, and printer status code `6`.
11. Enable `YUN_PRINT_ENABLED=true` only in a supervised test window. Prepare and send one approved task, then perform the physical confirmation in Ruiyin.

## Cancel and ambiguous operations

A `QUEUED` job shown as **等待銳印確認** may call `cancelTask`. Once callback status `1` moves a job to `PRINTING`, the website does not offer cancellation.

If `receiveTask` or `cancelTask` times out, returns a server error, or gives an ambiguous response, the job moves to `UNKNOWN`. Never retry the physical operation as a new attempt. Use **查核雲端** (`getAllTasks`) and inspect the raw status. Absence from the unprinted queue does not prove that a task was never created or that it completed.

Stale `SENDING` and `CANCELING` states remain reconcilable. Legacy `STARTING` rows may also be reconciled, but Phase 3.1 never creates a new `STARTING` operation.

`pushPrint`, website-triggered `startPrint`, maintenance controls, and vendor channel stock are intentionally absent from the A5 active flow. Vendor channel stock is not store SKU inventory.

### 歷史 REVIEW 的後端封鎖

一般 prepare/retry/send/manual recovery 共用 DB-backed handoff guard：REVIEW 或 legacy-auto-print-v1 回 HANDOFF_REVIEW_REQUIRED。沒有提供解除或補送 API。資料庫查詢失敗亦不放行。
Dashboard 每筆訂單的 handoff 狀態採 exact/batched order lookup，不使用截斷告警判斷權限。告警每頁20筆、支援上一頁/下一頁，數字僅代表本頁。
#89 整合時，其 resend-check 也會經同一 guard，UI 人工確認不能取代歷史 REVIEW 的授權／稽核流程。
