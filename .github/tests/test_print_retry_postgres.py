"""The production partial unique index permits only one active retry attempt."""
import os
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
print("PRINT_RETRY_POSTGRES_CONCURRENCY_OK")
