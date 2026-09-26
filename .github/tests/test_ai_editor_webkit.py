import io
import json
import os
import sys
import copy
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

test_dir = ROOT / '__pycache__' / f'webkit-test-{os.getpid()}'
test_dir.mkdir(parents=True, exist_ok=True)
os.environ['COMMERCE_DB_PATH'] = str(test_dir / 'commerce.sqlite3')
os.environ['ADMIN_PASSKEYS_FILE'] = str(test_dir / 'admin_passkeys.json')
os.environ['WEBAUTHN_RP_ID'] = '127.0.0.1'
os.environ['WEBAUTHN_ORIGIN'] = 'http://127.0.0.1:8765'
os.environ.pop('SUPABASE_URL', None)
os.environ.pop('SUPABASE_SERVICE_ROLE_KEY', None)
import app as app_module
from passkey_auth import install as install_passkey_auth
from security_perf import install as install_security
from supabase_resilience import install as install_supabase_resilience
from quality_perf_patch import install as install_quality_perf
from ai_runtime_patch import install as install_ai_runtime
from admin_perf_patch import install as install_admin_perf
from order_color_patch import install as install_order_colors
from asset_category_patch import install as install_asset_categories
from template_editor_patch import install as install_template_editor
from order_management_patch import install as install_order_management
from commerce_patch import install as install_commerce
from print_center import install as install_print_center

install_passkey_auth(app_module)
install_security(app_module)
install_supabase_resilience(app_module)
install_quality_perf(app_module)
install_ai_runtime(app_module)
install_admin_perf(app_module)
install_order_colors(app_module)
install_asset_categories(app_module)
install_template_editor(app_module)
install_order_management(app_module)
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


def assert_front_editor_geometry(page, label):
    metrics = poll(page, """() => {
      if(typeof canvas==='undefined'||!canvas?.wrapperEl||!canvas?.lowerCanvasEl)return false;
      const shell=document.getElementById('canvas-shell'),mask=document.getElementById('phone-mask');
      if(!shell||!mask||getComputedStyle(mask).display==='none')return false;
      const rect=el=>{const r=el.getBoundingClientRect();return {left:r.left,top:r.top,width:r.width,height:r.height}};
      const out={
        logical:{width:canvas.width,height:canvas.height,lowerWidth:canvas.lowerCanvasEl.width,lowerHeight:canvas.lowerCanvasEl.height},
        shell:rect(shell),wrapper:rect(canvas.wrapperEl),lower:rect(canvas.lowerCanvasEl),mask:rect(mask),
        inlineTransform:canvas.wrapperEl.style.transform,computedTransform:getComputedStyle(canvas.wrapperEl).transform
      };
      const lowerRect=canvas.lowerCanvasEl.getBoundingClientRect();
      const pointer=canvas.getPointer({clientX:lowerRect.left+lowerRect.width/2,clientY:lowerRect.top+lowerRect.height/2});
      out.centerPointer={x:pointer.x,y:pointer.y};
      return out.shell.width>0&&out.shell.height>0 ? out : false;
    }""")
    shell = metrics['shell']
    for name in ('wrapper', 'lower', 'mask'):
        rect = metrics[name]
        for key in ('left', 'top', 'width', 'height'):
            assert abs(rect[key] - shell[key]) <= 1, (label, name, key, metrics)
    assert metrics['inlineTransform'] in ('', 'none'), (label, metrics)
    assert metrics['computedTransform'] == 'none', (label, metrics)
    assert metrics['logical'] == {'width':240,'height':480,'lowerWidth':240,'lowerHeight':480}, (label, metrics)
    assert abs(metrics['centerPointer']['x'] - 120) <= 1 and abs(metrics['centerPointer']['y'] - 240) <= 1, (label, metrics)
    print('FRONT_EDITOR_DISPLAY_GEOMETRY_OK', label, round(shell['width'], 2), round(shell['height'], 2))
    return metrics


def front_test(browser, base):
    # Start with a constrained iPhone viewport so initCanvas installs a
    # transform below 1, then exercise the responsive owner's cssOnly fit.
    page = browser.new_page(viewport={'width': 390, 'height': 600})
    responses = [GOOD, BAD]
    page.route('**/api/ai/remove-background', lambda route: route.fulfill(status=200, body=responses.pop(0) if responses else GOOD, content_type='image/png'))
    page.goto(base + '/', wait_until='domcontentloaded')
    poll(page, "() => typeof fabric !== 'undefined' && typeof initCanvas === 'function' && !!window.BenfuwanAiRemoveV2 && !!window.removeBackgroundForActive && !!window.BenfuwanEditorAccess && !!window.BenfuwanOrderPayload")
    # Let the app finish its own initial catalog load/navigation before forcing
    # the editor. Otherwise the startup async task can switch pages after the
    # test has entered the editor and produce a false zero-geometry failure.
    poll(page, "() => typeof shopData !== 'undefined' && Array.isArray(shopData?.models) && shopData.models.length > 0", timeout=10000)
    page.evaluate("""() => {
      const m=document.createElement('canvas');m.width=8;m.height=16;
      const g=m.getContext('2d');g.clearRect(0,0,8,16);g.fillStyle='#fff';g.fillRect(1,1,6,14);
      ctx.printW=80;ctx.printH=160;ctx.maskUrl=m.toDataURL('image/png');ctx.printLineUrl=ctx.maskUrl;
      navigate('page-editor');initCanvas();editorHasSession=true;window.BenfuwanEditorAccess?.fitCanvas?.();
    }""")
    assert_front_editor_geometry(page, 'iphone-constrained-unselected')
    add_front_photo(page, 0)
    page.evaluate("() => window.BenfuwanEditorAccess.fitCanvas()")
    assert_front_editor_geometry(page, 'iphone-constrained-selected')
    page.evaluate("""() => {
      const o=canvas.getActiveObject();o.set({angle:27,scaleX:.82,scaleY:.82});o.setCoords();canvas.requestRenderAll();
    }""")
    assert_front_editor_geometry(page, 'iphone-object-transform')
    page.set_viewport_size({'width':390,'height':844})
    page.evaluate("() => window.BenfuwanEditorAccess.fitCanvas()")
    assert_front_editor_geometry(page, 'iphone-expanded-selected')
    layer_listeners = page.evaluate("""() => {
      const watched=new Set(['touchmove','touchend','touchcancel','mousemove','mouseup','pointermove','pointerup','pointercancel']);
      const active=new Map(),nativeAdd=document.addEventListener,nativeRemove=document.removeEventListener;
      document.addEventListener=function(type,listener,options){
        if(watched.has(type))active.set(listener,type);
        return nativeAdd.call(this,type,listener,options);
      };
      document.removeEventListener=function(type,listener,options){
        if(watched.has(type))active.delete(listener);
        return nativeRemove.call(this,type,listener,options);
      };
      try{
        renderLayerList();const once=active.size;
        for(let i=0;i<20;i++)renderLayerList();
        return {once,after:active.size};
      }finally{
        document.addEventListener=nativeAdd;document.removeEventListener=nativeRemove;
      }
    }""")
    assert layer_listeners['once'] > 0 and layer_listeners['after'] == layer_listeners['once'], layer_listeners
    print('FRONT_LAYER_LISTENER_OK', layer_listeners['after'])
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

    assert page.evaluate("""() => {const tb=document.querySelector('#page-editor>.toolbar');const b=[...tb.querySelectorAll('button')].find(x=>/openSheet|openTemplates|layer|sticker/i.test(x.getAttribute('onclick')||''))||tb.querySelector('button');b.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));window.BenfuwanEditorAccess.fitCanvas();return !canvas.getActiveObject();}"""), 'main toolbar did not release selection'
    assert_front_editor_geometry(page, 'iphone-expanded-unselected')
    page.evaluate("""() => {const o=canvas.getObjects().find(x=>x.role==='photo');canvas.setActiveObject(o);canvas.requestRenderAll();syncSelection();window.BenfuwanEditorAccess.fitCanvas();}""")
    assert_front_editor_geometry(page, 'iphone-expanded-reselected')
    page.evaluate("() => window.removeBackgroundForActive()")
    good = page.evaluate("""() => {const o=canvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved,role:o?.role,outline:String(o?.aiOutlineSource||'').startsWith('data:image/'),count:canvas.getObjects().filter(x=>x.role==='photo').length};}""")
    assert good == {'ai':True,'role':'photo','outline':True,'count':1}, good
    add_front_photo(page, 1)
    page.evaluate("() => window.removeBackgroundForActive()")
    bad = page.evaluate("""() => {const o=canvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved,name:o?.originalName,count:canvas.getObjects().filter(x=>x.role==='photo').length};}""")
    assert bad['ai'] is False and bad['name']=='test-1.png' and bad['count']==2, bad
    page.set_viewport_size({'width':768,'height':1024})
    page.evaluate("() => window.BenfuwanEditorAccess.fitCanvas()")
    assert_front_editor_geometry(page, 'ipad-selected')
    page.evaluate("""async () => {
      await openPreview();
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    }""")
    preview_state = page.evaluate("() => ({active:document.getElementById('page-preview')?.classList.contains('active'),print:!!ctx.printBase64,mockup:!!ctx.mockupBase64})")
    assert preview_state == {'active':True,'print':True,'mockup':True}, preview_state
    preview = page.evaluate("""() => Promise.all([ctx.printBase64,ctx.mockupBase64].map(src=>new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve({width:img.naturalWidth,height:img.naturalHeight});img.onerror=reject;img.src=src}))).then(([print,mockup])=>({print,mockup,logical:{width:canvas.width,height:canvas.height}}))""")
    assert preview == {'print':{'width':2268,'height':4535},'mockup':{'width':600,'height':1200},'logical':{'width':240,'height':480}}, preview
    print('FRONT_EDITOR_PREVIEW_DIMENSIONS_OK', preview)
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
    page.add_init_script("""(() => {
      window.PublicKeyCredential=function(){};window.__passkeyCreateCalls=0;
      Object.defineProperty(navigator,'credentials',{configurable:true,value:{
        get:async()=>{throw new DOMException('cancelled','NotAllowedError')},
        create:async()=>{window.__passkeyCreateCalls++;return {id:'mock-admin-credential',rawId:new Uint8Array([2]).buffer,type:'public-key',authenticatorAttachment:'platform',getClientExtensionResults:()=>({}),response:{clientDataJSON:new Uint8Array([3]).buffer,attestationObject:new Uint8Array([4]).buffer,getTransports:()=>['internal']}}}
      }});
    })()""")
    page.on('console', lambda msg: print('ADMIN_CONSOLE', msg.type, msg.text))
    page.on('pageerror', lambda exc: print('ADMIN_PAGEERROR', str(exc)))
    page.route('**/api/ai/remove-background', lambda route: route.fulfill(status=200, body=GOOD, content_type='image/png'))
    page.goto(base + '/login', wait_until='domcontentloaded')
    page.locator('#password-toggle').click()
    page.locator('input[name="password"]').fill('fan123')
    submit = page.locator('button[type="submit"],input[type="submit"]').first
    if submit.count(): submit.click()
    else: page.locator('form').evaluate('(f)=>f.submit()')
    page.wait_for_url('**/admin')

    # The first setup path is password login, then explicit enablement in the
    # dedicated login-security view. WebAuthn is mocked only at the browser edge;
    # cryptographic verification is covered by test_passkey_auth.py.
    registered = {'value': False, 'verify': None}
    def passkey_list(route):
        credentials = [] if not registered['value'] else [{'credential_id':'mock-admin-credential','device_label':'這台裝置的 Passkey','transports':['internal'],'created_at':'2026-09-25T00:00:00+00:00','last_used_at':None}]
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'status':'success','configured':True,'credentials':credentials}))
    def passkey_register_options(route):
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'status':'success','ceremony_id':'mock-register','publicKey':{'challenge':'AQ','rp':{'id':'127.0.0.1','name':'本福丸訂製'},'user':{'id':'Ag','name':'admin','displayName':'本福丸管理員'},'pubKeyCredParams':[{'type':'public-key','alg':-7}]}}))
    def passkey_register_verify(route):
        registered['verify'] = route.request.post_data_json
        registered['value'] = True
        route.fulfill(status=200, content_type='application/json', body='{"status":"success"}')
    page.route('**/api/admin/passkeys', passkey_list)
    page.route('**/api/admin/passkey/register/options', passkey_register_options)
    page.route('**/api/admin/passkey/register/verify', passkey_register_verify)
    page.locator('.nav button[data-view="security"]').click()
    poll(page, "() => document.getElementById('view-security')?.classList.contains('active') && !document.getElementById('passkey-enable').disabled")
    page.locator('#passkey-enable').click()
    poll(page, "() => window.__passkeyCreateCalls===1 && document.querySelectorAll('#passkey-list .passkey-item').length===1")
    assert registered['verify']['ceremony_id'] == 'mock-register'
    assert registered['verify']['credential']['authenticatorAttachment'] == 'platform'
    page.unroute('**/api/admin/passkeys')
    page.unroute('**/api/admin/passkey/register/options')
    page.unroute('**/api/admin/passkey/register/verify')
    print('ADMIN_PASSKEY_ENABLE_WEBKIT_OK')

    model_color_src = page.locator('script[src*="admin-model-colors.js"]').get_attribute('src')
    assert model_color_src and 'v=20260923b' in model_color_src, model_color_src
    commerce_src = page.locator('script[src*="admin-commerce-v1.js"]').get_attribute('src')
    assert commerce_src and 'v=20260923cas1' in commerce_src, commerce_src
    def ux_error(route):
        status = int(route.request.url.rsplit('-', 1)[-1])
        route.fulfill(status=status, content_type='application/json', body='{"status":"error"}')
    page.route('**/api/admin/ux-probe-*', ux_error)
    api_messages = page.evaluate("""async () => {
      const out={};
      for(const status of [401,409,503]){
        try{await apiJson('/api/admin/ux-probe-'+status)}catch(e){out[status]=e.message}
      }
      return out;
    }""")
    assert api_messages == {
        '401':'登入已過期，請重新登入後再試',
        '409':'資料已被其他操作更新，請重新載入後再試',
        '503':'服務暫時無法使用，請稍後再試'
    }, api_messages
    page.unroute('**/api/admin/ux-probe-*')
    print('ADMIN_API_FEEDBACK_CACHE_KEY_OK')

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

    page.locator('.nav button[data-view="models"]').click()
    page.locator('#model-tab-btn').click()
    poll(page, "() => document.getElementById('view-models').classList.contains('active') && document.getElementById('model-admin-view').classList.contains('active') && document.querySelector('#models-body button')")
    page.locator('#models-body button').first.click()
    page.locator('#model-modal.show').wait_for()
    model_text = page.locator('#model-modal').inner_text()
    assert 'A5 有效範圍為 200 × 230 mm' in model_text
    assert '座標原點在治具右下角' in model_text
    page.locator('#model-x').fill('1.5');page.locator('#model-y').fill('2.5')
    page.locator('#model-w').fill('80');page.locator('#model-h').fill('160');page.locator('#model-angle').fill('0')
    model_requests = []
    def save_model(route):
        model_requests.append(route.request.post_data_json)
        result = route.fetch()
        time.sleep(.15)
        route.fulfill(response=result)
    page.route('**/api/admin/print/model-profiles', save_model)
    page.evaluate("() => Promise.all([saveModel(),saveModel()])")
    assert len(model_requests) == 1, model_requests
    page.unroute('**/api/admin/print/model-profiles')
    page.locator('#model-modal').wait_for(state='hidden')
    page.locator('.nav button[data-view="styles"]').click()
    poll(page, "() => document.getElementById('view-styles').classList.contains('active') && document.querySelector('#styles-body button')")
    page.locator('#styles-body button').first.click()
    page.locator('#style-modal.show').wait_for()
    assert page.locator('#style-x,#style-y,#style-w,#style-h').count() == 0
    page.locator('#style-modal .mh button').click()

    style_requests = []
    dialogs = []
    page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    def save_style(route):
        style_requests.append(route.request.post_data_json)
        if len(style_requests) == 1:
            route.fulfill(status=503, content_type='application/json', body='{"status":"error"}')
        else:
            time.sleep(.15)
            route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"mock-style-version"}')
    page.route('**/api/admin/save_shop_data', save_style)
    before_styles = page.evaluate("() => shopData.styles.length")
    page.locator('#view-styles .titlebar .btn').click()
    page.locator('#style-name').fill('重複送出回歸殼款')
    page.locator('#style-price').fill('490')
    page.evaluate("() => Promise.all([saveStyle(),saveStyle()])")
    assert len(style_requests) == 1, style_requests
    failed = page.evaluate("""() => ({
      count:shopData.styles.filter(x=>x.name==='重複送出回歸殼款').length,
      open:document.getElementById('style-modal').classList.contains('show'),
      value:document.getElementById('style-name').value,
      disabled:document.getElementById('style-save').disabled
    })""")
    assert failed == {'count':0,'open':True,'value':'重複送出回歸殼款','disabled':False}, failed
    assert any('服務暫時無法使用，請稍後再試' in msg for msg in dialogs), dialogs
    page.evaluate("() => Promise.all([saveStyle(),saveStyle()])")
    saved = page.evaluate("""() => ({
      total:shopData.styles.length,
      count:shopData.styles.filter(x=>x.name==='重複送出回歸殼款').length,
      open:document.getElementById('style-modal').classList.contains('show')
    })""")
    assert len(style_requests) == 2 and saved == {'total':before_styles+1,'count':1,'open':False}, (style_requests,saved)
    page.unroute('**/api/admin/save_shop_data')
    page.evaluate("() => loadShop(true)")
    print('ADMIN_STYLE_RETRY_DOUBLE_SUBMIT_OK')
    print('MODEL_PROFILE_SINGLE_ENTRY_WEBKIT_OK')

    # Catalog CRUD must not mutate browser state until the server accepts it.
    catalog_original = page.evaluate("() => structuredClone(shopData)")
    catalog_fixture = {
        'brands':['Issue29品牌','Issue29空品牌'],
        'models':[{'id':'issue29-model','brand':'Issue29品牌','name':'Issue29型號','status':True}],
        'styles':[{'id':'issue29-style','name':'Issue29系列','price':390,'colors':['透明'],'status':True}],
    }
    page.evaluate("() => {window.__issue29Prompt=window.prompt;window.__issue29Confirm=window.confirm}")

    def catalog_case(label, action, failure_check, success_check):
        page.evaluate("data => {shopData=structuredClone(data);renderBrands();renderModels();renderStyles()}", catalog_fixture)
        requests = []
        def respond(route):
            requests.append(route.request.post_data_json)
            if len(requests) == 1:
                route.fulfill(status=503, content_type='application/json', body='{"status":"error"}')
            else:
                time.sleep(.15)
                route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"mock-catalog-version"}')
        page.route('**/api/admin/save_shop_data', respond)
        dialog_start = len(dialogs)
        page.evaluate(action)
        failed = page.evaluate(failure_check)
        assert len(requests) == 1 and failed, (label, requests, failed)
        assert any('服務暫時無法使用，請稍後再試' in msg for msg in dialogs[dialog_start:]), (label, dialogs[dialog_start:])
        page.evaluate(action)
        saved = page.evaluate(success_check)
        assert len(requests) == 2 and saved, (label, requests, saved)
        page.unroute('**/api/admin/save_shop_data')

    catalog_case(
        'addBrand',
        """() => {window.prompt=()=> 'Issue29新增品牌';return Promise.all([addBrand(),addBrand()])}""",
        """() => JSON.stringify(shopData)===JSON.stringify({brands:['Issue29品牌','Issue29空品牌'],models:[{id:'issue29-model',brand:'Issue29品牌',name:'Issue29型號',status:true}],styles:[{id:'issue29-style',name:'Issue29系列',price:390,colors:['透明'],status:true}]}) && !shopMutationBusy""",
        """() => shopData.brands.filter(x=>x==='Issue29新增品牌').length===1 && !shopMutationBusy""",
    )
    catalog_case(
        'editBrand',
        """() => {window.prompt=()=> 'Issue29品牌改名';return Promise.all([editBrand('Issue29品牌'),editBrand('Issue29品牌')])}""",
        """() => shopData.brands.includes('Issue29品牌') && !shopData.brands.includes('Issue29品牌改名') && shopData.models[0].brand==='Issue29品牌' && !shopMutationBusy""",
        """() => !shopData.brands.includes('Issue29品牌') && shopData.brands.filter(x=>x==='Issue29品牌改名').length===1 && shopData.models[0].brand==='Issue29品牌改名' && !shopMutationBusy""",
    )
    catalog_case(
        'deleteBrand',
        """() => {window.confirm=()=>true;return Promise.all([deleteBrand('Issue29品牌'),deleteBrand('Issue29品牌')])}""",
        """() => shopData.brands.includes('Issue29品牌') && !shopData.brands.includes('未分類') && shopData.models[0].brand==='Issue29品牌' && !shopMutationBusy""",
        """() => !shopData.brands.includes('Issue29品牌') && shopData.brands.filter(x=>x==='未分類').length===1 && shopData.models[0].brand==='未分類' && !shopMutationBusy""",
    )
    catalog_case(
        'deleteModel',
        """() => {window.confirm=()=>true;return Promise.all([deleteModel('issue29-model'),deleteModel('issue29-model')])}""",
        """() => shopData.models.some(x=>x.id==='issue29-model') && document.getElementById('models-body').textContent.includes('Issue29型號') && !shopMutationBusy""",
        """() => !shopData.models.some(x=>x.id==='issue29-model') && !shopMutationBusy""",
    )
    catalog_case(
        'deleteStyle',
        """() => {window.confirm=()=>true;return Promise.all([deleteStyle('issue29-style'),deleteStyle('issue29-style')])}""",
        """() => shopData.styles.some(x=>x.id==='issue29-style') && document.getElementById('styles-body').textContent.includes('Issue29系列') && !shopMutationBusy""",
        """() => !shopData.styles.some(x=>x.id==='issue29-style') && !shopMutationBusy""",
    )
    page.evaluate("async () => {await loadShop(true);window.prompt=window.__issue29Prompt;window.confirm=window.__issue29Confirm;delete window.__issue29Prompt;delete window.__issue29Confirm}")
    print('ADMIN_CATALOG_CRUD_STATE_RETRY_DOUBLE_SUBMIT_OK')

    # Catalog commit can succeed before production-profile sync fails. The
    # browser must adopt that committed candidate and returned version so its
    # next catalog mutation cannot legally CAS stale data over the model edit.
    partial_before = page.evaluate("() => ({data:structuredClone(shopData),model:structuredClone(shopData.models[0]),version:shopVersion})")
    primed_catalog = page.request.get(base + '/api/shop_data')
    assert primed_catalog.headers.get('x-benfuwan-cache') == 'HIT', primed_catalog.headers
    assert primed_catalog.json()['version'] == partial_before['version']
    partial_model_name = f'Partial Success 型號 {time.time_ns()}'
    partial_brand = f'部分成功後品牌 {time.time_ns()}'
    page.evaluate("id => openModelEditor(id)", partial_before['model']['id'])
    page.locator('#model-name').fill(partial_model_name)
    partial_dialog_start = len(dialogs)
    original_save_profiles = app_module.print_center.store.save_profiles
    def fail_profile_sync(_profiles):
        raise RuntimeError('browser fixture')
    app_module.print_center.store.save_profiles = fail_profile_sync
    try:
        page.evaluate("() => saveModel()")
    finally:
        app_module.print_center.store.save_profiles = original_save_profiles
    server_partial, server_partial_version = app_module.cloud_get_json_versioned(
        'shop_data', app_module.DATA_FILE, app_module.DEFAULT_SHOP_DATA)
    partial_state = page.evaluate("""() => ({
      open:document.getElementById('model-modal').classList.contains('show'),
      input:document.getElementById('model-name').value,
      id:document.getElementById('model-id').value,
      local:shopData.models.find(x=>x.id===document.getElementById('model-id').value)?.name,
      version:shopVersion
    })""")
    assert partial_state == {
        'open':True, 'input':partial_model_name, 'id':partial_before['model']['id'],
        'local':partial_model_name, 'version':server_partial_version,
    }, partial_state
    assert server_partial_version != partial_before['version']
    assert next(row for row in server_partial['models'] if row['id'] == partial_before['model']['id'])['name'] == partial_model_name
    assert any('型號資料已儲存，但正式列印參數同步失敗' in msg for msg in dialogs[partial_dialog_start:])
    fresh_after_partial = page.request.get(base + '/api/shop_data')
    assert fresh_after_partial.headers.get('x-benfuwan-cache') == 'MISS', fresh_after_partial.headers
    fresh_after_partial_data = fresh_after_partial.json()
    assert fresh_after_partial_data['version'] == server_partial_version
    assert next(row for row in fresh_after_partial_data['data']['models'] if row['id'] == partial_before['model']['id'])['name'] == partial_model_name
    print('ADMIN_MODEL_PROFILE_PARTIAL_SUCCESS_CACHE_INVALIDATION_OK')

    page.evaluate("""async brand => {const old=window.prompt;window.prompt=()=>brand;try{await addBrand()}finally{window.prompt=old}}""", partial_brand)
    server_after_mutation = page.request.get(base + '/api/shop_data').json()
    assert partial_brand in server_after_mutation['data']['brands']
    assert next(row for row in server_after_mutation['data']['models'] if row['id'] == partial_before['model']['id'])['name'] == partial_model_name
    assert page.evaluate("brand => shopData.brands.includes(brand) && document.getElementById('model-modal').classList.contains('show')", partial_brand)
    page.evaluate("() => saveModel()")
    assert 'show' not in page.locator('#model-modal').get_attribute('class')
    partial_restore = page.request.post(base + '/api/admin/save_shop_data', data={
        'data':partial_before['data'], 'expected_version':page.evaluate('() => shopVersion'),
    })
    assert partial_restore.status == 200, partial_restore.text()
    page.evaluate("() => loadShop(true)")
    print('ADMIN_MODEL_PROFILE_PARTIAL_SUCCESS_STATE_OK')

    # A second tab/device wins the catalog CAS. This tab must keep its unsaved
    # inputs and local state across all shop_data write paths until reload.
    stale_shop = page.evaluate("() => ({data:structuredClone(shopData),version:shopVersion})")
    winner_shop = copy.deepcopy(stale_shop['data'])
    winner_shop['brands'].append('CAS 分頁 A')
    winner = page.request.post(base + '/api/admin/save_shop_data', data={
        'data': winner_shop, 'expected_version': stale_shop['version'],
    })
    assert winner.status == 200, winner.text()
    winner_version = winner.json()['version']
    winner_cached = page.request.get(base + '/api/shop_data')
    assert winner_cached.headers.get('x-benfuwan-cache') == 'MISS', winner_cached.headers
    assert winner_cached.json()['version'] == winner_version
    stale_dialog_start = len(dialogs)

    page.evaluate("""() => {openStyleEditor();document.getElementById('style-name').value='CAS 分頁 B 系列';document.getElementById('style-price').value='555'}""")
    page.evaluate("() => saveStyle()")
    style_stale = page.evaluate("""() => ({
      open:document.getElementById('style-modal').classList.contains('show'),
      input:document.getElementById('style-name').value,
      local:shopData.styles.some(x=>x.name==='CAS 分頁 B 系列'),
      version:shopVersion
    })""")
    assert style_stale == {'open':True,'input':'CAS 分頁 B 系列','local':False,'version':stale_shop['version']}, style_stale
    page.locator('#style-modal .mh button').click()

    original_model = stale_shop['data']['models'][0]
    page.evaluate("id => openModelEditor(id)", original_model['id'])
    page.locator('#model-name').fill('CAS 分頁 B 型號')
    page.evaluate("() => saveModel()")
    model_stale = page.evaluate("""() => ({
      open:document.getElementById('model-modal').classList.contains('show'),
      input:document.getElementById('model-name').value,
      local:shopData.models.some(x=>x.name==='CAS 分頁 B 型號'),
      version:shopVersion
    })""")
    assert model_stale == {'open':True,'input':'CAS 分頁 B 型號','local':False,'version':stale_shop['version']}, model_stale
    cache_after_stale = page.request.get(base + '/api/shop_data')
    assert cache_after_stale.headers.get('x-benfuwan-cache') == 'HIT', cache_after_stale.headers
    assert cache_after_stale.json()['version'] == winner_version
    page.locator('#model-modal .mh button').click()

    page.locator('.nav button[data-view="commerce"]').click()
    poll(page, "() => document.getElementById('view-commerce')?.classList.contains('active')")
    page.locator('[data-tab="stock"]').click()
    poll(page, "() => !document.getElementById('pos-stock-panel').hidden")
    local_price = page.evaluate("""() => {const id=document.querySelector('#pos-series [data-series].selected')?.dataset.series||shopData.styles[0].id;return {id,price:Number(shopData.styles.find(x=>String(x.id)===String(id))?.price)}}""")
    page.locator('#pos-series-price').fill('888')
    page.locator('#pos-price-form button').click()
    poll(page, "() => document.getElementById('pos-message').textContent.includes('資料已被其他分頁或裝置更新')")
    assert page.locator('#pos-series-price').input_value() == '888'
    assert page.evaluate("before => Number(shopData.styles.find(x=>String(x.id)===String(before.id))?.price)===before.price", local_price)

    server_after_stale = page.request.get(base + '/api/shop_data').json()
    assert server_after_stale['version'] == winner_version
    assert 'CAS 分頁 A' in server_after_stale['data']['brands']
    assert not any(x.get('name') == 'CAS 分頁 B 系列' for x in server_after_stale['data']['styles'])
    assert any('資料已被其他分頁或裝置更新，請重新載入後再修改。' in msg for msg in dialogs[stale_dialog_start:]), dialogs[stale_dialog_start:]
    page.evaluate("() => loadShop(true)")
    assert page.evaluate("version => shopVersion===version && shopData.brands.includes('CAS 分頁 A')", winner_version)
    restored = page.request.post(base + '/api/admin/save_shop_data', data={
        'data': stale_shop['data'], 'expected_version': winner_version,
    })
    assert restored.status == 200, restored.text()
    page.evaluate("() => loadShop(true)")
    print('ADMIN_CATALOG_MODEL_PRICE_STALE_CAS_OK')

    print_nav = page.locator('.nav button[data-view="print-center"]')
    print_nav.click()
    poll(page, "() => document.querySelectorAll('#pc-grid .pc-card').length>0 && document.getElementById('view-print-center').classList.contains('active')")
    assert page.locator('#pc-config').get_attribute('class').find('warn') >= 0
    assert page.locator('[data-pc="start"]').count() == 0
    assert page.locator('[data-pc="profile"]').count() == 0
    assert page.locator('#pc-modal').count() == 0
    assert '80 × 160 mm / X 1.5 / Y 2.5' in page.locator('#pc-grid').inner_text()
    for width, height in ((390,844),(768,1024),(1440,900)):
        page.set_viewport_size(dict(width=width,height=height))
        metrics = page.evaluate("""() => ({
          width:innerWidth,scroll:document.documentElement.scrollWidth,
          view:document.getElementById('view-print-center').getBoundingClientRect().width,
          cards:document.querySelectorAll('#pc-grid .pc-card').length,
          secrets:document.getElementById('view-print-center').textContent.includes('fake-key')
        })""")
        assert metrics['scroll'] <= width + 2 and metrics['view'] > 200 and metrics['cards'] > 0 and not metrics['secrets'], metrics
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
    template_editor_src = page.locator('script[src*="admin-template-editor-v2.js"]').get_attribute('src')
    assert template_editor_src and 'v=20260923cas1' in template_editor_src, template_editor_src
    print('ADMIN_FABRIC_LAZY_OK')

    template_server_original = page.evaluate("() => ({data:structuredClone(templatesData),version:templatesVersion})")
    template_winner = copy.deepcopy(template_server_original['data'])
    template_winner['templates'].append({'id':'cas-template-a','name':'CAS 模板 A','category':'熱門','model_id':'*','universal':True})
    template_winner_response = page.request.post(base + '/api/admin/save_templates', data={
        'data': template_winner, 'expected_version': template_server_original['version'],
    })
    assert template_winner_response.status == 200, template_winner_response.text()
    template_winner_version = template_winner_response.json()['version']
    page.route('**/api/admin/upload_image', lambda route: route.fulfill(status=200, content_type='application/json', body='{"status":"success","url":"/static/materials/cas-orphan.png"}'))
    template_stale_dialog = len(dialogs)
    page.evaluate("""() => {document.getElementById('tpl-id').value='';document.getElementById('tpl-name').value='CAS 模板 B';document.getElementById('tpl-category').value='熱門'}""")
    page.evaluate("() => saveTemplate()")
    template_stale = page.evaluate("""() => ({
      open:document.getElementById('template-modal').classList.contains('show'),
      input:document.getElementById('tpl-name').value,
      local:templatesData.templates.some(x=>x.name==='CAS 模板 B'),
      version:templatesVersion
    })""")
    assert template_stale == {'open':True,'input':'CAS 模板 B','local':False,'version':template_server_original['version']}, template_stale
    page.unroute('**/api/admin/upload_image')
    template_server_after = page.request.get(base + '/api/templates').json()
    assert template_server_after['version'] == template_winner_version
    assert [row['id'] for row in template_server_after['data']['templates'] if row.get('id') in ('cas-template-a','cas-template-b')] == ['cas-template-a']
    assert any('資料已被其他分頁或裝置更新，請重新載入後再修改。' in msg for msg in dialogs[template_stale_dialog:]), dialogs[template_stale_dialog:]
    page.evaluate("() => loadTemplates(true)")
    reloaded_template = page.evaluate("version => ({version:templatesVersion,hasA:templatesData.templates.some(x=>x.id==='cas-template-a'),input:document.getElementById('tpl-name').value})", template_winner_version)
    assert reloaded_template == {'version':template_winner_version,'hasA':True,'input':'CAS 模板 B'}, reloaded_template
    restored_templates = page.request.post(base + '/api/admin/save_templates', data={
        'data': template_server_original['data'], 'expected_version': template_winner_version,
    })
    assert restored_templates.status == 200, restored_templates.text()
    page.evaluate("() => loadTemplates(true)")
    print('ADMIN_TEMPLATE_STALE_CAS_OK')

    page.evaluate("""() => new Promise((resolve,reject)=>{const c=document.createElement('canvas');c.width=128;c.height=128;const g=c.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,128,128);g.fillStyle='#d94d75';g.fillRect(24,16,80,96);fabric.Image.fromURL(c.toDataURL('image/png'),img=>{try{img.set({left:tplW/2,top:tplH/2,originX:'center',originY:'center',scaleX:.8,scaleY:1.1,angle:13,originalName:'admin-test.png'});visualCanvas.add(img);visualCanvas.setActiveObject(img);visualCanvas.requestRenderAll();resolve()}catch(e){reject(e)}});})""")
    before = page.evaluate("""() => {const o=visualCanvas.getActiveObject();return {w:o.getScaledWidth(),h:o.getScaledHeight(),x:o.getCenterPoint().x,y:o.getCenterPoint().y,a:o.angle};}""")
    page.evaluate("() => window.bfAdminRemoveBackground()")
    after = page.evaluate("""() => {const o=visualCanvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved,w:o?.getScaledWidth(),h:o?.getScaledHeight(),x:o?.getCenterPoint().x,y:o?.getCenterPoint().y,a:o?.angle,publicSrc:o?.publicSrc||''};}""")
    assert after['ai'] is True, after
    for k in ('w','h','x','y','a'):
        assert abs(after[k]-before[k]) < .75, (k,before,after)
    assert after['publicSrc'], after

    # Runtime saveTemplate is the lazy-loaded editor-v2 override. Verify its
    # existing candidate state/busy boundary, then cover deleteTemplate too.
    template_original = page.evaluate("() => structuredClone(templatesData)")
    template_save_requests = []
    template_uploads = []
    page.route('**/api/admin/upload_image', lambda route: (template_uploads.append(route.request.url), route.fulfill(status=200, content_type='application/json', body='{"status":"success","url":"/static/uploads/issue29-template.png"}')))
    def save_template_response(route):
        template_save_requests.append(route.request.post_data_json)
        if len(template_save_requests) == 1:
            route.fulfill(status=503, content_type='application/json', body='{"status":"error"}')
        else:
            time.sleep(.15)
            route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"mock-template-version"}')
    page.route('**/api/admin/save_templates', save_template_response)
    page.evaluate("""() => {document.getElementById('tpl-id').value='';document.getElementById('tpl-name').value='Issue29模板';document.getElementById('tpl-category').value='Issue29分類'}""")
    before_template_count = page.evaluate("() => templatesData.templates.length")
    template_dialog_start = len(dialogs)
    page.evaluate("() => Promise.all([saveTemplate(),saveTemplate()])")
    template_failed = page.evaluate("""() => ({
      count:templatesData.templates.filter(x=>x.name==='Issue29模板').length,
      open:document.getElementById('template-modal').classList.contains('show'),
      value:document.getElementById('tpl-name').value,
      disabled:[...document.querySelectorAll('#template-modal .mf .btn')].find(b=>b.textContent.includes('儲存'))?.disabled||false
    })""")
    assert len(template_save_requests) == 1 and len(template_uploads) == 1, (template_save_requests, template_uploads)
    assert template_failed == {'count':0,'open':True,'value':'Issue29模板','disabled':False}, template_failed
    assert any('服務暫時無法使用，請稍後再試' in msg for msg in dialogs[template_dialog_start:]), dialogs[template_dialog_start:]
    page.evaluate("() => Promise.all([saveTemplate(),saveTemplate()])")
    template_saved = page.evaluate("""() => ({
      total:templatesData.templates.length,
      count:templatesData.templates.filter(x=>x.name==='Issue29模板').length,
      open:document.getElementById('template-modal').classList.contains('show')
    })""")
    assert len(template_save_requests) == 2 and len(template_uploads) == 2, (template_save_requests, template_uploads)
    assert template_saved == {'total':before_template_count+1,'count':1,'open':False}, template_saved
    page.unroute('**/api/admin/upload_image')
    page.unroute('**/api/admin/save_templates')

    delete_requests = []
    page.evaluate("""data => {templatesData=structuredClone(data);templatesData.templates.push({id:'issue29-delete-template',name:'Issue29刪除模板',category:'熱門'});renderTemplateTabs();renderTemplates();window.__issue29Confirm=window.confirm;window.confirm=()=>true}""", template_original)
    def delete_template_response(route):
        delete_requests.append(route.request.post_data_json)
        if len(delete_requests) == 1:
            route.fulfill(status=503, content_type='application/json', body='{"status":"error"}')
        else:
            time.sleep(.15)
            route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"mock-template-delete-version"}')
    page.route('**/api/admin/save_templates', delete_template_response)
    delete_dialog_start = len(dialogs)
    page.evaluate("() => Promise.all([deleteTemplate('issue29-delete-template'),deleteTemplate('issue29-delete-template')])")
    delete_failed = page.evaluate("() => templatesData.templates.filter(x=>x.id==='issue29-delete-template').length===1 && document.getElementById('template-grid').textContent.includes('Issue29刪除模板') && !templateDeleteBusy")
    assert len(delete_requests) == 1 and delete_failed, (delete_requests, delete_failed)
    assert any('服務暫時無法使用，請稍後再試' in msg for msg in dialogs[delete_dialog_start:]), dialogs[delete_dialog_start:]
    page.evaluate("() => Promise.all([deleteTemplate('issue29-delete-template'),deleteTemplate('issue29-delete-template')])")
    delete_saved = page.evaluate("() => !templatesData.templates.some(x=>x.id==='issue29-delete-template') && !templateDeleteBusy")
    assert len(delete_requests) == 2 and delete_saved, (delete_requests, delete_saved)
    page.unroute('**/api/admin/save_templates')
    page.evaluate("async () => {await loadTemplates(true);window.confirm=window.__issue29Confirm;delete window.__issue29Confirm}")
    print('ADMIN_TEMPLATE_CRUD_STATE_RETRY_DOUBLE_SUBMIT_OK')
    print('ADMIN_WEBKIT_OK')
    page.close()


def durable_receipt_test(playwright, base):
    """Persist the real committed request across tab close AND browser restart."""
    engine = getattr(playwright, os.environ.get('BROWSER_ENGINE', 'webkit'))
    def admin(context):
        page = context.new_page()
        page.goto(base + '/login', wait_until='domcontentloaded')
        if '/admin' not in page.url:
            if not page.locator('#password-form').is_visible():
                page.locator('#password-toggle').click()
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


def passkey_login_test(browser, base):
    mock = """(() => {
      window.PublicKeyCredential=function(){};window.__passkeyGetCalls=0;window.__passkeyMode='success';
      Object.defineProperty(navigator,'credentials',{configurable:true,value:{
        create:async()=>null,
        get:async()=>{window.__passkeyGetCalls++;if(window.__passkeyMode==='cancel')throw new DOMException('cancelled','NotAllowedError');return {id:'mock-login-credential',rawId:new Uint8Array([2]).buffer,type:'public-key',authenticatorAttachment:'platform',getClientExtensionResults:()=>({}),response:{clientDataJSON:new Uint8Array([3]).buffer,authenticatorData:new Uint8Array([4]).buffer,signature:new Uint8Array([5]).buffer,userHandle:null}}}
      }});
    })()"""
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    page.add_init_script(mock)
    verify = []
    page.route('**/api/auth/passkey/status', lambda route: route.fulfill(status=200,content_type='application/json',body='{"status":"success","configured":true,"has_credentials":true}'))
    page.route('**/api/auth/passkey/options', lambda route: route.fulfill(status=200,content_type='application/json',body='{"status":"success","ceremony_id":"mock-login","publicKey":{"challenge":"AQ","rpId":"127.0.0.1","allowCredentials":[{"type":"public-key","id":"Ag"}],"userVerification":"required"}}'))
    def verify_login(route):
        verify.append(route.request.post_data_json)
        route.fulfill(status=200,content_type='application/json',body='{"status":"success","redirect":"/api/health"}')
    page.route('**/api/auth/passkey/verify', verify_login)
    page.goto(base + '/login', wait_until='domcontentloaded')
    poll(page, "() => !document.getElementById('passkey-login-button').classList.contains('hidden')")
    assert page.locator('#passkey-login-button').inner_text() == '使用 Face ID 登入'
    assert page.locator('#passkey-login-button').is_visible() and not page.locator('#password-form').is_visible()
    assert page.evaluate('() => window.__passkeyGetCalls') == 0
    page.locator('#passkey-login-button').click()
    page.wait_for_url('**/api/health')
    assert len(verify) == 1 and verify[0]['ceremony_id'] == 'mock-login'
    assert verify[0]['credential']['authenticatorAttachment'] == 'platform'
    page.close()

    cancelled = browser.new_page(viewport={'width': 390, 'height': 844})
    cancelled.add_init_script(mock)
    cancelled.route('**/api/auth/passkey/status', lambda route: route.fulfill(status=200,content_type='application/json',body='{"status":"success","configured":true,"has_credentials":true}'))
    cancelled.route('**/api/auth/passkey/options', lambda route: route.fulfill(status=200,content_type='application/json',body='{"status":"success","ceremony_id":"mock-cancel","publicKey":{"challenge":"AQ","rpId":"127.0.0.1","allowCredentials":[],"userVerification":"required"}}'))
    cancelled.goto(base + '/login', wait_until='domcontentloaded')
    cancelled.evaluate("() => {window.__passkeyMode='cancel'}")
    cancelled.locator('#passkey-login-button').click()
    poll(cancelled, "() => document.getElementById('login-message').textContent.includes('已取消 Face ID 驗證')")
    cancelled.locator('#password-toggle').click()
    assert cancelled.locator('#password-form').is_visible()
    cancelled.close()

    unsupported = browser.new_page(viewport={'width': 390, 'height': 844})
    unsupported.add_init_script("Object.defineProperty(window,'PublicKeyCredential',{configurable:true,value:undefined})")
    unsupported.goto(base + '/login', wait_until='domcontentloaded')
    poll(unsupported, "() => document.getElementById('password-form').classList.contains('show')")
    assert unsupported.locator('#password-form').is_visible()
    assert not unsupported.locator('#passkey-login-button').is_visible()
    unsupported.close()
    print('PASSKEY_LOGIN_WEBKIT_OK')


def main():
    server = ServerThread();server.start();time.sleep(.8)
    try:
        with sync_playwright() as p:
            browser = getattr(p, os.environ.get('BROWSER_ENGINE', 'webkit')).launch()
            try:
                base='http://127.0.0.1:8765';passkey_login_test(browser,base);front_test(browser,base);checkout_test(browser,base);admin_test(browser,base)
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
