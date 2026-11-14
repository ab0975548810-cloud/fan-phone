"""Exercise Fabric side/corner handles, independent inputs and persisted pixels."""
def stretch_regression(page, context, engine, poll, product):
    def state():
        return page.evaluate("() => {const o=canvas.getActiveObject();return {sx:o.scaleX,sy:o.scaleY,index:historyIndex}}")

    def select():
        page.evaluate("() => {canvas.setActiveObject(canvas.getObjects().find(o=>o.role==='sticker'));syncSelection()}")

    def reset():
        page.evaluate("() => {closeSheets();const o=canvas.getActiveObject();o.set({angle:0,scaleX:o.bfScaleBaseX*.6,scaleY:o.bfScaleBaseY*.6});o.setPositionByOrigin(new fabric.Point(canvas.width/2,canvas.height/2),'center','center');o.setCoords();canvas.renderAll();clearTimeout(historyTimer);historyStack=[];historyIndex=-1;recordHistory(true)}")
        page.wait_for_timeout(450)

    def drag(handle, dx, dy, touch=False):
        p=page.evaluate("name => {const o=canvas.getActiveObject();o.setCoords();const p=o.oCoords[name],r=canvas.upperCanvasEl.getBoundingClientRect();return {x:r.x+p.x*r.width/canvas.width,y:r.y+p.y*r.height/canvas.height}}",handle)
        if touch:
            session=context.new_cdp_session(page) if engine=='chromium' else None
            def send(kind,x,y):
                if session:
                    session.send('Input.dispatchTouchEvent',dict(type=kind,touchPoints=[] if kind=='touchEnd' else [dict(id=1,x=x,y=y)]))
                else:
                    page.evaluate("""([kind,x,y])=>{const el=canvas.upperCanvasEl,p={identifier:1,target:el,clientX:x,clientY:y,pageX:x+scrollX,pageY:y+scrollY};const touches=kind==='touchEnd'?[]:[p];const e=new Event(kind.toLowerCase(),{bubbles:true,cancelable:true});Object.assign(e,{touches,targetTouches:touches,changedTouches:[p]});el.dispatchEvent(e)}""",[kind,x,y])
            send('touchStart',p['x'],p['y'])
            for step in range(1,9):send('touchMove',p['x']+dx*step/8,p['y']+dy*step/8)
            send('touchEnd',p['x']+dx,p['y']+dy)
            if session:session.detach()
        else:
            page.mouse.move(p['x'],p['y']);page.mouse.down()
            page.mouse.move(p['x']+dx,p['y']+dy,steps=8);page.mouse.up()
        page.wait_for_timeout(400)

    for width,height in ((390,844),(375,667)):
        page.set_viewport_size(dict(width=width,height=height))
        for handle,dx,dy,axis in [('mr',14,0,'sx'),('ml',-14,0,'sx'),('mb',0,14,'sy'),('mt',0,-14,'sy')]:
            reset();before=state();drag(handle,dx,dy);after=state()
            other='sy' if axis=='sx' else 'sx'
            assert after[axis]>before[axis] and abs(after[other]-before[other])<1e-8,(handle,before,after)
            assert after['index']==before['index']+1,(before,after)
            page.evaluate('undoCanvas()');poll(page,'() => !restoringHistory');select()
            assert abs(state()[axis]-before[axis])<1e-7
            page.evaluate('redoCanvas()');poll(page,'() => !restoringHistory');select()
            assert abs(state()[axis]-after[axis])<1e-7
        for handle,dx,dy in [('tl',-12,-12),('tr',12,-12),('bl',-12,12),('br',12,12)]:
            reset();before=state();drag(handle,dx,dy);after=state()
            assert after['sx']>before['sx'] and abs(after['sx']/after['sy']-before['sx']/before['sy'])<1e-7,(handle,before,after)
        for handle,dx,dy,axis,other in [('mr',14,0,'sx','sy'),('mb',0,14,'sy','sx')]:
            reset();before=state();drag(handle,dx,dy,touch=True);after=state()
            assert after[axis]>before[axis] and abs(after[other]-before[other])<1e-8,(engine,handle,before,after)
    reset();page.evaluate('openAdjustSheet()');page.locator('#bf-adjust-more summary').click()
    before=state()
    for key,value,axis,other in [('width',110,'sx','sy'),('height',85,'sy','sx')]:
        before=state();field=page.locator('#object-'+key+'-number');field.fill(str(value));assert state()==before
        field.press('Enter');after=state();assert abs(after[other]-before[other])<1e-8 and after[axis]!=before[axis]
        assert float(page.locator('#object-'+key+'-range').input_value())==value
        for invalid in ('','bad','301','-1'):
            field.fill(invalid);field.press('Enter');assert state()==after
    slider=page.locator('#object-width-range');slider.scroll_into_view_if_needed();box=slider.bounding_box()
    before=state();y=box['y']+box['height']/2
    page.mouse.move(box['x']+box['width']*.36,y);page.mouse.down();page.mouse.move(box['x']+box['width']*.45,y,steps=6)
    live=state();assert live['index']==before['index'] and live['sx']!=before['sx'] and live['sy']==before['sy']
    page.mouse.up();assert state()['index']==before['index']+1
    # Persist actual stretched scales through the production draft workflow.
    saved=state();page.evaluate('async () => {closeSheets();await BenfuwanDesignDraft.saveNow();await openPreview()}')
    poll(page,'() => ctx.productionMeta?.dpi===720 && !!ctx.printBase64')
    pixels=page.evaluate('ctx.printBase64')
    page.reload(wait_until='domcontentloaded');poll(page,"() => catalogState==='ready' && !!window.BenfuwanDesignDraft")
    page.evaluate('BenfuwanDesignDraft.continueEditing()');poll(page,'() => editorHasSession && !!canvas && canvas.getObjects().some(o=>o.role===\'sticker\')');select()
    assert abs(state()['sx']-saved['sx'])<1e-7 and abs(state()['sy']-saved['sy'])<1e-7
    page.evaluate('openPreview()');poll(page,'() => ctx.productionMeta?.dpi===720 && !!ctx.printBase64')
    assert page.evaluate('ctx.printBase64')==pixels,'stretched production pixels changed after reload'
    page.evaluate("() => {navigate('page-editor');canvas.setActiveObject(canvas.getObjects().find(o=>o.role==='sticker'));openAdjustSheet()}")
    print('IMAGE_STRETCH_HANDLES_INPUT_UNDO_DRAFT_720_OK',engine,product,flush=True)
