"""Real WebKit/Chromium extraction test with private fixture and fake vendor only."""
import copy
import io
import os
import sys
import threading
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
os.chdir(ROOT)
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_pixel_orders as fx
from test_order_design_browser import wait


def run():
    t=fx.PixelTests()
    t.setUp()
    server=None
    try:
        size=(600,1200)
        art=Image.new('RGBA',size,(0,0,0,0))
        draw=ImageDraw.Draw(art)
        draw.ellipse((50,90,230,280),fill=(80,80,80,255))
        draw.rectangle((350,450,490,580),fill=(240,190,30,115))
        draw.rectangle((490,450,540,580),fill=(20,90,140,255))
        draw.ellipse((65,735,210,865),fill=(240,180,180,255))
        raw=fx.encode(art)
        app=fx.app
        order=app.commerce.store.order(t.order)
        Path(app.SAVE_DIR,order['print_path']).write_bytes(raw)
        with app.print_center.store.connection(True) as db:
            db.execute('UPDATE print_jobs SET artwork_sha256=?,width_mm=?,height_mm=? WHERE id=?',
                       (fx.sha(raw),size[0]*25.4/720,size[1]*25.4/720,t.source['id']))
        original=copy.deepcopy(app.commerce.read())
        server=make_server('127.0.0.1',0,app.app,threaded=True)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        url='http://127.0.0.1:'+str(server.server_port)
        with sync_playwright() as p:
            browser=getattr(p,os.environ.get('BROWSER_ENGINE','webkit')).launch()
            context=browser.new_context(viewport={'width':390,'height':844},has_touch=True)
            context.add_cookies([{'name':c.key,'value':c.value,'url':url} for c in t.client._cookies.values()])
            page=context.new_page()
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            path='/admin/order-design/'+t.order+'?pixel=1'
            started=time.monotonic()
            page.goto(url+path)
            wait(page,"document.querySelector('#pixel-status')?.textContent.includes('正在編輯 V1')")
            print('PIXEL_EDITOR_OPEN_SECONDS',browser.browser_type.name,round(time.monotonic()-started,2),flush=True)
            assert page.evaluate('canvas.getObjects().length')==0
            assert page.evaluate("(canvas.backgroundImage.getElement().height||canvas.backgroundImage.getElement().naturalHeight)<=1200")
            page.locator('#pixel-extract').click()
            x,y=page.evaluate("""() => {
                const point=fabric.util.transformPoint(new fabric.Point(50,70),canvas.viewportTransform);
                const box=canvas.upperCanvasEl.getBoundingClientRect();
                return [box.left+point.x*box.width/canvas.getWidth(),
                        box.top+point.y*box.height/canvas.getHeight()];
            }""")
            page.mouse.click(x,y)
            wait(page,'canvas.getObjects().length===2')
            state=page.evaluate("""() => ({
                count:canvas.getObjects().length,
                parts:canvas.getObjects().filter(o=>o.pixelExtractionBounds).length,
                masks:canvas.getObjects().filter(o=>o.pixelExtractionMask).length,
                bounds:canvas.getObjects().find(o=>o.pixelExtractionBounds)?.pixelExtractionBounds,
                bg:canvas.backgroundImage.getElement().width
            })""")
            assert state['parts']==1 and state['masks']==1,state
            assert state['bounds']==[50,90,231,281],state
            page.evaluate("""() => {
                const obj=canvas.getObjects().find(o=>o.pixelExtractionBounds);
                obj.set({left:180,top:250});
                canvas.fire('object:modified',{target:obj});
                recordHistory();
            }""")
            page.locator('#pixel-save').click()
            wait(page,"document.querySelector('#pixel-status')?.textContent.includes('V2 已保存')")
            assert 'pixel=1' in page.url,page.url
            page.reload()
            wait(page,"document.querySelector('#pixel-status')?.textContent.includes('正在編輯 V2')")
            assert page.evaluate("canvas.getObjects().length===2")
            assert page.evaluate("Math.abs(canvas.getObjects().find(o=>o.pixelExtractionBounds).left-180)<1")
            assert page.evaluate("canvas.getObjects().some(o=>o.pixelExtractionMask)")
            def tap_canvas(left,top):
                x,y=page.evaluate("""([x,y])=>{
                    const point=fabric.util.transformPoint(new fabric.Point(x,y),canvas.viewportTransform);
                    const box=canvas.upperCanvasEl.getBoundingClientRect();
                    return [box.left+point.x*box.width/canvas.getWidth(),box.top+point.y*box.height/canvas.getHeight()];
                }""",[left,top])
                page.touchscreen.tap(x,y)
            page.locator('#pixel-contour').click()
            for point in ((172,222),(244,222),(244,293),(172,293)):
                tap_canvas(*point)
            page.locator('#pixel-contour-undo').click()
            assert '3 點' in page.locator('#pixel-status').inner_text()
            page.locator('#pixel-contour').click()
            assert page.evaluate('canvas.getObjects().length===2')
            page.locator('#pixel-contour').click()
            for point in ((172,222),(244,222),(244,293),(172,293)):
                tap_canvas(*point)
            page.locator('#pixel-contour-done').click()
            wait(page,'canvas.getObjects().length===4')
            page.evaluate('undoCanvas()')
            wait(page,'!restoringHistory && canvas.getObjects().length===2')
            page.evaluate('redoCanvas()')
            wait(page,'!restoringHistory && canvas.getObjects().length===4')
            assert page.evaluate("canvas.getObjects().filter(o=>o.pixelExtractionMask).every(o=>!o.visible&&!o.selectable&&!o.evented)")
            started=time.monotonic()
            page.locator('#pixel-save').click()
            wait(page,"document.querySelector('#pixel-status')?.textContent.includes('V3 已保存')")
            print('PIXEL_EDITOR_SAVE_SECONDS',browser.browser_type.name,round(time.monotonic()-started,2),flush=True)
            page.locator('#pixel-review').click()
            wait(page,"document.querySelector('#pixel-compare')?.textContent.includes('禁止送印')")
            assert page.locator('#pixel-confirm').is_disabled()
            assert page.locator('#pixel-send').is_disabled()
            versions=app.order_designs.rows(t.order)
            v1,v2,v3=[row['document'] for row in versions]
            assert v1['baseSha']==fx.sha(raw)
            assert v3['objects'][0]['src']==v2['objects'][0]['src']
            output=Image.open(io.BytesIO(app.print_center._download_artwork(v3['outputPath'])))
            assert output.size==size and abs(output.info['dpi'][0]-720)<.1
            assert output.getpixel((510,500))==art.getpixel((510,500))
            assert v3['proof']['alphaExpansion'] and v3['profile'] is None
            assert not t.fx.fake.calls
            assert app.commerce.read()==original,'Pixel extraction changed commerce state'
            assert not errors,errors
            context.close()
            browser.close()
        print('Pixel extraction WebKit/Chromium integration OK')
    finally:
        if server:
            server.shutdown()
        t.tearDown()
        t.doCleanups()


if __name__=='__main__':
    run()
