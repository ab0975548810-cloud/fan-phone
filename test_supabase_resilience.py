"""Bounded last-good response cache and PGRST303 full-query isolation."""
import unittest
from types import SimpleNamespace
from unittest import mock

from flask import Flask, Response, jsonify, request

import supabase_resilience as resilience


class ResponseCacheTests(unittest.TestCase):
    def setUp(self):
        self.saved_cache = dict(resilience._LAST_RESPONSE)
        resilience._LAST_RESPONSE.clear()
        self.clock = mock.patch.object(resilience.time, 'monotonic', return_value=1000)
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.restore_cache)
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.fail = False

        @self.app.get('/orders', endpoint='admin_get_orders')
        def orders():
            if self.fail:
                response = jsonify(status='error', msg='PGRST303 JWT issued at future')
                response.status_code = 503
                return response
            return jsonify(status='success', query=request.args.to_dict(flat=False))

        module = SimpleNamespace(app=self.app)
        for name in ('cloud_get_json', 'cloud_get_json_versioned',
                     'cloud_save_json', 'cloud_compare_and_swap_json'):
            setattr(module, name, mock.Mock())
        with mock.patch.object(resilience, '_INSTALLED', False):
            resilience.install(module)
        self.delays = mock.patch.object(resilience, '_RETRY_DELAYS', ())
        self.delays.start()
        self.addCleanup(self.delays.stop)
        self.client = self.app.test_client()

    def restore_cache(self):
        resilience._LAST_RESPONSE.clear()
        resilience._LAST_RESPONSE.update(self.saved_cache)

    def remember(self, query, body='last-good'):
        with self.app.test_request_context('/orders?' + query):
            key = resilience._response_cache_key('admin_get_orders')
            resilience._remember_response(key, Response(body, mimetype='application/json'))
        return key

    def test_expired_read_really_removes_entry(self):
        key = self.remember('q=expired')
        fresh = self.remember('q=fresh')
        resilience._LAST_RESPONSE[key] = (1000 - resilience._STALE_SECONDS - 1,
                                          *resilience._LAST_RESPONSE[key][1:])
        self.assertIsNone(resilience._stale_response(key))
        self.assertNotIn(key, resilience._LAST_RESPONSE)
        self.assertIn(fresh, resilience._LAST_RESPONSE)

    def test_write_cleans_other_expired_entries(self):
        key = self.remember('q=expired')
        self.now.return_value += resilience._STALE_SECONDS + 1
        fresh = self.remember('q=fresh')
        self.assertNotIn(key, resilience._LAST_RESPONSE)
        self.assertEqual(list(resilience._LAST_RESPONSE), [fresh])

    def test_many_distinct_refresh_queries_are_bounded(self):
        for i in range(resilience._MAX_RESPONSE_CACHE * 3):
            self.remember(f'limit=200&offset=0&before={i}&q=query-{i}')
            self.assertLessEqual(len(resilience._LAST_RESPONSE),
                                 resilience._MAX_RESPONSE_CACHE)
        self.assertEqual(len(resilience._LAST_RESPONSE), resilience._MAX_RESPONSE_CACHE)

    def test_oldest_timestamp_evicted_newer_and_rewritten_kept(self):
        keys = []
        for i in range(resilience._MAX_RESPONSE_CACHE):
            self.now.return_value = 1000 + i
            keys.append(self.remember(f'before={i}'))
        self.now.return_value += 1
        self.remember('before=0', 'updated')
        self.now.return_value += 1
        newest = self.remember('before=newest')
        self.assertNotIn(keys[1], resilience._LAST_RESPONSE)
        self.assertIn(keys[0], resilience._LAST_RESPONSE)
        self.assertIn(keys[-1], resilience._LAST_RESPONSE)
        self.assertIn(newest, resilience._LAST_RESPONSE)
        self.assertEqual(len(resilience._LAST_RESPONSE), resilience._MAX_RESPONSE_CACHE)

    def assert_isolated(self, query_a, query_b):
        good = self.client.get('/orders?' + query_a)
        self.assertEqual(good.status_code, 200)
        self.fail = True
        failed = self.client.get('/orders?' + query_b)
        self.assertEqual(failed.status_code, 503)
        self.assertNotIn('X-Benfuwan-Stale', failed.headers)

    def test_query_b_failure_cannot_use_query_a(self):
        self.assert_isolated('q=A', 'q=B')

    def test_page_two_failure_cannot_use_page_one(self):
        self.assert_isolated('limit=200&offset=0&before=123',
                             'limit=200&offset=200&before=123')

    def test_exact_order_b_failure_cannot_use_order_a(self):
        self.assert_isolated('order_id=A', 'order_id=B')

    def test_all_filter_parameters_remain_isolated(self):
        for query_a, query_b in (
            ('status=待處理', 'status=已完成'),
            ('date_from=2026-10-01', 'date_from=2026-10-02'),
            ('date_to=2026-10-01', 'date_to=2026-10-02'),
            ('limit=50', 'limit=200'),
            ('before=123', 'before=124'),
            ('future_filter=A', 'future_filter=B'),
        ):
            with self.subTest(query_b=query_b):
                resilience._LAST_RESPONSE.clear()
                self.fail = False
                self.assert_isolated(query_a, query_b)

    def test_same_full_query_fresh_fallback_still_works(self):
        query = 'q=cat&status=待處理&date_from=2026-10-01&date_to=2026-10-03&order_id=A&limit=200&offset=200&before=123'
        good = self.client.get('/orders?' + query + '&ts=1')
        self.fail = True
        fallback = self.client.get('/orders?' + query + '&ts=2')
        self.assertEqual(fallback.status_code, 200)
        self.assertEqual(fallback.get_json(), good.get_json())
        self.assertEqual(fallback.headers['X-Benfuwan-Stale'], '1')

    def test_concurrent_distinct_writes_remain_bounded(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: self.remember(f'before={i}'),
                          range(resilience._MAX_RESPONSE_CACHE * 3)))
        self.assertEqual(len(resilience._LAST_RESPONSE), resilience._MAX_RESPONSE_CACHE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
