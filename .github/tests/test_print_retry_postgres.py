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
print("PRINT_RETRY_POSTGRES_CONCURRENCY_OK")
