"""Production safety + performance middleware for 本福丸訂製.

Installed from gunicorn.conf.py after the Flask app is loaded.  This keeps the
existing app.py/front-end stable while adding server-side protection and a few
hot-path optimisations.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from urllib.parse import urlsplit

from flask import Response, g, jsonify, redirect, request, session

_INSTALLED = False
_LOCK = threading.RLock()
_HITS: dict[str, deque[float]] = defaultdict(deque)
_CACHE: dict[str, tuple[float, int, list[tuple[str, str]], bytes]] = {}
_SIGNED: dict[str, tuple[float, str]] = {}
_AI_ACTIVE = 0


def _client_ip() -> str:
    # Zeabur sits behind a proxy.  Prefer the first forwarded address, but only
    # use it for throttling (never for authentication/authorization).
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
    return forwarded or request.remote_addr or "unknown"


def _client_id() -> str:
    cid = session.get("_bf_client_id")
    if not cid:
        cid = secrets.token_urlsafe(12)
        session["_bf_client_id"] = cid
    return str(cid)


def _limited(bucket: str, key: str, limit: int, window: int) -> tuple[bool, int]:
    now = time.monotonic()
    k = f"{bucket}:{key}"
    with _LOCK:
        q = _HITS[k]
        cutoff = now - window
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= limit:
            retry = max(1, int(window - (now - q[0]))) if q else window
            return True, retry
        q.append(now)
        # Opportunistic cleanup so a long-running kiosk does not grow forever.
        if len(_HITS) > 4000:
            dead = [name for name, hits in _HITS.items() if not hits or hits[-1] < now - 7200]
            for name in dead[:1000]:
                _HITS.pop(name, None)
    return False, 0


def _too_many(msg: str, retry: int):
    resp = jsonify({"status": "error", "code": "RATE_LIMITED", "msg": msg})
    resp.status_code = 429
    resp.headers["Retry-After"] = str(max(1, retry))
    return resp


def _same_origin_ok() -> bool:
    # Browser requests with a foreign Origin/Referer are rejected.  Missing
    # Origin is tolerated for same-device/native clients; rate limits still apply.
    candidate = request.headers.get("Origin") or request.headers.get("Referer") or ""
    if not candidate:
        return True
    try:
        u = urlsplit(candidate)
        return (u.netloc or "").lower() == (request.host or "").lower()
    except Exception:
        return False


def _looks_like_image(file_storage) -> bool:
    if not file_storage:
        return False
    stream = getattr(file_storage, "stream", None)
    if stream is None:
        return False
    try:
        pos = stream.tell()
    except Exception:
        pos = 0
    try:
        head = stream.read(16)
        stream.seek(pos)
    except Exception:
        return False
    mime = (getattr(file_storage, "mimetype", "") or "").lower()
    if mime == "image/png":
        return head.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return head.startswith(b"\xff\xd8\xff")
    if mime == "image/webp":
        return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    return False


def _cache_key() -> str | None:
    if request.method != "GET":
        return None
    if request.path in ("/api/shop_data", "/api/assets", "/api/templates"):
        return request.path
    return None


def _cache_ttl(path: str) -> int:
    return 30 if path == "/api/shop_data" else 60


def _serve_cache(key: str):
    now = time.monotonic()
    with _LOCK:
        item = _CACHE.get(key)
        if not item:
            return None
        expires, status, headers, body = item
        if expires <= now:
            _CACHE.pop(key, None)
            return None
    resp = Response(body, status=status)
    for k, v in headers:
        if k.lower() not in ("content-length", "set-cookie"):
            resp.headers[k] = v
    resp.headers["X-Benfuwan-Cache"] = "HIT"
    return resp


def _invalidate_for(path: str):
    keys = []
    if path == "/api/admin/save_shop_data":
        keys.append("/api/shop_data")
    if path == "/api/admin/save_templates":
        keys.append("/api/templates")
    if path in ("/api/admin/upload_image", "/api/admin/batch_upload_stickers", "/api/admin/delete_sticker"):
        keys.extend(("/api/assets", "/api/templates"))
    if keys:
        with _LOCK:
            for key in keys:
                _CACHE.pop(key, None)


def _signed_preview(app_module, order_id: str) -> str:
    storage_path = f"orders/{order_id}/preview.png"
    now = time.monotonic()
    with _LOCK:
        item = _SIGNED.get(storage_path)
        if item and item[0] > now:
            return item[1]
    url = app_module._supabase_signed_url(storage_path, 300)
    if url:
        with _LOCK:
            _SIGNED[storage_path] = (now + 240, url)
            if len(_SIGNED) > 500:
                dead = [k for k, v in _SIGNED.items() if v[0] <= now]
                for k in dead[:250]:
                    _SIGNED.pop(k, None)
    return url


def install(app_module):
    """Install middleware once per Gunicorn worker."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    flask_app = app_module.app

    # Production cookie/session defaults.  SESSION_COOKIE_SECURE is also set
    # before app.py imports by gunicorn.conf.py.
    flask_app.config["SESSION_COOKIE_HTTPONLY"] = True
    flask_app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    flask_app.config["SESSION_COOKIE_SECURE"] = True
    flask_app.config["MAX_CONTENT_LENGTH"] = min(int(flask_app.config.get("MAX_CONTENT_LENGTH") or 36 * 1024 * 1024), 36 * 1024 * 1024)

    admin_env = (os.environ.get("ADMIN_PASSWORD") or "").strip()
    secret_env = (os.environ.get("FLASK_SECRET_KEY") or "").strip()
    if not admin_env or admin_env == "fan123" or len(admin_env) < 12:
        print("[SECURITY] WARNING: set ADMIN_PASSWORD in Zeabur to a unique password of at least 12 characters.", flush=True)
    if not secret_env:
        print("[SECURITY] FLASK_SECRET_KEY was not configured; a random per-boot secret is being used. Set a stable secret in Zeabur.", flush=True)

    @flask_app.before_request
    def _bf_before_request():
        global _AI_ACTIVE
        g._bf_started = time.perf_counter()
        path = request.path

        # Tiny server-side cache for public configuration.  This is especially
        # useful for admin refreshes because shop_data used to hit Supabase every time.
        ck = _cache_key()
        if ck:
            cached = _serve_cache(ck)
            if cached is not None:
                return cached

        # Same-origin guard for state-changing browser requests.
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if path == "/login" or path.startswith("/api/admin/") or path in ("/api/create_order", "/api/ai/remove-background"):
                if not _same_origin_ok():
                    return jsonify({"status": "error", "code": "BAD_ORIGIN", "msg": "來源驗證失敗，請重新開啟網站後再試"}), 403

        ip = _client_ip()

        # Back-office brute-force protection.
        if path == "/login" and request.method == "POST":
            blocked, retry = _limited("login", ip, 6, 600)
            if blocked:
                return _too_many("登入嘗試太頻繁，請稍後再試", retry)

        # Public AI is the endpoint that can directly cost money.  Protect both
        # the device/session and the shared public IP, plus cap concurrent jobs.
        if path == "/api/ai/remove-background" and request.method == "POST":
            cid = _client_id()
            blocked, retry = _limited("ai-client", cid, 15, 600)
            if blocked:
                return _too_many("AI 去背使用太頻繁，請稍後再試", retry)
            blocked, retry = _limited("ai-ip", ip, 80, 3600)
            if blocked:
                return _too_many("此網路的 AI 使用量暫時較高，請稍後再試", retry)
            with _LOCK:
                if _AI_ACTIVE >= 3:
                    return _too_many("AI 目前正在處理其他圖片，請稍後再試", 5)
                _AI_ACTIVE += 1
                g._bf_ai_slot = True
            img = request.files.get("image")
            if not _looks_like_image(img):
                with _LOCK:
                    _AI_ACTIVE = max(0, _AI_ACTIVE - 1)
                g._bf_ai_slot = False
                return jsonify({"status": "error", "code": "BAD_IMAGE", "msg": "圖片格式無法驗證，請改用 JPG、PNG 或 WEBP"}), 400

        # Fake-order / storage-abuse protection with generous limits for a night-market kiosk.
        if path == "/api/create_order" and request.method == "POST":
            cid = _client_id()
            blocked, retry = _limited("order-client", cid, 8, 1800)
            if blocked:
                return _too_many("短時間建立的訂單太多，請稍後再試", retry)
            blocked, retry = _limited("order-ip", ip, 60, 3600)
            if blocked:
                return _too_many("此網路的下單次數暫時過多，請稍後再試", retry)
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({"status": "error", "code": "BAD_REQUEST", "msg": "訂單資料格式錯誤"}), 400
            name = str(data.get("customer_name") or "").strip()
            if not name or len(name) > 40:
                return jsonify({"status": "error", "code": "BAD_NAME", "msg": "姓名格式錯誤"}), 400
            design = data.get("design_json")
            if design is not None:
                try:
                    if len(json.dumps(design, ensure_ascii=False, separators=(",", ":"))) > 2_000_000:
                        return jsonify({"status": "error", "code": "DESIGN_TOO_LARGE", "msg": "設計資料過大，請返回畫布精簡後再試"}), 413
                except Exception:
                    return jsonify({"status": "error", "code": "BAD_DESIGN", "msg": "設計資料格式錯誤"}), 400

        # Avoid proxying every preview PNG through the single Flask process.
        # The browser is redirected to a short-lived private Supabase signed URL.
        if path.startswith("/api/admin/order_file/") and path.endswith("/preview") and request.method == "GET":
            if not session.get("logged_in"):
                return jsonify({"status": "error", "msg": "未登入"}), 401
            if getattr(app_module, "USE_SUPABASE", False):
                parts = path.strip("/").split("/")
                if len(parts) == 5:
                    order_id = parts[3]
                    if order_id and all(ch.isalnum() or ch == "-" for ch in order_id):
                        try:
                            url = _signed_preview(app_module, order_id)
                            if url:
                                return redirect(url, code=302)
                        except Exception as exc:
                            print("[PERF] preview signed-url fallback:", repr(exc), flush=True)

    @flask_app.after_request
    def _bf_after_request(resp):
        path = request.path

        # Store safe GET configuration responses in process memory only.
        ck = _cache_key()
        if ck and 200 <= resp.status_code < 300 and resp.mimetype == "application/json" and resp.headers.get("X-Benfuwan-Cache") != "HIT":
            try:
                body = resp.get_data()
                keep_headers = [("Content-Type", resp.headers.get("Content-Type", "application/json")), ("Cache-Control", "no-store")]
                with _LOCK:
                    _CACHE[ck] = (time.monotonic() + _cache_ttl(ck), resp.status_code, keep_headers, body)
                resp.headers["X-Benfuwan-Cache"] = "MISS"
            except Exception:
                pass

        if request.method in ("POST", "PUT", "PATCH", "DELETE") and 200 <= resp.status_code < 400:
            _invalidate_for(path)

        # Clear failed login attempts after a successful redirect.
        if path == "/login" and request.method == "POST" and 300 <= resp.status_code < 400:
            with _LOCK:
                _HITS.pop(f"login:{_client_ip()}", None)

        # Do not expose raw internal exception details on the two public write APIs.
        if path in ("/api/create_order", "/api/ai/remove-background") and resp.status_code >= 500 and resp.mimetype == "application/json":
            try:
                payload = resp.get_json(silent=True) or {}
                code = payload.get("code") or "SERVER_ERROR"
                public_msg = "服務暫時忙碌，請稍後再試"
                if code in ("AI_TIMEOUT", "AI_NETWORK_TIMEOUT"):
                    public_msg = "AI 等候時間較久，請再試一次"
                resp.set_data(json.dumps({"status": "error", "code": code, "msg": public_msg}, ensure_ascii=False))
                resp.headers["Content-Type"] = "application/json; charset=utf-8"
            except Exception:
                pass

        # Add non-secret security status to health output so setup can be checked safely.
        if path == "/api/health" and resp.status_code == 200 and resp.mimetype == "application/json":
            try:
                data = resp.get_json(silent=True) or {}
                pw = (os.environ.get("ADMIN_PASSWORD") or "").strip()
                data["security"] = {
                    "rate_limit": True,
                    "secure_cookie": True,
                    "admin_password_safe": bool(pw and pw != "fan123" and len(pw) >= 12),
                    "stable_secret_configured": bool((os.environ.get("FLASK_SECRET_KEY") or "").strip()),
                }
                resp.set_data(json.dumps(data, ensure_ascii=False))
                resp.headers["Content-Type"] = "application/json; charset=utf-8"
            except Exception:
                pass

        # Baseline browser security headers.  Inline scripts/styles are currently
        # required by the existing editor/admin, so CSP allows them but still
        # blocks frames, plugins and foreign connections.
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' data: https://cdnjs.cloudflare.com; "
            "connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").lower()
        if request.is_secure or forwarded_proto == "https":
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        try:
            elapsed = (time.perf_counter() - getattr(g, "_bf_started", time.perf_counter())) * 1000
            if path.startswith("/api/"):
                resp.headers["Server-Timing"] = f"app;dur={elapsed:.1f}"
            if elapsed >= 1200 and (path.startswith("/admin") or path.startswith("/api/")):
                print(f"[PERF] slow request {request.method} {path} {elapsed:.0f}ms", flush=True)
        except Exception:
            pass
        return resp

    @flask_app.teardown_request
    def _bf_teardown(_exc):
        global _AI_ACTIVE
        if getattr(g, "_bf_ai_slot", False):
            with _LOCK:
                _AI_ACTIVE = max(0, _AI_ACTIVE - 1)
            g._bf_ai_slot = False

    print("[SECURITY] production middleware enabled", flush=True)
    print("[PERF] config cache + direct private preview delivery enabled", flush=True)
