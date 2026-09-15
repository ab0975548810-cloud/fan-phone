"""Runtime tuning and safe diagnostics for scale-to-zero AI background removal.

The production Runpod endpoint uses Active workers=0 so idle time costs nothing.
A true cold worker can take longer than a warm request; allow enough startup time
while keeping a hard deadline and exposing an admin-only health probe that never
reveals the API key.
"""

_INSTALLED = False


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    # Scale-to-zero can occasionally need more than 75s for a true cold start.
    # 180s is bounded, and the backend cancels the Runpod job at the deadline.
    try:
        configured = int(app_module.AI_REMOVE_BG_TIMEOUT or 180)
        app_module.AI_REMOVE_BG_TIMEOUT = max(120, min(configured, 180))
    except Exception:
        app_module.AI_REMOVE_BG_TIMEOUT = 180

    try:
        app_module.AI_POLL_INTERVAL = min(float(app_module.AI_POLL_INTERVAL or 1.5), 1.5)
    except Exception:
        app_module.AI_POLL_INTERVAL = 1.5

    app = app_module.app

    @app.route('/api/admin/ai_remove_diagnose', methods=['GET'])
    def ai_remove_diagnose():
        if not app_module.session.get('logged_in'):
            return app_module.no_cache_json({'status':'error','msg':'未登入'}, 401)
        endpoint_id = str(app_module.RUNPOD_ENDPOINT_ID or '').strip()
        configured = bool(app_module.RUNPOD_API_KEY and endpoint_id and app_module.requests)
        result = {
            'status': 'configured' if configured else 'not_configured',
            'api_key_configured': bool(app_module.RUNPOD_API_KEY),
            'endpoint_configured': bool(endpoint_id),
            'endpoint_id': endpoint_id,
            'timeout_seconds': app_module.AI_REMOVE_BG_TIMEOUT,
            'active_workers_expected': 0,
        }
        if not configured:
            return app_module.no_cache_json(result, 503)
        try:
            url = f'{app_module.RUNPOD_API_BASE}/{endpoint_id}/health'
            resp = app_module.requests.get(url, headers=app_module._runpod_headers(), timeout=12)
            result['health_http'] = resp.status_code
            result['health_body'] = (resp.text or '')[:800]
            result['status'] = 'transport_ok' if 200 <= resp.status_code < 300 else 'endpoint_or_key_error'
            return app_module.no_cache_json(result, 200)
        except Exception as exc:
            result['status'] = 'transport_error'
            result['detail'] = str(exc)[:240]
            return app_module.no_cache_json(result, 200)

    print(
        f'[AI] scale-to-zero runtime tuned: remove-bg timeout={app_module.AI_REMOVE_BG_TIMEOUT}s '
        f'poll={app_module.AI_POLL_INTERVAL}s',
        flush=True,
    )
