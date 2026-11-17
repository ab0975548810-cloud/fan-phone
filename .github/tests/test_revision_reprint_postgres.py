"""Disposable Postgres: full-layer approval has the same CAS and task protections."""
import os
import sys
import uuid
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
