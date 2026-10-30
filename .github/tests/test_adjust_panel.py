"""Adjustment dock: real UI controls, touch events and display/production invariants."""
import base64
import json
import os
import runpy
import subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]


def adjust_panel_test(browser, base, poll):
    evidence = Path(os.environ.get('ADJUST_EVIDENCE_DIR', ROOT / 'artifacts/mobile-adjust'))
    evidence.mkdir(parents=True, exist_ok=True)
    baseline = os.environ.get('ADJUST_BASELINE') == '1'
    for product in ('phone_case', 'camera_film'):
        context = browser.new_context(viewport=dict(width=390, height=844), device_scale_factor=2, has_touch=True)
        page = context.new_page()
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        if baseline:
            for name in ('index.html','static/index-base-20260913.html','static/front-editor-controls-v1.js','static/front-editor-access-v1.js','static/front-multilayer-template-v1.js','static/multilayer-template-core-v1.js'):
                content=subprocess.check_output(['git','show','origin/main:'+name],cwd=ROOT)
                page.route('**/'+('' if name=='index.html' else name)+'?*' if name!='index.html' else base+'/',lambda route,request,body=content:route.fulfill(body=body,content_type='text/html' if b'<!DOCTYPE' in body else 'application/javascript'))
        maskname='film/print.png' if product=='camera_film' else 'preview_masks/iphone14-pro-max-print.png'
        # Use existing audited masks; preserve separate portrait and landscape geometry.
        maskpath=ROOT/'.github/tests/fixtures'/maskname
        if not maskpath.exists():
            maskpath=ROOT/'.github/tests/fixtures/film/print.png'
        mask='data:image/png;base64,'+base64.b64encode(maskpath.read_bytes()).decode()
        preview='data:image/png;base64,'+base64.b64encode(maskpath.with_name(maskpath.name.replace('print','preview')).read_bytes()).decode()
        w,h=(67,47) if product=='camera_film' else (75,150)
        catalog=dict(brands=['測試'],models=[dict(id='adjust',name='鏡頭底膜' if product=='camera_film' else '手機殼',brand='測試',status=True,product_type=product,direct_style_id='style',case_profiles={'style':dict(preview_mask_img=preview,print_line_img=mask,print_w=w,print_h=h,print_x=68,print_y=30,print_angle=0)})],styles=[dict(id='style',name='測試款',product_type=product,status=True,price=490,colors=[] if product=='camera_film' else ['白'])])
        page.route('**/api/shop_data*',lambda r:r.fulfill(json=dict(status='success',version='fixture',data=catalog)))
        page.goto(base,wait_until='domcontentloaded')
        poll(page,"() => catalogState==='ready' && !!window.BenfuwanEditorControls")
        page.evaluate("async () => {await startNewDesign();selectModel(shopData.models[0]);selectStyle(shopData.styles[0]);ctx.colorName='白';await startEditor(false)}")
        poll(page,"() => editorHasSession && !!canvas")
        image='data:image/png;base64,'+base64.b64encode((ROOT/'static/images/benfuwan-cat-peek.png').read_bytes()).decode()
        page.evaluate("url => new Promise(resolve=>fabric.Image.fromURL(url,o=>{const s=canvas.width*.55/o.width;o.set({left:canvas.width/2,top:canvas.height/2,originX:'center',originY:'center',scaleX:s,scaleY:s,role:'sticker'});canvas.add(o);canvas.setActiveObject(o);recordHistory();openAdjustSheet();resolve()}))",image)
        page.wait_for_timeout(450)
        page.evaluate('canvas.renderAll()')
        page.screenshot(path=str(evidence/f"{'before' if baseline else 'after'}-{product}-{browser.browser_type.name}.png"))
        if baseline:
            context.close();continue
        def state():
            return page.evaluate("() => {const o=canvas.getActiveObject();return {x:o.getCenterPoint().x,y:o.getCenterPoint().y,sx:o.scaleX,sy:o.scaleY,angle:o.angle,opacity:o.opacity,index:historyIndex,base:o.bfScaleBaseX,w:canvas.width,h:canvas.height}}")
        def layout():
            page.wait_for_timeout(120)
            result=poll(page,"() => {const a=document.getElementById('canvas-shell').getBoundingClientRect(),b=document.getElementById('sheet-adjust').getBoundingClientRect(),w=document.querySelector('#page-editor>.workspace').getBoundingClientRect();return a.top>=w.top-1&&a.bottom<=b.top+1&&a.right<=innerWidth+1&&a.height>20?{top:a.top,bottom:a.bottom,panel:b.top,workspace:w.top,right:a.right,width:innerWidth,height:a.height}:false}")
            assert result['top']>=result['workspace']-1 and result['bottom']<=result['panel']+1 and result['right']<=result['width']+1 and result['height']>20,result
        def number(selector,value):
            page.locator(selector).fill(str(value));page.locator(selector).press('Enter')
        layout()
        first=state();assert page.locator('#object-scale-number').input_value()=='100'
        if browser.browser_type.name=='chromium':
            session=context.new_cdp_session(page)
            point=page.evaluate("() => {const r=canvas.upperCanvasEl.getBoundingClientRect(),p=canvas.getActiveObject().getCenterPoint();return {x:r.x+p.x*r.width/canvas.width,y:r.y+p.y*r.height/canvas.height}}")
            before=state()
            session.send('Input.dispatchTouchEvent',dict(type='touchStart',touchPoints=[dict(x=point['x'],y=point['y'],id=1)]))
            for delta in (4,8,12):
                session.send('Input.dispatchTouchEvent',dict(type='touchMove',touchPoints=[dict(x=point['x']+delta,y=point['y']+delta,id=1)]))
            session.send('Input.dispatchTouchEvent',dict(type='touchEnd',touchPoints=[]))
            page.wait_for_timeout(250)
            after=state();assert after['x']>before['x'] and after['y']>before['y'] and after['sx']==before['sx'] and after['sy']==before['sy'],(before,after)
            first=state()
        number('#object-scale-number',150)
        second=state();assert abs(second['sx']/first['sx']-1.5)<1e-7 and second['index']==first['index']+1
        assert abs(float(page.locator('#object-scale-range').input_value())-150)<1e-7
        page.evaluate("() => {closeSheets();canvas.discardActiveObject();canvas.setActiveObject(canvas.getObjects().find(o=>o.role==='sticker'));openAdjustSheet()}")
        assert page.locator('#object-scale-number').input_value()=='150'
        for field,bad in (('#object-scale-number',''),('#object-scale-number','oops'),('#object-scale-number','301'),('#opacity-number','101'),('#angle-number','Infinity')):
            before=state();number(field,bad);assert state()==before,(field,bad,state(),before)
        # Numeric draft changes nothing until confirmation.
        before=state();page.locator('#opacity-number').fill('65');assert state()==before
        page.locator('#opacity-number').press('Enter');assert state()['opacity']==.65
        number('#angle-number',27);assert state()['angle']==27
        # Multiple actual pointer moves preview live and commit exactly once.
        before=state();slider=page.locator('#opacity-range');box=slider.bounding_box();y=box['y']+box['height']/2
        page.wait_for_timeout(100)
        pixels=page.evaluate('canvas.lowerCanvasEl.toDataURL()')
        page.mouse.move(box['x']+box['width']*.65,y);page.mouse.down();page.mouse.move(box['x']+box['width']*.35,y,steps=8)
        poll(page,"() => canvas.lowerCanvasEl.toDataURL()!=="+json.dumps(pixels))
        live=state();assert live['opacity']<before['opacity'] and live['index']==before['index'],(before,live)
        page.mouse.up();assert state()['index']==before['index']+1
        page.locator('#bf-adjust-more summary').click()
        number('#position-x',round(first['x']+5,3));number('#position-y',round(first['y']+7,3))
        before=state();page.locator('[onclick="nudgeActive(1,0)"]').click();after=state()
        assert abs(after['x']-before['x']-1)<1e-7 and after['sx']==before['sx'] and after['sy']==before['sy']
        # VisualViewport keyboard resize/scroll simulation: no OS keyboard in Playwright.
        page.locator('#position-y').focus()
        original=state()
        page.evaluate("() => {Object.defineProperty(visualViewport,'height',{configurable:true,value:440});Object.defineProperty(visualViewport,'offsetTop',{configurable:true,value:12});visualViewport.dispatchEvent(new Event('resize'))}")
        layout()
        bounds=page.locator('#position-y').bounding_box();assert bounds['y']>=12 and bounds['y']+bounds['height']<=452,bounds
        page.evaluate("document.querySelector('.toast')?.classList.remove('show')")
        page.screenshot(path=str(evidence/f'keyboard-{product}-{browser.browser_type.name}.png'))
        page.locator('#position-y').press('Enter')
        page.evaluate("() => {delete visualViewport.height;delete visualViewport.offsetTop;visualViewport.dispatchEvent(new Event('resize'))}")
        assert state()==original
        page.locator('#bf-adjust-more summary').click()
        for width,height in ((375,667),(844,390),(1180,900),(390,844)):
            page.set_viewport_size(dict(width=width,height=height));layout();assert state()==original
            page.locator('#bf-adjust-collapse').click();layout();page.locator('#bf-adjust-collapse').click();layout()
        # Two touches, rotation and scale form one undo, preserve both axes.
        page.evaluate("() => {window.adjustTouch=(type,points)=>{const el=canvas.upperCanvasEl;const touches=points.map((p,i)=>({identifier:i+1,target:el,clientX:p[0],clientY:p[1]}));const event=new Event(type,{bubbles:true,cancelable:true});Object.assign(event,{touches,targetTouches:touches,changedTouches:touches});el.dispatchEvent(event);};}")
        before=state()
        page.evaluate("() => {adjustTouch('touchstart',[[100,180],[180,180]]);adjustTouch('touchmove',[[100,180],[180,220]]);adjustTouch('touchmove',[[100,180],[190,230]]);}")
        live=state();assert live['index']==before['index'] and live['sx']>before['sx'] and live['angle']!=before['angle']
        page.evaluate("adjustTouch('touchend',[])")
        after=state();assert after['index']==before['index']+1 and abs(after['sx']/after['sy']-before['sx']/before['sy'])<1e-8
        page.evaluate('undoCanvas()');poll(page,'() => !restoringHistory')
        page.evaluate("() => {canvas.setActiveObject(canvas.getObjects().find(o=>o.role==='sticker'));syncSelection()}")
        restored=state();assert abs(restored['sx']-before['sx'])<.001 and restored['base']==before['base'],(restored,before)
        page.evaluate('redoCanvas()');poll(page,'() => !restoringHistory')
        page.evaluate("() => {canvas.setActiveObject(canvas.getObjects().find(o=>o.role==='sticker'));syncSelection()}")
        # Text uses the same uniform percentage without reflowing its box/font.
        page.evaluate("() => {window.__selectedPhoto=canvas.getActiveObject();const o=new fabric.Textbox('FAN',{width:70,fontSize:18,fontFamily:'jf-openhuninn',role:'text',left:50,top:50});canvas.add(o);canvas.setActiveObject(o);recordHistory();openAdjustSheet()}")
        text_before=page.evaluate("() => {const o=canvas.getActiveObject();return [o.width,o.height,o.fontSize,o.scaleX/o.scaleY]}")
        number('#object-scale-number',200)
        assert page.evaluate("() => {const o=canvas.getActiveObject();return [o.width,o.height,o.fontSize,o.scaleX/o.scaleY]}")==text_before
        page.evaluate("() => {const o=canvas.getActiveObject();o.set({scaleX:10,scaleY:10});canvas.fire('object:scaling',{target:o});}")
        assert page.locator('#object-scale-number').input_value()=='300'
        assert page.locator('#object-scale-range').input_value()=='300'
        page.evaluate("() => {canvas.remove(canvas.getActiveObject());canvas.setActiveObject(window.__selectedPhoto);recordHistory();syncSelection()}")
        # User locks and immutable template policy cannot be bypassed by events.
        for lock in ('user','template','slot'):
            page.evaluate("kind => {const o=canvas.getActiveObject();if(kind==='user')o.bfUserLocked=true;else {o.bfUserLocked=false;o.templateLayerId='protected';o.templateSlot=kind==='slot';if(kind==='slot')o.role='slot-photo';canvas.layer_contract_version='multilayer-v1';canvas.templateState={initial:[{templateLayerId:'protected',locked:kind==='slot',canMove:false,canScale:false,canRotate:false,canEdit:false}]};}BenfuwanEditorControls.applyUserLock(o);syncSelection()}",lock)
            before=state()
            page.evaluate("() => {changeOpacity(10);changeAngle(80);nudgeActive(2,3);const r=document.getElementById('object-scale-range');r.value=200;r.dispatchEvent(new Event('input'));adjustTouch('touchstart',[[100,180],[180,180]]);adjustTouch('touchmove',[[100,180],[220,220]]);adjustTouch('touchend',[]);}")
            assert state()==before,(lock,before,state())
        page.evaluate("() => {const o=canvas.getActiveObject();o.role='sticker';delete o.templateLayerId;delete o.templateSlot;delete o.locked;o.bfUserLocked=false;delete canvas.templateState;delete canvas.layer_contract_version;BenfuwanEditorControls.applyUserLock(o);closeSheets()}")
        # Production data and pixels are identical across opening/reflow/closing.
        page.evaluate('async () => {await openPreview();window.__printBefore=ctx.printBase64;}')
        meta=poll(page,'() => ctx.productionMeta');assert meta['dpi']==720
        page.evaluate("() => {navigate('page-editor');canvas.setActiveObject(canvas.getObjects().find(o=>o.role==='sticker'));openAdjustSheet()}")
        layout();page.locator('#bf-adjust-collapse').click();page.locator('#bf-adjust-collapse').click()
        page.evaluate('async () => {closeSheets();await openPreview()}')
        assert page.evaluate('ctx.printBase64===window.__printBefore'), 'display fit changed production pixels'
        assert not errors,errors
        print('ADJUST_PANEL_OK',browser.browser_type.name,product,json.dumps(meta),flush=True)
        context.close()

if __name__=='__main__':
    suite=runpy.run_path(str(ROOT/'.github/tests/test_ai_editor_webkit.py'))
    server=suite['ServerThread']();server.start()
    try:
        with suite['sync_playwright']() as p:
            browser=getattr(p,os.environ.get('BROWSER_ENGINE','webkit')).launch()
            try:adjust_panel_test(browser,f"http://127.0.0.1:{suite['BROWSER_TEST_PORT']}",suite['poll'])
            finally:browser.close()
    finally:server.close()

