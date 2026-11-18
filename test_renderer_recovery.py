"""Renderer stages are observable without disclosing private design data or sending print jobs."""
import base64
import copy
import hashlib
import io
import json
import math
import os
import subprocess
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

from PIL import Image
import editable_stickers as editable
import test_editable_stickers as fixture_module


class RendererRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.EditableTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.app = fixture_module.app
        self.order = self.app.commerce.store.order(self.fixture.create())
        self.profile = self.app.print_center.store.profile(self.fixture.fixture.sku_id)
        self.before_order = copy.deepcopy(self.order)
        self.before_commerce = copy.deepcopy(self.app.commerce.read())
        self.expected_vendor_paths = []
        self.warning = mock.patch.object(self.app.app.logger, 'warning').start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        self.assertEqual(self.app.commerce.store.order(self.order['id']), self.before_order)
        self.assertEqual(self.app.commerce.read(), self.before_commerce)
        self.assertEqual([path for path, _ in self.fixture.fixture.fake.calls], self.expected_vendor_paths)

    def render(self, reader=None):
        return editable.render(self.app, self.order, self.profile,
                               reader or self.app.print_center._download_artwork)

    def failure(self, code, stage, retryable, reader=None):
        with self.assertRaises(editable.ProductionRenderError) as caught:
            self.render(reader)
        error = caught.exception
        self.assertEqual((error.code, error.stage, error.retryable), (code, stage, retryable))
        record = json.loads(self.warning.call_args.args[1])
        self.assertEqual((record['code'], record['stage'], record['retryable']), (code, stage, retryable))
        self.assertGreaterEqual(record['elapsed_ms'], 0)
        self.assertEqual(len(record['order_ref']), 12)
        self.assertNotIn(self.order['id'], json.dumps(record))
        return error

    def successful_worker_output(self):
        dimensions = tuple(int(math.floor(float(self.profile[key])*720/25.4+.5))
                           for key in ('width_mm', 'height_mm'))
        buffer = io.BytesIO()
        Image.new('RGBA', dimensions, (30, 50, 70, 128)).save(buffer, 'PNG')
        return subprocess.CompletedProcess([], 0, json.dumps({
            'png': 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode(),
            'layouts': [],
        }), '')

    def test_timeout_is_retryable_and_slot_is_released(self):
        with mock.patch.object(editable.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 90)):
            self.failure('PRODUCTION_RENDERER_TIMEOUT', 'worker', True)
        self.assertEqual(json.loads(self.warning.call_args.args[1])['cause_type'], 'TimeoutExpired')
        self.assertTrue(editable._RENDER_SLOT.acquire(blocking=False))
        editable._RENDER_SLOT.release()

    def test_browser_install_failure_is_review_only_and_logs_are_redacted(self):
        private = 'https://private.invalid/customer-name?token=secret'
        failure = subprocess.CalledProcessError(1, 'worker', stderr="Executable doesn't exist " + private)
        with mock.patch.object(editable.subprocess, 'run', side_effect=failure):
            error = self.failure('PRODUCTION_RENDERER_UNAVAILABLE', 'worker', False)
        self.assertEqual(error.exit_code, 1)
        self.assertNotIn(private, str(error))
        self.assertNotIn(private, str(self.warning.call_args))
        self.assertNotIn('secret', str(self.warning.call_args))

    def test_worker_crash_is_distinct_from_known_font_failure(self):
        for stderr, code, retryable in (
                ('Browser closed unexpectedly', 'PRODUCTION_RENDERER_FAILED', True),
                ('Error: 字型載入失敗', 'PRODUCTION_FONT_LOAD_FAILED', False)):
            with self.subTest(code=code), mock.patch.object(editable.subprocess, 'run',
                    side_effect=subprocess.CalledProcessError(1, 'worker', stderr=stderr)):
                self.failure(code, 'worker', retryable)

    def test_busy_worker_does_not_start_or_release_unowned_slot(self):
        slot = mock.Mock()
        slot.acquire.return_value = False
        with mock.patch.object(editable, '_RENDER_SLOT', slot), mock.patch.object(editable.subprocess, 'run') as run:
            self.failure('PRODUCTION_RENDERER_BUSY', 'admission', True)
        run.assert_not_called()
        slot.release.assert_not_called()

    def test_changed_geometry_and_fonts_remain_fail_closed(self):
        with mock.patch.object(editable.subprocess, 'run') as run:
            self.profile['width_mm'] += 1
            self.failure('PRODUCTION_GEOMETRY_MISMATCH', 'geometry', False)
            self.profile['width_mm'] -= 1
            self.order['design_json']['fontHashes']['jf-openhuninn'] = 'wrong'
            self.failure('PRODUCTION_FONT_MISMATCH', 'fonts', False)
        run.assert_not_called()

    def test_source_absent_transport_failure_and_decode_failure_are_distinct(self):
        from print_center import PrintError
        from storage3.exceptions import StorageApiError
        cases = [
            (mock.Mock(side_effect=FileNotFoundError('private-path')), 'PRODUCTION_SOURCE_MISSING', False),
            (mock.Mock(side_effect=StorageApiError('private-path', 'not_found', 404)), 'PRODUCTION_SOURCE_MISSING', False),
            (mock.Mock(side_effect=StorageApiError('private-path', 'access_denied', 403)), 'PRODUCTION_STORAGE_ACCESS_DENIED', False),
            (mock.Mock(side_effect=StorageApiError('private-path', 'bad_request', 400)), 'PRODUCTION_STORAGE_REQUEST_INVALID', False),
            (mock.Mock(side_effect=PrintError('PRINT_FILE_INVALID', 'invalid PNG')), 'PRODUCTION_SOURCE_INVALID', False),
            (mock.Mock(side_effect=TimeoutError('private-storage-url')), 'PRODUCTION_STORAGE_READ_FAILED', True),
            (mock.Mock(return_value=b'invalid image'), 'PRODUCTION_SOURCE_INVALID', False),
        ]
        with mock.patch.object(editable.subprocess, 'run') as run:
            for reader, code, retryable in cases:
                with self.subTest(code=code):
                    self.failure(code, 'sources', retryable, reader)
                    if isinstance(reader.side_effect, TimeoutError):
                        self.assertEqual(json.loads(self.warning.call_args.args[1])['cause_type'], 'TimeoutError')
        run.assert_not_called()

    def test_foreign_source_never_reads_storage(self):
        self.order['design_json']['objects'][0]['src'] = 'orders_someone-else_sources_image.png'
        reader = mock.Mock()
        self.failure('PRODUCTION_SOURCE_INVALID', 'sources', False, reader)
        reader.assert_not_called()

    def test_checkout_budget_includes_frozen_mask_before_artifact_promotion(self):
        from flask import session
        draft = self.fixture.upload(self.fixture.draft)
        with self.fixture.client.session_transaction() as saved_session:
            checkout_session = dict(saved_session)
        shop = self.app.cloud_get_json('shop_data', self.app.DATA_FILE, self.app.DEFAULT_SHOP_DATA)
        model = next(row for row in shop['models'] if row['id'] == self.fixture.model)
        source_pixels = 512 * 256
        mask_pixels = 200 * 400
        uploaded = []
        with self.app.app.test_request_context('/api/create_order'), \
                mock.patch.object(editable, 'MAX_SOURCE_PIXELS', source_pixels + mask_pixels - 1), \
                mock.patch.object(editable, 'public_image', return_value=fixture_module.mask()), \
                mock.patch.object(self.app, 'upload_private_bytes') as upload:
            session.update(checkout_session)
            with self.assertRaisesRegex(ValueError, '生產遮罩總像素'):
                editable.snapshot(self.app, draft, 'isolated-pixel-budget', model, self.fixture.style, uploaded)
        upload.assert_not_called()
        self.assertEqual(uploaded, [])

    def test_malformed_worker_result_is_not_stored(self):
        for stdout in ('not json', '{"png":"data:image/png;base64,aW52YWxpZA==","layouts":[]}', '{"layouts":null}'):
            with self.subTest(stdout=stdout), mock.patch.object(editable.subprocess, 'run',
                    return_value=subprocess.CompletedProcess([], 0, stdout, '')), \
                    mock.patch.object(editable, 'store_generated') as store:
                self.failure('PRODUCTION_RENDERER_OUTPUT_INVALID', 'output', False)
            store.assert_not_called()

    def test_storage_timeout_can_retry_but_existing_artifact_conflict_cannot(self):
        result = self.successful_worker_output()
        for failure, code, retryable in (
                (TimeoutError('private storage'), 'PRODUCTION_STORAGE_WRITE_FAILED', True),
                (ValueError('生產圖保存衝突'), 'PRODUCTION_STORAGE_CONFLICT', False)):
            with self.subTest(code=code), mock.patch.object(editable.subprocess, 'run', return_value=result), \
                    mock.patch.object(editable, 'store_generated', side_effect=failure):
                self.failure(code, 'storage', retryable)

    def test_valid_worker_result_preserves_pixels_alpha_and_720_dpi(self):
        result = self.successful_worker_output()
        original = Image.open(io.BytesIO(base64.b64decode(json.loads(result.stdout)['png'].split(',')[1])))
        with mock.patch.object(editable.subprocess, 'run', return_value=result):
            path, raw, layouts = self.render()
        output = Image.open(io.BytesIO(raw))
        self.assertEqual(output.size, original.size)
        self.assertEqual(output.tobytes(), original.tobytes())
        self.assertEqual(output.getchannel('A').getextrema(), (128, 128))
        self.assertAlmostEqual(output.info['dpi'][0], 720, delta=.05)
        self.assertEqual(self.app.print_center._download_artwork(path), raw)
        self.assertEqual(layouts, [])

    @unittest.skipUnless(os.environ.get('RUN_REAL_RENDERER_TEST') == '1', 'browser installation required')
    def test_actual_background_and_request_render_are_identical(self):
        # Run the exact subprocess/Fabric path from a separate thread, like the dispatcher.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='print-auto-dispatch') as pool:
            background = pool.submit(self.render).result(timeout=120)
        foreground = self.render()
        self.assertEqual(background, foreground)
        image = Image.open(io.BytesIO(background[1]))
        self.assertEqual(image.size, (2030, 4241))
        self.assertAlmostEqual(image.info['dpi'][0], 720, delta=.05)
        self.assertEqual(image.getpixel((0, 0))[3], 0)

    @unittest.skipUnless(os.environ.get('RUN_REAL_RENDERER_TEST') == '1', 'browser installation required')
    def test_actual_720_dpi_auto_handoff_and_fake_vendor_receive_exactly_once(self):
        service = self.app.print_center
        fake = self.fixture.fixture.fake
        order_id = self.order['id']
        design = self.order['design_json']
        source_paths = {item['src'] for item in editable.nodes(design) if item['type'] == 'image'}
        source_paths.add(design['production']['maskPath'])
        original_sources = {path: service._download_artwork(path) for path in source_paths}
        original_print = service._download_artwork(self.order['print_path'])
        fake.responses['/api/Device/receiveTask'] = {
            'code': 0, 'data': {'taskid': 'real-render-isolated-once', 'status': 0}}
        self.expected_vendor_paths = ['/api/Device/receiveTask']
        self.assertIsNone(service.store.latest_job(order_id))
        # Exercise committed outbox, frozen sources/fonts, real subprocess,
        # immutable 720 DPI artifact and receiveTask from the dispatcher thread.
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='print-auto-dispatch') as pool:
            pool.submit(service.dispatch_auto_once).result(timeout=120)
        for _ in range(2):
            service.dispatch_auto_once()
        jobs = [job for job in service.store.list_jobs() if job['order_id'] == order_id]
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertEqual((job['state'], job['vendor_taskid']), ('QUEUED', 'real-render-isolated-once'))
        self.assertNotEqual(job['artwork_path'], self.order['print_path'])
        raw = service._download_artwork(job['artwork_path'])
        image = Image.open(io.BytesIO(raw))
        self.assertEqual(image.size, (2030, 4241))
        self.assertAlmostEqual(image.info['dpi'][0], 720, delta=.05)
        self.assertEqual(image.getpixel((0, 0))[3], 0)
        self.assertEqual(job['artwork_sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(service._download_artwork(self.order['print_path']), original_print)
        self.assertEqual({path: service._download_artwork(path) for path in source_paths}, original_sources)
        self.assertEqual(service.store.profile(self.fixture.fixture.sku_id), self.profile)
        with service.store.connection() as db:
            handoff = db.execute('SELECT state,attempt_count,prepared_job_id FROM print_handoffs WHERE order_id=?',
                                 (order_id,)).fetchone()
        self.assertEqual(tuple(handoff), ('PREPARED', 1, job['id']))
        self.assertEqual([path for path, _ in fake.calls], ['/api/Device/receiveTask'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
