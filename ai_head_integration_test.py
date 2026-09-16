"""Browser-level verification for the guided AI-head MediaPipe pipeline.

Uses Playwright WebKit (Safari engine) and verifies both the raw MediaPipe path
and the actual storefront flow: open guide -> draw -> preview -> apply -> replace
Fabric image -> record history.  Production main is not touched by this test.
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


install_mediapipe_proxy(app_module)
install_security(app_module)


@app_module.app.route('/__ai_head_test')
def ai_head_test_page():
    html = r'''<!doctype html>
<html><head><meta charset="utf-8"><title>AI head verification</title></head>
<body>
<div id="object-bar"><button type="button" onclick="deleteActive()">delete</button></div>
<div id="sheet-upload"><div class="ai-box"></div></div>
<canvas id="source" width="192" height="192"></canvas>
<canvas id="preview" width="192" height="192"></canvas>
<script>
var __objects = [];
var __active = null;
var __history = 0;
var __renderCount = 0;
var __toasts = [];
var canvas = {
  getActiveObject: function(){ return window.__active; },
  getObjects: function(){ return window.__objects; },
  on: function(){},
  remove: function(o){
    var i = window.__objects.indexOf(o);
    if(i >= 0) window.__objects.splice(i, 1);
    if(window.__active === o) window.__active = null;
  },
  insertAt: function(o, i){
    i = Math.max(0, Math.min(Number(i)||0, window.__objects.length));
    window.__objects.splice(i, 0, o);
    return o;
  },
  setActiveObject: function(o){ window.__active = o; return this; },
  requestRenderAll: function(){ window.__renderCount++; }
};
class FakeFabricImage {
  constructor(el, opts){
    this.type = 'image';
    this.width = Number(el.naturalWidth || el.width || 1);
    this.height = Number(el.naturalHeight || el.height || 1);
    Object.assign(this, opts || {});
  }
  set(v){ Object.assign(this, v || {}); return this; }
  setCoords(){}
  getCenterPoint(){ return {x:Number(this.left||0), y:Number(this.top||0)}; }
  getScaledWidth(){ return Math.max(1, this.width * Number(this.scaleX || 1)); }
}
var fabric = {Image: FakeFabricImage};
function recordHistory(){ window.__history++; }
function renderLayerList(){ window.__layerRendered = true; }
function syncSelection(){ window.__selectionSynced = true; }
function styleEditableObject(o){ o.__styled = true; }
function closeSheets(){}
function setBusy(v, msg){ window.__busyState = !!v; window.__busyMessage = msg || ''; }
function toast(msg){ window.__toasts.push(String(msg)); }
function deleteActive(){}

var oldPhoto = {
  type:'image', role:'photo', width:192, height:192, scaleX:1, scaleY:1,
  left:120, top:160, angle:0, flipX:false, flipY:false, opacity:1,
  getElement:function(){ return document.getElementById('source'); },
  getCenterPoint:function(){ return {x:120,y:160}; },
  getScaledWidth:function(){ return 192; }
};
window.__oldPhoto = oldPhoto;
window.__objects = [oldPhoto];
window.__active = oldPhoto;
</script>
<script src="/static/ai-head-interactive-v1.js?v=integration"></script>
<script src="/static/front-ai-head-cutout.js?v=integration"></script>
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

            bundle = context.request.get('http://127.0.0.1:8765/vendor/mediapipe/vision_bundle.mjs?v=1.0.1', timeout=120_000)
            assert bundle.ok, f'bundle proxy HTTP {bundle.status}'
            ctype = (bundle.headers.get('content-type') or '').lower()
            assert 'javascript' in ctype, f'wrong bundle MIME: {ctype}'
            assert len(bundle.body()) > 50_000, 'bundle body unexpectedly small'

            module_info = page.evaluate(r'''async () => {
              const mod = await import('/vendor/mediapipe/vision_bundle.mjs?v=1.0.1-diagnostics');
              return {
                keys: Object.keys(mod).sort(),
                hasFilesetResolver: !!mod.FilesetResolver,
                hasInteractiveSegmenter: !!mod.InteractiveSegmenter,
                hasBrushMode: !!mod.BrushMode
              };
            }''')
            print('MEDIAPIPE_MODULE_INFO', module_info, flush=True)

            # Draw one clear foreground object and first test the helper API itself.
            result = page.evaluate(r'''async () => {
              const helper = window.BenfuwanInteractiveHead;
              if (!helper) throw new Error('BenfuwanInteractiveHead missing');

              const source = document.getElementById('source');
              const g = source.getContext('2d');
              g.fillStyle = '#e8e8e8'; g.fillRect(0, 0, 192, 192);
              g.fillStyle = '#1f5fbf'; g.beginPath(); g.arc(96, 78, 48, 0, Math.PI * 2); g.fill();
              g.fillStyle = '#f0b040'; g.fillRect(72, 112, 48, 60);
              g.fillStyle = '#ffffff'; g.beginPath(); g.arc(82, 70, 7, 0, Math.PI * 2); g.fill();
              g.beginPath(); g.arc(110, 70, 7, 0, Math.PI * 2); g.fill();

              const strokes = [{mode:'positive',points:[
                {x:0.50,y:0.36},{x:0.50,y:0.43},{x:0.50,y:0.50}
              ]}];
              const mask = await helper.segment(source, strokes);
              if (!mask || !mask.data || !mask.width || !mask.height) throw new Error('segment() returned no mask');
              if (mask.data.length !== mask.width * mask.height) throw new Error('mask size mismatch');
              let min = Infinity, max = -Infinity, finite = 0;
              for (let i=0;i<mask.data.length;i++) {
                const v=Number(mask.data[i]);
                if(Number.isFinite(v)){finite++;if(v<min)min=v;if(v>max)max=v;}
              }
              if(finite !== mask.data.length) throw new Error('mask contains non-finite values');
              helper.drawPreview(document.getElementById('preview'), mask, strokes);
              const cut=helper.cut(source,mask,strokes);
              if(!cut?.canvas?.width||!cut?.canvas?.height) throw new Error('cut() returned invalid canvas');
              const png=cut.canvas.toDataURL('image/png');
              if(!png.startsWith('data:image/png;base64,')||png.length<100) throw new Error('cut() PNG export failed');
              return {version:helper.version,maskWidth:mask.width,maskHeight:mask.height,maskLength:mask.data.length,min,max,cutWidth:cut.canvas.width,cutHeight:cut.canvas.height,pngLength:png.length};
            }''')
            assert result['maskWidth'] > 0 and result['maskHeight'] > 0
            assert result['maskLength'] == result['maskWidth'] * result['maskHeight']
            assert math.isfinite(result['min']) and math.isfinite(result['max'])
            assert result['cutWidth'] > 0 and result['cutHeight'] > 0 and result['pngLength'] > 100
            print('AI_HEAD_WEBKIT_HELPER_OK', result, flush=True)

            # Now test the real front-ai-head-cutout.js interaction and Fabric replacement.
            started = page.evaluate("() => { window.__uiRun = window.makeAiHeadCutout(); return true; }")
            assert started is True
            page.wait_for_selector('#bf-ai-head-guide', state='visible', timeout=10_000)
            paint = page.locator('#bf-ai-head-guide .paint')
            box = paint.bounding_box()
            assert box and box['width'] > 20 and box['height'] > 20, f'paint canvas missing: {box}'

            x = box['x'] + box['width'] * 0.50
            y1 = box['y'] + box['height'] * 0.27
            y2 = box['y'] + box['height'] * 0.54
            page.mouse.move(x, y1)
            page.mouse.down()
            page.mouse.move(x, y2, steps=12)
            page.mouse.up()

            page.locator('#bf-ai-head-guide [data-act="preview"]').click()
            page.wait_for_function(
                "() => { const b=document.querySelector('#bf-ai-head-guide [data-act=\"apply\"]'); return !!b && !b.disabled; }",
                timeout=120_000,
            )
            status_text = page.locator('#bf-ai-head-guide .status').inner_text()
            assert '半透明粉紅區' in status_text, f'preview did not finish normally: {status_text}'
            page.locator('#bf-ai-head-guide [data-act="apply"]').click()
            page.wait_for_selector('#bf-ai-head-guide', state='detached', timeout=15_000)
            page.wait_for_function("() => window.__active && window.__active !== window.__oldPhoto", timeout=15_000)

            ui_result = page.evaluate(r'''() => {
              const neo=window.__active;
              return {
                objectCount:window.__objects.length,
                oldRemoved:!window.__objects.includes(window.__oldPhoto),
                replaced:neo!==window.__oldPhoto,
                aiHeadCutout:!!neo?.aiHeadCutout,
                aiBackgroundRemoved:!!neo?.aiBackgroundRemoved,
                aiHeadMode:String(neo?.aiHeadMode||''),
                role:String(neo?.role||''),
                width:Number(neo?.width||0),
                height:Number(neo?.height||0),
                scaleX:Number(neo?.scaleX||0),
                scaleY:Number(neo?.scaleY||0),
                history:Number(window.__history||0),
                renderCount:Number(window.__renderCount||0),
                layerRendered:!!window.__layerRendered,
                selectionSynced:!!window.__selectionSynced,
                styled:!!neo?.__styled,
                busy:!!window.__busyState,
                toasts:window.__toasts.slice()
              };
            }''')
            assert ui_result['objectCount'] == 1, ui_result
            assert ui_result['oldRemoved'] and ui_result['replaced'], ui_result
            assert ui_result['aiHeadCutout'] and ui_result['aiBackgroundRemoved'], ui_result
            assert ui_result['aiHeadMode'].startswith('interactive-guided-v3'), ui_result
            assert ui_result['role'] == 'photo', ui_result
            assert ui_result['width'] > 0 and ui_result['height'] > 0, ui_result
            assert ui_result['scaleX'] > 0 and ui_result['scaleY'] > 0, ui_result
            assert ui_result['history'] >= 1 and ui_result['renderCount'] >= 1, ui_result
            assert ui_result['layerRendered'] and ui_result['selectionSynced'] and ui_result['styled'], ui_result
            assert ui_result['busy'] is False, ui_result
            print('AI_HEAD_WEBKIT_UI_APPLY_OK', ui_result, flush=True)

            assert not page_errors, f'WebKit page errors: {page_errors}'
            if console:
                print('--- browser console ---', flush=True)
                for line in console[-40:]:
                    print(line, flush=True)

            context.close()
            browser.close()
    except Exception:
        print('--- browser console before failure ---', flush=True)
        for line in console[-60:]:
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
