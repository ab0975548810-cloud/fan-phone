"""Atomic commerce commits. Supabase RPC in production; SQLite for local use.

The revision belongs to the database, never a process lock or a cached read.
An order write and its entire finance/inventory change commit together.
"""
import json
import os
import sqlite3
from contextlib import contextmanager


class CommerceError(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


class Store:
    def __init__(self, app):
        self.app = app
        self.path = os.environ.get('COMMERCE_DB_PATH', 'commerce.sqlite3')

    @contextmanager
    def connection(self):
        # Local files require an explicitly acknowledged durable volume in prod.
        if os.environ.get('BENFUWAN_PRODUCTION') == '1' and not os.environ.get('COMMERCE_DURABLE_LOCAL') == '1':
            raise RuntimeError('Production commerce requires Supabase or an acknowledged durable local volume')
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute('PRAGMA synchronous=FULL')
            db.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT 1 FROM state WHERE id=1').fetchone():
                raw = {}
                if os.path.exists('commerce_data.json'):
                    with open('commerce_data.json', encoding='utf-8') as f:
                        raw = json.load(f)
                # One-time import; original files remain as a backup, never read again.
                for name in os.listdir(self.app.SAVE_DIR):
                    if name.endswith('_info.json'):
                        with open(os.path.join(self.app.SAVE_DIR, name), encoding='utf-8') as f:
                            row = json.load(f)
                        row.update(id=row['order_id'], model_name=row.get('model'), style_name=row.get('style'),
                                   unit_price=row.get('price'), created_at_unix=row.get('time'))
                        for field, url in [('print_path', 'print_url'), ('mockup_path', 'mockup_url')]:
                            row[field] = str(row.get(url) or '').removeprefix('/orders/')
                        db.execute('INSERT INTO orders VALUES (?,?)', (row['id'], json.dumps(row)))
                db.execute('INSERT INTO state VALUES (1,?)', (json.dumps(raw),))
            db.commit()
            yield db
        finally:
            db.close()

    def read(self):
        if self.app.USE_SUPABASE:
            rows = self.app.SUPABASE.table('app_store').select('value').eq('key', 'commerce_data').limit(1).execute().data
            return rows[0]['value'] if rows else {}
        with self.connection() as db:
            return json.loads(db.execute('SELECT value FROM state WHERE id=1').fetchone()[0])

    def order(self, order_id):
        if self.app.USE_SUPABASE:
            rows = self.app.SUPABASE.table('orders').select('*').eq('id', order_id).limit(1).execute().data
            return rows[0] if rows else None
        with self.connection() as db:
            row = db.execute('SELECT value FROM orders WHERE id=?', (order_id,)).fetchone()
            return json.loads(row[0]) if row else None

    def local_orders(self):
        with self.connection() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT value FROM orders')]

    def orders_between(self, start, end):
        if not self.app.USE_SUPABASE:
            return [r for r in self.local_orders() if start <= int(r.get('created_at_unix') or 0) < end]
        rows, offset = [], 0
        while True:
            batch = (self.app.SUPABASE.table('orders')
                     .select('id,style_id,style_name,total,quantity,status,created_at_unix')
                     .gte('created_at_unix', start).lt('created_at_unix', end)
                     .order('id').range(offset, offset + 499).execute().data or [])
            rows.extend(batch)
            if len(batch) < 500:
                return rows
            offset += 500

    def commit(self, revision, data, order=None, action=''):
        data['revision'] = revision + 1
        if self.app.USE_SUPABASE:
            return self.app.SUPABASE.rpc('commerce_commit', {
                'p_revision': revision, 'p_data': data, 'p_order': order, 'p_action': action,
            }).execute().data is True
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = json.loads(db.execute('SELECT value FROM state WHERE id=1').fetchone()[0])
            if int(current.get('revision', 0)) != revision:
                return False
            if action == 'create':
                db.execute('INSERT INTO orders VALUES (?,?)', (order['id'], json.dumps(order)))
            elif action in ('status', 'delete'):
                old = db.execute('SELECT value FROM orders WHERE id=?', (order['id'],)).fetchone()
                if not old:
                    raise CommerceError('ORDER_NOT_FOUND', '找不到這筆訂單', 404)
                if action == 'delete':
                    db.execute('DELETE FROM orders WHERE id=?', (order['id'],))
                else:
                    row = json.loads(old[0])
                    row['status'] = order['status']
                    db.execute('UPDATE orders SET value=? WHERE id=?', (json.dumps(row), order['id']))
            db.execute('UPDATE state SET value=? WHERE id=1', (json.dumps(data),))
            db.commit()
            return True
