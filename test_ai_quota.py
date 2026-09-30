"""Application regressions for privacy-safe RunPod quota lifecycle handling."""

import base64
from io import BytesIO
import unittest
from unittest import mock

import requests

import ai_quota
import app
import ai_runtime_patch
import security_perf


security_perf.install(app)
ai_runtime_patch.install(app)

PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+'
    '3MxZ5wAAAABJRU5ErkJggg=='
)


class FakeQuota:
    def __init__(self):
        self.events = []
        self.reserve_error = None
        self.mark_error = None
        self.finish_error = None

    def reserve(self, client_id, ip_address):
        self.events.append(('reserve', client_id, ip_address))
        if self.reserve_error:
            raise self.reserve_error
        return ai_quota.AiQuotaReservation('00000000-0000-0000-0000-000000000001')

    def mark_submitted(self, reservation, job_id):
        self.events.append(('submitted', reservation.request_id, job_id))
        if self.mark_error:
            raise self.mark_error

    def release(self, reservation):
        self.events.append(('released', reservation.request_id))

    def finish(self, reservation, state):
        self.events.append(('finished', reservation.request_id, state))
        if self.finish_error:
            raise self.finish_error

    def diagnostics(self):
        return {
            'client_limit_24h': 5,
            'ip_limit_24h': 15,
            'global_limit_24h': 60,
            'active_limit': 2,
            'global_used_24h': 7,
            'active_now': 1,
        }


class FakeRpcResult:
    def __init__(self, data):
        self.data = data

    def execute(self):
        return self


class FakeSupabase:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def rpc(self, name, params):
        self.calls.append((name, params))
        return FakeRpcResult(self.data)


class AiQuotaTests(unittest.TestCase):
    def setUp(self):
        app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = app.app.test_client()
        self.quota = FakeQuota()
        security_perf._HITS.clear()
        security_perf._AI_ACTIVE = 0

    def _post(self):
        return self.client.post(
            '/api/ai/remove-background',
            data={'image': (BytesIO(PNG), 'input.png')},
            content_type='multipart/form-data',
            headers={'X-Forwarded-For': '203.0.113.9'},
        )

    def _patch_route(self):
        output = {'output': {'image_base64': base64.b64encode(PNG).decode(), 'model': 'test'}}
        return mock.patch.multiple(
            app,
            AI_ENABLED=True,
            AI_QUOTA=self.quota,
            _runpod_submit=mock.DEFAULT,
            _runpod_wait_for_result=mock.DEFAULT,
        ), output

    def test_hmac_identity_is_all_the_database_receives(self):
        database = FakeSupabase({'reserved': True, 'code': 'OK'})
        quota = ai_quota.PersistentAiQuota(lambda: database, lambda: 'stable-test-secret')
        quota.reserve('raw-session-client', '198.51.100.42')
        name, params = database.calls[0]
        self.assertEqual(name, 'reserve_ai_usage')
        self.assertRegex(params['p_client_hash'], r'^[0-9a-f]{64}$')
        self.assertRegex(params['p_ip_hash'], r'^[0-9a-f]{64}$')
        self.assertNotIn('raw-session-client', repr(params))
        self.assertNotIn('198.51.100.42', repr(params))

    def test_unstable_or_missing_secret_fails_closed(self):
        database = FakeSupabase({'reserved': True, 'code': 'OK'})
        quota = ai_quota.PersistentAiQuota(lambda: database, lambda: '')
        with self.assertRaises(ai_quota.AiQuotaUnavailable):
            quota.reserve('client', 'ip')
        self.assertEqual(database.calls, [])

    def test_success_records_submitted_then_completed(self):
        patches, output = self._patch_route()
        with patches as values:
            values['_runpod_submit'].return_value = ('runpod-job-1', {})
            values['_runpod_wait_for_result'].return_value = (output, False)
            response = self._post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, PNG)
        self.assertEqual([event[0] for event in self.quota.events], ['reserve', 'submitted', 'finished'])
        self.assertEqual(self.quota.events[-1][-1], 'COMPLETED')

    def test_each_persistent_limit_rejects_before_runpod(self):
        cases = {
            'AI_DEVICE_DAILY_LIMIT': '今天的雲端 AI 去背額度已用完',
            'AI_IP_DAILY_LIMIT': '此網路今天的雲端 AI 使用量已達上限',
            'AI_GLOBAL_DAILY_LIMIT': '今日雲端 AI 使用量已達安全上限',
            'AI_BUSY': 'AI 正在處理其他圖片',
        }
        for code, message in cases.items():
            with self.subTest(code=code):
                self.quota.events.clear()
                self.quota.reserve_error = ai_quota.AiQuotaRejected(code)
                with mock.patch.object(app, 'AI_ENABLED', True), \
                     mock.patch.object(app, 'AI_QUOTA', self.quota), \
                     mock.patch.object(app, '_runpod_submit') as submit:
                    response = self._post()
                self.assertEqual(response.status_code, 429)
                self.assertEqual(response.get_json()['code'], code)
                self.assertIn(message, response.get_json()['msg'])
                submit.assert_not_called()
        self.quota.reserve_error = None

    def test_quota_database_unavailable_never_calls_runpod(self):
        self.quota.reserve_error = ai_quota.AiQuotaUnavailable('database down')
        with mock.patch.object(app, 'AI_ENABLED', True), \
             mock.patch.object(app, 'AI_QUOTA', self.quota), \
             mock.patch.object(app, '_runpod_submit') as submit:
            response = self._post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['code'], 'AI_QUOTA_UNAVAILABLE')
        self.assertIn('配額服務', response.get_json()['msg'])
        submit.assert_not_called()

    def test_submit_failure_releases_uncounted_reservation(self):
        with mock.patch.object(app, 'AI_ENABLED', True), \
             mock.patch.object(app, 'AI_QUOTA', self.quota), \
             mock.patch.object(app, '_runpod_submit', side_effect=requests.ConnectionError('offline')):
            response = self._post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()['code'], 'AI_NETWORK_ERROR')
        self.assertEqual([event[0] for event in self.quota.events], ['reserve', 'released'])

    def test_mark_submitted_failure_cancels_provider_and_fails_closed(self):
        self.quota.mark_error = ai_quota.AiQuotaUnavailable('write failed')
        with mock.patch.object(app, 'AI_ENABLED', True), \
             mock.patch.object(app, 'AI_QUOTA', self.quota), \
             mock.patch.object(app, '_runpod_submit', return_value=('runpod-job-2', {})), \
             mock.patch.object(app, '_runpod_cancel') as cancel, \
             mock.patch.object(app, '_runpod_wait_for_result') as wait:
            response = self._post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['code'], 'AI_QUOTA_UNAVAILABLE')
        cancel.assert_called_once_with('runpod-job-2')
        wait.assert_not_called()

    def test_worker_failure_remains_counted_and_is_finished_failed(self):
        with mock.patch.object(app, 'AI_ENABLED', True), \
             mock.patch.object(app, 'AI_QUOTA', self.quota), \
             mock.patch.object(app, '_runpod_submit', return_value=('runpod-job-3', {})), \
             mock.patch.object(app, '_runpod_wait_for_result', side_effect=RuntimeError('worker failed')):
            response = self._post()
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()['code'], 'AI_JOB_ERROR')
        self.assertEqual(self.quota.events[-1][-1], 'FAILED')

    def test_final_ledger_write_failure_fails_closed(self):
        self.quota.finish_error = ai_quota.AiQuotaUnavailable('finish write failed')
        output = {'output': {'image_base64': base64.b64encode(PNG).decode(), 'model': 'test'}}
        with mock.patch.object(app, 'AI_ENABLED', True), \
             mock.patch.object(app, 'AI_QUOTA', self.quota), \
             mock.patch.object(app, '_runpod_submit', return_value=('runpod-job-4', {})), \
             mock.patch.object(app, '_runpod_wait_for_result', return_value=(output, False)), \
             mock.patch.object(app, '_runpod_cancel') as cancel:
            response = self._post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()['code'], 'AI_QUOTA_UNAVAILABLE')
        cancel.assert_called_once_with('runpod-job-4')

    def test_invalid_image_never_reserves(self):
        with mock.patch.object(app, 'AI_ENABLED', True), mock.patch.object(app, 'AI_QUOTA', self.quota):
            response = self.client.post(
                '/api/ai/remove-background',
                data={'image': (BytesIO(b'not-an-image'), 'input.png')},
                content_type='multipart/form-data',
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.quota.events, [])

    def test_admin_diagnose_includes_minimal_quota_snapshot(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        with mock.patch.object(app, 'AI_QUOTA', self.quota):
            response = self.client.get('/api/admin/ai_remove_diagnose')
        self.assertEqual(response.status_code, 503)
        snapshot = response.get_json()['ai_quota']
        self.assertEqual(snapshot, self.quota.diagnostics())


if __name__ == '__main__':
    unittest.main(verbosity=2)
