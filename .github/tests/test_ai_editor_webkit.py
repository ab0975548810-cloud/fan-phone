import io
import base64
import json
import os
import sys
import copy
import threading
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

os.environ.setdefault('ADMIN_PASSWORD', 'fan123')
os.environ['SESSION_COOKIE_SECURE'] = 'false'
os.environ['PORT'] = '8765'

test_dir = ROOT / '__pycache__' / f'webkit-test-{os.getpid()}'
test_dir.mkdir(parents=True, exist_ok=True)
os.environ['COMMERCE_DB_PATH'] = str(test_dir / 'commerce.sqlite3')
os.environ['ADMIN_PASSKEYS_FILE'] = str(test_dir / 'admin_passkeys.json')
os.environ['WEBAUTHN_RP_ID'] = '127.0.0.1'
os.environ['WEBAUTHN_ORIGIN'] = 'http://127.0.0.1:8765'
os.environ.pop('SUPABASE_URL', None)
os.environ.pop('SUPABASE_SERVICE_ROLE_KEY', None)
import app as app_module
from passkey_auth import install as install_passkey_auth
from security_perf import install as install_security
from supabase_resilience import install as install_supabase_resilience
from quality_perf_patch import install as install_quality_perf
from ai_runtime_patch import install as install_ai_runtime
from admin_perf_patch import install as install_admin_perf
from order_color_patch import install as install_order_colors
from asset_category_patch import install as install_asset_categories
from template_editor_patch import install as install_template_editor
from order_management_patch import install as install_order_management
from commerce_patch import install as install_commerce
from print_center import install as install_print_center

install_passkey_auth(app_module)
install_security(app_module)
install_supabase_resilience(app_module)
install_quality_perf(app_module)
install_ai_runtime(app_module)
install_admin_perf(app_module)
install_order_colors(app_module)
install_asset_categories(app_module)
install_template_editor(app_module)
install_order_management(app_module)
install_commerce(app_module)
install_print_center(app_module)
app_module.app.config['SESSION_COOKIE_SECURE'] = False


def png_bytes(transparent=True):
    bg = (0, 0, 0, 0) if transparent else (255, 255, 255, 255)
    im = Image.new('RGBA', (128, 128), bg)
    d = ImageDraw.Draw(im)
    d.ellipse((25, 18, 103, 110), fill=(240, 80, 120, 255))
    buf = io.BytesIO(); im.save(buf, format='PNG')
    return buf.getvalue()


GOOD = png_bytes(True)
BAD = png_bytes(False)
MASK_FIXTURE_DIR = ROOT / '.github' / 'tests' / 'fixtures' / 'preview_masks'
PRODUCTION_MASK_CONTRACT = json.loads((ROOT / '.github' / 'tests' / 'fixtures' / 'production_shop_data_mask_contract.json').read_text(encoding='utf-8'))


def fixture_data_url(name):
    return 'data:image/png;base64,' + base64.b64encode((MASK_FIXTURE_DIR / name).read_bytes()).decode('ascii')


class ServerThread(threading.Thread):
    daemon = True
    def __init__(self):
        super().__init__()
        self.server = make_server('127.0.0.1', 8765, app_module.app, threaded=True)
    def run(self): self.server.serve_forever()
    def close(self): self.server.shutdown()


def poll(page, fn, timeout=20000, interval=.1):
    end = time.time() + timeout / 1000
    last = None
    while time.time() < end:
        try:
            last = page.evaluate(fn)
            if last: return last
        except Exception:
            pass
        time.sleep(interval)
    raise AssertionError(f'poll timeout; last={last!r}')


def add_front_photo(page, variant=0):
    page.evaluate(f'''() => new Promise((resolve,reject)=>{{
      const c=document.createElement('canvas');c.width=128;c.height=128;const g=c.getContext('2d');
      g.fillStyle='{ '#fff6fa' if variant == 0 else '#e8f4ff' }';g.fillRect(0,0,128,128);
      g.fillStyle='{ '#e05280' if variant == 0 else '#356edb' }';g.fillRect(28,20,72,90);
      fabric.Image.fromURL(c.toDataURL('image/png'),img=>{{
        try{{img.set({{left:canvas.width/2,top:canvas.height/2,originX:'center',originY:'center',role:'photo',originalName:'test-{variant}.png'}});styleEditableObject(img);canvas.add(img);canvas.setActiveObject(img);canvas.requestRenderAll();syncSelection();resolve();}}catch(e){{reject(e)}}
      }});
    }})''')


def assert_front_editor_geometry(page, label):
    metrics = poll(page, """() => {
      if(typeof canvas==='undefined'||!canvas?.wrapperEl||!canvas?.lowerCanvasEl)return false;
      const shell=document.getElementById('canvas-shell'),mask=document.getElementById('phone-mask');
      if(!shell||!mask||getComputedStyle(mask).display==='none')return false;
      const rect=el=>{const r=el.getBoundingClientRect();return {left:r.left,top:r.top,width:r.width,height:r.height}};
      const out={
        logical:{width:canvas.width,height:canvas.height,lowerWidth:canvas.lowerCanvasEl.width,lowerHeight:canvas.lowerCanvasEl.height},
        shell:rect(shell),wrapper:rect(canvas.wrapperEl),lower:rect(canvas.lowerCanvasEl),mask:rect(mask),
        inlineTransform:canvas.wrapperEl.style.transform,computedTransform:getComputedStyle(canvas.wrapperEl).transform
      };
      const lowerRect=canvas.lowerCanvasEl.getBoundingClientRect();
      const pointer=canvas.getPointer({clientX:lowerRect.left+lowerRect.width/2,clientY:lowerRect.top+lowerRect.height/2});
      out.centerPointer={x:pointer.x,y:pointer.y};
      return out.shell.width>0&&out.shell.height>0 ? out : false;
    }""")
    shell = metrics['shell']
    for name in ('wrapper', 'lower', 'mask'):
        rect = metrics[name]
        for key in ('left', 'top', 'width', 'height'):
            assert abs(rect[key] - shell[key]) <= 1, (label, name, key, metrics)
    assert metrics['inlineTransform'] in ('', 'none'), (label, metrics)
    assert metrics['computedTransform'] == 'none', (label, metrics)
    assert metrics['logical'] == {'width':240,'height':480,'lowerWidth':240,'lowerHeight':480}, (label, metrics)
    assert abs(metrics['centerPointer']['x'] - 120) <= 1 and abs(metrics['centerPointer']['y'] - 240) <= 1, (label, metrics)
    print('FRONT_EDITOR_DISPLAY_GEOMETRY_OK', label, round(shell['width'], 2), round(shell['height'], 2))
    return metrics


def front_test(browser, base):
    # Start with a constrained iPhone viewport so initCanvas installs a
    # transform below 1, then exercise the responsive owner's cssOnly fit.
    page = browser.new_page(viewport={'width': 390, 'height': 600})
    responses = [GOOD, BAD]
    page.route('**/api/ai/remove-background', lambda route: route.fulfill(status=200, body=responses.pop(0) if responses else GOOD, content_type='image/png'))
    page.goto(base + '/', wait_until='domcontentloaded')
    poll(page, "() => typeof fabric !== 'undefined' && typeof initCanvas === 'function' && !!window.BenfuwanAiRemoveV2 && !!window.removeBackgroundForActive && !!window.BenfuwanEditorAccess && !!window.BenfuwanOrderPayload && !!window.BenfuwanPrintMask && !!window.BenfuwanProductionHQ")
    # Let the app finish its own initial catalog load/navigation before forcing
    # the editor. Otherwise the startup async task can switch pages after the
    # test has entered the editor and produce a false zero-geometry failure.
    poll(page, "() => typeof shopData !== 'undefined' && Array.isArray(shopData?.models) && shopData.models.length > 0", timeout=10000)
    mask_normalization = page.evaluate("""async () => {
      const source=document.createElement('canvas');source.width=12;source.height=20;
      const g=source.getContext('2d');g.clearRect(0,0,12,20);g.fillStyle='#fff';g.fillRect(2,3,8,14);g.clearRect(4,6,4,6);
      const image=await new Promise((resolve,reject)=>{const i=new Image();i.onload=()=>resolve(i);i.onerror=reject;i.src=source.toDataURL('image/png')});
      const normalized=window.BenfuwanPrintMask.normalizeMaskImage(image);
      const output=window.BenfuwanPrintMask.resampleMask(normalized,80,140);
      const alpha=output.getContext('2d').getImageData(0,0,80,140).data;
      let left=80,top=140,right=-1,bottom=-1;
      for(let y=0;y<140;y++)for(let x=0;x<80;x++)if(alpha[(y*80+x)*4+3]>0){left=Math.min(left,x);top=Math.min(top,y);right=Math.max(right,x);bottom=Math.max(bottom,y)}
      return {
        bounds:normalized.bounds,
        artworkCrop:window.BenfuwanPrintMask.productionCropForMask(normalized,240,480),
        outputBounds:{left,top,right,bottom},
        holeAlpha:alpha[(60*80+40)*4+3],
        dimensions:[window.BenfuwanProductionHQ.pixelsForMm(71.63),window.BenfuwanProductionHQ.pixelsForMm(149.61)]
      };
    }""")
    assert mask_normalization['bounds'] == {'left':2,'top':3,'right':9,'bottom':16,'width':8,'height':14}, mask_normalization
    assert mask_normalization['artworkCrop'] == {'left':40,'top':72,'width':160,'height':336}, mask_normalization
    assert mask_normalization['outputBounds'] == {'left':0,'top':0,'right':79,'bottom':139}, mask_normalization
    assert mask_normalization['holeAlpha'] == 0, mask_normalization
    assert mask_normalization['dimensions'] == [2030, 4241], mask_normalization
    print('FRONT_PRINT_MASK_NORMALIZATION_HOLE_DIMENSIONS_OK', mask_normalization)
    fixture_models = PRODUCTION_MASK_CONTRACT['models']
    crystal_style = {'id':'style_1789287807818','name':'晶彩磁吸防摔殼','status':True}
    profile_audit = page.evaluate("({models,styles}) => window.BenfuwanModelProfile.audit(models,styles)", {'models':fixture_models,'styles':[crystal_style]})
    expected_audit = PRODUCTION_MASK_CONTRACT['expected']
    assert profile_audit['activeModels'] == expected_audit['active'] and profile_audit['activeStyles'] == 1, profile_audit
    assert len(profile_audit['configured']) == expected_audit['configured'], profile_audit
    assert len(profile_audit['incomplete']) == expected_audit['incomplete'], profile_audit
    assert set(profile_audit['configured']) == {
        'model_apple_13:style_1789287807818','model_apple_14:style_1789287807818',
        'model_apple_14_pro_max:style_1789287807818','model_apple_17_pro:style_1789287807818'
    }, profile_audit
    blocked_profile = page.evaluate("""({models,crystal}) => {
      shopData.models=models;shopData.styles=[crystal];activeBrand='';resetDesignState(false);renderModels();
      const model=models.find(row=>row.id==='model_apple_11'),selected=selectModel(model),styled=selectStyle(crystal);
      return {selected,styled,modelId:ctx.modelId,styleId:ctx.styleId,modelNext:document.getElementById('model-next').disabled,styleNext:document.getElementById('style-next').disabled,badges:document.querySelectorAll('.bf-style-unconfigured .bf-style-config-badge').length,toast:document.getElementById('toast').textContent};
    }""", {'models':fixture_models,'crystal':crystal_style})
    assert blocked_profile['selected'] is True and blocked_profile['styled'] is False, blocked_profile
    assert blocked_profile['modelId'] == 'model_apple_11' and blocked_profile['styleId'] is None, blocked_profile
    assert not blocked_profile['modelNext'] and blocked_profile['styleNext'] and blocked_profile['badges'] == 1 and '尚未完成生產設定' in blocked_profile['toast'], blocked_profile
    print('FRONT_MODEL_STYLE_PROFILE_AUDIT_FAIL_CLOSED_OK', profile_audit, blocked_profile)
    legacy_crystal_only = page.evaluate("""({models,crystal}) => {
      const model=models.find(row=>row.id==='model_apple_14_pro_max');
      const selected=selectModel(model);
      const styled=selectStyle(crystal);
      const mirror=selectStyle({id:'style_mirror',name:'鏡面殼',price:390,mask_img:'style-preview',line_img:'style-print',print_w:99,print_h:199,colors:[]});
      return {selected,styled,mirror,styleId:ctx.styleId,maskUrl:ctx.maskUrl,printLineUrl:ctx.printLineUrl,printW:ctx.printW,printH:ctx.printH};
    }""", {'models':fixture_models,'crystal':crystal_style})
    assert legacy_crystal_only == {
        'selected': True,
        'styled': True,
        'mirror': False,
        'styleId': 'style_1789287807818',
        'maskUrl': 'fixture://iphone14-pro-max-preview.png',
        'printLineUrl': 'fixture://iphone14-pro-max-print.png',
        'printW': 85,
        'printH': 166.3,
    }, legacy_crystal_only
    print('FRONT_LEGACY_ROOT_CRYSTAL_ONLY_NO_STYLE_FALLBACK_OK', legacy_crystal_only)

    style_isolation = page.evaluate("""model => {
      const configured={...model,case_profiles:{
        crystal:{preview_mask_img:'fixture://crystal-preview',print_line_img:'fixture://crystal-print',print_w:70,print_h:140,print_x:1,print_y:2},
        mirror:{preview_mask_img:'fixture://mirror-preview',print_line_img:'fixture://mirror-print',print_w:75,print_h:150,print_x:3,print_y:4}
      }};
      const crystal={id:'crystal',name:'晶彩',colors:['透明','粉']},mirror={id:'mirror',name:'鏡面',colors:['銀','黑']};
      shopData.models=[configured];shopData.styles=[crystal,mirror];selectModel(configured);selectStyle(crystal);
      const first={mask:ctx.maskUrl,line:ctx.printLineUrl,w:ctx.printW,h:ctx.printH,x:ctx.printX,y:ctx.printY};
      selectStyle(mirror);const second={mask:ctx.maskUrl,line:ctx.printLineUrl,w:ctx.printW,h:ctx.printH,x:ctx.printX,y:ctx.printY};
      return {first,second,crystalColors:window.BenfuwanModelColors?.colorsFor?.(crystal,configured.id)||crystal.colors};
    }""", fixture_models[0])
    assert style_isolation['first'] == {'mask':'fixture://crystal-preview','line':'fixture://crystal-print','w':70,'h':140,'x':1,'y':2}, style_isolation
    assert style_isolation['second'] == {'mask':'fixture://mirror-preview','line':'fixture://mirror-print','w':75,'h':150,'x':3,'y':4}, style_isolation
    print('FRONT_TWO_STYLES_INDEPENDENT_PROFILE_COLOR_SHARED_OK', style_isolation)
    page.evaluate("({models,crystal}) => {shopData.models=models;shopData.styles=[crystal];resetDesignState(false)}", {'models':fixture_models,'crystal':crystal_style})

    mask_fixtures = {
        'iphone13': {'preview': fixture_data_url('iphone13-preview.png'), 'print': fixture_data_url('iphone13-print.png')},
        'iphone14': {'preview': fixture_data_url('iphone14-preview.png'), 'print': fixture_data_url('iphone14-print.png')},
        'iphone14ProMax': {'preview': fixture_data_url('iphone14-pro-max-preview.png'), 'print': fixture_data_url('iphone14-pro-max-print.png')},
        'iphone17Pro': {'preview': fixture_data_url('iphone17-pro-preview.png'), 'print': fixture_data_url('iphone17-pro-print.png')},
    }
    source_contract = page.evaluate("""async fixtures => {
      const load=src=>new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=reject;image.src=src});
      const alphaStats=canvas=>{
        const {width,height}=canvas,g=canvas.getContext('2d',{willReadFrequently:true}),p=g.getImageData(0,0,width,height).data;
        let visible=0,transparent=0,left=width,top=height,right=-1,bottom=-1;
        for(let y=0;y<height;y++)for(let x=0;x<width;x++){const a=p[(y*width+x)*4+3];if(a>24){visible++;left=Math.min(left,x);top=Math.min(top,y);right=Math.max(right,x);bottom=Math.max(bottom,y)}else transparent++}
        let insideTransparent=0;if(right>=left&&bottom>=top)for(let y=top;y<=bottom;y++)for(let x=left;x<=right;x++)if(p[(y*width+x)*4+3]<=24)insideTransparent++;
        return {visible,transparent,insideTransparent,bounds:{left,top,right,bottom}};
      };
      const verify=async(pair)=>{
        const preview=await load(pair.preview),print=await load(pair.print),target=[240,480];
        const mapped=window.BenfuwanPrintMask.mapOverlayToPrintFrame(preview,...target);
        const expected=document.createElement('canvas');expected.width=target[0];expected.height=target[1];
        const expectedContext=expected.getContext('2d',{willReadFrequently:true});expectedContext.drawImage(preview,0,0,...target);
        const a=expectedContext.getImageData(0,0,...target).data;
        const b=mapped.canvas.getContext('2d').getImageData(0,0,mapped.canvas.width,mapped.canvas.height).data;
        let changed=0;for(let i=0;i<a.length;i++)if(a[i]!==b[i])changed++;
        const printTarget=window.BenfuwanPrintMask.resampleMask(print,...target);
        return {preview:[preview.naturalWidth,preview.naturalHeight],print:[print.naturalWidth,print.naturalHeight],output:[mapped.canvas.width,mapped.canvas.height],frame:mapped.frame,changed,previewAlpha:alphaStats(mapped.canvas),printAlpha:alphaStats(printTarget)};
      };
      const results=Object.fromEntries(await Promise.all(Object.entries(fixtures).map(async([name,pair])=>[name,await verify(pair)])));
      const empty=document.createElement('canvas');empty.width=20;empty.height=40;
      results.invalidTransparent=window.BenfuwanPrintMask.mapOverlayToPrintFrame(empty,240,480)===null;
      return results;
    }""", mask_fixtures)
    expected_sources = {
        'iphone13': ([186,359], [186,359]),
        'iphone14': ([186,359], [186,359]),
        'iphone14ProMax': ([172,336], [172,336]),
        'iphone17Pro': ([188,368], [90,175]),
    }
    for name, (preview_source, print_source) in expected_sources.items():
        result = source_contract[name]
        assert result['preview'] == preview_source and result['print'] == print_source, (name, result)
        assert result['output'] == [240,480] and result['frame'] == {'left':0,'top':0,'width':240,'height':480}, (name, result)
        assert result['changed'] == 0, (name, result)
        assert result['previewAlpha']['visible'] > 0 and result['printAlpha']['visible'] > 0, (name, result)
        assert result['printAlpha']['transparent'] > 0 and result['printAlpha']['insideTransparent'] > 0, (name, result)
    assert source_contract['invalidTransparent'] is True, source_contract
    print('FRONT_FOUR_MODEL_FULL_FRAME_TARGET_CONTRACT_OK', source_contract)

    production_crop_contract = page.evaluate("""async ({fixtures,models}) => {
      const ids={iphone13:'model_apple_13',iphone14:'model_apple_14',iphone14ProMax:'model_apple_14_pro_max',iphone17Pro:'model_apple_17_pro'};
      const load=src=>new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=reject;image.src=src});
      const robustOpaquePoint=canvas=>{
        const g=canvas.getContext('2d',{willReadFrequently:true}),p=g.getImageData(0,0,canvas.width,canvas.height).data,radius=3;
        const opaque=(x,y)=>p[(y*canvas.width+x)*4+3]>240;
        let best=null,bestDistance=Infinity;
        for(let y=radius;y<canvas.height-radius;y++)for(let x=radius;x<canvas.width-radius;x++){
          let solid=true;
          for(let yy=y-radius;solid&&yy<=y+radius;yy++)for(let xx=x-radius;xx<=x+radius;xx++)if(!opaque(xx,yy)){solid=false;break}
          if(!solid)continue;
          const distance=(x-canvas.width*.67)**2+(y-canvas.height*.67)**2;
          if(distance<bestDistance){best={x,y,radius};bestDistance=distance}
        }
        if(!best)throw new Error('production fixture has no opaque landmark area');
        return best;
      };
      const transparentInside=canvas=>{
        const p=canvas.getContext('2d',{willReadFrequently:true}).getImageData(0,0,canvas.width,canvas.height).data;
        let inside=0;
        for(let y=1;y<canvas.height-1;y++)for(let x=1;x<canvas.width-1;x++)if(p[(y*canvas.width+x)*4+3]===0)inside++;
        return inside;
      };
      const results={};
      for(const [name,pair] of Object.entries(fixtures)){
        const print=await load(pair.print),mask=window.BenfuwanPrintMask.normalizeMaskImage(print);
        const editorWidth=240,editorHeight=480,outputWidth=480,outputHeight=960;
        const crop=window.BenfuwanPrintMask.productionCropForMask(mask,editorWidth,editorHeight);
        const landmark=robustOpaquePoint(mask.canvas);
        const centerX=(mask.bounds.left+landmark.x+.5)/mask.sourceWidth*editorWidth;
        const centerY=(mask.bounds.top+landmark.y+.5)/mask.sourceHeight*editorHeight;
        const markerWidth=(landmark.radius*2+1)/mask.sourceWidth*editorWidth;
        const markerHeight=(landmark.radius*2+1)/mask.sourceHeight*editorHeight;
        const element=document.createElement('canvas');
        const artwork=new fabric.StaticCanvas(element,{width:editorWidth,height:editorHeight,renderOnAddRemove:false});
        artwork.add(new fabric.Rect({left:centerX,top:centerY,originX:'center',originY:'center',width:markerWidth,height:markerHeight,fill:'#ff0000',strokeWidth:0,objectCaching:false}));
        artwork.renderAll();
        const output=window.BenfuwanPrintMask.renderPrint(artwork,mask,outputWidth,outputHeight);
        const pixels=output.getContext('2d',{willReadFrequently:true}).getImageData(0,0,outputWidth,outputHeight).data;
        let count=0,sumX=0,sumY=0;
        for(let y=0;y<outputHeight;y++)for(let x=0;x<outputWidth;x++){
          const offset=(y*outputWidth+x)*4;
          if(pixels[offset]>180&&pixels[offset+1]<80&&pixels[offset+2]<80&&pixels[offset+3]>40){count++;sumX+=x+.5;sumY+=y+.5}
        }
        if(!count)throw new Error('production landmark was clipped');
        const expectedX=(landmark.x+.5)/mask.bounds.width*outputWidth;
        const expectedY=(landmark.y+.5)/mask.bounds.height*outputHeight;
        const model=models.find(row=>row.id===ids[name]);
        results[name]={
          source:[mask.sourceWidth,mask.sourceHeight],bounds:mask.bounds,crop,
          landmark:{expected:[expectedX,expectedY],actual:[sumX/count,sumY/count],pixels:count},
          cameraTransparent:transparentInside(mask.canvas),
          hq:[window.BenfuwanProductionHQ.pixelsForMm(model.print_w),window.BenfuwanProductionHQ.pixelsForMm(model.print_h)]
        };
        artwork.dispose();output.width=output.height=1;
      }
      return results;
    }""", {'fixtures': mask_fixtures, 'models': fixture_models})
    expected_hq_dimensions = {
        'iphone13': [2236,4313],
        'iphone14': [2236,4313],
        'iphone14ProMax': [2409,4714],
        'iphone17Pro': [2030,4241],
    }
    for name, result in production_crop_contract.items():
        expected_x, expected_y = result['landmark']['expected']
        actual_x, actual_y = result['landmark']['actual']
        assert abs(actual_x - expected_x) <= 3 and abs(actual_y - expected_y) <= 3, (name, result)
        assert result['landmark']['pixels'] > 20 and result['cameraTransparent'] > 0, (name, result)
        assert result['hq'] == expected_hq_dimensions[name], (name, result)
    print('FRONT_FOUR_MODEL_PRODUCTION_SHARED_CROP_LANDMARK_CAMERA_HQ_OK', production_crop_contract)

    page.evaluate("""() => {navigate('page-editor');initCanvas();editorHasSession=true;window.BenfuwanEditorAccess?.fitCanvas?.()}""")
    editor_contract = page.evaluate("""async ({fixtures,models}) => {
      const ids={iphone13:'model_apple_13',iphone14:'model_apple_14',iphone14ProMax:'model_apple_14_pro_max',iphone17Pro:'model_apple_17_pro'};
      const alphaStats=canvas=>{const p=canvas.getContext('2d',{willReadFrequently:true}).getImageData(0,0,canvas.width,canvas.height).data;let visible=0,transparent=0;for(let i=3;i<p.length;i+=4)(p[i]>24?visible++:transparent++);return {visible,transparent}};
      const results={};
      for(const [name,pair] of Object.entries(fixtures)){
        const model=models.find(row=>row.id===ids[name]);
        ctx.modelId=model.id;ctx.modelName=model.name;ctx.maskUrl=pair.preview;ctx.printLineUrl=pair.print;ctx.printW=model.print_w;ctx.printH=model.print_h;
        const clip=await window.BenfuwanPrintMask.ensureClip(canvas,pair.print,true);
        const overlay=await window.BenfuwanPrintMask.ensurePreviewOverlay(canvas,pair.preview,true);
        const guide=window.BenfuwanPrintMask.renderEditorGuide(clip.image,canvas.width,canvas.height);
        const review=window.BenfuwanPrintMask.renderPreviewFallback(clip.image,canvas.width,canvas.height);
        review.getContext('2d').drawImage(overlay.overlay.canvas,0,0,review.width,review.height);
        results[name]={target:[canvas.width,canvas.height],clipSource:[clip.image.naturalWidth,clip.image.naturalHeight],clipTarget:[Math.round(clip.clip.getScaledWidth()),Math.round(clip.clip.getScaledHeight())],overlaySource:[overlay.image.naturalWidth,overlay.image.naturalHeight],overlayTarget:[overlay.overlay.canvas.width,overlay.overlay.canvas.height],guide:[guide.width,guide.height],review:[review.width,review.height],guideAlpha:alphaStats(guide),reviewAlpha:alphaStats(review)};
      }
      return results;
    }""", {'fixtures': mask_fixtures, 'models': fixture_models})
    for name, result in editor_contract.items():
        assert result['clipTarget'] == result['target'] and result['overlayTarget'] == result['target'], (name, result)
        assert result['guide'] == result['target'] and result['review'] == result['target'], (name, result)
        assert result['guideAlpha']['visible'] > 0 and result['guideAlpha']['transparent'] > 0, (name, result)
        assert result['reviewAlpha']['visible'] > 0 and result['reviewAlpha']['transparent'] > 0, (name, result)
    print('FRONT_FOUR_MODEL_EDITOR_REVIEW_TARGET_CONSISTENCY_OK', editor_contract)

    page.evaluate("""fixtures => {
      ctx.modelId='model_apple_14_pro_max';ctx.modelName='iPhone 14 Pro Max';ctx.styleId='style_crystal';ctx.styleName='晶彩磁吸防摔殼';
      ctx.printW=80;ctx.printH=160;ctx.maskUrl=fixtures.iphone14ProMax.preview;ctx.printLineUrl=fixtures.iphone14ProMax.print;
      initCanvas();editorHasSession=true;window.BenfuwanEditorAccess?.fitCanvas?.();applyCaseBoundaryClip();
    }""", mask_fixtures)
    overlay_alignment = poll(page, """() => {
      const mask=document.getElementById('phone-mask');
      if(!mask?.complete||mask.naturalWidth!==240||mask.naturalHeight!==480||getComputedStyle(mask).display==='none')return false;
      return {size:[mask.naturalWidth,mask.naturalHeight],display:getComputedStyle(mask).display};
    }""")
    assert overlay_alignment == {'size':[240,480],'display':'block'}, overlay_alignment
    print('FRONT_IPHONE_14_PRO_MAX_SOURCE_FRAME_OVERLAY_OK', overlay_alignment)

    page.evaluate("""fixtures => {
      ctx.modelId='model_apple_17_pro';ctx.modelName='iPhone 17 Pro';ctx.maskUrl=fixtures.iphone17Pro.preview;ctx.printLineUrl=fixtures.iphone17Pro.print;applyCaseBoundaryClip();
    }""", mask_fixtures)
    mixed_resolution = poll(page, """() => {
      const overlay=document.getElementById('phone-mask'),guide=document.getElementById('print-area-guide');
      if(getComputedStyle(overlay).display==='none'||overlay.naturalWidth!==240||overlay.naturalHeight!==480||!guide?.complete||getComputedStyle(guide).display==='none')return false;
      return {overlay:[overlay.naturalWidth,overlay.naturalHeight],guide:[guide.naturalWidth,guide.naturalHeight],display:getComputedStyle(overlay).display};
    }""")
    assert mixed_resolution == {'overlay':[240,480],'guide':[240,480],'display':'block'}, mixed_resolution
    page.evaluate("""fixtures => {ctx.modelId='model_apple_14_pro_max';ctx.modelName='iPhone 14 Pro Max';ctx.maskUrl=fixtures.iphone14ProMax.preview;ctx.printLineUrl=fixtures.iphone14ProMax.print;applyCaseBoundaryClip()}""", mask_fixtures)
    poll(page, "() => {const m=document.getElementById('phone-mask');return getComputedStyle(m).display!=='none'&&m.naturalWidth===240&&m.naturalHeight===480}")
    print('FRONT_IPHONE_17_PRO_MIXED_RASTER_FULL_FRAME_OK', mixed_resolution)
    assert_front_editor_geometry(page, 'iphone-constrained-unselected')
    add_front_photo(page, 0)
    page.evaluate("() => window.BenfuwanEditorAccess.fitCanvas()")
    assert_front_editor_geometry(page, 'iphone-constrained-selected')
    page.evaluate("""() => {
      const o=canvas.getActiveObject();o.set({angle:27,scaleX:.82,scaleY:.82});o.setCoords();canvas.requestRenderAll();
    }""")
    assert_front_editor_geometry(page, 'iphone-object-transform')
    page.set_viewport_size({'width':390,'height':844})
    page.evaluate("() => window.BenfuwanEditorAccess.fitCanvas()")
    assert_front_editor_geometry(page, 'iphone-expanded-selected')
    layer_listeners = page.evaluate("""() => {
      const watched=new Set(['touchmove','touchend','touchcancel','mousemove','mouseup','pointermove','pointerup','pointercancel']);
      const active=new Map(),nativeAdd=document.addEventListener,nativeRemove=document.removeEventListener;
      document.addEventListener=function(type,listener,options){
        if(watched.has(type))active.set(listener,type);
        return nativeAdd.call(this,type,listener,options);
      };
      document.removeEventListener=function(type,listener,options){
        if(watched.has(type))active.delete(listener);
        return nativeRemove.call(this,type,listener,options);
      };
      try{
        renderLayerList();const once=active.size;
        for(let i=0;i<20;i++)renderLayerList();
        return {once,after:active.size};
      }finally{
        document.addEventListener=nativeAdd;document.removeEventListener=nativeRemove;
      }
    }""")
    assert layer_listeners['once'] > 0 and layer_listeners['after'] == layer_listeners['once'], layer_listeners
    print('FRONT_LAYER_LISTENER_OK', layer_listeners['after'])
    metrics = poll(page, """() => {
      const pe=document.getElementById('page-editor'),ob=document.getElementById('object-bar'),tb=document.querySelector('#page-editor>.toolbar'),ws=document.querySelector('#page-editor>.workspace'),shell=document.getElementById('canvas-shell'),row=document.querySelector('#page-editor>.bf-editor-action-row');
      if(!pe||!ob||!tb||!ws||!shell||!row||getComputedStyle(pe).display==='none')return false;
      const a=ob.getBoundingClientRect(),b=tb.getBoundingClientRect(),c=ws.getBoundingClientRect(),d=shell.getBoundingClientRect(),r=row.getBoundingClientRect();
      const left=row.querySelector('.editor-float:not(.right)'),right=row.querySelector('.editor-float.right');
      const out={show:ob.classList.contains('show'),objectTop:a.top,objectBottom:a.bottom,toolbarTop:b.top,workspaceBottom:c.bottom,shellBottom:d.bottom,actionTop:r.top,actionBottom:r.bottom,actionHeight:r.height,toolbarVisible:getComputedStyle(tb).visibility,toolbarPointer:getComputedStyle(tb).pointerEvents,position:getComputedStyle(ob).position,leftPosition:left?getComputedStyle(left).position:'',rightPosition:right?getComputedStyle(right).position:'',workspaceHasFloat:!!ws.querySelector('.editor-float')};
      return out.show && out.actionHeight>=44 && a.height>0 && b.height>0 && c.height>0 ? out : false;
    }""", timeout=10000)
    assert metrics['show'] and metrics['toolbarVisible']=='visible' and metrics['toolbarPointer']!='none', metrics
    assert metrics['position'] == 'relative', metrics
    assert metrics['workspaceBottom'] <= metrics['actionTop'] + 2, metrics
    assert metrics['shellBottom'] <= metrics['workspaceBottom'] + 2, metrics
    assert metrics['actionBottom'] <= metrics['objectTop'] + 2, metrics
    assert 44 <= metrics['actionHeight'] <= 56, metrics
    assert metrics['leftPosition'] == 'relative' and metrics['rightPosition'] == 'relative', metrics
    assert not metrics['workspaceHasFloat'], metrics
    assert metrics['objectBottom'] <= metrics['toolbarTop'] + 8, metrics
    print('FRONT_ACTION_ROW_OK', metrics['actionTop'], metrics['actionBottom'])

    payload = page.evaluate("""() => {
      const huge={background:'#fff',objects:[{type:'image',role:'photo',left:120,top:240,angle:8,src:'data:image/png;base64,'+'A'.repeat(2200000),originalName:'huge.png'}]};
      const compact=window.BenfuwanOrderPayload.compactDesign(huge),txt=JSON.stringify(compact);
      return {raw:JSON.stringify(huge).length,compact:txt.length,embedded:txt.includes('data:image'),role:compact.objects?.[0]?.role,left:compact.objects?.[0]?.left};
    }""")
    assert payload['raw'] > 2_000_000 and payload['compact'] < 1_500_000 and not payload['embedded'], payload
    assert payload['role'] == 'photo' and payload['left'] == 120, payload
    print('FRONT_ORDER_PAYLOAD_OK', payload['raw'], payload['compact'])

    assert page.evaluate("""() => {const tb=document.querySelector('#page-editor>.toolbar');const b=[...tb.querySelectorAll('button')].find(x=>/openSheet|openTemplates|layer|sticker/i.test(x.getAttribute('onclick')||''))||tb.querySelector('button');b.dispatchEvent(new MouseEvent('click',{bubbles:true,cancelable:true}));window.BenfuwanEditorAccess.fitCanvas();return !canvas.getActiveObject();}"""), 'main toolbar did not release selection'
    assert_front_editor_geometry(page, 'iphone-expanded-unselected')
    page.evaluate("""() => {const o=canvas.getObjects().find(x=>x.role==='photo');canvas.setActiveObject(o);canvas.requestRenderAll();syncSelection();window.BenfuwanEditorAccess.fitCanvas();}""")
    assert_front_editor_geometry(page, 'iphone-expanded-reselected')
    page.evaluate("() => window.removeBackgroundForActive()")
    good = page.evaluate("""() => {const o=canvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved,role:o?.role,outline:String(o?.aiOutlineSource||'').startsWith('data:image/'),count:canvas.getObjects().filter(x=>x.role==='photo').length};}""")
    assert good == {'ai':True,'role':'photo','outline':True,'count':1}, good
    add_front_photo(page, 1)
    page.evaluate("() => window.removeBackgroundForActive()")
    bad = page.evaluate("""() => {const o=canvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved,name:o?.originalName,count:canvas.getObjects().filter(x=>x.role==='photo').length};}""")
    assert bad['ai'] is False and bad['name']=='test-1.png' and bad['count']==2, bad
    page.set_viewport_size({'width':768,'height':1024})
    page.evaluate("() => window.BenfuwanEditorAccess.fitCanvas()")
    assert_front_editor_geometry(page, 'ipad-selected')
    page.evaluate("""async () => {
      await openPreview();
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
    }""")
    preview_state = page.evaluate("() => ({active:document.getElementById('page-preview')?.classList.contains('active'),print:!!ctx.printBase64,mockup:!!ctx.mockupBase64})")
    assert preview_state == {'active':True,'print':True,'mockup':True}, preview_state
    preview = page.evaluate("""() => Promise.all([ctx.printBase64,ctx.mockupBase64].map(src=>new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve({width:img.naturalWidth,height:img.naturalHeight});img.onerror=reject;img.src=src}))).then(([print,mockup])=>({print,mockup,logical:{width:canvas.width,height:canvas.height}}))""")
    assert preview == {'print':{'width':2268,'height':4535},'mockup':{'width':600,'height':1200},'logical':{'width':240,'height':480}}, preview
    production_meta = page.evaluate("() => structuredClone(ctx.productionMeta)")
    assert production_meta['dpi'] == 720 and production_meta['width'] == 2268 and production_meta['height'] == 4535, production_meta
    assert production_meta['maskBounds'] == {'left':10,'top':8,'right':161,'bottom':327,'width':152,'height':320}, production_meta
    preview_alpha = page.evaluate("""() => new Promise((resolve,reject)=>{
      const img=new Image();img.onload=()=>{
        const c=document.createElement('canvas');c.width=img.naturalWidth;c.height=img.naturalHeight;
        const g=c.getContext('2d');g.drawImage(img,0,0);const p=g.getImageData(0,0,c.width,c.height).data;
        const alpha=(x,y)=>p[(y*c.width+x)*4+3];
        resolve({outside:alpha(0,0),frame:alpha(300,14),body:alpha(349,714),camera:alpha(157,179)});
      };img.onerror=reject;img.src=ctx.mockupBase64;
    })""")
    assert preview_alpha['outside'] == 0 and preview_alpha['frame'] > 0 and preview_alpha['body'] > 0 and preview_alpha['camera'] == 0, preview_alpha
    print('FRONT_PREVIEW_SOURCE_FRAME_AND_CAMERA_HOLE_OK', preview_alpha)
    print('FRONT_EDITOR_PREVIEW_DIMENSIONS_OK', preview)
    hq_race = page.evaluate("""async () => {
      const hq=ctx.printBase64,meta=structuredClone(ctx.productionMeta);
      await idbDel('cart');cartItem=null;
      let release;const blocked=new Promise(resolve=>{release=resolve});
      window.BenfuwanProductionHQ.begin(ctx,async()=>{await blocked;ctx.printBase64=hq;ctx.productionMeta=meta;return meta});
      ctx.printBase64='preview-fallback';ctx.productionMeta=null;
      const pending=confirmDesignToCart();
      await new Promise(resolve=>setTimeout(resolve,0));
      const before=await idbGet('cart');
      release();await pending;
      const after=await idbGet('cart');
      const result={before:before===null,hq:after?.printBase64===hq,ppm:after?.productionMeta?.ppm,page:document.getElementById('page-cart')?.classList.contains('active')};
      await idbDel('cart');cartItem=null;updateCartBadge();
      return result;
    }""")
    assert hq_race['before'] and hq_race['hq'] and abs(hq_race['ppm'] - 28.3464567) < 0.0001 and hq_race['page'], hq_race
    print('FRONT_HQ_CART_RACE_OK', hq_race)
    print('FRONT_WEBKIT_OK')
    page.close()


def checkout_test(browser, base):
    page = browser.new_page()
    sent = []
    def intercept(route):
        sent.append(route.request.post_data_json)
        if len(sent) == 1:
            # Server commits, browser receives a simulated transport failure.
            result = route.fetch()
            assert result.status == 200, result.text()
            route.abort('failed')
        else:
            route.continue_()
    page.route('**/api/create_order', intercept)
    page.goto(base + '/', wait_until='domcontentloaded')
    poll(page, "() => !!window.BenfuwanOrderPayload && typeof shopData !== 'undefined' && shopData.models?.length")
    page.evaluate("""async () => {
      const c=document.createElement('canvas');c.width=2;c.height=2;
      cartItem={modelId:shopData.models[0].id,styleId:shopData.styles[0].id,modelName:shopData.models[0].name,styleName:shopData.styles[0].name,quantity:1,payment:'現金',printBase64:c.toDataURL(),designJson:{}};
      await idbSet('cart',cartItem);document.getElementById('form-surname').value='測試';await submitOrder();
    }""")
    page.wait_for_timeout(100)
    assert sent == [], sent
    print('FRONT_SUBMIT_REJECTS_NON_HQ_CART_OK')
    page.evaluate("""async () => {
      const c=document.createElement('canvas');c.width=2;c.height=2;
      cartItem={modelId:shopData.models[0].id,styleId:shopData.styles[0].id,modelName:shopData.models[0].name,styleName:shopData.styles[0].name,colorName:'透明',quantity:1,payment:'現金',printBase64:c.toDataURL(),productionMeta:{ppm:window.BenfuwanProductionHQ.PPM,dpi:720,width:2,height:2},designJson:{}};
      await idbSet('cart',cartItem);document.getElementById('form-surname').value='測試';await submitOrder();
    }""")
    assert len(sent) == 1 and sent[0]['idempotency_key']
    page.reload(wait_until='domcontentloaded')
    poll(page, "() => !!window.BenfuwanOrderPayload && typeof shopData !== 'undefined' && shopData.models?.length")
    page.evaluate("async () => {document.getElementById('form-surname').value='測試';await submitOrder()}")
    assert len(sent) == 2 and sent[0] == sent[1], sent
    assert page.evaluate("() => !!document.getElementById('success-id').textContent")
    assert page.evaluate("() => idbGet('cart')") is None
    print('CHECKOUT_LOST_RESPONSE_RELOAD_OK')
    page.close()


def admin_test(browser, base):
    page = browser.new_page(viewport={'width': 1180, 'height': 900})
    page.add_init_script("""(() => {
      window.PublicKeyCredential=function(){};window.__passkeyCreateCalls=0;
      Object.defineProperty(navigator,'credentials',{configurable:true,value:{
        get:async()=>{throw new DOMException('cancelled','NotAllowedError')},
        create:async()=>{window.__passkeyCreateCalls++;return {id:'mock-admin-credential',rawId:new Uint8Array([2]).buffer,type:'public-key',authenticatorAttachment:'platform',getClientExtensionResults:()=>({}),response:{clientDataJSON:new Uint8Array([3]).buffer,attestationObject:new Uint8Array([4]).buffer,getTransports:()=>['internal']}}}
      }});
    })()""")
    page.on('console', lambda msg: print('ADMIN_CONSOLE', msg.type, msg.text))
    page.on('pageerror', lambda exc: print('ADMIN_PAGEERROR', str(exc)))
    page.route('**/api/ai/remove-background', lambda route: route.fulfill(status=200, body=GOOD, content_type='image/png'))
    page.goto(base + '/login', wait_until='domcontentloaded')
    page.locator('#password-toggle').click()
    page.locator('input[name="password"]').fill('fan123')
    submit = page.locator('button[type="submit"],input[type="submit"]').first
    if submit.count(): submit.click()
    else: page.locator('form').evaluate('(f)=>f.submit()')
    page.wait_for_url('**/admin')

    # The first setup path is password login, then explicit enablement in the
    # dedicated login-security view. WebAuthn is mocked only at the browser edge;
    # cryptographic verification is covered by test_passkey_auth.py.
    registered = {'value': False, 'verify': None}
    def passkey_list(route):
        credentials = [] if not registered['value'] else [{'credential_id':'mock-admin-credential','device_label':'這台裝置的 Passkey','transports':['internal'],'created_at':'2026-09-25T00:00:00+00:00','last_used_at':None}]
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'status':'success','configured':True,'credentials':credentials}))
    def passkey_register_options(route):
        route.fulfill(status=200, content_type='application/json', body=json.dumps({'status':'success','ceremony_id':'mock-register','publicKey':{'challenge':'AQ','rp':{'id':'127.0.0.1','name':'本福丸訂製'},'user':{'id':'Ag','name':'admin','displayName':'本福丸管理員'},'pubKeyCredParams':[{'type':'public-key','alg':-7}]}}))
    def passkey_register_verify(route):
        registered['verify'] = route.request.post_data_json
        registered['value'] = True
        route.fulfill(status=200, content_type='application/json', body='{"status":"success"}')
    page.route('**/api/admin/passkeys', passkey_list)
    page.route('**/api/admin/passkey/register/options', passkey_register_options)
    page.route('**/api/admin/passkey/register/verify', passkey_register_verify)
    page.locator('.nav button[data-view="security"]').click()
    poll(page, "() => document.getElementById('view-security')?.classList.contains('active') && !document.getElementById('passkey-enable').disabled")
    page.locator('#passkey-enable').click()
    poll(page, "() => window.__passkeyCreateCalls===1 && document.querySelectorAll('#passkey-list .passkey-item').length===1")
    assert registered['verify']['ceremony_id'] == 'mock-register'
    assert registered['verify']['credential']['authenticatorAttachment'] == 'platform'
    page.unroute('**/api/admin/passkeys')
    page.unroute('**/api/admin/passkey/register/options')
    page.unroute('**/api/admin/passkey/register/verify')
    print('ADMIN_PASSKEY_ENABLE_WEBKIT_OK')

    page.evaluate("() => loadShop()")
    poll(page, "() => typeof shopLoaded !== 'undefined' && shopLoaded")
    xss_payload = "品牌');window.__adminStoredXss=1;//"
    xss_result = page.evaluate("""payload => {
      const originalData=structuredClone(shopData),originalEdit=window.editBrand;
      window.__adminStoredXss=0;window.__adminEditedBrand='';
      window.editBrand=value=>{window.__adminEditedBrand=value};
      shopData.brands=[payload];renderBrands();
      const button=document.querySelector('#brands-body [data-edit-brand]');
      const inlineHandlers=document.querySelectorAll('#brands-body [onclick],#models-body [onclick],#styles-body [onclick]').length;
      button.click();
      const result={executed:window.__adminStoredXss,edited:window.__adminEditedBrand,inlineHandlers};
      window.editBrand=originalEdit;shopData=originalData;renderBrands();renderModels();renderStyles();
      return result;
    }""", xss_payload)
    assert xss_result == {'executed': 0, 'edited': xss_payload, 'inlineHandlers': 0}, xss_result
    assert page.locator('.top form[action="/logout"] button[type="submit"]').is_visible()
    print('ADMIN_STORED_DATA_ACTIONS_AND_LOGOUT_OK')

    listing_original = page.evaluate("() => ({data:structuredClone(shopData),version:shopVersion})")
    model_status_requests = []
    def model_status_response(route):
        model_status_requests.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"model-status-version"}')
    page.route('**/api/admin/print/model-profiles', model_status_response)
    model_id = listing_original['data']['models'][0]['id']
    page.evaluate("""id => {
      openModelEditor(id);document.getElementById('model-active').checked=false;
      document.getElementById('model-profile-mask-url').value='fixture://admin-preview';
      document.getElementById('model-profile-line-url').value='fixture://admin-print';
      document.getElementById('model-profile-w').value='80';document.getElementById('model-profile-h').value='160';
    }""", model_id)
    page.evaluate("() => saveModel()")
    assert len(model_status_requests) == 1
    assert next(row for row in model_status_requests[0]['shop_data']['models'] if row['id'] == model_id)['status'] is False
    assert page.evaluate("id => shopData.models.find(row=>row.id===id).status===false && !document.getElementById('model-modal').classList.contains('show')", model_id)
    page.unroute('**/api/admin/print/model-profiles')

    style_status_requests = []
    def style_status_response(route):
        style_status_requests.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"style-status-version"}')
    page.route('**/api/admin/save_shop_data', style_status_response)
    style_id = listing_original['data']['styles'][0]['id']
    page.evaluate("id => {openStyleEditor(id);document.getElementById('style-active').checked=false}", style_id)
    page.evaluate("() => saveStyle()")
    assert len(style_status_requests) == 1
    assert next(row for row in style_status_requests[0]['data']['styles'] if row['id'] == style_id)['status'] is False
    assert page.evaluate("id => shopData.styles.find(row=>row.id===id).status===false && !document.getElementById('style-modal').classList.contains('show')", style_id)
    page.unroute('**/api/admin/save_shop_data')
    page.evaluate("snapshot => {shopData=structuredClone(snapshot.data);shopVersion=snapshot.version;renderBrands();renderModels();renderStyles()}", listing_original)
    print('ADMIN_MODEL_STYLE_LISTING_CONTROL_OK')

    model_color_src = page.locator('script[src*="admin-model-colors.js"]').get_attribute('src')
    assert model_color_src and 'v=20260926audit1' in model_color_src, model_color_src
    model_profile_src = page.locator('script[src*="admin-model-profiles.js"]').get_attribute('src')
    assert model_profile_src and 'v=20260928a' in model_profile_src, model_profile_src
    asset_category_src = page.locator('script[src*="admin-asset-categories.js"]').get_attribute('src')
    assert asset_category_src and 'v=20260926audit1' in asset_category_src, asset_category_src
    template_loader_src = page.locator('script[src*="admin-template-loader.js"]').get_attribute('src')
    assert template_loader_src and 'v=20260926audit1' in template_loader_src, template_loader_src
    commerce_src = page.locator('script[src*="admin-commerce-v1.js"]').get_attribute('src')
    assert commerce_src and 'v=20260923cas1' in commerce_src, commerce_src
    def ux_error(route):
        status = int(route.request.url.rsplit('-', 1)[-1])
        route.fulfill(status=status, content_type='application/json', body='{"status":"error"}')
    page.route('**/api/admin/ux-probe-*', ux_error)
    api_messages = page.evaluate("""async () => {
      const out={};
      for(const status of [401,409,503]){
        try{await apiJson('/api/admin/ux-probe-'+status)}catch(e){out[status]=e.message}
      }
      return out;
    }""")
    assert api_messages == {
        '401':'登入已過期，請重新登入後再試',
        '409':'資料已被其他操作更新，請重新載入後再試',
        '503':'服務暫時無法使用，請稍後再試'
    }, api_messages
    page.unroute('**/api/admin/ux-probe-*')
    print('ADMIN_API_FEEDBACK_CACHE_KEY_OK')

    # POS UI is injected only for authenticated admin and must coexist with the
    # existing order/template editor without leaking private data publicly.
    poll(page, "() => !!window.BenfuwanCommerce && !!document.querySelector('.nav button[data-view=\"commerce\"]')")
    page.locator('.nav button[data-view="commerce"]').click()
    poll(page, "() => document.getElementById('view-commerce')?.classList.contains('active') && document.querySelectorAll('#commerce-summary .commerce-kpi').length===4")
    commerce_diag = page.evaluate("""() => ({version:window.BenfuwanCommerce?.version||'',publicCostLeak:JSON.stringify(shopData||{}).includes('cost_price'),view:document.getElementById('view-commerce')?.classList.contains('active')})""")
    assert commerce_diag['version'].startswith('2.0') and commerce_diag['view'] and not commerce_diag['publicCostLeak'], commerce_diag
    print('ADMIN_COMMERCE_WEBKIT_OK', commerce_diag['version'])
    page.locator('[data-tab="stock"]').click()

    # Real Phase 2 controls, including a committed receipt with lost response.
    assert page.request.post(base + '/api/admin/commerce_sync_skus', data={}).ok
    data = page.request.get(base + '/api/admin/commerce_data').json()['data']
    sku = data['skus'][0]
    sku.update(stock_qty=1, cost_price=100, low_stock_threshold=2, target_stock=8, track_stock=True)
    assert page.request.post(base + '/api/admin/save_commerce_data', data=data).ok
    page.locator('#commerce-reload').click()
    poll(page, "() => window.BenfuwanCommerce.state.skus[0]?.target_stock===8")
    card = page.locator('[data-sku="' + sku['id'] + '"]')
    card.locator('[data-field="target_stock"]').fill('10')
    page.locator('#commerce-save').click()
    poll(page, "() => document.getElementById('pos-message').textContent==='商品設定已儲存'")
    page.locator('[data-tab="restock"]').click()
    assert page.locator('#commerce-low-only').is_checked()
    assert card.is_visible()
    page.locator('#pos-list').click()
    page.locator('#pos-export-text').wait_for(state='visible')
    assert '建議 9 件' in page.locator('#pos-export-text').input_value()
    page.locator('#pos-close').click()
    receipts = []
    def receive(route):
        receipts.append(route.request.post_data_json)
        if len(receipts) == 1:
            assert route.fetch().status == 200
            route.abort('failed')
        else:
            route.continue_()
    page.route('**/api/admin/purchase_received', receive)
    card.locator('[data-receive]').click()
    page.locator('#pos-receive-qty').fill('3')
    page.locator('#pos-dialog-submit').click()
    poll(page, "() => document.getElementById('pos-message').classList.contains('error')")
    page.reload(wait_until='domcontentloaded')
    page.locator('.nav button[data-view="commerce"]').click()
    page.locator('#pos-retry').click()
    poll(page, "() => !localStorage.getItem('bf-pos2-pending') && window.BenfuwanCommerce.state.skus[0]?.stock_qty===4")
    assert len(receipts) == 2 and receipts[0] == receipts[1], receipts
    page.locator('[data-tab="expenses"]').click()
    page.locator('#pos-expense-category').select_option('廣告')
    page.locator('#pos-expense-amount').fill('20.25')
    page.locator('#pos-expense-note').fill('瀏覽器測試支出')
    page.locator('#pos-expense-save').click()
    page.locator('.pos-expense').filter(has_text='瀏覽器測試支出').wait_for()
    for width, height in ((390,844),(1024,768),(1440,900)):
        page.set_viewport_size(dict(width=width,height=height))
        for tab in ('stock','restock','reports','expenses'):
            page.locator('[data-tab="'+tab+'"]').click()
            if tab == 'reports':
                poll(page, "() => document.querySelectorAll('#pos-metrics .pos-metric').length===9")
            metrics = page.evaluate("""() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,view:document.getElementById('view-commerce').getBoundingClientRect().width})""")
            assert metrics['scroll'] <= width + 2 and metrics['view'] > 200, (tab,metrics)
            if os.environ.get('POS_SCREENSHOT_DIR'):
                folder = Path(os.environ['POS_SCREENSHOT_DIR']);folder.mkdir(parents=True,exist_ok=True)
                page.screenshot(path=str(folder / f'pos-{width}-{tab}.png'), full_page=True)
    page.locator('[data-tab="reports"]').click()
    for period in ('week','month','year','custom'):
        page.locator('#pos-period').select_option(period)
        page.locator('#pos-report-form button').click()
        poll(page, "() => document.querySelectorAll('#pos-metrics .pos-metric').length===9 && document.getElementById('pos-metrics').getAttribute('aria-busy')===null")
    print('POS_PHASE2_RESPONSIVE_RECEIPT_EXPENSE_REPORT_OK')

    page.locator('.nav button[data-view="models"]').click()
    page.locator('#model-tab-btn').click()
    poll(page, "() => document.getElementById('view-models').classList.contains('active') && document.getElementById('model-admin-view').classList.contains('active') && document.querySelector('#models-body button')")
    page.locator('#models-body button').first.click()
    page.locator('#model-modal.show').wait_for()
    model_text = page.locator('#model-modal').inner_text()
    assert 'A5 有效範圍為 200 × 230 mm' in model_text
    assert '座標原點在治具右下角' in model_text
    page.evaluate("""() => {
      document.getElementById('model-profile-mask-url').value='fixture://admin-preview';
      document.getElementById('model-profile-line-url').value='fixture://admin-print';
    }""")
    page.locator('#model-profile-x').fill('1.5');page.locator('#model-profile-y').fill('2.5')
    page.locator('#model-profile-w').fill('80');page.locator('#model-profile-h').fill('160');page.locator('#model-profile-angle').fill('0')
    model_requests = []
    def save_model(route):
        model_requests.append(route.request.post_data_json)
        result = route.fetch()
        time.sleep(.15)
        route.fulfill(response=result)
    page.route('**/api/admin/print/model-profiles', save_model)
    page.evaluate("() => Promise.all([saveModel(),saveModel()])")
    assert len(model_requests) == 1, model_requests
    assert model_requests[0]['style_id'] and model_requests[0]['model_id'], model_requests
    page.unroute('**/api/admin/print/model-profiles')
    page.locator('#model-modal').wait_for(state='hidden')
    page.locator('.nav button[data-view="styles"]').click()
    poll(page, "() => document.getElementById('view-styles').classList.contains('active') && document.querySelector('#styles-body button')")
    page.locator('#styles-body button').first.click()
    page.locator('#style-modal.show').wait_for()
    assert page.locator('#style-x,#style-y,#style-w,#style-h').count() == 0
    page.locator('#style-modal .mh button').click()

    style_requests = []
    dialogs = []
    page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
    def save_style(route):
        style_requests.append(route.request.post_data_json)
        if len(style_requests) == 1:
            route.fulfill(status=503, content_type='application/json', body='{"status":"error"}')
        else:
            time.sleep(.15)
            route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"mock-style-version"}')
    page.route('**/api/admin/save_shop_data', save_style)
    before_styles = page.evaluate("() => shopData.styles.length")
    page.locator('#view-styles .titlebar .btn').click()
    page.locator('#style-name').fill('重複送出回歸殼款')
    page.locator('#style-price').fill('490')
    page.evaluate("() => Promise.all([saveStyle(),saveStyle()])")
    assert len(style_requests) == 1, style_requests
    failed = page.evaluate("""() => ({
      count:shopData.styles.filter(x=>x.name==='重複送出回歸殼款').length,
      open:document.getElementById('style-modal').classList.contains('show'),
      value:document.getElementById('style-name').value,
      disabled:document.getElementById('style-save').disabled
    })""")
    assert failed == {'count':0,'open':True,'value':'重複送出回歸殼款','disabled':False}, failed
    assert any('服務暫時無法使用，請稍後再試' in msg for msg in dialogs), dialogs
    page.evaluate("() => Promise.all([saveStyle(),saveStyle()])")
    saved = page.evaluate("""() => ({
      total:shopData.styles.length,
      count:shopData.styles.filter(x=>x.name==='重複送出回歸殼款').length,
      open:document.getElementById('style-modal').classList.contains('show')
    })""")
    assert len(style_requests) == 2 and saved == {'total':before_styles+1,'count':1,'open':False}, (style_requests,saved)
    page.unroute('**/api/admin/save_shop_data')
    page.evaluate("() => loadShop(true)")
    print('ADMIN_STYLE_RETRY_DOUBLE_SUBMIT_OK')
    print('MODEL_PROFILE_SINGLE_ENTRY_WEBKIT_OK')

    # Catalog CRUD must not mutate browser state until the server accepts it.
    catalog_original = page.evaluate("() => structuredClone(shopData)")
    catalog_fixture = {
        'brands':['Issue29品牌','Issue29空品牌'],
        'models':[{'id':'issue29-model','brand':'Issue29品牌','name':'Issue29型號','status':True}],
        'styles':[{'id':'issue29-style','name':'Issue29系列','price':390,'colors':['透明'],'status':True}],
    }
    page.evaluate("() => {window.__issue29Prompt=window.prompt;window.__issue29Confirm=window.confirm}")

    def catalog_case(label, action, failure_check, success_check):
        page.evaluate("data => {shopData=structuredClone(data);renderBrands();renderModels();renderStyles()}", catalog_fixture)
        requests = []
        def respond(route):
            requests.append(route.request.post_data_json)
            if len(requests) == 1:
                route.fulfill(status=503, content_type='application/json', body='{"status":"error"}')
            else:
                time.sleep(.15)
                route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"mock-catalog-version"}')
        page.route('**/api/admin/save_shop_data', respond)
        dialog_start = len(dialogs)
        page.evaluate(action)
        failed = page.evaluate(failure_check)
        assert len(requests) == 1 and failed, (label, requests, failed)
        assert any('服務暫時無法使用，請稍後再試' in msg for msg in dialogs[dialog_start:]), (label, dialogs[dialog_start:])
        page.evaluate(action)
        saved = page.evaluate(success_check)
        assert len(requests) == 2 and saved, (label, requests, saved)
        page.unroute('**/api/admin/save_shop_data')

    catalog_case(
        'addBrand',
        """() => {window.prompt=()=> 'Issue29新增品牌';return Promise.all([addBrand(),addBrand()])}""",
        """() => JSON.stringify(shopData)===JSON.stringify({brands:['Issue29品牌','Issue29空品牌'],models:[{id:'issue29-model',brand:'Issue29品牌',name:'Issue29型號',status:true}],styles:[{id:'issue29-style',name:'Issue29系列',price:390,colors:['透明'],status:true}]}) && !shopMutationBusy""",
        """() => shopData.brands.filter(x=>x==='Issue29新增品牌').length===1 && !shopMutationBusy""",
    )
    catalog_case(
        'editBrand',
        """() => {window.prompt=()=> 'Issue29品牌改名';return Promise.all([editBrand('Issue29品牌'),editBrand('Issue29品牌')])}""",
        """() => shopData.brands.includes('Issue29品牌') && !shopData.brands.includes('Issue29品牌改名') && shopData.models[0].brand==='Issue29品牌' && !shopMutationBusy""",
        """() => !shopData.brands.includes('Issue29品牌') && shopData.brands.filter(x=>x==='Issue29品牌改名').length===1 && shopData.models[0].brand==='Issue29品牌改名' && !shopMutationBusy""",
    )
    catalog_case(
        'deleteBrand',
        """() => {window.confirm=()=>true;return Promise.all([deleteBrand('Issue29品牌'),deleteBrand('Issue29品牌')])}""",
        """() => shopData.brands.includes('Issue29品牌') && !shopData.brands.includes('未分類') && shopData.models[0].brand==='Issue29品牌' && !shopMutationBusy""",
        """() => !shopData.brands.includes('Issue29品牌') && shopData.brands.filter(x=>x==='未分類').length===1 && shopData.models[0].brand==='未分類' && !shopMutationBusy""",
    )
    catalog_case(
        'deleteModel',
        """() => {window.confirm=()=>true;return Promise.all([deleteModel('issue29-model'),deleteModel('issue29-model')])}""",
        """() => shopData.models.some(x=>x.id==='issue29-model') && document.getElementById('models-body').textContent.includes('Issue29型號') && !shopMutationBusy""",
        """() => !shopData.models.some(x=>x.id==='issue29-model') && !shopMutationBusy""",
    )
    catalog_case(
        'deleteStyle',
        """() => {window.confirm=()=>true;return Promise.all([deleteStyle('issue29-style'),deleteStyle('issue29-style')])}""",
        """() => shopData.styles.some(x=>x.id==='issue29-style') && document.getElementById('styles-body').textContent.includes('Issue29系列') && !shopMutationBusy""",
        """() => !shopData.styles.some(x=>x.id==='issue29-style') && !shopMutationBusy""",
    )
    page.evaluate("async () => {await loadShop(true);window.prompt=window.__issue29Prompt;window.confirm=window.__issue29Confirm;delete window.__issue29Prompt;delete window.__issue29Confirm}")
    print('ADMIN_CATALOG_CRUD_STATE_RETRY_DOUBLE_SUBMIT_OK')

    # Catalog commit can succeed before production-profile sync fails. The
    # browser must adopt that committed candidate and returned version so its
    # next catalog mutation cannot legally CAS stale data over the model edit.
    partial_before = page.evaluate("() => ({data:structuredClone(shopData),model:structuredClone(shopData.models[0]),version:shopVersion})")
    primed_catalog = page.request.get(base + '/api/shop_data')
    assert primed_catalog.headers.get('x-benfuwan-cache') == 'HIT', primed_catalog.headers
    assert primed_catalog.json()['version'] == partial_before['version']
    partial_model_name = f'Partial Success 型號 {time.time_ns()}'
    partial_brand = f'部分成功後品牌 {time.time_ns()}'
    page.evaluate("id => openModelEditor(id)", partial_before['model']['id'])
    page.locator('#model-name').fill(partial_model_name)
    partial_dialog_start = len(dialogs)
    original_save_profiles = app_module.print_center.store.save_profiles
    def fail_profile_sync(_profiles):
        raise RuntimeError('browser fixture')
    app_module.print_center.store.save_profiles = fail_profile_sync
    try:
        page.evaluate("() => saveModel()")
    finally:
        app_module.print_center.store.save_profiles = original_save_profiles
    server_partial, server_partial_version = app_module.cloud_get_json_versioned(
        'shop_data', app_module.DATA_FILE, app_module.DEFAULT_SHOP_DATA)
    partial_state = page.evaluate("""() => ({
      open:document.getElementById('model-modal').classList.contains('show'),
      input:document.getElementById('model-name').value,
      id:document.getElementById('model-id').value,
      local:shopData.models.find(x=>x.id===document.getElementById('model-id').value)?.name,
      version:shopVersion
    })""")
    assert partial_state == {
        'open':True, 'input':partial_model_name, 'id':partial_before['model']['id'],
        'local':partial_model_name, 'version':server_partial_version,
    }, partial_state
    assert server_partial_version != partial_before['version']
    assert next(row for row in server_partial['models'] if row['id'] == partial_before['model']['id'])['name'] == partial_model_name
    assert any('型號資料已儲存，但正式列印參數同步失敗' in msg for msg in dialogs[partial_dialog_start:])
    fresh_after_partial = page.request.get(base + '/api/shop_data')
    assert fresh_after_partial.headers.get('x-benfuwan-cache') == 'MISS', fresh_after_partial.headers
    fresh_after_partial_data = fresh_after_partial.json()
    assert fresh_after_partial_data['version'] == server_partial_version
    assert next(row for row in fresh_after_partial_data['data']['models'] if row['id'] == partial_before['model']['id'])['name'] == partial_model_name
    print('ADMIN_MODEL_PROFILE_PARTIAL_SUCCESS_CACHE_INVALIDATION_OK')

    page.evaluate("""async brand => {const old=window.prompt;window.prompt=()=>brand;try{await addBrand()}finally{window.prompt=old}}""", partial_brand)
    server_after_mutation = page.request.get(base + '/api/shop_data').json()
    assert partial_brand in server_after_mutation['data']['brands']
    assert next(row for row in server_after_mutation['data']['models'] if row['id'] == partial_before['model']['id'])['name'] == partial_model_name
    assert page.evaluate("brand => shopData.brands.includes(brand) && document.getElementById('model-modal').classList.contains('show')", partial_brand)
    page.evaluate("() => saveModel()")
    assert 'show' not in page.locator('#model-modal').get_attribute('class')
    partial_restore = page.request.post(base + '/api/admin/save_shop_data', data={
        'data':partial_before['data'], 'expected_version':page.evaluate('() => shopVersion'),
    })
    assert partial_restore.status == 200, partial_restore.text()
    page.evaluate("() => loadShop(true)")
    print('ADMIN_MODEL_PROFILE_PARTIAL_SUCCESS_STATE_OK')

    # A second tab/device wins the catalog CAS. This tab must keep its unsaved
    # inputs and local state across all shop_data write paths until reload.
    stale_shop = page.evaluate("() => ({data:structuredClone(shopData),version:shopVersion})")
    winner_shop = copy.deepcopy(stale_shop['data'])
    winner_shop['brands'].append('CAS 分頁 A')
    winner = page.request.post(base + '/api/admin/save_shop_data', data={
        'data': winner_shop, 'expected_version': stale_shop['version'],
    })
    assert winner.status == 200, winner.text()
    winner_version = winner.json()['version']
    winner_cached = page.request.get(base + '/api/shop_data')
    assert winner_cached.headers.get('x-benfuwan-cache') == 'MISS', winner_cached.headers
    assert winner_cached.json()['version'] == winner_version
    stale_dialog_start = len(dialogs)

    page.evaluate("""() => {openStyleEditor();document.getElementById('style-name').value='CAS 分頁 B 系列';document.getElementById('style-price').value='555'}""")
    page.evaluate("() => saveStyle()")
    style_stale = page.evaluate("""() => ({
      open:document.getElementById('style-modal').classList.contains('show'),
      input:document.getElementById('style-name').value,
      local:shopData.styles.some(x=>x.name==='CAS 分頁 B 系列'),
      version:shopVersion
    })""")
    assert style_stale == {'open':True,'input':'CAS 分頁 B 系列','local':False,'version':stale_shop['version']}, style_stale
    page.locator('#style-modal .mh button').click()

    original_model = stale_shop['data']['models'][0]
    page.evaluate("id => openModelEditor(id)", original_model['id'])
    page.locator('#model-name').fill('CAS 分頁 B 型號')
    page.evaluate("() => saveModel()")
    model_stale = page.evaluate("""() => ({
      open:document.getElementById('model-modal').classList.contains('show'),
      input:document.getElementById('model-name').value,
      local:shopData.models.some(x=>x.name==='CAS 分頁 B 型號'),
      version:shopVersion
    })""")
    assert model_stale == {'open':True,'input':'CAS 分頁 B 型號','local':False,'version':stale_shop['version']}, model_stale
    cache_after_stale = page.request.get(base + '/api/shop_data')
    assert cache_after_stale.headers.get('x-benfuwan-cache') == 'HIT', cache_after_stale.headers
    assert cache_after_stale.json()['version'] == winner_version
    page.locator('#model-modal .mh button').click()

    page.locator('.nav button[data-view="commerce"]').click()
    poll(page, "() => document.getElementById('view-commerce')?.classList.contains('active')")
    page.locator('[data-tab="stock"]').click()
    poll(page, "() => !document.getElementById('pos-stock-panel').hidden")
    local_price = page.evaluate("""() => {const id=document.querySelector('#pos-series [data-series].selected')?.dataset.series||shopData.styles[0].id;return {id,price:Number(shopData.styles.find(x=>String(x.id)===String(id))?.price)}}""")
    page.locator('#pos-series-price').fill('888')
    page.locator('#pos-price-form button').click()
    poll(page, "() => document.getElementById('pos-message').textContent.includes('資料已被其他分頁或裝置更新')")
    assert page.locator('#pos-series-price').input_value() == '888'
    assert page.evaluate("before => Number(shopData.styles.find(x=>String(x.id)===String(before.id))?.price)===before.price", local_price)

    server_after_stale = page.request.get(base + '/api/shop_data').json()
    assert server_after_stale['version'] == winner_version
    assert 'CAS 分頁 A' in server_after_stale['data']['brands']
    assert not any(x.get('name') == 'CAS 分頁 B 系列' for x in server_after_stale['data']['styles'])
    assert any('資料已被其他分頁或裝置更新，請重新載入後再修改。' in msg for msg in dialogs[stale_dialog_start:]), dialogs[stale_dialog_start:]
    page.evaluate("() => loadShop(true)")
    assert page.evaluate("version => shopVersion===version && shopData.brands.includes('CAS 分頁 A')", winner_version)
    restored = page.request.post(base + '/api/admin/save_shop_data', data={
        'data': stale_shop['data'], 'expected_version': winner_version,
    })
    assert restored.status == 200, restored.text()
    page.evaluate("() => loadShop(true)")
    print('ADMIN_CATALOG_MODEL_PRICE_STALE_CAS_OK')

    page.locator('.nav button[data-view="assets"]').click()
    poll(page, "() => typeof assetsLoaded !== 'undefined' && assetsLoaded && !!document.getElementById('bf-asset-cat-actions')")
    asset_before = page.evaluate("() => ({data:structuredClone(assetsData),version:assetsVersion})")
    asset_a = f'CAS-A-{time.time_ns() % 100000000}'
    asset_b = f'CAS-B-{time.time_ns() % 100000000}'
    primed_assets = page.request.get(base + '/api/assets')
    assert primed_assets.headers.get('x-benfuwan-cache') == 'HIT', primed_assets.headers
    asset_winner = page.request.post(base + '/api/admin/sticker_category', data={
        'action': 'create', 'name': asset_a, 'expected_version': asset_before['version'],
    })
    assert asset_winner.status == 200, asset_winner.text()
    asset_winner_version = asset_winner.json()['version']
    fresh_assets = page.request.get(base + '/api/assets')
    assert fresh_assets.headers.get('x-benfuwan-cache') == 'MISS', fresh_assets.headers
    assert fresh_assets.json()['version'] == asset_winner_version
    asset_dialog_start = len(dialogs)
    page.evaluate("name => {window.__issue37Prompt=window.prompt;window.prompt=()=>name;document.querySelector('#bf-asset-cat-actions button').click()}", asset_b)
    poll(page, f"() => assetsVersion==={json.dumps(asset_winner_version)}")
    asset_stale_state = page.evaluate("""names => ({
      version:assetsVersion,
      hasA:assetsData.categories.includes(names.a),
      hasB:assetsData.categories.includes(names.b)
    })""", {'a': asset_a, 'b': asset_b})
    assert asset_stale_state == {'version': asset_winner_version, 'hasA': True, 'hasB': False}, asset_stale_state
    assert any('資料已被其他分頁或裝置更新' in msg for msg in dialogs[asset_dialog_start:]), dialogs[asset_dialog_start:]
    asset_restore = page.request.post(base + '/api/admin/sticker_category', data={
        'action': 'delete', 'name': asset_a, 'expected_version': asset_winner_version,
    })
    assert asset_restore.status == 200, asset_restore.text()
    page.evaluate("async () => {await loadAssets(true);window.prompt=window.__issue37Prompt;delete window.__issue37Prompt}")
    print('ADMIN_ASSET_STALE_CAS_CACHE_INVALIDATION_OK')

    print_nav = page.locator('.nav button[data-view="print-center"]')
    print_nav.click()
    poll(page, "() => document.querySelectorAll('#pc-grid .pc-card').length>0 && document.getElementById('view-print-center').classList.contains('active')")
    assert page.locator('#pc-config').get_attribute('class').find('warn') >= 0
    assert page.locator('[data-pc="start"]').count() == 0
    assert page.locator('[data-pc="profile"]').count() == 0
    assert page.locator('#pc-modal').count() == 0
    assert '80 × 160 mm / X 1.5 / Y 2.5' in page.locator('#pc-grid').inner_text()
    for width, height in ((390,844),(768,1024),(1440,900)):
        page.set_viewport_size(dict(width=width,height=height))
        metrics = page.evaluate("""() => ({
          width:innerWidth,scroll:document.documentElement.scrollWidth,
          view:document.getElementById('view-print-center').getBoundingClientRect().width,
          cards:document.querySelectorAll('#pc-grid .pc-card').length,
          secrets:document.getElementById('view-print-center').textContent.includes('fake-key')
        })""")
        assert metrics['scroll'] <= width + 2 and metrics['view'] > 200 and metrics['cards'] > 0 and not metrics['secrets'], metrics
    legacy_order = app_module.commerce.store.local_orders()[0]
    commerce = app_module.commerce.read()
    assert commerce['order_finance'].pop(legacy_order['id'], None), legacy_order['id']
    assert app_module.commerce.store.commit(int(commerce.get('revision', 0)), commerce)
    page.locator('#pc-reload').click()
    poll(page, "() => document.querySelector('[data-pc=\"binding\"]') !== null")
    page.locator('[data-pc="binding"]').first.click()
    page.locator('#pc-bind-modal.show').wait_for()
    assert '不會修改營收／成本／庫存資料' in page.locator('#pc-bind-modal').inner_text()
    assert page.locator('#pc-bind-sku option').count() >= 2
    page.locator('#pc-bind-close').click()
    print('PRINT_CENTER_A5_RESPONSIVE_FAIL_CLOSED_OK')

    template_nav = page.locator('.nav button[data-view="templates"]')
    template_nav.click()
    poll(page, "() => typeof window.benfuwanEnsureTemplateEditor === 'function' && typeof shopLoaded !== 'undefined' && shopLoaded && typeof templatesLoaded !== 'undefined' && templatesLoaded")
    page.evaluate("() => window.benfuwanEnsureTemplateEditor()")
    diag = page.evaluate("""() => ({core:!!window.BenfuwanAiRemoveV2,admin:typeof window.bfAdminRemoveBackground,stackReady:!!window.__benfuwanTemplateStackReady,adminFlag:!!window.__bfAdminAiRemoveOnlyV2,models:(shopData?.models||[]).length})""")
    print('ADMIN_STACK_DIAG', diag)
    assert diag['core'] and diag['admin']=='function' and diag['stackReady'] and diag['adminFlag'] and diag['models'] > 0, diag

    template_xss = "template');window.__adminStoredXss=2;//"
    template_xss_result = page.evaluate("""payload => {
      const originalData=structuredClone(templatesData),originalOpen=window.openTemplateEditor;
      window.__adminStoredXss=0;window.__adminEditedTemplate='';
      window.openTemplateEditor=value=>{window.__adminEditedTemplate=value};
      templatesData.templates=[{id:payload,name:'安全模板',category:'熱門',model_id:'*',universal:true}];
      currentTpl='全部';renderTemplates();
      const inlineHandlers=document.querySelectorAll('#template-grid [onclick]').length;
      document.querySelector('#template-grid [data-edit-template]').click();
      const result={executed:window.__adminStoredXss,edited:window.__adminEditedTemplate,inlineHandlers};
      window.openTemplateEditor=originalOpen;templatesData=originalData;renderTemplates();
      return result;
    }""", template_xss)
    assert template_xss_result == {'executed': 0, 'edited': template_xss, 'inlineHandlers': 0}, template_xss_result
    print('ADMIN_TEMPLATE_STORED_DATA_ACTIONS_OK')

    page.locator('#view-templates .titlebar .btn').click()
    poll(page, "() => document.getElementById('template-modal')?.classList.contains('show') && typeof window.fabric !== 'undefined' && typeof visualCanvas !== 'undefined' && !!visualCanvas", timeout=30000)
    template_editor_src = page.locator('script[src*="admin-template-editor-v2.js"]').get_attribute('src')
    assert template_editor_src and 'v=20260923cas1' in template_editor_src, template_editor_src
    print('ADMIN_FABRIC_LAZY_OK')

    template_server_original = page.evaluate("() => ({data:structuredClone(templatesData),version:templatesVersion})")
    template_winner = copy.deepcopy(template_server_original['data'])
    template_winner['templates'].append({'id':'cas-template-a','name':'CAS 模板 A','category':'熱門','model_id':'*','universal':True})
    template_winner_response = page.request.post(base + '/api/admin/save_templates', data={
        'data': template_winner, 'expected_version': template_server_original['version'],
    })
    assert template_winner_response.status == 200, template_winner_response.text()
    template_winner_version = template_winner_response.json()['version']
    page.route('**/api/admin/upload_image', lambda route: route.fulfill(status=200, content_type='application/json', body='{"status":"success","url":"/static/materials/cas-orphan.png"}'))
    template_stale_dialog = len(dialogs)
    page.evaluate("""() => {document.getElementById('tpl-id').value='';document.getElementById('tpl-name').value='CAS 模板 B';document.getElementById('tpl-category').value='熱門'}""")
    page.evaluate("() => saveTemplate()")
    template_stale = page.evaluate("""() => ({
      open:document.getElementById('template-modal').classList.contains('show'),
      input:document.getElementById('tpl-name').value,
      local:templatesData.templates.some(x=>x.name==='CAS 模板 B'),
      version:templatesVersion
    })""")
    assert template_stale == {'open':True,'input':'CAS 模板 B','local':False,'version':template_server_original['version']}, template_stale
    page.unroute('**/api/admin/upload_image')
    template_server_after = page.request.get(base + '/api/templates').json()
    assert template_server_after['version'] == template_winner_version
    assert [row['id'] for row in template_server_after['data']['templates'] if row.get('id') in ('cas-template-a','cas-template-b')] == ['cas-template-a']
    assert any('資料已被其他分頁或裝置更新，請重新載入後再修改。' in msg for msg in dialogs[template_stale_dialog:]), dialogs[template_stale_dialog:]
    page.evaluate("() => loadTemplates(true)")
    reloaded_template = page.evaluate("version => ({version:templatesVersion,hasA:templatesData.templates.some(x=>x.id==='cas-template-a'),input:document.getElementById('tpl-name').value})", template_winner_version)
    assert reloaded_template == {'version':template_winner_version,'hasA':True,'input':'CAS 模板 B'}, reloaded_template
    restored_templates = page.request.post(base + '/api/admin/save_templates', data={
        'data': template_server_original['data'], 'expected_version': template_winner_version,
    })
    assert restored_templates.status == 200, restored_templates.text()
    page.evaluate("() => loadTemplates(true)")
    print('ADMIN_TEMPLATE_STALE_CAS_OK')

    page.evaluate("""() => new Promise((resolve,reject)=>{const c=document.createElement('canvas');c.width=128;c.height=128;const g=c.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,128,128);g.fillStyle='#d94d75';g.fillRect(24,16,80,96);fabric.Image.fromURL(c.toDataURL('image/png'),img=>{try{img.set({left:tplW/2,top:tplH/2,originX:'center',originY:'center',scaleX:.8,scaleY:1.1,angle:13,originalName:'admin-test.png'});visualCanvas.add(img);visualCanvas.setActiveObject(img);visualCanvas.requestRenderAll();resolve()}catch(e){reject(e)}});})""")
    before = page.evaluate("""() => {const o=visualCanvas.getActiveObject();return {w:o.getScaledWidth(),h:o.getScaledHeight(),x:o.getCenterPoint().x,y:o.getCenterPoint().y,a:o.angle};}""")
    page.evaluate("() => window.bfAdminRemoveBackground()")
    after = page.evaluate("""() => {const o=visualCanvas.getActiveObject();return {ai:!!o?.aiBackgroundRemoved,w:o?.getScaledWidth(),h:o?.getScaledHeight(),x:o?.getCenterPoint().x,y:o?.getCenterPoint().y,a:o?.angle,publicSrc:o?.publicSrc||''};}""")
    assert after['ai'] is True, after
    for k in ('w','h','x','y','a'):
        assert abs(after[k]-before[k]) < .75, (k,before,after)
    assert after['publicSrc'], after

    # Runtime saveTemplate is the lazy-loaded editor-v2 override. Verify its
    # existing candidate state/busy boundary, then cover deleteTemplate too.
    template_original = page.evaluate("() => structuredClone(templatesData)")
    template_save_requests = []
    template_uploads = []
    page.route('**/api/admin/upload_image', lambda route: (template_uploads.append(route.request.url), route.fulfill(status=200, content_type='application/json', body='{"status":"success","url":"/static/uploads/issue29-template.png"}')))
    def save_template_response(route):
        template_save_requests.append(route.request.post_data_json)
        if len(template_save_requests) == 1:
            route.fulfill(status=503, content_type='application/json', body='{"status":"error"}')
        else:
            time.sleep(.15)
            route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"mock-template-version"}')
    page.route('**/api/admin/save_templates', save_template_response)
    page.evaluate("""() => {document.getElementById('tpl-id').value='';document.getElementById('tpl-name').value='Issue29模板';document.getElementById('tpl-category').value='Issue29分類'}""")
    before_template_count = page.evaluate("() => templatesData.templates.length")
    template_dialog_start = len(dialogs)
    page.evaluate("() => Promise.all([saveTemplate(),saveTemplate()])")
    template_failed = page.evaluate("""() => ({
      count:templatesData.templates.filter(x=>x.name==='Issue29模板').length,
      open:document.getElementById('template-modal').classList.contains('show'),
      value:document.getElementById('tpl-name').value,
      disabled:[...document.querySelectorAll('#template-modal .mf .btn')].find(b=>b.textContent.includes('儲存'))?.disabled||false
    })""")
    assert len(template_save_requests) == 1 and len(template_uploads) == 1, (template_save_requests, template_uploads)
    assert template_failed == {'count':0,'open':True,'value':'Issue29模板','disabled':False}, template_failed
    assert any('服務暫時無法使用，請稍後再試' in msg for msg in dialogs[template_dialog_start:]), dialogs[template_dialog_start:]
    page.evaluate("() => Promise.all([saveTemplate(),saveTemplate()])")
    template_saved = page.evaluate("""() => ({
      total:templatesData.templates.length,
      count:templatesData.templates.filter(x=>x.name==='Issue29模板').length,
      open:document.getElementById('template-modal').classList.contains('show')
    })""")
    assert len(template_save_requests) == 2 and len(template_uploads) == 2, (template_save_requests, template_uploads)
    assert template_saved == {'total':before_template_count+1,'count':1,'open':False}, template_saved
    page.unroute('**/api/admin/upload_image')
    page.unroute('**/api/admin/save_templates')

    delete_requests = []
    page.evaluate("""data => {templatesData=structuredClone(data);templatesData.templates.push({id:'issue29-delete-template',name:'Issue29刪除模板',category:'熱門'});renderTemplateTabs();renderTemplates();window.__issue29Confirm=window.confirm;window.confirm=()=>true}""", template_original)
    def delete_template_response(route):
        delete_requests.append(route.request.post_data_json)
        if len(delete_requests) == 1:
            route.fulfill(status=503, content_type='application/json', body='{"status":"error"}')
        else:
            time.sleep(.15)
            route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"mock-template-delete-version"}')
    page.route('**/api/admin/save_templates', delete_template_response)
    delete_dialog_start = len(dialogs)
    page.evaluate("() => Promise.all([deleteTemplate('issue29-delete-template'),deleteTemplate('issue29-delete-template')])")
    delete_failed = page.evaluate("() => templatesData.templates.filter(x=>x.id==='issue29-delete-template').length===1 && document.getElementById('template-grid').textContent.includes('Issue29刪除模板') && !templateDeleteBusy")
    assert len(delete_requests) == 1 and delete_failed, (delete_requests, delete_failed)
    assert any('服務暫時無法使用，請稍後再試' in msg for msg in dialogs[delete_dialog_start:]), dialogs[delete_dialog_start:]
    page.evaluate("() => Promise.all([deleteTemplate('issue29-delete-template'),deleteTemplate('issue29-delete-template')])")
    delete_saved = page.evaluate("() => !templatesData.templates.some(x=>x.id==='issue29-delete-template') && !templateDeleteBusy")
    assert len(delete_requests) == 2 and delete_saved, (delete_requests, delete_saved)
    page.unroute('**/api/admin/save_templates')
    page.evaluate("async () => {await loadTemplates(true);window.confirm=window.__issue29Confirm;delete window.__issue29Confirm}")
    print('ADMIN_TEMPLATE_CRUD_STATE_RETRY_DOUBLE_SUBMIT_OK')
    print('ADMIN_WEBKIT_OK')
    page.close()


def durable_receipt_test(playwright, base):
    """Persist the real committed request across tab close AND browser restart."""
    engine = getattr(playwright, os.environ.get('BROWSER_ENGINE', 'webkit'))
    def admin(context):
        page = context.new_page()
        page.goto(base + '/login', wait_until='domcontentloaded')
        if '/admin' not in page.url:
            if not page.locator('#password-form').is_visible():
                page.locator('#password-toggle').click()
            page.locator('input[name="password"]').fill('fan123')
            page.locator('button[type="submit"],input[type="submit"]').first.click()
            page.wait_for_url('**/admin')
        poll(page, "() => !!window.BenfuwanCommerce")
        page.locator('.nav button[data-view="commerce"]').click()
        poll(page, "() => window.BenfuwanCommerce.state.skus.length>0")
        page.locator('[data-tab="stock"]').click()
        return page
    with tempfile.TemporaryDirectory() as profile:
        for kind in ('purchase', 'expense'):
            context = engine.launch_persistent_context(profile, headless=True)
            try:
                page = admin(context)
                before = app_module.commerce.read()
                sku = before['skus'][0]
                url = '/api/admin/purchase_received' if kind == 'purchase' else '/api/admin/expense'
                sent = []
                def lose_response(route):
                    sent.append(route.request.post_data_json)
                    assert route.fetch().status == 200
                    route.abort('failed')
                context.route('**' + url, lose_response)
                if kind == 'purchase':
                    page.locator('[data-sku="'+sku['id']+'"] [data-receive]').click()
                    page.locator('#pos-receive-qty').fill('3')
                    page.locator('#pos-dialog-submit').click()
                else:
                    page.locator('[data-tab="expenses"]').click()
                    page.locator('#pos-expense-amount').fill('37.5')
                    page.locator('#pos-expense-note').fill('durable restart receipt')
                    page.locator('#pos-expense-save').click()
                poll(page, "() => document.getElementById('pos-message').classList.contains('error')")
                saved = page.evaluate("() => JSON.parse(localStorage.getItem('bf-pos2-pending'))")
                assert saved['body'] == sent[0]
                # Existing/new tabs see the same receipt and cannot replace it.
                other = admin(context)
                assert other.locator('#pos-pending').is_visible()
                other.locator('[data-tab="expenses"]').click()
                other.locator('#pos-expense-amount').fill('999')
                other.locator('#pos-expense-save').click()
                poll(other, "() => document.getElementById('pos-message').textContent.includes('未送出')")
                assert other.evaluate("() => JSON.parse(localStorage.getItem('bf-pos2-pending'))") == saved
                page.close()
                other.close()
            finally:
                context.close()  # exits browser; retain only the on-disk profile
            context = engine.launch_persistent_context(profile, headless=True)
            try:
                page = admin(context)
                assert page.locator('#pos-pending').is_visible()
                assert page.evaluate("() => JSON.parse(localStorage.getItem('bf-pos2-pending'))") == saved
                # Expired authentication must not discard an uncertain receipt.
                context.route('**'+url, lambda route: route.fulfill(status=401,content_type='application/json',body='{"status":"error","msg":"login required"}'))
                page.locator('#pos-retry').click()
                poll(page, "() => document.getElementById('pos-message').textContent==='login required'")
                assert page.evaluate("() => JSON.parse(localStorage.getItem('bf-pos2-pending'))") == saved
                context.unroute('**'+url)
                def retry(route):
                    sent.append(route.request.post_data_json)
                    route.continue_()
                context.route('**'+url, retry)
                observer = admin(context)
                assert observer.locator('#pos-pending').is_visible()
                page.locator('#pos-retry').click()
                poll(page, "() => !localStorage.getItem('bf-pos2-pending')")
                poll(observer, "() => document.getElementById('pos-pending').hidden")
                assert len(sent) == 2 and sent[0] == sent[1], sent
                after = app_module.commerce.read()
                if kind == 'purchase':
                    assert after['skus'][0]['stock_qty'] == sku['stock_qty'] + 3
                    entries = [x for x in after['inventory_ledger'] if x.get('receipt_id') == saved['body']['idempotency_key']]
                    assert len(entries) == 1
                else:
                    assert len(after['expenses']) == len(before['expenses']) + 1
                    entries = [x for x in after['expense_ledger'] if x['id'] == saved['body']['idempotency_key']]
                    assert len(entries) == 1
                print('DURABLE_RECEIPT_BROWSER_RESTART_OK', kind)
            finally:
                context.close()


def passkey_login_test(browser, base):
    mock = """(() => {
      window.PublicKeyCredential=function(){};window.__passkeyGetCalls=0;window.__passkeyMode='success';
      Object.defineProperty(navigator,'credentials',{configurable:true,value:{
        create:async()=>null,
        get:async()=>{window.__passkeyGetCalls++;if(window.__passkeyMode==='cancel')throw new DOMException('cancelled','NotAllowedError');return {id:'mock-login-credential',rawId:new Uint8Array([2]).buffer,type:'public-key',authenticatorAttachment:'platform',getClientExtensionResults:()=>({}),response:{clientDataJSON:new Uint8Array([3]).buffer,authenticatorData:new Uint8Array([4]).buffer,signature:new Uint8Array([5]).buffer,userHandle:null}}}
      }});
    })()"""
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    page.add_init_script(mock)
    verify = []
    page.route('**/api/auth/passkey/status', lambda route: route.fulfill(status=200,content_type='application/json',body='{"status":"success","configured":true,"has_credentials":true}'))
    page.route('**/api/auth/passkey/options', lambda route: route.fulfill(status=200,content_type='application/json',body='{"status":"success","ceremony_id":"mock-login","publicKey":{"challenge":"AQ","rpId":"127.0.0.1","allowCredentials":[{"type":"public-key","id":"Ag"}],"userVerification":"required"}}'))
    def verify_login(route):
        verify.append(route.request.post_data_json)
        route.fulfill(status=200,content_type='application/json',body='{"status":"success","redirect":"/api/health"}')
    page.route('**/api/auth/passkey/verify', verify_login)
    page.goto(base + '/login', wait_until='domcontentloaded')
    poll(page, "() => !document.getElementById('passkey-login-button').classList.contains('hidden')")
    assert page.locator('#passkey-login-button').inner_text() == '使用 Face ID 登入'
    assert page.locator('#passkey-login-button').is_visible() and not page.locator('#password-form').is_visible()
    assert page.evaluate('() => window.__passkeyGetCalls') == 0
    page.locator('#passkey-login-button').click()
    page.wait_for_url('**/api/health')
    assert len(verify) == 1 and verify[0]['ceremony_id'] == 'mock-login'
    assert verify[0]['credential']['authenticatorAttachment'] == 'platform'
    page.close()

    cancelled = browser.new_page(viewport={'width': 390, 'height': 844})
    cancelled.add_init_script(mock)
    cancelled.route('**/api/auth/passkey/status', lambda route: route.fulfill(status=200,content_type='application/json',body='{"status":"success","configured":true,"has_credentials":true}'))
    cancelled.route('**/api/auth/passkey/options', lambda route: route.fulfill(status=200,content_type='application/json',body='{"status":"success","ceremony_id":"mock-cancel","publicKey":{"challenge":"AQ","rpId":"127.0.0.1","allowCredentials":[],"userVerification":"required"}}'))
    cancelled.goto(base + '/login', wait_until='domcontentloaded')
    cancelled.evaluate("() => {window.__passkeyMode='cancel'}")
    cancelled.locator('#passkey-login-button').click()
    poll(cancelled, "() => document.getElementById('login-message').textContent.includes('已取消 Face ID 驗證')")
    cancelled.locator('#password-toggle').click()
    assert cancelled.locator('#password-form').is_visible()
    cancelled.close()

    unsupported = browser.new_page(viewport={'width': 390, 'height': 844})
    unsupported.add_init_script("Object.defineProperty(window,'PublicKeyCredential',{configurable:true,value:undefined})")
    unsupported.goto(base + '/login', wait_until='domcontentloaded')
    poll(unsupported, "() => document.getElementById('password-form').classList.contains('show')")
    assert unsupported.locator('#password-form').is_visible()
    assert not unsupported.locator('#passkey-login-button').is_visible()
    unsupported.close()
    print('PASSKEY_LOGIN_WEBKIT_OK')


def main():
    server = ServerThread();server.start();time.sleep(.8)
    try:
        with sync_playwright() as p:
            browser = getattr(p, os.environ.get('BROWSER_ENGINE', 'webkit')).launch()
            try:
                base='http://127.0.0.1:8765';passkey_login_test(browser,base);front_test(browser,base);checkout_test(browser,base);admin_test(browser,base)
                import runpy
                runpy.run_path(str(ROOT / '.github/tests/test_pos_dashboard.py'))['dashboard_test'](browser,base,poll)
            finally: browser.close()
            durable_receipt_test(p, base)
        print('AI_EDITOR_WEBKIT_OK')
    finally:
        server.close()
        # The commerce test runs in local fallback mode; keep CI workspaces clean.
        commerce = ROOT / 'commerce_data.json'
        if commerce.exists():
            try: commerce.unlink()
            except Exception: pass


if __name__ == '__main__': main()
