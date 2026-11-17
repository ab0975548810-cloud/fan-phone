"""Real isolated storefront -> order -> admin full editor -> cross-device revision."""
import os
import sys
import base64
import io
from PIL import Image, ImageDraw
import threading
import time
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
os.environ.pop('SUPABASE_URL',None);os.environ.pop('SUPABASE_SERVICE_ROLE_KEY',None)
os.environ['SESSION_COOKIE_SECURE']='false'
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_order_designs as fixture
import test_multilayer_templates as templates
app=fixture.app


def preview_mask():
    im=Image.new('RGBA',(200,400),(0,0,0,0));draw=ImageDraw.Draw(im)
    draw.rounded_rectangle((10,10,189,389),radius=12,outline='#9a9a9a',width=2)
    out=io.BytesIO();im.save(out,'PNG');return out.getvalue()


def wait(page, expression, timeout=30000):
    until=time.monotonic()+timeout/1000
    while time.monotonic()<until:
        if page.evaluate(expression):return
        page.wait_for_timeout(100)
    raise AssertionError((expression,page.locator("body").inner_text()[:1500]))


def run():
    fx=fixture.OrderDesignTests();fx.setUp()
    saved_templates=app.TEMPLATES_FILE;app.TEMPLATES_FILE=str(Path(fx.fixture.tmp.name)/'order-templates.json')
    fx.addCleanup(setattr,app,'TEMPLATES_FILE',saved_templates)
    server=make_server('127.0.0.1',0,app.app,threaded=True);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base='http://127.0.0.1:'+str(server.server_port)
    try:
        with sync_playwright() as p, mock.patch('editable_stickers.public_image',side_effect=lambda app,url:preview_mask() if 'preview' in url else fixture.fx.mask()):
            browser=getattr(p,os.environ.get('BROWSER_ENGINE','webkit')).launch()
            for product,use_template in (('phone_case',False),('camera_film',False),('phone_case',True),('camera_film',True)):
                if os.environ.get('TEMPLATE_ONLY') and not use_template:continue
                shop=app.cloud_get_json('shop_data',app.DATA_FILE,app.DEFAULT_SHOP_DATA)
                shop['models'][0]['product_type']=product;shop['styles'][0]['product_type']=product
                shop['models'][0]['direct_style_id']=fx.style
                shop['styles'][0].update(colors=[],model_colors={})
                profile=shop['models'][0]['case_profiles'][fx.style]
                profile.update(print_w=41.1 if product=='camera_film' else 71.63,print_h=21.7 if product=='camera_film' else 149.61)
                app.local_save_json(app.DATA_FILE,shop)
                tpl=templates.template(fx.model,fx.style,count=5)
                tpl['objects_json']['objects'][1]['styles']=[]
                with mock.patch('editable_stickers.public_image',return_value=fixture.fx.image()):templates.multi.prepare_template(app,tpl)
                app.local_save_json(app.TEMPLATES_FILE,{'templates':[tpl] if use_template else [],'categories':['全部']})
                import security_perf
                security_perf._CACHE.clear();security_perf._HITS.clear()
                customer=browser.new_context(viewport={'width':390,'height':844},has_touch=True)
                page=customer.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.route('**/static/dialog-*.png',lambda r:r.fulfill(body=preview_mask() if 'preview' in r.request.url else fixture.fx.mask(),content_type='image/png'))
                print('STEP storefront',product,flush=True);page.route('**/static/multi-layer.png',lambda r:r.fulfill(body=fixture.fx.image(),content_type='image/png'))
                page.goto(base);wait(page,"typeof catalogState!=='undefined' && catalogState==='ready'")
                print('STEP start editor',flush=True)
                page.evaluate("async()=>{await startNewDesign();selectModel(shopData.models[0]);selectStyle(shopData.styles[0]);await startEditor(false)}")
                if use_template:
                    tpl['objects_json']['objects'][0]=page.evaluate('(o)=>new fabric.Rect(o).toObject(BenfuwanMultilayer.PROPS)',tpl['objects_json']['objects'][0])
                    with mock.patch('editable_stickers.public_image',return_value=fixture.fx.image()):templates.multi.prepare_template(app,tpl)
                    app.local_save_json(app.TEMPLATES_FILE,{'templates':[tpl],'categories':['全部']})
                    security_perf._CACHE.clear()
                    page.evaluate('async()=>{await applyTemplate(templatesData.templates[0])}')
                    assert page.evaluate("canvas.layer_contract_version==='multilayer-v1'")
                print('STEP add objects',flush=True)
                photo='data:image/png;base64,'+base64.b64encode(fixture.fx.image()).decode()
                page.evaluate("""async url=>{try{
                  for(const [role,x] of [['photo',45],['sticker',100]])await new Promise((resolve,reject)=>fabric.Image.fromURL(url,o=>{try{o.set({role,left:x,top:160,scaleX:.15,scaleY:.15,opacity:.8});canvas.add(o);resolve()}catch(e){reject(e)}}));
                  await ensureEditorFont('jf-openhuninn','本福丸');canvas.add(new fabric.Textbox('本福丸',{role:'text',fontFamily:'jf-openhuninn',fontSize:18,left:40,top:250,width:100}));recordHistory();await openPreview();await confirmDesignToCart();
                }catch(e){throw Error(e.stack)}}""",photo)
                print('STEP cart',flush=True)
                wait(page,"cartItem?.designJson?.orderDesignVersion===1")
                original_pixels=page.evaluate('ctx.printBase64')
                order=page.evaluate("""async()=>{const d=await BenfuwanDesignSources.prepare(cartItem.designJson);const r=await fetch('/api/create_order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({idempotency_key:crypto.randomUUID(),model_id:ctx.modelId,style_id:ctx.styleId,quantity:1,customer_name:'隔離設計測試',payment_method:'現金',print_file:ctx.printBase64,mockup_file:ctx.mockupBase64||ctx.printBase64,design_json:d})});const j=await r.json();if(!r.ok)throw Error(JSON.stringify(j));return j.order_id;}""")
                original=app.commerce.store.order(order);finance=app.commerce.store.read()
                customer.close()
                def admin_context():
                    context=browser.new_context(viewport={'width':390,'height':844},has_touch=True)
                    context.add_cookies([{'name':cookie.key,'value':cookie.value,'url':base} for cookie in fx.client._cookies.values()])
                    return context
                admin=admin_context();page=admin.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
                page.goto(base+'/admin/order-design/'+order)
                wait(page,"document.querySelector('#order-design-save')?.disabled===false",timeout=30000)
                page.evaluate('openPreview()');wait(page,'ctx.productionMeta?.dpi===720 && !!ctx.printBase64')
                assert page.evaluate('ctx.printBase64')==original_pixels
                page.evaluate("navigate('page-editor')")
                baseline=page.evaluate("canvas.toJSON(CUSTOM_PROPS).objects")
                index=next(i for i,o in enumerate(baseline) if o.get('role')=='sticker')
                page.evaluate("()=>{canvas.setActiveObject(canvas.getObjects().find(o=>o.role==='sticker'));nudgeActive(5,0)}")
                changed=page.evaluate("canvas.toJSON(CUSTOM_PROPS).objects")
                assert all(before==after for i,(before,after) in enumerate(zip(baseline,changed)) if i!=index)
                assert changed[index]['left']==baseline[index]['left']+5
                page.locator('#order-design-save').click()
                wait(page,"document.getElementById('order-design-status').textContent.includes('V2 草稿已保存')",timeout=30000)
                page.evaluate('openPreview()');wait(page,'ctx.productionMeta?.dpi===720 && !!ctx.printBase64')
                pixels=page.evaluate('ctx.printBase64');meta=page.evaluate('ctx.productionMeta')
                admin.close()
                second=admin_context();again=second.new_page();again.goto(base+'/admin/order-design/'+order)
                wait(again,"document.querySelector('#order-design-save')?.disabled===false")
                assert 'V2' in again.locator('#order-design-status').text_content()
                restored=again.evaluate('canvas.toJSON(CUSTOM_PROPS).objects')
                assert restored[index]['left']==changed[index]['left']
                again.evaluate('openPreview()');wait(again,'ctx.productionMeta?.dpi===720 && !!ctx.printBase64')
                assert again.evaluate('ctx.printBase64')==pixels
                assert app.commerce.store.order(order)==original
                assert app.commerce.store.read()==finance
                assert len(app.order_designs.rows(order))==2
                assert fx.fixture.fake.calls==[]
                assert not errors,errors
                again.evaluate("navigate('page-editor')")
                evidence=ROOT/'__pycache__'/'order-design-evidence';evidence.mkdir(exist_ok=True)
                again.screenshot(path=str(evidence/(browser.browser_type.name+'-'+product+'-'+str(use_template)+'.png')))
                second.close()
                print('ORDER_DESIGN_CROSS_DEVICE_V2_720_IMMUTABLE_OK',browser.browser_type.name,product,'template='+str(use_template),meta,flush=True)
            browser.close()
    finally:
        server.shutdown();server.server_close();fx.doCleanups()


if __name__=='__main__':run()
