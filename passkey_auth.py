from __future__ import annotations

import json
import os
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from flask import request, send_file, session, url_for

try:
    from webauthn import (
        base64url_to_bytes,
        generate_authentication_options,
        generate_registration_options,
        options_to_json,
        verify_authentication_response,
        verify_registration_response,
    )
    from webauthn.helpers import bytes_to_base64url
    from webauthn.helpers.structs import (
        AttestationConveyancePreference,
        AuthenticatorAttachment,
        AuthenticatorSelectionCriteria,
        AuthenticatorTransport,
        PublicKeyCredentialDescriptor,
        ResidentKeyRequirement,
        UserVerificationRequirement,
    )
    WEBAUTHN_AVAILABLE = True
except Exception:
    WEBAUTHN_AVAILABLE = False


STORE_KEY = "admin_passkeys_v1"
DEFAULT_RP_NAME = "本福丸訂製"
MAX_CREDENTIALS = 10
CHALLENGE_TTL_SECONDS = 300
_INSTALLED = False


@dataclass(frozen=True)
class PasskeyConfig:
    rp_id: str
    origin: str
    rp_name: str
    owner_id: str
    configured: bool

    @classmethod
    def from_env(cls):
        rp_id = (os.environ.get("WEBAUTHN_RP_ID") or "").strip().lower()
        origin = (os.environ.get("WEBAUTHN_ORIGIN") or "").strip().rstrip("/")
        rp_name = (os.environ.get("WEBAUTHN_RP_NAME") or DEFAULT_RP_NAME).strip() or DEFAULT_RP_NAME
        configured = bool(WEBAUTHN_AVAILABLE and rp_id and origin)
        if configured:
            try:
                parsed = urlsplit(origin)
                host = (parsed.hostname or "").lower()
                local_http = parsed.scheme == "http" and host in ("localhost", "127.0.0.1")
                valid_origin = (
                    parsed.scheme == "https" or local_http
                ) and bool(host) and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.path in ("", "/")
                valid_rp = "://" not in rp_id and "/" not in rp_id and ":" not in rp_id and (host == rp_id or host.endswith("." + rp_id))
                configured = bool(valid_origin and valid_rp)
            except Exception:
                configured = False
        owner_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{rp_id or 'unconfigured'}.benfuwan.admin"))
        return cls(rp_id=rp_id, origin=origin, rp_name=rp_name, owner_id=owner_id, configured=configured)


class CeremonyRegistry:
    def __init__(self, ttl=CHALLENGE_TTL_SECONDS, clock=time.monotonic):
        self.ttl = ttl
        self.clock = clock
        self._lock = threading.RLock()
        self._records = {}

    def issue(self, kind, challenge, owner_id):
        now = self.clock()
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._records = {key: value for key, value in self._records.items() if value["expires_at"] > now}
            self._records[token] = {
                "kind": kind,
                "challenge": bytes(challenge),
                "owner_id": owner_id,
                "expires_at": now + self.ttl,
            }
        return token

    def consume(self, token, kind):
        if not isinstance(token, str) or not token:
            return None
        with self._lock:
            record = self._records.pop(token, None)
        if not record or record["kind"] != kind or record["expires_at"] <= self.clock():
            return None
        return record

    def clear(self):
        with self._lock:
            self._records.clear()


class PasskeyService:
    def __init__(self, app_module):
        self.app_module = app_module
        self.config = PasskeyConfig.from_env()
        self.filepath = (os.environ.get("ADMIN_PASSKEYS_FILE") or "admin_passkeys.json").strip() or "admin_passkeys.json"
        self.ceremonies = CeremonyRegistry()
        self._credential_lock = threading.RLock()

    def _default_document(self):
        return {"version": 1, "owner_id": self.config.owner_id, "credentials": []}

    def _load(self):
        data = self.app_module.cloud_get_json(STORE_KEY, self.filepath, self._default_document())
        if not isinstance(data, dict) or data.get("version") != 1 or data.get("owner_id") != self.config.owner_id:
            raise RuntimeError("Passkey credential store 格式不符")
        credentials = data.get("credentials")
        if not isinstance(credentials, list):
            raise RuntimeError("Passkey credential store 格式不符")
        return data

    def _save(self, data):
        self.app_module.cloud_save_json(STORE_KEY, self.filepath, data)

    def _error(self, code, message, status):
        return self.app_module.no_cache_json({"status": "error", "code": code, "msg": message}, status)

    def _require_config(self):
        if self.config.configured:
            return None
        return self._error("PASSKEY_NOT_CONFIGURED", "Face ID 登入尚未完成伺服器設定，請使用密碼登入。", 503)

    @staticmethod
    def _safe_transports(values):
        allowed = {item.value for item in AuthenticatorTransport} if WEBAUTHN_AVAILABLE else set()
        return [str(value) for value in (values or []) if str(value) in allowed]

    @staticmethod
    def _public_credential(row):
        return {
            "credential_id": row.get("credential_id", ""),
            "device_label": row.get("device_label") or "Passkey",
            "transports": list(row.get("transports") or []),
            "created_at": row.get("created_at"),
            "last_used_at": row.get("last_used_at"),
        }

    def _descriptor(self, row):
        transports = []
        for value in self._safe_transports(row.get("transports")):
            try:
                transports.append(AuthenticatorTransport(value))
            except ValueError:
                pass
        return PublicKeyCredentialDescriptor(
            id=base64url_to_bytes(row["credential_id"]),
            transports=transports or None,
        )

    def login_status(self):
        if not self.config.configured:
            return self.app_module.no_cache_json({"status": "success", "configured": False, "has_credentials": False})
        try:
            with self._credential_lock:
                credentials = self._load()["credentials"]
            return self.app_module.no_cache_json({"status": "success", "configured": True, "has_credentials": bool(credentials)})
        except Exception:
            return self._error("PASSKEY_STORE_UNAVAILABLE", "Face ID 登入目前暫時不可用，請使用密碼登入。", 503)

    def list_credentials(self):
        if not session.get("logged_in"):
            return self._error("NOT_LOGGED_IN", "未登入", 401)
        if not self.config.configured:
            return self.app_module.no_cache_json({"status": "success", "configured": False, "credentials": []})
        try:
            with self._credential_lock:
                rows = self._load()["credentials"]
            return self.app_module.no_cache_json({
                "status": "success",
                "configured": True,
                "credentials": [self._public_credential(row) for row in rows],
            })
        except Exception:
            return self._error("PASSKEY_STORE_UNAVAILABLE", "無法讀取 Face ID 登入設定，請稍後再試。", 503)

    def registration_options(self):
        if not session.get("logged_in"):
            return self._error("NOT_LOGGED_IN", "未登入", 401)
        missing = self._require_config()
        if missing:
            return missing
        try:
            with self._credential_lock:
                rows = self._load()["credentials"]
            if len(rows) >= MAX_CREDENTIALS:
                return self._error("PASSKEY_LIMIT", "已達 Passkey 裝置上限，請先移除不用的裝置。", 409)
            options = generate_registration_options(
                rp_id=self.config.rp_id,
                rp_name=self.config.rp_name,
                user_id=self.config.owner_id.encode("ascii"),
                user_name="admin",
                user_display_name="本福丸管理員",
                timeout=CHALLENGE_TTL_SECONDS * 1000,
                attestation=AttestationConveyancePreference.NONE,
                authenticator_selection=AuthenticatorSelectionCriteria(
                    authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                    resident_key=ResidentKeyRequirement.REQUIRED,
                    require_resident_key=True,
                    user_verification=UserVerificationRequirement.REQUIRED,
                ),
                exclude_credentials=[self._descriptor(row) for row in rows],
            )
            ceremony_id = self.ceremonies.issue("registration", options.challenge, self.config.owner_id)
            return self.app_module.no_cache_json({
                "status": "success",
                "ceremony_id": ceremony_id,
                "publicKey": json.loads(options_to_json(options)),
            })
        except Exception:
            return self._error("PASSKEY_OPTIONS_FAILED", "無法開始 Face ID 設定，請稍後再試。", 500)

    def verify_registration(self):
        if not session.get("logged_in"):
            return self._error("NOT_LOGGED_IN", "未登入", 401)
        missing = self._require_config()
        if missing:
            return missing
        body = request.get_json(silent=True) or {}
        record = self.ceremonies.consume(body.get("ceremony_id"), "registration")
        if not record or record["owner_id"] != self.config.owner_id:
            return self._error("CHALLENGE_INVALID", "Face ID 設定已過期或已使用，請重新開始。", 400)
        credential = body.get("credential")
        if not isinstance(credential, dict):
            return self._error("BAD_CREDENTIAL", "Face ID 設定資料格式錯誤。", 400)
        try:
            verified = verify_registration_response(
                credential=credential,
                expected_challenge=record["challenge"],
                expected_rp_id=self.config.rp_id,
                expected_origin=self.config.origin,
                require_user_verification=True,
            )
            credential_id = bytes_to_base64url(verified.credential_id)
            response = credential.get("response") or {}
            transports = self._safe_transports(response.get("transports"))
            label = str(body.get("device_label") or "Face ID / Passkey").strip()[:80] or "Face ID / Passkey"
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            with self._credential_lock:
                data = self._load()
                rows = data["credentials"]
                if any(row.get("credential_id") == credential_id for row in rows):
                    return self._error("PASSKEY_EXISTS", "這個 Passkey 已經啟用。", 409)
                if len(rows) >= MAX_CREDENTIALS:
                    return self._error("PASSKEY_LIMIT", "已達 Passkey 裝置上限。", 409)
                rows.append({
                    "credential_id": credential_id,
                    "public_key": bytes_to_base64url(verified.credential_public_key),
                    "sign_count": int(verified.sign_count),
                    "transports": transports,
                    "created_at": now,
                    "last_used_at": None,
                    "device_label": label,
                })
                self._save(data)
            return self.app_module.no_cache_json({"status": "success", "credential": self._public_credential(rows[-1])})
        except Exception:
            return self._error("PASSKEY_VERIFY_FAILED", "Face ID 設定驗證失敗，請重新開始。", 400)

    def authentication_options(self):
        missing = self._require_config()
        if missing:
            return missing
        try:
            with self._credential_lock:
                rows = self._load()["credentials"]
            if not rows:
                return self._error("PASSKEY_NOT_REGISTERED", "此裝置尚未設定 Face ID 登入，請先使用密碼登入後到後台啟用。", 404)
            options = generate_authentication_options(
                rp_id=self.config.rp_id,
                timeout=CHALLENGE_TTL_SECONDS * 1000,
                allow_credentials=[self._descriptor(row) for row in rows],
                user_verification=UserVerificationRequirement.REQUIRED,
            )
            ceremony_id = self.ceremonies.issue("authentication", options.challenge, self.config.owner_id)
            return self.app_module.no_cache_json({
                "status": "success",
                "ceremony_id": ceremony_id,
                "publicKey": json.loads(options_to_json(options)),
            })
        except Exception:
            return self._error("PASSKEY_OPTIONS_FAILED", "無法開始 Face ID 登入，請改用密碼登入。", 500)

    def verify_authentication(self):
        missing = self._require_config()
        if missing:
            return missing
        body = request.get_json(silent=True) or {}
        record = self.ceremonies.consume(body.get("ceremony_id"), "authentication")
        if not record or record["owner_id"] != self.config.owner_id:
            return self._error("CHALLENGE_INVALID", "Face ID 登入已過期或已使用，請重新再試。", 400)
        credential = body.get("credential")
        credential_id = credential.get("id") if isinstance(credential, dict) else None
        if not isinstance(credential_id, str) or not credential_id:
            return self._error("BAD_CREDENTIAL", "Face ID 登入資料格式錯誤。", 400)
        try:
            with self._credential_lock:
                data = self._load()
                row = next((item for item in data["credentials"] if item.get("credential_id") == credential_id), None)
                if not row:
                    return self._error("PASSKEY_UNKNOWN", "這個 Passkey 已失效，請改用密碼登入。", 401)
                verified = verify_authentication_response(
                    credential=credential,
                    expected_challenge=record["challenge"],
                    expected_rp_id=self.config.rp_id,
                    expected_origin=self.config.origin,
                    credential_public_key=base64url_to_bytes(row["public_key"]),
                    credential_current_sign_count=int(row.get("sign_count") or 0),
                    require_user_verification=True,
                )
                row["sign_count"] = int(verified.new_sign_count)
                row["last_used_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._save(data)
            session.clear()
            session["logged_in"] = True
            session["auth_method"] = "passkey"
            return self.app_module.no_cache_json({"status": "success", "redirect": url_for("admin_page")})
        except Exception:
            return self._error("PASSKEY_VERIFY_FAILED", "Face ID 驗證失敗，請重新再試或使用密碼登入。", 401)

    def revoke(self):
        if not session.get("logged_in"):
            return self._error("NOT_LOGGED_IN", "未登入", 401)
        missing = self._require_config()
        if missing:
            return missing
        credential_id = str((request.get_json(silent=True) or {}).get("credential_id") or "").strip()
        if not credential_id:
            return self._error("BAD_CREDENTIAL", "缺少 Passkey 識別資料。", 400)
        try:
            with self._credential_lock:
                data = self._load()
                before = len(data["credentials"])
                data["credentials"] = [row for row in data["credentials"] if row.get("credential_id") != credential_id]
                if len(data["credentials"]) == before:
                    return self._error("PASSKEY_UNKNOWN", "找不到這個 Passkey。", 404)
                self._save(data)
            return self.app_module.no_cache_json({"status": "success"})
        except Exception:
            return self._error("PASSKEY_REVOKE_FAILED", "無法移除 Passkey，請稍後再試。", 500)


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return app_module.app.extensions.get("benfuwan_passkeys")
    _INSTALLED = True
    app = app_module.app
    service = PasskeyService(app_module)
    app.extensions["benfuwan_passkeys"] = service

    original_login = app.view_functions["login_page"]

    def passkey_login_page():
        if request.method == "POST":
            return original_login()
        response = send_file(Path(__file__).resolve().parent / "login.html")
        response.headers["Cache-Control"] = "no-store"
        return response

    app.view_functions["login_page"] = passkey_login_page
    app.add_url_rule("/api/auth/passkey/status", "passkey_login_status", service.login_status, methods=["GET"])
    app.add_url_rule("/api/auth/passkey/options", "passkey_auth_options", service.authentication_options, methods=["POST"])
    app.add_url_rule("/api/auth/passkey/verify", "passkey_auth_verify", service.verify_authentication, methods=["POST"])
    app.add_url_rule("/api/admin/passkeys", "admin_passkeys", service.list_credentials, methods=["GET"])
    app.add_url_rule("/api/admin/passkey/register/options", "admin_passkey_register_options", service.registration_options, methods=["POST"])
    app.add_url_rule("/api/admin/passkey/register/verify", "admin_passkey_register_verify", service.verify_registration, methods=["POST"])
    app.add_url_rule("/api/admin/passkeys/revoke", "admin_passkey_revoke", service.revoke, methods=["POST"])
    return service
