import io
import os
import sys
import threading
import tempfile
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

test_dir = tempfile.TemporaryDirectory()
os.environ['COMMERCE_DB_PATH'] = str(Path(test_dir.name) / 'commerce.sqlite3')
os.environ.pop('SUPABASE_URL', None)
os.environ.pop('SUPABASE_SERVICE_ROLE_KEY', None)
import app as app_module
from admin_perf_patch import install as install_admin_perf
from template_editor_patch import install as install_template_editor
from commerce_patch import install as install_commerce
from print_center import install as install_print_center

install_admin_perf(app_module)
install_template_editor(app_module)
install_commerce(app_module)
install_print_center(app_module)
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


def poll(page, fn, timeout=20000, interval=.1):
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
    page.route('**/api/ai/remove-background', lambda route: route.fulfill(status=200, body=responses.pop(0) if responses else GOOD, content_type='image/png'))
    page.goto(base + '/', wait_until='domcontentloaded')
    poll(page, "() => typeof fabric !== 'undefined' && typeof initCanvas === 'function' && !!window.BenfuwanAiRemoveV2 && !!window.removeBackgroundForActive && !!window.BenfuwanEditorAccess && !!window.BenfuwanOrderPayload")
    # Let the app finish its own initial catalog load/navigation before forcing
    # the editor. Otherwise the startup async task can switch pages after the
    # test has entered the editor and produce a false zero-geometry failure.
    poll(page, "() => typeof shopData !== 'undefined' && Array.isArray(shopData?.models) && shopData.models.length > 0", timeout=10000)
    page.evaluate("""() => {ctx.printW=80;ctx.printH=160;ctx.maskUrl='';navigate('page-editor');initCanvas();editorHasSession=true;window.BenfuwanEditorAccess?.fitCanvas?.();}""")
    add_front_photo(page, 0)
    metrics = poll(page, """() => {
      const pe=document.getElementById('page-editor'),ob=document.getElementById('object-bar'),tb=document.querySelector('#page-editor>.toolbar'),ws=document.querySelector('#page-editor>.workspace'),shell=document.getElementById('canvas-shell'),row=document.querySelector('#page-editor>.bf-editor-action-row');
      if(!pe||!ob||!tb||!ws||!shell||!row||getComputedStyle(pe).display==='none')return false;
      const a=ob.getBoundingClientRect(),b=tb.getBoundingClientRect(),c=ws.getBoundingClientRect(),d=shell.getBoundingClientRect(),r=row.getBoundingClientRect();
      const left=row.querySelector('.editor-float:not(.right)'),right=row.querySelector('.editor-float.right');
      const out={show:ob.classList.contains('show'),objectTop:a.top,objectBottom:a.bottom,toolbarTop:b.top,workspaceBottom:c.bottom,shellBottom:d.bottom,actionTop:r.top,actionBottom:r.bottom,actionHeight:r.height,toolbarVisible:getComputedStyle(tb).visibility,toolbarPointer:getComputedStyle(tb).pointerEvents,position:getComputedStyle(ob).position,leftPosition:left?getComputedStyle(left).position:'',rightPosition:right?getComputedStyle(right).position:'',workspaceHasFloat:!!ws.querySelector('.editor-float')};
      return out.show && out.actionHeight>=44 && a.height>0 && b.height>0 && c.height>0 ? out : false;
    }""", timeout=10000)
    assert metrics['show'] and metrics['toolbarVisible']=='visible' and metrics['toolbarPointer']!='none', metrics
    assert metrics['position'] == 'relative', metrics
    assert metrics['workspaceBottom'] <= metrics['actionTop'] + 2, metrics
    assert metrics['shellBottom'] <= metrics['workspaceBottom'] + 2, metrics
    assert metrics['actionBottom'] <= metrics['objectTop'] + 2, metrics
    assert 44 <= metrics['actionHeight'] <= 56, metrics
    assert metrics['leftPosition'] == 'relative' and metrics['rightPosition'] == 'relative', metrics
    assert not metrics['workspaceHasFloat'], metrics
    assert metrics['objectBottom'] <= metrics['toolbarTop'] + 8, metrics
    print('FRONT_ACTION_ROW_OK', metrics['actionTop'], metrics['actionBottom'])

    payload = page.evaluate("""() => {
      const huge={background:'#fff',objects:[{type:'image',role:'photo',left:120,top:240,angle:8,src:'data:image/png;base64,'+'A'.repeat(2200000),originalName:'huge.png'}]};
      const compact=window.BenfuwanOrderPayload.compactDesign(huge),txt=JSON.stringify(compact);
      return {raw:JSON.stringify(huge).length,compact:txt.length,embedded:txt.includes('data:image'),role:compact.objects?.[0]?.role,left:compact.objects?.[0]?.left};
    }""")
    assert payload['raw'] > 2_000_000 and payload['compact'] < 1_500_000 and not payload['embedded'], payload
    assert payload['role'] == 'photo' and payload['left'] == 120, payload
    print('FRONT_ORDER_PAYLOAD_OK', payload['raw'], payload['compact'])

    assert page.evaluate("""() => {const tb=document.querySelector('#page-editor>.toolbar');const b=[...tb.querySelectorAll('button')].find(x=>/openSheet|openTemplates|layer|sticker/i.test(x.getAttribute('onclick')||''))||tb.querySelector('button');b.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));return !canvas.getActiveObject();}"""), 'main toolbar did not release selection'
    page.evaluate("""() => {const o=canvas.getObjects().find(x=>x.role==='photo');canvas.setActiveObject(o);canvas.requestRenderAll();syncSelection();}""")
    page.evaluate("() => window.removeBackgroundForActive()")
    good = page.evaluate("""() => {const o=canvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved,role:o?.role,outline:String(o?.aiOutlineSource||'').startsWith('data:image/'),count:canvas.getObjects().filter(x=>x.role==='photo').length};}""")
    assert good == {'ai':True,'role':'photo','outline':True,'count':1}, good
    add_front_photo(page, 1)
    page.evaluate("() => window.removeBackgroundForActive()")
    bad = page.evaluate("""() => {const o=canvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved,name:o?.originalName,count:canvas.getObjects().filter(x=>x.role==='photo').length};}""")
    assert bad['ai'] is False and bad['name']=='test-1.png' and bad['count']==2, bad
    print('FRONT_WEBKIT_OK')
    page.close()


def checkout_test(browser, base):
    page = browser.new_page()
    sent = []
    def intercept(route):
        sent.append(route.request.post_data_json)
        if len(sent) == 1:
            # Server commits, browser receives a simulated transport failure.
            result = route.fetch()
            assert result.status == 200, result.text()
            route.abort('failed')
        else:
            route.continue_()
    page.route('**/api/create_order', intercept)
    page.goto(base + '/', wait_until='domcontentloaded')
    poll(page, "() => !!window.BenfuwanOrderPayload && typeof shopData !== 'undefined' && shopData.models?.length")
    page.evaluate("""async () => {
      const c=document.createElement('canvas');c.width=2;c.height=2;
      cartItem={modelId:shopData.models[0].id,styleId:shopData.styles[0].id,modelName:shopData.models[0].name,styleName:shopData.styles[0].name,colorName:'透明',quantity:1,payment:'現金',printBase64:c.toDataURL(),designJson:{}};
      await idbSet('cart',cartItem);document.getElementById('form-surname').value='測試';await submitOrder();
    }""")
    assert len(sent) == 1 and sent[0]['idempotency_key']
    page.reload(wait_until='domcontentloaded')
    poll(page, "() => !!window.BenfuwanOrderPayload && typeof shopData !== 'undefined' && shopData.models?.length")
    page.evaluate("async () => {document.getElementById('form-surname').value='測試';await submitOrder()}")
    assert len(sent) == 2 and sent[0] == sent[1], sent
    assert page.evaluate("() => !!document.getElementById('success-id').textContent")
    assert page.evaluate("() => idbGet('cart')") is None
    print('CHECKOUT_LOST_RESPONSE_RELOAD_OK')
    page.close()


def admin_test(browser, base):
    page = browser.new_page(viewport={'width': 1180, 'height': 900})
    page.on('console', lambda msg: print('ADMIN_CONSOLE', msg.type, msg.text))
    page.on('pageerror', lambda exc: print('ADMIN_PAGEERROR', str(exc)))
    page.route('**/api/ai/remove-background', lambda route: route.fulfill(status=200, body=GOOD, content_type='image/png'))
    page.goto(base + '/login', wait_until='domcontentloaded')
    page.locator('input[name="password"]').fill('fan123')
    submit = page.locator('button[type="submit"],input[type="submit"]').first
    if submit.count(): submit.click()
    else: page.locator('form').evaluate('(f)=>f.submit()')
    page.wait_for_url('**/admin')

    # POS UI is injected only for authenticated admin and must coexist with the
    # existing order/template editor without leaking private data publicly.
    poll(page, "() => !!window.BenfuwanCommerce && !!document.querySelector('.nav button[data-view=\"commerce\"]')")
    page.locator('.nav button[data-view="commerce"]').click()
    poll(page, "() => document.getElementById('view-commerce')?.classList.contains('active') && document.querySelectorAll('#commerce-summary .commerce-kpi').length===4")
    commerce_diag = page.evaluate("""() => ({version:window.BenfuwanCommerce?.version||'',publicCostLeak:JSON.stringify(shopData||{}).includes('cost_price'),view:document.getElementById('view-commerce')?.classList.contains('active')})""")
    assert commerce_diag['version'].startswith('2.0') and commerce_diag['view'] and not commerce_diag['publicCostLeak'], commerce_diag
    print('ADMIN_COMMERCE_WEBKIT_OK', commerce_diag['version'])
    page.locator('[data-tab="stock"]').click()

    # Real Phase 2 controls, including a committed receipt with lost response.
    assert page.request.post(base + '/api/admin/commerce_sync_skus', data={}).ok
    data = page.request.get(base + '/api/admin/commerce_data').json()['data']
    sku = data['skus'][0]
    sku.update(stock_qty=1, cost_price=100, low_stock_threshold=2, target_stock=8, track_stock=True)
    assert page.request.post(base + '/api/admin/save_commerce_data', data=data).ok
    page.locator('#commerce-reload').click()
    poll(page, "() => window.BenfuwanCommerce.state.skus[0]?.target_stock===8")
    card = page.locator('[data-sku="' + sku['id'] + '"]')
    card.locator('[data-field="target_stock"]').fill('10')
    page.locator('#commerce-save').click()
    poll(page, "() => document.getElementById('pos-message').textContent==='商品設定已儲存'")
    page.locator('[data-tab="restock"]').click()
    assert page.locator('#commerce-low-only').is_checked()
    assert card.is_visible()
    page.locator('#pos-list').click()
    page.locator('#pos-export-text').wait_for(state='visible')
    assert '建議 9 件' in page.locator('#pos-export-text').input_value()
    page.locator('#pos-close').click()
    receipts = []
    def receive(route):
        receipts.append(route.request.post_data_json)
        if len(receipts) == 1:
            assert route.fetch().status == 200
            route.abort('failed')
        else:
            route.continue_()
    page.route('**/api/admin/purchase_received', receive)
    card.locator('[data-receive]').click()
    page.locator('#pos-receive-qty').fill('3')
    page.locator('#pos-dialog-submit').click()
    poll(page, "() => document.getElementById('pos-message').classList.contains('error')")
    page.reload(wait_until='domcontentloaded')
    page.locator('.nav button[data-view="commerce"]').click()
    page.locator('#pos-retry').click()
    poll(page, "() => !localStorage.getItem('bf-pos2-pending') && window.BenfuwanCommerce.state.skus[0]?.stock_qty===4")
    assert len(receipts) == 2 and receipts[0] == receipts[1], receipts
    page.locator('[data-tab="expenses"]').click()
    page.locator('#pos-expense-category').select_option('廣告')
    page.locator('#pos-expense-amount').fill('20.25')
    page.locator('#pos-expense-note').fill('瀏覽器測試支出')
    page.locator('#pos-expense-save').click()
    page.locator('.pos-expense').filter(has_text='瀏覽器測試支出').wait_for()
    for width, height in ((390,844),(1024,768),(1440,900)):
        page.set_viewport_size(dict(width=width,height=height))
        for tab in ('stock','restock','reports','expenses'):
            page.locator('[data-tab="'+tab+'"]').click()
            if tab == 'reports':
                poll(page, "() => document.querySelectorAll('#pos-metrics .pos-metric').length===9")
            metrics = page.evaluate("""() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,view:document.getElementById('view-commerce').getBoundingClientRect().width})""")
            assert metrics['scroll'] <= width + 2 and metrics['view'] > 200, (tab,metrics)
            if os.environ.get('POS_SCREENSHOT_DIR'):
                folder = Path(os.environ['POS_SCREENSHOT_DIR']);folder.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(folder / f'pos-{width}-{tab}.png'), full_page=True)
    page.locator('[data-tab="reports"]').click()
    for period in ('week','month','year','custom'):
        page.locator('#pos-period').select_option(period)
        page.locator('#pos-report-form button').click()
        poll(page, "() => document.querySelectorAll('#pos-metrics .pos-metric').length===9 && document.getElementById('pos-metrics').getAttribute('aria-busy')===null")
    print('POS_PHASE2_RESPONSIVE_RECEIPT_EXPENSE_REPORT_OK')

    print_nav = page.locator('.nav button[data-view="print-center"]')
    print_nav.click()
    poll(page, "() => document.querySelectorAll('#pc-grid .pc-card').length>0 && document.getElementById('view-print-center').classList.contains('active')")
    assert page.locator('#pc-config').get_attribute('class').find('warn') >= 0
    assert page.locator('[data-pc="start"]').count() == 0
    for width, height in ((390,844),(768,1024),(1440,900)):
        page.set_viewport_size(dict(width=width,height=height))
        metrics = page.evaluate("""() => ({
          width:innerWidth,scroll:document.documentElement.scrollWidth,
          view:document.getElementById('view-print-center').getBoundingClientRect().width,
          cards:document.querySelectorAll('#pc-grid .pc-card').length,
          secrets:document.getElementById('view-print-center').textContent.includes('fake-key')
        })""")
        assert metrics['scroll'] <= width + 2 and metrics['view'] > 200 and metrics['cards'] > 0 and not metrics['secrets'], metrics
    profile_button = page.locator('[data-pc="profile"]').first
    profile_button.click()
    page.locator('#pc-modal.show').wait_for()
    modal_text = page.locator('#pc-modal').inner_text()
    assert 'A5 有效範圍：200 × 230 mm' in modal_text
    assert '座標原點：治具右下角' in modal_text
    assert 'Channel 固定為 1' in modal_text
    page.locator('#pc-close').click()
    legacy_order = app_module.commerce.store.local_orders()[0]
    commerce = app_module.commerce.read()
    assert commerce['order_finance'].pop(legacy_order['id'], None), legacy_order['id']
    assert app_module.commerce.store.commit(int(commerce.get('revision', 0)), commerce)
    page.locator('#pc-reload').click()
    poll(page, "() => document.querySelector('[data-pc=\"binding\"]') !== null")
    page.locator('[data-pc="binding"]').first.click()
    page.locator('#pc-bind-modal.show').wait_for()
    assert '不會修改營收／成本／庫存資料' in page.locator('#pc-bind-modal').inner_text()
    assert page.locator('#pc-bind-sku option').count() >= 2
    page.locator('#pc-bind-close').click()
    print('PRINT_CENTER_A5_RESPONSIVE_FAIL_CLOSED_OK')

    template_nav = page.locator('.nav button[data-view="templates"]')
    template_nav.click()
    poll(page, "() => typeof window.benfuwanEnsureTemplateEditor === 'function' && typeof shopLoaded !== 'undefined' && shopLoaded && typeof templatesLoaded !== 'undefined' && templatesLoaded")
    page.evaluate("() => window.benfuwanEnsureTemplateEditor()")
    diag = page.evaluate("""() => ({core:!!window.BenfuwanAiRemoveV2,admin:typeof window.bfAdminRemoveBackground,stackReady:!!window.__benfuwanTemplateStackReady,adminFlag:!!window.__bfAdminAiRemoveOnlyV2,models:(shopData?.models||[]).length})""")
    print('ADMIN_STACK_DIAG', diag)
    assert diag['core'] and diag['admin']=='function' and diag['stackReady'] and diag['adminFlag'] and diag['models'] > 0, diag

    page.locator('#view-templates .titlebar .btn').click()
    poll(page, "() => document.getElementById('template-modal')?.classList.contains('show') && typeof window.fabric !== 'undefined' && typeof visualCanvas !== 'undefined' && !!visualCanvas", timeout=30000)
    print('ADMIN_FABRIC_LAZY_OK')

    page.evaluate("""() => new Promise((resolve,reject)=>{const c=document.createElement('canvas');c.width=128;c.height=128;const g=c.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,128,128);g.fillStyle='#d94d75';g.fillRect(24,16,80,96);fabric.Image.fromURL(c.toDataURL('image/png'),img=>{try{img.set({left:tplW/2,top:tplH/2,originX:'center',originY:'center',scaleX:.8,scaleY:1.1,angle:13,originalName:'admin-test.png'});visualCanvas.add(img);visualCanvas.setActiveObject(img);visualCanvas.requestRenderAll();resolve()}catch(e){reject(e)}});})""")
    before = page.evaluate("""() => {const o=visualCanvas.getActiveObject();return {w:o.getScaledWidth(),h:o.getScaledHeight(),x:o.getCenterPoint().x,y:o.getCenterPoint().y,a:o.angle};}""")
    page.evaluate("() => window.bfAdminRemoveBackground()")
    after = page.evaluate("""() => {const o=visualCanvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved,w:o?.getScaledWidth(),h:o?.getScaledHeight(),x:o?.getCenterPoint().x,y:o?.getCenterPoint().y,a:o?.angle,publicSrc:o?.publicSrc||''};}""")
    assert after['ai'] is True, after
    for k in ('w','h','x','y','a'):
        assert abs(after[k]-before[k]) < .75, (k,before,after)
    assert after['publicSrc'], after
    print('ADMIN_WEBKIT_OK')
    page.close()


def durable_receipt_test(playwright, base):
    """Persist the real committed request across tab close AND browser restart."""
    engine = getattr(playwright, os.environ.get('BROWSER_ENGINE', 'webkit'))
    def admin(context):
        page = context.new_page()
        page.goto(base + '/login', wait_until='domcontentloaded')
        if '/admin' not in page.url:
            page.locator('input[name="password"]').fill('fan123')
            page.locator('button[type="submit"],input[type="submit"]').first.click()
            page.wait_for_url('**/admin')
        poll(page, "() => !!window.BenfuwanCommerce")
        page.locator('.nav button[data-view="commerce"]').click()
        poll(page, "() => window.BenfuwanCommerce.state.skus.length>0")
        page.locator('[data-tab="stock"]').click()
        return page
    with tempfile.TemporaryDirectory() as profile:
        for kind in ('purchase', 'expense'):
            context = engine.launch_persistent_context(profile, headless=True)
            try:
                page = admin(context)
                before = app_module.commerce.read()
                sku = before['skus'][0]
                url = '/api/admin/purchase_received' if kind == 'purchase' else '/api/admin/expense'
                sent = []
                def lose_response(route):
                    sent.append(route.request.post_data_json)
                    assert route.fetch().status == 200
                    route.abort('failed')
                context.route('**' + url, lose_response)
                if kind == 'purchase':
                    page.locator('[data-sku="'+sku['id']+'"] [data-receive]').click()
                    page.locator('#pos-receive-qty').fill('3')
                    page.locator('#pos-dialog-submit').click()
                else:
                    page.locator('[data-tab="expenses"]').click()
                    page.locator('#pos-expense-amount').fill('37.5')
                    page.locator('#pos-expense-note').fill('durable restart receipt')
                    page.locator('#pos-expense-save').click()
                poll(page, "() => document.getElementById('pos-message').classList.contains('error')")
                saved = page.evaluate("() => JSON.parse(localStorage.getItem('bf-pos2-pending'))")
                assert saved['body'] == sent[0]
                # Existing/new tabs see the same receipt and cannot replace it.
                other = admin(context)
                assert other.locator('#pos-pending').is_visible()
                other.locator('[data-tab="expenses"]').click()
                other.locator('#pos-expense-amount').fill('999')
                other.locator('#pos-expense-save').click()
                poll(other, "() => document.getElementById('pos-message').textContent.includes('未送出')")
                assert other.evaluate("() => JSON.parse(localStorage.getItem('bf-pos2-pending'))") == saved
                page.close()
                other.close()
            finally:
                context.close()  # exits browser; retain only the on-disk profile
            context = engine.launch_persistent_context(profile, headless=True)
            try:
                page = admin(context)
                assert page.locator('#pos-pending').is_visible()
                assert page.evaluate("() => JSON.parse(localStorage.getItem('bf-pos2-pending'))") == saved
                # Expired authentication must not discard an uncertain receipt.
                context.route('**'+url, lambda route: route.fulfill(status=401,content_type='application/json',body='{"status":"error","msg":"login required"}'))
                page.locator('#pos-retry').click()
                poll(page, "() => document.getElementById('pos-message').textContent==='login required'")
                assert page.evaluate("() => JSON.parse(localStorage.getItem('bf-pos2-pending'))") == saved
                context.unroute('**'+url)
                def retry(route):
                    sent.append(route.request.post_data_json)
                    route.continue_()
                context.route('**'+url, retry)
                observer = admin(context)
                assert observer.locator('#pos-pending').is_visible()
                page.locator('#pos-retry').click()
                poll(page, "() => !localStorage.getItem('bf-pos2-pending')")
                poll(observer, "() => document.getElementById('pos-pending').hidden")
                assert len(sent) == 2 and sent[0] == sent[1], sent
                after = app_module.commerce.read()
                if kind == 'purchase':
                    assert after['skus'][0]['stock_qty'] == sku['stock_qty'] + 3
                    entries = [x for x in after['inventory_ledger'] if x.get('receipt_id') == saved['body']['idempotency_key']]
                    assert len(entries) == 1
                else:
                    assert len(after['expenses']) == len(before['expenses']) + 1
                    entries = [x for x in after['expense_ledger'] if x['id'] == saved['body']['idempotency_key']]
                    assert len(entries) == 1
                print('DURABLE_RECEIPT_BROWSER_RESTART_OK', kind)
            finally:
                context.close()


def main():
    server = ServerThread();server.start();time.sleep(.8)
    try:
        with sync_playwright() as p:
            browser = getattr(p, os.environ.get('BROWSER_ENGINE', 'webkit')).launch()
            try:
                base='http://127.0.0.1:8765';front_test(browser,base);checkout_test(browser,base);admin_test(browser,base)
                import runpy
                runpy.run_path(str(ROOT / '.github/tests/test_pos_dashboard.py'))['dashboard_test'](browser,base,poll)
            finally: browser.close()
            durable_receipt_test(p, base)
        print('AI_EDITOR_WEBKIT_OK')
    finally:
        server.close()
        # The commerce test runs in local fallback mode; keep CI workspaces clean.
        commerce = ROOT / 'commerce_data.json'
        if commerce.exists():
            try: commerce.unlink()
            except Exception: pass


if __name__ == '__main__': main()
