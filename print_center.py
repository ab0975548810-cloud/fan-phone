"""Print Phase 3.1 A5 Desktop domain, safe vendor handoff, and callbacks."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from flask import Response, request, session, url_for

from print_store import ACTIVE_STATES, PrintConflict, PrintStore, utcnow
from print_vendor import VendorAmbiguous, VendorDisabled, VendorError, YunPrintClient


_INSTALLED = False
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{16,100}$")
TERMINAL = {"COMPLETED", "CANCELED", "FAILED"}
STATE_LABELS = {
    "PREPARED": "待送出", "SENDING": "送出中", "QUEUED": "等待銳印確認",
    "STARTING": "舊版啟動狀態", "PRINTING": "打印中", "CANCELING": "取消中",
    "COMPLETED": "完成", "CANCELED": "已取消", "FAILED": "失敗", "UNKNOWN": "狀態待確認",
}
CALLBACK_STATES = {
    "1": "PRINTING", "2": "COMPLETED", "3": "CANCELED",
    "4": "FAILED", "5": "FAILED", "6": "FAILED", "7": "FAILED",
    "8": "FAILED", "11": "FAILED",
}
A5_DESKTOP_METADATA = {
    "workflow": "desktop_manual_confirmation",
    "print_area_mm": {"width": 200, "height": 230},
    "coordinate_origin": "治具右下角",
    "production_format": "PNG",
    "supported_formats": ["PNG", "JPG", "TIF"],
    "transparent_png": True,
    "color_space": "RGB",
    "icc_profile": False,
    "recommended_max_bytes": 20 * 1024 * 1024,
    "recommended_max_pixels": {"width": 8000, "height": 8000},
    "recommended_dpi": {"min": 300, "max": 900},
    "channel": "1",
    "spot_color_managed_by_operator": True,
}


class PrintError(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code = code
        self.status = status


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _payload_hash(operation, identity):
    return _hash(json.dumps([operation, identity], ensure_ascii=False, separators=(",", ":")))


def _as_decimal(value, name, *, positive=False):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise PrintError("BAD_PROFILE", f"{name} 格式錯誤", 400)
    if not number.is_finite() or (positive and number <= 0) or number < -10000 or number > 10000:
        raise PrintError("BAD_PROFILE", f"{name} 超出範圍", 400)
    return float(number.quantize(Decimal(".001")))


def _safe_payload(payload):
    allowed = ("device_id", "taskid", "status", "msg", "time", "once", "order_id")
    return {key: str(payload.get(key, ""))[:500] for key in allowed if key in payload}


def _public_job(job):
    if not job:
        return None
    hidden = {"artwork_token_nonce", "artwork_path"}
    row = {key: value for key, value in job.items() if key not in hidden}
    row["state_label"] = STATE_LABELS.get(row.get("state"), "未知")
    return row


class PrintService:
    def __init__(self, app_module, *, store=None, client=None):
        self.app = app_module
        self.store = store or PrintStore(app_module)
        self.client = client or YunPrintClient()

    @property
    def vendor_ready(self):
        if not self.client.ready:
            return False
        secret = os.environ.get("PRINT_ARTWORK_TOKEN_SECRET", "").strip()
        public_url = os.environ.get("PRINT_PUBLIC_BASE_URL", "").strip()
        try:
            parsed = urlsplit(public_url)
        except ValueError:
            return False
        return bool(len(secret) >= 32 and parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password)

    def _order(self, order_id):
        order = self.app.commerce.store.order(order_id)
        if not order:
            raise PrintError("ORDER_NOT_FOUND", "找不到這筆訂單", 404)
        return order

    def _finance(self, order_id):
        return (self.app.commerce.read().get("order_finance") or {}).get(order_id) or {}

    @staticmethod
    def _profile_suggestion(shop, model_id, style_id):
        """Return only explicit model calibration; never use style fallbacks."""
        if not isinstance(shop, dict):
            return None
        model = next((row for row in (shop.get("models") or [])
                      if str(row.get("id") or "") == str(model_id or "")), None)
        style = next((row for row in (shop.get("styles") or [])
                      if str(row.get("id") or "") == str(style_id or "")), None)
        required = ("print_w", "print_h", "print_x", "print_y")
        if not model or not style or any(name not in model or model.get(name) in (None, "") for name in required):
            return None
        try:
            numbers = {name: Decimal(str(model[name])) for name in required}
        except (InvalidOperation, TypeError, ValueError):
            return None
        if any(not value.is_finite() or value < -10000 or value > 10000 for value in numbers.values()):
            return None
        if numbers["print_w"] <= 0 or numbers["print_h"] <= 0:
            return None
        values = {name: float(value) for name, value in numbers.items()}
        return {
            "width_mm": values["print_w"], "height_mm": values["print_h"],
            "left_mm": values["print_x"], "top_mm": values["print_y"],
            "source": f"來自 {model.get('name') or model_id} 蒙版設定",
            "notice": f"僅為建議值；請依 {style.get('name') or style_id} 實體殼校正後儲存確認",
        }

    def _assert_order_printable(self, order, *, needs_artwork=True):
        if order.get("status") == "作廢":
            raise PrintError("VOID_ORDER", "作廢訂單不可建立或啟動列印任務")
        if needs_artwork and not order.get("print_path"):
            raise PrintError("PRINT_FILE_REQUIRED", "缺少高清生產圖，無法準備列印")

    def _download_artwork(self, path):
        if not path:
            raise PrintError("PRINT_FILE_REQUIRED", "找不到高清生產圖")
        if self.app.USE_SUPABASE:
            raw = self.app.SUPABASE.storage.from_(self.app.SUPABASE_PRIVATE_BUCKET).download(path)
        else:
            full = os.path.join(self.app.SAVE_DIR, path)
            try:
                with open(full, "rb") as handle:
                    raw = handle.read()
            except OSError as exc:
                raise PrintError("PRINT_FILE_MISSING", "高清生產圖不存在", 404) from exc
        if not raw or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise PrintError("PRINT_FILE_INVALID", "高清生產圖不是有效 PNG", 422)
        return raw

    def _token_secret(self):
        configured = os.environ.get("PRINT_ARTWORK_TOKEN_SECRET", "").strip()
        if configured:
            if self.client.enabled and len(configured) < 32:
                raise PrintError("PRINT_TOKEN_NOT_CONFIGURED", "生產圖存取密鑰至少需要 32 個字元", 503)
            return configured.encode("utf-8")
        if self.client.enabled:
            raise PrintError("PRINT_TOKEN_NOT_CONFIGURED", "啟用雲打印前必須明確設定生產圖存取密鑰", 503)
        return str(self.app.app.secret_key).encode("utf-8")

    def artwork_token(self, job):
        expires = job.get("artwork_token_expires_at")
        if not expires:
            raise PrintError("ARTWORK_TOKEN_INACTIVE", "生產圖連結尚未啟用", 403)
        stamp = int(datetime.fromisoformat(str(expires).replace("Z", "+00:00")).timestamp())
        material = f"{job['id']}|{job['artwork_path']}|{job['artwork_token_nonce']}|{stamp}"
        digest = hmac.new(self._token_secret(), material.encode("utf-8"), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")

    def verify_artwork_token(self, job, supplied):
        if not job or job.get("state") in TERMINAL or not job.get("artwork_token_expires_at"):
            return False
        try:
            expiry = datetime.fromisoformat(str(job["artwork_token_expires_at"]).replace("Z", "+00:00"))
        except ValueError:
            return False
        if expiry <= datetime.now(timezone.utc):
            return False
        try:
            expected = self.artwork_token(job)
        except PrintError:
            return False
        return bool(supplied and hmac.compare_digest(expected, str(supplied)))

    def prepare(self, order_id, key):
        fingerprint = _payload_hash("prepare", order_id)
        prior = self.store.request(key)
        if prior:
            if prior["operation"] != "prepare" or prior["request_hash"] != fingerprint:
                raise PrintConflict("IDEMPOTENCY_CONFLICT", "同一操作識別已用於不同列印操作")
            job = self.store.job(prior.get("job_id"))
            if job:
                return job
        order = self._order(order_id)
        self._assert_order_printable(order)
        raw = self._download_artwork(order["print_path"])
        finance = self._finance(order_id)
        sku_id = str(finance.get("sku_id") or "")
        profile = self.store.profile(sku_id)
        job = self.store.create_job(order, sku_id, profile, hashlib.sha256(raw).hexdigest(), secrets.token_urlsafe(18))
        owner, _ = self.store.claim_request(key, "prepare", job["id"], fingerprint)
        if owner:
            self.store.finish_request(key, "COMPLETED", {"job_id": job["id"]})
        return self.store.job(job["id"])

    def save_profile(self, payload):
        sku_id = str(payload.get("sku_id") or "").strip()
        if not sku_id or len(sku_id) > 200:
            raise PrintError("BAD_PROFILE", "缺少 SKU 識別", 400)
        try:
            copies = int(payload.get("copies", 1))
        except (TypeError, ValueError):
            raise PrintError("BAD_PROFILE", "列印份數格式錯誤", 400)
        if copies < 1 or copies > 99:
            raise PrintError("BAD_PROFILE", "列印份數須為 1 至 99", 400)
        profile = {
            "sku_id": sku_id,
            "width_mm": _as_decimal(payload.get("width_mm"), "寬度", positive=True),
            "height_mm": _as_decimal(payload.get("height_mm"), "高度", positive=True),
            "left_mm": _as_decimal(payload.get("left_mm", 0), "左偏移"),
            "top_mm": _as_decimal(payload.get("top_mm", 0), "上偏移"),
            "copies": copies,
            "spot_color": "",
            "channel": "1",
            "angle": _as_decimal(payload.get("angle", 0), "角度"),
        }
        return self.store.save_profile(profile)

    def snapshot_profile(self, job_id, key):
        job = self.store.job(job_id)
        if not job:
            raise PrintError("JOB_NOT_FOUND", "找不到列印任務", 404)
        fingerprint = _payload_hash("profile_snapshot", job_id)
        owner, prior = self.store.claim_request(key, "profile_snapshot", job_id, fingerprint)
        if not owner:
            return self.store.job(job_id)
        if job["state"] != "PREPARED" or job.get("vendor_taskid"):
            self.store.finish_request(key, "FAILED", {"code": "PROFILE_LOCKED"})
            raise PrintError("PROFILE_LOCKED", "只有尚未送出的任務可明確套用列印參數")
        profile = self.store.profile(job.get("sku_id"))
        if not profile:
            self.store.finish_request(key, "FAILED", {"code": "PROFILE_MISSING"})
            raise PrintError("PROFILE_MISSING", "列印參數未設定")
        fields = {name: profile[name] for name in ("width_mm", "height_mm", "left_mm", "top_mm", "copies", "spot_color", "channel", "angle")}
        fields["profile_complete"] = True
        updated = self.store.patch_job(job_id, fields, ("PREPARED",))
        self.store.finish_request(key, "COMPLETED", {"job_id": job_id})
        return updated

    def _existing_operation(self, key, operation, job_id, fingerprint):
        prior = self.store.request(key)
        if not prior:
            return None
        if prior["operation"] != operation or prior["request_hash"] != fingerprint or str(prior.get("job_id") or "") != job_id:
            raise PrintConflict("IDEMPOTENCY_CONFLICT", "同一操作識別已用於不同列印操作")
        return self.store.job(job_id)

    def _base_url(self):
        configured = os.environ.get("PRINT_PUBLIC_BASE_URL", "").strip()
        if self.client.enabled:
            try:
                parsed = urlsplit(configured)
            except ValueError:
                parsed = None
            if not parsed or parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                raise PrintError("PRINT_PUBLIC_URL_INVALID", "啟用雲打印前必須明確設定無帳密的 HTTPS public URL", 503)
            base = configured.rstrip("/")
        else:
            base = (configured or request.host_url).strip().rstrip("/")
        return base

    def send(self, job_id, key):
        fingerprint = _payload_hash("send", job_id)
        replay = self._existing_operation(key, "send", job_id, fingerprint)
        if replay:
            return replay
        job = self.store.job(job_id)
        if not job:
            raise PrintError("JOB_NOT_FOUND", "找不到列印任務", 404)
        order = self._order(job["order_id"])
        self._assert_order_printable(order)
        if job["state"] == "UNKNOWN":
            raise PrintError("RECONCILE_REQUIRED", "前次送出結果不明，必須先查核，禁止直接重送")
        if job["state"] != "PREPARED":
            raise PrintError("BAD_PRINT_STATE", "目前任務狀態不可送到銳印")
        if not job.get("profile_complete"):
            raise PrintError("PROFILE_MISSING", "列印參數未設定，不可送到銳印")
        if not self.vendor_ready:
            raise PrintError("VENDOR_NOT_READY", "雲打印憑證、HTTPS public URL 或生產圖密鑰尚未完整設定", 503)
        base = self._base_url()
        self._token_secret()
        owner, prior = self.store.claim_request(key, "send", job_id, fingerprint)
        if not owner:
            return self.store.job(job_id)
        nonce = secrets.token_urlsafe(18)
        expiry = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        claimed = self.store.patch_job(job_id, {
            "state": "SENDING", "artwork_token_nonce": nonce,
            "artwork_token_expires_at": expiry, "device_id": self.client.device_id,
            "last_error": None, "ambiguous_operation": None,
        }, ("PREPARED",))
        if not claimed:
            self.store.finish_request(key, "FAILED", {"code": "CONCURRENT_OPERATION"})
            raise PrintError("CONCURRENT_OPERATION", "另一個列印操作正在執行")
        try:
            self._assert_order_printable(self._order(claimed["order_id"]))
        except PrintError:
            self.store.patch_job(job_id, {"state": "PREPARED", "last_error": "送出前訂單已作廢"}, ("SENDING",))
            self.store.finish_request(key, "FAILED", {"job_id": job_id, "code": "VOID_ORDER"})
            raise
        token = self.artwork_token(claimed)
        file_url = f"{base}/api/print/artwork/{claimed['id']}/{token}"
        callback_url = f"{base}/api/print/callback"
        try:
            result = self.client.receive_task(claimed, file_url, callback_url)
            taskid = str((result or {}).get("taskid") or (result or {}).get("task_id") or "").strip()
            if not taskid:
                raise VendorAmbiguous("雲打印未回傳可確認的 taskid")
        except VendorAmbiguous as exc:
            job = self.store.patch_job(job_id, {"state": "UNKNOWN", "ambiguous_operation": "receiveTask", "last_error": str(exc)[:500]}, ("SENDING",))
            self.store.finish_request(key, "UNKNOWN", {"job_id": job_id, "code": "RECONCILE_REQUIRED"})
            raise PrintError("RECONCILE_REQUIRED", "送出結果不明，任務已鎖定；請按查核，不可重送", 503)
        except (VendorDisabled, VendorError) as exc:
            job = self.store.patch_job(job_id, {"state": "PREPARED", "last_error": str(exc)[:500]}, ("SENDING",))
            self.store.finish_request(key, "FAILED", {"job_id": job_id, "code": "VENDOR_REJECTED"})
            raise PrintError("VENDOR_REJECTED", str(exc), 502)
        except Exception as exc:
            self.app.app.logger.exception("Unexpected receiveTask failure for %s", job_id)
            job = self.store.patch_job(job_id, {"state": "UNKNOWN", "ambiguous_operation": "receiveTask", "last_error": "送出發生未預期中斷，必須先查核"}, ("SENDING",))
            self.store.finish_request(key, "UNKNOWN", {"job_id": job_id, "code": "RECONCILE_REQUIRED"})
            raise PrintError("RECONCILE_REQUIRED", "送出結果無法確認，任務已鎖定；請先查核", 503) from exc
        raw_status = str(result.get("status", "0"))
        job = self.store.patch_job(job_id, {
            "state": CALLBACK_STATES.get(raw_status, "QUEUED"), "vendor_taskid": taskid,
            "vendor_raw_status": raw_status, "vendor_raw_message": str(result.get("msg") or "")[:500],
            "sent_at": utcnow(), "ambiguous_operation": None,
        }, ("SENDING",))
        self.store.finish_request(key, "COMPLETED", {"job_id": job_id, "vendor_taskid": taskid})
        return job

    def start(self, job_id, key):
        # Kept as a fail-closed compatibility endpoint for old clients. A5
        # Desktop starts only after the operator confirms inside Ruiyin.
        raise PrintError(
            "DESKTOP_MANUAL_CONFIRMATION",
            "A5 桌面機請在銳印軟體人工確認；網站不會啟動實體打印",
            409,
        )

    def cancel(self, job_id, key):
        fingerprint = _payload_hash("cancel", job_id)
        replay = self._existing_operation(key, "cancel", job_id, fingerprint)
        if replay:
            return replay
        job = self.store.job(job_id)
        if not job:
            raise PrintError("JOB_NOT_FOUND", "找不到列印任務", 404)
        if job["state"] == "PREPARED":
            owner, _ = self.store.claim_request(key, "cancel", job_id, fingerprint)
            if not owner:
                return self.store.job(job_id)
            updated = self.store.patch_job(job_id, {"state": "CANCELED", "canceled_at": utcnow()}, ("PREPARED",))
            self.store.finish_request(key, "COMPLETED", {"job_id": job_id})
            return updated
        if job["state"] != "QUEUED":
            raise PrintError("BAD_PRINT_STATE", "只能取消尚未開始打印的等待任務")
        if not self.client.ready:
            raise PrintError("VENDOR_DISABLED", "雲打印未啟用或設備憑證未設定", 503)
        owner, _ = self.store.claim_request(key, "cancel", job_id, fingerprint)
        if not owner:
            return self.store.job(job_id)
        claimed = self.store.patch_job(job_id, {"state": "CANCELING", "last_error": None}, ("QUEUED",))
        if not claimed:
            self.store.finish_request(key, "FAILED", {"code": "CONCURRENT_OPERATION"})
            raise PrintError("CONCURRENT_OPERATION", "另一個列印操作正在執行")
        try:
            result = self.client.cancel_task(claimed["vendor_taskid"])
            if str((result or {}).get("status") or "") != "3":
                raise VendorAmbiguous("雲打印未回傳明確已取消狀態")
        except VendorAmbiguous as exc:
            updated = self.store.patch_job(job_id, {"state": "UNKNOWN", "ambiguous_operation": "cancelTask", "last_error": str(exc)[:500]}, ("CANCELING",))
            self.store.finish_request(key, "UNKNOWN", {"job_id": job_id, "code": "RECONCILE_REQUIRED"})
            raise PrintError("RECONCILE_REQUIRED", "取消結果不明，請先查核", 503)
        except (VendorDisabled, VendorError) as exc:
            updated = self.store.patch_job(job_id, {"state": "QUEUED", "last_error": str(exc)[:500]}, ("CANCELING",))
            self.store.finish_request(key, "FAILED", {"job_id": job_id, "code": "VENDOR_REJECTED"})
            raise PrintError("VENDOR_REJECTED", str(exc), 502)
        except Exception as exc:
            self.app.app.logger.exception("Unexpected cancelTask failure for %s", job_id)
            updated = self.store.patch_job(job_id, {"state": "UNKNOWN", "ambiguous_operation": "cancelTask", "last_error": "取消發生未預期中斷，必須先查核"}, ("CANCELING",))
            self.store.finish_request(key, "UNKNOWN", {"job_id": job_id, "code": "RECONCILE_REQUIRED"})
            raise PrintError("RECONCILE_REQUIRED", "取消結果無法確認，請先查核", 503) from exc
        updated = self.store.patch_job(job_id, {
            "state": "CANCELED", "canceled_at": utcnow(), "ambiguous_operation": None,
            "vendor_raw_status": str(result.get("status", "3")), "vendor_raw_message": str(result.get("msg") or "")[:500],
        }, ("CANCELING",))
        self.store.finish_request(key, "COMPLETED", {"job_id": job_id})
        return updated

    @staticmethod
    def _task_rows(value):
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
        if isinstance(value, dict):
            for name in ("list", "tasks", "rows", "data"):
                if name in value:
                    return PrintService._task_rows(value[name])
            return [value] if ("taskid" in value or "order_id" in value) else []
        return []

    def reconcile(self, job_id, key):
        fingerprint = _payload_hash("reconcile", job_id)
        replay = self._existing_operation(key, "reconcile", job_id, fingerprint)
        if replay:
            return replay
        job = self.store.job(job_id)
        if not job:
            raise PrintError("JOB_NOT_FOUND", "找不到列印任務", 404)
        if not self.client.ready:
            raise PrintError("VENDOR_DISABLED", "雲打印未啟用或設備憑證未設定", 503)
        owner, _ = self.store.claim_request(key, "reconcile", job_id, fingerprint)
        if not owner:
            return self.store.job(job_id)
        try:
            rows = self._task_rows(self.client.get_all_tasks())
        except (VendorAmbiguous, VendorDisabled, VendorError) as exc:
            self.store.finish_request(key, "FAILED", {"job_id": job_id, "code": "RECONCILE_FAILED"})
            raise PrintError("RECONCILE_FAILED", "目前無法完成雲端查核，任務維持原狀", 502) from exc
        match = next((row for row in rows if str(row.get("taskid") or row.get("task_id") or "") == str(job.get("vendor_taskid") or "")), None)
        if not match:
            match = next((row for row in rows if str(row.get("order_id") or "") == job["order_id"]), None)
        fields = {"last_reconciled_at": utcnow(), "reconcile_count": int(job.get("reconcile_count") or 0) + 1}
        if match:
            status = str(match.get("status", "0"))
            taskid = str(match.get("taskid") or match.get("task_id") or job.get("vendor_taskid") or "")
            fields.update({
                "vendor_taskid": taskid or None,
                "vendor_raw_status": status,
                "vendor_raw_message": str(match.get("msg") or "")[:500],
                "state": CALLBACK_STATES.get(status, "QUEUED"),
                "ambiguous_operation": None,
                "last_error": None,
            })
        elif job["state"] not in TERMINAL:
            fields.update({"state": "UNKNOWN", "last_error": "雲端未列印佇列找不到此任務；不可據此判定未建立或已完成"})
        updated = self.store.patch_job(job_id, fields)
        self.store.finish_request(key, "COMPLETED", {"job_id": job_id, "found": bool(match)})
        if match:
            self._sync_order(updated)
        return updated

    def _sync_order(self, job):
        target = "列印中" if job.get("state") == "PRINTING" else ("已完成" if job.get("state") == "COMPLETED" else "")
        if not target:
            return
        order = self.app.commerce.store.order(job["order_id"])
        if not order or order.get("status") == "作廢":
            return
        if target == "列印中" and order.get("status") == "已完成":
            return
        try:
            self.app.commerce.action(job["order_id"], "print_sync", target, key=f"print:{job['id']}:{target}")
        except Exception:
            self.app.app.logger.exception("Print callback order status sync failed for %s", job["id"])

    def task_callback(self, payload):
        if not self.client.valid_callback(payload):
            raise PrintError("INVALID_SIGNATURE", "簽名驗證失敗", 403)
        taskid = str(payload.get("taskid") or "").strip()
        if not taskid:
            raise PrintError("BAD_CALLBACK", "缺少 taskid", 400)
        job = self.store.job_for_task(taskid)
        if not job:
            raise PrintError("JOB_NOT_FOUND", "找不到對應列印任務", 404)
        status = str(payload.get("status") or "")
        msg = str(payload.get("msg") or "")[:500]
        # The vendor signature covers its auth tuple. Consume that tuple once so
        # a captured callback cannot be replayed with altered task/status fields.
        event_key = _hash(json.dumps(["task-auth", payload.get("device_id"), payload.get("once"), payload.get("time")], ensure_ascii=False, separators=(",", ":")))
        inserted = self.store.add_event("print_events", {
            "job_id": job["id"], "event_key": event_key, "event_type": "TASK_CALLBACK",
            "raw_status": status, "raw_message": msg, "payload_json": _safe_payload(payload),
        })
        if not inserted:
            existing = self.store.event("print_events", event_key) or {}
            original = existing.get("payload_json") or {}
            if (str(existing.get("job_id") or "") != job["id"] or
                    str(original.get("taskid") or "") != taskid or
                    str(existing.get("raw_status") or "") != status or
                    str(existing.get("raw_message") or "") != msg):
                raise PrintError("INVALID_REPLAY", "callback 驗證資料已被重用", 403)
        fields = {"vendor_raw_status": status, "vendor_raw_message": msg}
        # A delayed callback may update raw audit fields but cannot downgrade a
        # verified terminal outcome. A completed callback may still reveal that
        # a prior cancel did not prevent physical output.
        if job.get("state") == "COMPLETED":
            pass
        elif job.get("state") == "CANCELED" and status != "2":
            pass
        elif status in CALLBACK_STATES:
            fields["state"] = CALLBACK_STATES[status]
        elif status != "12":
            fields.update({"state": "UNKNOWN", "last_error": "收到未識別的雲打印狀態"})
        if status == "1":
            fields["started_at"] = job.get("started_at") or utcnow()
        elif status == "2":
            fields["completed_at"] = utcnow()
        elif status == "3":
            fields["canceled_at"] = utcnow()
        updated = self.store.patch_job(job["id"], fields)
        self._sync_order(updated)
        return updated, not inserted

    def printer_callback(self, payload):
        if not self.client.valid_callback(payload):
            raise PrintError("INVALID_SIGNATURE", "簽名驗證失敗", 403)
        device = str(payload.get("device_id") or "")
        status = str(payload.get("status") or "")
        msg = str(payload.get("msg") or "")[:500]
        event_key = _hash(json.dumps(["printer-auth", device, payload.get("once"), payload.get("time")], ensure_ascii=False, separators=(",", ":")))
        inserted = self.store.add_event("printer_status_events", {
            "event_key": event_key, "device_id": device, "raw_status": status,
            "raw_message": msg, "payload_json": _safe_payload(payload),
        })
        if not inserted:
            existing = self.store.event("printer_status_events", event_key) or {}
            if str(existing.get("raw_status") or "") != status or str(existing.get("raw_message") or "") != msg:
                raise PrintError("INVALID_REPLAY", "printer callback 驗證資料已被重用", 403)
        return inserted

    def dashboard(self):
        if self.app.USE_SUPABASE:
            fields = "id,customer_name,model_name,style_name,status,print_path,mockup_path,created_at_unix"
            orders = self.app.SUPABASE.table("orders").select(fields).order("created_at_unix", desc=True).limit(200).execute().data or []
        else:
            orders = self.app.commerce.store.local_orders()
            orders.sort(key=lambda row: int(row.get("created_at_unix") or 0), reverse=True)
            orders = orders[:200]
        finance = self.app.commerce.read().get("order_finance") or {}
        shop = self.app.cloud_get_json("shop_data", self.app.DATA_FILE, self.app.DEFAULT_SHOP_DATA)
        latest = {}
        for job in self.store.list_jobs():
            if job["order_id"] not in latest:
                latest[job["order_id"]] = job
        profiles = {row["sku_id"]: row for row in self.store.profiles()}
        result = []
        for order in orders:
            order_id = order["id"]
            fin = finance.get(order_id) or {}
            sku_id = str(fin.get("sku_id") or "")
            suggestion = self._profile_suggestion(shop, fin.get("model_id"), fin.get("style_id"))
            result.append({
                "order_id": order_id, "customer_name": order.get("customer_name") or "",
                "model": order.get("model_name") or "", "style": order.get("style_name") or "",
                "order_status": order.get("status") or "待處理", "time": order.get("created_at_unix"),
                "has_print": bool(order.get("print_path")), "sku_id": sku_id,
                "profile_available": bool(sku_id and sku_id in profiles),
                "profile_suggestion": suggestion,
                "profile": ({key: profiles[sku_id].get(key) for key in
                    ("width_mm", "height_mm", "left_mm", "top_mm", "copies", "spot_color", "channel", "angle")}
                    if sku_id in profiles else None),
                "preview_url": url_for("admin_order_file", order_id=order_id, kind="preview") if order.get("mockup_path") else "",
                "job": _public_job(latest.get(order_id)),
            })
        return {
            "rows": result,
            "vendor_ready": self.vendor_ready,
            "vendor_connected": self.client.ready,
            "vendor_enabled": self.client.enabled,
            "device_id": self.client.device_id if self.vendor_ready else "",
            "platform": A5_DESKTOP_METADATA,
        }


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = app_module.app
    service = PrintService(app_module)
    app_module.print_center = service

    @app.errorhandler(PrintError)
    def print_error(exc):
        return app_module.no_cache_json({"status": "error", "code": exc.code, "msg": str(exc)}, exc.status)

    @app.errorhandler(PrintConflict)
    def print_conflict(exc):
        return app_module.no_cache_json({"status": "error", "code": exc.code, "msg": str(exc)}, exc.status)

    def guarded(fn):
        from functools import wraps
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not session.get("logged_in"):
                return app_module.no_cache_json({"status": "error", "msg": "未登入"}, 401)
            try:
                return fn(*args, **kwargs)
            except (PrintError, PrintConflict):
                raise
            except Exception:
                app.logger.exception("Print Center operation failed")
                return app_module.no_cache_json({"status": "error", "code": "PRINT_UNAVAILABLE", "msg": "列印中心暫時無法完成操作"}, 503)
        return wrapped

    def body():
        value = request.get_json(silent=True)
        if not isinstance(value, dict):
            raise PrintError("BAD_REQUEST", "列印操作格式錯誤", 400)
        return value

    def key(payload):
        value = str(request.headers.get("Idempotency-Key") or payload.get("idempotency_key") or "")
        if not KEY_RE.fullmatch(value):
            raise PrintError("IDEMPOTENCY_REQUIRED", "缺少有效的列印操作識別", 400)
        return value

    @app.route("/api/admin/print/jobs")
    @guarded
    def print_jobs():
        return app_module.no_cache_json({"status": "success", **service.dashboard()})

    @app.route("/api/admin/print/profile", methods=["POST"])
    @guarded
    def print_profile():
        profile = service.save_profile(body())
        return app_module.no_cache_json({"status": "success", "profile": profile})

    @app.route("/api/admin/print/prepare", methods=["POST"])
    @guarded
    def print_prepare():
        payload = body()
        job = service.prepare(str(payload.get("order_id") or ""), key(payload))
        return app_module.no_cache_json({"status": "success", "job": _public_job(job)})

    @app.route("/api/admin/print/profile-snapshot", methods=["POST"])
    @guarded
    def print_profile_snapshot():
        payload = body()
        job = service.snapshot_profile(str(payload.get("job_id") or ""), key(payload))
        return app_module.no_cache_json({"status": "success", "job": _public_job(job)})

    def operation(name):
        payload = body()
        job_id = str(payload.get("job_id") or "")
        result = getattr(service, name)(job_id, key(payload))
        return app_module.no_cache_json({"status": "success", "job": _public_job(result)})

    @app.route("/api/admin/print/send", methods=["POST"])
    @guarded
    def print_send():
        return operation("send")

    @app.route("/api/admin/print/start", methods=["POST"])
    @guarded
    def print_start():
        return operation("start")

    @app.route("/api/admin/print/cancel", methods=["POST"])
    @guarded
    def print_cancel():
        return operation("cancel")

    @app.route("/api/admin/print/reconcile", methods=["POST"])
    @guarded
    def print_reconcile():
        return operation("reconcile")

    @app.route("/api/print/artwork/<job_id>/<token>")
    def print_artwork(job_id, token):
        job = service.store.job(job_id)
        if not service.verify_artwork_token(job, token):
            return app_module.no_cache_json({"status": "error", "msg": "生產圖連結無效"}, 404)
        raw = service._download_artwork(job["artwork_path"])
        response = Response(raw, mimetype="image/png")
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.route("/api/print/callback", methods=["POST"])
    def print_callback():
        payload = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        if not isinstance(payload, dict):
            raise PrintError("BAD_CALLBACK", "callback 格式錯誤", 400)
        job, duplicate = service.task_callback(payload)
        return app_module.no_cache_json({"status": "success", "duplicate": duplicate, "job_id": job["id"]})

    @app.route("/api/print/printer-callback", methods=["POST"])
    def printer_callback():
        payload = request.get_json(silent=True) if request.is_json else request.form.to_dict()
        if not isinstance(payload, dict):
            raise PrintError("BAD_CALLBACK", "callback 格式錯誤", 400)
        inserted = service.printer_callback(payload)
        return app_module.no_cache_json({"status": "success", "duplicate": not inserted})

    @app.after_request
    def inject_print_center(response):
        if request.path == "/admin" and response.status_code == 200 and response.mimetype == "text/html":
            response.direct_passthrough = False
            html = response.get_data(as_text=True)
            src = "/static/admin-print-center.js?v=20260921a"
            if src not in html:
                response.set_data(html.replace("</body>", f'<link rel="stylesheet" href="/static/admin-print-center.css?v=20260921a"><script src="{src}"></script></body>'))
            response.headers["Cache-Control"] = "no-store"
        return response
