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
different content is rejected. Admin lifecycle requests also retain a key while
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
