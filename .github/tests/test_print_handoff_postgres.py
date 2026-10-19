"""Real PostgreSQL atomic outbox, cutoff and multi-worker claim regression."""
import copy
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg


DSN = os.environ["TEST_POSTGRES_DSN"]
ORDER_ID = "handoff-atomic-order"
REQUEST_KEY = "handoff-postgres-request-0001"
MARKER = "auto-print-handoff-v1"


base = {
    "version": 3, "revision": 0, "skus": [], "order_finance": {},
    "requests": {}, "actions": {}, "inventory_ledger": [],
    "expenses": {}, "expense_ledger": [],
}
response = {"status": "success", "order_id": ORDER_ID, "total": 100}
receipt = {
    "fingerprint": "fixture", "response": response, "auto_print_v1": True,
    "auto_print_handoff_v1": {"version": MARKER, "order_id": ORDER_ID},
}
created = copy.deepcopy(base)
created.update(revision=1, requests={REQUEST_KEY: receipt})
order = {
    "id": ORDER_ID, "customer_name": "fixture", "payment_method": "cash",
    "model_id": "model", "model_name": "model", "style_id": "style",
    "style_name": "style", "unit_price": 100, "quantity": 1,
    "total": 100, "status": "待處理", "design_json": {},
    "print_path": "fixture.png", "mockup_path": "fixture-preview.png",
    "created_at_unix": 1,
    "_print_handoff": {
        "version": MARKER, "order_id": ORDER_ID, "request_key": REQUEST_KEY,
    },
}

with psycopg.connect(DSN) as db:
    db.execute("delete from public.print_handoffs")
    db.execute("delete from public.print_jobs")
    db.execute("delete from public.orders")
    db.execute("delete from public.app_store where key='commerce_data'")
    db.execute("insert into public.app_store(key,value) values ('commerce_data',%s)",
               (psycopg.types.json.Jsonb(base),))
    committed = db.execute(
        "select public.commerce_commit(0,%s,%s,'create')",
        (psycopg.types.json.Jsonb(created), psycopg.types.json.Jsonb(order)),
    ).fetchone()[0]
assert committed is True

with psycopg.connect(DSN) as db:
    assert db.execute("select count(*) from public.orders where id=%s", (ORDER_ID,)).fetchone()[0] == 1
    outbox = db.execute("""select order_id,request_key,marker_version,state,attempt_count
        from public.print_handoffs where order_id=%s""", (ORDER_ID,)).fetchone()
assert outbox == (ORDER_ID, REQUEST_KEY, MARKER, "PENDING", 0), outbox

# An idempotent receipt replay advances commerce CAS but cannot create another
# order, stock mutation, or outbox row.
replay = copy.deepcopy(created)
replay["revision"] = 2
with psycopg.connect(DSN) as db:
    assert db.execute("select public.commerce_commit(1,%s,null,'')",
                      (psycopg.types.json.Jsonb(replay),)).fetchone()[0] is True
    assert db.execute("select count(*) from public.print_handoffs where order_id=%s",
                      (ORDER_ID,)).fetchone()[0] == 1
    assert db.execute("select count(*) from public.orders where id=%s",
                      (ORDER_ID,)).fetchone()[0] == 1

# Marker/response mismatch rolls the entire create transaction back.
invalid_id = "handoff-invalid-marker"
invalid_request = "handoff-invalid-request-0001"
invalid_data = copy.deepcopy(replay)
invalid_data["revision"] = 3
invalid_data["requests"][invalid_request] = {
    "fingerprint": "invalid", "auto_print_v1": True,
    "auto_print_handoff_v1": {"version": MARKER, "order_id": invalid_id},
    "response": {"status": "success", "order_id": "different-order"},
}
invalid_order = {**order, "id": invalid_id, "_print_handoff": {
    "version": MARKER, "order_id": invalid_id, "request_key": invalid_request,
}}
try:
    with psycopg.connect(DSN) as db:
        db.execute("select public.commerce_commit(2,%s,%s,'create')", (
            psycopg.types.json.Jsonb(invalid_data),
            psycopg.types.json.Jsonb(invalid_order),
        ))
except psycopg.errors.RaiseException:
    pass
else:
    raise AssertionError("mismatched handoff marker committed")
with psycopg.connect(DSN) as db:
    assert db.execute("select count(*) from public.orders where id=%s",
                      (invalid_id,)).fetchone()[0] == 0
    assert db.execute("select count(*) from public.print_handoffs where order_id=%s",
                      (invalid_id,)).fetchone()[0] == 0

barrier = threading.Barrier(20)


def claim(_index):
    barrier.wait()
    with psycopg.connect(DSN) as db:
        rows = db.execute(
            "select id,lease_token from public.claim_print_handoffs(20,60)"
        ).fetchall()
    return rows


with ThreadPoolExecutor(max_workers=20) as pool:
    claims = list(pool.map(claim, range(20)))
flat = [row for rows in claims for row in rows]
assert len(flat) == 1, flat
handoff_id, lease_token = flat[0]

with psycopg.connect(DSN) as db:
    finished = db.execute(
        "select public.finish_print_handoff(%s,%s,'PREPARED',null,null,null)",
        (handoff_id, lease_token),
    ).fetchone()[0]
    assert finished["ok"] is True, finished
    assert db.execute("select count(*) from public.claim_print_handoffs(20,60)").fetchone()[0] == 0

# Pre-release/legacy candidates remain visible but are structurally unclaimable.
legacy_order = "handoff-legacy-review"
with psycopg.connect(DSN) as db:
    db.execute("""insert into public.orders
      (id,customer_name,payment_method,model_id,model_name,style_id,style_name,
       unit_price,quantity,total,status,created_at_unix)
      values (%s,'fixture','cash','m','m','s','s',100,1,100,'待處理',1)""",
               (legacy_order,))
    db.execute("""insert into public.print_handoffs
      (id,order_id,request_key,marker_version,state,last_error_code)
      values (%s,%s,%s,'legacy-auto-print-v1','REVIEW','LEGACY_CUTOFF_REVIEW')""",
               (str(uuid.uuid4()), legacy_order, "legacy-review-key-0001"))
    assert db.execute("select count(*) from public.claim_print_handoffs(20,60)").fetchone()[0] == 0

print("PRINT_HANDOFF_POSTGRES_ATOMIC_OK")
