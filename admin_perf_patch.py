"""Inject small admin helpers into authenticated /admin HTML."""
from flask import request

_INSTALLED = False


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = app_module.app

    @app.after_request
    def _inject_admin_helpers(resp):
        if request.path == '/admin' and resp.status_code == 200 and resp.mimetype == 'text/html':
            try:
                # /admin is served with Flask send_file(), which uses direct_passthrough.
                if getattr(resp, 'direct_passthrough', False):
                    resp.direct_passthrough = False

                html = resp.get_data(as_text=True)
                scripts = [
                    '/static/admin-perf.js?v=20260913d',
                    '/static/admin-model-colors.js?v=20260913d',
                    '/static/admin-asset-categories.js?v=20260913j',
                    '/static/admin-universal-templates.js?v=20260913k',
                ]
                for src in scripts:
                    if src not in html and '</body>' in html:
                        html = html.replace('</body>', f'<script src="{src}"></script></body>')
                resp.set_data(html)
                resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
                resp.headers.pop('Content-Length', None)
            except Exception as exc:
                print('[PERF] admin helper injection warning:', repr(exc), flush=True)
        return resp

    print('[PERF] admin page lazy-load + model-color + asset + universal-template helpers enabled', flush=True)
