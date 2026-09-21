"""Durable Print Center persistence for Supabase and the local SQLite fallback."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone


ACTIVE_STATES = ("PREPARED", "SENDING", "QUEUED", "STARTING", "PRINTING", "CANCELING", "UNKNOWN")
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
