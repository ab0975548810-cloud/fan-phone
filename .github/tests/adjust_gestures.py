"""Exact-angle touch regression; Chromium uses trusted CDP multi-touch input."""
import math


def gesture_regression(page, context, engine, poll, product):
    session = context.new_cdp_session(page) if engine == 'chromium' else None
    page.evaluate("""() => {
      window.gestureTouch=(type,points)=>{
        const el=canvas.upperCanvasEl;
        const touches=points.map(p=>({identifier:p.id,target:el,clientX:p.x,clientY:p.y,pageX:p.x+scrollX,pageY:p.y+scrollY}));
        const previous=window.gesturePrevious||[];
        const event=new Event(type,{bubbles:true,cancelable:true});
        Object.assign(event,{touches,targetTouches:touches,changedTouches:touches.length?touches:previous});el.dispatchEvent(event);
        window.gesturePrevious=touches;
      };
    }""")

    def send(kind, points):
        if session:
            session.send('Input.dispatchTouchEvent', dict(type=kind, touchPoints=points))
        else:
            page.evaluate('([kind,points])=>gestureTouch(kind.toLowerCase(),points)', [kind, points])

    def state():
        return page.evaluate("() => {const o=canvas.getActiveObject();return {angle:o.angle,sx:o.scaleX,sy:o.scaleY,x:o.left,y:o.top,index:historyIndex}}")

    def setup():
        page.evaluate("""() => {closeSheets();const o=canvas.getObjects().find(o=>o.role==='sticker');
          canvas.setActiveObject(o);o.set({angle:27,scaleX:o.bfScaleBaseX,scaleY:o.bfScaleBaseY});
          o.setPositionByOrigin(new fabric.Point(canvas.width/2,canvas.height/2),'center','center');
          o.setCoords();canvas.renderAll();clearTimeout(historyTimer);historyStack=[];historyIndex=-1;recordHistory(true);syncSelection();} """)
        page.wait_for_timeout(450)

    def points(angle, radius=24):
        center=page.evaluate("() => {const r=canvas.upperCanvasEl.getBoundingClientRect(),p=canvas.getActiveObject().getCenterPoint();return {x:r.x+p.x*r.width/canvas.width,y:r.y+p.y*r.height/canvas.height}}")
        dx=radius*math.cos(math.radians(angle));dy=radius*math.sin(math.radians(angle))
        return [dict(id=1,x=center['x'],y=center['y']),dict(id=2,x=center['x']+dx,y=center['y']+dy)]

    def angle(expected):
        actual=state()['angle']
        assert abs((actual-expected+180)%360-180)<.15,(product,engine,expected,actual)

    def restore(action):
        page.evaluate(action+'()');poll(page,'() => !restoringHistory')
        page.evaluate("() => {canvas.setActiveObject(canvas.getObjects().find(o=>o.role==='sticker'));syncSelection()}")

    for width,height in ((375,667),(390,844),(844,390),(1180,900)):
        page.set_viewport_size(dict(width=width,height=height));setup()
        before=state()
        send('touchStart',points(45));send('touchMove',points(45,30))
        angle(27)
        live=state();assert live['sx']>before['sx'] and live['index']==before['index'],(before,live)
        assert abs(live['sx']/live['sy']-before['sx']/before['sy'])<1e-7
        send('touchMove',points(60,30));angle(42)
        send('touchEnd',[])
        assert state()['index']==before['index']+1,(before,state())
        restore('undoCanvas');angle(27)
        assert abs(state()['sx']-before['sx'])<1e-7
        restore('redoCanvas');angle(42)
        for start,end,expected in ((179,-179,29),(-179,179,25)):
            setup();send('touchStart',points(start));send('touchMove',points(end));angle(expected);send('touchEnd',[])
        # Cancellation commits one preview, cleans up, and a fresh gesture works.
        setup();before=state();send('touchStart',points(45));send('touchMove',points(60));angle(42)
        send('touchCancel',[]);after=state()
        assert after['index']==before['index']+1,(before,after)
        page.evaluate("gestureTouch('touchend',[])");assert state()==after
        restore('undoCanvas');angle(27)
        # Deselect/reselect during contact must not revive the old gesture.
        setup();send('touchStart',points(45));send('touchMove',points(60));angle(42)
        page.evaluate("() => {const o=canvas.getActiveObject();canvas.discardActiveObject();canvas.setActiveObject(o)}")
        frozen=state();send('touchMove',points(80,34));assert state()==frozen;send('touchEnd',[])
        # Undo while contacts remain down cannot mutate the restored object.
        setup();send('touchStart',points(45));send('touchMove',points(60));restore('undoCanvas');angle(27)
        frozen=state();send('touchMove',points(80,34));assert state()==frozen;send('touchEnd',[])
        # A real one-finger drag followed by two contacts, then one remaining.
        setup();one=points(45,0)[:1];send('touchStart',one)
        moved=[dict(one[0],x=one[0]['x']+5,y=one[0]['y']+5)];send('touchMove',moved)
        send('touchStart',points(45));send('touchMove',points(60,30));angle(42)
        send('touchEnd',points(60,30)[:1]);frozen=state()
        send('touchMove',points(80,34)[:1]);assert state()==frozen;send('touchEnd',[])
        restore('undoCanvas');angle(27)
        # Fresh single-finger drag after handoff: Fabric's listeners are restored.
        page.wait_for_timeout(450);before=state();one=points(45,0)[:1];send('touchStart',one)
        send('touchMove',[dict(one[0],x=one[0]['x']+8,y=one[0]['y']+8)]);send('touchEnd',[])
        assert state()['x']!=before['x'],(before,state())
        print('EXACT_GESTURE_OK',engine,product,width,height,flush=True)
    # Author policy with independent scale/rotate permissions, including frames.
    for role in ('sticker','slot-photo'):
        for can_scale,can_rotate in ((False,False),(True,False),(False,True)):
            setup()
            page.evaluate("""([role,scale,rotate])=>{const o=canvas.getActiveObject();window.gestureProtected=o;
              o.set({scaleX:o.bfScaleBaseX*.4,scaleY:o.bfScaleBaseY*.4});o.setCoords();canvas.renderAll();
              o.role=role;o.templateSlot=role==='slot-photo';o.templateLayerId='gesture-policy';canvas.layer_contract_version='multilayer-v1';
              canvas.templateState={initial:[{...o.toObject(),templateLayerId:'gesture-policy',canMove:true,canEdit:true,canScale:scale,canRotate:rotate}]};
              BenfuwanEditorControls.applyUserLock(o);recordHistory();} """,[role,can_scale,can_rotate])
            before=state();send('touchStart',points(45));send('touchMove',points(60,30));send('touchEnd',[])
            angle(42 if can_rotate else 27)
            assert (state()['sx']>before['sx'])==can_scale,(role,can_scale,can_rotate,before,state())
            page.evaluate("""()=>{const o=gestureProtected;o.role='sticker';delete o.templateLayerId;delete o.templateSlot;
              delete canvas.templateState;delete canvas.layer_contract_version;BenfuwanEditorControls.applyUserLock(o);} """)
    setup();page.evaluate("() => {const o=canvas.getActiveObject();o.bfUserLocked=true;BenfuwanEditorControls.applyUserLock(o);recordHistory()}")
    before=state();send('touchStart',points(45));send('touchMove',points(60,30));send('touchEnd',[])
    assert state()==before
    page.evaluate("() => {const o=canvas.getActiveObject();o.bfUserLocked=false;BenfuwanEditorControls.applyUserLock(o)}")
    page.set_viewport_size(dict(width=390,height=844));setup()
    page.evaluate('() => {historyStack=[];historyIndex=-1;recordHistory(true);openAdjustSheet()}')
