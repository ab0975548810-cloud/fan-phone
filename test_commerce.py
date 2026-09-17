"""Run against SQLite locally and a disposable PostgreSQL database in CI.

The PostgreSQL adapter calls the exact service-role RPC shipped in the migration.
No production database or storage is used.
"""
import copy
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.pop('SUPABASE_URL', None)
os.environ.pop('SUPABASE_SERVICE_ROLE_KEY', None)
import app
import commerce_patch
from commerce_store import Store
from order_color_patch import install as colors
from order_management_patch import install as actions
colors(app)
actions(app)
commerce_patch.install(app)
app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)

PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z7VQAAAAASUVORK5CYII='


class PgStore(Store):
    def connect(self):
        import psycopg
        db = psycopg.connect(os.environ['TEST_POSTGRES_DSN'])
        db.execute('SET ROLE service_role')
        return db

    def read(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM app_store WHERE key='commerce_data'").fetchone()
            return row[0] if row else {}

    def order(self, order_id):
        with self.connect() as db:
            row = db.execute('SELECT to_jsonb(o) FROM orders o WHERE id=%s', (order_id,)).fetchone()
            return row[0] if row else None

    def local_orders(self):
        with self.connect() as db:
            return [row[0] for row in db.execute('SELECT to_jsonb(o) FROM orders o')]

    def commit(self, revision, data, order=None, action=''):
        from psycopg.types.json import Jsonb
        data['revision'] = revision + 1
        with self.connect() as db:
            return db.execute('SELECT commerce_commit(%s,%s,%s,%s)',
                (revision, Jsonb(data), Jsonb(order) if order else None, action)).fetchone()[0]


def configure(folder):
    app.SAVE_DIR = str(Path(folder) / 'orders')
    Path(app.SAVE_DIR).mkdir(exist_ok=True)
    app.DATA_FILE = str(Path(folder) / 'shop.json')
    app.commerce.store = PgStore(app) if os.environ.get('TEST_POSTGRES_DSN') else Store(app)
    app.commerce.store.path = str(Path(folder) / 'commerce.sqlite3')


def worker(folder, payload, barrier, queue):
    configure(folder)
    barrier.wait(timeout=20)
    response = app.app.test_client().post('/api/create_order', json=payload)
    queue.put((response.status_code, response.get_json()))


class CommerceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        configure(self.tmp.name)
        if os.environ.get('TEST_POSTGRES_DSN'):
            import psycopg
            with psycopg.connect(os.environ['TEST_POSTGRES_DSN']) as db:
                db.execute('TRUNCATE orders, app_store')
        self.client = app.app.test_client()
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        self.assertEqual(self.client.post('/api/admin/commerce_sync_skus').status_code, 200)
        data = self.data()
        self.sku_id = data['skus'][0]['id']
        data['skus'][0].update(cost_price=100, stock_qty=5, track_stock=True)
        self.assertEqual(self.save(data).status_code, 200)

    def tearDown(self):
        self.tmp.cleanup()

    def data(self):
        return self.client.get('/api/admin/commerce_data').get_json()['data']

    def save(self, data):
        return self.client.post('/api/admin/save_commerce_data', json=data)

    def stock(self):
        return next(s['stock_qty'] for s in self.data()['skus'] if s['id'] == self.sku_id)

    def payload(self, key='test-checkout-000001'):
        return dict(idempotency_key=key, print_file=PNG, mockup_file=PNG,
                    model_id=app.DEFAULT_SHOP_DATA['models'][0]['id'],
                    style_id=app.DEFAULT_SHOP_DATA['styles'][0]['id'], color_name='透明',
                    quantity=1, customer_name='測試', payment_method='現金', design_json={})

    def create(self, key='test-checkout-000001'):
        return self.client.post('/api/create_order', json=self.payload(key))

    def action(self, order_id, action, key='', **extra):
        return self.client.post('/api/admin/order_action', json=dict(
            order_id=order_id, action=action, idempotency_key=key, **extra))

    def test_replay_and_conflicting_payload(self):
        first = self.create()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.create().get_json(), first.get_json())
        self.assertEqual(self.stock(), 4)
        payload = self.payload(); payload['quantity'] = 2
        self.assertEqual(self.client.post('/api/create_order', json=payload).status_code, 409)
        self.assertEqual(len(app.commerce.store.local_orders()), 1)

    def test_missing_key_is_rejected_before_order_write(self):
        payload = self.payload(); payload.pop('idempotency_key')
        self.assertEqual(self.client.post('/api/create_order', json=payload).status_code, 400)
        self.assertEqual(self.stock(), 5)

    def test_stale_admin_save_and_history(self):
        stale = self.data()
        oid = self.create().get_json()['order_id']
        self.assertEqual(self.save(stale).status_code, 409)
        fresh = self.data(); fresh['skus'][0]['cost_price'] = 200
        self.assertEqual(self.save(fresh).status_code, 200)
        self.assertEqual(self.stock(), 4)
        self.assertEqual(app.commerce.read()['order_finance'][oid]['unit_cost'], 100)

    def test_repeated_void_restore_after_tracking_disabled(self):
        oid = self.create().get_json()['order_id']
        data = self.data(); data['skus'][0]['track_stock'] = False; self.save(data)
        for _ in range(2):
            self.assertEqual(self.action(oid, 'void', 'void-00001').status_code, 200)
        self.assertEqual(self.stock(), 5)
        for _ in range(2):
            self.assertEqual(self.action(oid, 'restore', 'restore-00001').status_code, 200)
        self.assertEqual(self.stock(), 4)
        # Delayed replay of the first void must not reverse a later restore.
        self.action(oid, 'void', 'void-00001')
        self.assertEqual(self.stock(), 4)
        ledger = app.commerce.read()['inventory_ledger']
        self.assertEqual([r['reason'] for r in ledger], ['MANUAL_ADJUST', 'ORDER_CREATED', 'ORDER_VOID', 'ORDER_RESTORED'])
        self.assertEqual(len({r['id'] for r in ledger}), len(ledger))

    def test_insufficient_stock_create_and_restore(self):
        oid = self.create().get_json()['order_id']
        self.action(oid, 'void')
        data = self.data(); data['skus'][0]['stock_qty'] = 0; self.save(data)
        self.assertEqual(self.create('other-checkout-0001').status_code, 409)
        self.assertEqual(self.action(oid, 'restore').status_code, 409)
        self.assertEqual(app.commerce.store.order(oid)['status'], '作廢')
        self.assertEqual(self.stock(), 0)

    def fail_writes(self, enable):
        store = app.commerce.store
        if isinstance(store, PgStore):
            import psycopg
            with psycopg.connect(os.environ['TEST_POSTGRES_DSN']) as db:
                if enable:
                    db.execute("CREATE OR REPLACE FUNCTION fail_commerce_test() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected failure'; END $$")
                    db.execute('CREATE TRIGGER fail_write BEFORE UPDATE ON app_store FOR EACH ROW EXECUTE FUNCTION fail_commerce_test()')
                else:
                    db.execute('DROP TRIGGER fail_write ON app_store')
        else:
            with store.connection() as db:
                db.execute("CREATE TRIGGER fail_write BEFORE UPDATE ON state BEGIN SELECT RAISE(ABORT, 'injected failure'); END" if enable else 'DROP TRIGGER fail_write')
                db.commit()

    def test_database_failure_rolls_back_order_and_finance(self):
        before = app.commerce.read()
        self.fail_writes(True)
        try:
            self.assertGreaterEqual(self.create().status_code, 500)
            self.assertEqual(app.commerce.store.local_orders(), [])
            self.assertEqual(app.commerce.read(), before)
        finally:
            self.fail_writes(False)
        self.assertEqual(self.create().status_code, 200)
        self.assertEqual(self.stock(), 4)

    def test_action_failure_rolls_back_order_status(self):
        oid = self.create().get_json()['order_id']
        before = app.commerce.read()
        self.fail_writes(True)
        try:
            self.assertGreaterEqual(self.action(oid, 'void').status_code, 500)
            self.assertEqual(app.commerce.store.order(oid)['status'], '待處理')
            self.assertEqual(app.commerce.read(), before)
        finally:
            self.fail_writes(False)

    def test_lost_commit_response_is_recoverable(self):
        commit = app.commerce.store.commit
        def lost(*args, **kwargs):
            commit(*args, **kwargs)
            raise TimeoutError('response lost after COMMIT')
        with patch.object(app.commerce.store, 'commit', side_effect=lost):
            self.assertGreaterEqual(self.create().status_code, 500)
        response = self.create()
        self.assertEqual(response.status_code, 200)
        order = app.commerce.store.order(response.get_json()['order_id'])
        self.assertTrue((Path(app.SAVE_DIR) / order['print_path']).exists())
        self.assertEqual(len(app.commerce.store.local_orders()), 1)
        self.assertEqual(self.stock(), 4)

    def parallel(self, same_key):
        data = self.data(); data['skus'][0]['stock_qty'] = 1; self.save(data)
        ctx = multiprocessing.get_context('spawn')
        barrier, queue = ctx.Barrier(2), ctx.Queue()
        processes = [ctx.Process(target=worker, args=(self.tmp.name, self.payload(
            'parallel-checkout-0001' if same_key else f'parallel-checkout-000{i}'), barrier, queue)) for i in range(2)]
        for process in processes: process.start()
        results = [queue.get(timeout=40) for _ in processes]
        for process in processes:
            process.join(20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sorted(r[0] for r in results), [200, 200] if same_key else [200, 409])
        if same_key: self.assertEqual(results[0][1]['order_id'], results[1][1]['order_id'])
        self.assertEqual(self.stock(), 0)
        self.assertEqual(len(app.commerce.store.local_orders()), 1)

    def test_two_processes_last_stock(self): self.parallel(False)
    def test_two_processes_same_request(self): self.parallel(True)

    def test_delete_preserves_audit_and_cannot_double_deduct(self):
        oid = self.create().get_json()['order_id']
        self.assertEqual(self.action(oid, 'delete').status_code, 409)
        self.action(oid, 'void'); self.action(oid, 'delete', 'delete-00001')
        self.assertEqual(self.stock(), 5)
        self.assertIn(oid, app.commerce.read()['order_finance'])
        self.assertEqual(self.create().get_json()['order_id'], oid)
        self.assertEqual(app.commerce.store.local_orders(), [])

    def test_private_data_and_auth(self):
        public = app.app.test_client()
        self.assertEqual(public.get('/api/admin/inventory_ledger').status_code, 401)
        self.assertEqual(public.post('/api/admin/save_commerce_data', json=self.data()).status_code, 401)
        for field in ('cost_price', 'inventory_ledger', 'gross_profit'):
            self.assertNotIn(field, public.get('/api/shop_data').get_data(as_text=True))

    def test_taipei_midnight(self):
        midnight = datetime(2026, 9, 18, tzinfo=ZoneInfo('Asia/Taipei')).timestamp()
        data = dict(order_finance={str(i): dict(status='待處理', revenue=v, cost_known=True, gross_profit=v,
                    created_at_unix=t) for i, (t, v) in enumerate([(midnight-1, 10), (midnight, 20), (midnight+86400, 40)])})
        with patch('commerce_patch.time.time', return_value=midnight+1):
            self.assertEqual(commerce_patch._finance_summary(data)['today_revenue'], 20)


if __name__ == '__main__':
    unittest.main(verbosity=2)
