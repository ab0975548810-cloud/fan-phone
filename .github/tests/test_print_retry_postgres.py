"""The production partial unique index permits only one active retry attempt."""
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg
from psycopg.errors import UniqueViolation


DSN = os.environ["TEST_POSTGRES_DSN"]
ORDER_ID = "retry-concurrency-fixture"


def insert_attempt(job_id):
    try:
        with psycopg.connect(DSN) as db:
            db.execute("""insert into public.print_jobs
                (id,order_id,attempt_no,artwork_path,artwork_token_nonce,state)
                values (%s,%s,2,'fixture.png',%s,'PREPARED')""",
                       (job_id, ORDER_ID, "nonce-" + job_id))
        return True
    except UniqueViolation:
        return False


with psycopg.connect(DSN) as db:
    db.execute("delete from public.print_jobs where order_id=%s", (ORDER_ID,))
    db.execute("""insert into public.print_jobs
        (id,order_id,attempt_no,artwork_path,artwork_token_nonce,state)
        values (%s,%s,1,'fixture.png','old-nonce','FAILED')""",
               (str(uuid.uuid4()), ORDER_ID))

ids = [str(uuid.uuid4()), str(uuid.uuid4())]
with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(insert_attempt, ids))
assert sum(results) == 1, results

with psycopg.connect(DSN) as db:
    rows = db.execute("select attempt_no,state from public.print_jobs where order_id=%s order by attempt_no",
                      (ORDER_ID,)).fetchall()
assert rows == [(1, "FAILED"), (2, "PREPARED")], rows

# A reconciled retry cannot adopt the old attempt's vendor task id.
with psycopg.connect(DSN) as db:
    jobs = db.execute("select id,attempt_no from public.print_jobs where order_id=%s order by attempt_no",
                      (ORDER_ID,)).fetchall()
    db.execute("update public.print_jobs set vendor_taskid='old-attempt-task' where id=%s", (jobs[0][0],))
try:
    with psycopg.connect(DSN) as db:
        db.execute("update public.print_jobs set vendor_taskid='old-attempt-task' where id=%s", (jobs[1][0],))
except UniqueViolation:
    pass
else:
    raise AssertionError("vendor_taskid unique constraint accepted a cross-attempt collision")
with psycopg.connect(DSN) as db:
    assert db.execute("select vendor_taskid from public.print_jobs where id=%s", (jobs[1][0],)).fetchone() == (None,)

# Production's partial unique index proves why a superseded callback must be
# audit-only: reviving attempt #1 while #2 is PREPARED is rejected.
try:
    with psycopg.connect(DSN) as db:
        db.execute("update public.print_jobs set state='PRINTING' where id=%s", (jobs[0][0],))
except UniqueViolation:
    pass
else:
    raise AssertionError("partial unique index accepted two active attempts")

# The production RPC atomically records physical evidence and quarantines the
# new attempt. Once evidence commits first, send claim must fail closed.
with psycopg.connect(DSN) as db:
    callback_result = db.execute(
        "select public.apply_print_callback_safely(%s,'1','late physical')",
        (jobs[0][0],),
    ).fetchone()[0]
assert callback_result["superseded"] is True, callback_result
with psycopg.connect(DSN) as db:
    blocked_claim = db.execute(
        "select public.claim_print_send_if_safe(%s,'new-nonce',now()+interval '1 day','device')",
        (jobs[1][0],),
    ).fetchone()[0]
assert blocked_claim == {"ok": False, "code": "REPRINT_REQUIRED"}, blocked_claim
with psycopg.connect(DSN) as db:
    states = db.execute("""select attempt_no,state,vendor_raw_status,ambiguous_operation,
                                  started_at is not null
                           from public.print_jobs where order_id=%s order by attempt_no""",
                        (ORDER_ID,)).fetchall()
assert states == [
    (1, "FAILED", "1", None, True),
    (2, "CANCELED", None, "prior_attempt_activity", False),
], states


def race_atomic_send_and_callback(index):
    order_id = f"retry-order-lock-{index}"
    old_id, latest_id = str(uuid.uuid4()), str(uuid.uuid4())
    with psycopg.connect(DSN) as db:
        db.execute("delete from public.print_jobs where order_id=%s", (order_id,))
        db.execute("""insert into public.print_jobs
            (id,order_id,attempt_no,artwork_path,artwork_token_nonce,state,vendor_taskid)
            values (%s,%s,1,'fixture.png','old','FAILED',%s),
                   (%s,%s,2,'fixture.png','latest','PREPARED',null)""",
                   (old_id, order_id, f"old-race-task-{index}", latest_id, order_id))
    barrier = threading.Barrier(2)

    def claim():
        with psycopg.connect(DSN) as db:
            barrier.wait()
            return db.execute(
                "select public.claim_print_send_if_safe(%s,%s,now()+interval '1 day','device')",
                (latest_id, f"race-nonce-{index}"),
            ).fetchone()[0]

    def callback():
        with psycopg.connect(DSN) as db:
            barrier.wait()
            return db.execute(
                "select public.apply_print_callback_safely(%s,'1','concurrent physical')",
                (old_id,),
            ).fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        claim_result, callback_result = list(pool.map(lambda fn: fn(), (claim, callback)))
    assert callback_result["superseded"] is True, callback_result
    assert claim_result.get("ok") is True or claim_result == {
        "ok": False, "code": "REPRINT_REQUIRED"
    }, claim_result
    with psycopg.connect(DSN) as db:
        rows = db.execute("""select attempt_no,state,vendor_raw_status,
                                    ambiguous_operation,started_at is not null
                             from public.print_jobs where order_id=%s order by attempt_no""",
                          (order_id,)).fetchall()
    assert rows[0] == (1, "FAILED", "1", None, True), rows
    assert rows[1][1] in ("CANCELED", "UNKNOWN"), rows
    assert rows[1][3] == "prior_attempt_activity", rows


for race_index in range(12):
    race_atomic_send_and_callback(race_index)
print("PRINT_RETRY_POSTGRES_CONCURRENCY_OK")
