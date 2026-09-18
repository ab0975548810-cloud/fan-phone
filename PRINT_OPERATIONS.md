# Print Center operations

Print Phase 3.0 keeps the order lifecycle and physical print lifecycle separate. A customer order never sends or starts a vendor task automatically.

## Required production configuration

Set these only in the server secret manager:

- `YUN_PRINT_DEVICE_ID`
- `YUN_PRINT_DEVICE_KEY`
- `YUN_PRINT_BASE_URL` (defaults to `https://open.yunweiyin.com`)
- `PRINT_ARTWORK_TOKEN_SECRET` (a long random, stable secret)
- `PRINT_PUBLIC_BASE_URL` (the public HTTPS origin used by vendor artwork and callbacks)

Keep `YUN_PRINT_ENABLED` unset or false until migration, callback reachability, artwork fetching, and vendor sandbox/device verification are complete. The key must never appear in the database, browser, logs, fixtures, or Git history.

## Deployment order

1. Stop old application writers and take a restorable Supabase database snapshot.
2. Review and apply `supabase/migrations/20260918134538_print_center_core.sql`.
3. Verify RLS is enabled and `anon` / `authenticated` have no privileges on all five print tables; run Supabase security and performance advisors.
4. Deploy the application with `YUN_PRINT_ENABLED=false` and the HTTPS/token settings present.
5. In the admin Print Center, configure production profiles from confirmed vendor values. Do not derive physical millimetres from the Fabric editor.
6. Verify a job-scoped artwork URL with a vendor-approved test device or sandbox and verify both callback endpoints.
7. Confirm `startPrint` versus `pushPrint`, channel, spot colour, angle, callback clock tolerance, status 6, and task-list retention with the vendor.
8. Enable `YUN_PRINT_ENABLED=true` only in a supervised test window. Prepare, send, and start one approved test task manually.

## Ambiguous operations

If `receiveTask`, `startPrint`, or `cancelTask` times out or returns a server error, the job moves to `UNKNOWN`. Never retry that operation as a new physical attempt. Use **查核雲端** (`getAllTasks`) and inspect the raw status. Absence from the unprinted queue does not prove a task was never created or that it completed.

`pushPrint`, maintenance controls, and vendor channel stock are intentionally absent. Vendor channel stock is not store SKU inventory.
