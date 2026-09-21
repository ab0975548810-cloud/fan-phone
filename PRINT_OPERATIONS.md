# Print Center operations

Print Phase 3.1 uses the A5 Desktop manual-confirmation workflow. Customer checkout never creates a vendor task, and the website never starts physical printing.

Active flow:

`準備任務 → 送到銳印（receiveTask）→ 等待銳印確認 → 店員在銳印人工確認 → callback 1 打印中 → callback 2 完成`

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

Existing model `print_w / print_h / print_x / print_y` values may appear as a suggestion only when all four are explicitly present on that model. Generic style fallback values such as `80 × 160` are never promoted to a production profile. The operator must calibrate the exact model + style and press **儲存列印參數** before the profile becomes usable.

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
2. Confirm the existing Print Phase 3.0 migration is present. Phase 3.1 adds no migration.
3. Verify RLS remains enabled and `anon` / `authenticated` have no privileges on all print tables; run Supabase security and performance advisors.
4. Deploy the application with `YUN_PRINT_ENABLED=false` and the HTTPS/token settings present. Confirm the reverse proxy redacts `/api/print/artwork/*`; the repository Gunicorn config already omits request paths.
5. Calibrate and explicitly save one production profile for the exact model + style. Do not accept a suggested value without physical measurement.
6. Give the printer callback URL to the vendor for backend binding, then verify both callback endpoints and one job-scoped artwork URL with a vendor-approved sandbox or supervised device.
7. Confirm angle, every model/style position, callback clock tolerance, `getAllTasks` retention, and printer status code `6`.
8. Enable `YUN_PRINT_ENABLED=true` only in a supervised test window. Prepare and send one approved task, then perform the physical confirmation in Ruiyin.

## Cancel and ambiguous operations

A `QUEUED` job shown as **等待銳印確認** may call `cancelTask`. Once callback status `1` moves a job to `PRINTING`, the website does not offer cancellation.

If `receiveTask` or `cancelTask` times out, returns a server error, or gives an ambiguous response, the job moves to `UNKNOWN`. Never retry the physical operation as a new attempt. Use **查核雲端** (`getAllTasks`) and inspect the raw status. Absence from the unprinted queue does not prove that a task was never created or that it completed.

Stale `SENDING` and `CANCELING` states remain reconcilable. Legacy `STARTING` rows may also be reconciled, but Phase 3.1 never creates a new `STARTING` operation.

`pushPrint`, website-triggered `startPrint`, maintenance controls, and vendor channel stock are intentionally absent from the A5 active flow. Vendor channel stock is not store SKU inventory.
