"""Offline Admin AI A/B regressions. All paid provider calls are mocked."""
import base64
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

import app
import admin_ai_ab_test as ab


def transparent_png(width=96, height=128):
    image = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((10, 12, width - 10, height - 12), fill=(230, 80, 120, 255))
    stream = BytesIO()
    image.save(stream, 'PNG')
    return stream.getvalue()


GOOD = transparent_png()


class AdminAiAbTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stats_path = str(Path(self.temp.name) / 'stats.json')
        self.path_patch = mock.patch.object(ab, '_STATS_FILE', self.stats_path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = app.app.test_client()

    def login(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True

    def post_image(self, filename='fixture.png'):
        return self.client.post('/api/admin/ai-ab-test/run', data={
            'image': (BytesIO(GOOD), filename, 'image/png'),
        })

    def test_admin_auth_guards_page_and_apis(self):
        self.assertEqual(self.client.get('/admin/ai-ab-test').status_code, 302)
        self.assertEqual(self.client.get('/api/admin/ai-ab-test/summary').status_code, 401)
        self.assertEqual(self.post_image().status_code, 401)
        self.assertEqual(self.client.post('/api/admin/ai-ab-test/rate', json={}).status_code, 401)

    def test_ten_visual_scenarios_use_strict_sequential_providers(self):
        self.login()
        scenarios = (
            '人像頭髮', '人像碎髮', '貓毛', '白色商品', '黑色商品',
            '手機', '反光物', '複雜背景', '衣服 Logo', '主體貼邊',
        )
        for scenario in scenarios:
            order = []
            def koukoutu(*_):
                order.append('koukoutu-start')
                order.append('koukoutu-finish')
                return GOOD, 'koukoutu', 'background-removal'
            def runpod(*_):
                order.append('runpod-start')
                order.append('runpod-finish')
                return GOOD, 'runpod', 'ZhengPeng7/BiRefNet'
            with mock.patch.object(ab, '_koukoutu', side_effect=koukoutu), \
                 mock.patch.object(ab, '_runpod', side_effect=runpod), \
                 mock.patch.object(app, 'AI_REMOVE_PROVIDER', 'runpod'):
                response = self.post_image(scenario + '.png')
            self.assertEqual(response.status_code, 200, scenario)
            data = response.get_json()
            self.assertEqual(order, ['koukoutu-start', 'koukoutu-finish', 'runpod-start', 'runpod-finish'])
            self.assertEqual(data['koukoutu']['provider'], 'koukoutu')
            self.assertEqual(data['runpod']['provider'], 'runpod')
            self.assertTrue(data['koukoutu']['valid_alpha'])
            self.assertTrue(data['runpod']['valid_alpha'])
            self.assertNotIn('job_id', json.dumps(data).lower())
            self.assertNotIn('server-only-secret', json.dumps(data))

    def test_failure_is_isolated_without_fallback(self):
        self.login()
        calls = []
        def fail_a(*_):
            calls.append('a')
            raise RuntimeError('vendor secret detail')
        def success_b(*_):
            calls.append('b')
            return GOOD, 'runpod', 'ZhengPeng7/BiRefNet'
        with mock.patch.object(ab, '_koukoutu', side_effect=fail_a), \
             mock.patch.object(ab, '_runpod', side_effect=success_b):
            response = self.post_image()
        data = response.get_json()
        self.assertEqual(calls, ['a', 'b'])
        self.assertFalse(data['koukoutu']['ok'])
        self.assertTrue(data['runpod']['ok'])
        self.assertEqual(data['rating_token'], '')
        self.assertNotIn('vendor secret detail', json.dumps(data))

    def test_direct_koukoutu_general_and_runpod_birefnet_calls(self):
        deadline = ab.time.monotonic() + 10
        with mock.patch.object(app, 'KOUKOUTU_API_KEY', 'server-only-secret'), \
             mock.patch.object(app, 'AI_ENABLED', True), \
             mock.patch('ai_remove_provider.submit', return_value='task-1') as submit, \
             mock.patch('ai_remove_provider.wait', return_value=GOOD) as wait, \
             mock.patch.object(app, '_runpod_submit', return_value=('job-1', {})) as runpod_submit, \
             mock.patch.object(app, '_runpod_wait_for_result', return_value=({'output': {
                 'image_base64': base64.b64encode(GOOD).decode(), 'model': 'ZhengPeng7/BiRefNet',
             }}, False)):
            a = ab._koukoutu(app, GOOD, 'image/png')
            b = ab._runpod(app, GOOD, 'image/png')
        self.assertEqual(submit.call_args.args[3], 'general')
        self.assertEqual(wait.call_args.args[2], 'general')
        self.assertEqual(a[1:], ('koukoutu', 'background-removal'))
        self.assertEqual(b[1:], ('runpod', 'ZhengPeng7/BiRefNet'))
        self.assertEqual(runpod_submit.call_args.args[0]['input']['max_output_edge'], 1800)
        self.assertGreater(deadline, 0)

    def test_rating_is_signed_deduplicated_and_updates_averages(self):
        self.login()
        with mock.patch.object(ab, '_koukoutu', return_value=(GOOD, 'koukoutu', 'background-removal')), \
             mock.patch.object(ab, '_runpod', return_value=(GOOD, 'runpod', 'ZhengPeng7/BiRefNet')):
            run = self.post_image().get_json()
        token = run['rating_token']
        self.assertTrue(token)
        rated = self.client.post('/api/admin/ai-ab-test/rate', json={
            'rating_token': token, 'choice': 'koukoutu',
        })
        self.assertEqual(rated.status_code, 200)
        stats = rated.get_json()['stats']
        self.assertEqual(stats['koukoutu_wins'], 1)
        self.assertEqual(stats['runpod_wins'], 0)
        self.assertEqual(stats['koukoutu_completed'], 1)
        self.assertEqual(stats['runpod_completed'], 1)
        self.assertIsNotNone(stats['koukoutu_average_ms'])
        duplicate = self.client.post('/api/admin/ai-ab-test/rate', json={
            'rating_token': token, 'choice': 'runpod',
        })
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(self.client.post('/api/admin/ai-ab-test/rate', json={
            'rating_token': 'forged', 'choice': 'tie',
        }).status_code, 400)

    def test_browser_assets_never_contain_key_or_renderer(self):
        for path in (Path('admin_ai_ab_test.html'), Path('static/admin-ai-ab-test.js')):
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('KOUKOUTU_API_KEY', text)
            self.assertNotIn('server-only-secret', text)
            self.assertNotIn('playwright', text.lower())
            self.assertNotIn('chromium', text.lower())


if __name__ == '__main__':
    unittest.main(verbosity=2)
