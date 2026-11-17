"""Existing storefront tools, isolated native PNGs and fake vendor only."""
import os,sys,io,threading,time,copy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));os.chdir(ROOT)
from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_pixel_orders as fixtures
from test_order_design_browser import wait

def run():
    with sync_playwright() as p:
        browser=getattr(p,os.environ.get('BROWSER_ENGINE','webkit')).launch()
        for size in ((2030,4241),(1165,615)):
            fx=fixtures.PixelTests();fx.setUp();app=fixtures.app
            order=app.commerce.store.order(fx.order);raw=fixtures.picture(size)
            Path(app.SAVE_DIR,order['print_path']).write_bytes(raw)
            with app.print_center.store.connection(True) as db:
                db.execute('UPDATE print_jobs SET artwork_sha256=?,width_mm=?,height_mm=? WHERE id=?',(fixtures.sha(raw),size[0]*25.4/720,size[1]*25.4/720,fx.source['id']))
            original_job=app.print_center.store.job(fx.source['id']);finance=copy.deepcopy(app.commerce.read())
            server=make_server('127.0.0.1',0,app.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_port)
            def context(width):
                c=browser.new_context(viewport={'width':width,'height':844},has_touch=width==390)
                c.add_cookies([{'name':k.key,'value':k.value,'url':base} for k in fx.client._cookies.values()]);return c
            try:
                c=context(390);page=c.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('response',lambda r:print('HTTP_ERROR',r.url,r.text()[:500],flush=True) if r.status>=400 and '/pixel/' in r.url else None)
                page.goto(base+'/admin/order-design/'+fx.order+'?pixel=1');wait(page,"document.querySelector('#pixel-status')?.textContent.includes('正在編輯 V1')")
                assert page.evaluate('canvas.getObjects().length')==0
                assert page.evaluate('canvas.backgroundImage.selectable===false')
                # Actual existing text and image tools remain available; original is never an object.
                page.evaluate("()=>{canvas.add(new fabric.Textbox('修補',{left:20,top:40,width:100,fontSize:16,fontFamily:'jf-openhuninn'}));recordHistory()}")
                page.evaluate("""async url=>{for(const role of ['photo','sticker'])await new Promise(ok=>fabric.Image.fromURL(url,o=>{o.set({left:110,top:30,width:30,height:30,role});canvas.add(o);ok()}));recordHistory();}""",fixtures.data(fixtures.picture((30,30))))
                page.get_by_role('button',name='新增局部遮蓋',exact=True).click()
                page.get_by_role('button',name='新增擦除區（可移動／縮放）',exact=True).click()
                page.evaluate("()=>{const o=canvas.getObjects().find(o=>o.pixelErase);o.set({left:80,top:80,width:20,height:20});canvas.fire('object:modified',{target:o});}")
                page.locator('#pixel-save').click();wait(page,"document.querySelector('#pixel-status').textContent.includes('V2 已保存')",60000)
                versions=app.order_designs.rows(fx.order);d=versions[-1]['document']
                out=Image.open(io.BytesIO(fixtures.app.print_center._download_artwork(d['outputPath'])))
                before=Image.open(io.BytesIO(raw));assert out.size==size and abs(out.info['dpi'][0]-720)<.1
                box=d['proof']['bounds'];assert box
                # Entire unedited lower half must be identical, including all RGBA channels.
                assert out.crop((0,int(size[1]*.8),size[0],size[1])).tobytes()==before.crop((0,int(size[1]*.8),size[0],size[1])).tobytes()
                c.close();c=context(1280);page=c.new_page();page.goto(base+'/admin/order-design/'+fx.order+'?pixel=1')
                wait(page,"document.querySelector('#pixel-status')?.textContent.includes('正在編輯 V2')")
                assert page.evaluate('canvas.getObjects().length')==5
                page.locator('#pixel-review').click();page.locator('#pixel-reason').fill('隔離像素修補測試');page.locator('#pixel-cost').fill('12.50')
                page.locator('#pixel-confirm').click();wait(page,"document.querySelector('#pixel-send')?.disabled===false")
                assert fx.fx.fake.calls==[]
                fx.fx.fake.responses['/api/Device/receiveTask']={'code':0,'data':{'taskid':'pixel-browser-'+str(size[0]),'status':0}}
                page.on('dialog',lambda d:d.accept());page.locator('#pixel-send').click();wait(page,"document.querySelector('#pixel-compare').textContent.includes('QUEUED')")
                assert len(fx.fx.fake.calls)==1
                assert app.commerce.store.order(fx.order)==order and app.commerce.read()==finance
                assert app.print_center.store.job(fx.source['id'])==original_job
                assert not errors,errors
                evidence=ROOT/'__pycache__'/'pixel-evidence';evidence.mkdir(exist_ok=True)
                page.screenshot(path=str(evidence/(browser.browser_type.name+'-'+str(size[0])+'.png')))
                c.close();print('PIXEL_REPAIR_NATIVE_RGBA_V2_COMPARE_REPRINT_OK',browser.browser_type.name,size,flush=True)
            finally:server.shutdown();server.server_close();fx.doCleanups()
        browser.close()

if __name__=='__main__':run()
