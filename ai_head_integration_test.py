"""Browser-level verification for the guided AI-head MediaPipe pipeline.

This intentionally uses Playwright WebKit because the production failure was
reported on iPhone Safari.  It runs the real storefront helper JS, same-origin
Flask proxy, MediaPipe ESM/WASM/model, setImage(), segment(), preview and cut().
"""
from __future__ import annotations

import math
import threading
import time

from flask import Response
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

import app as app_module
from mediapipe_proxy import install as install_mediapipe_proxy
from security_perf import install as install_security


# Production installs in this order so the proxy's after_request runs last and
# adds wasm-unsafe-eval to the security CSP.
install_mediapipe_proxy(app_module)
install_security(app_module)


@app_module.app.route('/__ai_head_test')
def ai_head_test_page():
    html = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>AI head verification</title></head>
<body>
<canvas id="source" width="192" height="192"></canvas>
<canvas id="preview" width="192" height="192"></canvas>
<script src="/static/ai-head-interactive-v1.js?v=integration"></script>
</body></html>'''
    return Response(html, content_type='text/html; charset=utf-8')


def _run_server(server):
    server.serve_forever()


def main():
    server = make_server('127.0.0.1', 8765, app_module.app, threaded=True)
    thread = threading.Thread(target=_run_server, args=(server,), daemon=True)
    thread.start()
    time.sleep(0.4)

    console = []
    page_errors = []
    try:
        with sync_playwright() as p:
            browser = p.webkit.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                user_agent=(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.6 "
                    "Mobile/15E148 Safari/604.1"
                ),
            )
            page = context.new_page()
            page.on('console', lambda msg: console.append(f'{msg.type}: {msg.text}'))
            page.on('pageerror', lambda exc: page_errors.append(str(exc)))

            response = page.goto('http://127.0.0.1:8765/__ai_head_test', wait_until='load', timeout=120_000)
            assert response and response.ok, f'test page HTTP failed: {response.status if response else "no response"}'

            # Sanity-check the exact module endpoint and MIME type Safari imports.
            bundle = context.request.get('http://127.0.0.1:8765/vendor/mediapipe/vision_bundle.mjs?v=1.0.1', timeout=120_000)
            assert bundle.ok, f'bundle proxy HTTP {bundle.status}'
            ctype = (bundle.headers.get('content-type') or '').lower()
            assert 'javascript' in ctype, f'wrong bundle MIME: {ctype}'
            assert len(bundle.body()) > 50_000, 'bundle body unexpectedly small'

            result = page.evaluate(r'''async () => {
              const helper = window.BenfuwanInteractiveHead;
              if (!helper) throw new Error('BenfuwanInteractiveHead missing');

              const canvas = document.getElementById('source');
              const g = canvas.getContext('2d');
              // Give MagicTouch a simple but non-uniform image with a clear central object.
              g.fillStyle = '#e8e8e8'; g.fillRect(0, 0, 192, 192);
              g.fillStyle = '#1f5fbf'; g.beginPath(); g.arc(96, 78, 48, 0, Math.PI * 2); g.fill();
              g.fillStyle = '#f0b040'; g.fillRect(72, 112, 48, 60);
              g.fillStyle = '#ffffff'; g.beginPath(); g.arc(82, 70, 7, 0, Math.PI * 2); g.fill();
              g.beginPath(); g.arc(110, 70, 7, 0, Math.PI * 2); g.fill();

              const strokes = [{
                mode: 'positive',
                points: [
                  {x: 0.50, y: 0.36},
                  {x: 0.50, y: 0.43},
                  {x: 0.50, y: 0.50}
                ]
              }];

              const mask = await helper.segment(canvas, strokes);
              if (!mask || !mask.data || !mask.width || !mask.height) {
                throw new Error('segment() returned no mask');
              }
              if (mask.data.length !== mask.width * mask.height) {
                throw new Error(`mask size mismatch ${mask.data.length} vs ${mask.width}x${mask.height}`);
              }
              let min = Infinity, max = -Infinity, finite = 0;
              for (let i = 0; i < mask.data.length; i++) {
                const v = Number(mask.data[i]);
                if (Number.isFinite(v)) { finite++; if (v < min) min = v; if (v > max) max = v; }
              }
              if (finite !== mask.data.length) throw new Error('mask contains non-finite values');

              helper.drawPreview(document.getElementById('preview'), mask, strokes);
              const cut = helper.cut(canvas, mask, strokes);
              if (!cut || !cut.canvas || cut.canvas.width < 1 || cut.canvas.height < 1) {
                throw new Error('cut() returned invalid canvas');
              }
              const png = cut.canvas.toDataURL('image/png');
              if (!png.startsWith('data:image/png;base64,') || png.length < 100) {
                throw new Error('cut() PNG export failed');
              }
              return {
                version: helper.version,
                maskWidth: mask.width,
                maskHeight: mask.height,
                maskLength: mask.data.length,
                min, max,
                cutWidth: cut.canvas.width,
                cutHeight: cut.canvas.height,
                pngLength: png.length
              };
            }''')

            assert result['maskWidth'] > 0 and result['maskHeight'] > 0
            assert result['maskLength'] == result['maskWidth'] * result['maskHeight']
            assert math.isfinite(result['min']) and math.isfinite(result['max'])
            assert result['cutWidth'] > 0 and result['cutHeight'] > 0
            assert result['pngLength'] > 100
            assert not page_errors, f'WebKit page errors: {page_errors}'
            print('AI_HEAD_WEBKIT_OK', result, flush=True)
            if console:
                print('--- browser console ---', flush=True)
                for line in console[-30:]:
                    print(line, flush=True)

            context.close()
            browser.close()
    except Exception:
        print('--- browser console before failure ---', flush=True)
        for line in console[-50:]:
            print(line, flush=True)
        if page_errors:
            print('--- page errors ---', flush=True)
            for line in page_errors:
                print(line, flush=True)
        raise
    finally:
        server.shutdown()
        thread.join(timeout=2)


if __name__ == '__main__':
    main()
