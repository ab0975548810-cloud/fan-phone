"""Disposable Postgres: full-layer approval has the same CAS and task protections."""
import os
import sys
import uuid
import copy
import queue
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import psycopg
from psycopg.types.json import Jsonb
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from order_designs import digest
DSN=os.environ['TEST_POSTGRES_DSN'];order='layered-test-'+uuid.uuid4().hex;source=str(uuid.uuid4())
profile={'sourceJobId':source,'sku_id':'fixture','width_mm':72,'height_mm':144,'left_mm':12,'top_mm':15,'angle':90,'copies':1,'channel':'1','spot_color':''}
proof={'mode':'layered-v1','profile':profile,'baseSha':'a'*64,'outputPath':'layered-v2.png','outputSha':'b'*64}
doc={'objects':[{'type':'text','text':'V2'}],'revisionPrint':proof};hashed=digest(doc);key='pixel-'+digest([order,2,hashed])[:64]
with psycopg.connect(DSN) as db:
    db.execute("""insert into public.print_jobs (id,order_id,attempt_no,sku_id,artwork_path,artwork_sha256,artwork_token_nonce,profile_complete,width_mm,height_mm,left_mm,top_mm,angle,copies,channel,spot_color,state)
        values (%s,%s,1,'fixture','original.png',%s,'original',true,72,144,12,15,90,1,'1','','COMPLETED')""",(source,order,'a'*64))
    for n in (0,1):db.execute('select public.append_order_design_version(%s,%s,%s,%s,%s,%s)',(order,n,Jsonb(doc),'admin','revision-'+str(n),hashed))
    original=db.execute('select to_jsonb(j) from public.print_jobs j where id=%s',(source,)).fetchone()[0]
def approve(_):
    with psycopg.connect(DSN) as db:
        db.execute('set local role service_role')
        return db.execute('select public.approve_pixel_reprint(%s,2,%s,%s,%s,%s,1250)',(order,hashed,key,'admin','full-layer edit')).fetchone()[0]
with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(approve,range(4)))
assert all(r['ok'] for r in results),results
assert len({r['job']['id'] for r in results})==1
with psycopg.connect(DSN) as db:
    job=results[0]['job'];assert job['manual_independent'] and job['artwork_path']=='layered-v2.png'
    assert db.execute('select to_jsonb(j) from public.print_jobs j where id=%s',(source,)).fetchone()[0]==original
    audit=db.execute('select payload_json from public.print_events where job_id=%s',(job['id'],)).fetchone()[0]
    assert audit['mode']=='layered-v1' and audit['versionHash']==hashed and audit['costCents']==1250
    db.execute('select public.append_order_design_version(%s,2,%s,%s,%s,%s)',(order,Jsonb(doc),'admin','v3',hashed))
    for state in ('PREPARED','QUEUED','UNKNOWN'):
        db.execute('update public.print_jobs set state=%s where id=%s',(state,job['id']))
        assert not db.execute('select public.approve_pixel_reprint(%s,3,%s,%s,%s,%s,1250)',(order,hashed,key+'3','admin','v3')).fetchone()[0]['ok']
print('LAYERED_POSTGRES_ATOMIC_APPROVAL_IMMUTABLE_V1_OK')


def revision_fixture(label):
    """Create only disposable DB rows; no artwork downloads or vendor client."""
    identity=label+'-'+uuid.uuid4().hex
    original_id=str(uuid.uuid4())
    parameters={**profile,'sourceJobId':original_id}
    document={'objects':[{'type':'text','text':'approved V2'}],
              'revisionPrint':{**proof,'profile':parameters}}
    content_hash=digest(document)
    request_key='pixel-'+digest([identity,2,content_hash])[:64]
    with psycopg.connect(DSN) as db:
        db.execute("""insert into public.print_jobs
            (id,order_id,attempt_no,sku_id,artwork_path,artwork_sha256,artwork_token_nonce,
             profile_complete,width_mm,height_mm,left_mm,top_mm,angle,copies,channel,spot_color,state)
            values (%s,%s,1,'fixture','original.png',%s,'original',true,72,144,12,15,90,1,'1','','COMPLETED')""",
            (original_id,identity,'a'*64))
        for expected in (0,1):
            appended=db.execute('select public.append_order_design_version(%s,%s,%s,%s,%s,%s)',
                (identity,expected,Jsonb(document),'fixture','seed-'+str(expected),content_hash)).fetchone()[0]
            assert appended['ok'],appended
        approved=db.execute('select public.approve_pixel_reprint(%s,2,%s,%s,%s,%s,1250)',
            (identity,content_hash,request_key,'fixture','race fixture')).fetchone()[0]
        assert approved['ok'],approved
        frozen=db.execute('select version,document,content_hash from public.order_design_versions where order_id=%s order by version',
                          (identity,)).fetchall()
        original=db.execute('select to_jsonb(j) from public.print_jobs j where id=%s',(original_id,)).fetchone()[0]
    return identity,approved['job'],document,frozen,original


def claim(db,job_id):
    return db.execute("select public.claim_manual_reprint_send_if_safe(%s,'race-nonce',now()+interval '1 day','fixture')",
                      (job_id,)).fetchone()[0]


def append_v3(db,identity,document):
    updated=copy.deepcopy(document)
    updated['objects'][0]['text']='later V3'
    return db.execute('select public.append_order_design_version(%s,2,%s,%s,%s,%s)',
        (identity,Jsonb(updated),'fixture','append-v3',digest(updated))).fetchone()[0]


def competing_call(ready,operation):
    with psycopg.connect(DSN) as db:
        db.execute("set local statement_timeout='15s'")
        db.execute('set local role service_role')
        ready.put(db.info.backend_pid)
        return operation(db)


def assert_waiting(waiter,holder):
    """Observe an actual lock wait instead of relying on scheduling or sleeps."""
    deadline=time.monotonic()+8
    with psycopg.connect(DSN,autocommit=True) as observer:
        while time.monotonic()<deadline:
            if observer.execute('select %s=any(pg_blocking_pids(%s))',(holder,waiter)).fetchone()[0]:
                return
            time.sleep(.01)
    raise AssertionError('Expected competing revision operation to wait for the held advisory lock')


def assert_immutable(identity,approved,frozen,original,state):
    with psycopg.connect(DSN) as db:
        assert db.execute('select version,document,content_hash from public.order_design_versions where order_id=%s and version<=2 order by version',
                          (identity,)).fetchall()==frozen
        assert db.execute('select to_jsonb(j) from public.print_jobs j where id=%s',(original['id'],)).fetchone()[0]==original
        current=db.execute('select to_jsonb(j) from public.print_jobs j where id=%s',(approved['id'],)).fetchone()[0]
        assert current['state']==state,current
        for field in ('artwork_path','artwork_sha256','manual_independent','sku_id','width_mm','height_mm',
                      'left_mm','top_mm','angle','copies','channel','spot_color'):
            assert current[field]==approved[field],(field,current,approved)


# V3 commits while a V2 sender waits: the database claim must reject stale V2.
identity,approved,document,frozen,original=revision_fixture('append-wins')
ready=queue.Queue()
with ThreadPoolExecutor(max_workers=1) as pool:
    with psycopg.connect(DSN) as winner:
        winner.execute('set local role service_role')
        winner.execute("select pg_advisory_xact_lock(hashtextextended('order-design:'||%s,0))",(identity,))
        pending=pool.submit(competing_call,ready,lambda db:claim(db,approved['id']))
        assert_waiting(ready.get(timeout=8),winner.info.backend_pid)
        appended=append_v3(winner,identity,document)
        assert appended=={'ok':True,'version':3},appended
        winner.commit()
    result=pending.result(timeout=15)
assert result=={'ok':False,'code':'STALE_DESIGN_VERSION'},result
assert_immutable(identity,approved,frozen,original,'PREPARED')
print('REVISION_POSTGRES_APPEND_WINS_BLOCKS_STALE_SEND_OK')


# V2 claims first: a later V3 save cannot recall or mutate the claimed V2 job.
identity,approved,document,frozen,original=revision_fixture('claim-wins')
ready=queue.Queue()
with ThreadPoolExecutor(max_workers=1) as pool:
    with psycopg.connect(DSN) as winner:
        winner.execute('set local role service_role')
        sent=claim(winner,approved['id'])
        assert sent['ok'] and sent['job']['state']=='SENDING',sent
        pending=pool.submit(competing_call,ready,lambda db:append_v3(db,identity,document))
        assert_waiting(ready.get(timeout=8),winner.info.backend_pid)
        winner.commit()
    appended=pending.result(timeout=15)
assert appended=={'ok':True,'version':3},appended
assert_immutable(identity,approved,frozen,original,'SENDING')
print('REVISION_POSTGRES_CLAIM_WINS_FREEZES_APPROVED_V2_OK')


# An independently queued/unknown task after approval must stop SQL send claims.
for state in ('QUEUED','UNKNOWN'):
    identity,approved,document,frozen,original=revision_fixture('competing-'+state.lower())
    with psycopg.connect(DSN) as db:
        db.execute("""insert into public.print_jobs
            (id,order_id,attempt_no,artwork_path,artwork_token_nonce,state,manual_independent,ambiguous_operation)
            values (%s,%s,3,'competing.png','competing',%s,true,%s)""",
            (str(uuid.uuid4()),identity,state,'receiveTask' if state=='UNKNOWN' else None))
    with psycopg.connect(DSN) as db:
        db.execute('set local role service_role')
        result=claim(db,approved['id'])
    assert result=={'ok':False,'code':'RECONCILE_REQUIRED'},(state,result)
    assert_immutable(identity,approved,frozen,original,'PREPARED')
print('REVISION_POSTGRES_POST_APPROVAL_QUEUED_UNKNOWN_BLOCKED_OK')
