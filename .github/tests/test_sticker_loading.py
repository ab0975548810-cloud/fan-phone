"""CSP/CORS, byte-preserving stickers and atomic failure/recovery in real browsers."""
import base64
import io
import json
import os
import runpy
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parents[2]


def sticker_loading_test(browser,base,poll):
    evidence=ROOT/'artifacts/sticker-loading';evidence.mkdir(parents=True,exist_ok=True)
    baseline=os.environ.get('STICKER_BASELINE')=='1'
    im=Image.new('RGBA',(128,128));ImageDraw.Draw(im).ellipse((20,20,108,108),fill=(240,80,120,200))
    buf=io.BytesIO();im.save(buf,'PNG');png=buf.getvalue();data='data:image/png;base64,'+base64.b64encode(png).decode()
    for product in ('camera_film','phone_case'):
        context=browser.new_context(viewport={'width':390,'height':844},has_touch=True,is_mobile=True,device_scale_factor=2)
        page=context.new_page();errors=[];csp=[];requests=[];held=[];mode=['ok']
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('console',lambda m:csp.append(m.text) if 'connect-src' in m.text else None)
        remote='https://stickers.invalid/public/photo.png'
        page.route('https://stickers.invalid/**',lambda r:r.fulfill(body=png,content_type='image/png',headers={'Access-Control-Allow-Origin':'*'}))
        def proxy(route):
            requests.append({'url':route.request.url,'mode':mode[0]})
            if mode[0]=='hold':held.append(route);return
            if mode[0]=='network':route.abort('internetdisconnected');return
            if mode[0]=='retry':mode[0]='ok';route.fulfill(status=503,body='temporarily unavailable');return
            if mode[0]=='missing':route.fulfill(status=404,body='not found');return
            route.fulfill(body=b'broken png' if mode[0]=='decode' else png,content_type='image/png')
        page.route('**/api/public/asset_proxy*',proxy)
        maskfile=ROOT/'.github/tests/fixtures/film/print.png'
        mask='data:image/png;base64,'+base64.b64encode(maskfile.read_bytes()).decode()
        w,h=(67,37) if product=='camera_film' else (75,150)
        catalog={'brands':['Apple'],'models':[{'id':'m_1792558304007' if product=='camera_film' else 'model_apple_17_pro_max','name':'iPhone 17 Pro Max','brand':'Apple','status':True,'product_type':product,'direct_style_id':'style','case_profiles':{'style':{'preview_mask_img':mask,'print_line_img':mask,'print_w':w,'print_h':h,'print_x':66,'print_y':30,'print_angle':0}}}], 'styles':[{'id':'style','name':'鏡頭底膜' if product=='camera_film' else '手機殼','status':True,'product_type':product,'price':490,'colors':[] if product=='camera_film' else ['白']}]}
        page.route('**/api/shop_data*',lambda r:r.fulfill(json={'status':'success','version':'fixture','data':catalog}))
        asset={'id':'dialog','name':'測試文字貼紙','imageSrc':remote,'textArea':{'x':.2,'y':.2,'width':.6,'height':.6},'defaultTextStyle':{'text':'本福丸','fontFamily':'jf-openhuninn','fontSize':24,'minFontSize':10}}
        page.route('**/api/assets',lambda r:r.fulfill(json={'status':'success','data':{'categories':['全部'],'stickers':[{'id':'photo','url':remote}],'editable_stickers':[asset]}}))
        if baseline:
            for file in ('index.html','static/index-base-20260913.html','static/front-draft-store.js','static/front-design-draft-v1.js','static/front-editable-stickers-v1.js','static/editable-sticker-core-v1.js'):
                old=subprocess.check_output(['git','show','44ed440:'+file],cwd=ROOT)
                page.route(base+'/' if file=='index.html' else '**/'+file+'*',lambda r,request,body=old:r.fulfill(body=body,content_type='text/html' if body.startswith(b'<!DOCTYPE') else 'application/javascript',headers={'Content-Security-Policy':"script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdnjs.cloudflare.com; img-src * data: blob:; connect-src 'self'; font-src 'self' data: https://cdnjs.cloudflare.com"}))
        page.goto(base+'/',wait_until='domcontentloaded');poll(page,"()=>typeof catalogState!=='undefined'&&catalogState==='ready'&&!!window.BenfuwanDesignDraft")
        page.evaluate("async()=>{await startNewDesign();selectModel(shopData.models[0]);selectStyle(shopData.styles[0]);ctx.colorName='白';await startEditor(false);openStickerSheet()}")
        assert page.evaluate('()=>!!canvas'),page.evaluate("()=>({errors:document.querySelector('.toast')?.textContent})")
        page.locator('#sticker-grid .sticker-item').first.click()
        poll(page,"()=>canvas.getObjects().some(o=>o.role==='sticker')")
        if baseline:
            assert not page.evaluate('()=>BenfuwanDesignDraft.saveNow()')
            assert csp,csp
            message=page.locator('.toast').inner_text();assert 'Load failed' in message or 'fetch' in message.lower(),message
            page.screenshot(path=str(evidence/f'before-{product}-{browser.browser_type.name}.png'))
            print('STICKER_BASELINE_CSP_DRAFT_FAILURE',product,message,flush=True);context.close();continue
        assert not csp,csp
        assert page.evaluate('src=>BenfuwanEditorImage.read(src)',data)==data
        page.route('https://stickers.invalid/**',lambda r:r.fulfill(body=png,content_type='image/png'))
        assert not page.evaluate("url=>new Promise(resolve=>{const image=new Image();image.crossOrigin='anonymous';image.onload=()=>resolve(true);image.onerror=()=>resolve(false);image.src=url+'?cors-test'})",base.replace('127.0.0.1','localhost')+'/static/images/benfuwan-cat-peek.png')
        assert page.evaluate("()=>canvas.getActiveObject().getSrc()") == data
        assert page.evaluate('()=>BenfuwanDesignDraft.saveNow()')
        page.wait_for_timeout(1000)
        page.screenshot(path=str(evidence/f'after-{product}-{browser.browser_type.name}.png'))
        def snapshot():
            return page.evaluate("async()=>({canvas:JSON.stringify(canvas.toDatalessJSON(CUSTOM_PROPS)),history:historyIndex,draft:JSON.stringify(await idbGet(BenfuwanDesignDraft.key))})")
        for failure,attempts in (('missing',1),('decode',1),('network',2)):
            mode[0]=failure;before=snapshot();count=len(requests)
            assert not page.evaluate('url=>addStickerImage(url)',remote)
            assert snapshot()==before,(failure,'mutated canvas/history/draft')
            assert len(requests)-count==attempts,(failure,requests[count:])
            assert 'Load failed' not in page.locator('.toast').inner_text()
        # Actual offline mode; no route fulfillment to bypass the browser network.
        context.set_offline(True);before=snapshot()
        assert not page.evaluate("()=>addStickerImage('/static/images/benfuwan-cat-peek.png?offline-sticker')")
        after=snapshot();assert after==before,[k for k in before if before[k]!=after[k]];context.set_offline(False)
        mode[0]='retry';count=len(requests)
        assert page.evaluate('url=>addStickerImage(url)',remote);assert len(requests)-count==2
        # Rapid concurrent attempts commit once; delayed completion after navigation never inserts.
        mode[0]='hold';page.evaluate('url=>{window.loadingSticker=addStickerImage(url)}',remote)
        poll(page,"()=>document.getElementById('sticker-load-status').textContent==='貼紙載入中…'")
        assert not page.evaluate('url=>addStickerImage(url)',remote)
        before=page.evaluate('canvas.getObjects().length');held.pop().fulfill(body=png,content_type='image/png')
        assert page.evaluate('()=>loadingSticker');assert page.evaluate('canvas.getObjects().length')==before+1
        page.evaluate('url=>{window.loadingSticker=addStickerImage(url)}',remote)
        page.wait_for_timeout(100);page.evaluate("()=>navigate('page-home')")
        held.pop().fulfill(body=png,content_type='image/png');assert not page.evaluate('()=>loadingSticker')
        assert page.evaluate('canvas.getObjects().length')==before+1
        page.evaluate("()=>navigate('page-editor')");mode[0]='ok'
        if product=='camera_film':
            assert page.evaluate('()=>BenfuwanDesignDraft.saveNow()');page.wait_for_timeout(1000)
            mode[0]='hold';before_timeout=snapshot();count=len(requests)
            assert not page.evaluate('url=>addStickerImage(url)',remote)
            assert len(requests)-count==2 and snapshot()==before_timeout
            assert '逾時' in page.locator('.toast').inner_text()
            for route in held:
                try:route.fulfill(body=png,content_type='image/png')
                except Exception:pass  # The bounded fetch has already aborted.
            held.clear();mode[0]='ok'
        # Existing legacy URL-based designs freeze through the same origin proxy.
        assert page.evaluate("async src=>{const d=await BenfuwanDraftStore.pack({canvasJson:{objects:[{type:'image',src}]}});return Object.keys(d.assets).length===1}",remote)
        # Transform/delete/undo/redo using actual editor commands.
        page.evaluate("()=>{canvas.setActiveObject(canvas.getObjects().find(o=>o.role==='sticker'));openAdjustSheet()}")
        page.locator('#object-scale-number').fill('150');page.locator('#object-scale-number').press('Enter')
        page.locator('#angle-number').fill('27');page.locator('#angle-number').press('Enter')
        page.evaluate('()=>{nudgeActive(3,2);closeSheets();recordHistory();window.savedSticker=canvas.getActiveObject().toObject()}')
        count=page.evaluate('canvas.getObjects().length');page.evaluate('deleteActive()')
        assert page.evaluate('canvas.getObjects().length')==count-1
        page.evaluate('undoCanvas()');poll(page,'()=>!restoringHistory');assert page.evaluate('canvas.getObjects().length')==count
        page.evaluate('redoCanvas()');poll(page,'()=>!restoringHistory');assert page.evaluate('canvas.getObjects().length')==count-1
        page.evaluate('undoCanvas()');poll(page,'()=>!restoringHistory')
        page.evaluate('openStickerSheet()');page.locator('[data-editable-sticker-category]').click()
        mode[0]='decode';before_text=page.evaluate('canvas.getObjects().length')
        page.get_by_role('button',name='測試文字貼紙',exact=True).click()
        poll(page,"()=>document.getElementById('sticker-load-status')?.textContent.includes('無法解碼')")
        assert page.evaluate('canvas.getObjects().length')==before_text
        assert page.get_by_role('button',name='測試文字貼紙',exact=True).is_enabled()
        mode[0]='ok';page.get_by_role('button',name='測試文字貼紙',exact=True).click()
        poll(page,"()=>canvas.getObjects().filter(o=>o.editableStickerInstanceId).length===2")
        assert page.evaluate("()=>canvas.getObjects().find(o=>o.role==='editable-sticker-bg').getSrc()") == data
        assert page.evaluate('()=>BenfuwanDesignDraft.saveNow()');key=page.evaluate('BenfuwanDesignDraft.key')
        before=page.evaluate('canvas.getObjects().length')
        page.reload(wait_until='domcontentloaded');poll(page,"()=>window.BenfuwanFrontHomeV1?.isCatalogReady()")
        assert page.evaluate('key=>BenfuwanDesignDraft.continueEditing(key)',key)
        assert page.evaluate('canvas.getObjects().length')==before
        page.evaluate('async()=>{await openPreview();await confirmDesignToCart()}')
        assert page.evaluate('cartItem.draftKey')==key
        meta=page.evaluate('cartItem.productionMeta');assert meta['dpi']==720,meta
        encoded=page.evaluate('cartItem.printBase64').split(',',1)[1]
        output=Image.open(io.BytesIO(base64.b64decode(encoded))).convert('RGBA');assert output.getextrema()[3][0]==0
        page.evaluate('async()=>await BenfuwanDraftCart.edit(cartItem)')
        poll(page,"()=>document.getElementById('page-editor').classList.contains('active')&&canvas.getObjects().length>0")
        assert page.evaluate('canvas.getObjects().length')==before
        assert not errors,errors
        print('STICKER_LOADING_OK',browser.browser_type.name,product,'CSP proxy bytes errors retries offline rapid undo draft cart 720 alpha',flush=True)
        context.close()


if __name__=='__main__':
    suite=runpy.run_path(str(ROOT/'.github/tests/test_ai_editor_webkit.py'))
    server=suite['ServerThread']();server.start()
    try:
        with suite['sync_playwright']() as p:
            browser=getattr(p,os.environ.get('BROWSER_ENGINE','webkit')).launch()
            try:sticker_loading_test(browser,f"http://127.0.0.1:{suite['BROWSER_TEST_PORT']}",suite['poll'])
            finally:browser.close()
    finally:server.close()
