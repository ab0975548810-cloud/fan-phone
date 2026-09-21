"""Print Center safety tests. No test in this file can reach the vendor network."""
import os
import tempfile
import unittest
import uuid
from pathlib import Path

os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
os.environ["SESSION_COOKIE_SECURE"] = "false"

import app
import commerce_patch
import print_center
from commerce_store import Store
from order_color_patch import install as install_colors
from order_management_patch import install as install_actions
from print_store import PrintStore
from print_vendor import VendorAmbiguous, YunPrintClient, yun_sign

install_colors(app)
install_actions(app)
commerce_patch.install(app)
print_center.install(app)
app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z7VQAAAAASUVORK5CYII="


class FakeVendor:
    def __init__(self):
        self.calls = []
        self.responses = {}
        self.timeout_paths = set()

    def __call__(self, path, payload):
        self.calls.append((path, dict(payload)))
        if path in self.timeout_paths:
            raise TimeoutError("fixture timeout")
        return self.responses.get(path, {"code": 0, "data": {"status": 0}})


class PrintCenterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        app.SAVE_DIR = str(root / "orders")
        Path(app.SAVE_DIR).mkdir()
        app.DATA_FILE = str(root / "shop.json")
        app.commerce.store = Store(app)
        app.commerce.store.path = str(root / "commerce.sqlite3")
        app.print_center.store = PrintStore(app)
        app.print_center.store.path = app.commerce.store.path
        self.fake = FakeVendor()
        self.vendor_env = {
            "YUN_PRINT_ENABLED": "true", "YUN_PRINT_DEVICE_ID": "device-fixture",
            "YUN_PRINT_DEVICE_KEY": "fake-key-never-production", "YUN_PRINT_BASE_URL": "https://fixture.invalid",
            "CI": "true",
        }
        self._old_print_env = {name: os.environ.get(name) for name in ("PRINT_ARTWORK_TOKEN_SECRET", "PRINT_PUBLIC_BASE_URL")}
        os.environ["PRINT_ARTWORK_TOKEN_SECRET"] = "fixture-artwork-token-secret-32-characters"
        os.environ["PRINT_PUBLIC_BASE_URL"] = "https://print.fixture.invalid"
        app.print_center.client = YunPrintClient(transport=self.fake, env=self.vendor_env, clock=lambda: 1700000000, nonce=lambda: "once-fixed")
        self.client = app.app.test_client()
        with self.client.session_transaction() as session:
            session["logged_in"] = True
        self.assertEqual(self.client.post("/api/admin/commerce_sync_skus").status_code, 200)
        data = self.client.get("/api/admin/commerce_data").get_json()["data"]
        self.sku_id = data["skus"][0]["id"]
        data["skus"][0].update(cost_price=100, stock_qty=20, track_stock=True)
        self.assertEqual(self.client.post("/api/admin/save_commerce_data", json=data).status_code, 200)
        self.order_id = self.create_order()

    def tearDown(self):
        for name, value in self._old_print_env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.tmp.cleanup()

    def create_order(self):
        key = "checkout-" + uuid.uuid4().hex
        response = self.client.post("/api/create_order", json={
            "idempotency_key": key, "print_file": PNG, "mockup_file": PNG,
            "model_id": app.DEFAULT_SHOP_DATA["models"][0]["id"],
            "style_id": app.DEFAULT_SHOP_DATA["styles"][0]["id"], "color_name": "透明",
            "quantity": 1, "customer_name": "列印測試", "payment_method": "現金", "design_json": {},
        })
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()["order_id"]

    def post(self, action, payload, key=None):
        idem = key or ("print-" + uuid.uuid4().hex)
        return self.client.post("/api/admin/print/" + action, json={**payload, "idempotency_key": idem}, headers={"Idempotency-Key": idem})

    def save_profile(self):
        response = self.client.post("/api/admin/print/profile", json={
            "sku_id": self.sku_id, "width_mm": 80, "height_mm": 160,
            "left_mm": 1.5, "top_mm": 2.5, "copies": 1,
            "spot_color": "must-be-ignored", "channel": "must-be-ignored", "angle": 0,
        })
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))

    def prepare(self, key=None):
        response = self.post("prepare", {"order_id": self.order_id}, key)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()["job"]

    def send(self, job_id, key=None, taskid="task-fixture"):
        self.fake.responses["/api/Device/receiveTask"] = {"code": 0, "data": {"taskid": taskid, "status": 0}}
        return self.post("send", {"job_id": job_id}, key)

    def callback(self, taskid, status, msg="fixture", valid=True):
        nonce = "cb-" + __import__("hashlib").sha256(f"{taskid}|{status}|{msg}".encode()).hexdigest()[:16]
        payload = {"device_id": "device-fixture", "once": nonce, "time": "1700000001", "taskid": taskid, "status": str(status), "msg": msg}
        payload["sign"] = yun_sign(payload["device_id"], "fake-key-never-production" if valid else "wrong", payload["once"], payload["time"])
        return self.client.post("/api/print/callback", json=payload)

    def test_sign_is_deterministic_and_exact(self):
        self.assertEqual(yun_sign("d", "k", "n", "1700000000"), "aeb1780269af57550e7157aa07203c61")

    def test_prepare_is_idempotent_and_one_active_job_per_order(self):
        key = "prepare-fixed-00000001"
        first = self.prepare(key)
        second = self.prepare(key)
        third = self.prepare("prepare-fixed-00000002")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["id"], third["id"])
        self.assertEqual(len(app.print_center.store.list_jobs()), 1)

    def test_missing_credentials_and_missing_profile_fail_closed(self):
        job = self.prepare()
        response = self.send(job["id"])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "PROFILE_MISSING")
        self.save_profile()
        self.assertEqual(self.post("profile-snapshot", {"job_id": job["id"]}).status_code, 200)
        app.print_center.client = YunPrintClient(env={"CI": "true"})
        response = self.send(job["id"])
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "VENDOR_NOT_READY")
        app.print_center.store.patch_job(job["id"], {"state": "QUEUED", "vendor_taskid": "fixture-disabled"})
        response = self.post("start", {"job_id": job["id"]})
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "DESKTOP_MANUAL_CONFIRMATION"))
        self.assertFalse(any(path == "/api/Device/startPrint" for path, _ in self.fake.calls))

    def test_enabled_vendor_requires_explicit_https_url_and_token_secret(self):
        self.save_profile();job = self.prepare()
        os.environ.pop("PRINT_ARTWORK_TOKEN_SECRET", None)
        os.environ.pop("PRINT_PUBLIC_BASE_URL", None)
        dashboard = self.client.get("/api/admin/print/jobs").get_json()
        self.assertFalse(dashboard["vendor_ready"])
        response = self.send(job["id"])
        self.assertEqual((response.status_code, response.get_json()["code"]), (503, "VENDOR_NOT_READY"))
        app.print_center.store.patch_job(job["id"], {"state": "QUEUED", "vendor_taskid": "secure-config-task"})
        response = self.post("start", {"job_id": job["id"]})
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "DESKTOP_MANUAL_CONFIRMATION"))
        self.assertFalse(any(path in ("/api/Device/receiveTask", "/api/Device/startPrint") for path, _ in self.fake.calls))

    def test_vendor_artwork_token_is_job_scoped_png_and_revoked_terminal(self):
        self.save_profile();job = self.prepare()
        expiry = (print_center.datetime.now(print_center.timezone.utc) + print_center.timedelta(hours=1)).isoformat()
        stored = app.print_center.store.patch_job(job["id"], {"artwork_token_expires_at": expiry})
        token = app.print_center.artwork_token(stored)
        good = self.client.get(f"/api/print/artwork/{job['id']}/{token}")
        self.assertEqual(good.status_code, 200)
        self.assertEqual(good.mimetype, "image/png")
        self.assertEqual(self.client.get(f"/api/print/artwork/{job['id']}/wrong-token").status_code, 404)
        app.print_center.store.patch_job(job["id"], {"state": "CANCELED"})
        self.assertEqual(self.client.get(f"/api/print/artwork/{job['id']}/{token}").status_code, 404)

    def test_receive_success_saves_task_and_profile_snapshot(self):
        self.save_profile();job = self.prepare()
        response = self.send(job["id"])
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        stored = app.print_center.store.job(job["id"])
        self.assertEqual((stored["state"], stored["vendor_taskid"], stored["width_mm"]), ("QUEUED", "task-fixture", 80.0))
        self.assertEqual((stored["channel"], stored["spot_color"]), ("1", ""))
        receives = [payload for path, payload in self.fake.calls if path == "/api/Device/receiveTask"]
        self.assertEqual(len(receives), 1)
        self.assertEqual(receives[0]["channel"], "1")
        self.assertNotIn("spot_color", receives[0])
        self.assertFalse(any(path in ("/api/Device/startPrint", "/api/Device/pushPrint") for path, _ in self.fake.calls))
        self.assertNotIn("fake-key", str(stored))

    def test_receive_timeout_locks_unknown_reconcile_recovers_without_resend(self):
        self.save_profile();job = self.prepare();self.fake.timeout_paths.add("/api/Device/receiveTask")
        key = "send-timeout-00000001"
        response = self.send(job["id"], key)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "UNKNOWN")
        response = self.send(job["id"], key)
        self.assertEqual(response.status_code, 200)
        receives = [c for c in self.fake.calls if c[0] == "/api/Device/receiveTask"]
        self.assertEqual(len(receives), 1)
        self.fake.timeout_paths.clear()
        self.fake.responses["/api/Device/getAllTasks"] = {"code": 0, "data": {"list": [{"order_id": self.order_id, "taskid": "recovered-task", "status": 0}]}}
        response = self.post("reconcile", {"job_id": job["id"]})
        self.assertEqual(response.status_code, 200)
        stored = app.print_center.store.job(job["id"])
        self.assertEqual((stored["state"], stored["vendor_taskid"]), ("QUEUED", "recovered-task"))

    def test_start_endpoint_is_always_manual_confirmation_and_never_calls_vendor(self):
        self.save_profile();job = self.prepare();self.assertEqual(self.send(job["id"]).status_code, 200)
        key = "start-fixed-000000001"
        first = self.post("start", {"job_id": job["id"]}, key)
        second = self.post("start", {"job_id": job["id"]}, key)
        self.assertEqual((first.status_code, first.get_json()["code"]), (409, "DESKTOP_MANUAL_CONFIRMATION"))
        self.assertEqual((second.status_code, second.get_json()["code"]), (409, "DESKTOP_MANUAL_CONFIRMATION"))
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "QUEUED")
        self.assertFalse(any(path in ("/api/Device/startPrint", "/api/Device/pushPrint") for path, _ in self.fake.calls))

    def test_malformed_success_and_unconfirmed_cancel_become_unknown(self):
        with self.assertRaises(VendorAmbiguous):
            YunPrintClient._unpack({})
        self.save_profile();job = self.prepare()
        self.fake.responses["/api/Device/receiveTask"] = {}
        response = self.post("send", {"job_id": job["id"]})
        self.assertEqual((response.status_code, response.get_json()["code"]), (503, "RECONCILE_REQUIRED"))
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "UNKNOWN")
        app.print_center.store.patch_job(job["id"], {"state": "QUEUED", "vendor_taskid": "task-fixture", "ambiguous_operation": None})
        self.fake.responses["/api/Device/cancelTask"] = {"code": 0, "data": {}}
        response = self.post("cancel", {"job_id": job["id"]})
        self.assertEqual((response.status_code, response.get_json()["code"]), (503, "RECONCILE_REQUIRED"))
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "UNKNOWN")

    def test_stale_sending_and_canceling_can_reconcile_without_resend(self):
        self.save_profile();job = self.prepare()
        app.print_center.store.patch_job(job["id"], {"state": "SENDING"})
        self.fake.responses["/api/Device/getAllTasks"] = {"code": 0, "data": {"list": [{"order_id": self.order_id, "taskid": "stale-task", "status": 0}]}}
        self.assertEqual(self.post("reconcile", {"job_id": job["id"]}).status_code, 200)
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "QUEUED")
        app.print_center.store.patch_job(job["id"], {"state": "CANCELING"})
        self.fake.responses["/api/Device/getAllTasks"] = {"code": 0, "data": {"list": []}}
        self.assertEqual(self.post("reconcile", {"job_id": job["id"]}).status_code, 200)
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "UNKNOWN")
        self.assertFalse(any(path in ("/api/Device/receiveTask", "/api/Device/cancelTask") for path, _ in self.fake.calls))

    def test_cancel_is_available_while_waiting_and_blocked_after_printing_callback(self):
        self.save_profile();job = self.prepare();self.assertEqual(self.send(job["id"], taskid="cancel-waiting").status_code, 200)
        self.fake.responses["/api/Device/cancelTask"] = {"code": 0, "data": {"status": 3}}
        self.assertEqual(self.post("cancel", {"job_id": job["id"]}).status_code, 200)
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "CANCELED")
        cancel_calls = len([path for path, _ in self.fake.calls if path == "/api/Device/cancelTask"])

        self.order_id = self.create_order();job = self.prepare()
        self.assertEqual(self.send(job["id"], taskid="printing-task").status_code, 200)
        self.assertEqual(self.callback("printing-task", 1).status_code, 200)
        blocked = self.post("cancel", {"job_id": job["id"]})
        self.assertEqual((blocked.status_code, blocked.get_json()["code"]), (409, "BAD_PRINT_STATE"))
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "PRINTING")
        self.assertEqual(len([path for path, _ in self.fake.calls if path == "/api/Device/cancelTask"]), cancel_calls)

    def test_callbacks_are_authenticated_idempotent_and_complete_order_safely(self):
        self.save_profile();job = self.prepare();self.assertEqual(self.send(job["id"]).status_code, 200)
        self.assertEqual(self.callback("task-fixture", 1).status_code, 200)
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "PRINTING")
        bad = self.callback("task-fixture", 2, valid=False)
        self.assertEqual(bad.status_code, 403)
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "PRINTING")
        done = self.callback("task-fixture", 2, "done")
        duplicate = self.callback("task-fixture", 2, "done")
        self.assertFalse(done.get_json()["duplicate"])
        self.assertTrue(duplicate.get_json()["duplicate"])
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "COMPLETED")
        self.assertEqual(app.commerce.store.order(self.order_id)["status"], "已完成")
        # A delayed printing callback with a fresh auth tuple cannot downgrade a
        # verified completed job or its order.
        self.assertEqual(self.callback("task-fixture", 1, "delayed printing").status_code, 200)
        self.assertEqual(app.print_center.store.job(job["id"])["state"], "COMPLETED")
        with app.print_center.store.connection() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM print_events WHERE job_id=?", (job["id"],)).fetchone()[0], 3)

    def test_model_calibration_is_suggestion_only_and_generic_style_defaults_are_not_guessed(self):
        dashboard = self.client.get("/api/admin/print/jobs").get_json()
        row = next(item for item in dashboard["rows"] if item["order_id"] == self.order_id)
        self.assertIsNone(row["profile_suggestion"])
        self.assertEqual(dashboard["platform"]["print_area_mm"], {"width": 200, "height": 230})
        self.assertEqual(dashboard["platform"]["coordinate_origin"], "治具右下角")

        shop = app.local_load_json(app.DATA_FILE, app.DEFAULT_SHOP_DATA)
        model = next(item for item in shop["models"] if item["id"] == app.DEFAULT_SHOP_DATA["models"][0]["id"])
        model.update(print_w=71.25, print_h=148.5, print_x=3.25, print_y=4.75)
        app.local_save_json(app.DATA_FILE, shop)
        dashboard = self.client.get("/api/admin/print/jobs").get_json()
        row = next(item for item in dashboard["rows"] if item["order_id"] == self.order_id)
        self.assertEqual(row["profile_suggestion"]["width_mm"], 71.25)
        self.assertIn("iPhone 11 蒙版設定", row["profile_suggestion"]["source"])
        self.assertFalse(row["profile_available"])
        job = self.prepare()
        self.assertFalse(job["profile_complete"])

    def test_print_center_ui_has_a5_guidance_and_no_start_action(self):
        source = (Path(__file__).parent / "static" / "admin-print-center.js").read_text(encoding="utf-8")
        self.assertNotIn('data-pc="start"', source)
        self.assertIn("A5 有效範圍：200 × 230 mm", source)
        self.assertIn("座標原點：治具右下角", source)
        self.assertIn("送到銳印", source)

    def test_fault_statuses_and_printer_status_six_keep_raw_values(self):
        self.save_profile();job = self.prepare();self.assertEqual(self.send(job["id"]).status_code, 200)
        for status in (3, 4, 5, 6, 7, 8, 11, 12, 99):
            app.print_center.store.patch_job(job["id"], {"state": "QUEUED"})
            response = self.callback("task-fixture", status, f"raw-{status}")
            self.assertEqual(response.status_code, 200)
            stored = app.print_center.store.job(job["id"])
            self.assertEqual((stored["vendor_raw_status"], stored["vendor_raw_message"]), (str(status), f"raw-{status}"))
        payload = {"device_id": "device-fixture", "once": "p-once", "time": "1700000002", "status": "6", "msg": "vendor ambiguous six"}
        payload["sign"] = yun_sign(payload["device_id"], "fake-key-never-production", payload["once"], payload["time"])
        self.assertEqual(self.client.post("/api/print/printer-callback", json=payload).status_code, 200)
        with app.print_center.store.connection() as db:
            row = db.execute("SELECT raw_status,raw_message FROM printer_status_events").fetchone()
            self.assertEqual(tuple(row), ("6", "vendor ambiguous six"))

    def test_void_order_cannot_prepare_and_late_callback_does_not_restore(self):
        self.assertEqual(self.client.post("/api/admin/order_action", json={"order_id": self.order_id, "action": "void", "idempotency_key": "void-order-000000001"}).status_code, 200)
        response = self.post("prepare", {"order_id": self.order_id})
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "VOID_ORDER"))
        other = self.create_order();self.order_id = other;self.save_profile();job = self.prepare();self.assertEqual(self.send(job["id"]).status_code, 200)
        self.assertEqual(self.client.post("/api/admin/order_action", json={"order_id": other, "action": "void", "idempotency_key": "void-order-000000002"}).status_code, 200)
        self.assertEqual(self.post("start", {"job_id": job["id"]}).get_json()["code"], "DESKTOP_MANUAL_CONFIRMATION")
        self.assertEqual(self.callback("task-fixture", 2, "late complete").status_code, 200)
        self.assertEqual(app.commerce.store.order(other)["status"], "作廢")

    def test_active_print_job_blocks_permanent_order_delete_and_artwork_cleanup(self):
        job = self.prepare()
        order = app.commerce.store.order(self.order_id)
        artwork = Path(app.SAVE_DIR) / order["print_path"]
        self.assertTrue(artwork.exists())
        self.assertEqual(self.client.post("/api/admin/order_action", json={"order_id": self.order_id, "action": "void", "idempotency_key": "void-delete-00000001"}).status_code, 200)
        blocked = self.client.post("/api/admin/order_action", json={"order_id": self.order_id, "action": "delete", "idempotency_key": "delete-active-000001"})
        self.assertEqual((blocked.status_code, blocked.get_json()["code"]), (409, "ACTIVE_PRINT_JOB"))
        self.assertIsNotNone(app.commerce.store.order(self.order_id))
        self.assertTrue(artwork.exists())
        app.print_center.store.patch_job(job["id"], {"state": "CANCELED", "canceled_at": "2026-09-19T00:00:00+00:00"})
        deleted = self.client.post("/api/admin/order_action", json={"order_id": self.order_id, "action": "delete", "idempotency_key": "delete-terminal-0001"})
        self.assertEqual(deleted.status_code, 200, deleted.get_data(as_text=True))
        self.assertIsNone(app.commerce.store.order(self.order_id))
        self.assertFalse(artwork.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
