"""Catalog/template optimistic concurrency tests. Never connects to production."""
import copy
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import app
import commerce_patch

commerce_patch.install(app)


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, store):
        self.store = store
        self.operation = 'select'
        self.payload = None
        self.filters = []

    def select(self, _columns):
        return self

    def update(self, payload):
        self.operation = 'update'
        self.payload = copy.deepcopy(payload)
        return self

    def insert(self, payload):
        self.operation = 'insert'
        self.payload = copy.deepcopy(payload)
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def limit(self, _count):
        return self

    def execute(self):
        with self.store.lock:
            if self.operation == 'insert':
                key = self.payload['key']
                if key in self.store.rows:
                    raise RuntimeError('duplicate key')
                self.store.rows[key] = {**self.payload, 'updated_at': 'seed-version'}
                return _Result([copy.deepcopy(self.store.rows[key])])
            row = next((value for value in self.store.rows.values()
                        if all(value.get(column) == expected for column, expected in self.filters)), None)
            if self.operation == 'update':
                if row is None:
                    return _Result([])
                row.update(copy.deepcopy(self.payload))
                return _Result([{'updated_at': row['updated_at']}])
            return _Result([copy.deepcopy(row)] if row is not None else [])


class _FakeSupabase:
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)
        self.lock = threading.Lock()

    def table(self, name):
        if name != 'app_store':
            raise AssertionError(name)
        return _FakeQuery(self)


class CatalogConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.old = (app.USE_SUPABASE, app.SUPABASE, app.DATA_FILE, app.TEMPLATES_FILE)
        app.USE_SUPABASE = False
        app.SUPABASE = None
        app.DATA_FILE = str(root / 'shop.json')
        app.TEMPLATES_FILE = str(root / 'templates.json')
        app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.a = app.app.test_client()
        self.b = app.app.test_client()
        for client in (self.a, self.b):
            with client.session_transaction() as session:
                session['logged_in'] = True

    def tearDown(self):
        app.USE_SUPABASE, app.SUPABASE, app.DATA_FILE, app.TEMPLATES_FILE = self.old
        self.tmp.cleanup()

    def test_local_catalog_and_template_stale_writes_are_rejected(self):
        first_a = self.a.get('/api/shop_data').get_json()
        first_b = self.b.get('/api/shop_data').get_json()
        self.assertEqual(first_a['version'], first_b['version'])
        data_a = copy.deepcopy(first_a['data'])
        data_a['brands'].append('分頁 A')
        saved_a = self.a.post('/api/admin/save_shop_data', json={
            'data': data_a, 'expected_version': first_a['version'],
        })
        self.assertEqual(saved_a.status_code, 200, saved_a.get_data(as_text=True))
        version_2 = saved_a.get_json()['version']
        self.assertNotEqual(version_2, first_a['version'])

        data_b = copy.deepcopy(first_b['data'])
        data_b['brands'].append('分頁 B')
        stale = self.b.post('/api/admin/save_shop_data', json={
            'data': data_b, 'expected_version': first_b['version'],
        })
        self.assertEqual((stale.status_code, stale.get_json()['code']), (409, 'STALE_DATA'))
        current = self.b.get('/api/shop_data').get_json()
        self.assertIn('分頁 A', current['data']['brands'])
        self.assertNotIn('分頁 B', current['data']['brands'])
        self.assertEqual(current['version'], version_2)

        data_b = copy.deepcopy(current['data'])
        data_b['brands'].append('分頁 B')
        saved_b = self.b.post('/api/admin/save_shop_data', json={
            'data': data_b, 'expected_version': current['version'],
        })
        self.assertEqual(saved_b.status_code, 200, saved_b.get_data(as_text=True))
        self.assertNotEqual(saved_b.get_json()['version'], version_2)

        templates_a = self.a.get('/api/templates').get_json()
        templates_b = self.b.get('/api/templates').get_json()
        data = copy.deepcopy(templates_a['data'])
        data['templates'].append({'id':'a','name':'模板 A'})
        saved = self.a.post('/api/admin/save_templates', json={
            'data': data, 'expected_version': templates_a['version'],
        })
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        stale_data = copy.deepcopy(templates_b['data'])
        stale_data['templates'].append({'id':'b','name':'模板 B'})
        stale = self.b.post('/api/admin/save_templates', json={
            'data': stale_data, 'expected_version': templates_b['version'],
        })
        self.assertEqual((stale.status_code, stale.get_json()['code']), (409, 'STALE_DATA'))
        current = self.b.get('/api/templates').get_json()
        self.assertEqual([row['id'] for row in current['data']['templates']], ['a'])

    def test_missing_version_fails_closed(self):
        response = self.a.post('/api/admin/save_shop_data', json=app.DEFAULT_SHOP_DATA)
        self.assertEqual((response.status_code, response.get_json()['code']), (409, 'STALE_DATA'))
        response = self.a.post('/api/admin/save_templates', json=app.DEFAULT_TEMPLATES)
        self.assertEqual((response.status_code, response.get_json()['code']), (409, 'STALE_DATA'))

    def test_commerce_sale_price_cannot_bypass_catalog_version(self):
        first = self.a.get('/api/shop_data').get_json()
        stale_version = first['version']
        changed = copy.deepcopy(first['data'])
        changed['brands'].append('其他分頁更新')
        saved = self.a.post('/api/admin/save_shop_data', json={
            'data': changed, 'expected_version': stale_version,
        })
        self.assertEqual(saved.status_code, 200, saved.get_data(as_text=True))
        style = first['data']['styles'][0]
        stale = self.b.post('/api/admin/commerce_set_style_price', json={
            'style_id': style['id'], 'price': 777, 'expected_version': stale_version,
        })
        self.assertEqual((stale.status_code, stale.get_json()['code']), (409, 'STALE_DATA'))
        current = self.b.get('/api/shop_data').get_json()
        current_style = next(row for row in current['data']['styles'] if row['id'] == style['id'])
        self.assertNotEqual(current_style['price'], 777)
        success = self.b.post('/api/admin/commerce_set_style_price', json={
            'style_id': style['id'], 'price': 777, 'expected_version': current['version'],
        })
        self.assertEqual(success.status_code, 200, success.get_data(as_text=True))
        self.assertNotEqual(success.get_json()['version'], current['version'])

    def test_supabase_conditional_update_has_one_winner(self):
        fake = _FakeSupabase({'shop_data': {
            'key':'shop_data', 'value':copy.deepcopy(app.DEFAULT_SHOP_DATA), 'updated_at':'version-1',
        }})
        with mock.patch.object(app, 'USE_SUPABASE', True), mock.patch.object(app, 'SUPABASE', fake):
            data, version = app.cloud_get_json_versioned('shop_data', app.DATA_FILE, app.DEFAULT_SHOP_DATA)
            self.assertEqual(version, 'version-1')
            one = copy.deepcopy(data); one['brands'].append('一')
            two = copy.deepcopy(data); two['brands'].append('二')
            def save(candidate):
                try:
                    return ('saved', app.cloud_compare_and_swap_json('shop_data', app.DATA_FILE, candidate, version))
                except app.StaleDataError:
                    return ('stale', None)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(save, (one, two)))
            self.assertEqual(sorted(result[0] for result in results), ['saved', 'stale'])
            brands = fake.rows['shop_data']['value']['brands']
            self.assertEqual(('一' in brands) + ('二' in brands), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
