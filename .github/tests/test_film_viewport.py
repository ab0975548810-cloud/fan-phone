"""Public original film fixture; local browser only, no production mutations."""
import base64
import io
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def film_viewport_test(browser, base, poll):
    for dpr in (1,2,3):
        film_density_test(browser,base,poll,dpr)


def film_density_test(browser, base, poll, dpr):
    context = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=dpr)
    page = context.new_page()
    pair = {key: 'data:image/png;base64,' + base64.b64encode(
        (ROOT / '.github/tests/fixtures/film' / (key + '.png')).read_bytes()).decode()
        for key in ('preview', 'print')}
    catalog={'brands':['鏡頭底膜'],'models':[{'id':'film-fixture','name':'iPhone 17 Pro Max','brand':'鏡頭底膜','status':True,'case_profiles':{'film':{'preview_mask_img':pair['preview'],'print_line_img':pair['print'],'print_w':67,'print_h':47,'print_x':68,'print_y':30,'print_angle':0}}}],
             'styles':[{'id':'film','name':'背膜','status':True,'colors':['白']}]}
    page.route('**/api/shop_data',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({'status':'success','version':'fixture','data':catalog})))
    page.goto(base + '/', wait_until='domcontentloaded')
    poll(page, "() => !!window.BenfuwanModelProfile?.prepareEditorGeometry && !!window.BenfuwanEditorAccess && !!window.BenfuwanDesignDraft")
    page.evaluate("""async pair => {
      shopData.models=[{id:'film-fixture',name:'iPhone 17 Pro Max',brand:'鏡頭底膜',status:true,case_profiles:{film:{preview_mask_img:pair.preview,print_line_img:pair.print,print_w:67,print_h:47,print_x:68,print_y:30,print_angle:0}}}];
      shopData.styles=[{id:'film',name:'背膜',status:true,colors:['白']}];
      selectModel(shopData.models[0]);selectStyle(shopData.styles[0]);ctx.colorName='白';
      await startEditor(false);await BenfuwanPrintMask.ensureClip(canvas,ctx.printLineUrl);
    }""", pair)
    def geometry():
        return page.evaluate("""() => {
          const box=el=>{const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}};
          return {shell:box(document.getElementById('canvas-shell')),mask:box(document.getElementById('phone-mask')),guide:box(document.getElementById('print-area-guide')),canvas:box(canvas.upperCanvasEl),workspace:box(document.querySelector('#page-editor>.workspace')),logical:[canvas.width,canvas.height],print:[ctx.printW,ctx.printH,ctx.printX,ctx.printY,ctx.printAngle]};
        }""")
    for width, height in ((390,844),(390,600),(768,1024),(1180,900)):
        page.set_viewport_size(dict(width=width,height=height))
        poll(page, "() => Math.abs(document.getElementById('canvas-shell').getBoundingClientRect().width-canvas.upperCanvasEl.getBoundingClientRect().width)<1")
        page.wait_for_timeout(100)
        result=geometry(); shell=result['shell']; workspace=result['workspace']
        assert result['logical'][0]==201 and abs(result['logical'][1]-201*827/1530)<1e-8,result
        assert abs(shell['w']/shell['h']-1530/827)<.001,result
        assert result['print']==[67,47,68,30,0],result
        assert shell['w'] <= workspace['w']-47 and shell['h'] <= workspace['h']-47,result
        assert abs(shell['x']+shell['w']/2-workspace['x']-workspace['w']/2)<1,result
        assert abs(shell['y']+shell['h']/2-workspace['y']-workspace['h']/2)<1,result
        for layer in ('mask','guide','canvas'):
            assert all(abs(result[layer][k]-shell[k])<1 for k in ('x','y','w','h')),result
        poll(page,"""() => {const r=canvas.lowerCanvasEl.getBoundingClientRect(),g=document.getElementById('print-area-guide');return Math.abs(canvas.lowerCanvasEl.width-r.width*devicePixelRatio)<=1 && Math.abs(g.naturalWidth-r.width*devicePixelRatio)<=1}""")
        density=page.evaluate("""() => {const r=canvas.lowerCanvasEl.getBoundingClientRect();return {css:[r.width,r.height],lower:[canvas.lowerCanvasEl.width,canvas.lowerCanvasEl.height],upper:[canvas.upperCanvasEl.width,canvas.upperCanvasEl.height],guide:[document.getElementById('print-area-guide').naturalWidth,document.getElementById('print-area-guide').naturalHeight],overlay:[document.getElementById('phone-mask').naturalWidth,document.getElementById('phone-mask').naturalHeight],checker:getComputedStyle(document.getElementById('canvas-shell')).backgroundSize}}""")
        for layer in ('lower','upper','guide'):
            assert all(abs(density[layer][i]-density['css'][i]*dpr)<=1 for i in (0,1)),density
        assert density['overlay']==[1530,827],density
        assert '16px 16px' in density['checker'],density
    page.set_viewport_size(dict(width=390,height=844))
    buf=io.BytesIO();Image.new('RGBA',(320,240),(220,40,70,255)).save(buf,format='PNG')
    page.locator('#photo-input').set_input_files(dict(name='film-photo.png',mimeType='image/png',buffer=buf.getvalue()))
    poll(page,"() => canvas.getObjects().some(o=>o.originalName==='film-photo.png') && !document.getElementById('busy')?.classList.contains('show')")
    # Select and drag via real browser pointer, in the opaque right half.
    page.evaluate("() => {const o=canvas.getObjects().find(o=>o.originalName==='film-photo.png');o.set({left:canvas.width*.65,top:canvas.height*.5});o.setCoords();canvas.setActiveObject(o);syncSelection();canvas.requestRenderAll()}")
    page.wait_for_timeout(150)
    def photo():
        return page.evaluate("() => {const o=canvas.getActiveObject();return {left:o.left,top:o.top,scaleX:o.scaleX,scaleY:o.scaleY,angle:o.angle}}")
    before=photo();box=page.locator('.upper-canvas').bounding_box()
    x=box['x']+box['width']*.65;y=box['y']+box['height']*.5
    page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+12,y+9,steps=5);page.mouse.up()
    after=photo();assert abs(after['left']-before['left'])>2 and abs(after['top']-before['top'])>2,(before,after)
    # Scale using a Fabric scale corner, not the dedicated bottom-right move handle.
    corner=page.evaluate("() => {canvas.getActiveObject().setCoords();const p=canvas.getActiveObject().oCoords.tr;const r=canvas.upperCanvasEl.getBoundingClientRect();return {x:r.x+p.x*r.width/canvas.width,y:r.y+p.y*r.height/canvas.height}}")
    page.mouse.move(corner['x'],corner['y']);page.mouse.down();page.mouse.move(corner['x']+12,corner['y']-9,steps=5);page.mouse.up()
    scaled=photo();assert scaled['scaleX']>after['scaleX'],(after,scaled)
    # Draft restoration uses the source frame, not the old forced portrait size.
    saved=page.evaluate("async () => {await BenfuwanDesignDraft.saveNow();return await BenfuwanDesignDraft.readDraft()}")
    assert page.evaluate("raw => BenfuwanDesignDraft.inspectDraft(raw).ok",saved)
    assert not page.evaluate("raw => BenfuwanDesignDraft.inspectDraft({...raw,logicalCanvasHeight:360}).ok",saved)
    assert page.evaluate("async () => {resetDesignState(true);return await BenfuwanDesignDraft.continueEditing()}")
    restored=page.evaluate("() => {const o=canvas.getObjects().find(o=>o.originalName==='film-photo.png');return {left:o.left,top:o.top,scaleX:o.scaleX,scaleY:o.scaleY,angle:o.angle}}")
    saved_photo=next(o for o in saved['canvasJson']['objects'] if o.get('originalName')=='film-photo.png')
    assert all(restored[k]==saved_photo[k] for k in scaled),(restored,saved_photo)
    page.evaluate("async () => {await BenfuwanPrintMask.ensureClip(canvas,ctx.printLineUrl);canvas.renderAll()}")
    poll(page,"""() => {const p=canvas.lowerCanvasEl.getContext('2d').getImageData(0,0,canvas.lowerCanvasEl.width,canvas.lowerCanvasEl.height).data;let red=0;for(let i=0;i<p.length;i+=4)if(p[i]>180&&p[i+1]<80&&p[i+3]>200)red++;return red>100}""")
    Path('artifacts').mkdir(exist_ok=True)
    page.screenshot(path=f'artifacts/film-{browser.browser_type.name}-390-dpr{dpr}.png')
    # Real HQ preview path: display-only geometry cannot change production W/H.
    page.evaluate("async () => {await openPreview()}")
    meta=poll(page,"() => ctx.productionMeta")
    assert [meta['width'],meta['height'],meta['dpi']]==[1899,1332,720],meta
    output=page.evaluate("""() => new Promise((resolve,reject)=>{const im=new Image();im.onerror=reject;im.onload=()=>{const c=document.createElement('canvas');c.width=im.width;c.height=im.height;const g=c.getContext('2d');g.drawImage(im,0,0);const p=g.getImageData(0,0,c.width,c.height).data;let red=0;for(let i=0;i<p.length;i+=4)if(p[i]>180&&p[i+1]<80&&p[i+3]>200)red++;const x=Math.round((200-6)/1519*c.width),y=Math.round((190-5)/817*c.height);resolve({width:im.width,height:im.height,red,hole:p[(y*c.width+x)*4+3]})};im.src=ctx.printBase64})""")
    assert output['width']==1899 and output['height']==1332 and output['red']>100 and output['hole']==0,output
    # Export pixels must be identical with/without the display-only retina override.
    assert page.evaluate("""async () => {
      const state=await BenfuwanPrintMask.ensureClip(canvas,ctx.printLineUrl);
      const render=()=>BenfuwanPrintMask.renderPrint(canvas,state.mask,1899,1332).toDataURL('image/png');
      const expected=render(),own={};
      for(const name of ['getRetinaScaling','_isRetinaScaling','_initRetinaScaling']){own[name]=canvas[name];delete canvas[name]}
      try {return render()===expected}
      finally {Object.assign(canvas,own)}
    }"""),'display density changed production PNG'
    # Switching back to an ordinary phone case must not reuse the film aspect.
    regular=page.evaluate("""() => {shopData.models[0].brand='Apple';resetDesignState(true);selectModel(shopData.models[0]);selectStyle(shopData.styles[0]);ctx.colorName='白';startEditor(false);return [canvas.width,canvas.height]}""")
    assert regular==[201,141],regular
    assert page.evaluate("() => !canvas.__bfFilmRetina && canvas.getRetinaScaling()===fabric.devicePixelRatio")
    page.route('**/fixture-missing-film.png',lambda route:route.fulfill(status=404,body='missing'))
    failed=page.evaluate("""async () => {resetDesignState(true);shopData.models[0].brand='鏡頭底膜';shopData.models[0].case_profiles.film.print_line_img='/fixture-missing-film.png';selectModel(shopData.models[0]);selectStyle(shopData.styles[0]);ctx.colorName='白';const result=await startEditor(false);return {result,session:editorHasSession}}""")
    assert failed=={'result':False,'session':False},failed
    print('FILM_RETINA_DRAG_SCALE_DRAFT_HQ_OK',browser.browser_type.name,'DPR',dpr,json.dumps(meta),flush=True)
    context.close()


if __name__ == '__main__':
    import runpy, os
    suite=runpy.run_path(str(ROOT/'.github/tests/test_ai_editor_webkit.py'))
    server=suite['ServerThread']();server.start()
    try:
        with suite['sync_playwright']() as p:
            browser=getattr(p,os.environ.get('BROWSER_ENGINE','webkit')).launch()
            try:film_viewport_test(browser,f"http://127.0.0.1:{suite['BROWSER_TEST_PORT']}",suite['poll'])
            finally:browser.close()
    finally:server.close()
