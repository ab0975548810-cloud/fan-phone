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
                # Keep the everyday admin light. The heavy Fabric/template stack is
                # loaded only when the template section/editor is opened.
                scripts = [
                    '/static/admin-perf.js?v=20260916orders1',
                    '/static/admin-model-colors.js?v=20260926audit1',
                    '/static/admin-asset-categories.js?v=20260926audit1',
                    '/static/admin-template-loader.js?v=20260926audit1',
                    '/static/admin-orders-v3.js?v=20260917a',
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

    print('[PERF] lightweight admin + lazy template editor + order center v3 enabled', flush=True)
