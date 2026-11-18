"""Production Storage GET retries use the real SDK with an in-memory transport."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx
from storage3 import SyncStorageClient
from storage3.exceptions import StorageApiError

import production_storage
from print_center import PrintError, PrintService


PNG = b'\x89PNG\r\n\x1a\nfixture'
PRIVATE_PATH = 'orders/fixture/sources/private.png'


class ProductionStorageTests(unittest.TestCase):
    def setUp(self):
        self.responses = []
        self.requests = []
        self.seconds = 0.0
        self.clock = mock.patch.object(production_storage.time, 'monotonic', side_effect=lambda: self.seconds)
        self.sleep = mock.patch.object(production_storage.time, 'sleep', side_effect=self.advance)
        self.clock.start(); self.pause = self.sleep.start()
        self.addCleanup(self.clock.stop); self.addCleanup(self.sleep.stop)
        self.http = httpx.Client(transport=httpx.MockTransport(self.respond))
        self.addCleanup(self.http.close)
        storage = SyncStorageClient('https://fixture.invalid/storage/v1/', headers={}, http_client=self.http)
        self.logger = mock.Mock()
        self.app = SimpleNamespace(SUPABASE=SimpleNamespace(storage=storage),
            SUPABASE_PRIVATE_BUCKET='private-fixture', USE_SUPABASE=True,
            app=SimpleNamespace(logger=self.logger))

    def advance(self, amount):
        self.seconds += amount

    def respond(self, request):
        self.requests.append(request)
        result = self.responses.pop(0)
        if callable(result):
            result = result()
        if isinstance(result, Exception):
            raise result
        return result

    def read(self):
        return PrintService._download_artwork(SimpleNamespace(app=self.app), PRIVATE_PATH)

    def test_disconnect_and_timeout_recover_with_three_identical_gets(self):
        self.responses = [httpx.RemoteProtocolError('private URL https://secret.invalid/token'),
                          httpx.ReadTimeout('private path and service-role token'),
                          httpx.Response(200, content=PNG)]
        self.assertEqual(self.read(), PNG)
        self.assertEqual(len(self.requests), 3)
        self.assertEqual({r.method for r in self.requests}, {'GET'})
        self.assertEqual({r.url.path for r in self.requests}, {'/storage/v1/object/private-fixture/' + PRIVATE_PATH})
        self.assertEqual(self.pause.call_args_list, [mock.call(.2), mock.call(.4)])
        logs = str(self.logger.warning.call_args_list)
        self.assertIn('RemoteProtocolError', logs)
        self.assertNotIn('secret.invalid', logs)
        self.assertNotIn('private.png', logs)
        self.assertNotIn('service-role', logs)

    def test_success_does_not_retry(self):
        self.responses = [httpx.Response(200, content=PNG)]
        self.assertEqual(self.read(), PNG)
        self.assertEqual(len(self.requests), 1)
        self.pause.assert_not_called()

    def test_exhaustion_keeps_last_transport_exception(self):
        failures = [httpx.ConnectError('offline') for _ in range(3)]
        self.responses = list(failures)
        with self.assertRaises(httpx.ConnectError) as raised:
            self.read()
        self.assertIs(raised.exception, failures[-1])
        self.assertEqual(len(self.requests), 3)

    def test_retry_deadline_reserves_sdk_window_and_stops(self):
        def stalled():
            self.advance(20)
            return httpx.ReadTimeout('fixture stalled')
        self.responses = [stalled, stalled, httpx.Response(200, content=PNG)]
        with self.assertRaises(httpx.ReadTimeout):
            self.read()
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.pause.call_args_list, [mock.call(.2)])
        self.assertLessEqual(self.seconds, 60)

    def test_http_rejections_are_not_transport_retries(self):
        for status in (400, 401, 403, 404, 422, 500):
            with self.subTest(status=status):
                self.requests.clear()
                self.responses = [httpx.Response(status, json={
                    'message':'fixture denied', 'error':'fixture', 'statusCode':status})]
                with self.assertRaises(StorageApiError):
                    self.read()
                self.assertEqual(len(self.requests), 1)
        self.pause.assert_not_called()

    def test_decoding_failure_is_not_retried(self):
        error = httpx.DecodingError('fixture invalid content encoding')
        self.responses = [error]
        with self.assertRaises(httpx.DecodingError) as raised:
            self.read()
        self.assertIs(raised.exception, error)
        self.assertEqual(len(self.requests), 1)
        self.pause.assert_not_called()

    def test_invalid_png_remains_blocked_without_retry(self):
        self.responses = [httpx.Response(200, content=b'<html>not artwork</html>')]
        with self.assertRaises(PrintError) as raised:
            self.read()
        self.assertEqual(raised.exception.code, 'PRINT_FILE_INVALID')
        self.assertEqual(len(self.requests), 1)
        self.pause.assert_not_called()

    def test_local_read_and_missing_file_stay_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            self.app.USE_SUPABASE = False
            self.app.SAVE_DIR = directory
            Path(directory, 'fixture.png').write_bytes(PNG)
            service = SimpleNamespace(app=self.app)
            self.assertEqual(PrintService._download_artwork(service, 'fixture.png'), PNG)
            with self.assertRaises(PrintError) as raised:
                PrintService._download_artwork(service, 'missing.png')
            self.assertEqual(raised.exception.code, 'PRINT_FILE_MISSING')
        self.assertEqual(self.requests, [])
        self.pause.assert_not_called()


if __name__ == '__main__':
    unittest.main()
