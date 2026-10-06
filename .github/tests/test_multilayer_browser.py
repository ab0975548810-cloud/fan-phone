"""Author a real 30-layer template, apply/edit/reset/draft/order it in both engines."""
import base64
import copy
import io
import json
import os
import tempfile
import uuid
from pathlib import Path
from PIL import Image,ImageDraw


def png(color='#f47ea8'):
    im=Image.new('RGBA',(512,256),(0,0,0,0));d=ImageDraw.Draw(im);d.rounded_rectangle((12,12,500,244),radius=25,fill=color)
    out=io.BytesIO();im.save(out,'PNG');return out.getvalue()


def multilayer_browser_test(browser,base,poll):
    import app as app_module
    from commerce_patch import _sync_skus
    original={name:getattr(app_module,name) for name in ('DATA_FILE','TEMPLATES_FILE','ASSETS_FILE')}
    static=Path(app_module.__file__).parent/'static';fixtures=static/'__pycache__';fixtures.mkdir(exist_ok=True)
    asset=fixtures/('multi-'+uuid.uuid4().hex+'.png');mask=fixtures/('mask-'+uuid.uuid4().hex+'.png');asset.write_bytes(png())
    im=Image.new('RGBA',(200,400),(0,0,0,0));draw=ImageDraw.Draw(im);draw.rounded_rectangle((10,10,189,389),radius=22,fill='black');draw.ellipse((18,18,58,58),fill=(0,0,0,0));im.save(mask)
    asset_url='/static/__pycache__/'+asset.name;mask_url='/static/__pycache__/'+mask.name
    materials=Path(app_module.MATERIAL_DIR);materials.mkdir(exist_ok=True);before=set(materials.iterdir())
    with tempfile.TemporaryDirectory() as directory:
        try:
            for name,file in (('DATA_FILE','shop.json'),('TEMPLATES_FILE','templates.json'),('ASSETS_FILE','assets.json')):setattr(app_module,name,str(Path(directory)/file))
            shop=copy.deepcopy(app_module.DEFAULT_SHOP_DATA);model=shop['models'][0];style=shop['styles'][0];style_id=style['id']
            model['name']='iPhone 13';ids=[model['id'],'multilayer-17-pro','multilayer-17-pro-max'];shop['models']=[copy.deepcopy(model) for _ in ids]
            for m,identity,name,w,h in zip(shop['models'],ids,['iPhone 13','iPhone 17 Pro','iPhone 17 Pro Max'],[70,71.63,77.6],[140,149.61,160.7]):
                m.update(id=identity,name=name,status=True,case_profiles={style_id:{'preview_mask_img':mask_url,'print_line_img':mask_url,'print_w':w,'print_h':h,'print_x':12,'print_y':13,'print_angle':90}})
            shop['styles']=[style];app_module.local_save_json(app_module.DATA_FILE,shop)
            app_module.local_save_json(app_module.TEMPLATES_FILE,{'templates':[],'categories':['全部','熱門']})
            assets=copy.deepcopy(app_module.DEFAULT_ASSETS);assets['editable_stickers']=[{'id':'multilayer-dialog','name':'圖層對話框','imageSrc':asset_url,'textArea':{'x':.15,'y':.2,'width':.7,'height':.45},'defaultTextStyle':{'text':'模板文字','fontFamily':'jf-openhuninn','fontSize':80,'minFontSize':18,'fontWeight':'400','fontStyle':'normal','fill':'#603c48','stroke':None,'strokeWidth':0,'textAlign':'center','charSpacing':0,'lineHeight':1.2}}]
            app_module.local_save_json(app_module.ASSETS_FILE,assets)
            # Public caches must follow fixture data, not the preceding test workspace.
            import security_perf
            security_perf._CACHE.clear()
            admin=browser.new_page(viewport={'width':1180,'height':900})
            admin.on('pageerror',lambda e:print('MULTILAYER_ADMIN_ERROR',str(e),flush=True))
            admin.goto(base+'/admin')
            if '/login' in admin.url:
                if not admin.locator('input[name=password]').is_visible():admin.locator('#password-toggle').click()
                admin.locator('input[name=password]').fill('fan123');admin.locator('form button[type=submit]').click();admin.wait_for_url('**/admin')
            admin.locator('.nav button[data-view=templates]').click();assert not admin.evaluate('!!window.__benfuwanTemplateStackReady')
            admin.locator('#view-templates .titlebar button').filter(has_text='建立模板').click()
            poll(admin,"() => !!window.visualCanvas && !!document.getElementById('multilayer-enable')")
            assert admin.locator('#multilayer-enable').is_checked()
            admin.locator('#bf-tpl-bg-btn-v3').click();admin.locator('#bf-tpl-bg-transparent-v3').click()
            assert admin.evaluate("visualCanvas.getObjects().find(o=>o.isTplBg).fill")=='rgba(0,0,0,0)'
            admin.locator('#bf-tpl-bg-white-v3').click();admin.locator('#bf-tpl-bg-close-v3').click()
            assert admin.evaluate("visualCanvas.getObjects().find(o=>o.isTplBg).fill")=='#ffffff'
            admin.locator('#tpl-name').fill('Multi-layer 30')
            files=[{'name':f'layer-{i}.png','mimeType':'image/png','buffer':png('#f47ea8' if i%2 else '#9ac8e5')} for i in range(14)]
            admin.locator('#multilayer-files').set_input_files(files)
            poll(admin,'() => visualCanvas.getObjects().filter(o=>o.type===\'image\').length===14',timeout=60000)
            for _ in range(12):admin.locator('#bf-tpl-text-v3').click()
            poll(admin,"() => visualCanvas.getObjects().filter(o=>o.type==='textbox').length===12")
            admin.locator('#bf-tpl-slot-v3').click()
            admin.get_by_role('button',name='加入文字貼紙',exact=True).click();admin.get_by_role('button',name='圖層對話框',exact=True).click()
            poll(admin,'() => visualCanvas.getObjects().length===30')
            # Source authoring layout is deliberately spread across the canvas.
            admin.evaluate("""async()=>{
              let image=0,text=0;
              for(const o of visualCanvas.getObjects()){
                if(o.isTplBg)continue;
                if(o.editableStickerInstanceId)continue;
                if(o.isSlot){o.set({left:tplW*.72,top:tplH*.74,width:tplW*.22,height:tplH*.18,scaleX:1,scaleY:1,strokeWidth:0});o.setPositionByOrigin(new fabric.Point(tplW*.72,tplH*.74),'center','center');continue;}
                if(o.type==='image'){
                  const index=image++;o.set({scaleX:tplW*.11/o.width,scaleY:tplW*.11/o.width,angle:index===3?27:0});o.setPositionByOrigin(new fabric.Point(tplW*(.14+.17*(index%5)),tplH*(.24+.1*Math.floor(index/5))),'center','center');
                }else if(o.type==='textbox'){
                  const index=text++;o.set({text:'Layer '+index,layerName:'Layer '+index,fontSize:8,width:tplW*.3});o.setPositionByOrigin(new fabric.Point(tplW*(index%2?.72:.25),tplH*(.48+.065*Math.floor(index/2))),'center','center');
                }
                o.setCoords();
              }
              const pair=BenfuwanEditableSticker.pair(visualCanvas,visualCanvas.getObjects().find(o=>o.editableStickerInstanceId));
              pair.bg.set({left:tplW*.3,top:tplH*.9,scaleX:tplW*.4/pair.bg.width,scaleY:tplW*.4/pair.bg.width});await BenfuwanEditableSticker.rehydrate(visualCanvas);
              visualCanvas.requestRenderAll();
            }""")
            # Lock an image above another image to test transparent hit-through.
            info=admin.evaluate("""()=>{const images=visualCanvas.getObjects().filter(o=>o.type==='image'&&!o.editableStickerInstanceId);const lower=images[0],upper=images[1];upper.setPositionByOrigin(lower.getCenterPoint(),'center','center');upper.setCoords();return {lower:lower.layerId,upper:upper.layerId,rotated:images[3].layerId,tools:images.slice(4,9).map(o=>o.layerId)}}""")
            image_tools_regression(admin,poll,info)
            admin.locator('#bf-tpl-layers-btn-v3').click()
            for label,flag in (('Layer 10','canEdit'),('Layer 11','canRotate')):
                # Resolve the row by the actual editable layer label.
                layer_id=admin.evaluate("label=>visualCanvas.getObjects().find(o=>o.layerName===label).layerId",label)
                row=admin.locator(f'.multi-admin-layer[data-layer-id="{layer_id}"]')
                row.locator('summary').click();row.locator(f'[data-permission={flag}]').uncheck()
            admin.locator(f'.multi-admin-layer[data-layer-id="{info["upper"]}"] [data-locked]').check()
            assert admin.locator(f'.multi-admin-layer[data-layer-id="{info["upper"]}"] [data-permission=canMove]').is_disabled()
            admin.route('**/api/admin/save_templates',lambda route:route.fulfill(status=503,content_type='application/json',body='{"status":"error"}'))
            admin.locator('#template-modal .mf button').filter(has_text='儲存').click()
            poll(admin,"() => document.getElementById('bf-product-message')?.textContent.includes('模板儲存失敗')")
            assert admin.locator('#bf-product-message').is_visible()
            assert admin.locator('#template-modal').is_visible() and admin.locator('#tpl-name').input_value()=='Multi-layer 30'
            assert admin.locator('#template-modal .mf button').filter(has_text='儲存').is_enabled()
            admin.unroute('**/api/admin/save_templates')
            admin.locator('#template-modal .mf button').filter(has_text='儲存').click()
            poll(admin,"() => !document.getElementById('template-modal').classList.contains('show')",timeout=60000)
            data=app_module.cloud_get_json('templates',app_module.TEMPLATES_FILE,app_module.DEFAULT_TEMPLATES);tpl=data['templates'][0]
            assert tpl['layer_contract_version']=='multilayer-v1' and len(tpl['objects_json']['objects'])==30
            assert all(not o.get('filters') and not o.get('__bfAdjust') for o in tpl['objects_json']['objects'])
            baked=next(o for o in tpl['objects_json']['objects'] if o['layerId']==info['lower'])
            assert baked['src'].endswith('.png') and baked['src']!=admin.evaluate('__beforeBakeSource')
            with Image.open(Path(app_module.__file__).parent/baked['src'].lstrip('/')) as image:
                assert image.size==(512,256) and image.convert('RGBA').getpixel((0,0))[3]==0
                assert image.convert('RGBA').getpixel((256,128))!=Image.open(io.BytesIO(png('#9ac8e5'))).convert('RGBA').getpixel((256,128))
            assert len({o['layerId'] for o in tpl['objects_json']['objects']})==30
            original_layers=copy.deepcopy(tpl['objects_json']['objects'])
            legacy_image_tools_regression(admin,poll)
            admin.close()
            page=browser.new_page(viewport={'width':390,'height':844},has_touch=True,is_mobile=True)
            page.on('dialog',lambda dialog:dialog.accept())
            page.on('pageerror',lambda e:print('MULTILAYER_FRONT_ERROR',str(e),flush=True))
            page.goto(base);poll(page,"() => !!window.BenfuwanMultilayer && typeof shopData!=='undefined' && shopData.models.length===3")
            # An image-only template still needs a font manifest without having
            # previously selected any text or loaded a FontFace.
            image_only=page.evaluate("""async()=>{const c=new fabric.Canvas(null,{width:200,height:400});c.add(new fabric.Rect({width:20,height:20,strokeWidth:0,fill:'#ffccdd'}));try{return await BenfuwanEditableSticker.serialize(c,{modelId:'fixture',styleId:'fixture',printW:70,printH:140});}finally{c.dispose();}}""")
            assert image_only['fontHashes'] and len(image_only['objects'])==1
            page.evaluate("""args=>{ctx={...ctx,modelId:args.model,styleId:args.style,printW:70,printH:140,maskUrl:args.mask,printLineUrl:args.mask};navigate('page-editor');initCanvas();return new Promise(resolve=>applyTemplate(args.template,resolve));}""",{'model':ids[0],'style':style_id,'mask':mask_url,'template':tpl})
            assert page.evaluate('canvas.getObjects().length')==30
            selected=page.evaluate("""()=>{const out=[];for(const o of canvas.getObjects()){if(!o.locked&&o.role!=='slot-guide'&&o.role!=='editable-sticker-text'){canvas.setActiveObject(o);out.push(canvas.getActiveObject().layerInstanceId)}}return out;}""")
            assert len(selected)>=25 and len(set(selected))==len(selected)
            assert page.evaluate("canvas.getObjects().filter(o=>o.locked).every(o=>!o.selectable&&!o.evented)")
            page.evaluate("canvas.setActiveObject(canvas.getObjects().find(o=>o.text==='Layer 10'));openTextSheet()")
            assert not page.locator('#sheet-text').evaluate("e=>e.classList.contains('show')")
            rotation=page.evaluate("() => {const o=canvas.getObjects().find(o=>o.text==='Layer 11');canvas.setActiveObject(o);changeAngle(90);return o.angle;}")
            assert rotation==0
            # Real click hits the lower image through the locked foreground image.
            point=page.evaluate("""id=>{canvas.discardActiveObject();const o=canvas.getObjects().find(o=>o.templateLayerId===id),p=o.getCenterPoint(),r=canvas.upperCanvasEl.getBoundingClientRect();return {x:r.x+p.x*r.width/canvas.width,y:r.y+p.y*r.height/canvas.height}}""",info['lower'])
            page.mouse.click(point['x'],point['y']);assert page.evaluate('canvas.getActiveObject()?.templateLayerId')==info['lower']
            page.evaluate('() => new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
            point=page.evaluate("""()=>{const p=canvas.getActiveObject().getCenterPoint(),r=canvas.upperCanvasEl.getBoundingClientRect();return {x:r.x+p.x*r.width/canvas.width,y:r.y+p.y*r.height/canvas.height}}""")
            old=page.evaluate('({left:canvas.getActiveObject().left,top:canvas.getActiveObject().top})')
            page.mouse.move(point['x'],point['y']);page.mouse.down();page.mouse.move(point['x']+12,point['y']+10,steps=8);page.mouse.up()
            assert abs(page.evaluate('canvas.getActiveObject().left')-old['left'])>3
            single_touch_drag_test(page,browser)
            gesture_test(page,browser)
            # Duplication and deletion operate on the selected layer only.
            before_count=page.evaluate('canvas.getObjects().length');page.evaluate('duplicateActive()')
            poll(page,f'() => canvas.getObjects().length==={before_count+1}')
            duplicate=page.evaluate('({id:canvas.getActiveObject().layerInstanceId,source:canvas.getActiveObject().templateLayerId,from:canvas.getActiveObject().duplicateOf})')
            assert duplicate['id']!=duplicate['from'] and duplicate['source']==info['lower']
            page.evaluate('flipActive(\'x\');bringForward();sendBackward();deleteActive()');assert page.evaluate('canvas.getObjects().length')==30
            page.evaluate('openLayerSheet()');row=page.locator('.multi-layer-row').filter(has=page.locator('.layer-name',has_text='Layer 0')).first
            assert row.count()==1;row.get_by_role('button',name='顯示／隱藏').click()
            assert page.evaluate("canvas.getObjects().find(o=>o.text==='Layer 0').visible") is False
            row=page.locator('.multi-layer-row').filter(has=page.locator('.layer-name',has_text='Layer 0')).first;row.get_by_role('button',name='顯示／隱藏').click()
            previous=page.evaluate("canvas.getObjects().indexOf(canvas.getObjects().find(o=>o.text==='Layer 0'))")
            row.get_by_role('button',name='上移',exact=True).click()
            assert page.evaluate("canvas.getObjects().indexOf(canvas.getObjects().find(o=>o.text==='Layer 0'))")==previous+1
            row=page.locator('.multi-layer-row').filter(has=page.locator('.layer-name',has_text='Layer 0')).first
            row.get_by_role('button',name='下移',exact=True).click()
            assert page.evaluate("canvas.getObjects().indexOf(canvas.getObjects().find(o=>o.text==='Layer 0'))")==previous
            page.evaluate('closeSheets()')
            page.evaluate("canvas.setActiveObject(canvas.getObjects().find(o=>o.text==='Layer 0'));openTextSheet()")
            page.locator('#text-input').fill('客人可改模板文字')
            page.locator('#text-size').fill('14')
            page.locator('#sheet-text button').filter(has_text='套用到選取文字').click()
            poll(page,"() => canvas.getObjects().some(o=>o.text==='客人可改模板文字')")
            page.evaluate('closeSheets()')
            # A customer-owned upload survives reset; filled slot returns to its placeholder.
            page.locator('#photo-input').set_input_files({'name':'customer.png','mimeType':'image/png','buffer':png('#92d0a4')})
            poll(page,"() => canvas.getObjects().some(o=>o.originalName==='customer.png')")
            page.evaluate("() => {activeSlotGuide=canvas.getObjects().find(o=>o.role==='slot-guide');}")
            page.locator('#slot-input').set_input_files({'name':'slot.png','mimeType':'image/png','buffer':png('#79bcde')})
            poll(page,"() => canvas.getObjects().some(o=>o.role==='slot-photo')")
            assert page.evaluate("canvas.getObjects().find(o=>o.role==='slot-photo').sourceSize.width")==512
            page.evaluate("() => BenfuwanMultilayerFront.resetTemplate()")
            poll(page,"() => canvas.getObjects().some(o=>o.role==='slot-guide') && !canvas.getObjects().some(o=>o.role==='slot-photo')")
            assert page.evaluate("canvas.getObjects().filter(o=>o.originalName==='customer.png').length")==1
            initial=page.evaluate("canvas.templateState.initial.map(o=>({id:o.templateLayerId,angle:o.angle,geometry:o.normalizedGeometry}))")
            current=page.evaluate("canvas.getObjects().filter(o=>o.templateLayerId).map(o=>({id:o.templateLayerId,angle:o.angle,geometry:o.normalizedGeometry}))")
            assert [(o['id'],o['angle']) for o in initial]==[(o['id'],o['angle']) for o in current]
            assert all(abs(a['geometry'][k]-b['geometry'][k])<1e-9 for a,b in zip(initial,current) for k in ('x','y','width','height')),(initial,current)
            # Edit paired Textbox then save/reload and draft restore, not a PNG bake.
            page.evaluate("""async()=>{const bg=canvas.getObjects().find(o=>o.role==='editable-sticker-bg');await BenfuwanEditableSticker.update(canvas,bg,{text:'可以編輯',fontSize:60});recordHistory();await BenfuwanDesignDraft.saveNow();}""")
            page.reload();poll(page,"() => window.BenfuwanDesignDraft?.state().prompt==='ready'");page.locator('#home-design-card').click()
            poll(page,"() => document.getElementById('page-editor').classList.contains('active') && canvas?.templateState?.initial.length===30")
            assert page.evaluate("canvas.getObjects().find(o=>o.role==='editable-sticker-text').text")=='可以編輯'
            assert page.evaluate("canvas.getObjects().find(o=>o.isTplBg).selectable") is False
            mapped=[]
            for identity,w,h in zip(ids,[70,71.63,77.6],[140,149.61,160.7]):
                mapped.append(page.evaluate("""async args=>{ctx={...ctx,modelId:args.id,printW:args.w,printH:args.h};initCanvas();await applyTemplate(args.tpl);return canvas.getObjects().map(o=>({id:o.templateLayerId,g:BenfuwanMultilayer.geometry(o,canvas),angle:o.angle,area:o.textArea,order:canvas.getObjects().indexOf(o)}));}""",{'id':identity,'w':w,'h':h,'tpl':tpl}))
            for a,b in zip(mapped[0],mapped[1]):
                assert a['id']==b['id'] and a['angle']==b['angle'] and a['order']==b['order'] and a.get('area')==b.get('area')
                assert all(abs(a['g'][key]-b['g'][key])<.0002 for key in ('x','y','width','height')),(a,b)
            for a,b in zip(mapped[0],mapped[2]):assert all(abs(a['g'][key]-b['g'][key])<.0002 for key in ('x','y','width','height')),(a,b)
            for w,h in ((390,844),(768,1024),(1180,900)):
                page.set_viewport_size({'width':w,'height':h});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            contract=page.evaluate('async()=>{await ensureCanvasFonts();return await BenfuwanMultilayer.serialize(canvas,ctx)}')
            assert len(contract['objects'])==29 and len(contract['emptyTemplateSlots'])==1
            uploaded=page.evaluate('async()=>{window.__multiOrder=await BenfuwanDesignSources.prepare(await BenfuwanMultilayer.serialize(canvas,ctx));return __multiOrder}')
            assert len(json.dumps(uploaded))<1500000 and 'base64' not in json.dumps(uploaded)
            assert len({o['layerInstanceId'] for o in uploaded['objects']})==29
            page.evaluate('BenfuwanDesignSources.release(__multiOrder)')
            page.evaluate('openPreview()')
            poll(page,"() => window.BenfuwanProductionHQ?.state().status==='ready'",timeout=60000)
            page.evaluate("""()=>{window.__cartStore=idbSet;window.idbSet=function(key,value){const result=__cartStore.apply(this,arguments);if(key==='cart'){if(window.__firstPublishedLayerCount===undefined)window.__firstPublishedLayerCount=value.designJson.objects.length;return Promise.all([result,new Promise(resolve=>setTimeout(resolve,200))]);}return result;}}""")
            page.locator('#page-preview button').filter(has_text='加入購物車').click()
            poll(page,"() => cartItem?.designJson?.layer_contract_version==='multilayer-v1'")
            assert page.evaluate('__firstPublishedLayerCount')==29
            page.evaluate('() => BenfuwanMultilayerFront.whenCartReady()')
            page.evaluate('window.idbSet=__cartStore')
            assert page.evaluate('cartItem.designJson.objects.length')==29
            assert page.evaluate('cartItem.productionMeta?.dpi')==720
            # Submit the actual Fabric-generated contract through #71 receipts,
            # then rebuild in Print Center. The CI DB/storage are local, and
            # prepare never sends a vendor task or starts physical printing.
            body=page.evaluate("""async()=>({idempotency_key:'multilayer-'+crypto.randomUUID(),model_id:cartItem.modelId,style_id:cartItem.styleId,color_name:cartItem.colorName||'透明',customer_name:'Multilayer browser fixture',quantity:1,payment_method:'現金',print_file:cartItem.printBase64,mockup_file:cartItem.mockupBase64,design_json:await BenfuwanDesignSources.prepare(cartItem.designJson)})""")
            response=page.request.post(base+'/api/create_order',data=body)
            assert response.status==200,response.text()
            order_id=response.json()['order_id'];order=app_module.commerce.store.order(order_id)
            assert order['design_json']['layerSeal'] and len(order['design_json']['objects'])==29
            assert 'base64' not in json.dumps(order['design_json'])
            job=app_module.print_center.prepare(order_id,'multilayer-browser-'+uuid.uuid4().hex)
            rendered=Image.open(io.BytesIO(app_module.print_center._download_artwork(job['artwork_path'])))
            assert rendered.size==(round(77.6*720/25.4),round(160.7*720/25.4))
            assert abs(rendered.info['dpi'][0]-720)<.05 and job['state']=='PREPARED'
            assert job['artwork_path']!=order['print_path']
            page.evaluate("""()=>new Promise(resolve=>applyTemplate({id:'legacy-v1',model_id:ctx.modelId,template_version:1,slots:[],objects_json:{version:'5.3.1',objects:[{type:'rect',left:25,top:35,width:40,height:30,fill:'#79bcde',strokeWidth:0,role:'sticker'}]}},resolve))""")
            assert page.evaluate("!canvas.templateState && !canvas.layer_contract_version && canvas.getObjects().every(o=>!o.templateLayerId)")
            page.close()
            print('MULTILAYER_30_LAYERS_AUTHORING_LOCK_HIT_THROUGH_TOUCH_DUPLICATE_RESET_PHOTO_DRAFT_NORMALIZED_ORDER_RESPONSIVE_OK')
        finally:
            for name,value in original.items():setattr(app_module,name,value)
            for file in set(materials.iterdir())-before:file.unlink(missing_ok=True)
            asset.unlink(missing_ok=True);mask.unlink(missing_ok=True)
            import security_perf
            security_perf._CACHE.clear()


def single_touch_drag_test(page,browser):
    point=page.evaluate("""()=>{const p=canvas.getActiveObject().getCenterPoint(),r=canvas.upperCanvasEl.getBoundingClientRect();return {x:r.x+p.x*r.width/canvas.width,y:r.y+p.y*r.height/canvas.height,left:canvas.getActiveObject().left}}""")
    if browser.browser_type.name=='chromium':
        cdp=page.context.new_cdp_session(page)
        cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':point['x'],'y':point['y'],'id':1}]})
        for step in range(1,6):cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':point['x']+step*3,'y':point['y']+step*2,'id':1}]})
        cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]});cdp.detach()
    else:
        page.evaluate("""p=>{const el=canvas.upperCanvasEl;
          function emit(type,dx,dy){const touch={identifier:1,target:el,clientX:p.x+dx,clientY:p.y+dy,pageX:p.x+dx+scrollX,pageY:p.y+dy+scrollY};const touches=type==='touchend'?[]:[touch],event=new Event(type,{bubbles:true,cancelable:true});Object.defineProperties(event,{touches:{value:touches},targetTouches:{value:touches},changedTouches:{value:[touch]}});el.dispatchEvent(event);}
          emit('touchstart',0,0);for(let i=1;i<=5;i++)emit('touchmove',i*3,i*2);emit('touchend',15,10);
        }""",point)
    assert abs(page.evaluate('canvas.getActiveObject().left')-point['left'])>3


def image_tools_regression(page,poll,info):
    uploads=[];cloud=[]
    page.on('request',lambda request:uploads.append(request.post_data_buffer) if '/api/admin/upload_image' in request.url else None)
    page.route('**/api/ai/remove-background',lambda route:(cloud.append(route.request.url),route.fulfill(status=500,content_type='application/json',body='{"status":"error"}')))
    def select(identity):
        page.evaluate("id=>{visualCanvas.setActiveObject(visualCanvas.getObjects().find(o=>o.layerId===id));visualCanvas.requestRenderAll();}",identity)
        poll(page,"() => document.getElementById('bf-tpl-objectbar').classList.contains('bf-imgtools')")
    def source(identity):return page.evaluate("id=>visualCanvas.getObjects().find(o=>o.layerId===id).publicSrc",identity)
    crop,replacement,ai,outline,expand=info['tools']
    select(crop);before=source(crop);page.locator('[data-bf-imgtool=crop]').click();page.locator('#bf-imgtool-panel [data-ratio="1"]').click()
    poll(page,f"() => visualCanvas.getObjects().find(o=>o.layerId==='{crop}').publicSrc !== '{before}'")
    assert source(crop).endswith('.png') and page.evaluate("id=>visualCanvas.getObjects().find(o=>o.layerId===id).width",crop)==256
    select(replacement);before=source(replacement);page.locator('#bf-it-replace-file').set_input_files({'name':'replacement.png','mimeType':'image/png','buffer':png('#a1d0f0')})
    poll(page,f"() => visualCanvas.getObjects().find(o=>o.layerId==='{replacement}').publicSrc !== '{before}'")
    assert source(replacement).endswith('.png')
    select(ai);before=source(ai);page.evaluate('() => bfAdminRemoveBackground()')
    assert source(ai).endswith('.png') and source(ai)!=before and cloud==[]
    select(outline);before=source(outline);page.locator('.bf-outline-v2-btn').click();page.locator('#bf-outline-v2-panel [data-style=white]').click()
    poll(page,f"() => visualCanvas.getObjects().find(o=>o.layerId==='{outline}').publicSrc !== '{before}'")
    assert source(outline).endswith('.png')
    # The existing smart-expand entry remains hidden; exercise its handler
    # without enabling any UI feature or calling a cloud/vendor provider.
    select(expand);before=source(expand);page.evaluate('() => document.getElementById("bf-tpl-expand-v4").onclick()')
    assert source(expand).endswith('.png') and source(expand)!=before
    select(info['lower']);page.evaluate('window.__beforeBakeSource=visualCanvas.getActiveObject().publicSrc')
    page.locator('[data-bf-imgtool=adjust]').click();poll(page,"() => !!document.getElementById('bf-it-bright').dataset.bfFilterFix")
    for name,start,end in (('bright',.5,.68),('contrast',.5,.57),('sat',.5,.57),('blur',0,.05)):
        slider=page.locator('#bf-it-'+name);slider.scroll_into_view_if_needed();box=slider.bounding_box();x=box['x'];y=box['y']+box['height']/2
        page.mouse.move(x+box['width']*start,y);page.mouse.down();page.mouse.move(x+box['width']*end,y,steps=6);page.mouse.up()
    assert page.evaluate("visualCanvas.getActiveObject().filters.length")==4
    assert uploads and all(b'name="source_contract"' in body and b'multilayer-v1' in body and b'content-type: image/png' in body.lower() for body in uploads)
    page.locator('#bf-imgtool-panel [data-close]').click()
    page.unroute('**/api/ai/remove-background')


def legacy_image_tools_regression(page,poll):
    calls=[]
    def capture(request):
        if '/api/admin/upload_image' in request.url:calls.append(request.post_data_buffer)
    page.on('request',capture)
    page.evaluate('window.__legacyPreviousCanvas=visualCanvas')
    page.locator('#view-templates .titlebar button').filter(has_text='建立模板').click()
    poll(page,"() => visualCanvas!==window.__legacyPreviousCanvas && document.getElementById('multilayer-enable')?.checked")
    page.locator('#multilayer-enable').uncheck()
    assert page.evaluate('BenfuwanAdminMultilayer.enabled()') is False
    page.locator('#bf-tpl-image-file-v3').set_input_files({'name':'legacy.png','mimeType':'image/png','buffer':png()})
    poll(page,"() => visualCanvas.getObjects().filter(o=>o.type==='image').length===1")
    assert page.evaluate('visualCanvas.getActiveObject().publicSrc.endsWith(".webp")')
    assert b'name="source_contract"' not in calls[-1]
    before=page.evaluate('visualCanvas.getActiveObject().publicSrc')
    poll(page,"() => document.getElementById('bf-tpl-objectbar').classList.contains('bf-imgtools')")
    page.locator('[data-bf-imgtool=crop]').click();page.locator('#bf-imgtool-panel [data-ratio="1"]').click()
    poll(page,f"() => visualCanvas.getActiveObject().publicSrc!=='{before}'")
    assert page.evaluate('visualCanvas.getActiveObject().publicSrc.endsWith(".webp")')
    assert b'name="source_contract"' not in calls[-1] and b'content-type: image/webp' in calls[-1].lower()
    page.remove_listener('request',capture)
    page.evaluate('closeModal("template-modal")')


def gesture_test(page,browser):
    before=page.evaluate('({scale:canvas.getActiveObject().scaleX,angle:canvas.getActiveObject().angle})')
    if browser.browser_type.name=='chromium':
        cdp=page.context.new_cdp_session(page)
        box=page.locator('#main-canvas').bounding_box();x=box['x']+box['width']*.3;y=box['y']+box['height']*.3
        points=lambda d,dy:[{'x':x-d,'y':y-dy,'id':1},{'x':x+d,'y':y+dy,'id':2}]
        cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':points(15,0)})
        cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':points(24,12)})
        cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]});cdp.detach()
    else:
        # WebKit Playwright has no CDP multi-touch transport. Dispatch native DOM
        # DOM touch-shaped input through the public canvas handler. Linux WebKit
        # disallows Touch constructors; no test directly changes transforms.
        page.evaluate("""()=>{const el=canvas.upperCanvasEl,r=el.getBoundingClientRect(),x=r.x+r.width*.3,y=r.y+r.height*.3;
          function emit(type,d,dy){const points=d?[{identifier:1,target:el,clientX:x-d,clientY:y-dy,pageX:x-d+scrollX,pageY:y-dy+scrollY},{identifier:2,target:el,clientX:x+d,clientY:y+dy,pageX:x+d+scrollX,pageY:y+dy+scrollY}]:[],event=new Event(type,{bubbles:true,cancelable:true});Object.defineProperties(event,{touches:{value:points},targetTouches:{value:points},changedTouches:{value:points}});el.dispatchEvent(event);}
          emit('touchstart',15,0);emit('touchmove',24,12);emit('touchend',0,0);
        }""")
    after=page.evaluate('({scale:canvas.getActiveObject().scaleX,angle:canvas.getActiveObject().angle})')
    assert after['scale']>before['scale']*1.3 and abs(after['angle']-before['angle'])>20,(before,after)


if __name__=='__main__':
    # Run the focused feature first in CI, then retain the full existing suite.
    # Reuse its isolated local server/middleware fixture, never production.
    import runpy,time
    from playwright.sync_api import sync_playwright
    helper=runpy.run_path(str(Path(__file__).with_name('test_ai_editor_webkit.py')))
    server=helper['ServerThread']();server.start();time.sleep(.8)
    try:
        with sync_playwright() as playwright:
            browser=getattr(playwright,os.environ.get('BROWSER_ENGINE','webkit')).launch()
            try:multilayer_browser_test(browser,f"http://127.0.0.1:{helper['BROWSER_TEST_PORT']}",helper['poll'])
            finally:browser.close()
    finally:server.close()
