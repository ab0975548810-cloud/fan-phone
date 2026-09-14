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
                if getattr(resp, 'direct_passthrough', False):
                    resp.direct_passthrough = False

                html = resp.get_data(as_text=True)
                scripts = [
                    '/static/admin-perf.js?v=20260913d',
                    '/static/admin-model-colors.js?v=20260913d',
                    '/static/admin-asset-categories.js?v=20260913j',
                    '/static/admin-universal-templates.js?v=20260913k',
                    '/static/admin-template-editor-v2.js?v=20260913l',
                    '/static/admin-template-editor-v3.js?v=20260914a',
                    '/static/admin-template-editor-v4.js?v=20260914c',
                    '/static/admin-template-editor-v4-fix.js?v=20260914c',
                    '/static/admin-global-canvas-bridge.js?v=20260914f',
                    '/static/admin-template-clean-v2.js?v=20260914f',
                    '/static/admin-template-outline-v2.js?v=20260914f',
                    '/static/admin-orders-v2.js?v=20260914a',
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

    print('[PERF] admin helpers enabled: template canvas bridge + clean canvas + outline v2 + orders v2', flush=True)
