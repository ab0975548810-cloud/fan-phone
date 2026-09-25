import hashlib
import json
import os
import unittest
from pathlib import Path

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import bytes_to_base64url


ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
TEST_DIR = ROOT / "__pycache__" / f"passkey-test-{os.getpid()}"
TEST_DIR.mkdir(parents=True, exist_ok=True)
PASSKEY_FILE = str(TEST_DIR / "admin_passkeys.json")
os.environ["ADMIN_PASSWORD"] = "test-password-only"
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ["ADMIN_PASSKEYS_FILE"] = PASSKEY_FILE
os.environ["WEBAUTHN_RP_ID"] = "localhost"
os.environ["WEBAUTHN_ORIGIN"] = "http://localhost"
os.environ.pop("SUPABASE_URL", None)
os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)

import app as app_module
from passkey_auth import CeremonyRegistry, PasskeyConfig, install as install_passkey_auth
from security_perf import install as install_security


service = install_passkey_auth(app_module)
install_security(app_module)
app_module.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)


def compact_json(value):
    return json.dumps(value, separators=(",", ":")).encode("utf-8")


class VirtualAuthenticator:
    def __init__(self):
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)

    @property
    def credential_id_b64(self):
        return bytes_to_base64url(self.credential_id)

    def registration(self, challenge, *, origin="http://localhost", rp_id="localhost", flags=0x45):
        numbers = self.private_key.public_key().public_numbers()
        cose_key = cbor2.dumps({
            1: 2,
            3: -7,
            -1: 1,
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        })
        client_data = compact_json({
            "type": "webauthn.create",
            "challenge": challenge,
            "origin": origin,
            "crossOrigin": False,
        })
        auth_data = (
            hashlib.sha256(rp_id.encode("utf-8")).digest()
            + bytes([flags])
            + (0).to_bytes(4, "big")
            + (b"\0" * 16)
            + len(self.credential_id).to_bytes(2, "big")
            + self.credential_id
            + cose_key
        )
        attestation = cbor2.dumps({"fmt": "none", "authData": auth_data, "attStmt": {}})
        return {
            "id": self.credential_id_b64,
            "rawId": self.credential_id_b64,
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal"],
            },
        }

    def assertion(self, challenge, *, origin="http://localhost", rp_id="localhost", flags=0x05, sign_count=1):
        client_data = compact_json({
            "type": "webauthn.get",
            "challenge": challenge,
            "origin": origin,
            "crossOrigin": False,
        })
        auth_data = hashlib.sha256(rp_id.encode("utf-8")).digest() + bytes([flags]) + sign_count.to_bytes(4, "big")
        signature = self.private_key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        return {
            "id": self.credential_id_b64,
            "rawId": self.credential_id_b64,
            "type": "public-key",
            "authenticatorAttachment": "platform",
            "clientExtensionResults": {},
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": bytes_to_base64url(service.config.owner_id.encode("ascii")),
            },
        }


class PasskeyTests(unittest.TestCase):
    ip_counter = 0

    def setUp(self):
        service.ceremonies.clear()
        app_module.local_save_json(PASSKEY_FILE, service._default_document())
        type(self).ip_counter += 1
        self.ip = f"198.51.100.{type(self).ip_counter}"

    def client(self):
        client = app_module.app.test_client()
        client.environ_base["HTTP_X_FORWARDED_FOR"] = self.ip
        return client

    def password_login(self, client):
        response = client.post("/login", data={"password": "test-password-only"})
        self.assertEqual(response.status_code, 302)
        return response

    def registration_options(self, client):
        response = client.post("/api/admin/passkey/register/options", json={})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def register(self, client, authenticator=None):
        authenticator = authenticator or VirtualAuthenticator()
        options = self.registration_options(client)
        payload = {
            "ceremony_id": options["ceremony_id"],
            "device_label": "測試 iPhone",
            "credential": authenticator.registration(options["publicKey"]["challenge"]),
        }
        response = client.post("/api/admin/passkey/register/verify", json=payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return authenticator, payload

    def test_password_login_and_face_id_default_cta(self):
        client = self.client()
        page = client.get("/login")
        text = page.get_data(as_text=True)
        self.assertEqual(page.status_code, 200)
        self.assertLess(text.index("使用 Face ID 登入"), text.index("使用密碼登入"))
        self.assertEqual(client.post("/login", data={"password": "wrong"}).status_code, 401)
        self.password_login(client)
        self.assertEqual(client.get("/admin").status_code, 200)

    def test_missing_server_config_fails_closed_and_password_remains(self):
        original = service.config
        service.config = PasskeyConfig(
            rp_id="",
            origin="",
            rp_name=original.rp_name,
            owner_id=original.owner_id,
            configured=False,
        )
        try:
            client = self.client()
            status = client.get("/api/auth/passkey/status")
            self.assertEqual(status.status_code, 200)
            self.assertFalse(status.get_json()["configured"])
            options = client.post("/api/auth/passkey/options", json={})
            self.assertEqual((options.status_code, options.get_json()["code"]), (503, "PASSKEY_NOT_CONFIGURED"))
            self.password_login(client)
            self.assertEqual(client.get("/admin").status_code, 200)
        finally:
            service.config = original

    def test_registration_requires_password_login_and_is_durable_single_use(self):
        client = self.client()
        self.assertEqual(client.post("/api/admin/passkey/register/options", json={}).status_code, 401)
        self.password_login(client)
        authenticator, payload = self.register(client)
        data = app_module.local_load_json(PASSKEY_FILE, {})
        self.assertEqual(data["owner_id"], service.config.owner_id)
        self.assertEqual(len(data["credentials"]), 1)
        saved = data["credentials"][0]
        self.assertEqual(saved["credential_id"], authenticator.credential_id_b64)
        self.assertTrue(saved["public_key"])
        self.assertNotIn("face", json.dumps(data).lower())
        replay = client.post("/api/admin/passkey/register/verify", json=payload)
        self.assertEqual((replay.status_code, replay.get_json()["code"]), (400, "CHALLENGE_INVALID"))

    def test_registration_rejects_wrong_challenge_origin_and_rp_id(self):
        cases = (
            ("challenge", {"challenge": bytes_to_base64url(os.urandom(32))}),
            ("origin", {"origin": "https://evil.example"}),
            ("rp", {"rp_id": "evil.example"}),
        )
        for label, changes in cases:
            with self.subTest(label=label):
                client = self.client()
                self.password_login(client)
                options = self.registration_options(client)
                args = {"challenge": options["publicKey"]["challenge"], **changes}
                credential = VirtualAuthenticator().registration(**args)
                response = client.post("/api/admin/passkey/register/verify", json={"ceremony_id": options["ceremony_id"], "credential": credential})
                self.assertEqual((response.status_code, response.get_json()["code"]), (400, "PASSKEY_VERIFY_FAILED"))

    def test_authentication_success_replay_rejection_and_counter_update(self):
        admin = self.client()
        self.password_login(admin)
        authenticator, _ = self.register(admin)
        user = self.client()
        options = user.post("/api/auth/passkey/options", json={}).get_json()
        payload = {
            "ceremony_id": options["ceremony_id"],
            "credential": authenticator.assertion(options["publicKey"]["challenge"], sign_count=1),
        }
        response = user.post("/api/auth/passkey/verify", json=payload)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        with user.session_transaction() as logged_in:
            self.assertTrue(logged_in["logged_in"])
            self.assertEqual(logged_in["auth_method"], "passkey")
        self.assertEqual(user.get("/admin").status_code, 200)
        saved = app_module.local_load_json(PASSKEY_FILE, {})["credentials"][0]
        self.assertEqual(saved["sign_count"], 1)
        self.assertTrue(saved["last_used_at"])
        replay = user.post("/api/auth/passkey/verify", json=payload)
        self.assertEqual((replay.status_code, replay.get_json()["code"]), (400, "CHALLENGE_INVALID"))

    def test_authentication_rejects_wrong_challenge_origin_rp_and_missing_uv(self):
        admin = self.client()
        self.password_login(admin)
        authenticator, _ = self.register(admin)
        cases = (
            ("challenge", {"challenge": bytes_to_base64url(os.urandom(32))}),
            ("origin", {"origin": "https://evil.example"}),
            ("rp", {"rp_id": "evil.example"}),
            ("uv", {"flags": 0x01}),
        )
        for label, changes in cases:
            with self.subTest(label=label):
                user = self.client()
                options = user.post("/api/auth/passkey/options", json={}).get_json()
                args = {"challenge": options["publicKey"]["challenge"], **changes}
                response = user.post("/api/auth/passkey/verify", json={
                    "ceremony_id": options["ceremony_id"],
                    "credential": authenticator.assertion(**args),
                })
                self.assertEqual((response.status_code, response.get_json()["code"]), (401, "PASSKEY_VERIFY_FAILED"))
                with user.session_transaction() as state:
                    self.assertFalse(state.get("logged_in"))

    def test_unknown_and_revoked_credential_cannot_log_in(self):
        admin = self.client()
        self.password_login(admin)
        authenticator, _ = self.register(admin)
        stranger = VirtualAuthenticator()
        user = self.client()
        options = user.post("/api/auth/passkey/options", json={}).get_json()
        unknown = user.post("/api/auth/passkey/verify", json={
            "ceremony_id": options["ceremony_id"],
            "credential": stranger.assertion(options["publicKey"]["challenge"]),
        })
        self.assertEqual((unknown.status_code, unknown.get_json()["code"]), (401, "PASSKEY_UNKNOWN"))

        options = user.post("/api/auth/passkey/options", json={}).get_json()
        revoked_payload = {"ceremony_id": options["ceremony_id"], "credential": authenticator.assertion(options["publicKey"]["challenge"])}
        revoked = admin.post("/api/admin/passkeys/revoke", json={"credential_id": authenticator.credential_id_b64})
        self.assertEqual(revoked.status_code, 200)
        rejected = user.post("/api/auth/passkey/verify", json=revoked_payload)
        self.assertEqual((rejected.status_code, rejected.get_json()["code"]), (401, "PASSKEY_UNKNOWN"))
        self.assertEqual(user.post("/api/auth/passkey/options", json={}).status_code, 404)
        self.password_login(user)

    def test_challenge_expiry_same_origin_and_rate_limit(self):
        now = [100.0]
        registry = CeremonyRegistry(ttl=5, clock=lambda: now[0])
        token = registry.issue("authentication", b"challenge", "owner")
        now[0] = 106.0
        self.assertIsNone(registry.consume(token, "authentication"))

        client = self.client()
        blocked = client.post("/api/auth/passkey/options", json={}, headers={"Origin": "https://evil.example"})
        self.assertEqual((blocked.status_code, blocked.get_json()["code"]), (403, "BAD_ORIGIN"))
        for _ in range(12):
            response = client.post("/api/auth/passkey/options", json={}, headers={"Origin": "http://localhost"})
            self.assertEqual(response.status_code, 404)
        limited = client.post("/api/auth/passkey/options", json={}, headers={"Origin": "http://localhost"})
        self.assertEqual((limited.status_code, limited.get_json()["code"]), (429, "RATE_LIMITED"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
