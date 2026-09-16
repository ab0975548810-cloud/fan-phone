import io
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

os.environ.setdefault('ADMIN_PASSWORD', 'fan123')
os.environ['SESSION_COOKIE_SECURE'] = 'false'
os.environ['PORT'] = '8765'

import app as app_module
from admin_perf_patch import install as install_admin_perf
from template_editor_patch import install as install_template_editor

install_admin_perf(app_module)
install_template_editor(app_module)
app_module.app.config['SESSION_COOKIE_SECURE'] = False


def png_bytes(transparent=True):
    bg = (0, 0, 0, 0) if transparent else (255, 255, 255, 255)
    im = Image.new('RGBA', (128, 128), bg)
    d = ImageDraw.Draw(im)
    d.ellipse((25, 18, 103, 110), fill=(240, 80, 120, 255))
    buf = io.BytesIO(); im.save(buf, format='PNG')
    return buf.getvalue()


GOOD = png_bytes(True)
BAD = png_bytes(False)


class ServerThread(threading.Thread):
    daemon = True
    def __init__(self):
        super().__init__()
        self.server = make_server('127.0.0.1', 8765, app_module.app, threaded=True)
    def run(self): self.server.serve_forever()
    def close(self): self.server.shutdown()


def poll(page, fn, timeout=15000, interval=.1):
    end = time.time() + timeout / 1000
    last = None
    while time.time() < end:
        try:
            last = page.evaluate(fn)
            if last: return last
        except Exception:
            pass
        time.sleep(interval)
    raise AssertionError(f'poll timeout; last={last!r}')


def add_front_photo(page, variant=0):
    page.evaluate(f'''() => new Promise((resolve,reject)=>{{
      const c=document.createElement('canvas');c.width=128;c.height=128;const g=c.getContext('2d');
      g.fillStyle='{ '#fff6fa' if variant == 0 else '#e8f4ff' }';g.fillRect(0,0,128,128);
      g.fillStyle='{ '#e05280' if variant == 0 else '#356edb' }';g.fillRect(28,20,72,90);
      fabric.Image.fromURL(c.toDataURL('image/png'),img=>{{
        try{{img.set({{left:canvas.width/2,top:canvas.height/2,originX:'center',originY:'center',role:'photo',originalName:'test-{variant}.png'}});styleEditableObject(img);canvas.add(img);canvas.setActiveObject(img);canvas.requestRenderAll();syncSelection();resolve();}}catch(e){{reject(e)}}
      }});
    }})''')


def front_test(browser, base):
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    responses = [GOOD, BAD]
    def route_ai(route):
        body = responses.pop(0) if responses else GOOD
        route.fulfill(status=200, body=body, content_type='image/png')
    page.route('**/api/ai/remove-background', route_ai)
    page.goto(base + '/', wait_until='domcontentloaded')
    poll(page, "() => typeof fabric !== 'undefined' && typeof initCanvas === 'function' && !!window.BenfuwanAiRemoveV2 && !!window.removeBackgroundForActive")
    page.evaluate("""() => {ctx.printW=80;ctx.printH=160;ctx.maskUrl='';navigate('page-editor');initCanvas();editorHasSession=true;}""")
    add_front_photo(page, 0)

    metrics = page.evaluate("""() => {
      const ob=document.getElementById('object-bar'),tb=document.querySelector('#page-editor>.toolbar');
      const a=ob.getBoundingClientRect(),b=tb.getBoundingClientRect();
      return {show:ob.classList.contains('show'), objectBottom:a.bottom, toolbarTop:b.top, toolbarVisible:getComputedStyle(tb).visibility, toolbarPointer:getComputedStyle(tb).pointerEvents};
    }""")
    assert metrics['show'], metrics
    assert metrics['toolbarVisible'] == 'visible' and metrics['toolbarPointer'] != 'none', metrics
    assert metrics['objectBottom'] <= metrics['toolbarTop'] + 2, metrics

    cleared = page.evaluate("""() => {
      const tb=document.querySelector('#page-editor>.toolbar');
      const b=[...tb.querySelectorAll('button')].find(x=>/openSheet|openTemplates|layer|sticker/i.test(x.getAttribute('onclick')||'')) || tb.querySelector('button');
      if(!b)throw new Error('main toolbar has no button');
      b.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));
      return !canvas.getActiveObject();
    }""")
    assert cleared, 'main toolbar click did not release object selection'

    # Re-select the same photo: no background tap is needed and no extra object is introduced.
    page.evaluate("""() => {const o=canvas.getObjects().find(x=>x.role==='photo');canvas.setActiveObject(o);canvas.requestRenderAll();syncSelection();}""")
    page.evaluate("() => window.removeBackgroundForActive()")
    good = page.evaluate("""() => {const o=canvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved, role:o?.role, outline:String(o?.aiOutlineSource||'').startsWith('data:image/'), count:canvas.getObjects().filter(x=>x.role==='photo').length};}""")
    assert good == {'ai': True, 'role': 'photo', 'outline': True, 'count': 1}, good

    add_front_photo(page, 1)
    page.evaluate("() => window.removeBackgroundForActive()")
    bad = page.evaluate("""() => {const o=canvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved,name:o?.originalName,count:canvas.getObjects().filter(x=>x.role==='photo').length};}""")
    assert bad['ai'] is False and bad['name'] == 'test-1.png' and bad['count'] == 2, bad
    page.close()


def admin_test(browser, base):
    page = browser.new_page(viewport={'width': 1180, 'height': 900})
    page.route('**/api/ai/remove-background', lambda route: route.fulfill(status=200, body=GOOD, content_type='image/png'))
    page.goto(base + '/login', wait_until='domcontentloaded')
    page.locator('input[name="password"]').fill('fan123')
    submit = page.locator('button[type="submit"],input[type="submit"]').first
    if submit.count(): submit.click()
    else: page.locator('form').evaluate('(f)=>f.submit()')
    page.wait_for_url('**/admin')
    poll(page, "() => typeof window.benfuwanEnsureTemplateEditor === 'function'")
    page.evaluate("() => window.benfuwanEnsureTemplateEditor()")
    poll(page, "() => !!window.BenfuwanAiRemoveV2 && typeof window.bfAdminRemoveBackground === 'function' && typeof fabric !== 'undefined'")
    page.evaluate("() => window.openTemplateEditor()")
    poll(page, "() => typeof visualCanvas !== 'undefined' && !!visualCanvas")

    page.evaluate("""() => new Promise((resolve,reject)=>{
      const c=document.createElement('canvas');c.width=128;c.height=128;const g=c.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,128,128);g.fillStyle='#d94d75';g.fillRect(24,16,80,96);
      fabric.Image.fromURL(c.toDataURL('image/png'),img=>{try{img.set({left:tplW/2,top:tplH/2,originX:'center',originY:'center',scaleX:.8,scaleY:1.1,angle:13,originalName:'admin-test.png'});visualCanvas.add(img);visualCanvas.setActiveObject(img);visualCanvas.requestRenderAll();resolve()}catch(e){reject(e)}});
    })""")
    before = page.evaluate("""() => {const o=visualCanvas.getActiveObject();return {w:o.getScaledWidth(),h:o.getScaledHeight(),x:o.getCenterPoint().x,y:o.getCenterPoint().y,a:o.angle};}""")
    page.evaluate("() => window.bfAdminRemoveBackground()")
    after = page.evaluate("""() => {const o=visualCanvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved,w:o?.getScaledWidth(),h:o?.getScaledHeight(),x:o?.getCenterPoint().x,y:o?.getCenterPoint().y,a:o?.angle,publicSrc:o?.publicSrc||''};}""")
    assert after['ai'] is True, after
    for k in ('w','h','x','y','a'):
        assert abs(after[k]-before[k]) < .75, (k,before,after)
    assert after['publicSrc'], after
    page.close()


def main():
    server = ServerThread();server.start();time.sleep(.8)
    try:
        with sync_playwright() as p:
            browser = p.webkit.launch()
            try:
                base='http://127.0.0.1:8765'
                front_test(browser,base)
                admin_test(browser,base)
            finally:
                browser.close()
        print('AI_EDITOR_WEBKIT_OK')
    finally:
        server.close()


if __name__ == '__main__': main()
