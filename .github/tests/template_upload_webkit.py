import os
import sys
import threading
import time
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

os.environ['ADMIN_PASSWORD'] = 'template-test-pass'
os.environ['SESSION_COOKIE_SECURE'] = 'false'

import app as app_module
from admin_perf_patch import install as install_admin_perf
from asset_category_patch import install as install_asset_categories
from order_color_patch import install as install_order_colors
from order_management_patch import install as install_order_management
from quality_perf_patch import install as install_quality_perf
from security_perf import install as install_security
from supabase_resilience import install as install_supabase_resilience
from template_editor_patch import install as install_template_editor
from ai_runtime_patch import install as install_ai_runtime

install_security(app_module)
install_supabase_resilience(app_module)
install_quality_perf(app_module)
install_ai_runtime(app_module)
install_admin_perf(app_module)
install_order_colors(app_module)
install_asset_categories(app_module)
install_template_editor(app_module)
install_order_management(app_module)

# Production correctly requires Secure cookies. Local WebKit is plain HTTP.
app_module.app.config['SESSION_COOKIE_SECURE'] = False

from werkzeug.serving import make_server
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

PORT = 8765
BASE = f'http://127.0.0.1:{PORT}'


def sample_jpeg():
    im = Image.new('RGB', (2400, 1600), (250, 235, 241))
    d = ImageDraw.Draw(im)
    d.rectangle((250, 180, 2150, 1420), fill=(255, 115, 157))
    d.ellipse((700, 300, 1700, 1300), fill=(255, 220, 80))
    out = BytesIO()
    im.save(out, format='JPEG', quality=94)
    return out.getvalue()


def wait_js(page, fn_source, timeout_ms=30000, label='condition'):
    """Poll via Playwright's execution context without page-side eval()/setTimeout()."""
    deadline = time.monotonic() + timeout_ms / 1000
    last = None
    while time.monotonic() < deadline:
        try:
            if page.evaluate(fn_source):
                return
        except Exception as exc:
            last = exc
        time.sleep(0.12)
    raise AssertionError(f'timed out waiting for {label}: {last or "false"}')


def main():
    server = make_server('127.0.0.1', PORT, app_module.app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.4)
    jpg = sample_jpeg()

    try:
        with sync_playwright() as p:
            browser = p.webkit.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            console_errors = []
            page.on('console', lambda m: console_errors.append(m.text) if m.type == 'error' else None)

            page.goto(BASE + '/login', wait_until='domcontentloaded')
            page.fill('input[name="password"]', 'template-test-pass')
            page.click('button[type="submit"]')
            page.wait_for_url('**/admin')
            page.wait_for_selector('button[data-view="templates"]')
            page.click('button[data-view="templates"]')
            wait_js(page, '() => window.__benfuwanTemplateStackReady === true', 30000, 'template stack')
            wait_js(page, '() => window.__benfuwanTemplateUploadFixV1 === true', 10000, 'upload fix')

            page.click('#view-templates .titlebar .btn')
            page.wait_for_selector('#template-modal.show', timeout=30000)
            wait_js(page, '() => !!window.visualCanvas && !!document.querySelector("#bf-tpl-image-file-v3")', 30000, 'template canvas')

            # Generic MIME + .jpg filename exercises Safari-style missing/odd MIME normalization.
            page.set_input_files('#bf-tpl-image-file-v3', {
                'name': 'template-photo.jpg',
                'mime_type': 'application/octet-stream',
                'buffer': jpg,
            })
            page.locator('#bf-tpl-status').filter(has_text='圖片已加入').wait_for(timeout=30000)
            image_state = page.evaluate("""() => {
              const c=window.visualCanvas;
              const imgs=c.getObjects().filter(o=>o.type==='image'&&!o.isTplBg);
              const o=imgs[imgs.length-1];
              return {count:imgs.length, publicSrc:o?.publicSrc||'', width:o?.getScaledWidth?.()||0};
            }""")
            assert image_state['count'] >= 1, image_state
            assert image_state['publicSrc'], image_state
            assert image_state['width'] > 0, image_state

            uploaded = page.request.get(BASE + image_state['publicSrc'])
            assert uploaded.ok, (uploaded.status, image_state)
            assert uploaded.body()[:4] == b'RIFF', 'server did not standardize template image to WebP'

            page.set_input_files('#tpl-bg-file', {
                'name': 'template-background.jpg',
                'mime_type': 'image/jpeg',
                'buffer': jpg,
            })
            page.locator('#bf-tpl-status').filter(has_text='底圖已加入').wait_for(timeout=30000)
            bg_state = page.evaluate("""() => {
              const c=window.visualCanvas;
              const bg=c.getObjects().find(o=>o.isTplBg);
              return {exists:!!bg, publicSrc:bg?.publicSrc||'', width:bg?.getScaledWidth?.()||0};
            }""")
            assert bg_state['exists'] and bg_state['publicSrc'] and bg_state['width'] > 0, bg_state

            exported = page.evaluate("() => window.visualCanvas.toDataURL({format:'png',multiplier:1}).slice(0,30)")
            assert exported.startswith('data:image/png;base64,'), exported

            print('TEMPLATE_UPLOAD_WEBKIT_OK', image_state, bg_state)
            if console_errors:
                print('WEBKIT_CONSOLE_ERRORS', console_errors)
            browser.close()
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
