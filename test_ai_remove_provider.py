"""Offline provider/ledger regressions. No vendor or production DB calls."""
import base64
from io import BytesIO
import os
import unittest
from unittest import mock

from PIL import Image, ImageDraw
import requests
import app
import ai_remove_provider as provider
from ai_quota import AiQuotaUnavailable
from test_ai_quota import FakeQuota
import security_perf


def png(transparent=True):
    image = Image.new('RGBA', (64, 96), (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
    ImageDraw.Draw(image).rectangle((12, 10, 50, 80), fill=(200, 50, 90, 255))
    stream = BytesIO(); image.save(stream, 'PNG'); return stream.getvalue()


GOOD, OPAQUE = png(), png(False)


class ProviderTests(unittest.TestCase):
    def setUp(self):
        app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = app.app.test_client(); self.quota = FakeQuota()
        security_perf._HITS.clear(); security_perf._AI_ACTIVE = 0
        self.patch = mock.patch.multiple(app, AI_REMOVE_PROVIDER='koukoutu', KOUKOUTU_API_KEY='server-only-test-key', AI_ENABLED=True, AI_QUOTA=self.quota)
        self.patch.start(); self.addCleanup(self.patch.stop)

    def post(self, mode='general', raw=OPAQUE):
        data = {'image': (BytesIO(raw), 'photo.png')}
        if mode is not None: data['mode'] = mode
        return self.client.post('/api/ai/remove-background', data=data)

    def runpod_result(self):
        return ({'output': {'image_base64': base64.b64encode(GOOD).decode()}}, False)

    def test_model_keys_and_private_multipart_png_no_crop(self):
        for mode, model in provider.MODELS.items():
            response = mock.Mock(status_code=200)
            response.json.return_value = {'code': 200, 'data': {'task_id': 42}}
            with mock.patch.object(app.requests, 'post', return_value=response) as post:
                self.assertEqual(provider.submit(app, OPAQUE, 'image/png', mode, provider.time.monotonic()+10), '42')
            kwargs = post.call_args.kwargs
            self.assertEqual(kwargs['data'], dict(model_key=model, output_format='png', crop='0', border='0', stamp_crop='0'))
            self.assertEqual(kwargs['headers'], {'X-API-Key': 'server-only-test-key'})
            self.assertEqual(kwargs['files']['image_file'][1], OPAQUE)

    def test_query_running_then_success_and_download(self):
        responses = [mock.Mock(status_code=200), mock.Mock(status_code=200)]
        responses[0].json.return_value = {'code':200,'data':{'state':0}}
        responses[1].json.return_value = {'code':200,'data':{'state':1,'result_file':'https://img.koukoutu.com/result.png'}}
        with mock.patch.object(app.requests,'post',side_effect=responses) as query, mock.patch.object(provider,'download',return_value=GOOD) as download, mock.patch.object(provider.time,'sleep'):
            self.assertEqual(provider.wait(app,'42','stamp',provider.time.monotonic()+10),GOOD)
        self.assertEqual(query.call_args.kwargs['data'], {'task_id':'42','response':'url'})
        download.assert_called_once()

    def test_general_default_and_stamp_headers_and_single_count(self):
        for mode in (None, 'stamp'):
            self.quota.events.clear()
            with mock.patch.object(provider,'submit',return_value='42'), mock.patch.object(provider,'wait',return_value=GOOD):
                response = self.post(mode)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['X-AI-Provider'],'koukoutu')
            self.assertEqual(response.headers['X-AI-Model'],provider.MODELS[mode or 'general'])
            self.assertEqual([e[0] for e in self.quota.events],['reserve','submitted','finished'])
            self.assertEqual(self.quota.events[1][-1],'koukoutu:42')

    def test_timeout_5xx_malformed_before_submit_release(self):
        bad_responses = [mock.Mock(status_code=503),mock.Mock(status_code=200)]
        bad_responses[1].json.return_value = {'code':200,'data':{}}
        for failure in [requests.Timeout(),*bad_responses]:
            self.quota.events.clear()
            with mock.patch.object(app.requests,'post',side_effect=failure if isinstance(failure,Exception) else None,return_value=failure):
                response=self.post()
            self.assertIn(response.status_code,(502,504))
            self.assertEqual([e[0] for e in self.quota.events],['reserve','released'])

    def test_opaque_and_invalid_output_remain_counted(self):
        for output in (OPAQUE,b'bad png'):
            self.quota.events.clear()
            with mock.patch.object(provider,'submit',return_value='42'),mock.patch.object(provider,'wait',return_value=output):
                response=self.post()
            self.assertEqual(response.status_code,502)
            self.assertEqual(self.quota.events[-1][-1],'FAILED')

    def test_auto_fallback_after_accepted_job_counts_once(self):
        with mock.patch.object(app,'AI_REMOVE_PROVIDER','auto'),mock.patch.object(provider,'submit',return_value='42'),mock.patch.object(provider,'wait',side_effect=RuntimeError('failed')),mock.patch.object(app,'_runpod_submit',return_value=('rp-1',{})),mock.patch.object(app,'_runpod_wait_for_result',return_value=self.runpod_result()):
            response=self.post('stamp')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['X-AI-Provider'],'runpod')
        self.assertEqual([e[0] for e in self.quota.events],['reserve','submitted','finished'])
        self.assertEqual(self.quota.events[1][-1],'koukoutu:42')

    def test_auto_general_success_never_starts_runpod(self):
        with mock.patch.object(app,'AI_REMOVE_PROVIDER','auto'),mock.patch.object(provider,'submit',return_value='42') as submit,mock.patch.object(provider,'wait',return_value=GOOD),mock.patch.object(app,'_runpod_submit') as fallback:
            response=self.post('general')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.headers['X-AI-Provider'],'koukoutu')
        self.assertEqual(submit.call_args.args[3],'general')
        fallback.assert_not_called()
        self.assertEqual([e[0] for e in self.quota.events],['reserve','submitted','finished'])

    def test_auto_general_technical_failures_fallback_with_one_reservation(self):
        for failure in (requests.Timeout(),requests.HTTPError('HTTP 503'),b'invalid PNG',OPAQUE):
            with self.subTest(failure=type(failure).__name__):
                self.quota.events.clear()
                with mock.patch.object(app,'AI_REMOVE_PROVIDER','auto'),mock.patch.object(provider,'submit',return_value='42'),mock.patch.object(provider,'wait',side_effect=failure if isinstance(failure,Exception) else None,return_value=failure),mock.patch.object(app,'_runpod_submit',return_value=('rp-1',{})) as fallback,mock.patch.object(app,'_runpod_wait_for_result',return_value=self.runpod_result()):
                    response=self.post('general')
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.headers['X-AI-Provider'],'runpod')
                fallback.assert_called_once()
                self.assertEqual([e[0] for e in self.quota.events],['reserve','submitted','finished'])

    def test_auto_general_both_providers_fail_count_once(self):
        with mock.patch.object(app,'AI_REMOVE_PROVIDER','auto'),mock.patch.object(provider,'submit',return_value='42'),mock.patch.object(provider,'wait',side_effect=requests.Timeout()),mock.patch.object(app,'_runpod_submit',side_effect=RuntimeError('RunPod unavailable')):
            response=self.post('general')
        self.assertGreaterEqual(response.status_code,500)
        self.assertEqual([e[0] for e in self.quota.events],['reserve','submitted','finished'])
        self.assertEqual(self.quota.events[-1][-1],'FAILED')

    def test_auto_fallback_before_accepted_job_counts_runpod_once(self):
        with mock.patch.object(app,'AI_REMOVE_PROVIDER','auto'),mock.patch.object(provider,'submit',side_effect=requests.Timeout()),mock.patch.object(app,'_runpod_submit',return_value=('rp-1',{})),mock.patch.object(app,'_runpod_wait_for_result',return_value=self.runpod_result()):
            response=self.post()
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.quota.events[1][-1],'rp-1')
        self.assertEqual(sum(e[0]=='submitted' for e in self.quota.events),1)

    def test_quota_failure_never_calls_vendor(self):
        self.quota.reserve_error=AiQuotaUnavailable('offline')
        with mock.patch.object(provider,'submit') as submit, mock.patch.object(app,'_runpod_submit') as fallback:
            response=self.post()
        self.assertEqual(response.status_code,503);submit.assert_not_called();fallback.assert_not_called()

    def test_mark_failure_stops_poll_and_auto_fallback(self):
        self.quota.mark_error=AiQuotaUnavailable('offline')
        with mock.patch.object(app,'AI_REMOVE_PROVIDER','auto'),mock.patch.object(provider,'submit',return_value='42'),mock.patch.object(provider,'wait') as wait,mock.patch.object(app,'_runpod_submit') as fallback:
            response=self.post()
        self.assertEqual(response.status_code,503);wait.assert_not_called();fallback.assert_not_called()
        self.assertFalse(any(e[0]=='released' for e in self.quota.events))

    def test_default_runpod_with_key_present_stays_runpod(self):
        with mock.patch.object(app,'AI_REMOVE_PROVIDER','runpod'),mock.patch.object(provider,'submit') as submit,mock.patch.object(app,'_runpod_submit',return_value=('rp-1',{})),mock.patch.object(app,'_runpod_wait_for_result',return_value=self.runpod_result()):
            response=self.post(None)
        self.assertEqual(response.status_code,200);submit.assert_not_called()

    def test_no_key_auto_still_uses_runpod(self):
        with mock.patch.object(app,'AI_REMOVE_PROVIDER','auto'),mock.patch.object(app,'KOUKOUTU_API_KEY',''),mock.patch.object(app,'_runpod_submit',return_value=('rp-1',{})),mock.patch.object(app,'_runpod_wait_for_result',return_value=self.runpod_result()):
            response=self.post()
        self.assertEqual(response.status_code,200)

    def test_invalid_mode_and_input_never_reserve(self):
        self.assertEqual(self.post('private-api').status_code,400)
        self.assertEqual(self.post(raw=b'\x89PNG\r\n\x1a\ninvalid').status_code,400)
        self.assertEqual(self.quota.events,[])

    def test_result_download_rejects_private_and_redirect_targets(self):
        for url in ('http://img.koukoutu.com/a','https://127.0.0.1/a','https://169.254.169.254/a'):
            with self.assertRaises(RuntimeError):provider._public_url(url)

    def test_key_never_in_browser_files_or_health(self):
        from pathlib import Path
        for path in [Path('index.html'),*Path('static').glob('*.js')]:
            self.assertNotIn('KOUKOUTU_API_KEY',path.read_text(encoding='utf-8'))
            self.assertNotIn('server-only-test-key',path.read_text(encoding='utf-8'))
        self.assertNotIn('server-only-test-key',self.client.get('/api/health').get_data(as_text=True))


if __name__ == '__main__':unittest.main(verbosity=2)
