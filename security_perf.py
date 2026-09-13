"""Production safety + performance middleware for 本福丸訂製."""
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
_HITS = defaultdict(deque)
_CACHE = {}
_SIGNED = {}
_AI_ACTIVE = 0


def _ip():
    forwarded = (request.headers.get('X-Forwarded-For') or '').split(',', 1)[0].strip()
    return forwarded or request.remote_addr or 'unknown'


def _cid():
    cid = session.get('_bf_client_id')
    if not cid:
        cid = secrets.token_urlsafe(12)
        session['_bf_client_id'] = cid
    return str(cid)


def _limited(bucket, key, limit, window):
    now = time.monotonic()
    name = f'{bucket}:{key}'
    with _LOCK:
        q = _HITS[name]
        cutoff = now - window
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= limit:
            return True, max(1, int(window - (now - q[0])))
        q.append(now)
        if len(_HITS) > 4000:
            stale = [k for k, v in _HITS.items() if not v or v[-1] < now - 7200]
            for k in stale[:1000]:
                _HITS.pop(k, None)
    return False, 0


def _429(msg, retry):
    r = jsonify({'status': 'error', 'code': 'RATE_LIMITED', 'msg': msg})
    r.status_code = 429
    r.headers['Retry-After'] = str(max(1, retry))
    return r


def _same_origin():
    value = request.headers.get('Origin') or request.headers.get('Referer') or ''
    if not value:
        return True
    try:
        return (urlsplit(value).netloc or '').lower() == (request.host or '').lower()
    except Exception:
        return False


def _valid_image(f):
    if not f or not getattr(f, 'stream', None):
        return False
    s = f.stream
    try:
        pos = s.tell()
    except Exception:
        pos = 0
    try:
        head = s.read(16)
        s.seek(pos)
    except Exception:
        return False
    mime = (f.mimetype or '').lower()
    if mime == 'image/png':
        return head.startswith(b'\x89PNG\r\n\x1a\n')
    if mime == 'image/jpeg':
        return head.startswith(b'\xff\xd8\xff')
    if mime == 'image/webp':
        return len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'WEBP'
    return False


def _cfg_key():
    if request.method == 'GET' and request.path in ('/api/shop_data', '/api/assets', '/api/templates'):
        return request.path
    return None


def _serve_cache(key):
    now = time.monotonic()
    with _LOCK:
        item = _CACHE.get(key)
        if not item:
            return None
        expires, status, ctype, body = item
        if expires <= now:
            _CACHE.pop(key, None)
            return None
    r = Response(body, status=status, content_type=ctype)
    r.headers['Cache-Control'] = 'no-store'
    r.headers['X-Benfuwan-Cache'] = 'HIT'
    return r


def _invalidate(path):
    keys = []
    if path == '/api/admin/save_shop_data':
        keys.append('/api/shop_data')
    elif path == '/api/admin/save_templates':
        keys.append('/api/templates')
    elif path in ('/api/admin/upload_image', '/api/admin/batch_upload_stickers', '/api/admin/delete_sticker'):
        keys += ['/api/assets', '/api/templates']
    with _LOCK:
        for key in keys:
            _CACHE.pop(key, None)


def _preview_url(app_module, order_id):
    storage_path = f'orders/{order_id}/preview.png'
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
                for k in [k for k, v in _SIGNED.items() if v[0] <= now][:250]:
                    _SIGNED.pop(k, None)
    return url


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = app_module.app
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['MAX_CONTENT_LENGTH'] = min(int(app.config.get('MAX_CONTENT_LENGTH') or 36 * 1024 * 1024), 36 * 1024 * 1024)

    admin_pw = (os.environ.get('ADMIN_PASSWORD') or '').strip()
    generated_secret = os.environ.get('BENFUWAN_GENERATED_SECRET') == '1'
    if not admin_pw or admin_pw == 'fan123' or len(admin_pw) < 12:
        print('[SECURITY] WARNING: set ADMIN_PASSWORD in Zeabur to a unique password of at least 12 characters.', flush=True)
    if generated_secret:
        print('[SECURITY] FLASK_SECRET_KEY is using a safe random per-boot fallback. Set a stable secret in Zeabur to keep sessions across redeploys.', flush=True)

    @app.before_request
    def _before():
        global _AI_ACTIVE
        g._bf_started = time.perf_counter()
        path = request.path

        key = _cfg_key()
        if key:
            hit = _serve_cache(key)
            if hit is not None:
                return hit

        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            protected = path == '/login' or path.startswith('/api/admin/') or path in ('/api/create_order', '/api/ai/remove-background')
            if protected and not _same_origin():
                return jsonify({'status': 'error', 'code': 'BAD_ORIGIN', 'msg': '來源驗證失敗，請重新開啟網站後再試'}), 403

        ip = _ip()
        if path == '/login' and request.method == 'POST':
            blocked, retry = _limited('login', ip, 6, 600)
            if blocked:
                return _429('登入嘗試太頻繁，請稍後再試', retry)

        if path == '/api/ai/remove-background' and request.method == 'POST':
            # Night-market friendly: enough headroom for a shared iPad, while still
            # preventing one device/IP from running the GPU without bounds.
            blocked, retry = _limited('ai-client', _cid(), 30, 600)
            if blocked:
                return _429('AI 去背使用太頻繁，請稍後再試', retry)
            blocked, retry = _limited('ai-ip', ip, 120, 3600)
            if blocked:
                return _429('此網路的 AI 使用量暫時較高，請稍後再試', retry)
            with _LOCK:
                if _AI_ACTIVE >= 3:
                    return _429('AI 目前正在處理其他圖片，請稍後再試', 5)
                _AI_ACTIVE += 1
                g._bf_ai_slot = True
            if not _valid_image(request.files.get('image')):
                with _LOCK:
                    _AI_ACTIVE = max(0, _AI_ACTIVE - 1)
                g._bf_ai_slot = False
                return jsonify({'status': 'error', 'code': 'BAD_IMAGE', 'msg': '圖片格式無法驗證，請改用 JPG、PNG 或 WEBP'}), 400

        if path == '/api/create_order' and request.method == 'POST':
            blocked, retry = _limited('order-client', _cid(), 20, 1800)
            if blocked:
                return _429('短時間建立的訂單太多，請稍後再試', retry)
            blocked, retry = _limited('order-ip', ip, 100, 3600)
            if blocked:
                return _429('此網路的下單次數暫時過多，請稍後再試', retry)
            data = request.get_json(silent=True)
            if not isinstance(data, dict):
                return jsonify({'status': 'error', 'code': 'BAD_REQUEST', 'msg': '訂單資料格式錯誤'}), 400
            name = str(data.get('customer_name') or '').strip()
            if not name or len(name) > 40:
                return jsonify({'status': 'error', 'code': 'BAD_NAME', 'msg': '姓名格式錯誤'}), 400
            design = data.get('design_json')
            if design is not None:
                try:
                    size = len(json.dumps(design, ensure_ascii=False, separators=(',', ':')))
                except Exception:
                    return jsonify({'status': 'error', 'code': 'BAD_DESIGN', 'msg': '設計資料格式錯誤'}), 400
                if size > 2_000_000:
                    return jsonify({'status': 'error', 'code': 'DESIGN_TOO_LARGE', 'msg': '設計資料過大，請返回畫布精簡後再試'}), 413

        # Preview images were a major admin bottleneck: do not stream them through
        # Flask.  Redirect authenticated admins to a short-lived private URL.
        if path.startswith('/api/admin/order_file/') and path.endswith('/preview') and request.method == 'GET':
            if not session.get('logged_in'):
                return jsonify({'status': 'error', 'msg': '未登入'}), 401
            if getattr(app_module, 'USE_SUPABASE', False):
                parts = path.strip('/').split('/')
                if len(parts) == 5:
                    order_id = parts[3]
                    if order_id and all(ch.isalnum() or ch == '-' for ch in order_id):
                        try:
                            url = _preview_url(app_module, order_id)
                            if url:
                                return redirect(url, 302)
                        except Exception as exc:
                            print('[PERF] signed preview fallback:', repr(exc), flush=True)

    @app.after_request
    def _after(resp):
        path = request.path
        key = _cfg_key()
        if key and 200 <= resp.status_code < 300 and resp.mimetype == 'application/json' and resp.headers.get('X-Benfuwan-Cache') != 'HIT':
            try:
                ttl = 30 if key == '/api/shop_data' else 60
                with _LOCK:
                    _CACHE[key] = (time.monotonic() + ttl, resp.status_code, resp.headers.get('Content-Type', 'application/json'), resp.get_data())
                resp.headers['X-Benfuwan-Cache'] = 'MISS'
            except Exception:
                pass

        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and 200 <= resp.status_code < 400:
            _invalidate(path)

        if path == '/login' and request.method == 'POST' and 300 <= resp.status_code < 400:
            with _LOCK:
                _HITS.pop(f'login:{_ip()}', None)

        if path in ('/api/create_order', '/api/ai/remove-background') and resp.status_code >= 500 and resp.mimetype == 'application/json':
            try:
                payload = resp.get_json(silent=True) or {}
                code = payload.get('code') or 'SERVER_ERROR'
                msg = 'AI 等候時間較久，請再試一次' if code in ('AI_TIMEOUT', 'AI_NETWORK_TIMEOUT') else '服務暫時忙碌，請稍後再試'
                resp.set_data(json.dumps({'status': 'error', 'code': code, 'msg': msg}, ensure_ascii=False))
                resp.headers['Content-Type'] = 'application/json; charset=utf-8'
            except Exception:
                pass

        if path == '/api/health' and resp.status_code == 200 and resp.mimetype == 'application/json':
            try:
                data = resp.get_json(silent=True) or {}
                pw = (os.environ.get('ADMIN_PASSWORD') or '').strip()
                data['security'] = {
                    'rate_limit': True,
                    'secure_cookie': True,
                    'admin_password_safe': bool(pw and pw != 'fan123' and len(pw) >= 12),
                    'stable_secret_configured': bool((os.environ.get('FLASK_SECRET_KEY') or '').strip()) and os.environ.get('BENFUWAN_GENERATED_SECRET') != '1',
                }
                resp.set_data(json.dumps(data, ensure_ascii=False))
                resp.headers['Content-Type'] = 'application/json; charset=utf-8'
            except Exception:
                pass

        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['X-Frame-Options'] = 'DENY'
        resp.headers['Referrer-Policy'] = 'same-origin'
        resp.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=(), payment=()'
        resp.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; img-src 'self' data: blob: https:; "
            "font-src 'self' data: https://cdnjs.cloudflare.com; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
        )
        if request.is_secure or (request.headers.get('X-Forwarded-Proto') or '').lower() == 'https':
            resp.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'

        try:
            ms = (time.perf_counter() - getattr(g, '_bf_started', time.perf_counter())) * 1000
            if path.startswith('/api/'):
                resp.headers['Server-Timing'] = f'app;dur={ms:.1f}'
            if ms >= 1200 and (path.startswith('/admin') or path.startswith('/api/')):
                print(f'[PERF] slow request {request.method} {path} {ms:.0f}ms', flush=True)
        except Exception:
            pass
        return resp

    @app.teardown_request
    def _teardown(_exc):
        global _AI_ACTIVE
        if getattr(g, '_bf_ai_slot', False):
            with _LOCK:
                _AI_ACTIVE = max(0, _AI_ACTIVE - 1)
            g._bf_ai_slot = False

    print('[SECURITY] production middleware enabled', flush=True)
    print('[PERF] config cache + direct private preview delivery enabled', flush=True)
