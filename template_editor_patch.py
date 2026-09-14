"""Template image helpers for admin and public frontend rendering.

Both the admin Fabric editor and the customer editor need same-origin image bytes
when exporting a canvas. The proxy is intentionally narrow: it only reads images
from the configured Supabase project host.
"""
from urllib.parse import urlparse
from flask import request, Response

_INSTALLED = False


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

            upstream = requests_lib.get(url, timeout=15)
            if upstream.status_code < 200 or upstream.status_code >= 300:
                return no_cache_json({'status': 'error', 'msg': f'圖片讀取失敗（HTTP {upstream.status_code}）'}, 502)

            raw = upstream.content or b''
            if not raw:
                return no_cache_json({'status': 'error', 'msg': '圖片內容是空的'}, 502)
            if len(raw) > 12 * 1024 * 1024:
                return no_cache_json({'status': 'error', 'msg': '圖片超過 12MB'}, 413)

            content_type = str(upstream.headers.get('content-type') or '').split(';', 1)[0].lower()
            if content_type not in ('image/png', 'image/jpeg', 'image/webp'):
                return no_cache_json({'status': 'error', 'msg': '圖片格式不支援'}, 415)

            resp = Response(raw, mimetype=content_type)
            resp.headers['Cache-Control'] = 'private, max-age=3600' if require_admin else 'public, max-age=3600'
            resp.headers['X-Content-Type-Options'] = 'nosniff'
            return resp
        except Exception as exc:
            print('[TEMPLATE] asset proxy error:', repr(exc), flush=True)
            return no_cache_json({'status': 'error', 'msg': '模板圖片讀取失敗'}, 502)

    @app.route('/api/admin/template_asset_proxy', methods=['GET'])
    def admin_template_asset_proxy():
        return _serve_proxy(require_admin=True)

    @app.route('/api/public/asset_proxy', methods=['GET'])
    def public_template_asset_proxy():
        return _serve_proxy(require_admin=False)

    print('[TEMPLATE] admin + public same-origin asset proxy enabled', flush=True)
