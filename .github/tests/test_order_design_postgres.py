"""Append-only version/CAS/privilege regressions in explicit disposable PostgreSQL."""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
import psycopg
from psycopg.types.json import Jsonb

DSN=os.environ['TEST_POSTGRES_DSN']
ORDER='design-test-'+uuid.uuid4().hex
SIGNATURE='public.append_order_design_version(text,integer,jsonb,text,text,text)'
def append(expected,request,document):
    with psycopg.connect(DSN) as db:
        db.execute('set local role service_role')
        return db.execute('select public.append_order_design_version(%s,%s,%s,%s,%s,%s)',
            (ORDER,expected,Jsonb(document),'isolated-admin',request,str(document))).fetchone()[0]

with psycopg.connect(DSN) as db:
    for role in ('anon','authenticated'):
        assert not db.execute("select has_function_privilege(%s,%s,'EXECUTE')",(role,SIGNATURE)).fetchone()[0]
        for permission in ('SELECT','INSERT','UPDATE','DELETE'):
            assert not db.execute('select has_table_privilege(%s,%s,%s)',(role,'public.order_design_versions',permission)).fetchone()[0]
    assert db.execute("select relrowsecurity from pg_class where oid='public.order_design_versions'::regclass").fetchone()[0]
    for permission in ('UPDATE','DELETE'):
        assert not db.execute('select has_table_privilege(%s,%s,%s)',('service_role','public.order_design_versions',permission)).fetchone()[0]
assert append(0,'original',{'original':True})=={'ok':True,'version':1}
assert append(0,'original',{'original':True})=={'ok':True,'version':1}
assert not append(0,'original',{'original':False})['ok']
with ThreadPoolExecutor(max_workers=8) as pool:
    results=list(pool.map(lambda n:append(1,'save-'+str(n),{'revision':n}),range(8)))
assert sum(r['ok'] for r in results)==1,results
with psycopg.connect(DSN) as db:
    rows=db.execute('select version,document,actor from public.order_design_versions where order_id=%s order by version',(ORDER,)).fetchall()
    assert len(rows)==2 and rows[0]==(1,{'original':True},'isolated-admin')
    try:
        with db.transaction():
            db.execute('set local role service_role')
            db.execute('delete from public.order_design_versions where order_id=%s',(ORDER,))
    except psycopg.errors.InsufficientPrivilege:pass
    else:raise AssertionError('service role deleted immutable V1')
print('ORDER_DESIGN_POSTGRES_RLS_CAS_APPEND_ONLY_OK')
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).with_name('test_pixel_order_postgres.py')))
runpy.run_path(str(Path(__file__).with_name('test_revision_reprint_postgres.py')))
