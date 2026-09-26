"""Focused Backend V1 regressions for admin session and private local artwork."""
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import app
import security_perf


security_perf.install(app)


class BackendV1SecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_save_dir = app.SAVE_DIR
        app.SAVE_DIR = self.tmp.name
        app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        self.client = app.app.test_client()
        Path(self.tmp.name, 'private-order.png').write_bytes(b'private-artwork')

    def tearDown(self):
        app.SAVE_DIR = self.old_save_dir
        self.tmp.cleanup()

    def _login_session(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True

    def test_local_order_artwork_requires_admin_session(self):
        response = self.client.get('/orders/private-order.png')
        self.assertEqual(response.status_code, 404)

        self._login_session()
        response = self.client.get('/orders/private-order.png')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'private-artwork')
        response.close()

    def test_logout_is_same_origin_and_clears_session(self):
        self._login_session()
        admin = self.client.get('/admin')
        self.assertEqual(admin.status_code, 200)
        self.assertIn(b'action="/logout"', admin.data)
        admin.close()

        rejected = self.client.post('/logout', headers={'Origin': 'https://attacker.example'})
        self.assertEqual(rejected.status_code, 403)
        admin = self.client.get('/admin')
        self.assertEqual(admin.status_code, 200)
        admin.close()

        response = self.client.post('/logout', headers={'Origin': 'http://localhost'})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith('/login'))
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.assertEqual(self.client.get('/orders/private-order.png').status_code, 404)

    def test_production_password_login_fails_closed_until_strong_secret_is_set(self):
        with mock.patch.dict(
            app.os.environ,
            {'BENFUWAN_PRODUCTION': '1', 'ADMIN_PASSWORD': 'fan123'},
            clear=False,
        ):
            response = self.client.post(
                '/login',
                data={'password': 'fan123'},
                headers={'Origin': 'http://localhost'},
            )
            self.assertEqual(response.status_code, 503)
            self.assertIn('ADMIN_PASSWORD', response.get_data(as_text=True))

        strong_password = 'safe-admin-password-2026'
        with mock.patch.dict(
            app.os.environ,
            {'BENFUWAN_PRODUCTION': '1', 'ADMIN_PASSWORD': strong_password},
            clear=False,
        ), mock.patch.object(app, 'ADMIN_PASSWORD', strong_password):
            response = self.client.post(
                '/login',
                data={'password': strong_password},
                headers={'Origin': 'http://localhost'},
            )
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.headers['Location'].endswith('/admin'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
