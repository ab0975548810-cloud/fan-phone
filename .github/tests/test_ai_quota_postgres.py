"""PostgreSQL regressions for the atomic rolling-24h RunPod quota ledger."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import uuid

import psycopg


DSN = os.environ['TEST_POSTGRES_DSN']


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def reset(db):
    db.execute('truncate public.ai_usage_events')


def reserve(db, client, ip, request_id=None):
    request_id = request_id or uuid.uuid4()
    return db.execute(
        'select public.reserve_ai_usage(%s,%s,%s)',
        (request_id, digest(client), digest(ip)),
    ).fetchone()[0], request_id


def submit(db, request_id, job_id=None):
    return db.execute(
        'select public.mark_ai_usage_submitted(%s,%s)',
        (request_id, job_id or f'job-{request_id}'),
    ).fetchone()[0]


def finish(db, request_id, state='COMPLETED'):
    return db.execute(
        'select public.finish_ai_usage(%s,%s)', (request_id, state)
    ).fetchone()[0]


with psycopg.connect(DSN) as db:
    reset(db)
    for index in range(5):
        decision, request_id = reserve(db, 'device-a', f'ip-{index}')
        assert decision['reserved'] and submit(db, request_id) and finish(db, request_id)
    denied, _ = reserve(db, 'device-a', 'fresh-ip')
    assert denied['code'] == 'AI_DEVICE_DAILY_LIMIT', denied

    reset(db)
    for index in range(15):
        decision, request_id = reserve(db, f'device-{index}', 'shared-ip')
        assert decision['reserved'] and submit(db, request_id) and finish(db, request_id)
    denied, _ = reserve(db, 'device-16', 'shared-ip')
    assert denied['code'] == 'AI_IP_DAILY_LIMIT', denied

    reset(db)
    for index in range(60):
        decision, request_id = reserve(db, f'global-device-{index}', f'global-ip-{index}')
        assert decision['reserved'] and submit(db, request_id) and finish(db, request_id)
    denied, _ = reserve(db, 'global-device-61', 'global-ip-61')
    assert denied['code'] == 'AI_GLOBAL_DAILY_LIMIT', denied

    reset(db)
    active_ids = []
    for index in range(2):
        decision, request_id = reserve(db, f'active-device-{index}', f'active-ip-{index}')
        assert decision['reserved']
        active_ids.append(request_id)
    denied, _ = reserve(db, 'active-device-3', 'active-ip-3')
    assert denied['code'] == 'AI_BUSY', denied

    reset(db)
    db.execute(
        """insert into public.ai_usage_events
           (request_id,client_hash,ip_hash,state,counted,runpod_job_id,created_at,submitted_at,finished_at)
           values (%s,%s,%s,'COMPLETED',true,'old-job',now()-interval '25 hours',
                   now()-interval '25 hours',now()-interval '25 hours')""",
        (uuid.uuid4(), digest('old-device'), digest('old-ip')),
    )
    decision, request_id = reserve(db, 'old-device', 'old-ip')
    assert decision['reserved'], decision
    assert db.execute('select public.release_ai_usage(%s)', (request_id,)).fetchone()[0]

    reset(db)
    stale_id = uuid.uuid4()
    db.execute(
        """insert into public.ai_usage_events
           (request_id,client_hash,ip_hash,state,counted,created_at)
           values (%s,%s,%s,'RESERVED',false,now()-interval '11 minutes')""",
        (stale_id, digest('stale-device'), digest('stale-ip')),
    )
    decision, current_id = reserve(db, 'current-device', 'current-ip')
    assert decision['reserved']
    stale = db.execute(
        'select state,counted from public.ai_usage_events where request_id=%s', (stale_id,)
    ).fetchone()
    assert stale == ('RELEASED', False), stale
    assert db.execute('select public.release_ai_usage(%s)', (current_id,)).fetchone()[0]

    reset(db)
    decision, request_id = reserve(db, 'release-device', 'release-ip')
    assert decision['reserved']
    assert db.execute('select public.release_ai_usage(%s)', (request_id,)).fetchone()[0]
    assert db.execute(
        'select state,counted,runpod_job_id from public.ai_usage_events where request_id=%s',
        (request_id,),
    ).fetchone() == ('RELEASED', False, None)

    decision, request_id = reserve(db, 'failed-device', 'failed-ip')
    assert decision['reserved'] and submit(db, request_id, 'provider-job-1')
    assert finish(db, request_id, 'FAILED')
    assert db.execute(
        'select state,counted,runpod_job_id from public.ai_usage_events where request_id=%s',
        (request_id,),
    ).fetchone() == ('FAILED', True, 'provider-job-1')

# A new process/connection sees the already-counted rows.
with psycopg.connect(DSN) as first:
    reset(first)
    for index in range(5):
        decision, request_id = reserve(first, 'restart-device', f'restart-ip-{index}')
        assert decision['reserved'] and submit(first, request_id) and finish(first, request_id)
with psycopg.connect(DSN) as after_restart:
    denied, _ = reserve(after_restart, 'restart-device', 'restart-new-ip')
    assert denied['code'] == 'AI_DEVICE_DAILY_LIMIT', denied


def concurrent_reserve(index):
    with psycopg.connect(DSN) as connection:
        decision, request_id = reserve(
            connection, f'concurrent-device-{index}', f'concurrent-ip-{index}'
        )
        return decision, request_id


with psycopg.connect(DSN) as db:
    reset(db)
with ThreadPoolExecutor(max_workers=6) as pool:
    concurrent = list(pool.map(concurrent_reserve, range(6)))
assert sum(1 for decision, _ in concurrent if decision['reserved']) == 2, concurrent
assert sum(1 for decision, _ in concurrent if decision['code'] == 'AI_BUSY') == 4, concurrent

print('AI_QUOTA_POSTGRES_ATOMIC_LIMITS_AND_RESTART_OK')
