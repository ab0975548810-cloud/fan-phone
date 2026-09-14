"""Template image helpers for admin and public frontend rendering.

Images are proxied through this app so Fabric can export canvases without CORS
tainting. A small in-memory cache avoids refetching the same Supabase objects
while users switch models/templates.
"""
import time
from collections import OrderedDict
from urllib.parse import urlparse
from flask import request, Response

_INSTALLED = False
_CACHE = OrderedDict()
_CACHE_BYTES = 0
_CACHE_MAX_BYTES = 64 * 1024 * 1024
_CACHE_TTL = 1800


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app = app_module.app
    session = app_module.session
    no_cache_json = app_module.no_cache_json
    requests_lib = app_module.requests
    supabase_url = (app_module.SUPABASE_URL or '').strip()
    allowed_host = (urlparse(supabase_url).hostname or '').lower()

    def _cache_get(url):
        item = _CACHE.get(url)
        if not item:
            return None
        ts, raw, content_type = item
        if time.time() - ts > _CACHE_TTL:
            _CACHE.pop(url, None)
            return None
        _CACHE.move_to_end(url)
        return raw, content_type

    def _cache_put(url, raw, content_type):
        global _CACHE_BYTES
        if len(raw) > 18 * 1024 * 1024:
            return
        old = _CACHE.pop(url, None)
        if old:
            _CACHE_BYTES -= len(old[1])
        _CACHE[url] = (time.time(), raw, content_type)
        _CACHE_BYTES += len(raw)
        while _CACHE and _CACHE_BYTES > _CACHE_MAX_BYTES:
            _, item = _CACHE.popitem(last=False)
            _CACHE_BYTES -= len(item[1])

    def _response(raw, content_type, require_admin=False):
        resp = Response(raw, mimetype=content_type)
        resp.headers['Cache-Control'] = 'private, max-age=3600' if require_admin else 'public, max-age=86400, immutable'
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        return resp

    def _serve_proxy(require_admin=False):
        if require_admin and not session.get('logged_in'):
            return no_cache_json({'status': 'error', 'msg': '未登入'}, 401)
        if not requests_lib:
            return no_cache_json({'status': 'error', 'msg': '伺服器缺少圖片連線元件'}, 503)

        url = str(request.args.get('url') or '').strip()
        if not url:
            return no_cache_json({'status': 'error', 'msg': '缺少圖片網址'}, 400)

        try:
            parsed = urlparse(url)
            host = (parsed.hostname or '').lower()
            if parsed.scheme not in ('http', 'https') or not host:
                return no_cache_json({'status': 'error', 'msg': '圖片網址格式錯誤'}, 400)
            if not allowed_host or host != allowed_host:
                return no_cache_json({'status': 'error', 'msg': '不允許讀取這個圖片來源'}, 403)

            hit = _cache_get(url)
            if hit:
                raw, content_type = hit
                return _response(raw, content_type, require_admin)

            upstream = requests_lib.get(url, timeout=15)
            if upstream.status_code < 200 or upstream.status_code >= 300:
                return no_cache_json({'status': 'error', 'msg': f'圖片讀取失敗（HTTP {upstream.status_code}）'}, 502)

            raw = upstream.content or b''
            if not raw:
                return no_cache_json({'status': 'error', 'msg': '圖片內容是空的'}, 502)
            if len(raw) > 18 * 1024 * 1024:
                return no_cache_json({'status': 'error', 'msg': '圖片超過 18MB'}, 413)

            content_type = str(upstream.headers.get('content-type') or '').split(';', 1)[0].lower()
            if content_type not in ('image/png', 'image/jpeg', 'image/webp'):
                return no_cache_json({'status': 'error', 'msg': '圖片格式不支援'}, 415)

            _cache_put(url, raw, content_type)
            return _response(raw, content_type, require_admin)
        except Exception as exc:
            print('[TEMPLATE] asset proxy error:', repr(exc), flush=True)
            return no_cache_json({'status': 'error', 'msg': '模板圖片讀取失敗'}, 502)

    @app.route('/api/admin/template_asset_proxy', methods=['GET'])
    def admin_template_asset_proxy():
        return _serve_proxy(require_admin=True)

    @app.route('/api/public/asset_proxy', methods=['GET'])
    def public_template_asset_proxy():
        return _serve_proxy(require_admin=False)

    print('[TEMPLATE] same-origin asset proxy + memory cache enabled', flush=True)
