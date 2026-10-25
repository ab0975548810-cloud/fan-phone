"""Public original film fixture; local browser only, no production mutations."""
import base64
import io
import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]


def film_viewport_test(browser, base, poll):
    film_admin_test(browser, base, poll)
    for dpr in (1,2,3):
        film_density_test(browser,base,poll,dpr)


def film_admin_test(browser, base, poll):
    page = browser.new_page(viewport={'width':390,'height':844})
    profile = dict(preview_mask_img='/static/images/benfuwan-cat-peek.png',
                   print_line_img='/static/images/benfuwan-cat-peek.png',
                   print_w=67,print_h=37,print_x=66,print_y=30,print_angle=0)
    catalog = dict(brands=['鏡頭底膜','Apple'], models=[dict(id='m_1792558304007',
        brand='鏡頭底膜',name='底膜型號',status=True,case_profiles={'crystal':profile})],
        styles=[dict(id='crystal',name='晶彩',status=True,price=790,colors=['白','黑'])])
    writes=[]
    def catalog_response(route):
        route.fulfill(status=200,content_type='application/json',body=json.dumps(dict(status='success',version='v1',data=catalog)))
    def save(route):
        data=route.request.post_data_json
        writes.append(data)
        catalog.clear();catalog.update(data['shop_data'])
        route.fulfill(status=200,content_type='application/json',body=json.dumps(dict(status='success',version='v2',synced_skus=1)))
    page.route('**/api/shop_data*',catalog_response)
    page.route('**/api/admin/print/model-profiles',save)
    page.on('dialog',lambda d:d.accept())
    page.goto(base+'/login',wait_until='load')
    if page.locator('#password-toggle').is_visible():
        page.locator('#password-toggle').click()
    page.locator('input[name="password"]').fill('fan123')
    page.locator('button[type="submit"]').click()
    page.wait_for_url('**/admin')
    poll(page,"() => !!window.BenfuwanModelProfilesAdmin && !!window.BenfuwanProducts")
    page.evaluate("async () => {await loadShop(true);openModelEditor('m_1792558304007')}")
    assert page.locator('#model-product-type').input_value()=='camera_film'
    assert page.locator('#model-film-price').input_value()=='490'
    assert page.locator('#model-profile-w').input_value()==''  # No silent inheritance.
    page.get_by_role('button',name='確認帶入本型號的「晶彩」刀模').click()
    assert page.locator('#model-profile-w').input_value()=='67'
    for width,height in ((390,844),(768,1024),(1180,900)):
        page.set_viewport_size(dict(width=width,height=height))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    page.locator('#model-save').click()
    poll(page,"() => !document.getElementById('model-modal').classList.contains('show')")
    assert len(writes)==1,writes
    model=catalog['models'][0]; style=next(s for s in catalog['styles'] if s['id']==model['direct_style_id'])
    assert model['product_type']=='camera_film' and style['product_type']=='camera_film'
    assert style['price']==490 and style['colors']==[] and style['model_colors']=={}
    assert model['case_profiles'][style['id']]==profile
    assert model['case_profiles']['crystal']==profile
    assert catalog['styles'][0]['price']==790 and catalog['styles'][0]['colors']==['白','黑']
    page.evaluate("async () => {await loadShop(true);openModelEditor('m_1792558304007')}")
    assert page.locator('#model-profile-w').input_value()=='67'
    assert page.locator('#model-film-price').input_value()=='490'
    print('FILM_ADMIN_EXPLICIT_IMPORT_490_INDEPENDENT_PRODUCT_OK',flush=True)
    page.close()


def film_density_test(browser, base, poll, dpr):
    context = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=dpr)
    page = context.new_page()
    pair = {key: 'data:image/png;base64,' + base64.b64encode(
        (ROOT / '.github/tests/fixtures/film' / (key + '.png')).read_bytes()).decode()
        for key in ('preview', 'print')}
    catalog={'brands':['鏡頭底膜'],'models':[{'id':'film-fixture','name':'iPhone 17 Pro Max','brand':'鏡頭底膜','product_type':'camera_film','direct_style_id':'film','status':True,'case_profiles':{'film':{'preview_mask_img':pair['preview'],'print_line_img':pair['print'],'print_w':67,'print_h':47,'print_x':68,'print_y':30,'print_angle':0}}}],
             'styles':[{'id':'film','name':'背膜','product_type':'camera_film','price':490,'status':True,'colors':[]}]}
    catalog['brands'].append('Apple')
    catalog['models'].append(dict(id='case-fixture',name='名字含底膜也仍是手機殼',brand='Apple',product_type='phone_case',status=True,case_profiles={'crystal':catalog['models'][0]['case_profiles']['film']}))
    catalog['styles'].append(dict(id='crystal',name='晶彩手機殼',status=True,price=790,colors=['白','黑']))
    page.route('**/api/shop_data',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps({'status':'success','version':'fixture','data':catalog})))
    page.goto(base + '/', wait_until='domcontentloaded')
    poll(page, "() => !!window.BenfuwanModelProfile?.prepareEditorGeometry && !!window.BenfuwanEditorAccess && !!window.BenfuwanDesignDraft")
    # Real model-next click must go directly to a blank editor, never styles/templates.
    poll(page, "() => catalogState==='ready'")
    page.evaluate("async () => {await startNewDesign();selectModel(shopData.models[1])}")
    page.locator('#model-next').click()
    assert page.locator('#page-style').is_visible()
    assert page.locator('#style-grid .style-card').count()==1
    assert '晶彩手機殼' in page.locator('#style-grid').inner_text()
    page.locator('#style-grid .style-card').click()
    page.locator('.bf-color-chip').first.click()
    page.locator('#style-next').click()
    assert page.locator('#page-template').is_visible()
    # Known legacy film cannot accidentally continue using the old crystal SKU.
    page.evaluate("async () => {await startNewDesign();shopData.models[0].direct_style_id='';selectModel(shopData.models[0])}")
    page.locator('#model-next').click()
    assert page.locator('#page-model').is_visible() and not page.locator('#page-style').is_visible()
    page.evaluate("() => {shopData.models[0].direct_style_id='film';selectModel(shopData.models[0])}")
    page.locator('#model-next').click()
    poll(page, "() => editorHasSession && canvas && document.getElementById('page-editor').classList.contains('active')")
    assert page.evaluate("() => ctx.styleId==='film' && ctx.price===490 && ctx.colorName==='' && !selectedTpl")
    assert not page.locator('[onclick="openTemplatesInEditor()"]').is_visible()
    assert not page.locator('#page-style').is_visible()
    assert not page.locator('#page-template').is_visible()
    assert page.evaluate("() => {openTemplatesInEditor();return !document.getElementById('page-template').classList.contains('active')}")
    page.evaluate("async () => await BenfuwanPrintMask.ensureClip(canvas,ctx.printLineUrl)")
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
    # Scale using the Fabric corner handle, not a programmatic scale mutation.
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
    # Changing the film background must never move or resize the customer's
    # photo objects. This corresponds to the reported transparent -> pink edit.
    photo_positions = """() => canvas.getObjects().filter(o => o.role === 'photo').map(
      o => [o.left,o.top,o.scaleX,o.scaleY,o.angle,o.originX,o.originY]
    )"""
    before_background = page.evaluate(photo_positions)
    page.evaluate("() => { setCanvasBackground('#ffc7d9'); closeSheets(); }")
    page.wait_for_timeout(50)
    assert page.evaluate(photo_positions) == before_background, 'setting pink background moved artwork'
    page.evaluate("async () => {await BenfuwanPrintMask.ensureClip(canvas,ctx.printLineUrl);canvas.renderAll()}")
    poll(page,"""() => {const p=canvas.lowerCanvasEl.getContext('2d').getImageData(0,0,canvas.lowerCanvasEl.width,canvas.lowerCanvasEl.height).data;let red=0;for(let i=0;i<p.length;i+=4)if(p[i]>180&&p[i+1]<80&&p[i+3]>200)red++;return red>100}""")
    Path('artifacts').mkdir(exist_ok=True)
    page.screenshot(path=f'artifacts/film-{browser.browser_type.name}-390-dpr{dpr}.png')
    # Real HQ preview path: the final film preview MUST use the same
    # production raster, not the separately-cropped source-frame mockup.
    before_preview = page.evaluate(photo_positions)
    page.evaluate("async () => {await openPreview()}")
    meta=poll(page,"() => ctx.productionMeta")
    assert [meta['width'],meta['height'],meta['dpi']]==[1899,1332,720],meta
    assert page.evaluate(photo_positions) == before_preview, 'final preview moved artwork'
    poll(page, "() => document.getElementById('preview-image')?.naturalWidth === 1200")
    assert page.evaluate("""() => {
      const image=document.getElementById('preview-image'), meta=ctx.productionMeta;
      const expectedHeight=Math.round(1200*meta.height/meta.width);
      return image.src===ctx.mockupBase64
        && image.naturalWidth===1200 && image.naturalHeight===expectedHeight
        && document.querySelector('.preview-info p').textContent.includes('720 DPI')
        && document.querySelector('.design-checker').style.aspectRatio===meta.width+' / '+meta.height;
    }"""), 'film final preview diverged from production PNG'
    # Compare actual thumbnail pixels against downscaled production PNG at fixed
    # camera-hole and artwork reference points. Never rely only on dimensions.
    assert page.evaluate("""async () => {
      const image=document.getElementById('preview-image');
      const full=new Image();full.src=ctx.printBase64;await full.decode();
      const cv=document.createElement('canvas');
      cv.width=image.naturalWidth;cv.height=image.naturalHeight;
      const g=cv.getContext('2d');g.imageSmoothingEnabled=true;g.imageSmoothingQuality='high';
      g.drawImage(full,0,0,cv.width,cv.height);
      const expected=g.getImageData(0,0,cv.width,cv.height).data;
      g.clearRect(0,0,cv.width,cv.height);
      g.drawImage(image,0,0,cv.width,cv.height);
      const actual=g.getImageData(0,0,cv.width,cv.height).data;
      const positions=[[.05,.2],[.24,.55],[.6,.15],[.75,.35],[.82,.85]];
      return positions.every(([x,y])=>{
        const i=(Math.floor(y*cv.height)*cv.width+Math.floor(x*cv.width))*4;
        return [0,1,2,3].every(channel=>Math.abs(expected[i+channel]-actual[i+channel])<=8);
      });
    }"""), 'film thumbnail pixels do not match production PNG'
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
    regular=page.evaluate("""() => {shopData.models[0].product_type='phone_case';shopData.styles[0].product_type='phone_case';shopData.models[0].brand='Apple';resetDesignState(true);selectModel(shopData.models[0]);selectStyle(shopData.styles[0]);ctx.colorName='白';startEditor(false);return [canvas.width,canvas.height]}""")
    assert regular==[201,141],regular
    assert page.evaluate("() => !canvas.__bfFilmRetina && canvas.getRetinaScaling()===fabric.devicePixelRatio")
    page.route('**/fixture-missing-film.png',lambda route:route.fulfill(status=404,body='missing'))
    failed=page.evaluate("""async () => {resetDesignState(true);shopData.models[0].product_type='camera_film';shopData.styles[0].product_type='camera_film';shopData.models[0].brand='鏡頭底膜';shopData.models[0].case_profiles.film.print_line_img='/fixture-missing-film.png';selectModel(shopData.models[0]);selectStyle(shopData.styles[0]);ctx.colorName='白';const result=await startEditor(false);return {result,session:editorHasSession}}""")
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
