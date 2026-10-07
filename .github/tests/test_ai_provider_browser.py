"""Actual mode-button/pointer paths, with deterministic same-origin SDK fixture.

Mock only the inference transport: normalize real user strokes, composite and
replace real Fabric objects through the production code. Never call paid APIs.
"""
import base64
import io
import json
import tempfile
from PIL import Image, ImageDraw


SDK = """
export class FilesetResolver { static async forVisionTasks(url){window.__mpWasm=url;return {}} }
export class InteractiveSegmenter {
  static async createFromOptions(v,opts){
    (window.__mpAttempts ||= []).push(opts);
    if(window.__mpInitFailure==='both' || (window.__mpInitFailure==='cpu' && opts.baseOptions.delegate==='CPU'))throw new Error('fixture initialization failed');
    window.__mpOptions=opts;return new InteractiveSegmenter();
  }
  setImage(image){this.image=image}
  segment(strokes){
    window.__mpStrokes=strokes;
    const w=200,h=150,data=new Float32Array(w*h);
    for(let y=0;y<h;y++)for(let x=0;x<w;x++){
      let value=x>20&&x<180&&y>10&&y<140?1:0;
      for(const s of strokes)if(s.brushMode===2)for(const p of s.point)if(Math.hypot(x/w-p.x,y/h-p.y)<.1)value=0;
      data[y*w+x]=value;
    }
    return {width:w,height:h,getAsFloat32Array:()=>data,close:()=>{window.__mpClosed=true}};
  }
}
"""


def image_url(width=2400, height=1800):
    image=Image.new('RGBA',(width,height),'white')
    ImageDraw.Draw(image).rectangle((100,100,width-100,height-100),fill='#cd628b')
    buf=io.BytesIO();image.save(buf,'PNG')
    return 'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()


def delegate_fallback_test(browser,base,poll):
    for failure,expected_delegates in ((None,['CPU']),('cpu',['CPU',None]),('both',['CPU',None])):
        page=browser.new_page()
        page.route('**/vendor/mediapipe/vision_bundle.mjs*',lambda r:r.fulfill(status=200,body=SDK,content_type='text/javascript'))
        page.goto(base+'/')
        poll(page,'() => !!window.BenfuwanAiTools && !!window.BenfuwanAiRemoveV2')
        result=page.evaluate("""async(failure)=>{
          window.__mpInitFailure=failure;
          const image=document.createElement('canvas');image.width=200;image.height=150;
          image.getContext('2d').fillRect(0,0,200,150);
          try{
            const blob=await BenfuwanAiTools.segment(image,[{mode:'positive',points:[{x:.5,y:.5}]}]);
            return {ok:blob.type==='image/png',attempts:window.__mpAttempts};
          }catch(error){return {ok:false,error:error.message,attempts:window.__mpAttempts};}
        }""",failure)
        attempts=result['attempts']
        assert [a['baseOptions'].get('delegate') for a in attempts]==expected_delegates,result
        assert all(a['baseOptions']['modelAssetPath']=='/vendor/mediapipe/interactive_segmentation.task' for a in attempts),result
        if len(attempts)==2:assert 'delegate' not in attempts[1]['baseOptions'],result
        assert result['ok']==(failure!='both'),result
        if failure=='both':assert result['error']=='fixture initialization failed',result
        page.close()
    print('MEDIAPIPE_CPU_SUCCESS_DEFAULT_DELEGATE_FALLBACK_DOUBLE_FAILURE_OK')


def real_mediapipe_test(browser,base,poll):
    # No SDK/model/WASM stubs: exercise the production same-origin loader.
    page=browser.new_page()
    page.set_default_timeout(180000)
    page.goto(base+'/')
    poll(page,'() => !!window.BenfuwanAiTools && !!document.querySelector(".bf-home-hero-art")?.naturalWidth')
    result=page.evaluate("""async()=>{
      const image=document.querySelector('.bf-home-hero-art');await image.decode();
      const blob=await BenfuwanAiTools.segment(image,[
        {mode:'positive',points:[{x:.5,y:.4}]},
        {mode:'negative',points:[{x:.03,y:.03}]}
      ]);
      const stats=await BenfuwanAiRemoveV2.validate(blob);
      return {type:blob.type,bytes:blob.size,width:stats.width,height:stats.height,
        originalWidth:image.naturalWidth,originalHeight:image.naturalHeight,alpha:stats.transparentRatio};
    }""")
    assert result['type']=='image/png' and result['bytes']>0,result
    assert result['width']==result['originalWidth'] and result['height']==result['originalHeight'],result
    assert 0<result['alpha']<1,result
    page.close()
    print('REAL_MEDIAPIPE_SAME_ORIGIN_INITIALIZATION_SEGMENTATION_OK',result)


def ai_provider_browser_test(browser,base,poll):
    delegate_fallback_test(browser,base,poll)
    page=browser.new_page(viewport={'width':390,'height':844},has_touch=True)
    page.on('dialog',lambda dialog:dialog.accept())
    requests=[]
    output=Image.new('RGBA',(128,96),(0,0,0,0));ImageDraw.Draw(output).rectangle((10,10,110,80),fill='#cd628b')
    stream=io.BytesIO();output.save(stream,'PNG')
    def cloud(route):
        requests.append(route.request.post_data_buffer.decode('latin1'))
        route.fulfill(status=200,body=stream.getvalue(),content_type='image/png')
    page.route('**/api/ai/remove-background',cloud)
    page.route('**/vendor/mediapipe/vision_bundle.mjs*',lambda r:r.fulfill(status=200,body=SDK,content_type='text/javascript'))
    page.goto(base+'/')
    poll(page,"() => !!window.BenfuwanAiTools && !!window.BenfuwanAiRemoveV2 && typeof fabric!=='undefined'")
    assert page.evaluate('async()=>{await WebAssembly.compile(new Uint8Array([0,97,115,109,1,0,0,0]));return true}')
    page.evaluate("() => {navigate('page-editor');initCanvas();editorHasSession=true}")

    def add_photo(admin=False):
        return page.evaluate("""({src,admin})=>new Promise(resolve=>fabric.Image.fromURL(src,img=>{
          const c=admin?visualCanvas:canvas;
          c.clear();img.set({left:100,top:120,originX:'center',originY:'center',scaleX:.07,scaleY:.06,angle:23,opacity:.7,role:'photo',slotId:'test-slot',slotMeta:{keep:true},originalName:'provider-test.png'});
          img.clipPath=new fabric.Rect({width:2000,height:1500});
          c.add(img);c.setActiveObject(img);c.requestRenderAll();
          window.__providerOld=img;window.__providerCanvas=c;resolve();
        }))""",dict(src=image_url(),admin=admin))

    def geometry():
        return page.evaluate("""()=>{const c=window.__providerCanvas,o=c.getActiveObject();return {center:o.getCenterPoint(),width:o.width,height:o.height,sx:o.scaleX,sy:o.scaleY,angle:o.angle,opacity:o.opacity,slot:o.slotId,meta:o.slotMeta,index:c.getObjects().indexOf(o),clip:o.clipPath===window.__providerOld.clipPath}}""")

    def open_menu(admin=False):
        if admin:page.locator('#bf-provider-test-entry').click()
        else:
            page.evaluate("() => openSheet('sheet-upload')")
            page.locator('#ai-remove-btn').click()
            assert page.locator('[data-ai-mode]').count()==0
            return
        assert page.locator('[data-ai-mode]').all_text_contents()==['自動去背人物、寵物、商品','點選摳圖自己指定要留下的區域','印花摳圖Logo、插畫、衣服／商品上的圖案']

    def interactive(admin=False):
        add_photo(admin);before=geometry();count=len(requests)
        if admin:
            open_menu(True);page.locator('[data-ai-mode="interactive"]').click()
        else:
            # Retained underlying feature; no customer-facing mode chooser.
            page.evaluate("() => {void removeBackgroundForActive('interactive')}")
        target=page.locator('[data-ai-strokes]');target.wait_for()
        box=target.bounding_box()
        # Real touch tap plus real pointer drag; no dispatch/evaluate fake strokes.
        page.touchscreen.tap(box['x']+box['width']*.45,box['y']+box['height']*.35)
        page.locator('[data-brush="negative"]').click()
        page.mouse.move(box['x']+box['width']*.65,box['y']+box['height']*.5)
        page.mouse.down();page.mouse.move(box['x']+box['width']*.72,box['y']+box['height']*.55,steps=6);page.mouse.up()
        page.locator('[data-ai-apply]').click()
        poll(page,"() => window.__providerCanvas.getActiveObject()!==window.__providerOld")
        after=geometry()
        for key in ('width','height','sx','sy','angle','opacity','slot','meta','index'):assert after[key]==before[key],(key,before,after)
        assert after['clip'] and after['center']==before['center'],after
        assert len(requests)==count
        strokes=page.evaluate('window.__mpStrokes')
        assert [s['brushMode'] for s in strokes]==[1,2] and len(strokes[1]['point'])>=2,strokes
        assert all(s['isCompleted'] for s in strokes)
        assert page.evaluate("window.__mpOptions.baseOptions.modelAssetPath")=='/vendor/mediapipe/interactive_segmentation.task'
        assert page.evaluate('window.__mpClosed')
        alpha=page.evaluate("""()=>{const o=window.__providerCanvas.getActiveObject(),c=document.createElement('canvas');c.width=o.width;c.height=o.height;const g=c.getContext('2d');g.drawImage(o.getElement(),0,0);return {outside:g.getImageData(0,0,1,1).data[3],inside:g.getImageData(1000,700,1,1).data[3],excluded:g.getImageData(1600,950,1,1).data[3]}}""")
        assert alpha['outside']==0 and alpha['inside']==255 and alpha['excluded']==0,alpha

    add_photo();open_menu()
    poll(page,"() => window.__providerCanvas.getActiveObject()!==window.__providerOld")
    assert requests==[],requests # confident edge-connected background remains local.
    add_photo();before=geometry();page.evaluate("() => {void removeBackgroundForActive('stamp')}")
    poll(page,"() => window.__providerCanvas.getActiveObject()!==window.__providerOld")
    assert len(requests)==1 and 'name="mode"\r\n\r\nstamp' in requests[-1]
    after=geometry();assert after['width']==2400 and after['height']==1800
    assert after['center']==before['center'] and after['angle']==23 and after['clip']
    interactive()
    page.goto(base+'/admin');
    if '/login' in page.url:
        if not page.locator('input[name=password]').is_visible():
            page.locator('#password-toggle').click()
        page.locator('input[name=password]').fill('fan123');page.locator('form button[type=submit]').click();page.wait_for_url('**/admin')
    page.evaluate('async() => {await window.benfuwanEnsureTemplateEditor();await ensureFabric()}')
    page.evaluate("""()=>{
      const el=document.createElement('canvas');el.id='provider-admin-canvas';document.body.append(el);
      visualCanvas=new fabric.Canvas(el,{width:300,height:500});
      const b=document.createElement('button');b.id='bf-provider-test-entry';b.textContent='AI 摳圖工具';b.onclick=window.bfAdminAiTools;document.body.append(b);
      window.uploadAdminImage=async()=>'/static/test-cutout.png';
    }""")
    add_photo(True);open_menu(True);page.locator('[data-ai-mode="stamp"]').click()
    poll(page,"() => window.__providerCanvas.getActiveObject()!==window.__providerOld")
    assert len(requests)==2 and 'name="mode"\r\n\r\nstamp' in requests[-1]
    interactive(True)
    for width,height in ((390,844),(768,1024),(1180,900)):
        page.set_viewport_size(dict(width=width,height=height));open_menu(True)
        assert page.locator('.bf-ai-tool-dialog').evaluate('(e)=>e.scrollWidth<=e.clientWidth+1')
        page.locator('.bf-ai-tool-dialog [data-close]').click()
    page.close()
    print('AI_PROVIDER_THREE_MODES_REAL_TOUCH_FULL_RES_FABRIC_PRESERVATION_OK')
    front_auto_ux_test(browser,base,poll)
    real_mediapipe_test(browser,base,poll)


def front_auto_ux_test(browser,base,poll):
    # WebKit's ephemeral/private contexts cannot persist IndexedDB Blobs.
    # Use a real temporary browser profile to verify the normal Safari cache
    # path, without replacing IndexedDB or weakening the cache-hit assertion.
    with tempfile.TemporaryDirectory() as profile:
        context=browser.browser_type.launch_persistent_context(profile,
            viewport={'width':390,'height':844},has_touch=True)
        try:
            _front_auto_ux_test(context,base,poll)
        finally:
            context.close()


def _front_auto_ux_test(context,base,poll):
    page=context.new_page()
    diagnostics=[]
    page.on('console',lambda msg:diagnostics.append(msg.text) if msg.type in ('warning','error') else None)
    requests=[]
    def failed_cloud(route):
        requests.append(route.request.post_data_buffer.decode('latin1'))
        route.fulfill(status=502,content_type='application/json',body=json.dumps({
            'msg':'Koukoutu timeout; RunPod BiRefNet provider job=private-job failed'}))
    page.route('**/api/ai/remove-background',failed_cloud)
    page.route('**/api/health',lambda r:r.fulfill(status=200,content_type='application/json',
        body=json.dumps({'ai_background_removal':True,'ai_model':'PRIVATE_PROVIDER_MODEL'})))
    page.goto(base+'/')
    poll(page,"() => !!window.BenfuwanMultilayer && !!window.BenfuwanAiRemoveV2 && typeof fabric!=='undefined'")
    page.evaluate("""() => {
      navigate('page-editor');initCanvas();editorHasSession=true;
      window.__generalCalls=0;window.__chooseCalls=0;
      BenfuwanAiTools.chooseMode=()=>{window.__chooseCalls++;throw Error('Customer must not choose a mode')};
      const original=BenfuwanAiRemoveV2.universalRemoveFromElement;
      BenfuwanAiRemoveV2.universalRemoveFromElement=async(el,opts)=>{
        window.__generalCalls++;
        if(window.__holdGeneral)await new Promise(resolve=>window.__releaseGeneral=resolve);
        return original(el,{...opts,...(window.__forceCloud?{localConfidence:2}:{})});
      };
    }""")

    def add(role='photo',multi=False):
        page.evaluate("""({src,role,multi})=>new Promise(resolve=>fabric.Image.fromURL(src,img=>{
          canvas.clear();
          canvas.add(new fabric.Rect({width:10,height:10,role:'fixture-back'}));
          img.set({left:100,top:120,originX:'center',originY:'center',scaleX:.07,scaleY:.06,
            angle:23,opacity:.7,flipX:true,flipY:true,role,slotId:'slot-1',slotMeta:{keep:true},originalName:'auto.png'});
          img.clipPath=new fabric.Rect({width:2000,height:1500});
          canvas.add(img);canvas.add(new fabric.Rect({width:10,height:10,role:'fixture-front'}));
          if(multi){
            Object.assign(img,{layerId:'layer-1',templateLayerId:'layer-1',layerInstanceId:'instance-1',
              templateApplicationId:'application-1',assetId:'asset-1',templateSlot:role==='slot-photo',
              locked:false,canMove:true,canScale:true,canRotate:true,canDelete:false,canDuplicate:false,canEdit:true});
            canvas.layer_contract_version=BenfuwanMultilayer.VERSION;
            canvas.templateState={id:'template-1',applicationId:'application-1',initial:[img.toObject(BenfuwanMultilayer.PROPS)]};
            BenfuwanMultilayer.update(canvas);
          }
          canvas.setActiveObject(img);canvas.requestRenderAll();syncSelection();
          window.__autoOld=img;resolve();
        }))""",dict(src=image_url(),role=role,multi=multi))

    def snapshot():
        return page.evaluate("""()=>{const o=canvas.getActiveObject();return {
          center:o.getCenterPoint(),width:o.width,height:o.height,sx:o.scaleX,sy:o.scaleY,
          angle:o.angle,flipX:o.flipX,flipY:o.flipY,opacity:o.opacity,role:o.role,slotId:o.slotId,slotMeta:o.slotMeta,
          index:canvas.getObjects().indexOf(o),clip:o.clipPath===window.__autoOld.clipPath,
          layers:Object.fromEntries(BenfuwanMultilayer.PROPS.filter(k=>o[k]!==undefined).map(k=>[k,o[k]]))};}""")

    def click():
        page.evaluate("() => {document.querySelector('#toast').textContent='';openSheet('sheet-upload')}")
        button=page.locator('#ai-remove-btn')
        assert button.inner_text()=='✨ AI 自動去背'
        assert page.locator('#ai-status-text').inner_text()=='自動辨識人物、寵物與商品，產生透明背景'
        assert '點選摳圖' not in page.locator('body').inner_text()
        assert '印花摳圖' not in page.locator('body').inner_text()
        button.click()
        assert page.locator('[data-ai-mode]').count()==0

    add();before=snapshot()
    page.evaluate('() => {window.__holdGeneral=true}')
    click()
    poll(page,'() => !!window.__releaseGeneral')
    assert page.locator('#ai-remove-btn').inner_text()=='AI 正在自動去背…'
    assert page.locator('#busy-text').inner_text()=='AI 正在自動去背…'
    page.evaluate('() => {window.__holdGeneral=false;window.__releaseGeneral()}')
    poll(page,'() => canvas.getActiveObject()!==window.__autoOld')
    assert snapshot()==before
    assert page.locator('#toast').inner_text()=='去背完成 ✓'
    assert page.evaluate('window.__generalCalls')==1 and requests==[]
    # The same source in a photo slot / multilayer uses the validated cache;
    # replacement still traverses real Fabric remove/insert and #72 metadata hooks.
    for role,multi in (('photo',False),('slot-photo',False),('photo',True),('slot-photo',True)):
        add(role,multi);before=snapshot();click()
        poll(page,'() => canvas.getActiveObject()!==window.__autoOld')
        assert snapshot()==before,(role,multi,before,snapshot())
        assert page.evaluate('canvas.getActiveObject().aiCacheHit'),(diagnostics,page.evaluate("async()=>({role:canvas.getActiveObject().role,mode:canvas.getActiveObject().aiRemovalMode,calls:__generalCalls,index:await idbGet('ai-cache-v2-index')})"))
        assert page.locator('#toast').inner_text()=='去背完成 ✓'
    assert page.evaluate('window.__generalCalls')==1
    assert page.evaluate('window.__chooseCalls')==0
    # A late health response must never overwrite the plain customer copy.
    page.evaluate('async() => {await checkBackendStatus()}')
    assert page.locator('#ai-status-text').inner_text()=='自動辨識人物、寵物與商品，產生透明背景'
    for role,multi in (('photo',False),('slot-photo',True)):
        add(role,multi);before=snapshot()
        page.evaluate("""async()=>{
          const key='ai-cache-v4:'+await BenfuwanAiRemoveV2.cacheIdentityFromElement(__autoOld.getElement(),{maxEdge:1200,maxBytes:5.5*1024*1024});
          await idbDel(key);window.__forceCloud=true;
        }""")
        click()
        poll(page,"() => document.querySelector('#toast').textContent==='自動去背暫時無法使用，請稍後再試' && !document.querySelector('#ai-remove-btn').disabled")
        assert page.evaluate('canvas.getActiveObject()===window.__autoOld')
        assert snapshot()==before
        assert page.locator('#ai-remove-btn').is_enabled()
        assert page.locator('#ai-remove-btn').inner_text()=='✨ AI 自動去背'
        body=page.locator('body').inner_text()
        for secret in ('Koukoutu','RunPod','BiRefNet','private-job','PRIVATE_PROVIDER_MODEL'):
            assert secret not in body,secret
    assert len(requests)==2 and all('name="mode"\r\n\r\ngeneral' in r for r in requests)
    page.close()
    print('FRONT_AUTO_SINGLE_ENTRY_NO_CHOOSER_BUSY_CACHE_FULLRES_SLOT_MULTILAYER_FAILURE_SAFE_OK')
