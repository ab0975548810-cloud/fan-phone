"""Real Fabric paired transforms, editing, persistence and high-res text in both engines."""
import base64
import io
from PIL import Image,ImageDraw


def png():
    image=Image.new('RGBA',(1024,512),(0,0,0,0));d=ImageDraw.Draw(image);d.rounded_rectangle((20,20,1004,492),radius=60,fill='white',outline='#df87a8',width=8);out=io.BytesIO();image.save(out,'PNG');return out.getvalue()


def editable_sticker_test(browser,base,poll):
    page=browser.new_page(viewport={'width':390,'height':844},has_touch=True,is_mobile=True)
    page.on('pageerror',lambda error:print('EDITABLE_PAGE_ERROR',str(error),flush=True))
    page.route('**/static/test-dialog.png',lambda r:r.fulfill(status=200,body=png(),content_type='image/png'))
    def catalog(route):
        response=route.fetch();payload=response.json();data=payload.get('data',payload)
        for model in data.get('models',[]):
            model.setdefault('case_profiles',{})[data['styles'][0]['id']]={'preview_mask_img':'/static/test-dialog.png','print_line_img':'/static/test-dialog.png','print_w':71.63,'print_h':149.61,'print_x':12,'print_y':13,'print_angle':90}
        route.fulfill(response=response,json=payload)
    page.route('**/api/shop_data',catalog)
    page.goto(base+'/')
    poll(page,"() => !!window.BenfuwanEditableSticker && typeof fabric!=='undefined' && typeof shopData!=='undefined' && shopData.models?.length")
    page.evaluate("""()=>{
      const mask=document.createElement('canvas');mask.width=200;mask.height=400;const g=mask.getContext('2d');g.fillStyle='#000';g.fillRect(10,10,180,380);g.clearRect(15,15,35,35);
      window.__editableMask=mask.toDataURL();
      ctx={...ctx,modelId:shopData.models[0].id,styleId:shopData.styles[0].id,printW:71.63,printH:149.61,printLineUrl:window.__editableMask,maskUrl:window.__editableMask};
      navigate('page-editor');initCanvas();
      assetsData.editable_stickers=[{id:'test-dialog',name:'測試對話框',imageSrc:'/static/test-dialog.png',textArea:{x:.15,y:.2,width:.7,height:.45},defaultTextStyle:{text:'輸入文字',fontFamily:'jf-openhuninn',fontSize:80,minFontSize:18,fill:'#000000',stroke:'#fff',strokeWidth:0,textAlign:'center',charSpacing:0,lineHeight:1.2,fontWeight:'400',fontStyle:'normal'}}];
      openStickerSheet();
    }""")
    page.locator('[data-editable-sticker-category]').click();page.get_by_role('button',name='測試對話框',exact=True).click()
    poll(page,"() => canvas.getObjects().filter(o=>o.editableStickerInstanceId).length===2")
    state=page.evaluate("""()=>{const p=BenfuwanEditableSticker.pair(canvas,canvas.getActiveObject());window.__pair=p;return {types:[p.bg.type,p.text.type],roles:[p.bg.role,p.text.role],same:p.bg.editableStickerInstanceId===p.text.editableStickerInstanceId}}""")
    assert state['types']==['image','textbox'] and state['roles']==['editable-sticker-bg','editable-sticker-text'] and state['same'],state
    page.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
    # Actual pointer drag on the frame, then Fabric's real transform event paths.
    point=page.evaluate("""()=>{const r=canvas.upperCanvasEl.getBoundingClientRect(),p=__pair.bg.getCenterPoint();return {x:r.x+p.x*r.width/canvas.width,y:r.y+p.y*r.height/canvas.height}}""")
    before=page.evaluate('({bg:__pair.bg.getCenterPoint(),text:__pair.text.getCenterPoint()})')
    diagnostic=page.evaluate("""p=>{window.__dragEvents=[];canvas.on('mouse:down',e=>__dragEvents.push({event:'down',role:e.target?.role,pointer:e.pointer}));canvas.on('object:moving',e=>__dragEvents.push({event:'moving',role:e.target?.role}));const r=canvas.upperCanvasEl.getBoundingClientRect();const hit=document.elementFromPoint(p.x,p.y);return {point:p,rect:{x:r.x,y:r.y,width:r.width,height:r.height},hit:hit?.outerHTML.slice(0,300),zoom:canvas.getZoom(),scrollY:window.scrollY,editorTop:document.getElementById('page-editor').getBoundingClientRect().top,dockStyle:{height:document.getElementById('editable-text-tools').getBoundingClientRect().height,max:getComputedStyle(document.getElementById('editable-text-tools')).maxHeight},offset:canvas._offset,objects:canvas.getObjects().map(o=>({role:o.role,left:o.left,top:o.top,selectable:o.selectable,evented:o.evented,lockX:o.lockMovementX,lockY:o.lockMovementY}))}}""",point)
    page.mouse.move(point['x'],point['y']);page.mouse.down();page.mouse.move(point['x']+15,point['y']+10,steps=8);page.mouse.up()
    after=page.evaluate('({bg:__pair.bg.getCenterPoint(),text:__pair.text.getCenterPoint()})')
    assert abs(after['bg']['x']-before['bg']['x'])>2,(after,diagnostic,page.evaluate('__dragEvents'))
    assert abs((after['bg']['x']-before['bg']['x'])-(after['text']['x']-before['text']['x']))<.01,(before,after)
    page.evaluate("""()=>{__pair.bg.set({scaleX:.19,scaleY:.23,angle:27});canvas.fire('object:scaling',{target:__pair.bg});canvas.fire('object:rotating',{target:__pair.bg});recordHistory();}""")
    transformed=page.evaluate('({bg:[__pair.bg.scaleX,__pair.bg.scaleY,__pair.bg.angle],text:[__pair.text.scaleX,__pair.text.scaleY,__pair.text.angle]})')
    assert transformed['bg']==transformed['text']==[.19,.23,27]
    page.locator('#editable-text-tools [data-edit-text]').click()
    assert page.evaluate('__pair.text.isEditing && canvas.getActiveObject()===__pair.text')
    page.keyboard.insert_text('客製文字')
    page.evaluate('__pair.text.exitEditing()')
    assert page.evaluate('__pair.text.text')=='客製文字'
    form=page.locator('#editable-text-tools form');form.locator('[name=text]').fill('繁體中文\n可愛文字')
    form.locator('[name=fontFamily]').select_option('NotoSansTC');form.locator('[name=fontSize]').fill('76');form.locator('[name=strokeWidth]').fill('2');form.locator('[name=textAlign]').select_option('left');form.locator('[name=charSpacing]').fill('50');form.locator('[name=lineHeight]').fill('1.4');form.locator('[name=fill]').fill('#112233');form.locator('[name=stroke]').fill('#ffffff');form.locator('[name=fontWeight]').check();form.locator('[name=fontStyle]').check();form.get_by_role('button',name='套用文字').click()
    poll(page,"() => __pair.text.fontFamily==='NotoSansTC' && __pair.text.text==='繁體中文\\n可愛文字'")
    style=page.evaluate('({font:__pair.text.fontFamily,fill:__pair.text.fill,stroke:__pair.text.stroke,width:__pair.text.strokeWidth,align:__pair.text.textAlign,spacing:__pair.text.charSpacing,height:__pair.text.lineHeight,weight:__pair.text.fontWeight,style:__pair.text.fontStyle})')
    assert style==dict(font='NotoSansTC',fill='#112233',stroke='#ffffff',width=2,align='left',spacing=50,height=1.4,weight='700',style='italic'),style
    fitted=page.evaluate("""async()=>{await BenfuwanEditableSticker.update(canvas,__pair.bg,{text:'長文字測試'.repeat(12),fontSize:100});return {size:__pair.text.fontSize,max:__pair.text.requestedFontSize,height:__pair.text.height+__pair.text.strokeWidth*2,safe:__pair.bg.height*__pair.text.textArea.height}}""")
    assert fitted['size']<fitted['max'] and fitted['height']<=fitted['safe']+.01,fitted
    overflow=page.evaluate("""async()=>{const old=__pair.text.text;try{await BenfuwanEditableSticker.update(canvas,__pair.bg,{text:'超長'.repeat(1000)});return false}catch(e){return e.message.includes('文字過多')&&__pair.text.text===old}}""")
    assert overflow
    old_id=page.evaluate('__pair.bg.editableStickerInstanceId');page.evaluate('async()=>{await duplicateActive();window.__duplicate=BenfuwanEditableSticker.pair(canvas,canvas.getActiveObject())}')
    assert page.evaluate('__duplicate.bg.editableStickerInstanceId')!=old_id
    assert page.evaluate('canvas.getObjects().filter(o=>o.editableStickerInstanceId).length')==4
    page.evaluate('canvas.remove(__duplicate.text)');assert page.evaluate('canvas.getObjects().filter(o=>o.editableStickerInstanceId).length')==2
    # Draft/history JSON round-trip preserves independent editable objects.
    page.evaluate('recordHistory();BenfuwanDesignDraft.saveNow()')
    poll(page,"() => idbGet('design-draft-v1').then(d=>d?.canvasJson?.objects?.some(o=>o.editableStickerInstanceId))")
    page.evaluate("""async()=>{window.__saved=canvas.toJSON(CUSTOM_PROPS);canvas.clear();await new Promise(r=>canvas.loadFromJSON(__saved,r));await BenfuwanEditableSticker.rehydrate(canvas);__pair=BenfuwanEditableSticker.pair(canvas,canvas.getObjects()[0]);}""")
    assert page.evaluate('__pair.text.type')=='textbox'
    page.reload()
    poll(page,"() => window.BenfuwanDesignDraft?.state().prompt==='ready'")
    page.locator('#home-design-card').click()
    poll(page,"() => document.getElementById('page-editor').classList.contains('active') && canvas?.getObjects().some(o=>o.editableStickerInstanceId)")
    page.evaluate("() => {window.__pair=BenfuwanEditableSticker.pair(canvas,canvas.getObjects().find(o=>o.editableStickerInstanceId));const mask=document.createElement('canvas');mask.width=200;mask.height=400;const g=mask.getContext('2d');g.fillStyle='#000';g.fillRect(10,10,180,380);g.clearRect(15,15,35,35);window.__editableMask=mask.toDataURL();}")
    assert page.evaluate('__pair.text.type')=='textbox'
    page.evaluate("""async()=>{await BenfuwanEditableSticker.update(canvas,__pair.bg,{text:'重繪文字測試',fontFamily:'jf-openhuninn',fill:'#000000',strokeWidth:0,fontWeight:'400',fontStyle:'normal',fontSize:80});__pair.bg.set({left:canvas.width/2,top:canvas.height/2,angle:0,scaleX:.19,scaleY:.19});BenfuwanEditableSticker.sync(__pair.bg,__pair.text);window.__contract=await BenfuwanEditableSticker.serialize(canvas,ctx);}""")
    contract=page.evaluate('BenfuwanOrderPayload.compactDesign({...__contract,padding:"x".repeat(1600000)})')
    assert contract['render_contract_version']=='editable-text-v1' and contract['objects'][0]['src'].startswith('data:image/png;base64,')
    assert contract['objects'][1]['textArea']==dict(x=.15,y=.2,width=.7,height=.45)
    assert page.evaluate("""async()=>{const old={modelId:ctx.modelId,styleId:ctx.styleId,printBase64:'existing',designJson:{keep:true}};cartItem=old;ctx.printBase64=null;ctx.productionMeta=null;await confirmDesignToCart();return cartItem===old&&cartItem.designJson.keep===true;}""")
    production=page.evaluate("""async()=>{const front=__pair.text._textLines.map(a=>a.join(''));const high=await BenfuwanEditableSticker.render(__contract,__editableMask,2030,4241);const low=await BenfuwanEditableSticker.render(__contract,__editableMask,200,418);return {front,layouts:high.layouts,png:high.png,low:low.png}}""")
    assert production['layouts'][0]['lines']==production['front']
    high=Image.open(io.BytesIO(base64.b64decode(production['png'].split(',')[1]))).convert('RGBA');low=Image.open(io.BytesIO(base64.b64decode(production['low'].split(',')[1]))).convert('RGBA').resize(high.size,Image.Resampling.BILINEAR)
    assert high.size==(2030,4241) and high.getpixel((0,0))[3]==0
    # Text grayscale transition band is thinner when rendered from Textbox at HQ.
    def softness(im):
        mid=dark=0
        for r,g,b,a in im.getdata():
            if a>250 and abs(r-g)<3 and abs(g-b)<3:
                if 40<r<210:mid+=1
                elif r<40:dark+=1
        return mid/max(1,dark)
    assert softness(high)<softness(low), (softness(high),softness(low))
    # Rehydration after an arbitrary model template transform uses normalized area.
    result=page.evaluate("""async()=>{__pair.bg.set({scaleX:.13,scaleY:.13,angle:38});await BenfuwanEditableSticker.rehydrate(canvas);return {area:__pair.text.textArea,angle:__pair.text.angle,scale:__pair.text.scaleX}}""")
    assert result['area']==dict(x=.15,y=.2,width=.7,height=.45) and result['angle']==38 and result['scale']==.13
    for width,height in ((390,844),(768,1024),(1180,900)):
        page.set_viewport_size(dict(width=width,height=height));assert page.locator('#editable-text-tools').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
    template_results=page.evaluate("""async()=>{
      const sourceModel=ctx.modelId,styleId=ctx.styleId,tpl={id:'editable-universal',model_id:'*',universal:true,template_version:3,reference_model_id:sourceModel,reference_style_id:styleId,source_print_w:ctx.printW,source_print_h:ctx.printH,source_canvas_w:canvas.width,source_canvas_h:canvas.height,objects_json:canvas.toJSON(CUSTOM_PROPS),slots:[]};
      const results=[];
      for(const [id,name,w,h] of [['editable-iphone-13','iPhone 13',70,140],['editable-iphone-17','iPhone 17 Pro',71.63,149.61]]){
        const profile={preview_mask_img:__editableMask,print_line_img:__editableMask,print_w:w,print_h:h,print_x:12,print_y:13,print_angle:90};
        shopData.models.push({id,name,status:true,case_profiles:{[styleId]:profile}});ctx={...ctx,modelId:id,printW:w,printH:h,printLineUrl:__editableMask,maskUrl:__editableMask};
        initCanvas();await new Promise(resolve=>applyTemplate(tpl,resolve));await BenfuwanEditableSticker.rehydrate(canvas);
        __pair=BenfuwanEditableSticker.pair(canvas,canvas.getObjects().find(o=>o.editableStickerInstanceId));
        results.push({model:name,area:__pair.text.textArea,widthRatio:__pair.text.width/__pair.bg.width,font:__pair.text.fontFamily});
      }
      return results;
    }""")
    assert [r['model'] for r in template_results]==['iPhone 13','iPhone 17 Pro']
    assert all(r['area']==dict(x=.15,y=.2,width=.7,height=.45) and abs(r['widthRatio']-.7)<.01 for r in template_results),template_results
    page.evaluate('canvas.setActiveObject(__pair.text);deleteActive()');assert page.evaluate('canvas.getObjects().filter(o=>o.editableStickerInstanceId).length')==0
    page.evaluate("() => addStickerImage('/static/test-dialog.png')");poll(page,"() => canvas.getObjects().some(o=>o.role==='sticker' && !o.editableStickerInstanceId)")
    page.close()
    print('EDITABLE_STICKER_PAIR_EDIT_FIT_DRAFT_CONTRACT_REAL_HQ_FONTS_RESPONSIVE_OK')
    editable_admin_test(browser,base,poll,catalog)


def editable_admin_test(browser,base,poll,catalog):
    page=browser.new_page(viewport={'width':1180,'height':900})
    page.on('dialog',lambda dialog:dialog.accept())
    page.route('**/static/test-dialog.png',lambda r:r.fulfill(status=200,body=png(),content_type='image/png'))
    page.route('**/api/shop_data',catalog)
    assets={'stickers':[],'categories':['全部'],'editable_stickers':[]};writes=[]
    page.route('**/api/assets?*',lambda route:route.fulfill(status=200,json={'status':'success','data':assets,'version':'asset-fixture'}))
    page.route('**/api/admin/upload_image',lambda route:route.fulfill(status=200,json={'status':'success','url':'/static/test-dialog.png'}))
    def save(route):
        body=route.request.post_data_json;writes.append(body)
        assets['editable_stickers']=[{**body,'id':'admin-dialog','intrinsicSize':{'width':1024,'height':512}}]
        route.fulfill(status=200,json={'status':'success','version':'asset-fixture-2','data':assets})
    page.route('**/api/admin/editable_sticker',save)
    page.goto(base+'/admin')
    if '/login' in page.url:
        if not page.locator('input[name=password]').is_visible():page.locator('#password-toggle').click()
        page.locator('input[name=password]').fill('fan123');page.locator('form button[type=submit]').click();page.wait_for_url('**/admin')
    page.locator('.nav button[data-view=assets]').click()
    page.get_by_role('button',name='建立文字貼紙',exact=True).click()
    dialog=page.locator('.editable-config-dialog')
    dialog.locator('[name=name]').fill('管理者對話框')
    dialog.locator('[name=image]').set_input_files({'name':'dialog.png','mimeType':'image/png','buffer':png()})
    poll(page,"() => document.querySelector('.editable-config-stage img').naturalWidth===1024 && !document.querySelector('.editable-config-dialog [type=submit]').disabled")
    box=dialog.locator('.editable-config-area').bounding_box();page.mouse.move(box['x']+15,box['y']+15);page.mouse.down();page.mouse.move(box['x']+35,box['y']+25,steps=6);page.mouse.up()
    assert float(dialog.locator('[name=area-x]').input_value())>.15
    dialog.locator('[name=fontSize]').fill('80');dialog.locator('[name=minFontSize]').fill('18')
    dialog.get_by_role('button',name='儲存',exact=True).click();poll(page,"() => !document.querySelector('.editable-config-dialog').open")
    assert len(writes)==1 and writes[0]['expected_version']=='asset-fixture'
    assert writes[0]['textArea']['x']>.15 and writes[0]['defaultTextStyle']['fontFamily']=='jf-openhuninn'
    assert assets['stickers']==[]
    assert not page.evaluate("!!window.__benfuwanTemplateStackReady")
    page.locator('.nav button[data-view=templates]').click()
    page.locator('#view-templates .titlebar button').filter(has_text='建立模板').click()
    poll(page,"() => !!window.__benfuwanTemplateStackReady && !!window.visualCanvas")
    page.get_by_role('button',name='加入文字貼紙',exact=True).click()
    page.locator('dialog').filter(has=page.get_by_role('button',name='管理者對話框',exact=True)).get_by_role('button',name='管理者對話框',exact=True).click()
    poll(page,"() => visualCanvas.getObjects().filter(o=>o.editableStickerInstanceId).length===2")
    saved=page.evaluate("""()=>{const raw=visualCanvas.toJSON(['isSlot','isTplBg','slotId']);return raw.objects.filter(o=>o.editableStickerInstanceId)}""")
    assert [o['role'] for o in saved]==['editable-sticker-bg','editable-sticker-text']
    assert saved[1]['textArea']==writes[0]['textArea']
    page.evaluate("() => {const bg=visualCanvas.getObjects().find(o=>o.role==='editable-sticker-bg');visualCanvas.setActiveObject(bg);addText();}")
    assert page.evaluate("visualCanvas.getActiveObject().isEditing===true")
    page.keyboard.insert_text('模板文字')
    page.evaluate('visualCanvas.getActiveObject().exitEditing()')
    for width,height in ((390,844),(768,1024),(1180,900)):
        page.set_viewport_size(dict(width=width,height=height));assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    page.close()
    print('EDITABLE_ADMIN_NORMALIZED_AREA_CAS_LAZY_TEMPLATE_METADATA_EDIT_OK')
