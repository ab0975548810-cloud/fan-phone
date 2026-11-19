"""Exercise recovery and native export after repeated pixel-editor operations."""
import io
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_pixel_orders as fixture
from test_order_design_browser import wait


def run():
    test = fixture.PixelTests()
    test.setUp()
    app = fixture.app
    order = app.commerce.store.order(test.order)
    size = (2030, 4241)
    original = Image.new('RGBA', size)
    draw = ImageDraw.Draw(original)
    draw.ellipse((760, 820, 1230, 1300), fill=(45, 120, 190, 183))
    draw.rectangle((1500, 3000, 1590, 3090), fill=(240, 80, 30, 255))
    raw = fixture.encode(original)
    Path(app.SAVE_DIR, order['print_path']).write_bytes(raw)
    server = make_server('127.0.0.1', 0, app.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    path = f'/admin/order-design/{test.order}?pixel=1'
    try:
        with sync_playwright() as p:
            engine = os.environ.get('BROWSER_ENGINE', 'webkit')
            browser = getattr(p, engine).launch()
            context = browser.new_context(viewport={'width': 402, 'height': 874},
                                          device_scale_factor=3, has_touch=True)
            context.add_cookies([{'name': cookie.key, 'value': cookie.value, 'url': base}
                                 for cookie in test.client._cookies.values()])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base+path)
            wait(page, "document.querySelector('#pixel-status')?.textContent.includes('正在編輯 V1')")
            assert page.evaluate('canvas.getRetinaScaling()') == 1

            def select():
                page.locator('#pixel-extract').click()
                x,y = page.evaluate("""() => {
                    const point=fabric.util.transformPoint(new fabric.Point(200,210),canvas.viewportTransform);
                    const r=canvas.upperCanvasEl.getBoundingClientRect();
                    return [r.left+point.x*r.width/canvas.getWidth(),r.top+point.y*r.height/canvas.getHeight()];
                }""")
                page.touchscreen.tap(x,y)
                wait(page, "canvas.getObjects().some(o=>o.pixelExtractionBounds)")

            def adjust(key,value):
                page.evaluate("""([key,value])=>{
                    const picture=canvas.getObjects().find(o=>o.pixelExtractionBounds);
                    picture.set(key, value);
                    picture.setCoords();
                    canvas.fire('object:modified',{target:picture});
                    recordHistory();
                    canvas.requestRenderAll();
                }""",[key,value])

            for i in range(5):
                select()
                adjust('left',220+i)
                adjust('scaleX',.28)
                adjust('scaleY',.28)
                adjust('angle',27)
                wait(page, "document.querySelector('#pixel-recovery').textContent.includes('已暫存')")
                if i == 0:
                    # Kill the page and create a new one with the same origin storage.
                    page.close(run_before_unload=False)
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base+path)
                    wait(page, "document.querySelector('#pixel-status')?.textContent.includes('已復原')")
                    assert page.evaluate("""() => {
                        const o=canvas.getObjects().find(o=>o.pixelExtractionBounds);
                        return o.left===220 && o.angle===27 && o.scaleX===.28;
                    }""")
                if i < 4:
                    page.evaluate("canvas.remove(canvas.getObjects().find(o=>o.pixelExtractionBounds));recordHistory()")
                    assert page.evaluate('canvas.getObjects().length') == 1
                    page.locator('#pixel-back').click()
                    page.wait_for_url(base+'/admin')
                    page.goto(base+path)
                    wait(page,"document.querySelector('#pixel-status')?.textContent.includes('已復原')")
                    assert page.evaluate('canvas.getObjects().length') == 1

            with page.expect_response(lambda response: response.url.endswith('/pixel/save')) as saved:
                page.locator('#pixel-save').click()
            assert saved.value.ok,saved.value.json()
            wait(page,"document.querySelector('#pixel-status')?.textContent.includes('V2 已保存')")
            page.reload()
            wait(page,"document.querySelector('#pixel-status')?.textContent.includes('正在編輯 V2')")
            assert page.evaluate('canvas.getObjects().filter(o=>o.pixelExtractionMask).length')==1
            assert page.evaluate('canvas.getObjects().find(o=>o.pixelExtractionBounds).angle')==27
            page.locator('#pixel-review').click()
            wait(page,"Array.from(document.querySelectorAll('#pixel-compare img')).length===2 && Array.from(document.querySelectorAll('#pixel-compare img')).every(im=>im.naturalHeight===1200)")
            assert page.locator('#pixel-confirm').is_disabled()
            page.keyboard.press('Escape')
            wait(page,"!document.querySelector('#pixel-compare')")
            assert not errors,errors
            browser.close()

        v1,v2=[row['document'] for row in app.order_designs.rows(test.order)]
        assert app.print_center._download_artwork(v1['basePath'])==raw
        assert v2['proof']['unchangedRGBA'] and v2['proof']['alphaExpansion'] and not v2['profile']
        output=Image.open(io.BytesIO(app.print_center._download_artwork(v2['outputPath'])))
        assert output.size==size and abs(output.info['dpi'][0]-720)<.1
        assert output.getpixel((1530,3030))==original.getpixel((1530,3030))
        assert not test.fx.fake.calls
        print(f'PIXEL_P0_RECOVERY_OK {engine}: 25 layer operations, 5 page switches, V1/V2 720 DPI',flush=True)
    finally:
        server.shutdown()
        test.tearDown()
        test.doCleanups()


if __name__ == '__main__':
    run()
