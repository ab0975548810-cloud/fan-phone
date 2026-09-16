import os
import threading
import time
from io import BytesIO

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

# Match production middleware order closely enough to verify the real /admin page.
install_security(app_module)
install_supabase_resilience(app_module)
install_quality_perf(app_module)
install_ai_runtime(app_module)
install_admin_perf(app_module)
install_order_colors(app_module)
install_asset_categories(app_module)
install_template_editor(app_module)
install_order_management(app_module)

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
            page.wait_for_function('window.__benfuwanTemplateStackReady === true', timeout=30000)
            page.wait_for_function('window.__benfuwanTemplateUploadFixV1 === true', timeout=10000)

            page.click('#view-templates .titlebar .btn')
            page.wait_for_selector('#template-modal.show', timeout=30000)
            page.wait_for_function('window.visualCanvas && document.querySelector("#bf-tpl-image-file-v3")', timeout=30000)

            # Deliberately give a generic MIME while keeping a .jpg filename. The fix
            # must normalize it instead of failing before the server receives it.
            page.set_input_files('#bf-tpl-image-file-v3', {
                'name': 'template-photo.jpg',
                'mime_type': 'application/octet-stream',
                'buffer': jpg,
            })
            page.wait_for_function("document.querySelector('#bf-tpl-status')?.textContent.includes('圖片已加入')", timeout=30000)
            image_state = page.evaluate("""() => {
              const c=window.visualCanvas;
              const imgs=c.getObjects().filter(o=>o.type==='image'&&!o.isTplBg);
              const o=imgs[imgs.length-1];
              return {count:imgs.length, publicSrc:o?.publicSrc||'', width:o?.getScaledWidth?.()||0};
            }""")
            assert image_state['count'] >= 1, image_state
            assert image_state['publicSrc'], image_state
            assert image_state['width'] > 0, image_state

            # The uploaded standardized image must be retrievable, not just present in Fabric memory.
            uploaded = page.request.get(BASE + image_state['publicSrc'])
            assert uploaded.ok, (uploaded.status, image_state)
            assert uploaded.body()[:4] == b'RIFF', 'server did not standardize template image to WebP'

            page.set_input_files('#tpl-bg-file', {
                'name': 'template-background.jpg',
                'mime_type': 'image/jpeg',
                'buffer': jpg,
            })
            page.wait_for_function("document.querySelector('#bf-tpl-status')?.textContent.includes('底圖已加入')", timeout=30000)
            bg_state = page.evaluate("""() => {
              const c=window.visualCanvas;
              const bg=c.getObjects().find(o=>o.isTplBg);
              return {exists:!!bg, publicSrc:bg?.publicSrc||'', width:bg?.getScaledWidth?.()||0};
            }""")
            assert bg_state['exists'] and bg_state['publicSrc'] and bg_state['width'] > 0, bg_state

            # Canvas export verifies the upload did not taint Fabric/CORS state.
            exported = page.evaluate("window.visualCanvas.toDataURL({format:'png',multiplier:1}).slice(0,30)")
            assert exported.startswith('data:image/png;base64,'), exported

            print('TEMPLATE_UPLOAD_WEBKIT_OK', image_state, bg_state)
            if console_errors:
                print('WEBKIT_CONSOLE_ERRORS', console_errors)
            browser.close()
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
