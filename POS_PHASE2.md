# POS Phase 2

Extend the existing commerce record, CAS commit, Supabase RPC and inventory ledger.
Do not deploy or merge automatically.

- Series are the existing stable style IDs; manage SKUs within one selected series.
- Add target stock, status buckets, grouped replenishment exports and idempotent PURCHASE_RECEIVED entries.
- Add audited expense records and Asia/Taipei calendar reports based on immutable order snapshots.
- Preserve historical unknown cost explicitly. Never infer it from current SKU cost.
- Complete Smoke, SQLite/PostgreSQL Commerce Transactions and responsive WebKit regression before review.

Implementation, migration and deployment details will be recorded in COMMERCE_OPERATIONS.md.
