"""Initialize ONLY an explicitly selected disposable CI database."""
import os
from pathlib import Path
import psycopg

root = Path(__file__).resolve().parents[2]
with psycopg.connect(os.environ['TEST_POSTGRES_DSN']) as db:
    db.execute('CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS')
    db.execute((root / 'supabase_setup.sql').read_text(encoding='utf-8').split('-- Public bucket')[0])
    for path in sorted((root / 'supabase/migrations').glob('*.sql')):
        db.execute(path.read_text(encoding='utf-8-sig'))
    for role in ('anon', 'authenticated'):
        assert not db.execute("SELECT has_function_privilege(%s, 'public.commerce_commit(bigint,jsonb,jsonb,text)', 'EXECUTE')", (role,)).fetchone()[0]
    assert db.execute("SELECT bool_and(relrowsecurity) FROM pg_class WHERE oid IN ('public.orders'::regclass,'public.app_store'::regclass)").fetchone()[0]
    assert not db.execute("SELECT prosecdef FROM pg_proc WHERE oid='public.commerce_commit(bigint,jsonb,jsonb,text)'::regprocedure").fetchone()[0]
print('POSTGRES_SCHEMA_AND_PRIVILEGES_OK')
