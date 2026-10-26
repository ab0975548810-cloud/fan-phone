"""Real Fabric before/after matrix and admin batch flow. Isolated local data only."""
import copy
import base64
import io
import json
import os
import runpy
import tempfile
import time
import uuid
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw, ImageChops, ImageStat

ROOT=Path(__file__).resolve().parents[2]


def master_adaptation_browser_test(browser,base,poll):
    import app
    import template_adaptation as engine
    import test_template_adaptation as fixtures
    import multilayer_templates
    import security_perf
    original={k:getattr(app,k) for k in ('DATA_FILE','TEMPLATES_FILE','ASSETS_FILE')}
    assets=ROOT/'static/__pycache__';assets.mkdir(exist_ok=True)
    prefix='master-'+uuid.uuid4().hex
    paths=[]
    output=ROOT/'artifacts/master-adaptation'/browser.browser_type.name;output.mkdir(parents=True,exist_ok=True)
    page=None;front=None
    with tempfile.TemporaryDirectory() as temporary:
        try:
            for key in original:setattr(app,key,str(Path(temporary)/(key+'.json')))
            photo=Image.new('RGBA',(1800,3000),'#f6cdda');draw=ImageDraw.Draw(photo)
            for i in range(24):draw.rectangle((0,i*125,1800,i*125+120),fill=(250-i*3,180+i*2,200+i,255))
            draw.ellipse((500,650,1300,1450),fill='#815a60');draw.rounded_rectangle((280,1300,1520,2850),radius=200,fill='#ffffff')
            photo_path=assets/(prefix+'-photo.png');photo.save(photo_path);paths.append(photo_path)
            url='/static/__pycache__/'+photo_path.name
            dialog_path=assets/(prefix+'-dialog.png');dialog_path.write_bytes(fixtures.fixture.fixture.image());paths.append(dialog_path)
            dialog_url='/static/__pycache__/'+dialog_path.name
            models=[]
            for name,w,h in [('iphone13',78.87,152.15),('iphone14',78.87,152.15),('iphone14-pro-max',85,166.3),('iphone17-pro',71.63,149.61)]:
                source=ROOT/'.github/tests/fixtures/preview_masks'/f'{name}-print.png';destination=assets/(prefix+'-'+name+'.png');destination.write_bytes(source.read_bytes());paths.append(destination)
                image_url='/static/__pycache__/'+destination.name
                models.append(dict(id=name,name=name,brand='Apple',status=True,case_profiles={'crystal':dict(preview_mask_img=image_url,print_line_img=image_url,print_w=w,print_h=h,print_x=12,print_y=13,print_angle=90)}))
            # An explicitly independent film and incomplete case must not enter the batch.
            catalog=dict(brands=['Apple'],models=models+[dict(id='film',name='Film',status=True,product_type='camera_film'),dict(id='incomplete',name='Incomplete',status=True)],styles=[dict(id='crystal',name='晶彩',status=True,price=790,colors=['白'])])
            app.local_save_json(app.DATA_FILE,catalog);app.local_save_json(app.TEMPLATES_FILE,dict(templates=[],categories=['全部','熱門']));app.local_save_json(app.ASSETS_FILE,copy.deepcopy(app.DEFAULT_ASSETS))
            security_perf._CACHE.clear();engine._MASKS.clear()
            page=browser.new_page(viewport=dict(width=1180,height=900))
            errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.on('dialog',lambda d:d.accept())
            page.goto(base+'/admin')
            if '/login' in page.url:
                if not page.locator('input[name=password]').is_visible():page.locator('#password-toggle').click()
                page.locator('input[name=password]').fill('fan123');page.locator('button[type=submit]').click();page.wait_for_url('**/admin')
            page.locator('.nav button[data-view=templates]').click()
            assert not page.evaluate('!!window.__benfuwanTemplateStackReady')
            page.locator('#view-templates .titlebar button').filter(has_text='建立模板').click()
            poll(page,"() => !!window.visualCanvas && !!document.getElementById('master-open')")
            page.locator('#tpl-name').fill('母版跨型號驗收')
            reports=[];templates=[]
            for kind in ('full-image','photos','text-sticker','subject-title','mixed'):
                template=fixtures.master(kind);template['testAsset']=dialog_url;template.update(id='master-'+kind,name=kind,reference_model_id=models[0]['id'],reference_style_id='crystal')
                for o in template['objects_json']['objects']:
                    if o['type']=='image':o.update(src=url,publicSrc=url,sourceSize=dict(width=1800,height=3000),width=1500 if kind=='full-image' else 1800,height=3000,cropX=150 if kind=='full-image' else 0)
                # Serialize real Fabric objects (including text measurements) as the admin does.
                template=page.evaluate("""async template=>{
                  const c=visualCanvas;c.setDimensions({width:200,height:400});
                  await BenfuwanMultilayer.apply(c,template,{},true);await BenfuwanMultilayer.fonts(c);
                  if(template.name==='mixed'){const pair=await BenfuwanEditableSticker.add(c,{id:'master-dialog',imageSrc:template.objects_json.objects[0].src||template.testAsset,textArea:{x:.12,y:.2,width:.76,height:.5},defaultTextStyle:{text:'Hello',fontFamily:'jf-openhuninn',fontSize:36,minFontSize:12,fill:'#643d4b'}});pair.bg.set({left:100,top:350,scaleX:.14,scaleY:.14});await BenfuwanEditableSticker.rehydrate(c);}
                  c.getObjects().forEach(o=>BenfuwanMultilayer.decorate(o,c));
                  template.objects_json=BenfuwanMultilayer.exportTemplate(c);delete template.testAsset;return template;
                }""",template)
                multilayer_templates.prepare_template(app,template);templates.append(template)
                page.evaluate("""kind=>{document.getElementById('master-evidence')?.remove();const box=document.createElement('div');box.id='master-evidence';box.style='position:fixed;inset:0;background:#fff7fa;z-index:9999;overflow:auto;padding:18px;font:16px sans-serif;color:#563b46;box-sizing:border-box';const title=document.createElement('h2');title.textContent=kind+' · 原始母版 → 舊映射 / 統一適配';box.append(title);document.body.append(box);}""",kind)
                for model in models:
                    target=engine.target_for(catalog,model['id'],'crystal');safe,sha=engine.mask(app,target['profile']['print_line_img']);adapted=engine.adapt(template,target,safe,sha)
                    report=adapted['adaptation_report'];reports.append(dict(kind=kind,model=model['id'],**report))
                    assert report['maxAspectError']<1e-9 and report['relativeDistanceError']<1e-9,report
                    actual=page.evaluate("""async data=>{
                      const {original,adapted,model}=data,box=document.getElementById('master-evidence'),row=document.createElement('section');row.style='display:inline-block;vertical-align:top;padding:10px;width:23%;box-sizing:border-box';const title=document.createElement('h3');title.textContent=model.id+' · '+adapted.adaptation_report.status;title.style='font-size:13px';row.append(title);box.append(row);
                      const metrics=[];
                      for(const [label,template] of [['舊：分軸映射',original],['新：整組等比例',adapted]]){
                        const heading=document.createElement('p');heading.textContent=label;row.append(heading);
                        const el=document.createElement('canvas');row.append(el);
                        const c=new fabric.StaticCanvas(el,{width:Math.round(model.case_profiles.crystal.print_w*3),height:Math.round(model.case_profiles.crystal.print_h*3)});
                        await BenfuwanMultilayer.apply(c,template,{},true);
                        const image=await new Promise(resolve=>fabric.Image.fromURL(model.case_profiles.crystal.print_line_img,resolve));image.set({left:0,top:0,scaleX:c.width/image.width,scaleY:c.height/image.height,absolutePositioned:true});c.clipPath=image;c.renderAll();
                        el.style='width:130px;max-width:100%;height:auto;background:repeating-conic-gradient(#eee 0 25%,white 0 50%) 0/12px 12px';
                        metrics.push(c.getObjects().map(o=>({id:o.layerId,center:o.getCenterPoint(),width:o.getScaledWidth(),height:o.getScaledHeight(),angle:o.angle,scaleX:o.scaleX,scaleY:o.scaleY})));
                      }return metrics;
                    }""",dict(original=template,adapted=adapted,model=model))
                    report['fabricLayers']=actual[1]
                    # Compare actually enlivened/measured Fabric aspect to the immutable master.
                    for item in template['objects_json']['objects']:
                        metrics=next(o for o in actual[1] if o['id']==item['layerId'])
                        if item.get('adaptationRole')=='background-crop':
                            assert abs(metrics['scaleX']/metrics['scaleY']-1)<1e-9,metrics
                            continue
                        g=item['normalizedGeometry'];expected=g['width']*200/(g['height']*400)
                        assert abs(metrics['width']/metrics['height']-expected)<1e-6,(kind,model['id'],item['layerId'],metrics,expected)
                page.evaluate("document.getElementById('master-evidence').scrollTop=0")
                page.locator('#master-evidence').screenshot(path=str(output/(kind+'.png')))
                page.evaluate("document.getElementById('master-evidence').remove()")
            (output/'metrics.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2),encoding='utf-8')
            app.local_save_json(app.TEMPLATES_FILE,dict(templates=templates,categories=['全部','熱門']));security_perf._CACHE.clear()
            # Exercise the actual batch UI, not only the engine API.
            template=templates[2]
            page.evaluate("""async t=>{await loadTemplates(true);await BenfuwanMultilayer.apply(visualCanvas,t,{},true);document.getElementById('tpl-name').value='批次驗收';document.getElementById('tpl-model').value='iphone13';document.getElementById('tpl-style').value='crystal';}""",template)
            page.locator('#master-open').click();poll(page,"() => document.querySelectorAll('.master-target').length===4")
            page.locator('#master-preview-all').click();poll(page,"() => !document.getElementById('master-preview-all').disabled",timeout=60000)
            assert page.locator('.master-target[data-result=success]').count()==4
            reference_picture=page.locator('#master-original').evaluate('e=>e.toDataURL()')
            neighbor=page.locator('.master-target canvas').nth(1).evaluate('e=>e.toDataURL()')
            first=page.locator('.master-target').first;first.locator('summary').click()
            first.locator('input[type=number]').first.fill('2')
            first.get_by_role('button',name='重新預覽此型號').click()
            poll(page,"() => !document.getElementById('master-preview-all').disabled")
            assert first.get_attribute('data-result')=='success'
            assert page.locator('#master-original').evaluate('e=>e.toDataURL()')==reference_picture
            assert page.locator('.master-target canvas').nth(1).evaluate('e=>e.toDataURL()')==neighbor
            for width,height in ((390,844),(768,1024),(1180,900)):
                page.set_viewport_size(dict(width=width,height=height))
                assert page.locator('#master-batch').evaluate('(e)=>e.scrollWidth<=e.clientWidth+2')
                page.locator('#master-batch').screenshot(path=str(output/f'admin-{width}.png'))
            before=copy.deepcopy(app.local_load_json(app.TEMPLATES_FILE,{}))
            page.route('**/api/admin/template-adaptation/save',lambda r:r.fulfill(status=503,content_type='application/json',body='{"status":"error","msg":"隔離測試儲存失敗"}'))
            page.locator('#master-save').click();poll(page,"() => document.getElementById('master-message').textContent.includes('隔離測試儲存失敗') && !document.getElementById('master-save').disabled")
            assert page.locator('#master-message').is_visible() and page.locator('#master-batch').is_visible()
            assert app.local_load_json(app.TEMPLATES_FILE,{})==before
            page.unroute('**/api/admin/template-adaptation/save')
            page.locator('#master-save').click();poll(page,"() => !document.getElementById('master-batch').open",timeout=60000)
            saved=app.local_load_json(app.TEMPLATES_FILE,{})['templates'];assert len(saved)==len(templates)+5
            assert saved[:len(templates)]==before['templates']
            assert len({t['id'] for t in saved})==len(saved)
            # Fresh public browser receives the same authoritative result; batch versions
            # are exact model/style targets, the original master is not modified.
            front=browser.new_page(viewport=dict(width=390,height=844))
            front.on('dialog',lambda d:d.accept());front.goto(base)
            poll(front,"() => !!window.BenfuwanMultilayer && catalogState==='ready'")
            variant=saved[-1];model=models[-1]
            applied=front.evaluate("""async data=>{
              const p=data.model.case_profiles.crystal;ctx={...ctx,modelId:data.model.id,styleId:'crystal',printW:p.print_w,printH:p.print_h,printLineUrl:p.print_line_img,maskUrl:p.preview_mask_img};navigate('page-editor');initCanvas();
              await new Promise(resolve=>applyTemplate(data.template,resolve));
              return {objects:canvas.getObjects().length,hash:canvas.templateState.binding.geometryHash,initial:canvas.templateState.initial.map(o=>o.normalizedGeometry)};
            }""",dict(model=model,template=variant))
            assert applied['objects']==len(variant['objects_json']['objects']) and applied['hash']
            for a,b in zip(applied['initial'],[o['normalizedGeometry'] for o in variant['objects_json']['objects']]):
                assert max(abs(a[k]-b[k]) for k in a)<1e-5,(a,b)
            front.screenshot(path=str(output/'front-390.png'),full_page=True)
            # Actual #71 private-source checkout + deterministic Print Center rebuild.
            # No vendor calls; YUN_PRINT_ENABLED is disabled in this isolated process.
            app.commerce.sync_skus()
            import editable_stickers
            production=[]
            for template in templates:
                body=front.evaluate("""async data=>{
                  const p=data.model.case_profiles.crystal;ctx={...ctx,modelId:data.model.id,styleId:'crystal',modelName:data.model.name,styleName:'晶彩',colorName:'白',printW:p.print_w,printH:p.print_h,printLineUrl:p.print_line_img,maskUrl:p.preview_mask_img};navigate('page-editor');initCanvas();
                  await new Promise(resolve=>applyTemplate(data.template,resolve));await ensureCanvasFonts();
                  const layouts=canvas.getObjects().filter(o=>['text','textbox','i-text'].includes(o.type)).map(o=>({lines:o._textLines.map(a=>a.join('')),left:o.left,top:o.top,fontSize:o.fontSize}));
                  await openPreview();if(!ctx.productionMeta)throw Error('HQ output missing');
                  return {layouts,print:ctx.printBase64,body:{idempotency_key:'master-production-'+crypto.randomUUID(),model_id:ctx.modelId,style_id:ctx.styleId,color_name:'白',customer_name:'isolated master QA',quantity:1,payment_method:'現金',print_file:ctx.printBase64,mockup_file:ctx.mockupBase64,design_json:await BenfuwanDesignSources.prepare(await BenfuwanMultilayer.serialize(canvas,ctx))}};
                }""",dict(template=template,model=models[-1]))
                response=front.request.post(base+'/api/create_order',data=body['body'])
                if response.status!=200:
                    expected=engine.resolve(app,template,catalog,models[-1]['id'],'crystal')['objects_json']['objects']
                    for a in expected:
                        if not a['canEdit']:
                            b=next(o for o in body['body']['design_json']['objects'] if o.get('templateLayerId')==a['layerId'])
                            print('CONTENT_DIFF',[(k,a.get(k),b.get(k)) for k in multilayer_templates.CONTENT_FIELDS if a.get(k)!=b.get(k)],flush=True)
                assert response.status==200,response.text()
                captured=[];render=editable_stickers.render
                def capture(*args,**kwargs):
                    value=render(*args,**kwargs);captured.extend(value[2]);return value
                with mock.patch('editable_stickers.render',side_effect=capture):
                    job=app.print_center.prepare(response.json()['order_id'],'master-QA-'+uuid.uuid4().hex)
                rendered=Image.open(io.BytesIO(app.print_center._download_artwork(job['artwork_path']))).convert('RGBA')
                preview=Image.open(io.BytesIO(base64.b64decode(body['print'].split(',')[1]))).convert('RGBA')
                assert rendered.size==preview.size==(2030,4241)
                rendered.save(output/(template['name']+'-production.png'));preview.save(output/(template['name']+'-front-hq.png'))
                diff=ImageStat.Stat(ImageChops.difference(rendered,preview))
                # Browser engines differ at antialiased edges; require close raster output
                # AND exact text line breaks/positions, not only image dimensions.
                white=Image.new('RGBA',rendered.size,'white')
                visible=ImageStat.Stat(ImageChops.difference(Image.alpha_composite(white,rendered).convert('RGB'),Image.alpha_composite(white,preview).convert('RGB')))
                # RGB underneath fully transparent pixels is unspecified across engines.
                # Compare visible premultiplied color and alpha separately.
                assert max(visible.mean)<.75 and diff.mean[3]<.75,(template['name'],visible.mean,diff.mean[3])
                assert rendered.getpixel((1000,500))[3]==preview.getpixel((1000,500))[3]==0
                for a,b in zip(body['layouts'],captured):
                    assert a['lines']==b['lines'] and abs(a['left']-b['left'])<.0002 and abs(a['top']-b['top'])<.0002,(a,b)
                assert len(body['layouts'])==len(captured)
                production.append(dict(kind=template['name'],dimensions=list(rendered.size),rawChannelMeanAbsoluteError=diff.mean,visibleMeanAbsoluteError=visible.mean,alphaMeanAbsoluteError=diff.mean[3],textLayouts=captured))
            (output/'production.json').write_text(json.dumps(production,ensure_ascii=False,indent=2),encoding='utf-8')
            assert not errors,errors
            print('MASTER_ADAPTATION_BROWSER_OK',browser.browser_type.name,'5 designs x 4 real masks; batch/new-only; frontend exact geometry; 390/768/1180',flush=True)
        finally:
            if page:page.close()
            if front:front.close()
            for key,value in original.items():setattr(app,key,value)
            security_perf._CACHE.clear();engine._MASKS.clear()
            for path in paths:path.unlink(missing_ok=True)


if __name__=='__main__':
    os.environ['YUN_PRINT_ENABLED']='false';os.environ['YUN_AUTO_PRINT_ENABLED']='false'
    from playwright.sync_api import sync_playwright
    helper=runpy.run_path(str(ROOT/'.github/tests/test_ai_editor_webkit.py'))
    server=helper['ServerThread']();server.start();time.sleep(.8)
    try:
        with sync_playwright() as p:
            browser=getattr(p,os.environ.get('BROWSER_ENGINE','webkit')).launch()
            try:master_adaptation_browser_test(browser,f"http://127.0.0.1:{helper['BROWSER_TEST_PORT']}",helper['poll'])
            finally:browser.close()
    finally:server.close()
