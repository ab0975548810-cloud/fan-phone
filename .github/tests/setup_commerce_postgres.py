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
    assert db.execute("""SELECT bool_and(relrowsecurity) FROM pg_class WHERE oid IN (
        'public.orders'::regclass,'public.app_store'::regclass,'public.production_profiles'::regclass,
        'public.print_jobs'::regclass,'public.print_requests'::regclass,
        'public.print_events'::regclass,'public.printer_status_events'::regclass
    )""").fetchone()[0]
    for table in ('production_profiles','print_jobs','print_requests','print_events','printer_status_events'):
        for role in ('anon','authenticated'):
            assert not db.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", (role, 'public.' + table)).fetchone()[0]
            assert not db.execute("SELECT has_table_privilege(%s, %s, 'INSERT')", (role, 'public.' + table)).fetchone()[0]
        assert db.execute("SELECT has_table_privilege('service_role', %s, 'SELECT')", ('public.' + table,)).fetchone()[0]
    assert db.execute("SELECT to_regclass('public.idx_print_jobs_one_active_order') IS NOT NULL").fetchone()[0]
    assert db.execute("SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='orders_prevent_active_print_job_delete')").fetchone()[0]
    for role in ('anon', 'authenticated'):
        assert not db.execute("SELECT has_function_privilege(%s, 'public.prevent_active_print_job_order_delete()', 'EXECUTE')", (role,)).fetchone()[0]
    assert not db.execute("SELECT prosecdef FROM pg_proc WHERE oid='public.commerce_commit(bigint,jsonb,jsonb,text)'::regprocedure").fetchone()[0]
print('POSTGRES_SCHEMA_AND_PRIVILEGES_OK')
