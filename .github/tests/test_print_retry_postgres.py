"""The production partial unique index permits only one active retry attempt."""
import os
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import psycopg
from psycopg import sql
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from print_store import PrintStore


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

# Quarantined reconcile may add raw/timestamp audit, but cannot clear the
# quarantine or restore workflow state.
with psycopg.connect(DSN) as db:
    quarantined_reconcile = db.execute(
        "select public.apply_print_reconcile_safely(%s,true,%s,'1','printing audit',false)",
        (jobs[1][0], "quarantine-reconcile-task"),
    ).fetchone()[0]
assert quarantined_reconcile["code"] == "RECONCILE_REQUIRED", quarantined_reconcile
assert quarantined_reconcile["quarantined"] is True, quarantined_reconcile
with psycopg.connect(DSN) as db:
    quarantined_row = db.execute("""select state,ambiguous_operation,vendor_raw_status,
                                           started_at is not null
                                    from public.print_jobs where id=%s""",
                                 (jobs[1][0],)).fetchone()
assert quarantined_row == ("CANCELED", "prior_attempt_activity", "1", True), quarantined_row


def assert_reconcile_timestamp_sticky(index, first_status, final_status, timestamp_column):
    order_id = f"reconcile-sticky-timestamp-{index}"
    job_id = str(uuid.uuid4())
    taskid = f"reconcile-sticky-task-{index}"
    with psycopg.connect(DSN) as db:
        db.execute("delete from public.print_jobs where order_id=%s", (order_id,))
        db.execute("""insert into public.print_jobs
            (id,order_id,attempt_no,artwork_path,artwork_token_nonce,state,vendor_taskid)
            values (%s,%s,1,'fixture.png','sticky','QUEUED',%s)""",
                   (job_id, order_id, taskid))
        first = db.execute(
            "select public.apply_print_reconcile_safely(%s,true,%s,%s,'first audit',false)",
            (job_id, taskid, first_status),
        ).fetchone()[0]
    assert first["job"][timestamp_column] is not None, first
    timestamp_value = first["job"][timestamp_column]
    with psycopg.connect(DSN) as db:
        later = db.execute(
            "select public.apply_print_reconcile_safely(%s,true,%s,%s,'later terminal',false)",
            (job_id, taskid, final_status),
        ).fetchone()[0]
        blocked = db.execute(
            "select public.claim_print_send_if_safe(%s,'blocked',now()+interval '1 day','device')",
            (job_id,),
        ).fetchone()[0]
    assert later["job"][timestamp_column] == timestamp_value, later
    assert later["job"]["state"] == "FAILED", later
    assert blocked == {"ok": False, "code": "REPRINT_REQUIRED"}, blocked


assert_reconcile_timestamp_sticky(1, "1", "4", "started_at")
assert_reconcile_timestamp_sticky(2, "2", "4", "completed_at")

cancel_order_id = "reconcile-canceled-timestamp"
cancel_job_id = str(uuid.uuid4())
with psycopg.connect(DSN) as db:
    db.execute("delete from public.print_jobs where order_id=%s", (cancel_order_id,))
    db.execute("""insert into public.print_jobs
        (id,order_id,attempt_no,artwork_path,artwork_token_nonce,state,vendor_taskid)
        values (%s,%s,1,'fixture.png','cancel-sticky','QUEUED','cancel-sticky-task')""",
               (cancel_job_id, cancel_order_id))
    canceled = db.execute(
        "select public.apply_print_reconcile_safely(%s,true,'cancel-sticky-task','3','canceled audit',false)",
        (cancel_job_id,),
    ).fetchone()[0]
assert canceled["job"]["state"] == "CANCELED", canceled
assert canceled["job"]["canceled_at"] is not None, canceled


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


def race_atomic_reconcile_and_callback(index):
    order_id = f"reconcile-order-lock-{index}"
    old_id, latest_id = str(uuid.uuid4()), str(uuid.uuid4())
    latest_taskid = f"reconcile-new-task-{index}"
    with psycopg.connect(DSN) as db:
        db.execute("delete from public.print_jobs where order_id=%s", (order_id,))
        db.execute("""insert into public.print_jobs
            (id,order_id,attempt_no,artwork_path,artwork_token_nonce,state,vendor_taskid)
            values (%s,%s,1,'fixture.png','old','FAILED',%s),
                   (%s,%s,2,'fixture.png','latest','QUEUED',%s)""",
                   (old_id, order_id, f"reconcile-old-task-{index}",
                    latest_id, order_id, latest_taskid))
    barrier = threading.Barrier(2)

    def reconcile():
        with psycopg.connect(DSN) as db:
            barrier.wait()
            return db.execute(
                "select public.apply_print_reconcile_safely(%s,true,%s,'0','queued',false)",
                (latest_id, latest_taskid),
            ).fetchone()[0]

    def callback():
        with psycopg.connect(DSN) as db:
            barrier.wait()
            return db.execute(
                "select public.apply_print_callback_safely(%s,'1','late physical during reconcile')",
                (old_id,),
            ).fetchone()[0]

    with ThreadPoolExecutor(max_workers=2) as pool:
        reconcile_result, callback_result = list(pool.map(
            lambda fn: fn(), (reconcile, callback)))
    assert callback_result["superseded"] is True, callback_result
    with psycopg.connect(DSN) as db:
        rows = db.execute("""select attempt_no,state,vendor_raw_status,
                                    ambiguous_operation,last_error,started_at is not null
                             from public.print_jobs where order_id=%s order by attempt_no""",
                          (order_id,)).fetchall()
    assert rows[0][0:4] == (1, "FAILED", "1", None), rows
    assert rows[0][5] is True, rows
    assert rows[1][1] == "UNKNOWN", rows
    assert rows[1][3] == "prior_attempt_activity", rows
    assert "人工查核" in rows[1][4], rows
    if reconcile_result.get("quarantined"):
        assert reconcile_result["code"] == "RECONCILE_REQUIRED", reconcile_result


for race_index in range(12):
    race_atomic_reconcile_and_callback(race_index)


class _Result:
    def __init__(self, data):
        self.data = data


class _PostgresTableQuery:
    """Small PostgREST-shaped adapter for exercising the real PrintStore path."""

    def __init__(self, table):
        if table != "print_jobs":
            raise AssertionError(f"unexpected test table: {table}")
        self.table = table
        self.filters = []
        self.ordering = None
        self.row_limit = None
        self.insert_row = None

    def select(self, _columns):
        return self

    def eq(self, name, value):
        self.filters.append((name, value))
        return self

    def order(self, name, desc=False):
        self.ordering = (name, bool(desc))
        return self

    def limit(self, value):
        self.row_limit = int(value)
        return self

    def insert(self, row):
        self.insert_row = dict(row)
        return self

    def execute(self):
        with psycopg.connect(DSN, row_factory=dict_row) as db:
            if self.insert_row is not None:
                names = list(self.insert_row)
                query = sql.SQL("insert into public.{} ({}) values ({}) returning *").format(
                    sql.Identifier(self.table),
                    sql.SQL(",").join(map(sql.Identifier, names)),
                    sql.SQL(",").join(sql.Placeholder() for _ in names),
                )
                row = db.execute(query, [self.insert_row[name] for name in names]).fetchone()
                return _Result([dict(row)])
            query = sql.SQL("select * from public.{}").format(sql.Identifier(self.table))
            params = []
            if self.filters:
                clauses = []
                for name, value in self.filters:
                    clauses.append(sql.SQL("{} = {}").format(
                        sql.Identifier(name), sql.Placeholder()))
                    params.append(value)
                query += sql.SQL(" where ") + sql.SQL(" and ").join(clauses)
            if self.ordering:
                name, desc = self.ordering
                query += sql.SQL(" order by {} {}").format(
                    sql.Identifier(name), sql.SQL("desc" if desc else "asc"))
            if self.row_limit is not None:
                query += sql.SQL(" limit {} ").format(sql.Literal(self.row_limit))
            rows = db.execute(query, params).fetchall()
            return _Result([dict(row) for row in rows])


class _PostgresRpcQuery:
    ALLOWED = {
        "apply_print_callback_safely": (
            "p_job_id", "p_status", "p_message"),
        "claim_print_send_if_safe": (
            "p_job_id", "p_artwork_token_nonce",
            "p_artwork_token_expires_at", "p_device_id"),
    }

    def __init__(self, name, params):
        if name not in self.ALLOWED:
            raise AssertionError(f"unexpected test RPC: {name}")
        self.name = name
        self.params = params

    def execute(self):
        names = self.ALLOWED[self.name]
        query = sql.SQL("select public.{}({})").format(
            sql.Identifier(self.name),
            sql.SQL(",").join(sql.Placeholder() for _ in names),
        )
        with psycopg.connect(DSN) as db:
            value = db.execute(query, [self.params[name] for name in names]).fetchone()[0]
        return _Result(value)


class _PostgresSupabaseAdapter:
    def table(self, name):
        return _PostgresTableQuery(name)

    def rpc(self, name, params):
        return _PostgresRpcQuery(name, params)


def race_real_create_job_and_callback(index):
    """Race the production store service path, not only raw SQL constraints."""
    order_id = f"create-job-callback-race-{index}"
    old_id = str(uuid.uuid4())
    with psycopg.connect(DSN) as db:
        db.execute("delete from public.print_jobs where order_id=%s", (order_id,))
        db.execute("""insert into public.print_jobs
            (id,order_id,attempt_no,artwork_path,artwork_token_nonce,state,vendor_taskid)
            values (%s,%s,1,'fixture.png','old','FAILED',%s)""",
                   (old_id, order_id, f"create-race-old-task-{index}"))

    store = PrintStore(SimpleNamespace(
        USE_SUPABASE=True,
        SUPABASE=_PostgresSupabaseAdapter(),
    ))
    barrier = threading.Barrier(2)

    def create_retry():
        barrier.wait()
        return store.create_job(
            {"id": order_id, "print_path": "fixture.png"},
            "", None, "0" * 64, f"create-race-nonce-{index}",
        )

    def physical_callback():
        barrier.wait()
        return store.apply_task_callback(
            old_id, "1", "physical activity concurrent with retry creation")

    with ThreadPoolExecutor(max_workers=2) as pool:
        create_result, callback_result = list(pool.map(
            lambda fn: fn(), (create_retry, physical_callback)))

    assert isinstance(create_result, dict), create_result
    assert isinstance(callback_result.get("job"), dict), callback_result
    with psycopg.connect(DSN, row_factory=dict_row) as db:
        rows = [dict(row) for row in db.execute("""select * from public.print_jobs
            where order_id=%s order by attempt_no""", (order_id,)).fetchall()]
    assert rows[0]["started_at"] is not None, rows
    assert rows[0]["vendor_raw_status"] == "1", rows
    assert len(rows) in (1, 2), rows
    if len(rows) == 2:
        assert rows[1]["state"] in ("CANCELED", "UNKNOWN"), rows
        assert rows[1]["ambiguous_operation"] == "prior_attempt_activity", rows

    latest = rows[-1]
    claim = store.claim_send_if_safe(
        latest["id"], nonce=f"blocked-after-create-race-{index}",
        expires_at="2099-01-01T00:00:00+00:00", device_id="test-device")
    assert claim == {"ok": False, "code": "REPRINT_REQUIRED"}, (rows, claim)
    with psycopg.connect(DSN) as db:
        sending = db.execute("""select count(*) from public.print_jobs
            where order_id=%s and state='SENDING'""", (order_id,)).fetchone()[0]
    assert sending == 0, rows
    assert not any(row["state"] == "PREPARED" for row in rows), rows
    assert rows[-1]["state"] in ("CANCELED", "UNKNOWN", "PRINTING"), rows


for race_index in range(20):
    race_real_create_job_and_callback(race_index)
print("PRINT_RETRY_POSTGRES_CONCURRENCY_OK")
