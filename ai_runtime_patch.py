"""Runtime tuning and safe diagnostics for scale-to-zero AI background removal.

The production Runpod endpoint uses Active workers=0 so idle time costs nothing.
A true cold worker can take longer than a warm request; allow enough startup time
while keeping a hard deadline and exposing an admin-only health probe that never
reveals the API key.

This patch also exposes a same-origin MediaPipe vendor proxy. Mobile Safari can be
unreliable when dynamically importing cross-origin module URLs; serving the JS,
WASM and MagicTouch model through fanphone.zeabur.app avoids that browser/CDN edge.
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

    # Safari / canvas uploads can occasionally declare a different image MIME than
    # the bytes actually contain. Keep the security check, but trust PNG/JPEG/WEBP
    # magic bytes instead of the browser label and normalize the multipart MIME so
    # app.py and the Runpod worker receive the real format.
    try:
        import security_perf as security_module

        def _sniff_image_mime(file_storage):
            if not file_storage or not getattr(file_storage, 'stream', None):
                return ''
            stream = file_storage.stream
            try:
                pos = stream.tell()
            except Exception:
                pos = 0
            try:
                head = stream.read(32)
                stream.seek(pos)
            except Exception:
                return ''
            if head.startswith(b'\x89PNG\r\n\x1a\n'):
                return 'image/png'
            if head.startswith(b'\xff\xd8\xff'):
                return 'image/jpeg'
            if len(head) >= 12 and head[:4] == b'RIFF' and head[8:12] == b'WEBP':
                return 'image/webp'
            return ''

        def _valid_image_by_magic(file_storage):
            detected = _sniff_image_mime(file_storage)
            if not detected:
                return False
            try:
                file_storage.headers['Content-Type'] = detected
            except Exception:
                pass
            return True

        security_module._sniff_image_mime = _sniff_image_mime
        security_module._valid_image = _valid_image_by_magic
    except Exception as exc:
        print('[AI] image MIME compatibility patch warning:', repr(exc), flush=True)

    app = app_module.app

    # MediaPipe Tasks Vision 1.0.1, pinned so the JS and WASM files always match.
    # Browser requests stay same-origin; Zeabur performs the upstream fetch.
    mediapipe_version = '1.0.1'
    mediapipe_base = f'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@{mediapipe_version}'
    mediapipe_model = (
        'https://storage.googleapis.com/mediapipe-models/'
        'interactive_segmenter_v2/magic_touch/int8/1/interactive_segmentation.task'
    )
    allowed_wasm = {
        'vision_wasm_internal.js',
        'vision_wasm_internal.wasm',
        'vision_wasm_nosimd_internal.js',
        'vision_wasm_nosimd_internal.wasm',
        'vision_wasm_module_internal.js',
        'vision_wasm_module_internal.wasm',
    }

    @app.route('/vendor/mediapipe/<path:asset>', methods=['GET'])
    def mediapipe_vendor(asset):
        if not app_module.requests:
            return app_module.Response('requests unavailable', status=503, mimetype='text/plain')

        if asset == 'vision_bundle.mjs':
            upstream = f'{mediapipe_base}/vision_bundle.mjs'
            mime = 'application/javascript; charset=utf-8'
        elif asset == 'interactive_segmentation.task':
            upstream = mediapipe_model
            mime = 'application/octet-stream'
        elif asset.startswith('wasm/'):
            filename = asset.split('/', 1)[1]
            if filename not in allowed_wasm:
                return app_module.Response('Not found', status=404, mimetype='text/plain')
            upstream = f'{mediapipe_base}/wasm/{filename}'
            mime = 'application/wasm' if filename.endswith('.wasm') else 'application/javascript; charset=utf-8'
        else:
            return app_module.Response('Not found', status=404, mimetype='text/plain')

        try:
            resp = app_module.requests.get(
                upstream,
                timeout=30,
                headers={'User-Agent': 'Benfuwan-MediaPipe-Proxy/1.0'},
            )
            if resp.status_code < 200 or resp.status_code >= 300:
                return app_module.Response(
                    f'Upstream MediaPipe error: HTTP {resp.status_code}',
                    status=502,
                    mimetype='text/plain',
                )
            out = app_module.Response(resp.content, status=200, content_type=mime)
            out.headers['Cache-Control'] = 'public, max-age=86400, immutable'
            out.headers['X-Benfuwan-Vendor'] = f'mediapipe-tasks-vision-{mediapipe_version}'
            return out
        except Exception as exc:
            print('mediapipe vendor proxy error:', asset, repr(exc), flush=True)
            return app_module.Response('MediaPipe vendor temporarily unavailable', status=502, mimetype='text/plain')

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
        f'poll={app_module.AI_POLL_INTERVAL}s; MediaPipe same-origin proxy enabled; image magic-byte validation enabled',
        flush=True,
    )
