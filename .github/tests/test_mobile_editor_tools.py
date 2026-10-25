"""Real pointer interactions; isolated catalog, no order or vendor writes."""
import base64
import json
import os
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def mobile_editor_tools_test(browser, base, poll):
    for product in ('phone_case', 'camera_film'):
        context = browser.new_context(viewport=dict(width=390, height=844), device_scale_factor=3)
        page = context.new_page()
        image = 'data:image/png;base64,' + base64.b64encode((ROOT / 'static/images/benfuwan-cat-peek.png').read_bytes()).decode()
        mask = 'data:image/png;base64,' + base64.b64encode((ROOT / '.github/tests/fixtures/film/print.png').read_bytes()).decode()
        catalog = dict(brands=['測試'], models=[dict(id='mobile', name='測試型號', brand='測試', status=True,
            product_type=product, direct_style_id='style', case_profiles={'style':dict(preview_mask_img=mask,
            print_line_img=mask, print_w=67, print_h=47, print_x=68, print_y=30, print_angle=0)})],
            styles=[dict(id='style', name='測試款', product_type=product, status=True, price=490, colors=[] if product=='camera_film' else ['白'])])
        page.route('**/api/shop_data*', lambda r:r.fulfill(json=dict(status='success', version='fixture', data=catalog)))
        page.goto(base, wait_until='domcontentloaded')
        poll(page, "() => catalogState==='ready' && !!window.BenfuwanEditorControls")
        page.evaluate("async () => {await startNewDesign();selectModel(shopData.models[0]);selectStyle(shopData.styles[0]);ctx.colorName='白';await startEditor(false)}")
        poll(page, "() => editorHasSession && !!canvas")
        # Overflowing sticker fixtures and real category / add / close buttons.
        page.evaluate("url => {assetsData.categories=['貓咪','其他'];assetsData.stickers=Array.from({length:60},(_,i)=>({id:'s'+i,url,category:i%2?'貓咪':'其他',name:'貓'+i}));openStickerSheet()}", image)
        page.wait_for_timeout(300)
        page.evaluate("document.querySelector('#sheet-sticker .sheet-body').scrollTop=500")
        assert page.evaluate("document.querySelector('#sheet-sticker .sheet-body').scrollTop") > 0
        page.locator('#sheet-sticker .sheet-close').click()
        page.locator('[onclick="openStickerSheet()"]' ).click()
        assert page.evaluate("document.querySelector('#sheet-sticker .sheet-body').scrollTop") == 0
        page.evaluate("document.querySelector('#sheet-sticker .sheet-body').scrollTop=200")
        page.locator('#sticker-cats button', has_text='貓咪').click()
        assert page.evaluate("document.querySelector('#sheet-sticker .sheet-body').scrollTop") == 0
        page.locator('#sticker-grid .sticker-item').first.click()
        poll(page, "() => canvas.getActiveObject()?.role==='sticker' && !document.getElementById('sheet-sticker').classList.contains('show')")
        assert page.evaluate("() => canvas.getObjects().at(-1)===canvas.getActiveObject()")
        # Uniform scale preserves a pre-existing unequal ratio, rotation, alpha,
        # center, clip and stack. Real pointer drag: live render, one history.
        page.evaluate("() => {const o=canvas.getActiveObject();o.set({scaleX:.5,scaleY:.75,angle:19,opacity:.7});o.setCoords();window.__clip=o.clipPath;recordHistory();openAdjustSheet()}")
        page.wait_for_timeout(300)
        assert float(page.locator('#object-scale-range').input_value()) == 50
        assert page.locator('[onclick^="cropActive("]').count() == 0
        assert page.evaluate("typeof cropActive==='function'")
        before = page.evaluate("() => ({center:canvas.getActiveObject().getCenterPoint(),history:historyStack.length})")
        slider = page.locator('#object-scale-range')
        slider.hover()
        box = slider.bounding_box()
        x = box['x'] + 14 + (box['width']-28)*(.5-.001)/(4-.001)
        y = box['y'] + box['height']/2
        page.mouse.move(x,y);page.mouse.down();page.mouse.move(x+35,y,steps=12)
        live = page.evaluate("() => ({scale:canvas.getActiveObject().scaleX,history:historyStack.length})")
        assert live['scale'] > .5 and live['history'] == before['history'], (live,box,page.evaluate("p=>document.elementFromPoint(p.x,p.y)?.outerHTML",dict(x=x,y=y)))
        page.mouse.up()
        assert page.evaluate("() => historyStack.length") == before['history']+1
        result = page.evaluate("() => {const o=canvas.getActiveObject();return {ratio:o.scaleY/o.scaleX,angle:o.angle,opacity:o.opacity,clip:o.clipPath===window.__clip,center:o.getCenterPoint(),top:canvas.getObjects().at(-1)===o}}")
        assert abs(result['ratio']-1.5)<1e-8 and result['angle']==19 and result['opacity']==.7 and result['clip'] and result['top'],result
        assert abs(result['center']['x']-before['center']['x'])<1e-7 and abs(result['center']['y']-before['center']['y'])<1e-7
        page.evaluate('undoCanvas()')
        poll(page,"() => !restoringHistory && canvas.getObjects().find(o=>o.role==='sticker')?.scaleX===.5")
        page.evaluate('redoCanvas()')
        poll(page,"() => !restoringHistory && canvas.getObjects().find(o=>o.role==='sticker')?.scaleX>.5")
        page.evaluate("() => {canvas.setActiveObject(canvas.getObjects().find(o=>o.role==='sticker'));syncSelection()}")
        page.evaluate("() => {canvas.getActiveObject().bfUserLocked=true;BenfuwanEditorControls.applyUserLock(canvas.getActiveObject());openAdjustSheet()}")
        assert slider.is_disabled()
        locked = page.evaluate("canvas.getActiveObject().scaleX")
        page.evaluate("() => {const r=document.getElementById('object-scale-range');r.value=200;r.dispatchEvent(new Event('input'))}")
        assert page.evaluate("canvas.getActiveObject().scaleX") == locked
        page.evaluate("() => {const o=canvas.getActiveObject();o.bfUserLocked=false;o.templateLayerId='locked';canvas.layer_contract_version='multilayer-v1';canvas.templateState={initial:[{templateLayerId:'locked',canScale:false,canMove:true,canEdit:true}]};BenfuwanEditorControls.applyUserLock(o);openAdjustSheet()}")
        assert slider.is_disabled()
        page.evaluate("() => {const o=canvas.getActiveObject();delete o.templateLayerId;delete canvas.templateState;delete canvas.layer_contract_version;BenfuwanEditorControls.applyUserLock(o);closeSheets()}")
        # Shape controls are scoped to vectors, with normal duplicate/delete.
        page.locator('[onclick="openMaterialSheet()"]' ).click()
        page.locator('#material-cats button', has_text='基本形狀').click()
        assert page.locator('#material-grid button').count()==3
        page.locator('[data-material="rect"]').click()
        poll(page,"() => canvas.getActiveObject()?.type==='rect'")
        page.evaluate('openAdjustSheet()')
        page.locator('#shape-stroke-width').fill('5');page.locator('#shape-stroke-width').press('Tab')
        page.locator('#shape-radius').fill('12');page.locator('#shape-radius').press('Tab')
        assert page.evaluate("() => canvas.getActiveObject().strokeWidth===5 && canvas.getActiveObject().rx===12")
        shape = page.evaluate("() => canvas.getActiveObject().toObject()")
        assert shape['strokeWidth']==5 and shape['rx']==shape['ry']==12
        page.evaluate("() => {closeSheets();duplicateActive()}")
        poll(page,"() => canvas.getObjects().filter(o=>o.type==='rect').length===2")
        page.evaluate('deleteActive()')
        assert page.evaluate("canvas.getObjects().filter(o=>o.type==='rect').length") == 1
        # Font cards use the same hash-checked font loader as production, and
        # simply opening the UI must not change existing text layout or family.
        legacy = page.evaluate("() => {const o=new fabric.Textbox('Legacy Arial',{fontFamily:'Arial',fontSize:18,width:140,role:'text'});canvas.add(o);canvas.setActiveObject(o);const saved=o.toObject();openTextSheet();return saved}")
        assert page.locator('#text-font').input_value()=='Arial'
        assert page.evaluate('canvas.getActiveObject().toObject()')==legacy
        poll(page,"() => document.querySelector('#bf-font-previews button[data-family=Arial]')?.disabled===false")
        assert 'BF-Arimo' in page.locator('#bf-font-previews button[data-family="Arial"] span').evaluate('e=>e.style.fontFamily')
        page.evaluate('() => {closeSheets();deleteActive()}')
        page.evaluate("() => {canvas.discardActiveObject();openTextSheet()}")
        assert page.evaluate("document.querySelector('.app').scrollTop") == 0
        assert page.locator('#text-font').input_value() == 'NotoSansTC'
        poll(page,"() => document.querySelector('#bf-font-previews button[data-family=\"jf-openhuninn\"]')?.disabled===false")
        Path('artifacts').mkdir(exist_ok=True)
        page.locator('#bf-font-previews').scroll_into_view_if_needed()
        assert page.evaluate("() => document.querySelector('.app').scrollTop===0 && document.getElementById('sheet-text').getBoundingClientRect().top>=0")
        page.screenshot(path=f'artifacts/mobile-fonts-{product}-{browser.browser_type.name}.png')
        page.locator('#bf-font-previews button[data-family="jf-openhuninn"]').click()
        page.locator('#text-input').fill('本福丸可愛貓咪')
        page.locator('[onclick="addTextFromControls()"]' ).click()
        poll(page,"() => canvas.getActiveObject()?.fontFamily==='jf-openhuninn'")
        snapshot = page.evaluate("() => canvas.getActiveObject().toObject()")
        original_layout = page.evaluate("() => {const o=canvas.getActiveObject();return [o.width,o.height,o.left,o.top,o.textLines]}")
        page.evaluate('openTextSheet()')
        assert page.evaluate("() => canvas.getActiveObject().toObject()") == snapshot
        page.evaluate("async () => {closeSheets();await ensureCanvasFonts()}")
        assert page.evaluate("canvas.getActiveObject().fontFamily") == 'jf-openhuninn'
        layout = page.evaluate("() => {const o=canvas.getActiveObject();return [o.width,o.height,o.left,o.top,o.textLines]}")
        assert layout == original_layout, (layout,original_layout)
        for width,height in ((390,844),(768,1024),(1180,900)):
            page.set_viewport_size(dict(width=width,height=height));page.evaluate('openMaterialSheet()')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth+2')
        page.set_viewport_size(dict(width=390,height=844));page.evaluate('openAdjustSheet()')
        Path('artifacts').mkdir(exist_ok=True)
        page.wait_for_timeout(350)
        page.screenshot(path=f'artifacts/mobile-tools-{product}-{browser.browser_type.name}.png')
        page.evaluate("async () => {closeSheets();await openPreview()}")
        meta=poll(page,"() => ctx.productionMeta")
        assert [meta['width'],meta['height'],meta['dpi']]==[1899,1332,720],meta
        print('MOBILE_EDITOR_TOOLS_OK',product,browser.browser_type.name,json.dumps(meta),flush=True)
        context.close()


if __name__=='__main__':
    suite=runpy.run_path(str(ROOT/'.github/tests/test_ai_editor_webkit.py'))
    server=suite['ServerThread']();server.start()
    try:
        with suite['sync_playwright']() as p:
            browser=getattr(p,os.environ.get('BROWSER_ENGINE','webkit')).launch()
            try:mobile_editor_tools_test(browser,f"http://127.0.0.1:{suite['BROWSER_TEST_PORT']}",suite['poll'])
            finally:browser.close()
    finally:server.close()
