"""Durable Print Center persistence for Supabase and the local SQLite fallback."""
from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone


ACTIVE_STATES = ("PREPARED", "SENDING", "QUEUED", "STARTING", "PRINTING", "CANCELING", "UNKNOWN")
CALLBACK_STATES = {
    "1": "PRINTING", "2": "COMPLETED", "3": "CANCELED",
    "4": "FAILED", "5": "FAILED", "6": "FAILED", "7": "FAILED",
    "8": "FAILED", "11": "FAILED",
}
JSON_COLUMNS = {"response_json", "payload_json"}
BOOL_COLUMNS = {"profile_complete", "active"}


def utcnow():
    return datetime.now(timezone.utc).isoformat()


class PrintConflict(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code = code
        self.status = status


class PrintStore:
    def __init__(self, app_module):
        self.app = app_module
        self.path = os.environ.get("PRINT_DB_PATH") or os.environ.get("COMMERCE_DB_PATH", "commerce.sqlite3")

    @contextmanager
    def connection(self, write=False):
        if os.environ.get("BENFUWAN_PRODUCTION") == "1" and not self.app.USE_SUPABASE and os.environ.get("COMMERCE_DURABLE_LOCAL") != "1":
            raise RuntimeError("Production print jobs require Supabase or an acknowledged durable local volume")
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS production_profiles (
                    sku_id TEXT PRIMARY KEY, width_mm REAL NOT NULL, height_mm REAL NOT NULL,
                    left_mm REAL NOT NULL, top_mm REAL NOT NULL, copies INTEGER NOT NULL,
                    spot_color TEXT NOT NULL, channel TEXT NOT NULL, angle REAL NOT NULL,
                    active INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS print_order_bindings (
                    order_id TEXT PRIMARY KEY, sku_id TEXT NOT NULL,
                    source TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS print_jobs (
                    id TEXT PRIMARY KEY, order_id TEXT NOT NULL, attempt_no INTEGER NOT NULL,
                    sku_id TEXT, vendor_taskid TEXT, artwork_path TEXT NOT NULL,
                    artwork_sha256 TEXT, artwork_token_nonce TEXT NOT NULL,
                    artwork_token_expires_at TEXT, profile_complete INTEGER NOT NULL,
                    width_mm REAL, height_mm REAL, left_mm REAL, top_mm REAL, copies INTEGER,
                    spot_color TEXT, channel TEXT, angle REAL, device_id TEXT, state TEXT NOT NULL,
                    vendor_raw_status TEXT, vendor_raw_message TEXT, ambiguous_operation TEXT,
                    last_error TEXT, reconcile_count INTEGER NOT NULL DEFAULT 0,
                    last_reconciled_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    prepared_at TEXT NOT NULL, sent_at TEXT, started_at TEXT,
                    completed_at TEXT, canceled_at TEXT, UNIQUE(order_id, attempt_no)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_local_print_vendor_taskid ON print_jobs(vendor_taskid) WHERE vendor_taskid IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS idx_local_print_one_active ON print_jobs(order_id)
                    WHERE state IN ('PREPARED','SENDING','QUEUED','STARTING','PRINTING','CANCELING','UNKNOWN');
                CREATE TABLE IF NOT EXISTS print_requests (
                    request_key TEXT PRIMARY KEY, operation TEXT NOT NULL, job_id TEXT,
                    request_hash TEXT NOT NULL, status TEXT NOT NULL, response_json TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS print_events (
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL, event_key TEXT NOT NULL UNIQUE,
                    event_type TEXT NOT NULL, raw_status TEXT, raw_message TEXT,
                    payload_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS printer_status_events (
                    id TEXT PRIMARY KEY, event_key TEXT NOT NULL UNIQUE, device_id TEXT NOT NULL,
                    raw_status TEXT, raw_message TEXT, payload_json TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS print_handoffs (
                    id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE,
                    request_key TEXT NOT NULL UNIQUE, marker_version TEXT NOT NULL,
                    state TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at TEXT, lease_token TEXT, lease_expires_at TEXT,
                    prepared_job_id TEXT, last_error_code TEXT, last_error_at TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_local_print_handoffs_due
                    ON print_handoffs(state,next_attempt_at,created_at);
            """)
            db.commit()
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except Exception:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        for key in JSON_COLUMNS:
            if key in result and isinstance(result[key], str):
                try:
                    result[key] = json.loads(result[key])
                except ValueError:
                    result[key] = None
        for key in BOOL_COLUMNS:
            if key in result:
                result[key] = bool(result[key])
        return result

    def profile(self, sku_id):
        if not sku_id:
            return None
        if self.app.USE_SUPABASE:
            rows = self.app.SUPABASE.table("production_profiles").select("*").eq("sku_id", sku_id).eq("active", True).limit(1).execute().data or []
            return rows[0] if rows else None
        with self.connection() as db:
            return self._decode(db.execute("SELECT * FROM production_profiles WHERE sku_id=? AND active=1", (sku_id,)).fetchone())

    def profiles(self):
        if self.app.USE_SUPABASE:
            return self.app.SUPABASE.table("production_profiles").select("*").eq("active", True).execute().data or []
        with self.connection() as db:
            return [self._decode(row) for row in db.execute("SELECT * FROM production_profiles WHERE active=1")]

    def binding(self, order_id):
        if not order_id:
            return None
        if self.app.USE_SUPABASE:
            rows = (self.app.SUPABASE.table("print_order_bindings").select("*")
                    .eq("order_id", order_id).limit(1).execute().data or [])
            return rows[0] if rows else None
        with self.connection() as db:
            return self._decode(db.execute(
                "SELECT * FROM print_order_bindings WHERE order_id=?", (order_id,)
            ).fetchone())

    def bindings(self):
        if self.app.USE_SUPABASE:
            return self.app.SUPABASE.table("print_order_bindings").select("*").execute().data or []
        with self.connection() as db:
            return [self._decode(row) for row in db.execute("SELECT * FROM print_order_bindings")]

    def save_binding(self, order_id, sku_id, source="ADMIN_CONFIRMED"):
        now = utcnow()
        row = {"order_id": order_id, "sku_id": sku_id, "source": source, "updated_at": now}
        if self.app.USE_SUPABASE:
            existing = self.binding(order_id)
            row["created_at"] = existing.get("created_at") if existing else now
            self.app.SUPABASE.table("print_order_bindings").upsert(row).execute()
            return self.binding(order_id)
        with self.connection(True) as db:
            old = db.execute("SELECT created_at FROM print_order_bindings WHERE order_id=?", (order_id,)).fetchone()
            row["created_at"] = old[0] if old else now
            db.execute("""INSERT INTO print_order_bindings (order_id,sku_id,source,created_at,updated_at)
                VALUES (:order_id,:sku_id,:source,:created_at,:updated_at)
                ON CONFLICT(order_id) DO UPDATE SET sku_id=excluded.sku_id,
                source=excluded.source,updated_at=excluded.updated_at""", row)
        return self.binding(order_id)

    def save_profile(self, profile):
        now = utcnow()
        row = {**profile, "active": True, "updated_at": now}
        if self.app.USE_SUPABASE:
            existing = self.profile(profile["sku_id"])
            if not existing:
                row["created_at"] = now
            self.app.SUPABASE.table("production_profiles").upsert(row).execute()
            return self.profile(profile["sku_id"])
        with self.connection(True) as db:
            old = db.execute("SELECT created_at FROM production_profiles WHERE sku_id=?", (profile["sku_id"],)).fetchone()
            row["created_at"] = old[0] if old else now
            db.execute("""INSERT INTO production_profiles
                (sku_id,width_mm,height_mm,left_mm,top_mm,copies,spot_color,channel,angle,active,created_at,updated_at)
                VALUES (:sku_id,:width_mm,:height_mm,:left_mm,:top_mm,:copies,:spot_color,:channel,:angle,1,:created_at,:updated_at)
                ON CONFLICT(sku_id) DO UPDATE SET width_mm=excluded.width_mm,height_mm=excluded.height_mm,
                left_mm=excluded.left_mm,top_mm=excluded.top_mm,copies=excluded.copies,
                spot_color=excluded.spot_color,channel=excluded.channel,angle=excluded.angle,
                active=1,updated_at=excluded.updated_at""", row)
        return self.profile(profile["sku_id"])

    def materialize_profile(self, profile):
        """Create a derived SKU profile once without replacing a calibrated row."""
        now = utcnow()
        row = {**profile, "active": True, "created_at": now, "updated_at": now}
        if self.app.USE_SUPABASE:
            (self.app.SUPABASE.table("production_profiles")
             .upsert(row, on_conflict="sku_id", ignore_duplicates=True).execute())
            current = self.profile(profile["sku_id"])
            if not current:
                (self.app.SUPABASE.table("production_profiles").update(row)
                 .eq("sku_id", profile["sku_id"]).eq("active", False).execute())
            return self.profile(profile["sku_id"])
        with self.connection(True) as db:
            db.execute("""INSERT INTO production_profiles
                (sku_id,width_mm,height_mm,left_mm,top_mm,copies,spot_color,channel,angle,active,created_at,updated_at)
                VALUES (:sku_id,:width_mm,:height_mm,:left_mm,:top_mm,:copies,:spot_color,:channel,:angle,1,:created_at,:updated_at)
                ON CONFLICT(sku_id) DO UPDATE SET width_mm=excluded.width_mm,height_mm=excluded.height_mm,
                left_mm=excluded.left_mm,top_mm=excluded.top_mm,copies=excluded.copies,
                spot_color=excluded.spot_color,channel=excluded.channel,angle=excluded.angle,
                active=1,updated_at=excluded.updated_at
                WHERE production_profiles.active=0""", row)
        return self.profile(profile["sku_id"])

    def save_profiles(self, profiles):
        """Upsert a model's active SKU profiles as one database statement."""
        profiles = list(profiles or [])
        if not profiles:
            return []
        now = utcnow()
        existing = {row["sku_id"]: row for row in self.profiles()}
        rows = []
        for profile in profiles:
            old = existing.get(profile["sku_id"])
            rows.append({
                **profile,
                "active": True,
                "created_at": old.get("created_at") if old else now,
                "updated_at": now,
            })
        if self.app.USE_SUPABASE:
            self.app.SUPABASE.table("production_profiles").upsert(rows).execute()
        else:
            with self.connection(True) as db:
                db.executemany("""INSERT INTO production_profiles
                    (sku_id,width_mm,height_mm,left_mm,top_mm,copies,spot_color,channel,angle,active,created_at,updated_at)
                    VALUES (:sku_id,:width_mm,:height_mm,:left_mm,:top_mm,:copies,:spot_color,:channel,:angle,1,:created_at,:updated_at)
                    ON CONFLICT(sku_id) DO UPDATE SET width_mm=excluded.width_mm,height_mm=excluded.height_mm,
                    left_mm=excluded.left_mm,top_mm=excluded.top_mm,copies=excluded.copies,
                    spot_color=excluded.spot_color,channel=excluded.channel,angle=excluded.angle,
                    active=1,updated_at=excluded.updated_at""", rows)
        return [self.profile(row["sku_id"]) for row in rows]

    def job(self, job_id):
        if self.app.USE_SUPABASE:
            rows = self.app.SUPABASE.table("print_jobs").select("*").eq("id", job_id).limit(1).execute().data or []
            return rows[0] if rows else None
        with self.connection() as db:
            return self._decode(db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())

    def job_for_task(self, taskid):
        if self.app.USE_SUPABASE:
            rows = self.app.SUPABASE.table("print_jobs").select("*").eq("vendor_taskid", taskid).limit(1).execute().data or []
            return rows[0] if rows else None
        with self.connection() as db:
            return self._decode(db.execute("SELECT * FROM print_jobs WHERE vendor_taskid=?", (taskid,)).fetchone())

    def latest_job(self, order_id):
        if self.app.USE_SUPABASE:
            rows = self.app.SUPABASE.table("print_jobs").select("*").eq("order_id", order_id).order("attempt_no", desc=True).limit(1).execute().data or []
            return rows[0] if rows else None
        with self.connection() as db:
            return self._decode(db.execute("SELECT * FROM print_jobs WHERE order_id=? ORDER BY attempt_no DESC LIMIT 1", (order_id,)).fetchone())

    def jobs_for_order(self, order_id):
        """Return every immutable attempt, newest attempt first."""
        if self.app.USE_SUPABASE:
            return (self.app.SUPABASE.table("print_jobs").select("*")
                    .eq("order_id", order_id).order("attempt_no", desc=True)
                    .execute().data or [])
        with self.connection() as db:
            rows = db.execute(
                "SELECT * FROM print_jobs WHERE order_id=? ORDER BY attempt_no DESC",
                (order_id,),
            ).fetchall()
            return [self._decode(row) for row in rows]

    def jobs_for_orders(self, order_ids):
        """Batch-load attempts for dashboard rows without updated_at semantics."""
        ids = [str(value) for value in dict.fromkeys(order_ids) if value]
        if not ids:
            return []
        if self.app.USE_SUPABASE:
            return (self.app.SUPABASE.table("print_jobs").select("*")
                    .in_("order_id", ids).order("attempt_no", desc=True)
                    .execute().data or [])
        marks = ",".join("?" for _ in ids)
        with self.connection() as db:
            rows = db.execute(
                f"SELECT * FROM print_jobs WHERE order_id IN ({marks}) "
                "ORDER BY order_id, attempt_no DESC",
                ids,
            ).fetchall()
            return [self._decode(row) for row in rows]

    @staticmethod
    def _physical_evidence(job):
        return bool(
            str(job.get("state") or "") in ("PRINTING", "COMPLETED")
            or str(job.get("vendor_raw_status") or "") in ("1", "2")
            or job.get("started_at")
            or job.get("completed_at")
            or str(job.get("ambiguous_operation") or "") == "prior_attempt_activity"
        )

    def attest_unknown_missing(self, job_id, request_key, vendor_taskid, operator, confirmation):
        """Atomically persist operator attestation and release UNKNOWN, never send.

        Supabase uses the same per-order advisory lock as callback/send/reconcile.
        SQLite uses one BEGIN IMMEDIATE transaction. Both leave old vendor identity
        and raw status untouched; the next attempt uses the normal retry pipeline.
        """
        if (not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", str(request_key or ""))
                or confirmation != "VERIFIED_RUIYIN_HISTORY_AND_NO_PHYSICAL_OUTPUT"
                or not vendor_taskid or not (1 <= len(str(operator or "")) <= 100)):
            return {"ok": False, "code": "BAD_CONFIRMATION"}
        if self.app.USE_SUPABASE:
            data = self.app.SUPABASE.rpc("attest_print_unknown_missing", {
                "p_job_id": job_id, "p_request_key": request_key,
                "p_vendor_taskid": vendor_taskid, "p_operator": operator,
                "p_confirmation": confirmation,
            }).execute().data
            return data if isinstance(data, dict) else {"ok": False, "code": "PRINT_UNAVAILABLE"}

        event_key = "operator-missing:" + request_key
        with self.connection(True) as db:
            job = self._decode(db.execute(
                "SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())
            if not job:
                return {"ok": False, "code": "JOB_NOT_FOUND"}
            latest = self._decode(db.execute(
                "SELECT * FROM print_jobs WHERE order_id=? ORDER BY attempt_no DESC LIMIT 1",
                (job["order_id"],)).fetchone())
            existing = self._decode(db.execute(
                "SELECT * FROM print_events WHERE event_key=?", (event_key,)).fetchone())
            if existing:
                payload = existing.get("payload_json") or {}
                if (existing.get("job_id") != job_id
                        or existing.get("event_type") != "OPERATOR_CONFIRMED_MISSING"
                        or payload.get("vendor_taskid") != vendor_taskid
                        or payload.get("operator") != operator):
                    return {"ok": False, "code": "IDEMPOTENCY_CONFLICT"}
                return {"ok": True, "code": "OK", "replay": True,
                        "job": job, "latest": latest}
            if latest["id"] != job_id:
                return {"ok": False, "code": "STALE_PRINT_ATTEMPT"}
            if job["state"] != "UNKNOWN" or job.get("ambiguous_operation"):
                return {"ok": False, "code": "RECONCILE_REQUIRED"}
            if job.get("vendor_taskid") != vendor_taskid or not job.get("sent_at"):
                return {"ok": False, "code": "BAD_CONFIRMATION"}
            if not job.get("last_reconciled_at") or not int(job.get("reconcile_count") or 0):
                return {"ok": False, "code": "RECONCILE_REQUIRED"}
            attempts = [self._decode(row) for row in db.execute(
                "SELECT * FROM print_jobs WHERE order_id=?", (job["order_id"],))]
            if any(self._physical_evidence(attempt) for attempt in attempts):
                return {"ok": False, "code": "REPRINT_REQUIRED"}
            now = utcnow()
            warning = ("操作員已核對銳印待列印、歷史、完成及實體輸出，確認找不到原 Task ID；"
                       "此操作有重複出墨風險，原銳印 Task ID 與證據均保留")
            payload = {
                "vendor_taskid": vendor_taskid, "operator": operator,
                "confirmation": confirmation, "reconciled_at": job.get("last_reconciled_at"),
                "reconcile_count": job.get("reconcile_count"),
                "vendor_lookup": "no_matching_pending_tasks",
                "original_state": job["state"], "original_attempt_no": job["attempt_no"],
                "warning": "Operator attestation is not evidence that vendor never accepted a task",
            }
            db.execute("""INSERT INTO print_events
                (id,job_id,event_key,event_type,raw_status,raw_message,payload_json,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), job_id, event_key, "OPERATOR_CONFIRMED_MISSING",
                 job.get("vendor_raw_status"), warning[:500],
                 json.dumps(payload, ensure_ascii=False), now))
            db.execute("""UPDATE print_jobs SET state='CANCELED',canceled_at=?,
                ambiguous_operation='operator_confirmed_missing',last_error=?,updated_at=?
                WHERE id=? AND state='UNKNOWN'""", (now, warning[:500], now, job_id))
            updated = self._decode(db.execute(
                "SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())
            return {"ok": True, "code": "OK", "replay": False,
                    "job": updated, "latest": updated}

    def claim_send_if_safe(self, job_id, *, nonce, expires_at, device_id):
        """Atomically claim PREPARED -> SENDING under the order safety lock."""
        if self.app.USE_SUPABASE:
            data = self.app.SUPABASE.rpc("claim_print_send_if_safe", {
                "p_job_id": job_id,
                "p_artwork_token_nonce": nonce,
                "p_artwork_token_expires_at": expires_at,
                "p_device_id": device_id,
            }).execute().data
            return data if isinstance(data, dict) else {"ok": False, "code": "PRINT_UNAVAILABLE"}
        with self.connection(True) as db:
            row = self._decode(db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())
            if not row:
                return {"ok": False, "code": "JOB_NOT_FOUND"}
            attempts = [self._decode(value) for value in db.execute(
                "SELECT * FROM print_jobs WHERE order_id=? ORDER BY attempt_no DESC",
                (row["order_id"],),
            ).fetchall()]
            if any(self._physical_evidence(value) for value in attempts):
                return {"ok": False, "code": "REPRINT_REQUIRED"}
            if row.get("state") != "PREPARED":
                return {"ok": False, "code": "CONCURRENT_OPERATION"}
            now = utcnow()
            db.execute("""UPDATE print_jobs SET state='SENDING',artwork_token_nonce=?,
                artwork_token_expires_at=?,device_id=?,last_error=NULL,
                ambiguous_operation=NULL,updated_at=? WHERE id=? AND state='PREPARED'""",
                       (nonce, expires_at, device_id, now, job_id))
            claimed = self._decode(db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())
            return {"ok": claimed.get("state") == "SENDING", "code": "OK", "job": claimed}

    def apply_task_callback(self, job_id, status, message):
        """Atomically record callback evidence and quarantine a newer attempt."""
        status, message = str(status or ""), str(message or "")[:500]
        if self.app.USE_SUPABASE:
            data = self.app.SUPABASE.rpc("apply_print_callback_safely", {
                "p_job_id": job_id, "p_status": status, "p_message": message,
            }).execute().data
            if not isinstance(data, dict) or not isinstance(data.get("job"), dict):
                raise RuntimeError("Invalid print callback RPC response")
            return data
        with self.connection(True) as db:
            job = self._decode(db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())
            if not job:
                raise ValueError("JOB_NOT_FOUND")
            latest = self._decode(db.execute(
                "SELECT * FROM print_jobs WHERE order_id=? ORDER BY attempt_no DESC LIMIT 1",
                (job["order_id"],),
            ).fetchone())
            superseded = int(job.get("attempt_no") or 0) < int(latest.get("attempt_no") or 0)
            now = utcnow()
            raw_status, raw_message = status, message
            prior_raw = str(job.get("vendor_raw_status") or "")
            if superseded and (prior_raw == "2" or (prior_raw == "1" and status != "2")):
                raw_status = prior_raw
                raw_message = str(job.get("vendor_raw_message") or "")[:500]
            fields = {"vendor_raw_status": raw_status, "vendor_raw_message": raw_message,
                      "updated_at": now}
            if status == "1":
                fields["started_at"] = job.get("started_at") or now
            elif status == "2":
                fields["completed_at"] = job.get("completed_at") or now
            elif status == "3":
                fields["canceled_at"] = job.get("canceled_at") or now
            if not superseded:
                if job.get("state") == "COMPLETED":
                    pass
                elif job.get("state") == "CANCELED" and status != "2":
                    pass
                elif status in CALLBACK_STATES:
                    fields["state"] = CALLBACK_STATES[status]
                elif status != "12":
                    fields.update({"state": "UNKNOWN", "last_error": "收到未識別的雲打印狀態"})
            sets = ",".join(f"{name}=?" for name in fields)
            db.execute(f"UPDATE print_jobs SET {sets} WHERE id=?", (*fields.values(), job_id))
            physical = (status in ("1", "2") or self._physical_evidence(job))
            if superseded and physical:
                warning = "舊列印嘗試延遲回報列印中/完成，為避免重複打印，本次重推已封鎖"
                if latest.get("state") == "PREPARED":
                    db.execute("""UPDATE print_jobs SET state='CANCELED',canceled_at=?,
                        ambiguous_operation='prior_attempt_activity',last_error=?,updated_at=?
                        WHERE id=? AND state='PREPARED'""",
                               (now, warning, now, latest["id"]))
                elif latest.get("state") in ACTIVE_STATES:
                    db.execute("""UPDATE print_jobs SET state='UNKNOWN',
                        ambiguous_operation='prior_attempt_activity',last_error=?,updated_at=?
                        WHERE id=?""", (warning + "，請人工查核雲端狀態", now, latest["id"]))
            updated = self._decode(db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())
            return {"job": updated, "superseded": superseded}

    def apply_reconcile_safely(self, job_id, *, matched, taskid="", status="",
                               message="", ambiguous=False):
        """Atomically apply a vendor lookup without clearing retry quarantine."""
        taskid = str(taskid or "")
        status = str(status or "")
        message = str(message or "")[:500]
        if self.app.USE_SUPABASE:
            data = self.app.SUPABASE.rpc("apply_print_reconcile_safely", {
                "p_job_id": job_id,
                "p_matched": bool(matched),
                "p_taskid": taskid or None,
                "p_status": status,
                "p_message": message,
                "p_ambiguous": bool(ambiguous),
            }).execute().data
            if not isinstance(data, dict) or not isinstance(data.get("job"), dict):
                raise RuntimeError("Invalid print reconcile RPC response")
            return data
        with self.connection(True) as db:
            job = self._decode(db.execute(
                "SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())
            if not job:
                raise ValueError("JOB_NOT_FOUND")
            safe_match = bool(matched)
            if safe_match and taskid:
                owner = self._decode(db.execute(
                    "SELECT * FROM print_jobs WHERE vendor_taskid=? LIMIT 1", (taskid,)
                ).fetchone())
                if owner and str(owner.get("id") or "") != str(job_id):
                    safe_match = False
                    ambiguous = True
            now = utcnow()
            fields = {
                "last_reconciled_at": now,
                "reconcile_count": int(job.get("reconcile_count") or 0) + 1,
            }
            quarantined = str(job.get("ambiguous_operation") or "") == "prior_attempt_activity"
            if quarantined:
                if safe_match:
                    fields.update({
                        "vendor_raw_status": status,
                        "vendor_raw_message": message,
                    })
                    if status == "1":
                        fields["started_at"] = job.get("started_at") or now
                    elif status == "2":
                        fields["completed_at"] = job.get("completed_at") or now
                    elif status == "3":
                        fields["canceled_at"] = job.get("canceled_at") or now
            elif safe_match:
                fields.update({
                    "vendor_taskid": taskid or None,
                    "vendor_raw_status": status,
                    "vendor_raw_message": message,
                    "state": CALLBACK_STATES.get(status, "QUEUED"),
                    "ambiguous_operation": None,
                    "last_error": None,
                })
                if status == "1":
                    fields["started_at"] = job.get("started_at") or now
                elif status == "2":
                    fields["completed_at"] = job.get("completed_at") or now
                elif status == "3":
                    fields["canceled_at"] = job.get("canceled_at") or now
            elif ambiguous:
                fields.update({
                    "state": "UNKNOWN",
                    "ambiguous_operation": "reconcile",
                    "last_error": "雲端查核找到多筆可能任務，無法安全判定；請人工確認",
                })
            elif str(job.get("state") or "") not in ("COMPLETED", "CANCELED", "FAILED"):
                fields.update({
                    "state": "UNKNOWN",
                    "last_error": "雲端未列印佇列找不到此任務；不可據此判定未建立或已完成",
                })
            sets = ",".join(f"{name}=?" for name in fields)
            db.execute(f"UPDATE print_jobs SET {sets} WHERE id=?", (*fields.values(), job_id))
            updated = self._decode(db.execute(
                "SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())
            return {
                "ok": True,
                "code": "RECONCILE_REQUIRED" if quarantined or ambiguous else "OK",
                "job": updated,
                "found": safe_match,
                "ambiguous": bool(ambiguous),
                "quarantined": quarantined,
            }

    def active_job(self, order_id):
        if self.app.USE_SUPABASE:
            rows = (self.app.SUPABASE.table("print_jobs").select("*").eq("order_id", order_id)
                    .in_("state", list(ACTIVE_STATES)).limit(1).execute().data or [])
            return rows[0] if rows else None
        with self.connection() as db:
            marks = ",".join("?" for _ in ACTIVE_STATES)
            row = db.execute(f"SELECT * FROM print_jobs WHERE order_id=? AND state IN ({marks}) LIMIT 1",
                             (order_id, *ACTIVE_STATES)).fetchone()
            return self._decode(row)

    def list_jobs(self, limit=300):
        if self.app.USE_SUPABASE:
            return self.app.SUPABASE.table("print_jobs").select("*").order("updated_at", desc=True).limit(limit).execute().data or []
        with self.connection() as db:
            return [self._decode(row) for row in db.execute("SELECT * FROM print_jobs ORDER BY updated_at DESC LIMIT ?", (limit,))]

    def auto_prepared_jobs(self, limit=50):
        """Pending auto jobs, plus one bounded recovery for a crashed pre-claim send.

        A PREPARED job with an old IN_PROGRESS send request is recoverable only
        when there is *no* claim token, vendor identity, timestamp, raw status,
        quarantine, or other send outcome. A claim token means the vendor might
        have been contacted; that case always requires manual reconciliation.
        Recovery uses a different, durable idempotency key exactly once.
        """
        limit = max(1, min(int(limit), 200))
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
        # Deploying code alone must never cause previously stranded customer
        # orders to be handed to the vendor. Explicit operator opt-in is needed.
        recovery_enabled = os.environ.get(
            "PRINT_AUTO_RECOVER_STALE_SENDS", "").strip().lower() in ("1", "true", "yes")

        def ready(job, requests):
            if job.get("state") != "PREPARED" or any(job.get(field) for field in (
                    "vendor_taskid", "sent_at", "started_at", "completed_at",
                    "artwork_token_expires_at", "vendor_raw_status",
                    "ambiguous_operation")):
                return None
            if not any(row.get("operation") == "prepare"
                       and row.get("status") == "COMPLETED"
                       and str(row.get("request_key") or "").startswith("auto-prepare-")
                       for row in requests):
                return None
            sends = [row for row in requests if row.get("operation") == "send"]
            if not sends:
                return job
            if not recovery_enabled:
                return None
            if (not any(str(row.get("request_key") or "").startswith("auto-send-")
                        and not str(row.get("request_key") or "").startswith("auto-send-recovery-")
                        for row in sends)
                    or any(row.get("status") != "IN_PROGRESS" for row in sends)
                    or any(str(row.get("request_key") or "").startswith("auto-send-recovery-")
                           for row in sends)):
                return None
            for row in sends:
                try:
                    stamp = datetime.fromisoformat(
                        str(row.get("updated_at") or "").replace("Z", "+00:00"))
                    if stamp.tzinfo is None or stamp.astimezone(timezone.utc) > cutoff:
                        return None
                except (ValueError, TypeError):
                    return None
            return {**job, "_auto_recovery": True}

        page_size = max(100, min(200, limit * 2))
        offset = 0
        result = []
        # Continue past manual and terminal-failed PREPARED jobs: a fixed first
        # page can permanently starve newly created automatic orders.
        while len(result) < limit:
            if self.app.USE_SUPABASE:
                jobs = (self.app.SUPABASE.table("print_jobs").select("*")
                        .eq("state", "PREPARED")
                        .order("prepared_at").order("id")
                        .range(offset, offset + page_size - 1).execute().data or [])
                if not jobs:
                    break
                requests = (self.app.SUPABASE.table("print_requests")
                            .select("job_id,operation,status,request_key,updated_at")
                            .in_("job_id", [str(row["id"]) for row in jobs])
                            .execute().data or [])
            else:
                with self.connection() as db:
                    jobs = [self._decode(row) for row in db.execute(
                        "SELECT * FROM print_jobs WHERE state='PREPARED' "
                        "ORDER BY prepared_at,id LIMIT ? OFFSET ?",
                        (page_size, offset)).fetchall()]
                    if not jobs:
                        break
                    placeholders = ",".join("?" for _ in jobs)
                    requests = [self._decode(row) for row in db.execute(
                        "SELECT job_id,operation,status,request_key,updated_at "
                        f"FROM print_requests WHERE job_id IN ({placeholders})",
                        [row["id"] for row in jobs]).fetchall()]
            by_job = {}
            for row in requests:
                by_job.setdefault(str(row.get("job_id") or ""), []).append(row)
            for job in jobs:
                candidate = ready(job, by_job.get(str(job["id"]), []))
                if candidate:
                    result.append(candidate)
                    if len(result) >= limit:
                        break
            if len(jobs) < page_size:
                break
            offset += page_size
        return result

    def claim_handoffs(self, limit=20, lease_seconds=60):
        """Claim a bounded batch with a DB lease, safe across worker processes."""
        limit = max(1, min(int(limit), 50))
        lease_seconds = max(15, min(int(lease_seconds), 600))
        if self.app.USE_SUPABASE:
            return self.app.SUPABASE.rpc("claim_print_handoffs", {
                "p_limit": limit, "p_lease_seconds": lease_seconds,
            }).execute().data or []
        now = datetime.now(timezone.utc)
        now_text = now.isoformat()
        expires = (now + timedelta(seconds=lease_seconds)).isoformat()
        claimed = []
        with self.connection(write=True) as db:
            rows = db.execute("""SELECT * FROM print_handoffs
                WHERE marker_version='auto-print-handoff-v1' AND (
                    (state IN ('PENDING','RETRY') AND COALESCE(next_attempt_at,'') <= ?)
                    OR (state='CLAIMED' AND lease_expires_at <= ?)
                ) ORDER BY created_at,id LIMIT ?""",
                (now_text, now_text, limit)).fetchall()
            for row in rows:
                token = str(uuid.uuid4())
                db.execute("""UPDATE print_handoffs
                    SET state='CLAIMED',attempt_count=attempt_count+1,
                        lease_token=?,lease_expires_at=?,updated_at=? WHERE id=?""",
                    (token, expires, now_text, row["id"]))
                claimed.append(self._decode(db.execute(
                    "SELECT * FROM print_handoffs WHERE id=?", (row["id"],)).fetchone()))
        return claimed

    def finish_handoff(self, handoff_id, lease_token, state, *,
                       prepared_job_id=None, error_code=None, retry_seconds=None):
        if state not in ("RETRY", "PREPARED", "REVIEW", "FAILED"):
            raise ValueError("invalid handoff finish state")
        if self.app.USE_SUPABASE:
            result = self.app.SUPABASE.rpc("finish_print_handoff", {
                "p_id": handoff_id, "p_lease_token": lease_token,
                "p_state": state, "p_prepared_job_id": prepared_job_id,
                "p_error_code": error_code, "p_retry_seconds": retry_seconds,
            }).execute().data
            return result or {"ok": False, "code": "LEASE_LOST"}
        now = datetime.now(timezone.utc)
        next_attempt = ((now + timedelta(seconds=int(retry_seconds))).isoformat()
                        if state == "RETRY" else None)
        with self.connection(write=True) as db:
            handoff = db.execute("""SELECT order_id FROM print_handoffs
                WHERE id=? AND state='CLAIMED' AND lease_token=?""",
                (handoff_id, lease_token)).fetchone()
            if not handoff:
                return {"ok": False, "code": "LEASE_LOST"}
            if state == "PREPARED":
                if not prepared_job_id:
                    return {"ok": False, "code": "PREPARED_JOB_REQUIRED"}
                job = db.execute(
                    "SELECT order_id FROM print_jobs WHERE id=?",
                    (prepared_job_id,)).fetchone()
                if not job or str(job["order_id"]) != str(handoff["order_id"]):
                    return {"ok": False, "code": "PREPARED_JOB_MISMATCH"}
            changed = db.execute("""UPDATE print_handoffs SET
                state=?,prepared_job_id=CASE WHEN ?='PREPARED' THEN ? ELSE prepared_job_id END,
                last_error_code=?,last_error_at=CASE WHEN ? IS NULL THEN last_error_at ELSE ? END,
                next_attempt_at=?,lease_token=NULL,lease_expires_at=NULL,updated_at=?
                WHERE id=? AND state='CLAIMED' AND lease_token=?""",
                (state, state, prepared_job_id, error_code, error_code,
                 now.isoformat(), next_attempt, now.isoformat(), handoff_id,
                 lease_token)).rowcount
        return {"ok": bool(changed), "state": state if changed else None,
                "code": None if changed else "LEASE_LOST"}

    def handoffs_for_orders(self, order_ids):
        """Authoritative per-order lookup, independent of truncated alert summaries."""
        ids = list(dict.fromkeys(str(value) for value in order_ids))
        result = {}
        for offset in range(0, len(ids), 100):
            batch = ids[offset:offset + 100]
            if self.app.USE_SUPABASE:
                rows = (self.app.SUPABASE.table("print_handoffs").select("*")
                        .in_("order_id", batch).execute().data or [])
            else:
                with self.connection() as db:
                    rows = [self._decode(row) for row in db.execute(
                        "SELECT * FROM print_handoffs WHERE order_id IN (" +
                        ",".join("?" for _ in batch) + ")", batch).fetchall()]
            result.update({str(row["order_id"]): row for row in rows})
        return result

    def handoff_summary(self, limit=20, *, include_order_ids=False, offset=0):
        """Bounded alerts; raw order IDs are opt-in for authenticated admin UI."""
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        alert_states = ("REVIEW", "FAILED", "RETRY", "CLAIMED", "PENDING")
        if self.app.USE_SUPABASE:
            rows = (self.app.SUPABASE.table("print_handoffs")
                    .select("order_id,marker_version,state,attempt_count,last_error_code,created_at,updated_at")
                    .in_("state", list(alert_states))
                    .order("updated_at", desc=True).order("order_id").range(offset, offset + limit).execute().data or [])
        else:
            with self.connection() as db:
                rows = [self._decode(row) for row in db.execute("""SELECT
                    order_id,marker_version,state,attempt_count,last_error_code,created_at,updated_at
                    FROM print_handoffs WHERE state IN ('REVIEW','FAILED','RETRY','CLAIMED','PENDING')
                    ORDER BY updated_at DESC, order_id LIMIT ? OFFSET ?""", (limit + 1, offset)).fetchall()]
        more = len(rows) > limit
        rows = rows[:limit]
        counts, alerts = {}, []
        for row in rows:
            state = str(row.get("state") or "")
            counts[state] = counts.get(state, 0) + 1
            alert = {
                "order_ref": hashlib.sha256(
                    str(row.get("order_id") or "").encode()).hexdigest()[:12],
                "marker_version": str(row.get("marker_version") or ""),
                "state": state,
                "attempt_count": int(row.get("attempt_count") or 0),
                "error_code": str(row.get("last_error_code") or "")[:100],
                "updated_at": row.get("updated_at"),
            }
            if include_order_ids:
                alert["order_id"] = str(row.get("order_id") or "")
            alerts.append(alert)
        return {"counts": counts, "alerts": alerts, "offset": offset,
                "next_offset": offset + limit if more else None,
                "bounded_limit": limit, "truncated": more}

    def create_job(self, order, sku_id, profile, artwork_sha256, token_nonce):
        now = utcnow()
        prior = self.latest_job(order["id"])
        if prior and prior["state"] in ACTIVE_STATES:
            return prior
        if prior and prior["state"] in ("PRINTING", "COMPLETED"):
            raise PrintConflict("REPRINT_REQUIRED", "已列印訂單必須使用未來獨立的重印流程")
        attempt = int(prior["attempt_no"]) + 1 if prior else 1
        row = {
            "id": str(uuid.uuid4()), "order_id": order["id"], "attempt_no": attempt,
            "sku_id": sku_id or None, "vendor_taskid": None, "artwork_path": order["print_path"],
            "artwork_sha256": artwork_sha256, "artwork_token_nonce": token_nonce,
            "artwork_token_expires_at": None, "profile_complete": bool(profile),
            "width_mm": profile.get("width_mm") if profile else None,
            "height_mm": profile.get("height_mm") if profile else None,
            "left_mm": profile.get("left_mm") if profile else None,
            "top_mm": profile.get("top_mm") if profile else None,
            "copies": profile.get("copies") if profile else None,
            "spot_color": profile.get("spot_color") if profile else None,
            "channel": profile.get("channel") if profile else None,
            "angle": profile.get("angle") if profile else None,
            "device_id": None, "state": "PREPARED", "vendor_raw_status": None,
            "vendor_raw_message": None, "ambiguous_operation": None, "last_error": None,
            "reconcile_count": 0, "last_reconciled_at": None, "created_at": now,
            "updated_at": now, "prepared_at": now, "sent_at": None, "started_at": None,
            "completed_at": None, "canceled_at": None,
        }
        if self.app.USE_SUPABASE:
            try:
                self.app.SUPABASE.table("print_jobs").insert(row).execute()
                return row
            except Exception:
                active = self.latest_job(order["id"])
                if active and active["state"] in ACTIVE_STATES:
                    return active
                raise
        columns = ",".join(row)
        values = ",".join("?" for _ in row)
        encoded = [int(v) if k in BOOL_COLUMNS else v for k, v in row.items()]
        try:
            with self.connection(True) as db:
                db.execute(f"INSERT INTO print_jobs ({columns}) VALUES ({values})", encoded)
            return row
        except sqlite3.IntegrityError:
            active = self.latest_job(order["id"])
            if active and active["state"] in ACTIVE_STATES:
                return active
            raise

    def authorize_manual_reprint(self, order_id, key, request_hash, actor,
                                 order_status, seed, handoff_review=False):
        """Atomically authorize one operator-initiated attempt and audit it.

        A terminal prior attempt is copied byte-for-byte at the print snapshot
        boundary (artwork path/hash and every vendor parameter). A never-sent
        PREPARED attempt may be adopted, but an in-flight/unknown attempt is
        never superseded. The request row makes a browser retry return the same
        attempt instead of creating another one.
        """
        if self.app.USE_SUPABASE:
            data = self.app.SUPABASE.rpc("authorize_manual_reprint", {
                "p_order_id": order_id, "p_request_key": key,
                "p_request_hash": request_hash, "p_actor": actor,
                "p_order_status": order_status,
                "p_seed": seed, "p_handoff_review": bool(handoff_review),
            }).execute().data
            return data if isinstance(data, dict) else {
                "ok": False, "code": "PRINT_UNAVAILABLE"}

        event_key = "manual-reprint:" + key
        with self.connection(True) as db:
            prior_request = self._decode(db.execute(
                "SELECT * FROM print_requests WHERE request_key=?", (key,)
            ).fetchone())
            if prior_request:
                if (prior_request.get("operation") != "manual_reprint"
                        or prior_request.get("request_hash") != request_hash):
                    return {"ok": False, "code": "IDEMPOTENCY_CONFLICT"}
                replay = self._decode(db.execute(
                    "SELECT * FROM print_jobs WHERE id=?",
                    (prior_request.get("job_id"),),
                ).fetchone())
                return {"ok": bool(replay), "code": "OK" if replay else "JOB_NOT_FOUND",
                        "replay": True, "job": replay}

            attempts = [self._decode(row) for row in db.execute(
                "SELECT * FROM print_jobs WHERE order_id=? ORDER BY attempt_no DESC",
                (order_id,),
            ).fetchall()]
            latest = attempts[0] if attempts else None
            active = next((row for row in attempts if row.get("state") in ACTIVE_STATES), None)
            if active and active.get("state") != "PREPARED":
                code = "RECONCILE_REQUIRED" if active.get("state") in (
                    "SENDING", "UNKNOWN") else "ACTIVE_PRINT_JOB"
                return {"ok": False, "code": code}

            job = None
            if active:
                # A normal unsent first attempt is safe to adopt. A PREPARED
                # manual attempt can also be retried after a definitive vendor
                # rejection. Nothing with unresolved prior-activity quarantine
                # is adopted.
                authorized = db.execute(
                    "SELECT 1 FROM print_events WHERE job_id=? AND event_type IN "
                    "('MANUAL_REPRINT_AUTHORIZED','HANDOFF_REVIEW_MANUAL_REPRINT_AUTHORIZED') LIMIT 1",
                    (active["id"],),
                ).fetchone()
                prior_physical = any(self._physical_evidence(row) for row in attempts
                                     if row["id"] != active["id"])
                if active.get("ambiguous_operation") or (prior_physical and not authorized):
                    return {"ok": False, "code": "RECONCILE_REQUIRED"}
                job = active
            else:
                source = latest
                values = source or seed
                required = ("artwork_path", "artwork_sha256", "sku_id", "width_mm",
                            "height_mm", "left_mm", "top_mm", "copies", "spot_color",
                            "channel", "angle")
                if not values or any(values.get(name) is None for name in required):
                    return {"ok": False, "code": "PROFILE_MISSING"}
                now = utcnow()
                job = {
                    "id": str(uuid.uuid4()), "order_id": order_id,
                    "attempt_no": int((latest or {}).get("attempt_no") or 0) + 1,
                    "sku_id": values.get("sku_id"), "vendor_taskid": None,
                    "artwork_path": values["artwork_path"],
                    "artwork_sha256": values["artwork_sha256"],
                    "artwork_token_nonce": str(seed.get("artwork_token_nonce") or uuid.uuid4().hex),
                    "artwork_token_expires_at": None,
                    "profile_complete": bool(values.get("profile_complete", True)),
                    "width_mm": values["width_mm"], "height_mm": values["height_mm"],
                    "left_mm": values["left_mm"], "top_mm": values["top_mm"],
                    "copies": values["copies"], "spot_color": values["spot_color"],
                    "channel": values["channel"], "angle": values["angle"],
                    "device_id": None, "state": "PREPARED", "vendor_raw_status": None,
                    "vendor_raw_message": None, "ambiguous_operation": None,
                    "last_error": None, "reconcile_count": 0,
                    "last_reconciled_at": None, "created_at": now, "updated_at": now,
                    "prepared_at": now, "sent_at": None, "started_at": None,
                    "completed_at": None, "canceled_at": None,
                }
                columns = ",".join(job)
                encoded = [int(v) if k in BOOL_COLUMNS else v for k, v in job.items()]
                db.execute(f"INSERT INTO print_jobs ({columns}) VALUES ({','.join('?' for _ in job)})", encoded)

            now = utcnow()
            event_type = ("HANDOFF_REVIEW_MANUAL_REPRINT_AUTHORIZED" if handoff_review
                          else "MANUAL_REPRINT_AUTHORIZED")
            payload = {
                "actor": actor, "order_id": order_id, "order_status": order_status,
                "source_job_id": (latest or {}).get("id"),
                "source_attempt_no": (latest or {}).get("attempt_no"),
                "source_state": (latest or {}).get("state"),
                "handoff_review": bool(handoff_review),
                "artwork_sha256": job.get("artwork_sha256"),
                "parameters": {name: job.get(name) for name in (
                    "width_mm", "height_mm", "left_mm", "top_mm", "copies",
                    "spot_color", "channel", "angle")},
            }
            db.execute("""INSERT INTO print_events
                (id,job_id,event_key,event_type,raw_status,raw_message,payload_json,created_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), job["id"], event_key, event_type,
                 (latest or {}).get("vendor_raw_status"),
                 "店員按下重新送任務，已授權建立獨立人工重印嘗試",
                 json.dumps(payload, ensure_ascii=False), now))
            db.execute("""INSERT INTO print_requests
                (request_key,operation,job_id,request_hash,status,response_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)""",
                (key, "manual_reprint", job["id"], request_hash, "COMPLETED",
                 json.dumps({"job_id": job["id"]}, ensure_ascii=False), now, now))
            return {"ok": True, "code": "OK", "replay": False, "job": job}

    def claim_manual_reprint_send_if_safe(self, job_id, *, nonce, expires_at,
                                          device_id):
        """Claim an audited manual attempt without treating old output as a ban."""
        if self.app.USE_SUPABASE:
            data = self.app.SUPABASE.rpc("claim_manual_reprint_send_if_safe", {
                "p_job_id": job_id,
                "p_artwork_token_nonce": nonce,
                "p_artwork_token_expires_at": expires_at,
                "p_device_id": device_id,
            }).execute().data
            return data if isinstance(data, dict) else {
                "ok": False, "code": "PRINT_UNAVAILABLE"}
        with self.connection(True) as db:
            row = self._decode(db.execute(
                "SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())
            if not row:
                return {"ok": False, "code": "JOB_NOT_FOUND"}
            latest = self._decode(db.execute(
                "SELECT * FROM print_jobs WHERE order_id=? ORDER BY attempt_no DESC LIMIT 1",
                (row["order_id"],),
            ).fetchone())
            authorized = db.execute(
                "SELECT 1 FROM print_events WHERE job_id=? AND event_type IN "
                "('MANUAL_REPRINT_AUTHORIZED','HANDOFF_REVIEW_MANUAL_REPRINT_AUTHORIZED') LIMIT 1",
                (job_id,),
            ).fetchone()
            if not authorized:
                return {"ok": False, "code": "MANUAL_REPRINT_AUTH_REQUIRED"}
            if not latest or latest.get("id") != job_id:
                return {"ok": False, "code": "STALE_PRINT_ATTEMPT"}
            if row.get("state") != "PREPARED" or row.get("ambiguous_operation"):
                code = "RECONCILE_REQUIRED" if row.get("state") in (
                    "SENDING", "UNKNOWN") or row.get("ambiguous_operation") else "CONCURRENT_OPERATION"
                return {"ok": False, "code": code}
            now = utcnow()
            db.execute("""UPDATE print_jobs SET state='SENDING',artwork_token_nonce=?,
                artwork_token_expires_at=?,device_id=?,last_error=NULL,
                ambiguous_operation=NULL,updated_at=? WHERE id=? AND state='PREPARED'""",
                (nonce, expires_at, device_id, now, job_id))
            claimed = self._decode(db.execute(
                "SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())
            return {"ok": claimed.get("state") == "SENDING", "code": "OK",
                    "job": claimed}

    def patch_job(self, job_id, fields, from_states=None):
        fields = {**fields, "updated_at": utcnow()}
        allowed = {
            "vendor_taskid","artwork_token_nonce","artwork_token_expires_at","profile_complete",
            "width_mm","height_mm","left_mm","top_mm","copies","spot_color","channel","angle",
            "device_id","state","vendor_raw_status","vendor_raw_message","ambiguous_operation",
            "last_error","reconcile_count","last_reconciled_at","sent_at","started_at",
            "completed_at","canceled_at","updated_at",
        }
        if not set(fields).issubset(allowed):
            raise ValueError("Unsupported print job field")
        if self.app.USE_SUPABASE:
            query = self.app.SUPABASE.table("print_jobs").update(fields).eq("id", job_id)
            if from_states:
                query = query.in_("state", list(from_states))
            rows = query.execute().data or []
            return rows[0] if rows else None
        params = []
        sets = []
        for key, value in fields.items():
            sets.append(f"{key}=?")
            params.append(int(value) if key in BOOL_COLUMNS else value)
        where = "id=?"
        params.append(job_id)
        if from_states:
            where += " AND state IN (" + ",".join("?" for _ in from_states) + ")"
            params.extend(from_states)
        with self.connection(True) as db:
            cur = db.execute(f"UPDATE print_jobs SET {','.join(sets)} WHERE {where}", params)
            if cur.rowcount != 1:
                return None
            return self._decode(db.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone())

    def request(self, key):
        if self.app.USE_SUPABASE:
            rows = self.app.SUPABASE.table("print_requests").select("*").eq("request_key", key).limit(1).execute().data or []
            return rows[0] if rows else None
        with self.connection() as db:
            return self._decode(db.execute("SELECT * FROM print_requests WHERE request_key=?", (key,)).fetchone())

    def claim_request(self, key, operation, job_id, request_hash):
        prior = self.request(key)
        if prior:
            if prior["operation"] != operation or prior["request_hash"] != request_hash or (prior.get("job_id") or "") != (job_id or ""):
                raise PrintConflict("IDEMPOTENCY_CONFLICT", "同一操作識別已用於不同列印操作")
            return False, prior
        now = utcnow()
        row = {"request_key": key, "operation": operation, "job_id": job_id,
               "request_hash": request_hash, "status": "IN_PROGRESS", "response_json": None,
               "created_at": now, "updated_at": now}
        try:
            if self.app.USE_SUPABASE:
                self.app.SUPABASE.table("print_requests").insert(row).execute()
            else:
                with self.connection(True) as db:
                    db.execute("INSERT INTO print_requests VALUES (?,?,?,?,?,?,?,?)",
                               (key, operation, job_id, request_hash, "IN_PROGRESS", None, now, now))
            return True, row
        except Exception:
            prior = self.request(key)
            if not prior:
                raise
            if prior["operation"] != operation or prior["request_hash"] != request_hash or (prior.get("job_id") or "") != (job_id or ""):
                raise PrintConflict("IDEMPOTENCY_CONFLICT", "同一操作識別已用於不同列印操作")
            return False, prior

    def finish_request(self, key, status, response):
        now = utcnow()
        if self.app.USE_SUPABASE:
            self.app.SUPABASE.table("print_requests").update({"status": status, "response_json": response, "updated_at": now}).eq("request_key", key).execute()
        else:
            with self.connection(True) as db:
                db.execute("UPDATE print_requests SET status=?,response_json=?,updated_at=? WHERE request_key=?",
                           (status, json.dumps(response, ensure_ascii=False), now, key))

    def add_event(self, table, row):
        if table not in ("print_events", "printer_status_events"):
            raise ValueError("Unsupported event table")
        row = {**row, "id": str(uuid.uuid4()), "created_at": utcnow()}
        try:
            if self.app.USE_SUPABASE:
                self.app.SUPABASE.table(table).insert(row).execute()
            else:
                encoded = {k: json.dumps(v, ensure_ascii=False) if k in JSON_COLUMNS else v for k, v in row.items()}
                with self.connection(True) as db:
                    db.execute(f"INSERT INTO {table} ({','.join(encoded)}) VALUES ({','.join('?' for _ in encoded)})", list(encoded.values()))
            return True
        except Exception:
            if self.app.USE_SUPABASE:
                found = self.app.SUPABASE.table(table).select("id").eq("event_key", row["event_key"]).limit(1).execute().data or []
            else:
                with self.connection() as db:
                    found = db.execute(f"SELECT id FROM {table} WHERE event_key=?", (row["event_key"],)).fetchone()
            if found:
                return False
            raise

    def event(self, table, event_key):
        if table not in ("print_events", "printer_status_events"):
            raise ValueError("Unsupported event table")
        if self.app.USE_SUPABASE:
            rows = self.app.SUPABASE.table(table).select("*").eq("event_key", event_key).limit(1).execute().data or []
            return rows[0] if rows else None
        with self.connection() as db:
            return self._decode(db.execute(f"SELECT * FROM {table} WHERE event_key=?", (event_key,)).fetchone())
