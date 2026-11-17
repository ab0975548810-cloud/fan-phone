"""No real vendor: an independent manual task fences automatic dispatch."""
import copy
import json
import os
import unittest
import uuid
from unittest import mock
import test_print_center as fixtures
from print_center import PrintError

app = fixtures.app


class SendGuardTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PrintCenterTests('runTest')
        self.fixture.setUp()
        self.fixture.save_profile()

    def tearDown(self):
        self.fixture.tearDown()

    def test_manual_queued_unknown_and_completed_block_ordinary_send(self):
        f = self.fixture
        ordinary = f.prepare()
        f.fake.responses['/api/Device/receiveTask'] = {'code': 0, 'data': {'taskid': 'manual-isolated', 'status': 0}}
        result = f.post('manual-reprint', {'order_id': f.order_id})
        self.assertEqual(result.status_code, 200, result.get_json())
        manual = result.get_json()['job']
        before = copy.deepcopy(app.commerce.read())
        for state in ('QUEUED', 'UNKNOWN', 'SENDING', 'COMPLETED'):
            with self.subTest(state=state):
                app.print_center.store.patch_job(manual['id'], {'state': state})
                response = f.post('send', {'job_id': ordinary['id']})
                self.assertEqual(response.status_code, 409, response.get_json())
                atomic = app.print_center.store.claim_send_if_safe(
                    ordinary['id'], nonce='isolated', expires_at='2099-01-01T00:00:00+00:00', device_id='fixture')
                self.assertFalse(atomic['ok'])
                self.assertEqual(app.print_center.store.job(ordinary['id'])['state'], 'PREPARED')
        self.assertEqual(app.commerce.read(), before)
        self.assertEqual(len([p for p, _ in f.fake.calls if p.endswith('receiveTask')]), 1)

    def test_generic_manual_reprint_cannot_clone_revision_with_flag_on_or_off(self):
        f = self.fixture
        revision = f.prepare()
        with app.print_center.store.connection(True) as db:
            db.execute('UPDATE print_jobs SET manual_independent=1 WHERE id=?', (revision['id'],))
            db.execute('INSERT INTO print_events (id,job_id,event_key,event_type,payload_json,created_at) VALUES (?,?,?,?,?,?)',
                (str(uuid.uuid4()), revision['id'], 'revision-approval-fixture', 'MANUAL_REPRINT_AUTHORIZED',
                 json.dumps({'version': 2, 'versionHash': 'a'*64}), revision['created_at']))
        before = copy.deepcopy(app.commerce.read())
        jobs = app.print_center.store.jobs_for_order(f.order_id)
        for flag in ('false', 'true'):
            with self.subTest(flag=flag), mock.patch.dict(os.environ, {'ORDER_PIXEL_REPRINT_ENABLED': flag}):
                response = f.post('manual-reprint', {'order_id': f.order_id})
                self.assertEqual(response.status_code, 409, response.get_json())
                self.assertEqual(response.get_json()['code'], 'REVISION_REVIEW_REQUIRED')
        with mock.patch.dict(os.environ, {'ORDER_PIXEL_REPRINT_ENABLED': 'false'}):
            with self.assertRaises(PrintError) as raised:
                app.print_center.send(revision['id'], 'revision-disabled-send-0001', manual_reprint=True)
            self.assertEqual(raised.exception.code, 'REVISION_REPRINT_DISABLED')
        self.assertEqual(app.print_center.store.jobs_for_order(f.order_id), jobs)
        self.assertEqual(app.commerce.read(), before)
        self.assertEqual(f.fake.calls, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
