"""Disposable PostgreSQL: version-specific authorization is atomic and private."""
import os,uuid,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import psycopg
from psycopg.types.json import Jsonb
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from order_designs import digest
DSN=os.environ['TEST_POSTGRES_DSN'];order='pixel-test-'+uuid.uuid4().hex;source=str(uuid.uuid4())
profile={'sourceJobId':source,'sku_id':'fixture','width_mm':72,'height_mm':144,'left_mm':12,'top_mm':15,'angle':90,'copies':1,'channel':'1','spot_color':''}
doc={'mode':'pixel-v1','profile':profile,'baseSha':'a'*64,'outputPath':'pixel-v2.png','outputSha':'b'*64}
hashed=digest(doc);key='pixel-'+digest([order,2,hashed])[:64]
signature='public.approve_pixel_reprint(text,integer,text,text,text,text,integer)'
with psycopg.connect(DSN) as db:
    for role in ('anon','authenticated'):assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')",(role,signature)).fetchone()[0]
    assert not db.execute('select prosecdef from pg_proc where oid=%s::regprocedure',(signature,)).fetchone()[0]
    db.execute("""insert into public.print_jobs (id,order_id,attempt_no,sku_id,artwork_path,artwork_sha256,artwork_token_nonce,profile_complete,width_mm,height_mm,left_mm,top_mm,angle,copies,channel,spot_color,state)
        values (%s,%s,1,'fixture','original.png',%s,'original',true,72,144,12,15,90,1,'1','','COMPLETED')""",(source,order,'a'*64))
    db.execute('select public.append_order_design_version(%s,0,%s,%s,%s,%s)',(order,Jsonb(doc),'admin','base',hashed))
    db.execute('select public.append_order_design_version(%s,1,%s,%s,%s,%s)',(order,Jsonb(doc),'admin','v2',hashed))
    original=db.execute('select to_jsonb(j) from public.print_jobs j where id=%s',(source,)).fetchone()[0]
def approve(_):
    with psycopg.connect(DSN) as db:
        db.execute('set local role service_role')
        return db.execute('select public.approve_pixel_reprint(%s,2,%s,%s,%s,%s,2500)',(order,hashed,key,'admin','pixel repair')).fetchone()[0]
with ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(approve,range(6)))
assert all(r['ok'] for r in results),results
assert len({r['job']['id'] for r in results})==1
with psycopg.connect(DSN) as db:
    assert db.execute('select to_jsonb(j) from public.print_jobs j where id=%s',(source,)).fetchone()[0]==original
    assert db.execute('select count(*) from public.print_jobs where order_id=%s',(order,)).fetchone()[0]==2
    job=results[0]['job'];assert job['artwork_sha256']=='b'*64 and job['manual_independent']
    for k in profile:
        if k!='sourceJobId':assert job[k]==profile[k],(k,job[k],profile[k])
    audit=db.execute('select payload_json from public.print_events where job_id=%s',(job['id'],)).fetchone()[0]
    assert audit['costCents']==2500 and audit['versionHash']==hashed and audit['reason']=='pixel repair'
    # New version cannot be confirmed while the previous approved job is active.
    db.execute('select public.append_order_design_version(%s,2,%s,%s,%s,%s)',(order,Jsonb(doc),'admin','v3',hashed))
    blocked=db.execute('select public.approve_pixel_reprint(%s,3,%s,%s,%s,%s,2500)',(order,hashed,key+'x','admin','next')).fetchone()[0]
    assert not blocked['ok']
print('PIXEL_POSTGRES_PRIVATE_ATOMIC_APPROVAL_SOURCE_IMMUTABLE_OK')
