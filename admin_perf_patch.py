"""Inject the small admin performance helper into authenticated /admin HTML."""
from flask import request

_INSTALLED = False


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = app_module.app

    @app.after_request
    def _inject_admin_perf(resp):
        if request.path == '/admin' and resp.status_code == 200 and resp.mimetype == 'text/html':
            try:
                html = resp.get_data(as_text=True)
                marker = '/static/admin-perf.js?v=20260913b'
                if marker not in html and '</body>' in html:
                    html = html.replace('</body>', f'<script src="{marker}"></script></body>')
                    resp.set_data(html)
                resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            except Exception as exc:
                print('[PERF] admin helper injection warning:', repr(exc), flush=True)
        return resp

    print('[PERF] admin page lazy-load helper enabled', flush=True)
