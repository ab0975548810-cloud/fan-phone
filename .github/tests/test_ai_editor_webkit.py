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
BROWSER_TEST_PORT = int(os.environ.get('BROWSER_TEST_PORT', '8765'))
os.environ['PORT'] = str(BROWSER_TEST_PORT)

test_dir = ROOT / '__pycache__' / f'webkit-test-{os.getpid()}'
test_dir.mkdir(parents=True, exist_ok=True)
os.environ['COMMERCE_DB_PATH'] = str(test_dir / 'commerce.sqlite3')
os.environ['ADMIN_PASSKEYS_FILE'] = str(test_dir / 'admin_passkeys.json')
os.environ['WEBAUTHN_RP_ID'] = '127.0.0.1'
os.environ['WEBAUTHN_ORIGIN'] = f'http://127.0.0.1:{BROWSER_TEST_PORT}'
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
        self.server = make_server('127.0.0.1', BROWSER_TEST_PORT, app_module.app, threaded=True)
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
      // Deliberately varied border forces this fixture through the AI fallback;
      // the separate solid-background regression covers the local connected path.
      ['#ffcad8','#c9e7ff','#ffe6a8','#d8c9ff'].forEach((color,index)=>{{g.fillStyle=color;if(index===0)g.fillRect(0,0,128,5);if(index===1)g.fillRect(0,123,128,5);if(index===2)g.fillRect(0,0,5,128);if(index===3)g.fillRect(123,0,5,128)}});
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
    browser_engine = os.environ.get('BROWSER_ENGINE', 'webkit').lower()
    page = browser.new_page(viewport={'width': 390, 'height': 600})
    responses = [GOOD, BAD]
    backend_ai_requests = []
    def backend_ai_response(route):
        backend_ai_requests.append(route.request.url)
        route.fulfill(status=200, body=responses.pop(0) if responses else GOOD, content_type='image/png')
    page.route('**/api/ai/remove-background', backend_ai_response)
    page.goto(base + '/', wait_until='domcontentloaded')
    poll(page, "() => typeof fabric !== 'undefined' && typeof initCanvas === 'function' && !!window.BenfuwanAiRemoveV2 && !!window.removeBackgroundForActive && !!window.BenfuwanEditorAccess && !!window.BenfuwanOrderPayload && !!window.BenfuwanPrintMask && !!window.BenfuwanProductionHQ && !!window.BenfuwanImageUpload && !!window.BenfuwanTemplateThumbFallback")
    page.set_viewport_size({'width': 390, 'height': 844})
    home = poll(page, """() => {
      const page=document.getElementById('page-home'),hero=document.querySelector('.bf-home-hero'),copy=document.querySelector('.bf-home-hero-copy'),art=document.querySelector('.bf-home-hero-art'),cta=document.querySelector('.bf-home-primary');
      const draftState=document.getElementById('home-design-card')?.dataset.draftState;
      if(!window.BenfuwanFrontHomeV1||!page?.classList.contains('active')||!art?.complete||!art.naturalWidth||!draftState||draftState==='loading')return false;
      const heroBox=hero.getBoundingClientRect(),copyBox=copy.getBoundingClientRect(),artBox=art.getBoundingClientRect(),ctaBox=cta.getBoundingClientRect(),app=document.getElementById('app').getBoundingClientRect();
      const labels=[...document.querySelectorAll('.bf-home-bottom-nav .nav-btn')].map(button=>[...button.childNodes].filter(node=>node.nodeType===Node.TEXT_NODE).map(node=>node.textContent).join('').trim());
      const textFits=[...document.querySelectorAll('.bf-home-primary-copy,.bf-home-quick>span:nth-child(2),.bf-home-banner-copy')].every(node=>node.scrollWidth<=node.clientWidth+1);
      return {
        title:document.getElementById('bf-home-title').textContent.trim(),
        image:[art.naturalWidth,art.naturalHeight],
        appWidth:app.width,pageWidth:page.scrollWidth,documentWidth:document.documentElement.scrollWidth,
        heroBottom:heroBox.bottom,ctaTop:ctaBox.top,copyBottom:copyBox.bottom,artTop:artBox.top,artBottom:artBox.bottom,textFits,labels,
        fakeTabs:labels.filter(label=>['æ¨¡æ¿','æˆ‘çš„ä½œå“','æœƒå“¡'].includes(label)),
        draftState
      };
    }""")
    assert home['title'] == 'æœ¬ç¦ä¸¸è¨‚è£½' and home['image'] == [960, 1026], home
    assert abs(home['appWidth'] - 390) <= 1 and home['pageWidth'] <= 391 and home['documentWidth'] <= 391, home
    assert home['heroBottom'] <= home['ctaTop'] + 1 and home['copyBottom'] <= home['artTop'] + 1 and home['artBottom'] <= home['heroBottom'] + 1 and home['textFits'], home
    assert home['labels'] == ['é¦–é ','é–‹å§‹è£½ä½œ','è³¼ç‰©è»Š'] and home['fakeTabs'] == [], home
    assert home['draftState'] == 'empty', home
    page.locator('.bf-home-quick-template').click()
    poll(page, "() => document.getElementById('page-model')?.classList.contains('active')")
    assert not page.locator('#page-template').evaluate('(node) => node.classList.contains(\'active\')')
    page.evaluate("() => showPage('page-home')")
    page.locator('.bf-home-primary').click()
    poll(page, "() => document.getElementById('page-model')?.classList.contains('active')")
    page.evaluate("() => showPage('page-home')")
    page.locator('.bf-home-bottom-nav .nav-cart-wrap').click()
    poll(page, "() => document.getElementById('page-cart')?.classList.contains('active')")
    page.evaluate("() => showPage('page-home')")
    page.locator('#home-design-card').click()
    poll(page, "() => document.getElementById('toast')?.textContent.includes('ç›®å‰æ²’æœ‰æœªå®Œæˆè¨­è¨ˆ')")
    page.set_viewport_size({'width': 1180, 'height': 900})
    desktop = page.evaluate("""() => {
      const app=document.getElementById('app').getBoundingClientRect(),page=document.getElementById('page-home'),hero=document.querySelector('.bf-home-hero').getBoundingClientRect(),cta=document.querySelector('.bf-home-primary').getBoundingClientRect();
      const art=document.querySelector('.bf-home-hero-art').getBoundingClientRect();return {appWidth:app.width,pageWidth:page.scrollWidth,heroBeforeCta:hero.bottom<=cta.top+1,artInsideHero:art.bottom<=hero.bottom+1};
    }""")
    assert desktop['appWidth'] <= 521 and desktop['pageWidth'] <= 521 and desktop['heroBeforeCta'] and desktop['artInsideHero'], desktop
    home_css = page.locator('link[href*="front-home-v1.css"]').get_attribute('href')
    assert home_css and 'v=20261002hero1' in home_css, home_css
    print('FRONT_HOME_V1_RESPONSIVE_REAL_ACTIONS_OK', browser_engine, {'iphone':home,'desktop':desktop})

    page.route('**/broken-template-thumb.png', lambda route: route.fulfill(status=404, body='missing'))
    page.evaluate("""() => {
      window.__thumbFallbackBackup={templates:structuredClone(templatesData),modelId:ctx.modelId,styleId:ctx.styleId,page:document.querySelector('.page.active')?.id||'page-home'};
      ctx.modelId='fallback-model';ctx.styleId='';
      templatesData={categories:['å…¨éƒ¨'],templates:[
        {id:'broken-thumb',name:'å£åœ–æ¨¡æ¿',model_id:'*',universal:true,thumb_url:'/broken-template-thumb.png'},
        {id:'empty-thumb',name:'ç©ºåœ–æ¨¡æ¿',model_id:'*',universal:true,thumb_url:''}
      ]};
      showPage('page-template');
      renderTemplates();
    }""")
    thumb_fallback = poll(page, """() => {
      const imgs=[...document.querySelectorAll('#tpl-grid .tpl-card img')];
      if(imgs.length!==2)return false;
      if(!imgs.every(img=>img.dataset.bfFallback==='1'&&img.complete&&img.naturalWidth>0&&getComputedStyle(img).visibility==='visible'))return false;
      return imgs.map(img=>({src:img.getAttribute('src'),objectFit:img.style.objectFit,padding:img.style.padding,alt:img.alt,natural:[img.naturalWidth,img.naturalHeight]}));
    }""")
    assert all('/static/front-assets/benfuwan-case-fallback.webp' in row['src'] for row in thumb_fallback), thumb_fallback
    assert all(row['objectFit']=='contain' and row['padding']=='10px' and row['natural'][0]>0 and row['natural'][1]>0 for row in thumb_fallback), thumb_fallback
    page.evaluate("""() => {
      const previous=window.__thumbFallbackBackup.page||'page-home';
      templatesData=window.__thumbFallbackBackup.templates;
      ctx.modelId=window.__thumbFallbackBackup.modelId;
      ctx.styleId=window.__thumbFallbackBackup.styleId;
      delete window.__thumbFallbackBackup;
      renderTemplates();
      showPage(previous);
    }""")
    page.unroute('**/broken-template-thumb.png')
    print('FRONT_TEMPLATE_BROKEN_THUMB_USES_CASE_FALLBACK_OK', thumb_fallback)
    template_src = page.locator('script[src*="front-universal-templates.js"]').get_attribute('src')
    assert template_src and 'v=20261001fallback1' in template_src, template_src

    page.set_viewport_size({'width': 390, 'height': 600})
    upload_regression = page.evaluate("""async () => {
      const api=window.BenfuwanImageUpload;
      const loadImage=src=>new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=reject;image.src=src});
      const source=document.createElement('canvas');source.width=2030;source.height=4241;
      const sourceContext=source.getContext('2d',{alpha:true});sourceContext.clearRect(0,0,source.width,source.height);
      sourceContext.fillStyle='rgba(255,0,0,.5)';sourceContext.fillRect(1000,2100,20,20);
      const sourceBlob=await new Promise((resolve,reject)=>source.toBlob(blob=>blob?resolve(blob):reject(new Error('PNG fixture failed')),'image/png'));
      const tenMiB=10*1024*1024;
      const padding=new Uint8Array(Math.max(1,tenMiB+1-sourceBlob.size));
      const largePng=new File([sourceBlob,padding],'transparent-large.png',{type:'image/png'});
      const pngData=await api.prepareImageDataURL(largePng);
      const pngImage=await loadImage(pngData);
      const sample=document.createElement('canvas');sample.width=1;sample.height=1;
      sample.getContext('2d').drawImage(pngImage,1005,2105,1,1,0,0,1,1);
      const pngAlpha=sample.getContext('2d').getImageData(0,0,1,1).data[3];

      const UTIF=await api.loadTiffDecoder();
      const rgba=new Uint8Array([255,0,0,255,0,255,0,128,0,0,255,0,255,255,255,255]);
      const savedPako=window.pako;let encoded;
      try{window.pako=null;encoded=UTIF.encodeImage(rgba.buffer,2,2)}finally{window.pako=savedPako}
      const tifData=await api.prepareImageDataURL(new File([encoded],'alpha.tif',{type:'image/tiff'}));
      const tiffData=await api.prepareImageDataURL(new File([encoded],'alpha.tiff',{type:''}));
      const tifImage=await loadImage(tifData),tiffImage=await loadImage(tiffData);
      const tifCanvas=document.createElement('canvas');tifCanvas.width=2;tifCanvas.height=2;
      const tifContext=tifCanvas.getContext('2d');tifContext.drawImage(tifImage,0,0);
      const tifAlpha=Array.from(tifContext.getImageData(0,0,2,2).data).filter((_,index)=>index%4===3);

      const oversizedHeader=new Uint8Array(24);oversizedHeader.set([137,80,78,71,13,10,26,10],0);
      oversizedHeader.set([73,72,68,82],12);const oversizedView=new DataView(oversizedHeader.buffer);
      oversizedView.setUint32(16,9000,false);oversizedView.setUint32(20,9000,false);
      let pixelError='';try{await api.prepareImageDataURL(new File([oversizedHeader],'too-many-pixels.png',{type:'image/png'}))}catch(error){pixelError=error.message}
      let byteError='';try{await api.prepareImageDataURL({name:'too-large.png',type:'image/png',size:50*1024*1024+1})}catch(error){byteError=error.message}
      return {
        acceptPhoto:document.getElementById('photo-input').accept,
        acceptSlot:document.getElementById('slot-input').accept,
        pngBytes:largePng.size,pngPrefix:pngData.slice(0,22),pngWidth:pngImage.naturalWidth,pngHeight:pngImage.naturalHeight,pngAlpha,
        tifPrefix:tifData.slice(0,22),tiffPrefix:tiffData.slice(0,22),tifWidth:tifImage.naturalWidth,tifHeight:tifImage.naturalHeight,
        tiffWidth:tiffImage.naturalWidth,tiffHeight:tiffImage.naturalHeight,tifAlpha,
        emptyMimeKind:api.imageKind(new File([encoded],'alpha.tiff',{type:''})),imageTifKind:api.imageKind(new File([encoded],'alpha.bin',{type:'image/tif'})),
        maxBytes:api.PNG_TIFF_MAX_BYTES,maxPixels:api.MAX_DECODED_PIXELS,maxEdge:api.MAX_IMAGE_EDGE,pixelError,byteError
      };
    }""")
    expected_accept = '.png,.tif,.tiff,image/png,image/tiff,image/jpeg,image/webp'
    assert upload_regression['acceptPhoto'] == expected_accept and upload_regression['acceptSlot'] == expected_accept, upload_regression
    assert upload_regression['pngBytes'] > 10 * 1024 * 1024 and upload_regression['pngPrefix'] == 'data:image/png;base64,', upload_regression
    assert (upload_regression['pngWidth'], upload_regression['pngHeight']) == (2030, 4241), upload_regression
    assert 100 <= upload_regression['pngAlpha'] <= 155, upload_regression
    assert upload_regression['tifPrefix'] == 'data:image/png;base64,' and upload_regression['tiffPrefix'] == 'data:image/png;base64,', upload_regression
    assert (upload_regression['tifWidth'], upload_regression['tifHeight']) == (2, 2), upload_regression
    assert (upload_regression['tiffWidth'], upload_regression['tiffHeight']) == (2, 2), upload_regression
    assert upload_regression['tifAlpha'] == [255, 128, 0, 255], upload_regression
    assert upload_regression['emptyMimeKind'] == 'tiff' and upload_regression['imageTifKind'] == 'tiff', upload_regression
    assert upload_regression['maxBytes'] == 50 * 1024 * 1024 and upload_regression['maxPixels'] == 32_000_000 and upload_regression['maxEdge'] == 8192, upload_regression
    assert 'åƒç´ éå¤§' in upload_regression['pixelError'] and '50MB' in upload_regression['byteError'], upload_regression
    print('FRONT_HIGH_RES_PNG_TIFF_UPLOAD_OK', upload_regression)
    universal_remove = page.evaluate("""async () => {
      const core=window.BenfuwanAiRemoveV2,source=document.createElement('canvas');source.width=640;source.height=480;
      const g=source.getContext('2d',{alpha:true});g.fillStyle='#f7d8e1';g.fillRect(0,0,640,480);
      g.fillStyle='#c52f67';g.fillRect(90,80,180,300);
      g.fillStyle='#fff';g.beginPath();g.arc(500,110,42,0,Math.PI*2);g.fill();
      g.strokeStyle='#111';g.lineWidth=8;g.stroke();
      const input=await core.sourceBlobFromElement(source,{maxEdge:4096,maxBytes:6*1024*1024});
      const result=await core.universalRemoveFromElement(source,{localOnly:true});
      const output=await new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=reject;image.src=URL.createObjectURL(result.blob)});
      const c=document.createElement('canvas');c.width=output.naturalWidth;c.height=output.naturalHeight;const cg=c.getContext('2d',{willReadFrequently:true});cg.drawImage(output,0,0);
      const alpha=(x,y)=>cg.getImageData(x,y,1,1).data[3];
      return {inputType:input.type,mode:result.mode,type:result.blob.type,width:output.naturalWidth,height:output.naturalHeight,corner:alpha(0,0),main:alpha(150,200),isolatedWhite:alpha(500,110)};
    }""")
    assert universal_remove['inputType'] == 'image/png' and universal_remove['type'] == 'image/png', universal_remove
    assert universal_remove['mode'] == 'edge-connected', universal_remove
    assert (universal_remove['width'], universal_remove['height']) == (640, 480), universal_remove
    assert universal_remove['corner'] == 0 and universal_remove['main'] > 250 and universal_remove['isolatedWhite'] > 250, universal_remove
    print('FRONT_UNIVERSAL_CONNECTED_BACKGROUND_HIGH_RES_OK', universal_remove)
    transparent_decontaminate = page.evaluate("""async () => {
      const core=window.BenfuwanAiRemoveV2,source=document.createElement('canvas');source.width=96;source.height=96;
      const g=source.getContext('2d',{alpha:true,willReadFrequently:true}),image=g.createImageData(96,96),d=image.data;
      const pixel=(x,y,r,g,b,a)=>{const i=(y*96+x)*4;d[i]=r;d[i+1]=g;d[i+2]=b;d[i+3]=a};
      for(let y=32;y<64;y++)for(let x=32;x<64;x++)pixel(x,y,255,255,255,255);
      for(let y=31;y<=64;y++)for(let x=31;x<=64;x++)if(x===31||x===64||y===31||y===64)pixel(x,y,255,255,255,64);
      g.putImageData(image,0,0);
      const result=await core.universalRemoveFromElement(source,{localOnly:true}),output=await new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=reject;image.src=URL.createObjectURL(result.blob)});
      const c=document.createElement('canvas');c.width=96;c.height=96;const cg=c.getContext('2d',{willReadFrequently:true});cg.drawImage(output,0,0);const sample=(x,y)=>Array.from(cg.getImageData(x,y,1,1).data);
      return {mode:result.mode,type:result.blob.type,opaqueWhite:sample(40,40),halo:sample(31,40),transparent:sample(0,0)};
    }""")
    assert transparent_decontaminate['mode'] == 'transparent-decontaminated' and transparent_decontaminate['type'] == 'image/png', transparent_decontaminate
    assert transparent_decontaminate['opaqueWhite'] == [255,255,255,255], transparent_decontaminate
    assert transparent_decontaminate['halo'][3] < 40 and transparent_decontaminate['transparent'][3] == 0, transparent_decontaminate
    print('FRONT_TRANSPARENT_PNG_DECONTAMINATE_OPAQUE_WHITE_OK', transparent_decontaminate)
    assert backend_ai_requests == [], backend_ai_requests
    print('FRONT_LOCAL_BACKGROUND_REMOVAL_DOES_NOT_SPEND_CLOUD_QUOTA_OK')
    transparent_stripes = page.evaluate("""async () => {
      const core=window.BenfuwanAiRemoveV2,w=2030,h=4241,source=document.createElement('canvas');source.width=w;source.height=h;
      const g=source.getContext('2d',{alpha:true,willReadFrequently:true});g.clearRect(0,0,w,h);g.fillStyle='rgba(255,255,255,.25)';g.fillRect(599,999,832,2202);g.fillStyle='#fff';g.fillRect(600,1000,830,2200);
      const contextPrototype=CanvasRenderingContext2D.prototype,nativeGetImageData=contextPrototype.getImageData,NativeArray=window.Uint8ClampedArray,fullBytes=w*h*4;
      let maxReadRows=0,fullReads=0,fullCopies=0,blob;
      contextPrototype.getImageData=function(x,y,width,height){if(this.canvas.width===w&&this.canvas.height===h){maxReadRows=Math.max(maxReadRows,height);if(width*height===w*h)fullReads++}return nativeGetImageData.call(this,x,y,width,height)};
      window.Uint8ClampedArray=new Proxy(NativeArray,{construct(target,args,newTarget){const value=args[0],length=typeof value==='number'?value:Number(value?.length||0);if(length>=fullBytes)fullCopies++;return Reflect.construct(target,args,newTarget)}});
      try{blob=await core.decontaminateTransparentElement(source,{stripeRows:384})}finally{contextPrototype.getImageData=nativeGetImageData;window.Uint8ClampedArray=NativeArray}
      const output=await new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=reject;image.src=URL.createObjectURL(blob)});
      g.clearRect(0,0,w,h);g.drawImage(output,0,0);const sample=(x,y)=>Array.from(g.getImageData(x,y,1,1).data);
      return {type:blob.type,width:output.naturalWidth,height:output.naturalHeight,opaqueWhite:sample(700,1500),halo:sample(599,1500),transparent:sample(0,0),maxReadRows,fullReads,fullCopies};
    }""")
    assert transparent_stripes['type'] == 'image/png' and (transparent_stripes['width'], transparent_stripes['height']) == (2030,4241), transparent_stripes
    assert transparent_stripes['opaqueWhite'] == [255,255,255,255] and transparent_stripes['halo'][3] < 40 and transparent_stripes['transparent'][3] == 0, transparent_stripes
    assert transparent_stripes['maxReadRows'] <= 386 and transparent_stripes['fullReads'] == 0 and transparent_stripes['fullCopies'] == 0, transparent_stripes
    print('FRONT_HIGH_RES_TRANSPARENT_STRIPE_DECONTAMINATE_OK', transparent_stripes)
    high_res_cache = page.evaluate("""async () => {
      const core=window.BenfuwanAiRemoveV2;
      const make=(w,h)=>{const c=document.createElement('canvas');c.width=w;c.height=h;const g=c.getContext('2d',{alpha:true});g.clearRect(0,0,w,h);g.fillStyle='#fff';g.fillRect(w*.25,h*.25,w*.5,h*.5);return c};
      const small=make(1200,2400),large=make(2400,4800),smallKey=await core.cacheIdentityFromElement(small),largeKey=await core.cacheIdentityFromElement(large),result=await core.universalRemoveFromElement(large,{localOnly:true});
      const output=await new Promise((resolve,reject)=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=reject;image.src=URL.createObjectURL(result.blob)}),answer={smallKey,largeKey,mode:result.mode,width:output.naturalWidth,height:output.naturalHeight,type:result.blob.type};small.width=small.height=large.width=large.height=1;return answer;
    }""")
    assert high_res_cache['smallKey'] and high_res_cache['largeKey'] and high_res_cache['smallKey'] != high_res_cache['largeKey'], high_res_cache
    assert (high_res_cache['width'], high_res_cache['height']) == (2400,4800) and high_res_cache['type'] == 'image/png', high_res_cache
    print('FRONT_HIGH_RES_CACHE_IDENTITY_AND_OUTPUT_DIMENSIONS_OK', high_res_cache['mode'], high_res_cache['width'], high_res_cache['height'])
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
    crystal_style = {'id':'style_1789287807818','name':'æ™¶å½©ç£å¸é˜²æ‘”æ®¼','status':True}
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
    assert not blocked_profile['modelNext'] and blocked_profile['styleNext'] and blocked_profile['badges'] == 1 and 'å°šæœªå®Œæˆç”Ÿç”¢è¨­å®š' in blocked_profile['toast'], blocked_profile
    print('FRONT_MODEL_STYLE_PROFILE_AUDIT_FAIL_CLOSED_OK', profile_audit, blocked_profile)
    legacy_crystal_only = page.evaluate("""({models,crystal}) => {
      const model=models.find(row=>row.id==='model_apple_14_pro_max');
      const selected=selectModel(model);
      const styled=selectStyle(crystal);
      const mirror=selectStyle({id:'style_mirror',name:'é¡é¢æ®¼',price:390,mask_img:'style-preview',line_img:'style-print',print_w:99,print_h:199,colors:[]});
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
      const crystal={id:'crystal',name:'æ™¶å½©',colors:['é€æ˜','ç²‰']},mirror={id:'mirror',name:'é¡é¢',colors:['éŠ€','é»‘']};
      shopData.models=[configured];shopData.styles=[crystal,mirror];selectModel(configured);selectStyle(crystal);
      const first={mask:ctx.maskUrl,line:ctx.printLineUrl,w:ctx.printW,h:ctx.printH,x:ctx.printX,y:ctx.printY};
      selectStyle(mirror);const second={mask:ctx.maskUrl,line:ctx.printLineUrl,w:ctx.printW,h:ctx.printH,x:ctx.printX,y:ctx.printY};
      return {first,second,crystalColors:window.BenfuwanModelColors?.colorsFor?.(crystal,configured.id)||crystal.colors};
    }""", fixture_models[0])
    assert style_isolation['first'] == {'mask':'fixture://crystal-preview','line':'fixture://crystal-print','w':70,'h':140,'x':1,'y':2}, style_isolation
    assert style_isolation['second'] == {'mask':'fixture://mirror-preview','line':'fixture://mirror-print','w':75,'h':150,'x':3,'y':4}, style_isolation
    print('FRONT_TWO_STYLES_INDEPENDENT_PROFILE_COLOR_SHARED_OK', style_isolation)
    template_geometry = page.evaluate("""() => {
      const model={id:'tpl-model',preview_mask_img:'fixture://legacy-crystal-preview',print_line_img:'fixture://legacy-crystal-print',print_w:72,print_h:142,case_profiles:{
        crystal:{preview_mask_img:'fixture://cp',print_line_img:'fixture://cl',print_w:70,print_h:140},
        mirror:{preview_mask_img:'fixture://mp',print_line_img:'fixture://ml',print_w:75,print_h:150}
      }};
      shopData.models=[model];ctx.printW=75;ctx.printH=150;ctx.printLineUrl='fixture://target';
      const crystal=BenfuwanTemplateGeometry.sourceGeometry({reference_model_id:'tpl-model',reference_style_id:'crystal'});
      const mirror=BenfuwanTemplateGeometry.sourceGeometry({reference_model_id:'tpl-model',reference_style_id:'mirror'});
      const legacyTemplate={model_id:'*',universal:true,reference_model_id:'tpl-model',source_print_w:68,source_print_h:138,source_canvas_w:136,source_canvas_h:276};
      const legacy=BenfuwanTemplateGeometry.sourceGeometry(legacyTemplate);
      const explicitLegacyCrystal=BenfuwanTemplateGeometry.sourceGeometry({...legacyTemplate,reference_style_id:BenfuwanModelProfile.LEGACY_CRYSTAL_STYLE_ID});
      const oldMirror=BenfuwanTemplateGeometry.sourceGeometry({...legacyTemplate,case_style_id:'mirror'});
      let failed=false;try{BenfuwanTemplateGeometry.sourceGeometry({reference_model_id:'tpl-model'})}catch(e){failed=true}
      const target=BenfuwanTemplateGeometry.targetGeometry();
      return {crystal:{w:crystal.w,h:crystal.h,mask:crystal.mask},mirror:{w:mirror.w,h:mirror.h,mask:mirror.mask},legacy:{w:legacy.w,h:legacy.h,mask:legacy.mask},explicitLegacyCrystal:{w:explicitLegacyCrystal.w,h:explicitLegacyCrystal.h,mask:explicitLegacyCrystal.mask},oldMirror:{w:oldMirror.w,h:oldMirror.h,mask:oldMirror.mask},failed,target:{w:target.w,h:target.h,mask:target.mask}};
    }""")
    assert template_geometry == {
        'crystal': {'w':70,'h':140,'mask':'fixture://cl'},
        'mirror': {'w':75,'h':150,'mask':'fixture://ml'},
        'legacy': {'w':68,'h':138,'mask':'fixture://legacy-crystal-print'},
        'explicitLegacyCrystal': {'w':68,'h':138,'mask':'fixture://legacy-crystal-print'},
        'oldMirror': {'w':68,'h':138,'mask':'fixture://ml'},
        'failed': True,
        'target': {'w':75,'h':150,'mask':'fixture://target'},
    }, template_geometry
    print('FRONT_TEMPLATE_LEGACY_CRYSTAL_MASK_AND_EXPLICIT_STYLE_PRECEDENCE_OK', template_geometry)
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
        const expectedContext=expected.getContext('2d',{willReadFrequently:true});expectedContext.imageSmoothingEnabled=true;expectedContext.imageSmoothingQuality='high';expectedContext.drawImage(preview,0,0,...target);
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
      ctx.modelId='model_apple_14_pro_max';ctx.modelName='iPhone 14 Pro Max';ctx.styleId='style_crystal';ctx.styleName='æ™¶å½©ç£å¸é˜²æ‘”æ®¼';
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
    retina_before = page.evaluate("""() => {
      const box=el=>{const r=el.getBoundingClientRect();return [Math.round(r.width*1000)/1000,Math.round(r.height*1000)/1000]};
      return {dpr:window.devicePixelRatio,logical:[canvas.width,canvas.height],shell:box(document.getElementById('canvas-shell')),overlay:box(document.getElementById('phone-mask')),guide:box(document.getElementById('print-area-guide'))};
    }""")
    page.evaluate("""() => {
      window.__bfTestOriginalDpr=window.devicePixelRatio;
      Object.defineProperty(window,'devicePixelRatio',{configurable:true,value:4});
      applyCaseBoundaryClip();
    }""")
    retina_overlay = poll(page, """() => {
      const overlay=document.getElementById('phone-mask'),guide=document.getElementById('print-area-guide');
      if(!overlay?.complete||!guide?.complete||overlay.naturalWidth!==720||overlay.naturalHeight!==1440||guide.naturalWidth!==720||guide.naturalHeight!==1440)return false;
      const box=el=>{const r=el.getBoundingClientRect();return [Math.round(r.width*1000)/1000,Math.round(r.height*1000)/1000]};
      return {dpr:BenfuwanPrintMask.previewDpr(),logical:[canvas.width,canvas.height],shell:box(document.getElementById('canvas-shell')),overlayCss:box(overlay),guideCss:box(guide),overlayBacking:[overlay.naturalWidth,overlay.naturalHeight],guideBacking:[guide.naturalWidth,guide.naturalHeight]};
    }""")
    assert retina_overlay == {
        'dpr': 3, 'logical': retina_before['logical'], 'shell': retina_before['shell'],
        'overlayCss': retina_before['overlay'], 'guideCss': retina_before['guide'],
        'overlayBacking': [720,1440], 'guideBacking': [720,1440],
    }, (retina_before, retina_overlay)
    page.evaluate("""() => {
      Object.defineProperty(window,'devicePixelRatio',{configurable:true,value:window.__bfTestOriginalDpr});
      applyCaseBoundaryClip();delete window.__bfTestOriginalDpr;
    }""")
    poll(page, "() => {const m=document.getElementById('phone-mask'),g=document.getElementById('print-area-guide');return m?.naturalWidth===240&&m?.naturalHeight===480&&g?.naturalWidth===240&&g?.naturalHeight===480}")
    print('FRONT_RETINA_OVERLAY_GUIDE_BACKING_ONLY_OK', retina_overlay)
    assert_front_editor_geometry(page, 'iphone-constrained-unselected')
    add_front_photo(page, 0)
    page.evaluate("() => window.BenfuwanEditorAccess.fitCanvas()")
    assert_front_editor_geometry(page, 'iphone-constrained-selected')
    page.evaluate("""() => {
      const o=canvas.getActiveObject();o.set({angle:27,scaleX:.82,scaleY:.82});o.setCoords();canvas.requestRenderAll();
    }""")
    assert_front_editor_geometry(page, 'iphone-object-transform')
    position_controls = page.evaluate("""() => {
      const o=canvas.getActiveObject(),near=(a,b)=>Math.abs(a-b)<.001;
      const start=o.getCenterPoint(),before={angle:o.angle,scaleX:o.scaleX,scaleY:o.scaleY,opacity:o.opacity,clipPath:o.clipPath};
      nudgeActive(0,-1);const up=o.getCenterPoint();
      nudgeActive(0,1);const down=o.getCenterPoint();
      nudgeActive(-1,0);const left=o.getCenterPoint();
      nudgeActive(1,0);const right=o.getCenterPoint();
      centerActive('horizontal');const horizontal=o.getCenterPoint();
      centerActive('vertical');const bothFromAxes=o.getCenterPoint();
      o.setPositionByOrigin(new fabric.Point(17,23),'center','center');o.setCoords();
      centerActive('both');const full=o.getCenterPoint();
      return {
        step:{up:[up.x-start.x,up.y-start.y],down:[down.x-up.x,down.y-up.y],left:[left.x-down.x,left.y-down.y],right:[right.x-left.x,right.y-left.y]},
        horizontal:[horizontal.x,horizontal.y],bothFromAxes:[bothFromAxes.x,bothFromAxes.y],full:[full.x,full.y],canvas:[canvas.width,canvas.height],
        preserved:near(o.angle,before.angle)&&near(o.scaleX,before.scaleX)&&near(o.scaleY,before.scaleY)&&o.opacity===before.opacity&&o.clipPath===before.clipPath
      };
    }""")
    assert position_controls['step'] == {'up':[0,-1],'down':[0,1],'left':[-1,0],'right':[1,0]}, position_controls
    assert abs(position_controls['horizontal'][0] - position_controls['canvas'][0] / 2) < .001, position_controls
    assert abs(position_controls['bothFromAxes'][0] - position_controls['canvas'][0] / 2) < .001 and abs(position_controls['bothFromAxes'][1] - position_controls['canvas'][1] / 2) < .001, position_controls
    assert position_controls['full'] == [position_controls['canvas'][0] / 2, position_controls['canvas'][1] / 2], position_controls
    assert position_controls['preserved'], position_controls
    print('FRONT_OBJECT_NUDGE_AND_CENTER_OK', position_controls['step'], position_controls['full'])

    page.evaluate("() => openAdjustSheet()")
    page.wait_for_timeout(350)
    slider_css = page.evaluate("""() => {
      const opacity=document.getElementById('opacity-range'),angle=document.getElementById('angle-range'),body=document.querySelector('#sheet-adjust .sheet-body');
      const style=getComputedStyle(opacity),thumb=getComputedStyle(opacity,'::-webkit-slider-thumb');
      return {opacityHeight:opacity.getBoundingClientRect().height,angleHeight:angle.getBoundingClientRect().height,touchAction:style.touchAction,bodyScroll:body.scrollTop,thumbWidth:thumb.width};
    }""")
    assert slider_css['opacityHeight'] >= 44 and slider_css['angleHeight'] >= 44, slider_css
    assert slider_css['touchAction'] == 'none', slider_css
    page.evaluate("""() => {
      window.__rangeTrusted=[];
      for(const id of ['opacity-range','angle-range'])for(const type of ['pointerdown','input','change'])document.getElementById(id).addEventListener(type,event=>window.__rangeTrusted.push({id,type,trusted:event.isTrusted}));
    }""")
    page.wait_for_timeout(250)
    opacity_slider = page.locator('#opacity-range')
    opacity_box = opacity_slider.bounding_box()
    assert opacity_box, 'opacity slider missing'
    opacity_slider.click(position={'x': opacity_box['width'] - 1, 'y': opacity_box['height'] / 2})
    assert float(opacity_slider.input_value()) >= 98, opacity_slider.input_value()
    opacity_history = page.evaluate("() => historyStack.length")
    opacity_y = opacity_box['y'] + opacity_box['height'] / 2
    if browser_engine == 'webkit':
        opacity_slider.hover(position={'x': opacity_box['width'] - 1, 'y': opacity_box['height'] / 2})
        page.mouse.down()
        page.mouse.move(opacity_box['x'] + opacity_box['width'] * .4, opacity_y, steps=12)
        opacity_live = page.evaluate("() => ({value:+document.getElementById('opacity-range').value,opacity:canvas.getActiveObject().opacity,history:historyStack.length,scroll:document.querySelector('#sheet-adjust .sheet-body').scrollTop})")
        assert opacity_live['history'] == opacity_history, opacity_live
        page.mouse.up()
    else:
        opacity_slider.click(position={'x': opacity_box['width'] * .4, 'y': opacity_box['height'] / 2})
        opacity_live = page.evaluate("() => ({value:+document.getElementById('opacity-range').value,opacity:canvas.getActiveObject().opacity,history:historyStack.length,scroll:document.querySelector('#sheet-adjust .sheet-body').scrollTop})")
    assert 34 <= opacity_live['value'] <= 46 and abs(opacity_live['opacity'] - opacity_live['value'] / 100) < .001, opacity_live
    assert opacity_live['scroll'] == slider_css['bodyScroll'], opacity_live
    page.wait_for_timeout(100)
    assert page.evaluate("() => historyStack.length") == opacity_history + 1, 'opacity drag should record exactly one history entry'

    angle_slider = page.locator('#angle-range')
    angle_box = angle_slider.bounding_box()
    assert angle_box, 'angle slider missing'
    angle_slider.click(position={'x': angle_box['width'] / 2, 'y': angle_box['height'] / 2})
    assert abs(float(angle_slider.input_value())) <= 2, angle_slider.input_value()
    angle_history = page.evaluate("() => historyStack.length")
    angle_y = angle_box['y'] + angle_box['height'] / 2
    if browser_engine == 'webkit':
        angle_slider.hover(position={'x': angle_box['width'] / 2, 'y': angle_box['height'] / 2})
        page.mouse.down()
        page.mouse.move(angle_box['x'] + angle_box['width'] * .75, angle_y, steps=12)
        angle_live = page.evaluate("() => ({value:+document.getElementById('angle-range').value,angle:canvas.getActiveObject().angle,history:historyStack.length,scroll:document.querySelector('#sheet-adjust .sheet-body').scrollTop})")
        assert angle_live['history'] == angle_history, angle_live
        page.mouse.up()
    else:
        angle_slider.click(position={'x': angle_box['width'] * .75, 'y': angle_box['height'] / 2})
        angle_live = page.evaluate("() => ({value:+document.getElementById('angle-range').value,angle:canvas.getActiveObject().angle,history:historyStack.length,scroll:document.querySelector('#sheet-adjust .sheet-body').scrollTop})")
    assert 80 <= angle_live['value'] <= 100 and abs(angle_live['angle'] - angle_live['value']) < .001, angle_live
    assert angle_live['scroll'] == slider_css['bodyScroll'], angle_live
    page.wait_for_timeout(100)
    assert page.evaluate("() => historyStack.length") == angle_history + 1, 'angle drag should record exactly one history entry'
    trusted_events = page.evaluate("() => window.__rangeTrusted")
    assert trusted_events and all(event['trusted'] for event in trusted_events), trusted_events
    for slider_id in ('opacity-range', 'angle-range'):
        assert any(event['id'] == slider_id and event['type'] == 'pointerdown' for event in trusted_events), trusted_events
        assert any(event['id'] == slider_id and event['type'] == 'input' for event in trusted_events), trusted_events
        assert any(event['id'] == slider_id and event['type'] == 'change' for event in trusted_events), trusted_events
    page.evaluate("""() => {closeSheets();const o=canvas.getActiveObject();o.set({opacity:1,angle:27});o.setCoords();canvas.requestRenderAll()}""")
    print('FRONT_RANGE_POINTER_INTERACTION_OK', browser_engine, opacity_live['value'], angle_live['value'], slider_css)

    font_result = page.evaluate("""async () => {
      document.getElementById('text-input').value='æœ¬ç¦ä¸¸å¯æ„›ç²‰åœ“';
      document.getElementById('text-font').value='jf-openhuninn';
      document.getElementById('text-bold').checked=false;
      await addTextFromControls();
      const o=canvas.getActiveObject();
      await ensureCanvasFonts();
      const serialized=canvas.toJSON(CUSTOM_PROPS).objects.find(item=>item.role==='text');
      const exported=canvas.toDataURL({format:'png',multiplier:1});
      return {family:o?.fontFamily,loaded:document.fonts.check('16px "jf-openhuninn"','æœ¬ç¦ä¸¸å¯æ„›ç²‰åœ“'),serialized:serialized?.fontFamily,exported:exported.startsWith('data:image/png;base64,'),option:document.querySelector('#text-font option[value="jf-openhuninn"]')?.textContent};
    }""")
    assert font_result == {'family':'jf-openhuninn','loaded':True,'serialized':'jf-openhuninn','exported':True,'option':'å¯æ„›ç²‰åœ“'}, font_result
    page.evaluate("""() => {const photo=canvas.getObjects().find(o=>o.role==='photo');canvas.setActiveObject(photo);canvas.requestRenderAll();syncSelection()}""")
    print('FRONT_HUNINN_FONT_EXPORT_OK', font_result)
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


def design_draft_test(browser, base):
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    draft_preview = fixture_data_url('iphone13-preview.png')
    draft_print = fixture_data_url('iphone13-print.png')

    def configure_draft_catalog(route):
        response = route.fetch()
        payload = response.json()
        catalog = payload.get('data', payload)
        models = [row for row in catalog.get('models', []) if row and row.get('status') is not False]
        styles = [row for row in catalog.get('styles', []) if row and row.get('status') is not False]
        assert models and styles, 'draft fixture requires one active model and style'
        model, style = models[0], styles[0]
        model.setdefault('case_profiles', {})[style['id']] = {
            'preview_mask_img': draft_preview,
            'print_line_img': draft_print,
            'print_x': 0,
            'print_y': 0,
            'print_w': 80,
            'print_h': 160,
            'print_angle': 0,
        }
        style.setdefault('model_colors', {})[model['id']] = ['é€æ˜', 'é»‘']
        route.fulfill(response=response, body=json.dumps(payload, ensure_ascii=False))

    page.route('**/api/shop_data', configure_draft_catalog)
    page.route('**/api/create_order', lambda route: route.fulfill(
        status=200,
        content_type='application/json',
        body='{"status":"success","order_id":"DRAFT-TEST","total":390}'
    ))
    page.goto(base + '/', wait_until='domcontentloaded')
    poll(page, "() => !!window.BenfuwanDesignDraft && !!window.BenfuwanModelProfile && shopData.models?.length")

    initial = page.evaluate("""async () => {
      await BenfuwanDesignDraft.clearDraft();
      const colorList=(model,style)=>{const raw=style.model_colors?.[model.id]||style.colors||[];return (Array.isArray(raw)?raw:String(raw||'').split(/[,ï¼Œ]/)).map(x=>String(x).trim()).filter(Boolean)};
      const model=(shopData.models||[]).find(row=>row?.status!==false);
      const style=(shopData.styles||[]).find(row=>row?.status!==false);
      if(!model||!style)throw new Error('Missing deterministic model/style fixture');
      const pair={model,style,colors:colorList(model,style)};
      if(!BenfuwanModelProfile.profileFor(model,style.id).ready||pair.colors.length<2)throw new Error('Invalid deterministic model/style fixture');
      selectModel(pair.model);if(selectStyle(pair.style)===false)throw new Error('Configured style rejected');if(pair.colors.length)chooseCaseColor(pair.colors[0]);startEditor(false);
      const imageSource=document.createElement('canvas');imageSource.width=12;imageSource.height=18;
      const imageContext=imageSource.getContext('2d',{alpha:true});imageContext.clearRect(0,0,12,18);imageContext.fillStyle='rgba(255,0,0,.7)';imageContext.fillRect(1,1,10,16);
      const photo=await new Promise((resolve,reject)=>fabric.Image.fromURL(imageSource.toDataURL('image/png'),image=>image?resolve(image):reject(new Error('draft image failed'))));
      const aiSource=photo.getSrc();
      photo.set({left:71,top:93,originX:'center',originY:'center',scaleX:1.4,scaleY:1.2,angle:23,opacity:.62,role:'photo',originalName:'draft-photo.png',clipPath:baseClip,aiBackgroundRemoved:true,aiRemovalMode:'universal-v3',aiOutlineSource:aiSource,aiOutlineStrength:'0',aiOutlineStyle:'none',aiOutlineWidth:9,aiOutlineColor:'#ffffff'});
      styleEditableObject(photo);canvas.add(photo);canvas.setActiveObject(photo);recordHistory();
      return {modelId:ctx.modelId,styleId:ctx.styleId,colorName:ctx.colorName||'',width:canvas.width,height:canvas.height,aiSource,aiWidth:photo.width,aiHeight:photo.height};
    }""")
    image_draft = poll(page, "() => idbGet(BenfuwanDesignDraft.key).then(draft => draft?.version === 1 ? draft : false)", timeout=10000)
    assert image_draft and image_draft['version'] == 1
    assert image_draft['modelId'] == initial['modelId'] and image_draft['styleId'] == initial['styleId']
    assert image_draft['colorName'] == initial['colorName']
    assert image_draft['logicalCanvasWidth'] == initial['width'] and image_draft['logicalCanvasHeight'] == initial['height']
    assert [obj.get('role') for obj in image_draft['canvasJson']['objects']] == ['photo']
    initial_ai = image_draft['canvasJson']['objects'][0]
    assert initial_ai['aiRemovalMode'] == 'universal-v3' and initial_ai['aiOutlineSource'] == initial['aiSource']
    assert all(key not in image_draft for key in ('printBase64','mockupBase64','productionMeta','orderId'))

    changed = page.evaluate("""async () => {
      await ensureEditorFont('jf-openhuninn','ç²‰åœ“æ¢å¾©');
      const sticker=new fabric.Text('â˜…',{left:42,top:51,role:'sticker',fontSize:28,fill:'#ff5d91',clipPath:baseClip});
      const text=new fabric.Textbox('ç²‰åœ“æ¢å¾©',{left:88,top:122,width:130,role:'text',fontFamily:'jf-openhuninn',fontSize:30,opacity:.84,clipPath:baseClip});
      styleEditableObject(sticker);styleEditableObject(text);canvas.add(sticker);canvas.add(text);
      const photo=canvas.getObjects().find(object=>object.role==='photo');canvas.setActiveObject(photo);nudgeActive(1,-1);
      setCanvasBackground('#ffeeaa');changeBackgroundOpacity(67);recordHistory();
      return {photo:{left:photo.left,top:photo.top,scaleX:photo.scaleX,scaleY:photo.scaleY,angle:photo.angle,opacity:photo.opacity}};
    }""")
    page.evaluate("""() => {
      const photo=canvas.getObjects().find(object=>object.role==='photo');canvas.setActiveObject(photo);canvas.requestRenderAll();
      document.getElementById('bf-os-width').value='9';document.getElementById('bf-os-custom-color').value='#ffffff';
      document.querySelector('#sheet-outline-v2 [data-style="custom"]').click();
    }""")
    outlined = poll(page, """() => {
      const photo=canvas.getActiveObject();
      if(!photo||photo.aiOutlineStyle!=='custom'||photo.getSrc()===photo.aiOutlineSource)return false;
      photo.aiRemovalMode='universal-v3';recordHistory();
      return {source:photo.aiOutlineSource,current:photo.getSrc(),width:photo.width,height:photo.height,strength:photo.aiOutlineStrength,style:photo.aiOutlineStyle,outlineWidth:photo.aiOutlineWidth,color:photo.aiOutlineColor};
    }""", timeout=10000)
    page.evaluate("updatedAt => { window.__draftBeforeUpdate = updatedAt; }", image_draft['updatedAt'])
    full_draft = poll(page, "() => idbGet(BenfuwanDesignDraft.key).then(draft => draft?.updatedAt && draft.updatedAt !== window.__draftBeforeUpdate ? draft : false)", timeout=10000)
    assert full_draft['updatedAt'] != image_draft['updatedAt']
    assert full_draft['backgroundColor'] == '#ffeeaa' and abs(full_draft['backgroundOpacity'] - .67) < .001
    assert {obj.get('role') for obj in full_draft['canvasJson']['objects']} == {'photo','sticker','text'}
    saved_ai = next(obj for obj in full_draft['canvasJson']['objects'] if obj.get('role') == 'photo')
    assert saved_ai['aiRemovalMode'] == 'universal-v3'
    assert saved_ai['aiOutlineSource'] == initial['aiSource'] == outlined['source']
    assert saved_ai['aiOutlineStrength'] == outlined['strength'] == 'custom'
    assert saved_ai['aiOutlineStyle'] == outlined['style'] == 'custom'
    assert saved_ai['aiOutlineWidth'] == outlined['outlineWidth'] == 9
    assert saved_ai['aiOutlineColor'] == outlined['color'] == '#ffffff'
    print('FRONT_DESIGN_DRAFT_AUTOSAVE_ACTIONS_OK', full_draft['updatedAt'])

    page.reload(wait_until='domcontentloaded')
    poll(page, "() => window.BenfuwanDesignDraft?.state().prompt==='ready' && document.getElementById('design-draft-prompt')?.classList.contains('show') && document.getElementById('home-design-card')?.dataset.draftState==='ready'")
    assert page.locator('#design-draft-title').inner_text() == 'ç™¼ç¾ä¸Šæ¬¡æœªå®Œæˆçš„è¨­è¨ˆ'
    assert page.locator('#home-design-title').inner_text() == 'ç¹¼çºŒä¸Šæ¬¡è¨­è¨ˆ'
    page.locator('#home-design-card').click()
    poll(page, "() => document.getElementById('page-editor')?.classList.contains('active') && canvas?.getObjects().length===3 && !BenfuwanDesignDraft.state().suspended")
    restored = page.evaluate("""() => {
      const photo=canvas.getObjects().find(object=>object.role==='photo');
      const text=canvas.getObjects().find(object=>object.role==='text');
      return {
        modelId:ctx.modelId,styleId:ctx.styleId,colorName:ctx.colorName||'',width:canvas.width,height:canvas.height,count:canvas.getObjects().length,
        backgroundColor:ctx.backgroundColor,backgroundOpacity:ctx.backgroundOpacity,
        photo:{left:photo.left,top:photo.top,scaleX:photo.scaleX,scaleY:photo.scaleY,angle:photo.angle,opacity:photo.opacity},
        ai:{removalMode:photo.aiRemovalMode,source:photo.aiOutlineSource,strength:photo.aiOutlineStrength,style:photo.aiOutlineStyle,width:photo.aiOutlineWidth,color:photo.aiOutlineColor,current:photo.getSrc(),imageWidth:photo.width,imageHeight:photo.height},
        font:text.fontFamily,fontLoaded:document.fonts.check('16px "jf-openhuninn"','ç²‰åœ“æ¢å¾©'),
        printBase64:ctx.printBase64,mockupBase64:ctx.mockupBase64,productionMeta:ctx.productionMeta,
        historyLength:historyStack.length,historyIndex
      };
    }""")
    assert restored['modelId'] == initial['modelId'] and restored['styleId'] == initial['styleId']
    assert restored['colorName'] == initial['colorName']
    assert restored['width'] == initial['width'] and restored['height'] == initial['height'] and restored['count'] == 3
    assert restored['backgroundColor'] == '#ffeeaa' and abs(restored['backgroundOpacity'] - .67) < .001
    for key, value in changed['photo'].items():
        assert abs(restored['photo'][key] - value) < .001, (key, restored, changed)
    assert restored['font'] == 'jf-openhuninn' and restored['fontLoaded']
    assert restored['ai']['removalMode'] == 'universal-v3'
    assert restored['ai']['source'] == initial['aiSource'] and restored['ai']['current'] == outlined['current']
    assert restored['ai']['strength'] == 'custom' and restored['ai']['style'] == 'custom'
    assert restored['ai']['width'] == 9 and restored['ai']['color'] == '#ffffff'
    assert restored['printBase64'] is None and restored['mockupBase64'] is None and restored['productionMeta'] is None
    assert restored['historyLength'] == 1 and restored['historyIndex'] == 0
    print('FRONT_DESIGN_DRAFT_RELOAD_RECOVERY_OK', restored)

    page.evaluate("""() => {
      const photo=canvas.getObjects().find(object=>object.role==='photo');canvas.setActiveObject(photo);canvas.requestRenderAll();
      window.__draftOutlineBeforeRecolor=photo.getSrc();
      const color=document.getElementById('bf-os-custom-color');color.value='#00ff00';color.dispatchEvent(new Event('change',{bubbles:true}));
    }""")
    recolored = poll(page, """() => {
      const photo=canvas.getActiveObject();
      return photo?.aiOutlineColor==='#00ff00'&&photo.getSrc()!==window.__draftOutlineBeforeRecolor
        ? {source:photo.aiOutlineSource,width:photo.width,height:photo.height,color:photo.aiOutlineColor,style:photo.aiOutlineStyle}
        : false;
    }""", timeout=10000)
    assert recolored == {'source': initial['aiSource'], 'width': outlined['width'], 'height': outlined['height'], 'color': '#00ff00', 'style': 'custom'}, recolored
    page.evaluate("() => document.querySelector('#sheet-outline-v2 [data-style=\"none\"]').click()")
    outline_removed = poll(page, """() => {
      const photo=canvas.getActiveObject();
      return photo?.aiOutlineStyle==='none'&&photo.getSrc()===photo.aiOutlineSource
        ? {source:photo.aiOutlineSource,current:photo.getSrc(),width:photo.width,height:photo.height,strength:photo.aiOutlineStrength}
        : false;
    }""", timeout=10000)
    assert outline_removed['source'] == outline_removed['current'] == initial['aiSource']
    assert outline_removed['width'] == initial['aiWidth'] and outline_removed['height'] == initial['aiHeight']
    assert outline_removed['strength'] == '0'
    print('FRONT_DESIGN_DRAFT_AI_OUTLINE_EDITABILITY_OK', {'recolored': recolored, 'removed': outline_removed})

    cart_state = page.evaluate("""async () => {
      const tiny=document.createElement('canvas');tiny.width=2;tiny.height=2;
      ctx.printBase64=tiny.toDataURL('image/png');ctx.mockupBase64=ctx.printBase64;
      ctx.productionMeta={ppm:BenfuwanProductionHQ.PPM,dpi:720,width:2,height:2};
      await BenfuwanProductionHQ.begin(ctx,async()=>ctx.productionMeta);
      await confirmDesignToCart();
      return {draft:!!(await idbGet(BenfuwanDesignDraft.key)),cart:!!(await idbGet('cart'))};
    }""")
    assert cart_state == {'draft':True,'cart':True}, cart_state
    page.evaluate("""async () => {
      document.getElementById('form-surname').value='è‰ç¨¿';
      await submitOrder();
    }""")
    poll(page, "() => document.getElementById('page-success')?.classList.contains('active')")
    completed = page.evaluate("""async () => {
      await BenfuwanDesignDraft.saveNow();
      return {draft:await idbGet(BenfuwanDesignDraft.key),autosave:BenfuwanDesignDraft.state().autosaveEnabled};
    }""")
    assert completed == {'draft':None,'autosave':False}, completed
    print('FRONT_DESIGN_DRAFT_CART_KEEP_ORDER_SUCCESS_CLEAR_OK')

    incompatible = page.evaluate("""async draft => {
      draft.logicalCanvasWidth+=1;await idbSet(BenfuwanDesignDraft.key,draft);return draft;
    }""", full_draft)
    page.reload(wait_until='domcontentloaded')
    poll(page, "() => window.BenfuwanDesignDraft?.state().prompt==='invalid'")
    assert page.locator('#design-draft-message').inner_text() == 'æ­¤æ‰‹æ©Ÿæ®¼è¨­å®šå·²æ›´æ–°ï¼ŒèˆŠè¨­è¨ˆç„¡æ³•å®‰å…¨æ¢å¾©ï¼Œè«‹é‡æ–°è£½ä½œã€‚'
    assert not page.locator('#design-draft-prompt .continue').is_visible()
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#design-draft-prompt .discard').click()
    poll(page, "() => document.getElementById('page-model')?.classList.contains('active')")
    assert page.evaluate("() => idbGet(BenfuwanDesignDraft.key)") is None
    print('FRONT_DESIGN_DRAFT_GEOMETRY_FAIL_CLOSED_OK', incompatible['logicalCanvasWidth'])

    page.evaluate("""async () => {
      await idbSet(BenfuwanDesignDraft.key,{version:1,updatedAt:new Date().toISOString(),modelId:'broken',styleId:'broken',logicalCanvasWidth:240,logicalCanvasHeight:480,canvasJson:'{broken'});
    }""")
    page.reload(wait_until='domcontentloaded')
    poll(page, "() => window.BenfuwanDesignDraft?.state().prompt==='invalid'")
    assert page.locator('#design-draft-message').inner_text() == 'ä¸Šæ¬¡çš„è¨­è¨ˆè‰ç¨¿å·²ç„¡æ³•å®‰å…¨æ¢å¾©ï¼Œè«‹åˆªé™¤èˆŠè‰ç¨¿ä¸¦é‡æ–°é–‹å§‹ã€‚'
    page.once('dialog', lambda dialog: dialog.accept())
    page.locator('#design-draft-prompt .discard').click()
    poll(page, "() => document.getElementById('page-model')?.classList.contains('active')")
    assert page.evaluate("() => idbGet(BenfuwanDesignDraft.key)") is None
    print('FRONT_DESIGN_DRAFT_CORRUPTION_RECOVERY_OK')

    guarded = page.evaluate("""async ({modelId,styleId,width,height}) => {
      const draft={version:1,updatedAt:new Date().toISOString(),modelId,styleId,backgroundColor:'transparent',backgroundOpacity:0,logicalCanvasWidth:width,logicalCanvasHeight:height,canvasJson:{version:'5.3.0',objects:[]}};
      await idbSet(BenfuwanDesignDraft.key,draft);await BenfuwanDesignDraft.refreshPrompt();showPage('page-home');
      const realConfirm=window.confirm;window.confirm=()=>false;await startNewDesign();const kept=!!(await idbGet(BenfuwanDesignDraft.key))&&document.getElementById('page-home').classList.contains('active');
      window.confirm=()=>true;await startNewDesign();const discarded=(await idbGet(BenfuwanDesignDraft.key))===null&&document.getElementById('page-model').classList.contains('active');window.confirm=realConfirm;
      return {kept,discarded};
    }""", initial)
    assert guarded == {'kept':True,'discarded':True}, guarded
    print('FRONT_DESIGN_DRAFT_NEW_DESIGN_GUARD_OK')
    page.close()


def home_draft_catalog_race_test(browser, base):
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    draft_preview = fixture_data_url('iphone13-preview.png')
    draft_print = fixture_data_url('iphone13-print.png')

    def configure_catalog(route):
        response = route.fetch()
        payload = response.json()
        catalog = payload.get('data', payload)
        model = next(row for row in catalog.get('models', []) if row and row.get('status') is not False)
        style = next(row for row in catalog.get('styles', []) if row and row.get('status') is not False)
        model.setdefault('case_profiles', {})[style['id']] = {
            'preview_mask_img': draft_preview,
            'print_line_img': draft_print,
            'print_x': 0,
            'print_y': 0,
            'print_w': 80,
            'print_h': 160,
            'print_angle': 0,
        }
        route.fulfill(response=response, body=json.dumps(payload, ensure_ascii=False))

    page.route('**/api/shop_data', configure_catalog)
    page.goto(base + '/', wait_until='domcontentloaded')
    poll(page, "() => window.BenfuwanFrontHomeV1?.isCatalogReady() && shopData.models?.length && shopData.styles?.length")
    seeded = page.evaluate("""async () => {
      const model=shopData.models.find(row=>row?.status!==false),style=shopData.styles.find(row=>row?.status!==false),profile=BenfuwanModelProfile.profileFor(model,style.id);
      const draft={version:1,updatedAt:new Date().toISOString(),modelId:model.id,styleId:style.id,colorName:'',backgroundColor:'transparent',backgroundOpacity:1,logicalCanvasWidth:Math.max(180,Math.round(profile.printW*3)),logicalCanvasHeight:Math.max(360,Math.round(profile.printH*3)),canvasJson:{version:'5.3.0',objects:[]}};
      await idbSet(BenfuwanDesignDraft.key,draft);
      return {modelId:model.id,styleId:style.id,width:draft.logicalCanvasWidth,height:draft.logicalCanvasHeight};
    }""")
    page.add_init_script("""(() => {
      const nativeFetch=window.fetch.bind(window);
      window.fetch=(input,init)=>{
        const url=String(typeof input==='string'?input:(input&&input.url)||'');
        if(!url.includes('/api/shop_data'))return nativeFetch(input,init);
        window.__catalogFetchPending=true;
        return new Promise((resolve,reject)=>{
          window.__releaseShopData=()=>{window.__catalogFetchPending=false;nativeFetch(input,init).then(resolve,reject)};
        });
      };
    })()""")
    page.reload(wait_until='domcontentloaded')
    loading = poll(page, """() => {
      const card=document.getElementById('home-design-card');
      if(!window.__catalogFetchPending||card?.dataset.draftState!=='loading')return false;
      return {title:document.getElementById('home-design-title').textContent,subtitle:document.getElementById('home-design-subtitle').textContent,promptInvalid:document.getElementById('design-draft-prompt')?.classList.contains('invalid')||false,promptVisible:document.getElementById('design-draft-prompt')?.classList.contains('show')||false};
    }""")
    assert loading == {'title':'æˆ‘çš„è¨­è¨ˆ','subtitle':'æ­£åœ¨æª¢æŸ¥ä¸Šæ¬¡è¨­è¨ˆâ€¦','promptInvalid':False,'promptVisible':False}, loading
    page.locator('#home-design-card').click()
    page.wait_for_timeout(100)
    assert not page.locator('#design-draft-prompt.invalid').count()
    page.evaluate("() => window.__releaseShopData()")
    poll(page, "() => window.BenfuwanFrontHomeV1?.isCatalogReady() && document.getElementById('home-design-card')?.dataset.draftState==='ready'")
    assert page.locator('#home-design-title').inner_text() == 'ç¹¼çºŒä¸Šæ¬¡è¨­è¨ˆ'
    page.locator('#home-design-card').click()
    poll(page, "() => document.getElementById('page-editor')?.classList.contains('active') && canvas && !BenfuwanDesignDraft.state().suspended")
    restored = page.evaluate("() => ({modelId:ctx.modelId,styleId:ctx.styleId,width:canvas.width,height:canvas.height,objects:canvas.getObjects().length})")
    assert restored == {'modelId':seeded['modelId'],'styleId':seeded['styleId'],'width':seeded['width'],'height':seeded['height'],'objects':0}, restored
    print('FRONT_HOME_DRAFT_CATALOG_RACE_OK', loading, restored)
    page.close()


def checkout_test(browser, base):
    page = browser.new_page()
    sent = []
    def intercept(route):
        sent.append(route.request.post_data_json)
        if len(sent) == 1:
            # Server commits, browser receives a simulated transport failure.
            result = route.fetch()
        ÷_y¶‰Ëkºwµç[Z[œÊ	ÜÚİÉÊHŠB‚ˆYÙK›ØØ]ÜŠ	ÈØœ˜[™XYZ[‹]šY]È]X˜\ˆ˜‰ÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈØ™‹Xœ˜[™[˜[YIÊK™š[
	ùníº`l¹i,y¥eùdàyâc	ÊBˆYÙK›ØØ]ÜŠ	ÈØ™‹Xœ˜[™\Ø]™IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆÚ[™İË—×İÛÜšÜÜXÙPœ˜[™[™[™Ë›[™İOOLHŠBˆYÙK™]˜[X]JˆˆŠ
HOˆÚ[™İË—×İÛÜšÜÜXÙPœ˜[™[™[™ËœÚY

J™]È™\ÜÛœÙJ”ÓÓ‹œİš[™ÚYJÜİ]\Î‰Ù\œ›Ü‰Ë\ÙÎ‰ùníº`l¹a,¹kf9i,y¥eÉßJKÜİ]\ÎLËXY\œÎÉĞÛÛ[U\IÎ‰Ø\XØ][Û‹ÚœÛÛ‰ß_JJHˆˆŠBˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™Y\œ›Ü‰ÊK^ÛÛ[š[˜ÛY\Ê	ùníº`l¹a,¹kf9i,y¥eÉÊHŠBˆ˜Z[YØœ˜[™HYÙK™]˜[X]JˆˆŠ
HOˆ
ÂˆÜ[™Øİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊKˆ˜[YN™Øİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™[˜[YIÊK˜[YKˆØ]™Q\ØX›Y™Øİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™\Ø]™IÊK™\ØX›YˆÛÜÙQ\ØX›Y–Ë‹‹™Øİ[Y[œ]Y\TÙ[XİÜ[
	ÈØ™‹Xœ˜[™[[Ù[Ù]KXœ˜[™XÛÜÙWIÊWKœÛÛYJ]ÛO˜]Û‹™\ØX›Y
Kˆ\œ›Ü™Øİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™Y\œ›Ü‰ÊK^ÛÛ[ˆJHˆˆŠBˆ\ÜÙ\˜Z[YØœ˜[™ÉÛÜ[‰×H[™˜Z[YØœ˜[™Éİ˜[YI×HOH	ùníº`l¹i,y¥eùdàyâc	Ë˜Z[YØœ˜[™ˆ\ÜÙ\›İ˜Z[YØœ˜[™ÉÜØ]™Q\ØX›Y	×H[™›İ˜Z[YØœ˜[™ÉØÛÜÙQ\ØX›Y	×H[™	ùníº`l¹a,¹kf9i,y¥eÉÈ[ˆ˜Z[YØœ˜[™ÉÙ\œ›Ü‰×K˜Z[YØœ˜[™ˆYÙK›ØØ]ÜŠ	ÈØ™‹Xœ˜[™[[Ù[Ù]KXœ˜[™XÛÜÙWIÊK›\İ˜ÛXÚÊ
BˆYÙK™]˜[X]JˆˆŠ
HOˆİÚ[™İË™™]Ú]Ú[™İË—×İÛÜšÜÜXÙT™X[™]ÚÙ[]HÚ[™İË—×İÛÜšÜÜXÙT™X[™]ÚÙ[]HÚ[™İË—×İÛÜšÜÜXÙPœ˜[™[™[™ßHˆˆŠB‚ˆÛÜšÜÜXÙWİÜš]\ÈH×BˆYˆÛÜšÜÜXÙWÜØ]™J›İ]JN‚ˆÛÜšÜÜXÙWİÜš]\Ë˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹™\œÚ[ÛˆˆÛÜšÜÜXÙK]™\œÚ[ÛˆŸIÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜØ]™WÜÚÜÙ]IËÛÜšÜÜXÙWÜØ]™JBˆYÙK›ØØ]ÜŠ	ÈØœ˜[™XYZ[‹]šY]È]X˜\ˆ˜‰ÊK˜ÛXÚÊ
Bˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈØ™‹Xœ˜[™[[Ù[œÚİÉÊK˜Ûİ[

HOHBˆYÙK›ØØ]ÜŠ	ÈØ™‹Xœ˜[™[˜[YIÊK™š[
	Ğ\IÊBˆYÙK›ØØ]ÜŠ	ÈØ™‹Xœ˜[™\Ø]™IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™Y\œ›Ü‰ÊK^ÛÛ[š[˜ÛY\Ê	ùdàyâc9mì¹kf9g*	ÊHŠBˆ\ÜÙ\ÛÜšÜÜXÙWİÜš]\ÈOH×H[™YÙK™]˜[X]JŠ
HOˆÚ[™İË—×İÛÜšÜÜXÙT›Û\Ø[ÈŠHOHˆYÙK›ØØ]ÜŠ	ÈØ™‹Xœ˜[™[˜[YIÊK™š[
	ÑÛÛÙÛIÊBˆYÙK›ØØ]ÜŠ	ÈØ™‹Xœ˜[™\Ø]™IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆÚÜ]K˜œ˜[™Ëš[˜ÛY\Ê	ÑÛÛÙÛIÊH	‰ˆYØİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊHŠBˆYÙK›ØØ]ÜŠ	ÈØœ˜[™ËX›ÙHÙ]KYY]Xœ˜[™H\H—IÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈØ™‹Xœ˜[™[˜[YIÊK™š[
	Ğ\H[˜Ë‰ÊBˆYÙK›ØØ]ÜŠ	ÈØ™‹Xœ˜[™\Ø]™IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆÚÜ]K˜œ˜[™Ëš[˜ÛY\Ê	Ğ\H[˜Ë‰ÊH	‰ˆÚÜ]K›[Ù[Ë™š[™
OšYOOIÛ[Ù[XIÊK˜œ˜[™OOIĞ\H[˜Ë‰ÈŠBˆ\ÜÙ\[ŠÛÜšÜÜXÙWİÜš]\ÊHOHˆ[™YÙK™]˜[X]JŠ
HOˆÚ[™İË—×İÛÜšÜÜXÙT›Û\Ø[ÈŠHOHˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈØœ˜[™ËX›ÙH–Ù]KXœ˜[™H\H[˜Ëˆ—H˜™‹XÛİ[XÚ\	ÊKš[›™\—İ^

HOH	ÌH9`"ùg¢ú&gÉÂˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜØ]™WÜÚÜÙ]IÊB‚ˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[]X‹X‰ÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈØ™‹[[Ù[\ÙX\˜Ú	ÊK™š[
	ÌMÈ›ÉÊBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÛ[Ù[ËX›ÙH–Ù]K[[Ù[ZYIÊK˜Ûİ[

HOHBˆYÙK›ØØ]ÜŠ	ÈØ™‹[[Ù[\ÙX\˜Ú	ÊK™š[
	ÉÊBˆYÙK›ØØ]ÜŠ	ÈØ™‹[[Ù[Xœ˜[™Yš[\‰ÊKœÙ[XİÛÜ[ÛŠ	ÔØ[\İ[™ÉÊBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÛ[Ù[ËX›ÙH–Ù]K[[Ù[ZYH›[Ù[Xˆ—IÊK˜Ûİ[

HOHBˆYÙK›ØØ]ÜŠ	ÈØ™‹[[Ù[Xœ˜[™Yš[\‰ÊKœÙ[XİÛÜ[ÛŠ	ÉÊBˆYÙK›ØØ]ÜŠ	ÈØ™‹[[Ù[\İ]\ËYš[\‰ÊKœÙ[XİÛÜ[ÛŠ	ØXİ]™IÊBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÛ[Ù[ËX›ÙH–Ù]K[[Ù[ZYIÊK˜Ûİ[

HOHBˆYÙK›ØØ]ÜŠ	ÈØ™‹[[Ù[\İ]\ËYš[\‰ÊKœÙ[XİÛÜ[ÛŠ	Ø[	ÊB‚ˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[ËX›ÙHÙ]K[[Ù[ZYH›[Ù[XH—VÙ]K[[Ù[\İ[OHœİ[K[Z\œ›Üˆ—IÊK˜ÛXÚÊ
Bˆ\ÜÙ\YÙK™]˜[X]JŠ
HOˆ™[™]Ø[“[Ù[›Ùš[\ĞYZ[‹™Ù]Xİ]™Tİ[RY

HŠHOH	Üİ[K[Z\œ›Ü‰Âˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÛ[Ù[\›Ùš[K^	ÊKš[œ]İ˜[YJ
HOH	ÌŒIÂˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[\›Ùš[K^	ÊK™š[
	ÎNIÊBˆ\WÙİX\™HYÙK™]˜[X]JˆˆŠ
HOˆİÚ[™İË—×İÛÜšÜÜXÙPÛÛ™š\›O]Ú[™İË˜ÛÛ™š\›NİÚ[™İË—×İÛÜšÜÜXÙPÛÛ™š\›PØ[ÏLİÚ[™İË˜ÛÛ™š\›OJ
OOİÚ[™İË—×İÛÜšÜÜXÙPÛÛ™š\›PØ[ÊÊÎÜ™]\›ˆ˜[Ù_NÙØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K\›Ùš[K\İ[OHœİ[WÌMÎLÎÎN—IÊK˜ÛXÚÊ
NÜ™]\›ˆØØ[ÎÚ[™İË—×İÛÜšÜÜXÙPÛÛ™š\›PØ[Ëİ[N™[™]Ø[“[Ù[›Ùš[\ĞYZ[‹™Ù]Xİ]™Tİ[RY

K\N™[™]Ø[“[Ù[›Ùš[\ĞYZ[‹š\Ñ\J
__HˆˆŠBˆ\ÜÙ\\WÙİX\™OHÉØØ[ÉÎŒK	Üİ[IÎ‰Üİ[K[Z\œ›Ü‰Ë	Ù\IÎ•Y_K\WÙİX\™ˆYÙK™]˜[X]JŠ
HOˆİÚ[™İË˜ÛÛ™š\›OJ
OOYNÙØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K\›Ùš[K\İ[OWœİ[WÌMÎLÎÎN—IÊK˜ÛXÚÊ
_HŠBˆ\ÜÙ\YÙK™]˜[X]JŠ
HOˆ™[™]Ø[“[Ù[›Ùš[\ĞYZ[‹™Ù]Xİ]™Tİ[RY

HŠHOH	Üİ[WÌMÎLÎÎN	Âˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÛ[Ù[\›Ùš[K^	ÊKš[œ]İ˜[YJ
HOH	ÌLIÂˆYÙK™]˜[X]JŠ
HOˆİÚ[™İË˜ÛÛ™š\›O]Ú[™İË—×İÛÜšÜÜXÙPÛÛ™š\›NÙ[]HÚ[™İË—×İÛÜšÜÜXÙPÛÛ™š\›NÙ[]HÚ[™İË—×İÛÜšÜÜXÙPÛÛ™š\›PØ[ßHŠB‚ˆ›Ùš[WİÜš]\ÈH×BˆYˆÛÜšÜÜXÙWÜ›Ùš[WÜØ]™J›İ]JN‚ˆ›Ùš[WİÜš]\Ë˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹™\œÚ[ÛˆˆÛÜšÜÜXÙK\›Ùš[K]™\œÚ[ÛˆŸIÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹Üš[Û[Ù[\›Ùš[\ÉËÛÜšÜÜXÙWÜ›Ùš[WÜØ]™JBˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[\›Ùš[K^	ÊK™š[
	ÌLËIÊBˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[\Ø]™IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆYØİ[Y[™Ù][[Y[RY
	Û[Ù[[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊHŠBˆ\ÜÙ\[Š›Ùš[WİÜš]\ÊHOHBˆØ]™YÛ[Ù[H™^
›İÈ›Üˆ›İÈ[ˆ›Ùš[WİÜš]\ÖÌVÉÜÚÜÙ]I×VÉÛ[Ù[É×HYˆ›İÖÉÚY	×HOH	Û[Ù[XIÊBˆ\ÜÙ\›Ùš[WİÜš]\ÖÌVÉÜİ[WÚY	×HOH	Üİ[WÌMÎLÎÎN	Âˆ\ÜÙ\Ø]™YÛ[Ù[ÉØØ\ÙWÜ›Ùš[\É×VÉÜİ[WÌMÎLÎÎN	×VÉÜš[Ş	×HOHLËBˆ\ÜÙ\Ø]™YÛ[Ù[ÉØØ\ÙWÜ›Ùš[\É×VÉÜİ[K[Z\œ›Ü‰×HOHÛÜšÜÜXÙWÙš^\™VÉÛ[Ù[É×VÌVÉØØ\ÙWÜ›Ùš[\É×VÉÜİ[K[Z\œ›Ü‰×BˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹Üš[Û[Ù[\›Ùš[\ÉÊB‚ˆYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏHœİ[\È—IÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈØ™‹\İ[K\ÙX\˜Ú	ÊK™š[
	úcèzgh‰ÊBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜİ[\ËX›ÙH–Ù]K\İ[KZYHœİ[K[Z\œ›Üˆ—IÊK˜Ûİ[

HOHBˆYÙK›ØØ]ÜŠ	ÈØ™‹\İ[K\ÙX\˜Ú	ÊK™š[
	ÉÊBˆYÙK›ØØ]ÜŠ	ÈØ™‹\İ[K\İ]\ËYš[\‰ÊKœÙ[XİÛÜ[ÛŠ	Ú[˜Xİ]™IÊBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜİ[\ËX›ÙH–Ù]K\İ[KZYHœİ[K[Ù™ˆ—IÊK˜Ûİ[

HOHBˆYÙK›ØØ]ÜŠ	ÈØ™‹\İ[K\İ]\ËYš[\‰ÊKœÙ[XİÛÜ[ÛŠ	Ø[	ÊBˆYÙK›ØØ]ÜŠ	ÈÜİ[\ËX›ÙHÙ]KYY]\İ[OHœİ[WÌMÎLÎÎN—IÊK˜ÛXÚÊ
Bˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜİ[KXÛÛÜœÉÊKš[œ]İ˜[YJ
HOH	ùæoz"l‹:näz"l‰Âˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈØ™‹[[Ù[XÛÛÜ‹[\İÙ]K[[Ù[ZYH›[Ù[XH—IÊKš[œ]İ˜[YJ
HOH	ú`#ù¦#‰ÂˆYÙK›ØØ]ÜŠ	ÈÜİ[K[[Ù[›Z]Û‰ÊK˜ÛXÚÊ
B‚ˆ›ÜˆÚYZYÚ[ˆ

ÎL
K
ÍL
K
LNL
JN‚ˆYÙKœÙ]İšY]ÜÜÜÚ^™JÉİÚY	ÎÚY	ÚZYÚ	ÎšZYÚJBˆYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏH›[Ù[È—IÊK˜ÛXÚÊ
HYˆÚYHŒ[ÙHYÙK™]˜[X]JŠ
HOˆÚİÕšY]Ê	Û[Ù[ÉËØİ[Y[œ]Y\TÙ[XİÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏW›[Ù[×—IÊJHŠBˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[]X‹X‰ÊK˜ÛXÚÊ
Bˆ^[İ]HYÙK™]˜[X]JˆˆŠ
HOˆ
ÜØÜ›Û™Øİ[Y[™Øİ[Y[[[Y[œØÜ›ÛÚYšY]ÜÜ™Øİ[Y[™Øİ[Y[[[Y[˜ÛY[ÚY›İÎ™Ù]ÛÛ\]Yİ[JØİ[Y[œ]Y\TÙ[XİÜŠ	ÈÛ[Ù[ËX›ÙH–Ù]K[[Ù[ZYIÊJK™\Ü^_JHˆˆŠBˆ\ÜÙ\^[İ]ÉÜØÜ›Û	×HH^[İ]ÉİšY]ÜÜ	×H
È‹
ÚY^[İ]
Bˆ\ÜÙ\
^[İ]ÉÜ›İÉ×HOH	ÙÜšY	ÊHOH
ÚYŒ
K
ÚY^[İ]
BˆYÙKœÙ]İšY]ÜÜÜÚ^™JÉİÚY	ÎŒLN	ÚZYÚ	ÎLJBˆYÙK™]˜[X]JœÛ˜\ÚİOˆÜÚÜ]O\İXİ\™YÛÛ™JÛ˜\Úİ™]JNÜÚÜ™\œÚ[Û\Û˜\Úİ™\œÚ[ÛİÚ[™İËœ›Û\]Ú[™İË—×İÛÜšÜÜXÙT›Û\Ù[]HÚ[™İË—×İÛÜšÜÜXÙT›Û\Ù[]HÚ[™İË—×İÛÜšÜÜXÙT›Û\Ø[ÎÜ™[™\œ˜[™Ê
NÜ™[™\“[Ù[Ê
NÜ™[™\”İ[\Ê
_H‹ÛÜšÜÜXÙWÛÜšYÚ[˜[
Bˆš[
	ĞQRS—Ô“ÑPÕÔÑUS‘Ô×ÕÓÔ’ÔÔPÑWÕŒWÓÒÉÊB‚ˆ[Ù[ØÛÛÜ—ÜÜ˜ÈHYÙK›ØØ]ÜŠ	ÜØÜš\ÜÜ˜ÊH˜YZ[‹[[Ù[XÛÛÜœËšœÈ—IÊK™Ù]Ø]šX]J	ÜÜ˜ÉÊBˆ\ÜÙ\[Ù[ØÛÛÜ—ÜÜ˜È[™	İLŒŒL˜]Y]IÈ[ˆ[Ù[ØÛÛÜ—ÜÜ˜Ë[Ù[ØÛÛÜ—ÜÜ˜Âˆ[Ù[Ü›Ùš[WÜÜ˜ÈHYÙK›ØØ]ÜŠ	ÜØÜš\ÜÜ˜ÊH˜YZ[‹[[Ù[\›Ùš[\ËšœÈ—IÊK™Ù]Ø]šX]J	ÜÜ˜ÉÊBˆ\ÜÙ\[Ù[Ü›Ùš[WÜÜ˜È[™	İLŒŒL\İ[LIÈ[ˆ[Ù[Ü›Ùš[WÜÜ˜Ë[Ù[Ü›Ùš[WÜÜ˜Âˆ›ÙXİİÛÜšÜÜXÙWÜÜ˜ÈHYÙK›ØØ]ÜŠ	ÜØÜš\ÜÜ˜ÊH˜YZ[‹\›ÙXİ]ÛÜšÜÜXÙK]ŒKšœÈ—IÊK™Ù]Ø]šX]J	ÜÜ˜ÉÊBˆ\ÜÙ\›ÙXİİÛÜšÜÜXÙWÜÜ˜È[™	İLŒŒLX‰È[ˆ›ÙXİİÛÜšÜÜXÙWÜÜ˜Ë›ÙXİİÛÜšÜÜXÙWÜÜ˜Âˆ\ÜÙ]ØØ]YÛÜWÜÜ˜ÈHYÙK›ØØ]ÜŠ	ÜØÜš\ÜÜ˜ÊH˜YZ[‹X\ÜÙ]XØ]YÛÜšY\ËšœÈ—IÊK™Ù]Ø]šX]J	ÜÜ˜ÉÊBˆ\ÜÙ\\ÜÙ]ØØ]YÛÜWÜÜ˜È[™	İLŒŒL˜IÈ[ˆ\ÜÙ]ØØ]YÛÜWÜÜ˜Ë\ÜÙ]ØØ]YÛÜWÜÜ˜Âˆ[\]WÛØY\—ÜÜ˜ÈHYÙK›ØØ]ÜŠ	ÜØÜš\ÜÜ˜ÊH˜YZ[‹][\]K[ØY\‹šœÈ—IÊK™Ù]Ø]šX]J	ÜÜ˜ÉÊBˆ\ÜÙ\[\]WÛØY\—ÜÜ˜È[™	İLŒŒL˜IÈ[ˆ[\]WÛØY\—ÜÜ˜Ë[\]WÛØY\—ÜÜ˜ÂˆXœ˜\WİÛÜšÜÜXÙWÜÜ˜ÈHYÙK›ØØ]ÜŠ	ÜØÜš\ÜÜ˜ÊH˜YZ[‹[Xœ˜\K]ÛÜšÜÜXÙK]ŒKšœÈ—IÊK™Ù]Ø]šX]J	ÜÜ˜ÉÊBˆ\ÜÙ\Xœ˜\WİÛÜšÜÜXÙWÜÜ˜È[™	İLŒŒL˜IÈ[ˆXœ˜\WİÛÜšÜÜXÙWÜÜ˜ËXœ˜\WİÛÜšÜÜXÙWÜÜ˜ÂˆÛÛ[Y\˜ÙWÜÜ˜ÈHYÙK›ØØ]ÜŠ	ÜØÜš\ÜÜ˜ÊH˜YZ[‹XÛÛ[Y\˜ÙK]ŒKšœÈ—IÊK™Ù]Ø]šX]J	ÜÜ˜ÉÊBˆ\ÜÙ\ÛÛ[Y\˜ÙWÜÜ˜È[™	İLŒŒLÛ][˜ÚIÈ[ˆÛÛ[Y\˜ÙWÜÜ˜ËÛÛ[Y\˜ÙWÜÜ˜ÂˆYˆ^Ù\œ›ÜŠ›İ]JN‚ˆİ]\ÈH[
›İ]Kœ™\]Y\İ\›œœÜ]
	ËIËJVËLWJBˆ›İ]K™[š[
İ]\Ï\İ]\ËÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\Èˆ™\œ›ÜˆŸIÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹İ^\›Ø™KJ‰Ë^Ù\œ›ÜŠBˆ\WÛY\ÜØYÙ\ÈHYÙK™]˜[X]Jˆˆ˜\Ş[˜È

HOˆÂˆÛÛœİİ]^ßNÂˆ›ÜŠÛÛœİİ]\ÈÙˆÍKKL×J^Âˆ^Ø]ØZ]\RœÛÛŠ	ËØ\KØYZ[‹İ^\›Ø™KIÊÜİ]\Ê_XØ]Ú
J^Ûİ]Üİ]\×OYK›Y\ÜØYÙ_BˆBˆ™]\›ˆİ]ÂˆHˆˆŠBˆ\ÜÙ\\WÛY\ÜØYÙ\ÈOHÂˆ	ÍIÎ‰ùænùaiymìº`c¹§'ûï#:*âúaãy¥¬9ænùaiyo£9a£z*i‰Ëˆ	ÍIÎ‰ú,áù¥¦ymìº(ªùam¹.å¹¤ãy/g9¦í9¥¬;ï#:*âúaãy¥¬:/"yaiyo£9a£z*i‰Ëˆ	ÍLÉÎ‰ù§#ybæy¦ªù¦`¹á(y¬åy/oùå*;ï#:*âùê#yo£9a£z*i‰ÂˆK\WÛY\ÜØYÙ\ÂˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹İ^\›Ø™KJ‰ÊBˆš[
	ĞQRS—ĞTWÑ‘QQPÒ×ĞĞPÒWÒÑVWÓÒÉÊB‚ˆÈÔÈRH\È[š™XİYÛ›H›Üˆ]][XØ]YYZ[ˆ[™]\İÛÙ^\İÚ]BˆÈ^\İ[™ÈÜ™\‹İ[\]HY]ÜˆÚ]İ]XZÚ[™Èš]˜]H]HX›XÛK‚ˆÛ
YÙKŠ
HOˆH]Ú[™İË™[™]Ø[ÛÛ[Y\˜ÙH	‰ˆHYØİ[Y[œ]Y\TÙ[XİÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏW˜ÛÛ[Y\˜ÙW—IÊHŠBˆYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏH˜ÛÛ[Y\˜ÙH—IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	İšY]ËXÛÛ[Y\˜ÙIÊOË˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ØXİ]™IÊH	‰ˆØİ[Y[œ]Y\TÙ[XİÜ[
	ÈØÛÛ[Y\˜ÙK\İ[[X\H˜ÛÛ[Y\˜ÙKZÜIÊK›[™İOOMŠBˆÛÛ[Y\˜ÙWÙXYÈHYÙK™]˜[X]JˆˆŠ
HOˆ
İ™\œÚ[ÛÚ[™İË™[™]Ø[ÛÛ[Y\˜ÙOË™\œÚ[ÛŸ	ÉËX›XĞÛÜİXZÎ’”ÓÓ‹œİš[™ÚYJÚÜ]_ßJKš[˜ÛY\Ê	ØÛÜİÜšXÙIÊKšY]Î™Øİ[Y[™Ù][[Y[RY
	İšY]ËXÛÛ[Y\˜ÙIÊOË˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ØXİ]™IÊ_JHˆˆŠBˆ\ÜÙ\ÛÛ[Y\˜ÙWÙXYÖÉİ™\œÚ[Û‰×Kœİ\İÚ]
	Ì‹Œ	ÊH[™ÛÛ[Y\˜ÙWÙXYÖÉİšY]É×H[™›İÛÛ[Y\˜ÙWÙXYÖÉÜX›XĞÛÜİXZÉ×KÛÛ[Y\˜ÙWÙXYÂˆš[
	ĞQRS—ĞÓÓSQTÑWÕÑP’ÒUÓÒÉËÛÛ[Y\˜ÙWÙXYÖÉİ™\œÚ[Û‰×JBˆYÙK›ØØ]ÜŠ	ÖÙ]K]XHœİØÚÈ—IÊK˜ÛXÚÊ
B‚ˆÈ™X[\ÙHˆÛÛ›ÛË[˜ÛY[™ÈHÛÛ[Z]Y™XÙZ\Ú]Üİ™\ÜÛœÙK‚ˆ\ÜÙ\YÙKœ™\]Y\İœÜİ
˜\ÙH
È	ËØ\KØYZ[‹ØÛÛ[Y\˜ÙWÜŞ[˜×ÜÚİ\ÉË]O^ßJK›ÚÂˆ]HHYÙKœ™\]Y\İ™Ù]
˜\ÙH
È	ËØ\KØYZ[‹ØÛÛ[Y\˜ÙWÙ]IÊKšœÛÛŠ
VÉÙ]I×BˆÚİHH]VÉÜÚİ\É×VÌBˆÚİK\]JİØÚ×Ü]OLKÛÜİÜšXÙOLLİ×ÜİØÚ×İ™\ÚÛL‹\™Ù]ÜİØÚÏN˜XÚ×ÜİØÚÏUYJBˆ\ÜÙ\YÙKœ™\]Y\İœÜİ
˜\ÙH
È	ËØ\KØYZ[‹ÜØ]™WØÛÛ[Y\˜ÙWÙ]IË]OY]JK›ÚÂˆYÙK›ØØ]ÜŠ	ÈØÛÛ[Y\˜ÙK\™[ØY	ÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆÚ[™İË™[™]Ø[ÛÛ[Y\˜ÙKœİ]KœÚİ\ÖÌOË\™Ù]ÜİØÚÏOONŠBˆØ\™HYÙK›ØØ]ÜŠ	ÖÙ]K\ÚİOH‰È
ÈÚİVÉÚY	×H
È	È—IÊBˆØ\™›ØØ]ÜŠ	ÖÙ]KYšY[H\™Ù]ÜİØÚÈ—IÊK™š[
	ÌL	ÊBˆYÙK›ØØ]ÜŠ	ÈØÛÛ[Y\˜ÙK\Ø]™IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	ÜÜË[Y\ÜØYÙIÊK^ÛÛ[OOIùea¹dàz*+yk¦¹mì¹a,¹kf	ÈŠBˆYÙK›ØØ]ÜŠ	ÖÙ]K]XHœ™\İØÚÈ—IÊK˜ÛXÚÊ
Bˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈØÛÛ[Y\˜ÙK[İË[Û›IÊKš\×ØÚXÚÙY

Bˆ\ÜÙ\Ø\™š\×İš\ÚX›J
BˆYÙK›ØØ]ÜŠ	ÈÜÜË[\İ	ÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈÜÜËY^Ü]^	ÊKØZ]Ù›ÜŠİ]OIİš\ÚX›IÊBˆ\ÜÙ\	ùnîº+lH9.í‰È[ˆYÙK›ØØ]ÜŠ	ÈÜÜËY^Ü]^	ÊKš[œ]İ˜[YJ
BˆYÙK›ØØ]ÜŠ	ÈÜÜËXÛÜÙIÊK˜ÛXÚÊ
Bˆ™XÙZ\ÈH×BˆYˆ™XÙZ]™J›İ]JN‚ˆ™XÙZ\Ë˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆYˆ[Š™XÙZ\ÊHOHN‚ˆ\ÜÙ\›İ]K™™]Ú

Kœİ]\ÈOHŒˆ›İ]K˜X›Ü
	Ù˜Z[Y	ÊBˆ[ÙN‚ˆ›İ]K˜ÛÛ[YWÊ
BˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹Ü\˜Ú\ÙWÜ™XÙZ]™Y	Ë™XÙZ]™JBˆØ\™›ØØ]ÜŠ	ÖÙ]K\™XÙZ]™WIÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈÜÜË\™XÙZ]™K\]IÊK™š[
	ÌÉÊBˆYÙK›ØØ]ÜŠ	ÈÜÜËYX[ÙË\İX›Z]	ÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	ÜÜË[Y\ÜØYÙIÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	Ù\œ›Ü‰ÊHŠBˆYÙKœ™[ØY
ØZ]İ[[IÙÛXÛÛ[ØYY	ÊBˆYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏH˜ÛÛ[Y\˜ÙH—IÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈÜÜË\™]IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆ[ØØ[İÜ˜YÙK™Ù]][J	Ø™‹\ÜÌ‹\[™[™ÉÊH	‰ˆÚ[™İË™[™]Ø[ÛÛ[Y\˜ÙKœİ]KœÚİ\ÖÌOËœİØÚ×Ü]OOOMŠBˆ\ÜÙ\[Š™XÙZ\ÊHOHˆ[™™XÙZ\ÖÌHOH™XÙZ\ÖÌWK™XÙZ\ÂˆYÙK›ØØ]ÜŠ	ÖÙ]K]XH™^[œÙ\È—IÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈÜÜËY^[œÙKXØ]YÛÜIÊKœÙ[XİÛÜ[ÛŠ	ùnèùdb‰ÊBˆYÙK›ØØ]ÜŠ	ÈÜÜËY^[œÙKX[[İ[	ÊK™š[
	ÌŒŒIÊBˆYÙK›ØØ]ÜŠ	ÈÜÜËY^[œÙK[›İIÊK™š[
	ùà#ú)¯yfj9®+:*i¹¥+ùaî‰ÊBˆYÙK›ØØ]ÜŠ	ÈÜÜËY^[œÙK\Ø]™IÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ËœÜËY^[œÙIÊK™š[\Š\×İ^Iùà#ú)¯yfj9®+:*i¹¥+ùaî‰ÊKØZ]Ù›ÜŠ
Bˆ›ÜˆÚYZYÚ[ˆ

ÎL
K
LÍ
K
ML
JN‚ˆYÙKœÙ]İšY]ÜÜÜÚ^™JXİ
ÚY]ÚYZYÚZZYÚ
JBˆ›ÜˆXˆ[ˆ
	ÜİØÚÉË	Ü™\İØÚÉË	Ü™\ÜÉË	Ù^[œÙ\ÉÊN‚ˆYÙK›ØØ]ÜŠ	ÖÙ]K]XH‰ÊİXŠÉÈ—IÊK˜ÛXÚÊ
BˆYˆXˆOH	Ü™\ÜÉÎ‚ˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜ[
	ÈÜÜË[Y]šXÜÈœÜË[Y]šXÉÊK›[™İOONHŠBˆY]šXÜÈHYÙK™]˜[X]JˆˆŠ
HOˆ
İÚYš[›™\•ÚYØÜ›Û™Øİ[Y[™Øİ[Y[[[Y[œØÜ›ÛÚYšY]Î™Øİ[Y[™Ù][[Y[RY
	İšY]ËXÛÛ[Y\˜ÙIÊK™Ù]›İ[™[™ĞÛY[™Xİ

KÚYJHˆˆŠBˆ\ÜÙ\Y]šXÜÖÉÜØÜ›Û	×HHÚY
Èˆ[™Y]šXÜÖÉİšY]É×HˆŒ
X‹Y]šXÜÊBˆYˆÜË™[š\›Û‹™Ù]
	ÔÔ×ÔĞÔ‘QS”ÒÕÑT‰ÊN‚ˆ›Û\ˆH]
ÜË™[š\›Û–ÉÔÔ×ÔĞÔ‘QS”ÒÕÑT‰×JNÙ›Û\‹›ZÙ\Š\™[ÏUYK^\İÛÚÏUYJBˆYÙKœØÜ™Y[œÚİ
]\İŠ›Û\ˆÈ‰ÜÜË^İÚYK^İXŸKœ™ÉÊK[ÜYÙOUYJBˆYÙK›ØØ]ÜŠ	ÖÙ]K]XHœ™\ÜÈ—IÊK˜ÛXÚÊ
Bˆ›Üˆ\š[Ù[ˆ
	İÙYZÉË	Û[Û	Ë	ŞYX\‰Ë	Øİ\İÛIÊN‚ˆYÙK›ØØ]ÜŠ	ÈÜÜË\\š[Ù	ÊKœÙ[XİÛÜ[ÛŠ\š[Ù
BˆYÙK›ØØ]ÜŠ	ÈÜÜË\™\ÜY›Ü›H]Û‰ÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜ[
	ÈÜÜË[Y]šXÜÈœÜË[Y]šXÉÊK›[™İOONH	‰ˆØİ[Y[™Ù][[Y[RY
	ÜÜË[Y]šXÜÉÊK™Ù]]šX]J	Ø\šXKX\ŞIÊOOO[[ŠBˆš[
	ÔÔ×ÔTÑL—Ô‘TÔÓ”ÒU‘WÔ‘PÑRTÑVS”ÑWÔ‘TÔ•ÓÒÉÊB‚ˆYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏH›[Ù[È—IÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[]X‹X‰ÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	İšY]Ë[[Ù[ÉÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ØXİ]™IÊH	‰ˆØİ[Y[™Ù][[Y[RY
	Û[Ù[XYZ[‹]šY]ÉÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ØXİ]™IÊH	‰ˆØİ[Y[œ]Y\TÙ[XİÜŠ	ÈÛ[Ù[ËX›ÙH]Û‰ÊHŠBˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[ËX›ÙH]Û‰ÊK™š\œİ˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[[[Ù[œÚİÉÊKØZ]Ù›ÜŠ
Bˆ[Ù[İ^HYÙK›ØØ]ÜŠ	ÈÛ[Ù[[[Ù[	ÊKš[›™\—İ^

Bˆ\ÜÙ\	ĞMH9§"y¥b9ëá9g#yà®ˆŒ0åÈŒÌ[IÈ[ˆ[Ù[İ^ˆ\ÜÙ\	ùn©ùª&yc§únç¹g*9¬®ùamùcìù."ú)ä‰È[ˆ[Ù[İ^ˆYÙK™]˜[X]JˆˆŠ
HOˆÂˆØİ[Y[™Ù][[Y[RY
	Û[Ù[\›Ùš[K[X\ÚË]\›	ÊK˜[YOIÙš^\™N‹ËØYZ[‹\™]šY]ÉÎÂˆØİ[Y[™Ù][[Y[RY
	Û[Ù[\›Ùš[K[[™K]\›	ÊK˜[YOIÙš^\™N‹ËØYZ[‹\š[	ÎÂˆHˆˆŠBˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[\›Ùš[K^	ÊK™š[
	ÌKIÊNÜYÙK›ØØ]ÜŠ	ÈÛ[Ù[\›Ùš[K^IÊK™š[
	Ì‹IÊBˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[\›Ùš[K]ÉÊK™š[
	Î	ÊNÜYÙK›ØØ]ÜŠ	ÈÛ[Ù[\›Ùš[KZ	ÊK™š[
	ÌMŒ	ÊNÜYÙK›ØØ]ÜŠ	ÈÛ[Ù[\›Ùš[KX[™ÛIÊK™š[
	Ì	ÊBˆ[Ù[Ü™\]Y\İÈH×BˆYˆØ]™WÛ[Ù[
›İ]JN‚ˆ[Ù[Ü™\]Y\İË˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆ™\İ[H›İ]K™™]Ú

Bˆ[YKœÛY\
ŒMJBˆ›İ]K™[š[
™\ÜÛœÙO\™\İ[
BˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹Üš[Û[Ù[\›Ùš[\ÉËØ]™WÛ[Ù[
BˆYÙK™]˜[X]JŠ
HOˆ›ÛZ\ÙK˜[
ÜØ]™S[Ù[

KØ]™S[Ù[

WJHŠBˆ\ÜÙ\[Š[Ù[Ü™\]Y\İÊHOHK[Ù[Ü™\]Y\İÂˆ\ÜÙ\[Ù[Ü™\]Y\İÖÌVÉÜİ[WÚY	×H[™[Ù[Ü™\]Y\İÖÌVÉÛ[Ù[ÚY	×K[Ù[Ü™\]Y\İÂˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹Üš[Û[Ù[\›Ùš[\ÉÊBˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[[[Ù[	ÊKØZ]Ù›ÜŠİ]OIÚY[‰ÊBˆYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏHœİ[\È—IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	İšY]Ë\İ[\ÉÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ØXİ]™IÊH	‰ˆØİ[Y[œ]Y\TÙ[XİÜŠ	ÈÜİ[\ËX›ÙH]Û‰ÊHŠBˆYÙK›ØØ]ÜŠ	ÈÜİ[\ËX›ÙH]Û‰ÊK™š\œİ˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈÜİ[K[[Ù[œÚİÉÊKØZ]Ù›ÜŠ
Bˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜİ[K^Üİ[K^KÜİ[K]ËÜİ[KZ	ÊK˜Ûİ[

HOHˆYÙK›ØØ]ÜŠ	ÈÜİ[K[[Ù[›Z]Û‰ÊK˜ÛXÚÊ
B‚ˆİ[WÜ™\]Y\İÈH×BˆX[ÙÜÈH×BˆYÙK›ÛŠ	ÙX[ÙÉË[X™HX[ÙÎˆ
X[ÙÜË˜\[™
X[ÙË›Y\ÜØYÙJKX[ÙË™\ÛZ\ÜÊ
JJBˆYˆØ]™WÜİ[J›İ]JN‚ˆİ[WÜ™\]Y\İË˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆYˆ[Šİ[WÜ™\]Y\İÊHOHN‚ˆ›İ]K™[š[
İ]\ÏMLËÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\Èˆ™\œ›ÜˆŸIÊBˆ[ÙN‚ˆ[YKœÛY\
ŒMJBˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹™\œÚ[Ûˆˆ›[ØÚË\İ[K]™\œÚ[ÛˆŸIÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜØ]™WÜÚÜÙ]IËØ]™WÜİ[JBˆ™Y›Ü™WÜİ[\ÈHYÙK™]˜[X]JŠ
HOˆÚÜ]Kœİ[\Ë›[™İŠBˆYÙK›ØØ]ÜŠ	ÈİšY]Ë\İ[\È]X˜\ˆ˜‰ÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈÜİ[K[˜[YIÊK™š[
	úaãz)!ú` yaî¹fç¹«n9«¯9«/‰ÊBˆYÙK›ØØ]ÜŠ	ÈÜİ[K\šXÙIÊK™š[
	ÍL	ÊBˆYÙK™]˜[X]JŠ
HOˆ›ÛZ\ÙK˜[
ÜØ]™Tİ[J
KØ]™Tİ[J
WJHŠBˆ\ÜÙ\[Šİ[WÜ™\]Y\İÊHOHKİ[WÜ™\]Y\İÂˆ˜Z[YHYÙK™]˜[X]JˆˆŠ
HOˆ
ÂˆÛİ[œÚÜ]Kœİ[\Ë™š[\ŠO›˜[YOOOIúaãz)!ú` yaî¹fç¹«n9«¯9«/‰ÊK›[™İˆÜ[™Øİ[Y[™Ù][[Y[RY
	Üİ[K[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊKˆ˜[YN™Øİ[Y[™Ù][[Y[RY
	Üİ[K[˜[YIÊK˜[YKˆ\ØX›Y™Øİ[Y[™Ù][[Y[RY
	Üİ[K\Ø]™IÊK™\ØX›YˆJHˆˆŠBˆ\ÜÙ\˜Z[YOHÉØÛİ[	ÎŒ	ÛÜ[‰Î•YK	İ˜[YIÎ‰úaãz)!ú` yaî¹fç¹«n9«¯9«/‰Ë	Ù\ØX›Y	Î‘˜[Ù_K˜Z[Yˆ\ÜÙ\	ù§#ybæy¦ªù¦`¹á(y¬åy/oùå*;ï#:*âùê#yo£9a£z*i‰È[ˆYÙK›ØØ]ÜŠ	ÈØ™‹\›ÙXİ[Y\ÜØYÙIÊKš[›™\—İ^

Bˆİ[WÙ˜Z[\™WÛ^Y\œÈHYÙK™]˜[X]JˆˆŠ
HOˆÂˆÛÛœİY\ÜØYÙOYØİ[Y[™Ù][[Y[RY
	Ø™‹\›ÙXİ[Y\ÜØYÙIÊNÂˆÛÛœİ[Ù[YØİ[Y[™Ù][[Y[RY
	Üİ[K[[Ù[	ÊNÂˆ™]\›ˆÂˆY\ÜØYÙV“[X™\‹œ\œÙR[
Ù]ÛÛ\]Yİ[JY\ÜØYÙJK’[™^L
Kˆ[Ù[“[X™\‹œ\œÙR[
Ù]ÛÛ\]Yİ[J[Ù[
K’[™^L
Kˆš\ÚX›N›Y\ÜØYÙK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊH	‰ˆ[X™\‹œ\œÙQ›Ø]
Ù]ÛÛ\]Yİ[JY\ÜØYÙJK›ÜXÚ]JOŒˆNÂˆHˆˆŠBˆ\ÜÙ\İ[WÙ˜Z[\™WÛ^Y\œÖÉÛY\ÜØYÙV‰×Hˆİ[WÙ˜Z[\™WÛ^Y\œÖÉÛ[Ù[‰×H[™İ[WÙ˜Z[\™WÛ^Y\œÖÉİš\ÚX›I×Kİ[WÙ˜Z[\™WÛ^Y\œÂˆYÙK™]˜[X]JŠ
HOˆ›ÛZ\ÙK˜[
ÜØ]™Tİ[J
KØ]™Tİ[J
WJHŠBˆØ]™YHYÙK™]˜[X]JˆˆŠ
HOˆ
Âˆİ[œÚÜ]Kœİ[\Ë›[™İˆÛİ[œÚÜ]Kœİ[\Ë™š[\ŠO›˜[YOOOIúaãz)!ú` yaî¹fç¹«n9«¯9«/‰ÊK›[™İˆÜ[™Øİ[Y[™Ù][[Y[RY
	Üİ[K[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊBˆJHˆˆŠBˆ\ÜÙ\[Šİ[WÜ™\]Y\İÊHOHˆ[™Ø]™YOHÉİİ[	Î˜™Y›Ü™WÜİ[\ÊÌK	ØÛİ[	ÎŒK	ÛÜ[‰Î‘˜[Ù_K
İ[WÜ™\]Y\İËØ]™Y
BˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜØ]™WÜÚÜÙ]IÊBˆYÙK™]˜[X]JŠ
HOˆØYÚÜ
YJHŠBˆš[
	ĞQRS—ÔÕSWÔ‘U–WÑÕP“WÔÕP“RUÓÒÉÊBˆš[
	ÓSÑSÔ“Ñ’SWÔÒS‘ÓWÑS•–WÕÑP’ÒUÓÒÉÊB‚ˆÈØ][ÙÈÔ•Q]\İ›İ]]]Hœ›İÜÙ\ˆİ]H[[HÙ\™\ˆXØÙ\È]‚ˆØ][Ù×ÛÜšYÚ[˜[HYÙK™]˜[X]JŠ
HOˆİXİ\™YÛÛ™JÚÜ]JHŠBˆØ][Ù×Ùš^\™HHÂˆ	Øœ˜[™ÉÎ–ÉÒ\ÜİYLydàyâc	Ë	Ò\ÜİYLyên¹dàyâc	×Kˆ	Û[Ù[ÉÎ–ŞÉÚY	Î‰Ú\ÜİYLK[[Ù[	Ë	Øœ˜[™	Î‰Ò\ÜİYLydàyâc	Ë	Û˜[YIÎ‰Ò\ÜİYLyg¢ú&gÉË	Üİ]\ÉÎ•Y_WKˆ	Üİ[\ÉÎ–ŞÉÚY	Î‰Ú\ÜİYLK\İ[IË	Û˜[YIÎ‰Ò\ÜİYLyìîùb%ÉË	ÜšXÙIÎŒÎL	ØÛÛÜœÉÎ–Éú`#ù¦#‰×K	Üİ]\ÉÎ•Y_WKˆBˆYÙK™]˜[X]JŠ
HOˆİÚ[™İË—×Ú\ÜİYLPÛÛ™š\›O]Ú[™İË˜ÛÛ™š\›_HŠB‚ˆYˆØ][Ù×ØØ\ÙJX™[Xİ[Û‹˜Z[\™WØÚXÚËİXØÙ\Ü×ØÚXÚË™YY˜XÚ×ØÚXÚÊN‚ˆYÙK™]˜[X]J™]HOˆÜÚÜ]O\İXİ\™YÛÛ™J]JNÜ™[™\œ˜[™Ê
NÜ™[™\“[Ù[Ê
NÜ™[™\”İ[\Ê
_H‹Ø][Ù×Ùš^\™JBˆ™\]Y\İÈH×BˆYˆ™\ÜÛ™
›İ]JN‚ˆ™\]Y\İË˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆYˆ[Š™\]Y\İÊHOHN‚ˆ›İ]K™[š[
İ]\ÏMLËÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\Èˆ™\œ›ÜˆŸIÊBˆ[ÙN‚ˆ[YKœÛY\
ŒMJBˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹™\œÚ[Ûˆˆ›[ØÚËXØ][ÙË]™\œÚ[ÛˆŸIÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜØ]™WÜÚÜÙ]IË™\ÜÛ™
BˆYÙK™]˜[X]JXİ[ÛŠBˆ˜Z[YHYÙK™]˜[X]J˜Z[\™WØÚXÚÊBˆ\ÜÙ\[Š™\]Y\İÊHOHH[™˜Z[Y
X™[™\]Y\İË˜Z[Y
Bˆ\ÜÙ\YÙK™]˜[X]J™YY˜XÚ×ØÚXÚÊKX™[ˆYÙK™]˜[X]JXİ[ÛŠBˆØ]™YHYÙK™]˜[X]JİXØÙ\Ü×ØÚXÚÊBˆ\ÜÙ\[Š™\]Y\İÊHOHˆ[™Ø]™Y
X™[™\]Y\İËØ]™Y
BˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜØ]™WÜÚÜÙ]IÊB‚ˆØ][Ù×ØØ\ÙJˆ	ØYœ˜[™	ËˆˆˆŠ
HOˆØYœ˜[™

NÙØİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™[˜[YIÊK˜[YOIÒ\ÜİYLy¥¬9h§¹dàyâc	ÎÜ™]\›ˆ›ÛZ\ÙK˜[
Ğ™[™]Ø[YZ[”›ÙXİÛÜšÜÜXÙKœİX›Z]œ˜[™

K™[™]Ø[YZ[”›ÙXİÛÜšÜÜXÙKœİX›Z]œ˜[™

WJ_Hˆˆ‹ˆˆˆŠ
HOˆ”ÓÓ‹œİš[™ÚYJÚÜ]JOOOR”ÓÓ‹œİš[™ÚYJØœ˜[™Î–ÉÒ\ÜİYLydàyâc	Ë	Ò\ÜİYLyên¹dàyâc	×K[Ù[Î–ŞÚY‰Ú\ÜİYLK[[Ù[	Ëœ˜[™‰Ò\ÜİYLydàyâc	Ë˜[YN‰Ò\ÜİYLyg¢ú&gÉËİ]\ÎY_WKİ[\Î–ŞÚY‰Ú\ÜİYLK\İ[IË˜[YN‰Ò\ÜİYLyìîùb%ÉËšXÙNŒÎLÛÛÜœÎ–Éú`#ù¦#‰×Kİ]\ÎY_W_JH	‰ˆ\ÚÜ]]][Û\ŞHˆˆ‹ˆˆˆŠ
HOˆÚÜ]K˜œ˜[™Ë™š[\ŠOOOIÒ\ÜİYLy¥¬9h§¹dàyâc	ÊK›[™İOOLH	‰ˆ\ÚÜ]]][Û\ŞHˆˆ‹ˆˆˆŠ
HOˆØİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™Y\œ›Ü‰ÊK^ÛÛ[š[˜ÛY\Ê	ù§#ybæy¦ªù¦`¹á(y¬åy/oùå*	ÊHˆˆ‹ˆ
BˆØ][Ù×ØØ\ÙJˆ	ÙY]œ˜[™	ËˆˆˆŠ
HOˆÙY]œ˜[™
	Ò\ÜİYLydàyâc	ÊNÙØİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™[˜[YIÊK˜[YOIÒ\ÜİYLydàyâc9¥.yd#IÎÜ™]\›ˆ›ÛZ\ÙK˜[
Ğ™[™]Ø[YZ[”›ÙXİÛÜšÜÜXÙKœİX›Z]œ˜[™

K™[™]Ø[YZ[”›ÙXİÛÜšÜÜXÙKœİX›Z]œ˜[™

WJ_Hˆˆ‹ˆˆˆŠ
HOˆÚÜ]K˜œ˜[™Ëš[˜ÛY\Ê	Ò\ÜİYLydàyâc	ÊH	‰ˆ\ÚÜ]K˜œ˜[™Ëš[˜ÛY\Ê	Ò\ÜİYLydàyâc9¥.yd#IÊH	‰ˆÚÜ]K›[Ù[ÖÌK˜œ˜[™OOIÒ\ÜİYLydàyâc	È	‰ˆ\ÚÜ]]][Û\ŞHˆˆ‹ˆˆˆŠ
HOˆ\ÚÜ]K˜œ˜[™Ëš[˜ÛY\Ê	Ò\ÜİYLydàyâc	ÊH	‰ˆÚÜ]K˜œ˜[™Ë™š[\ŠOOOIÒ\ÜİYLydàyâc9¥.yd#IÊK›[™İOOLH	‰ˆÚÜ]K›[Ù[ÖÌK˜œ˜[™OOIÒ\ÜİYLydàyâc9¥.yd#IÈ	‰ˆ\ÚÜ]]][Û\ŞHˆˆ‹ˆˆˆŠ
HOˆØİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™Y\œ›Ü‰ÊK^ÛÛ[š[˜ÛY\Ê	ù§#ybæy¦ªù¦`¹á(y¬åy/oùå*	ÊHˆˆ‹ˆ
BˆØ][Ù×ØØ\ÙJˆ	Ù[]Pœ˜[™	ËˆˆˆŠ
HOˆİÚ[™İË˜ÛÛ™š\›OJ
OOYNÜ™]\›ˆ›ÛZ\ÙK˜[
Ù[]Pœ˜[™
	Ò\ÜİYLydàyâc	ÊK[]Pœ˜[™
	Ò\ÜİYLydàyâc	ÊWJ_Hˆˆ‹ˆˆˆŠ
HOˆÚÜ]K˜œ˜[™Ëš[˜ÛY\Ê	Ò\ÜİYLydàyâc	ÊH	‰ˆ\ÚÜ]K˜œ˜[™Ëš[˜ÛY\Ê	ù§*¹b!ºhg‰ÊH	‰ˆÚÜ]K›[Ù[ÖÌK˜œ˜[™OOIÒ\ÜİYLydàyâc	È	‰ˆ\ÚÜ]]][Û\ŞHˆˆ‹ˆˆˆŠ
HOˆ\ÚÜ]K˜œ˜[™Ëš[˜ÛY\Ê	Ò\ÜİYLydàyâc	ÊH	‰ˆÚÜ]K˜œ˜[™Ë™š[\ŠOOOIù§*¹b!ºhg‰ÊK›[™İOOLH	‰ˆÚÜ]K›[Ù[ÖÌK˜œ˜[™OOIù§*¹b!ºhg‰È	‰ˆ\ÚÜ]]][Û\ŞHˆˆ‹ˆˆˆŠ
HOˆØİ[Y[™Ù][[Y[RY
	Ø™‹\›ÙXİ[Y\ÜØYÙIÊK^ÛÛ[š[˜ÛY\Ê	ù§#ybæy¦ªù¦`¹á(y¬åy/oùå*	ÊHˆˆ‹ˆ
BˆØ][Ù×ØØ\ÙJˆ	Ù[]S[Ù[	ËˆˆˆŠ
HOˆİÚ[™İË˜ÛÛ™š\›OJ
OOYNÜ™]\›ˆ›ÛZ\ÙK˜[
Ù[]S[Ù[
	Ú\ÜİYLK[[Ù[	ÊK[]S[Ù[
	Ú\ÜİYLK[[Ù[	ÊWJ_Hˆˆ‹ˆˆˆŠ
HOˆÚÜ]K›[Ù[ËœÛÛYJOšYOOIÚ\ÜİYLK[[Ù[	ÊH	‰ˆØİ[Y[™Ù][[Y[RY
	Û[Ù[ËX›ÙIÊK^ÛÛ[š[˜ÛY\Ê	Ò\ÜİYLyg¢ú&gÉÊH	‰ˆ\ÚÜ]]][Û\ŞHˆˆ‹ˆˆˆŠ
HOˆ\ÚÜ]K›[Ù[ËœÛÛYJOšYOOIÚ\ÜİYLK[[Ù[	ÊH	‰ˆ\ÚÜ]]][Û\ŞHˆˆ‹ˆˆˆŠ
HOˆØİ[Y[™Ù][[Y[RY
	Ø™‹\›ÙXİ[Y\ÜØYÙIÊK^ÛÛ[š[˜ÛY\Ê	ù§#ybæy¦ªù¦`¹á(y¬åy/oùå*	ÊHˆˆ‹ˆ
BˆØ][Ù×ØØ\ÙJˆ	Ù[]Tİ[IËˆˆˆŠ
HOˆİÚ[™İË˜ÛÛ™š\›OJ
OOYNÜ™]\›ˆ›ÛZ\ÙK˜[
Ù[]Tİ[J	Ú\ÜİYLK\İ[IÊK[]Tİ[J	Ú\ÜİYLK\İ[IÊWJ_Hˆˆ‹ˆˆˆŠ
HOˆÚÜ]Kœİ[\ËœÛÛYJOšYOOIÚ\ÜİYLK\İ[IÊH	‰ˆØİ[Y[™Ù][[Y[RY
	Üİ[\ËX›ÙIÊK^ÛÛ[š[˜ÛY\Ê	Ò\ÜİYLyìîùb%ÉÊH	‰ˆ\ÚÜ]]][Û\ŞHˆˆ‹ˆˆˆŠ
HOˆ\ÚÜ]Kœİ[\ËœÛÛYJOšYOOIÚ\ÜİYLK\İ[IÊH	‰ˆ\ÚÜ]]][Û\ŞHˆˆ‹ˆˆˆŠ
HOˆØİ[Y[™Ù][[Y[RY
	Ø™‹\›ÙXİ[Y\ÜØYÙIÊK^ÛÛ[š[˜ÛY\Ê	ù§#ybæy¦ªù¦`¹á(y¬åy/oùå*	ÊHˆˆ‹ˆ
BˆYÙK™]˜[X]J˜\Ş[˜È

HOˆØ]ØZ]ØYÚÜ
YJNİÚ[™İË˜ÛÛ™š\›O]Ú[™İË—×Ú\ÜİYLPÛÛ™š\›NÙ[]HÚ[™İË—×Ú\ÜİYLPÛÛ™š\›_HŠBˆš[
	ĞQRS—ĞĞUSÑ×ĞÔ•QÔÕUWÔ‘U–WÑÕP“WÔÕP“RUÓÒÉÊB‚ˆÈØ][ÙÈÛÛ[Z]Ø[ˆİXØÙYY™Y›Ü™H›ÙXİ[Û‹\›Ùš[HŞ[˜È˜Z[ËˆBˆÈœ›İÜÙ\ˆ]\İYÜ]ÛÛ[Z]YØ[™Y]H[™™]\›™Y™\œÚ[ÛˆÛÈ]ÂˆÈ™^Ø][ÙÈ]]][ÛˆØ[››İYØ[HĞTÈİ[H]Hİ™\ˆH[Ù[Y]‚ˆ\X[Ø™Y›Ü™HHYÙK™]˜[X]JŠ
HOˆ
Ù]NœİXİ\™YÛÛ™JÚÜ]JK[Ù[œİXİ\™YÛÛ™JÚÜ]K›[Ù[ÖÌJK™\œÚ[ÛœÚÜ™\œÚ[ÛŸJHŠBˆš[YYØØ][ÙÈHYÙKœ™\]Y\İ™Ù]
˜\ÙH
È	ËØ\KÜÚÜÙ]IÊBˆ\ÜÙ\š[YYØØ][ÙËšXY\œË™Ù]
	ŞX™[™]Ø[‹XØXÚIÊHOH	ÒU	Ëš[YYØØ][ÙËšXY\œÂˆ\ÜÙ\š[YYØØ][ÙËšœÛÛŠ
VÉİ™\œÚ[Û‰×HOH\X[Ø™Y›Ü™VÉİ™\œÚ[Û‰×Bˆ\X[Û[Ù[Û˜[YHH‰Ô\X[İXØÙ\ÜÈ9g¢ú&gÈİ[YK[YWÛœÊ
_IÂˆ\X[Øœ˜[™H‰ú`ê9b!¹¢$9b§ùo£9dàyâcİ[YK[YWÛœÊ
_IÂˆYÙK™]˜[X]JšYOˆÜ[“[Ù[Y]ÜŠY
H‹\X[Ø™Y›Ü™VÉÛ[Ù[	×VÉÚY	×JBˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[[˜[YIÊK™š[
\X[Û[Ù[Û˜[YJBˆÜšYÚ[˜[ÜØ]™WÜ›Ùš[\ÈH\Û[Ù[Kœš[ØÙ[\‹œİÜ™KœØ]™WÜ›Ùš[\ÂˆYˆ˜Z[Ü›Ùš[WÜŞ[˜ÊÜ›Ùš[\ÊN‚ˆ˜Z\ÙH[[YQ\œ›ÜŠ	Øœ›İÜÙ\ˆš^\™IÊBˆ\Û[Ù[Kœš[ØÙ[\‹œİÜ™KœØ]™WÜ›Ùš[\ÈH˜Z[Ü›Ùš[WÜŞ[˜ÂˆN‚ˆYÙK™]˜[X]JŠ
HOˆØ]™S[Ù[

HŠBˆš[˜[N‚ˆ\Û[Ù[Kœš[ØÙ[\‹œİÜ™KœØ]™WÜ›Ùš[\ÈHÜšYÚ[˜[ÜØ]™WÜ›Ùš[\ÂˆÙ\™\—Ü\X[Ù\™\—Ü\X[İ™\œÚ[ÛˆH\Û[Ù[K˜ÛİYÙÙ]ÚœÛÛ—İ™\œÚ[Û™Y
ˆ	ÜÚÜÙ]IË\Û[Ù[K‘UWÑ’SK\Û[Ù[K‘QUSÔÒÔÑUJBˆ\X[Üİ]HHYÙK™]˜[X]JˆˆŠ
HOˆ
ÂˆÜ[™Øİ[Y[™Ù][[Y[RY
	Û[Ù[[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊKˆ[œ]™Øİ[Y[™Ù][[Y[RY
	Û[Ù[[˜[YIÊK˜[YKˆY™Øİ[Y[™Ù][[Y[RY
	Û[Ù[ZY	ÊK˜[YKˆØØ[œÚÜ]K›[Ù[Ë™š[™
OšYOOYØİ[Y[™Ù][[Y[RY
	Û[Ù[ZY	ÊK˜[YJOË›˜[YKˆ™\œÚ[ÛœÚÜ™\œÚ[Û‚ˆJHˆˆŠBˆ\ÜÙ\\X[Üİ]HOHÂˆ	ÛÜ[‰Î•YK	Ú[œ]	Îœ\X[Û[Ù[Û˜[YK	ÚY	Îœ\X[Ø™Y›Ü™VÉÛ[Ù[	×VÉÚY	×Kˆ	ÛØØ[	Îœ\X[Û[Ù[Û˜[YK	İ™\œÚ[Û‰ÎœÙ\™\—Ü\X[İ™\œÚ[Û‹ˆK\X[Üİ]Bˆ\ÜÙ\Ù\™\—Ü\X[İ™\œÚ[ÛˆOH\X[Ø™Y›Ü™VÉİ™\œÚ[Û‰×Bˆ\ÜÙ\™^
›İÈ›Üˆ›İÈ[ˆÙ\™\—Ü\X[ÉÛ[Ù[É×HYˆ›İÖÉÚY	×HOH\X[Ø™Y›Ü™VÉÛ[Ù[	×VÉÚY	×JVÉÛ˜[YI×HOH\X[Û[Ù[Û˜[YBˆ\ÜÙ\	ùg¢ú&gú,áù¥¦ymì¹a,¹kf;ï#9/a¹«hùo#ùb%ùcl9càù¥n9d#9«iyi,y¥eÉÈ[ˆYÙK›ØØ]ÜŠ	ÈØ™‹\›ÙXİ[Y\ÜØYÙIÊKš[›™\—İ^

Bˆ[Ù[Ù˜Z[\™WÛ^Y\œÈHYÙK™]˜[X]JˆˆŠ
HOˆÂˆÛÛœİY\ÜØYÙOYØİ[Y[™Ù][[Y[RY
	Ø™‹\›ÙXİ[Y\ÜØYÙIÊNÂˆÛÛœİ[Ù[YØİ[Y[™Ù][[Y[RY
	Û[Ù[[[Ù[	ÊNÂˆ™]\›ˆÂˆY\ÜØYÙV“[X™\‹œ\œÙR[
Ù]ÛÛ\]Yİ[JY\ÜØYÙJK’[™^L
Kˆ[Ù[“[X™\‹œ\œÙR[
Ù]ÛÛ\]Yİ[J[Ù[
K’[™^L
Kˆš\ÚX›N›Y\ÜØYÙK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊH	‰ˆ[X™\‹œ\œÙQ›Ø]
Ù]ÛÛ\]Yİ[JY\ÜØYÙJK›ÜXÚ]JOŒˆNÂˆHˆˆŠBˆ\ÜÙ\[Ù[Ù˜Z[\™WÛ^Y\œÖÉÛY\ÜØYÙV‰×Hˆ[Ù[Ù˜Z[\™WÛ^Y\œÖÉÛ[Ù[‰×H[™[Ù[Ù˜Z[\™WÛ^Y\œÖÉİš\ÚX›I×K[Ù[Ù˜Z[\™WÛ^Y\œÂˆœ™\ÚØY\—Ü\X[HYÙKœ™\]Y\İ™Ù]
˜\ÙH
È	ËØ\KÜÚÜÙ]IÊBˆ\ÜÙ\œ™\ÚØY\—Ü\X[šXY\œË™Ù]
	ŞX™[™]Ø[‹XØXÚIÊHOH	ÓRTÔÉËœ™\ÚØY\—Ü\X[šXY\œÂˆœ™\ÚØY\—Ü\X[Ù]HHœ™\ÚØY\—Ü\X[šœÛÛŠ
Bˆ\ÜÙ\œ™\ÚØY\—Ü\X[Ù]VÉİ™\œÚ[Û‰×HOHÙ\™\—Ü\X[İ™\œÚ[Û‚ˆ\ÜÙ\™^
›İÈ›Üˆ›İÈ[ˆœ™\ÚØY\—Ü\X[Ù]VÉÙ]I×VÉÛ[Ù[É×HYˆ›İÖÉÚY	×HOH\X[Ø™Y›Ü™VÉÛ[Ù[	×VÉÚY	×JVÉÛ˜[YI×HOH\X[Û[Ù[Û˜[YBˆš[
	ĞQRS—ÓSÑSÔ“Ñ’SWÔT•PSÔÕPĞÑTÔ×ĞĞPÒWÒS•SQUSÓ—ÓÒÉÊB‚ˆYÙK™]˜[X]Jˆˆ˜\Ş[˜Èœ˜[™OˆØYœ˜[™

NÙØİ[Y[™Ù][[Y[RY
	Ø™‹Xœ˜[™[˜[YIÊK˜[YOXœ˜[™Ø]ØZ]™[™]Ø[YZ[”›ÙXİÛÜšÜÜXÙKœİX›Z]œ˜[™

_Hˆˆ‹\X[Øœ˜[™
BˆÙ\™\—ØY\—Û]]][ÛˆHYÙKœ™\]Y\İ™Ù]
˜\ÙH
È	ËØ\KÜÚÜÙ]IÊKšœÛÛŠ
Bˆ\ÜÙ\\X[Øœ˜[™[ˆÙ\™\—ØY\—Û]]][Û–ÉÙ]I×VÉØœ˜[™É×Bˆ\ÜÙ\™^
›İÈ›Üˆ›İÈ[ˆÙ\™\—ØY\—Û]]][Û–ÉÙ]I×VÉÛ[Ù[É×HYˆ›İÖÉÚY	×HOH\X[Ø™Y›Ü™VÉÛ[Ù[	×VÉÚY	×JVÉÛ˜[YI×HOH\X[Û[Ù[Û˜[YBˆ\ÜÙ\YÙK™]˜[X]J˜œ˜[™OˆÚÜ]K˜œ˜[™Ëš[˜ÛY\Êœ˜[™
H	‰ˆØİ[Y[™Ù][[Y[RY
	Û[Ù[[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊH‹\X[Øœ˜[™
BˆYÙK™]˜[X]JŠ
HOˆØ]™S[Ù[

HŠBˆ\ÜÙ\	ÜÚİÉÈ›İ[ˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[[[Ù[	ÊK™Ù]Ø]šX]J	ØÛ\ÜÉÊBˆ\X[Ü™\İÜ™HHYÙKœ™\]Y\İœÜİ
˜\ÙH
È	ËØ\KØYZ[‹ÜØ]™WÜÚÜÙ]IË]O^Âˆ	Ù]IÎœ\X[Ø™Y›Ü™VÉÙ]I×K	Ù^XİYİ™\œÚ[Û‰ÎœYÙK™]˜[X]J	Ê
HOˆÚÜ™\œÚ[Û‰ÊKˆJBˆ\ÜÙ\\X[Ü™\İÜ™Kœİ]\ÈOHŒ\X[Ü™\İÜ™K^

BˆYÙK™]˜[X]JŠ
HOˆØYÚÜ
YJHŠBˆš[
	ĞQRS—ÓSÑSÔ“Ñ’SWÔT•PSÔÕPĞÑTÔ×ÔÕUWÓÒÉÊB‚ˆÈHÙXÛÛ™X‹Ù]šXÙHÚ[œÈHØ][ÙÈĞTËˆ\ÈXˆ]\İÙY\]È[œØ]™YˆÈ[œ]È[™ØØ[İ]HXÜ›ÜÜÈ[ÚÜÙ]HÜš]H]È[[™[ØY‚ˆİ[WÜÚÜHYÙK™]˜[X]JŠ
HOˆ
Ù]NœİXİ\™YÛÛ™JÚÜ]JK™\œÚ[ÛœÚÜ™\œÚ[ÛŸJHŠBˆÚ[›™\—ÜÚÜHÛÜK™Y\ÛÜJİ[WÜÚÜÉÙ]I×JBˆÚ[›™\—ÜÚÜÉØœ˜[™É×K˜\[™
	ĞĞTÈ9b!ºh HIÊBˆÚ[›™\ˆHYÙKœ™\]Y\İœÜİ
˜\ÙH
È	ËØ\KØYZ[‹ÜØ]™WÜÚÜÙ]IË]O^Âˆ	Ù]IÎˆÚ[›™\—ÜÚÜ	Ù^XİYİ™\œÚ[Û‰Îˆİ[WÜÚÜÉİ™\œÚ[Û‰×KˆJBˆ\ÜÙ\Ú[›™\‹œİ]\ÈOHŒÚ[›™\‹^

BˆÚ[›™\—İ™\œÚ[ÛˆHÚ[›™\‹šœÛÛŠ
VÉİ™\œÚ[Û‰×BˆÚ[›™\—ØØXÚYHYÙKœ™\]Y\İ™Ù]
˜\ÙH
È	ËØ\KÜÚÜÙ]IÊBˆ\ÜÙ\Ú[›™\—ØØXÚYšXY\œË™Ù]
	ŞX™[™]Ø[‹XØXÚIÊHOH	ÓRTÔÉËÚ[›™\—ØØXÚYšXY\œÂˆ\ÜÙ\Ú[›™\—ØØXÚYšœÛÛŠ
VÉİ™\œÚ[Û‰×HOHÚ[›™\—İ™\œÚ[Û‚‚ˆYÙK™]˜[X]JˆˆŠ
HOˆÛÜ[”İ[QY]ÜŠ
NÙØİ[Y[™Ù][[Y[RY
	Üİ[K[˜[YIÊK˜[YOIĞĞTÈ9b!ºh Hˆ9ìîùb%ÉÎÙØİ[Y[™Ù][[Y[RY
	Üİ[K\šXÙIÊK˜[YOIÍMMIßHˆˆŠBˆYÙK™]˜[X]JŠ
HOˆØ]™Tİ[J
HŠBˆİ[WÜİ[HHYÙK™]˜[X]JˆˆŠ
HOˆ
ÂˆÜ[™Øİ[Y[™Ù][[Y[RY
	Üİ[K[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊKˆ[œ]™Øİ[Y[™Ù][[Y[RY
	Üİ[K[˜[YIÊK˜[YKˆØØ[œÚÜ]Kœİ[\ËœÛÛYJO›˜[YOOOIĞĞTÈ9b!ºh Hˆ9ìîùb%ÉÊKˆ™\œÚ[ÛœÚÜ™\œÚ[Û‚ˆJHˆˆŠBˆ\ÜÙ\İ[WÜİ[HOHÉÛÜ[‰Î•YK	Ú[œ]	Î‰ĞĞTÈ9b!ºh Hˆ9ìîùb%ÉË	ÛØØ[	Î‘˜[ÙK	İ™\œÚ[Û‰Îœİ[WÜÚÜÉİ™\œÚ[Û‰×_Kİ[WÜİ[BˆYÙK›ØØ]ÜŠ	ÈÜİ[K[[Ù[›Z]Û‰ÊK˜ÛXÚÊ
B‚ˆÜšYÚ[˜[Û[Ù[Hİ[WÜÚÜÉÙ]I×VÉÛ[Ù[É×VÌBˆYÙK™]˜[X]JšYOˆÜ[“[Ù[Y]ÜŠY
H‹ÜšYÚ[˜[Û[Ù[ÉÚY	×JBˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[[˜[YIÊK™š[
	ĞĞTÈ9b!ºh Hˆ9g¢ú&gÉÊBˆYÙK™]˜[X]JŠ
HOˆØ]™S[Ù[

HŠBˆ[Ù[Üİ[HHYÙK™]˜[X]JˆˆŠ
HOˆ
ÂˆÜ[™Øİ[Y[™Ù][[Y[RY
	Û[Ù[[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊKˆ[œ]™Øİ[Y[™Ù][[Y[RY
	Û[Ù[[˜[YIÊK˜[YKˆØØ[œÚÜ]K›[Ù[ËœÛÛYJO›˜[YOOOIĞĞTÈ9b!ºh Hˆ9g¢ú&gÉÊKˆ™\œÚ[ÛœÚÜ™\œÚ[Û‚ˆJHˆˆŠBˆ\ÜÙ\[Ù[Üİ[HOHÉÛÜ[‰Î•YK	Ú[œ]	Î‰ĞĞTÈ9b!ºh Hˆ9g¢ú&gÉË	ÛØØ[	Î‘˜[ÙK	İ™\œÚ[Û‰Îœİ[WÜÚÜÉİ™\œÚ[Û‰×_K[Ù[Üİ[BˆØXÚWØY\—Üİ[HHYÙKœ™\]Y\İ™Ù]
˜\ÙH
È	ËØ\KÜÚÜÙ]IÊBˆ\ÜÙ\ØXÚWØY\—Üİ[KšXY\œË™Ù]
	ŞX™[™]Ø[‹XØXÚIÊHOH	ÒU	ËØXÚWØY\—Üİ[KšXY\œÂˆ\ÜÙ\ØXÚWØY\—Üİ[KšœÛÛŠ
VÉİ™\œÚ[Û‰×HOHÚ[›™\—İ™\œÚ[Û‚ˆYÙK›ØØ]ÜŠ	ÈÛ[Ù[[[Ù[›Z]Û‰ÊK˜ÛXÚÊ
B‚ˆYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏH˜ÛÛ[Y\˜ÙH—IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	İšY]ËXÛÛ[Y\˜ÙIÊOË˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ØXİ]™IÊHŠBˆYÙK›ØØ]ÜŠ	ÖÙ]K]XHœİØÚÈ—IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆYØİ[Y[™Ù][[Y[RY
	ÜÜË\İØÚË\[™[	ÊKšY[ˆŠBˆØØ[ÜšXÙHHYÙK™]˜[X]JˆˆŠ
HOˆØÛÛœİYYØİ[Y[œ]Y\TÙ[XİÜŠ	ÈÜÜË\Ù\šY\ÈÙ]K\Ù\šY\×KœÙ[XİY	ÊOË™]\Ù]œÙ\šY\ßÚÜ]Kœİ[\ÖÌKšYÜ™]\›ˆÚYšXÙN“[X™\ŠÚÜ]Kœİ[\Ë™š[™
O”İš[™ÊšY
OOOTİš[™ÊY
JOËœšXÙJ__HˆˆŠBˆYÙK›ØØ]ÜŠ	ÈÜÜË\Ù\šY\Ë\šXÙIÊK™š[
	Î	ÊBˆYÙK›ØØ]ÜŠ	ÈÜÜË\šXÙKY›Ü›H]Û‰ÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	ÜÜË[Y\ÜØYÙIÊK^ÛÛ[š[˜ÛY\Ê	ú,áù¥¦ymìº(ªùam¹.å¹b!ºh y¢%º(çyïk¹¦í9¥¬	ÊHŠBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜÜË\Ù\šY\Ë\šXÙIÊKš[œ]İ˜[YJ
HOH	Î	Âˆ\ÜÙ\YÙK™]˜[X]J˜™Y›Ü™HOˆ[X™\ŠÚÜ]Kœİ[\Ë™š[™
O”İš[™ÊšY
OOOTİš[™Ê™Y›Ü™KšY
JOËœšXÙJOOOX™Y›Ü™KœšXÙH‹ØØ[ÜšXÙJB‚ˆÙ\™\—ØY\—Üİ[HHYÙKœ™\]Y\İ™Ù]
˜\ÙH
È	ËØ\KÜÚÜÙ]IÊKšœÛÛŠ
Bˆ\ÜÙ\Ù\™\—ØY\—Üİ[VÉİ™\œÚ[Û‰×HOHÚ[›™\—İ™\œÚ[Û‚ˆ\ÜÙ\	ĞĞTÈ9b!ºh HIÈ[ˆÙ\™\—ØY\—Üİ[VÉÙ]I×VÉØœ˜[™É×Bˆ\ÜÙ\›İ[J™Ù]
	Û˜[YIÊHOH	ĞĞTÈ9b!ºh Hˆ9ìîùb%ÉÈ›Üˆ[ˆÙ\™\—ØY\—Üİ[VÉÙ]I×VÉÜİ[\É×JBˆ\ÜÙ\	ú,áù¥¦ymìº(ªùam¹.å¹b!ºh y¢%º(çyïk¹¦í9¥¬;ï#:*âúaãy¥¬:/"yaiyo£9a£y/ë¹¥.xà ‰È[ˆYÙK›ØØ]ÜŠ	ÈØ™‹\›ÙXİ[Y\ÜØYÙIÊKš[›™\—İ^

BˆYÙK™]˜[X]JŠ
HOˆØYÚÜ
YJHŠBˆ\ÜÙ\YÙK™]˜[X]J™\œÚ[ÛˆOˆÚÜ™\œÚ[ÛOO]™\œÚ[Ûˆ	‰ˆÚÜ]K˜œ˜[™Ëš[˜ÛY\Ê	ĞĞTÈ9b!ºh HIÊH‹Ú[›™\—İ™\œÚ[ÛŠBˆ™\İÜ™YHYÙKœ™\]Y\İœÜİ
˜\ÙH
È	ËØ\KØYZ[‹ÜØ]™WÜÚÜÙ]IË]O^Âˆ	Ù]IÎˆİ[WÜÚÜÉÙ]I×K	Ù^XİYİ™\œÚ[Û‰ÎˆÚ[›™\—İ™\œÚ[Û‹ˆJBˆ\ÜÙ\™\İÜ™Yœİ]\ÈOHŒ™\İÜ™Y^

BˆYÙK™]˜[X]JŠ
HOˆØYÚÜ
YJHŠBˆš[
	ĞQRS—ĞĞUSÑ×ÓSÑSÔ’PÑWÔÕSWĞĞT×ÓÒÉÊB‚ˆYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏH˜\ÜÙ]È—IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆ\[Ùˆ\ÜÙ]ÓØYYOOH	İ[™Yš[™Y	È	‰ˆ\ÜÙ]ÓØYY	‰ˆHYØİ[Y[™Ù][[Y[RY
	Ø™‹X\ÜÙ]XØ]XXİ[ÛœÉÊHŠBˆ\ÜÙ]Ø™Y›Ü™HHYÙK™]˜[X]JŠ
HOˆ
Ù]NœİXİ\™YÛÛ™J\ÜÙ]Ñ]JK™\œÚ[Û˜\ÜÙ]Õ™\œÚ[ÛŸJHŠBˆ\ÜÙ]ØHH‰ĞĞTËPK^İ[YK[YWÛœÊ
H	HLIÂˆ\ÜÙ]ØˆH‰ĞĞTËP‹^İ[YK[YWÛœÊ
H	HLIÂˆš[YYØ\ÜÙ]ÈHYÙKœ™\]Y\İ™Ù]
˜\ÙH
È	ËØ\KØ\ÜÙ]ÉÊBˆ\ÜÙ\š[YYØ\ÜÙ]ËšXY\œË™Ù]
	ŞX™[™]Ø[‹XØXÚIÊHOH	ÒU	Ëš[YYØ\ÜÙ]ËšXY\œÂˆ\ÜÙ]İÚ[›™\ˆHYÙKœ™\]Y\İœÜİ
˜\ÙH
È	ËØ\KØYZ[‹ÜİXÚÙ\—ØØ]YÛÜIË]O^Âˆ	ØXİ[Û‰Îˆ	ØÜ™X]IË	Û˜[YIÎˆ\ÜÙ]ØK	Ù^XİYİ™\œÚ[Û‰Îˆ\ÜÙ]Ø™Y›Ü™VÉİ™\œÚ[Û‰×KˆJBˆ\ÜÙ\\ÜÙ]İÚ[›™\‹œİ]\ÈOHŒ\ÜÙ]İÚ[›™\‹^

Bˆ\ÜÙ]İÚ[›™\—İ™\œÚ[ÛˆH\ÜÙ]İÚ[›™\‹šœÛÛŠ
VÉİ™\œÚ[Û‰×Bˆœ™\ÚØ\ÜÙ]ÈHYÙKœ™\]Y\İ™Ù]
˜\ÙH
È	ËØ\KØ\ÜÙ]ÉÊBˆ\ÜÙ\œ™\ÚØ\ÜÙ]ËšXY\œË™Ù]
	ŞX™[™]Ø[‹XØXÚIÊHOH	ÓRTÔÉËœ™\ÚØ\ÜÙ]ËšXY\œÂˆ\ÜÙ\œ™\ÚØ\ÜÙ]ËšœÛÛŠ
VÉİ™\œÚ[Û‰×HOH\ÜÙ]İÚ[›™\—İ™\œÚ[Û‚ˆ›Û\ØÛİ[HYÙK™]˜[X]JŠ
HOˆİÚ[™İË—×Ú\ÜİYMNT›Û\]Ú[™İËœ›Û\İÚ[™İË—×Ú\ÜİYMNT›Û\Ûİ[LİÚ[™İËœ›Û\J
OOİÚ[™İË—×Ú\ÜİYMNT›Û\Ûİ[
ÊÎÜ™]\›ˆ	İ[™^XİY	ßNÙØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]KX\ÜÙ]XÜ™X]WIÊK˜ÛXÚÊ
NÜ™]\›ˆÚ[™İË—×Ú\ÜİYMNT›Û\Ûİ[HŠBˆ\ÜÙ\›Û\ØÛİ[OHˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]XØ]YÛÜK[˜[YIÊK™š[
\ÜÙ]ØŠBˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]XØ]YÛÜK\Ø]™IÊK˜ÛXÚÊ
BˆÛ
YÙKˆŠ
HOˆ\ÜÙ]Õ™\œÚ[ÛOO^ÚœÛÛ‹™[\Ê\ÜÙ]İÚ[›™\—İ™\œÚ[ÛŠ_HŠBˆ\ÜÙ]Üİ[WÜİ]HHYÙK™]˜[X]Jˆˆ›˜[Y\ÈOˆ
Âˆ™\œÚ[Û˜\ÜÙ]Õ™\œÚ[Û‹ˆ\ĞN˜\ÜÙ]Ñ]K˜Ø]YÛÜšY\Ëš[˜ÛY\Ê˜[Y\Ë˜JKˆ\Ğ˜\ÜÙ]Ñ]K˜Ø]YÛÜšY\Ëš[˜ÛY\Ê˜[Y\Ë˜ŠBˆJHˆˆ‹ÉØIÎˆ\ÜÙ]ØK	Ø‰Îˆ\ÜÙ]ØŸJBˆ\ÜÙ\\ÜÙ]Üİ[WÜİ]HOHÉİ™\œÚ[Û‰Îˆ\ÜÙ]İÚ[›™\—İ™\œÚ[Û‹	Ú\ĞIÎˆYK	Ú\Ğ‰Îˆ˜[Ù_K\ÜÙ]Üİ[WÜİ]Bˆ\ÜÙ\	ú,áù¥¦ymìº(ªùam¹.å¹b!ºh y¢%º(çyïk¹¦í9¥¬	È[ˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]XØ]YÛÜKY\œ›Ü‰ÊKš[›™\—İ^

Bˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]XØ]YÛÜK[[Ù[	ÊK™Ù]Ø]šX]J	ØÛ\ÜÉÊK™š[™
	ÜÚİÉÊHHˆ\ÜÙ\YÙK™]˜[X]JŠ
HOˆÚ[™İË—×Ú\ÜİYMNT›Û\Ûİ[ŠHOHˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]XØ]YÛÜK[[Ù[Ù]KXØ]YÛÜKXÛÜÙWIÊK™š\œİ˜ÛXÚÊ
Bˆ\ÜÙ]Ü™\İÜ™HHYÙKœ™\]Y\İœÜİ
˜\ÙH
È	ËØ\KØYZ[‹ÜİXÚÙ\—ØØ]YÛÜIË]O^Âˆ	ØXİ[Û‰Îˆ	Ù[]IË	Û˜[YIÎˆ\ÜÙ]ØK	Ù^XİYİ™\œÚ[Û‰Îˆ\ÜÙ]İÚ[›™\—İ™\œÚ[Û‹ˆJBˆ\ÜÙ\\ÜÙ]Ü™\İÜ™Kœİ]\ÈOHŒ\ÜÙ]Ü™\İÜ™K^

BˆYÙK™]˜[X]J˜\Ş[˜È

HOˆØ]ØZ]ØY\ÜÙ]ÊYJ_HŠBˆš[
	ĞQRS—ĞTÔÑUÔÕSWĞĞT×ĞĞPÒWÒS•SQUSÓ—ÓÒÉÊB‚ˆ\ÜÙ]İÛÜšÜÜXÙHHYÙK™]˜[X]JˆˆŠ
HOˆÂˆÚ[™İË—×Ú\ÜİYMNP\ÜÙ]Ï\İXİ\™YÛÛ™J\ÜÙ]Ñ]JNÂˆ\ÜÙ]Ñ]O^ØØ]YÛÜšY\Î–Éùaj:`ê	Ë	ú,¤ùdª‰Ë	ú"¬y§-I×KİXÚÙ\œÎ–ÂˆÚY‰Ø\ÜÙ]XØ]XIË˜[YN‰ùçhz)®º,¤ùdª‰ËØ]YÛÜN‰ú,¤ùdª‰Ë\›‰ËÜİ]XËÛZ\ÜÚ[™ËZ\ÜİYMNKX\ÜÙ]œ™ÉßKˆÚY‰Ø\ÜÙ]XØ]X‰Ë˜[YN‰ùªf:"l¹l#ú"¬IËØ]YÛÜN‰ú"¬y§-IË\›‰ËÜİ]XËÚ[XYÙKœ™ÉßKˆÚY‰Ø\ÜÙ]XØ]XÉË˜[YN‰ùêæyêâú,¤ùdª‰ËØ]YÛÜN‰ú,¤ùdª‰Ë\›‰ËÜİ]XËÚ[XYÙKœ™ÉßBˆ_NÂˆİ\œ™[\ÜÙ]Iùaj:`ê	ÎÜ™[™\\ÜÙ]XœÊ
NÜ™[™\\ÜÙ]Ê
NÂˆØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]KX\ÜÙ]XÜ™X]WIÊK˜ÛXÚÊ
NÂˆØİ[Y[™Ù][[Y[RY
	Ø™‹X\ÜÙ]XØ]YÛÜK[˜[YIÊK˜[YOIú,¤ùdª‰ÎÂˆØİ[Y[™Ù][[Y[RY
	Ø™‹X\ÜÙ]XØ]YÛÜKY›Ü›IÊKœ™\]Y\İİX›Z]

NÂˆ™]\›ˆÂˆ›Û\Ø[ÎÚ[™İË—×Ú\ÜİYMNT›Û\Ûİ[ˆ\XØ]N™Øİ[Y[™Ù][[Y[RY
	Ø™‹X\ÜÙ]XØ]YÛÜKY\œ›Ü‰ÊK^ÛÛ[ˆÛİ[™Øİ[Y[™Ù][[Y[RY
	Ø™‹X\ÜÙ]\™\İ[XÛİ[	ÊK^ÛÛ[ˆØ\™Î™Øİ[Y[œ]Y\TÙ[XİÜ[
	ÈØ\ÜÙ]YÜšY˜™‹X\ÜÙ]XØ\™	ÊK›[™İˆ^XÚ][]N™Øİ[Y[œ]Y\TÙ[XİÜ[
	ÈØ\ÜÙ]YÜšYÙ]KY[]K\İXÚÙ\—IÊK›[™İˆNÂˆHˆˆŠBˆ\ÜÙ\\ÜÙ]İÛÜšÜÜXÙHOHÂˆ	Ü›Û\Ø[ÉÎˆ	Ù\XØ]IÎˆ	ùb!ºhg¹d#yê,ymì¹kf9g*	Ëˆ	ØÛİ[	Îˆ	ùæë¹bcyb!ºhgˆÈ9o-IË	ØØ\™ÉÎˆË	Ù^XÚ][]IÎˆËˆK\ÜÙ]İÛÜšÜÜXÙBˆ[™[™×Ø\ÜÙ]Ú[XYÙHH×BˆYÙKœ›İ]J	ÊŠ‹Ú\ÜİYMNKY[^YYX\ÜÙ]œ™ÉË[X™H›İ]Nˆ[™[™×Ø\ÜÙ]Ú[XYÙK˜\[™
›İ]JJBˆÚ]YÙK™^XİÜ™\]Y\İ
	ÊŠ‹Ú\ÜİYMNKY[^YYX\ÜÙ]œ™ÉÊN‚ˆYÙK™]˜[X]JŠ
HOˆØ\ÜÙ]Ñ]KœİXÚÙ\œË™š[™
OšYOOIØ\ÜÙ]XØ]XIÊK\›IËÚ\ÜİYMNKY[^YYX\ÜÙ]œ™ÉÎÜ™[™\\ÜÙ]Ê
NÙØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]KZYW˜\ÜÙ]XØ]XW—H[YÉÊK›ØY[™ÏIÙXYÙ\‰ßHŠBˆ\ÜÙ]Ü[™[™ÈHYÙK™]˜[X]JˆˆŠ
HOˆÂˆÛÛœİYYXOYØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]KZYH˜\ÜÙ]XØ]XH—H˜™‹XØ\™[YYXIÊNÂˆ™]\›ˆÚ[XYÙN™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ú[YÉÊJKš\ÚXš[]KXÙZÛ\™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ë˜™‹Z[XYÙK\XÙZÛ\‰ÊJK™\Ü^_NÂˆHˆˆŠBˆ\ÜÙ\\ÜÙ]Ü[™[™ÈOHÉÚ[XYÙIÎˆ	ÚY[‰Ë	ÜXÙZÛ\‰Îˆ	ÙÜšY	ßK\ÜÙ]Ü[™[™Âˆ\ÜÙ\[Š[™[™×Ø\ÜÙ]Ú[XYÙJHOHBˆYÙK›ØØ]ÜŠ	ÖÙ]KZYH˜\ÜÙ]XØ]XH—H˜™‹XØ\™[YYXH[YÉÊK™]˜[X]Jš[YÈOˆ[YË˜Y]™[\İ[™\Š	Ù\œ›Ü‰Ë

HOˆ[YË™]\Ù]\İ\œ›ÜˆH	ÌIÊHŠBˆ[™[™×Ø\ÜÙ]Ú[XYÙKœÜ

K™[š[
İ]\ÏM›ÙOIÛZ\ÜÚ[™ÉÊBˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]KZYW˜\ÜÙ]XØ]XW—H˜™‹XØ\™[YYXH[YÉÊOË™]\Ù]\İ\œ›ÜOOIÌIÈŠBˆ\ÜÙ]Ù˜Z[YHYÙK™]˜[X]JˆˆŠ
HOˆÂˆÛÛœİYYXOYØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]KZYH˜\ÜÙ]XØ]XH—H˜™‹XØ\™[YYXIÊNÂˆ™]\›ˆÚ[XYÙN™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ú[YÉÊJKš\ÚXš[]KXÙZÛ\™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ë˜™‹Z[XYÙK\XÙZÛ\‰ÊJK™\Ü^_NÂˆHˆˆŠBˆ\ÜÙ\\ÜÙ]Ù˜Z[YOHÉÚ[XYÙIÎˆ	ÚY[‰Ë	ÜXÙZÛ\‰Îˆ	ÙÜšY	ßK\ÜÙ]Ù˜Z[YˆYÙK[œ›İ]J	ÊŠ‹Ú\ÜİYMNKY[^YYX\ÜÙ]œ™ÉÊBˆ[™[™×Ø\ÜÙ]ÜİXØÙ\ÜÈH×BˆYÙKœ›İ]J	ÊŠ‹Ú\ÜİYMNK[ÚËX\ÜÙ]œ™ÉË[X™H›İ]Nˆ[™[™×Ø\ÜÙ]ÜİXØÙ\ÜË˜\[™
›İ]JJBˆÚ]YÙK™^XİÜ™\]Y\İ
	ÊŠ‹Ú\ÜİYMNK[ÚËX\ÜÙ]œ™ÉÊN‚ˆYÙK™]˜[X]JŠ
HOˆØ\ÜÙ]Ñ]KœİXÚÙ\œË™š[™
OšYOOIØ\ÜÙ]XØ]XIÊK\›IËÚ\ÜİYMNK[ÚËX\ÜÙ]œ™ÉÎÜ™[™\\ÜÙ]Ê
NÙØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]KZYW˜\ÜÙ]XØ]XW—H[YÉÊK›ØY[™ÏIÙXYÙ\‰ßHŠBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÖÙ]KZYH˜\ÜÙ]XØ]XH—H˜™‹XØ\™[YYXH[YÉÊK™]˜[X]Jš[YÈOˆÙ]ÛÛ\]Yİ[J[YÊKš\ÚXš[]HŠHOH	ÚY[‰Âˆ\ÜÙ\[Š[™[™×Ø\ÜÙ]ÜİXØÙ\ÜÊHOHBˆ[™[™×Ø\ÜÙ]ÜİXØÙ\ÜËœÜ

K™[š[
İ]\ÏLŒ›ÙOQÓÓÑÛÛ[İ\OIÚ[XYÙKÜ™ÉÊBˆÛ
YÙKŠ
HOˆÙ]ÛÛ\]Yİ[JØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]KZYW˜\ÜÙ]XØ]XW—H˜™‹XØ\™[YYXH[YÉÊJKš\ÚXš[]OOOIİš\ÚX›IÈŠBˆ\ÜÙ]ÛØYYHYÙK™]˜[X]JˆˆŠ
HOˆÂˆÛÛœİYYXOYØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]KZYH˜\ÜÙ]XØ]XH—H˜™‹XØ\™[YYXIÊNÂˆ™]\›ˆÚ[XYÙN™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ú[YÉÊJKš\ÚXš[]KXÙZÛ\™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ë˜™‹Z[XYÙK\XÙZÛ\‰ÊJK™\Ü^_NÂˆHˆˆŠBˆ\ÜÙ\\ÜÙ]ÛØYYOHÉÚ[XYÙIÎˆ	İš\ÚX›IË	ÜXÙZÛ\‰Îˆ	Û›Û™IßK\ÜÙ]ÛØYYˆYÙK[œ›İ]J	ÊŠ‹Ú\ÜİYMNK[ÚËX\ÜÙ]œ™ÉÊBˆYÙK™]˜[X]JŠ
HOˆØ\ÜÙ]Ñ]KœİXÚÙ\œË™š[™
OšYOOIØ\ÜÙ]XØ]XIÊK\›IËÜİ]XËÛZ\ÜÚ[™ËZ\ÜİYMNKX\ÜÙ]œ™ÉÎÜ™[™\\ÜÙ]Ê
_HŠBˆš[
	ĞQRS—ĞTÔÑUÕSP—Ó“×Ñ“TÒÓÒÉÊBˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]XØ]YÛÜK[[Ù[Ù]KXØ]YÛÜKXÛÜÙWIÊK™š\œİ˜ÛXÚÊ
BˆYÙK™]˜[X]JŠ
HOˆØİ\œ™[\ÜÙ]Iú,¤ùdª‰ÎÜ™[™\\ÜÙ]XœÊ
NÜ™[™\\ÜÙ]Ê
NÙØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]KX\ÜÙ]\™[˜[YWIÊK˜ÛXÚÊ
_HŠBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]XØ]YÛÜK[˜[YIÊKš[œ]İ˜[YJ
HOH	ú,¤ùdª‰Âˆ\ÜÙ\YÙK™]˜[X]JŠ
HOˆÚ[™İË—×Ú\ÜİYMNT›Û\Ûİ[ŠHOHˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]XØ]YÛÜK[[Ù[Ù]KXØ]YÛÜKXÛÜÙWIÊK™š\œİ˜ÛXÚÊ
BˆYÙK™]˜[X]JŠ
HOˆØİ\œ™[\ÜÙ]Iùaj:`ê	ÎÜ™[™\\ÜÙ]XœÊ
NÜ™[™\\ÜÙ]Ê
_HŠBˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]\ÙX\˜Ú	ÊK™š[
	ú,¤ùdª‰ÊBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈØ\ÜÙ]YÜšY˜™‹X\ÜÙ]XØ\™	ÊK˜Ûİ[

HOH‚ˆ\ÜÙ\	ù¤'9l"ùb,ˆ9o-IÈ[ˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]\™\İ[XÛİ[	ÊKš[›™\—İ^

B‚ˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]\ÙX\˜Ú	ÊK™š[
	ÉÊBˆYÙK›ØØ]ÜŠ	ÈØ™‹X˜]ÚXØ]X‰ÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÖÙ]KZYH˜\ÜÙ]XØ]XH—IÊK˜ÛXÚÊ
Bˆ[İ™WÜ™\]Y\İÈH×BˆYˆ[İ™WØ\ÜÙ]Ü™\ÜÛœÙJ›İ]JN‚ˆ[İ™WÜ™\]Y\İË˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹›[İ™YŒK™\œÚ[Ûˆˆš\ÜİYMNK[[İ™HŸIÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜİXÚÙ\—ØØ]YÛÜIË[İ™WØ\ÜÙ]Ü™\ÜÛœÙJBˆYÙK›ØØ]ÜŠ	ÈØ™‹]\™Ù]XØ]YÛÜIÊK™š[
	ùì¯º`n	ÊBˆYÙK›ØØ]ÜŠ	ÈØ™‹[[İ™KX\ÜÙ]ÉÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆ\ÜÙ]Ñ]KœİXÚÙ\œË™š[™
OšYOOIØ\ÜÙ]XØ]XIÊOË˜Ø]YÛÜOOOIùì¯º`n	ÈŠBˆ\ÜÙ\[Š[İ™WÜ™\]Y\İÊHOHH[™[İ™WÜ™\]Y\İÖÌVÉØXİ[Û‰×HOH	Û[İ™IÈ[™[İ™WÜ™\]Y\İÖÌVÉÚYÉ×HOHÉØ\ÜÙ]XØ]XI×K[İ™WÜ™\]Y\İÂˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜİXÚÙ\—ØØ]YÛÜIÊB‚ˆYÙK›ØØ]ÜŠ	ÈØ™‹X˜]ÚXØ]X‰ÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÖÙ]KZYH˜\ÜÙ]XØ]XH—IÊK˜ÛXÚÊ
Bˆ[]WØ\ÜÙ]ÈH×BˆYˆ[]WØ\ÜÙ]×Ü™\ÜÛœÙJ›İ]JN‚ˆ[]WØ\ÜÙ]Ë˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹™[]YŒK™\œÚ[Ûˆˆš\ÜİYMNKY[]HŸIÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜİXÚÙ\—ØØ]YÛÜIË[]WØ\ÜÙ]×Ü™\ÜÛœÙJBˆYÙK™]˜[X]JŠ
HOˆİÚ[™İË—×Ú\ÜİYMNPÛÛ™š\›O]Ú[™İË˜ÛÛ™š\›NİÚ[™İË˜ÛÛ™š\›OJ
OOY_HŠBˆYÙK›ØØ]ÜŠ	ÈØ™‹Y[]KX\ÜÙ]ÉÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆX\ÜÙ]Ñ]KœİXÚÙ\œËœÛÛYJOšYOOIØ\ÜÙ]XØ]XIÊHŠBˆ\ÜÙ\[Š[]WØ\ÜÙ]ÊHOHH[™[]WØ\ÜÙ]ÖÌVÉØXİ[Û‰×HOH	Ù[]WÜİXÚÙ\œÉË[]WØ\ÜÙ]ÂˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜİXÚÙ\—ØØ]YÛÜIÊB‚ˆ\ØYØ][\ÈH×BˆYˆ\ØYØ\ÜÙ]Ù˜Z[\™J›İ]JN‚ˆ\ØYØ][\Ë˜\[™
›İ]Kœ™\]Y\İœÜİÙ]JBˆ›İ]K™[š[
İ]\ÏMLËÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\Èˆ™\œ›Üˆ‹›\ÙÈˆ¹."¹`¬ù¦ªù¦`¹i,y¥eÈŸIÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹Ø˜]Úİ\ØYÜİXÚÙ\œÉË\ØYØ\ÜÙ]Ù˜Z[\™JBˆYÙK›ØØ]ÜŠ	ÈÜİXÚÙ\‹Yš[\ÉÊKœÙ]Ú[œ]Ùš[\Êš[\ÏVŞÂˆ	Û˜[YIÎˆ	Ú\ÜİYMNKœ™ÉË	ÛZ[YU\IÎˆ	Ú[XYÙKÜ™ÉËˆ	ØY™™\‰Îˆ‰Ú\ÜİYMNK]\ØYYš^\™IËˆWJBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]]\ØY[[Ù[	ÊK™Ù]Ø]šX]J	ØÛ\ÜÉÊK™š[™
	ÜÚİÉÊHHˆ\ÜÙ\	ùmìº`n9¤áÈH9o-yg%¹âaÉÈ[ˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]]\ØY\İ[[X\IÊKš[›™\—İ^

BˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ][™]ËXØ]YÛÜK]ÙÙÛIÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]]\ØY[™]ËXØ]YÛÜIÊK™š[
	ù¢ny«(y¥¬9b!ºhg‰ÊBˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]]\ØYXÛÛ™š\›IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	Ø™‹X\ÜÙ]]\ØYY\œ›Ü‰ÊK^ÛÛ[š[˜ÛY\Ê	ù."¹`¬ù¦ªù¦`¹i,y¥eÉÊHŠBˆ\ÜÙ\[Š\ØYØ][\ÊHOHBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]]\ØY[[Ù[	ÊK™Ù]Ø]šX]J	ØÛ\ÜÉÊK™š[™
	ÜÚİÉÊHHˆ\ÜÙ\	ùmìº`n9¤áÈH9o-yg%¹âaÉÈ[ˆYÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]]\ØY\İ[[X\IÊKš[›™\—İ^

Bˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈØ™‹X\ÜÙ]]\ØY[™]ËXØ]YÛÜIÊKš[œ]İ˜[YJ
HOH	ù¢ny«(y¥¬9b!ºhg‰ÂˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹Ø˜]Úİ\ØYÜİXÚÙ\œÉÊBˆ\ØYÜİXØÙ\ÜÈH×BˆYˆ\ØYØ\ÜÙ]ÜİXØÙ\ÜÊ›İ]JN‚ˆ\ØYÜİXØÙ\ÜË˜\[™
›İ]Kœ™\]Y\İœÜİÙ]JBˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹™\œÚ[Ûˆˆš\ÜİYMNK]\ØY‹™]H–ŞÈšYˆš\ÜİYMNK]\ØYY‹˜Ø]YÛÜHˆ¹¢ny«(y¥¬9b!ºhgˆ‹\›ˆ‹Üİ]XËÛZ\ÜÚ[™ËZ\ÜİYMNK]\ØYœ™ÈŸW_IÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹Ø˜]Úİ\ØYÜİXÚÙ\œÉË\ØYØ\ÜÙ]ÜİXØÙ\ÜÊBˆYÙK™]˜[X]JŠ
HOˆØÛÛœİ›Ü›OYØİ[Y[™Ù][[Y[RY
	Ø™‹X\ÜÙ]]\ØYY›Ü›IÊNÙ›Ü›Kœ™\]Y\İİX›Z]

NÙ›Ü›Kœ™\]Y\İİX›Z]

_HŠBˆÛ
YÙKŠ
HOˆYØİ[Y[™Ù][[Y[RY
	Ø™‹X\ÜÙ]]\ØY[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊHŠBˆ\ÜÙ\[Š\ØYÜİXØÙ\ÜÊHOHBˆ\ÜÙ\	ùmì¹."¹`¬ÈH9o-yb,8à#9¢ny«(y¥¬9b!ºhg¸à#IÈ[ˆYÙK›ØØ]ÜŠ	ÈØ™‹\›ÙXİ[Y\ÜØYÙIÊKš[›™\—İ^

BˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹Ø˜]Úİ\ØYÜİXÚÙ\œÉÊB‚ˆYÙKœÙ]İšY]ÜÜÜÚ^™JÉİÚY	ÎŒÎL	ÚZYÚ	ÎJBˆYÙK™]˜[X]JŠ
HOˆØİ\œ™[\ÜÙ]Iùaj:`ê	ÎÜ™[™\\ÜÙ]XœÊ
NÜ™[™\\ÜÙ]Ê
NÙØİ[Y[™Ù][[Y[RY
	Ø™‹X˜]ÚXØ]X‰ÊK˜ÛXÚÊ
_HŠBˆ\ÜÙ]Û[Øš[HHYÙK™]˜[X]JˆˆŠ
HOˆ
ÂˆØÜ›Û™Øİ[Y[™Øİ[Y[[[Y[œØÜ›ÛÚYˆÛÛ[[œÎ™Ù]ÛÛ\]Yİ[JØİ[Y[™Ù][[Y[RY
	Ø\ÜÙ]YÜšY	ÊJK™ÜšY[\]PÛÛ[[œËœÜ]
	È	ÊK›[™İˆ[]RZYÚ™Øİ[Y[œ]Y\TÙ[XİÜŠ	ÈØ\ÜÙ]YÜšYÙ]KY[]K\İXÚÙ\—IÊOË™Ù]›İ[™[™ĞÛY[™Xİ

KšZYÚˆ˜]Úİ™\™›İÎ™Ù]ÛÛ\]Yİ[JØİ[Y[™Ù][[Y[RY
	Ø\ÜÙ]X˜]Ú˜\‰ÊJK›İ™\™›İÖˆJHˆˆŠBˆ\ÜÙ\\ÜÙ]Û[Øš[VÉÜØÜ›Û	×HHÎLˆ[™\ÜÙ]Û[Øš[VÉØÛÛ[[œÉ×HOHˆ[™\ÜÙ]Û[Øš[VÉÙ[]RZYÚ	×HHË\ÜÙ]Û[Øš[Bˆ\ÜÙ\\ÜÙ]Û[Øš[VÉØ˜]Úİ™\™›İÉ×HOH	Ø]]ÉË\ÜÙ]Û[Øš[BˆYÙKœÙ]İšY]ÜÜÜÚ^™JÉİÚY	ÎŒLN	ÚZYÚ	ÎLJB‚ˆYÙK™]˜[X]JˆˆŠ
HOˆÂˆYŠØİ[Y[™Ù][[Y[RY
	Ø\ÜÙ]X˜]Ú˜\‰ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊJYØİ[Y[™Ù][[Y[RY
	Ø™‹X˜]ÚXØ]X‰ÊK˜ÛXÚÊ
NÂˆ\ÜÙ]Ñ]O]Ú[™İË—×Ú\ÜİYMNP\ÜÙ]ÎÙ[]HÚ[™İË—×Ú\ÜİYMNP\ÜÙ]ÎÂˆÚ[™İË˜ÛÛ™š\›O]Ú[™İË—×Ú\ÜİYMNPÛÛ™š\›NÙ[]HÚ[™İË—×Ú\ÜİYMNPÛÛ™š\›NÂˆÚ[™İËœ›Û\]Ú[™İË—×Ú\ÜİYMNT›Û\Ù[]HÚ[™İË—×Ú\ÜİYMNT›Û\Ù[]HÚ[™İË—×Ú\ÜİYMNT›Û\Ûİ[Âˆİ\œ™[\ÜÙ]Iùaj:`ê	ÎÜ™[™\\ÜÙ]XœÊ
NÜ™[™\\ÜÙ]Ê
NÂˆHˆˆŠBˆš[
	ĞQRS—ĞTÔÑUÓP”T–WÕÓÔ’ÔÔPÑWÓÒÉÊB‚ˆš[Û˜]ˆHYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏHœš[XÙ[\ˆ—IÊBˆš[Û˜]‹˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜ[
	ÈÜËYÜšYœËXØ\™	ÊK›[™İŒ	‰ˆØİ[Y[™Ù][[Y[RY
	İšY]Ë\š[XÙ[\‰ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ØXİ]™IÊHŠBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜËXÛÛ™šYÉÊK™Ù]Ø]šX]J	ØÛ\ÜÉÊK™š[™
	İØ\›‰ÊHHˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÖÙ]K\ÏHœİ\—IÊK˜Ûİ[

HOHˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÖÙ]K\ÏHœ›Ùš[H—IÊK˜Ûİ[

HOHˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜË[[Ù[	ÊK˜Ûİ[

HOHˆ\ÜÙ\	Î0åÈMŒ[HÈKHÈH‹IÈ[ˆYÙK›ØØ]ÜŠ	ÈÜËYÜšY	ÊKš[›™\—İ^

Bˆ›ÜˆÚYZYÚ[ˆ

ÎL
K
ÍL
K
ML
JN‚ˆYÙKœÙ]İšY]ÜÜÜÚ^™JXİ
ÚY]ÚYZYÚZZYÚ
JBˆY]šXÜÈHYÙK™]˜[X]JˆˆŠ
HOˆ
ÂˆÚYš[›™\•ÚYØÜ›Û™Øİ[Y[™Øİ[Y[[[Y[œØÜ›ÛÚYˆšY]Î™Øİ[Y[™Ù][[Y[RY
	İšY]Ë\š[XÙ[\‰ÊK™Ù]›İ[™[™ĞÛY[™Xİ

KÚYˆØ\™Î™Øİ[Y[œ]Y\TÙ[XİÜ[
	ÈÜËYÜšYœËXØ\™	ÊK›[™İˆÙXÜ™]Î™Øİ[Y[™Ù][[Y[RY
	İšY]Ë\š[XÙ[\‰ÊK^ÛÛ[š[˜ÛY\Ê	Ù˜ZÙKZÙ^IÊBˆJHˆˆŠBˆ\ÜÙ\Y]šXÜÖÉÜØÜ›Û	×HHÚY
Èˆ[™Y]šXÜÖÉİšY]É×HˆŒ[™Y]šXÜÖÉØØ\™É×Hˆ[™›İY]šXÜÖÉÜÙXÜ™]É×KY]šXÜÂˆYØXŞWÛÜ™\ˆH\Û[Ù[K˜ÛÛ[Y\˜ÙKœİÜ™K›ØØ[ÛÜ™\œÊ
VÌBˆÛÛ[Y\˜ÙHH\Û[Ù[K˜ÛÛ[Y\˜ÙKœ™XY

Bˆ\ÜÙ\ÛÛ[Y\˜ÙVÉÛÜ™\—Ùš[˜[˜ÙI×KœÜ
YØXŞWÛÜ™\–ÉÚY	×K›Û™JKYØXŞWÛÜ™\–ÉÚY	×Bˆ\ÜÙ\\Û[Ù[K˜ÛÛ[Y\˜ÙKœİÜ™K˜ÛÛ[Z]
[
ÛÛ[Y\˜ÙK™Ù]
	Ü™]š\Ú[Û‰Ë
JKÛÛ[Y\˜ÙJBˆYÙK›ØØ]ÜŠ	ÈÜË\™[ØY	ÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K\ÏW˜š[™[™×—IÊHOOH[ŠBˆYÙK›ØØ]ÜŠ	ÖÙ]K\ÏH˜š[™[™È—IÊK™š\œİ˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈÜËXš[™[[Ù[œÚİÉÊKØZ]Ù›ÜŠ
Bˆ\ÜÙ\	ù.#y§ ù/ë¹¥.yáçù¥-»ï#ù¢$9§+;ï#ùnªùkf:,áù¥¦IÈ[ˆYÙK›ØØ]ÜŠ	ÈÜËXš[™[[Ù[	ÊKš[›™\—İ^

Bˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜËXš[™\ÚİHÜ[Û‰ÊK˜Ûİ[

HH‚ˆYÙK›ØØ]ÜŠ	ÈÜËXš[™XÛÜÙIÊK˜ÛXÚÊ
Bˆš[
	Ô’S•ĞÑS•T—ĞMWÔ‘TÔÓ”ÒU‘WÑRSĞÓÔÑQÓÒÉÊB‚ˆ[\]WÛ˜]ˆHYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏH[\]\È—IÊBˆ[\]WÛ˜]‹˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆ\[ÙˆÚ[™İË˜™[™]Ø[‘[œİ\™U[\]QY]ÜˆOOH	Ù[˜İ[Û‰È	‰ˆ\[ÙˆÚÜØYYOOH	İ[™Yš[™Y	È	‰ˆÚÜØYY	‰ˆ\[Ùˆ[\]\ÓØYYOOH	İ[™Yš[™Y	È	‰ˆ[\]\ÓØYYŠBˆ^WØ™Y›Ü™HHYÙK™]˜[X]JˆˆŠ
HOˆ
Âˆ™XYNˆH]Ú[™İË—×Ø™[™]Ø[•[\]TİXÚÔ™XYKˆ[š]™\œØ[ØÜš\Î™Øİ[Y[œ]Y\TÙ[XİÜ[
	ÜØÜš\ÜÜ˜ÊH˜YZ[‹][š]™\œØ[][\]\ËšœÈ—IÊK›[™İˆY]Ü”ØÜš\Î™Øİ[Y[œ]Y\TÙ[XİÜ[
	ÜØÜš\ÜÜ˜ÊH˜YZ[‹][\]KYY]Ü‹]Œ‹šœÈ—IÊK›[™İˆš[\œÎˆHYØİ[Y[™Ù][[Y[RY
	Ø™‹][\]KYš[\œÉÊBˆJHˆˆŠBˆ\ÜÙ\^WØ™Y›Ü™HOHÉÜ™XYIÎˆ˜[ÙK	İ[š]™\œØ[ØÜš\ÉÎˆ	ÙY]Ü”ØÜš\ÉÎˆ	Ùš[\œÉÎˆY_K^WØ™Y›Ü™B‚ˆ[\]WÛXœ˜\HHYÙK™]˜[X]JˆˆŠ
HOˆÂˆÚ[™İË—×Ú\ÜİYMNU[\]\Ï\İXİ\™YÛÛ™J[\]\Ñ]JNÂˆÚ[™İË—×Ú\ÜİYMNTÚÜ\İXİ\™YÛÛ™JÚÜ]JNÂˆÛÛœİ[Ù[JÚÜ]K›[Ù[ß×JVÌ_ÚY‰Ú\ÜİYMNK[[Ù[	Ë˜[YN‰ù®+:*i¹g¢ú&gÉËİ]\ÎY_NÂˆYŠJÚÜ]K›[Ù[ß×JK›[™İ
\ÚÜ]K›[Ù[ÏVÛ[Ù[NÂˆÛÛœİš\œİJÚÜ]Kœİ[\ß×JVÌ_ÚY‰Ú\ÜİYMNKXÜ\İ[	Ë˜[YN‰ù¦m¹ojIËİ]\ÎY_NÂˆYŠJÚÜ]Kœİ[\ß×JK›[™İ
\ÚÜ]Kœİ[\ÏVÙš\œİNÂˆÛÛœİÙXÛÛ™JÚÜ]Kœİ[\ß×JVÌW_ÚY‰Ú\ÜİYMNK[Z\œ›Ü‰Ë˜[YN‰úcèzgh‰Ëİ]\ÎY_NÂˆYŠJÚÜ]Kœİ[\ß×JKœÛÛYJOšYOO\ÙXÛÛ™šY
J\ÚÜ]Kœİ[\Ëœ\Ú
ÙXÛÛ™
NÂˆ[\]\Ñ]O^ØØ]YÛÜšY\Î–Éùaj:`ê	Ë	ùì¯º`n	Ë	ùkhùëà	×K[\]\Î–ÂˆÚY‰Ú\ÜİYMNK][š]™\œØ[	Ë˜[YN‰ù¦m¹ojz,¤ùdª¹ª(y§oÉËØ]YÛÜN‰ùì¯º`n	Ë[Ù[ÚY‰Ê‰Ë[š]™\œØ[YK™Y™\™[˜ÙWÛ[Ù[ÚY›[Ù[šY™Y™\™[˜ÙWÜİ[WÚY™š\œİšY[X—İ\›‰ËÜİ]XËÛZ\ÜÚ[™ËZ\ÜİYMNK][\]Kœ™ÉßKˆÚY‰Ú\ÜİYMNK\ÜXÚYšXÉË˜[YN‰úcèzghº"¬y§-yª(y§oÉËØ]YÛÜN‰ùì¯º`n	Ë[Ù[ÚY›[Ù[šYØ\ÙWÜİ[WÚYœÙXÛÛ™šY[X—İ\›‰ËÜİ]XËÚ[XYÙKœ™ÉßBˆ_NÂˆİ\œ™[Iùaj:`ê	ÎÂˆØš™Xİ˜\ÜÚYÛŠ™[™]Ø[YZ[“Xœ˜\UÛÜšÜÜXÙKœİ]KÜ]Y\N‰ÉËØ]YÛÜN‰ùaj:`ê	Ë[Ù[‰ÉËİ[N‰ÉË\N‰Ø[	ßJNÂˆ™[™\•[\]UXœÊ
NÜ™[™\•[\]\Ê
NÂˆÛÛœİ˜\ÙO^ØØ\™Î™Øİ[Y[œ]Y\TÙ[XİÜ[
	Èİ[\]KYÜšY˜™‹][\]KXØ\™	ÊK›[™İ^™Øİ[Y[™Ù][[Y[RY
	İ[\]KYÜšY	ÊK^ÛÛ[NÂˆ™[™]Ø[YZ[“Xœ˜\UÛÜšÜÜXÙKœİ]Kœ]Y\OIù¦m¹ojIÎÜ™[™\•[\]\Ê
NØÛÛœİÙX\˜ÚYØİ[Y[œ]Y\TÙ[XİÜ[
	Èİ[\]KYÜšY˜™‹][\]KXØ\™	ÊK›[™İÂˆØš™Xİ˜\ÜÚYÛŠ™[™]Ø[YZ[“Xœ˜\UÛÜšÜÜXÙKœİ]KÜ]Y\N‰ÉËØ]YÛÜN‰ùì¯º`n	Ë[Ù[‰ÉËİ[N™š\œİšY\N‰Ø[	ßJNÜ™[™\•[\]\Ê
NØÛÛœİİ[OYØİ[Y[œ]Y\TÙ[XİÜ[
	Èİ[\]KYÜšY˜™‹][\]KXØ\™	ÊK›[™İÂˆØš™Xİ˜\ÜÚYÛŠ™[™]Ø[YZ[“Xœ˜\UÛÜšÜÜXÙKœİ]KÜ]Y\N‰ÉËØ]YÛÜN‰ùì¯º`n	Ë[Ù[›[Ù[šYİ[N‰ÉË\N‰ÜÜXÚYšXÉßJNÜ™[™\•[\]\Ê
NØÛÛœİÜXÚYšXÏYØİ[Y[œ]Y\TÙ[XİÜ[
	Èİ[\]KYÜšY˜™‹][\]KXØ\™	ÊK›[™İÂˆØš™Xİ˜\ÜÚYÛŠ™[™]Ø[YZ[“Xœ˜\UÛÜšÜÜXÙKœİ]KÜ]Y\N‰ÉËØ]YÛÜN‰ùì¯º`n	Ë[Ù[›[Ù[šYİ[N‰ÉË\N‰İ[š]™\œØ[	ßJNÜ™[™\•[\]\Ê
NØÛÛœİ[š]™\œØ[YØİ[Y[œ]Y\TÙ[XİÜ[
	Èİ[\]KYÜšY˜™‹][\]KXØ\™	ÊK›[™İÂˆØš™Xİ˜\ÜÚYÛŠ™[™]Ø[YZ[“Xœ˜\UÛÜšÜÜXÙKœİ]KÜ]Y\N‰ÉËØ]YÛÜN‰ùaj:`ê	Ë[Ù[‰ÉËİ[N‰ÉË\N‰Ø[	ßJNØİ\œ™[Iùaj:`ê	ÎÜ™[™\•[\]UXœÊ
NÜ™[™\•[\]\Ê
NÂˆ™]\›ˆØ˜\ÙKÙX\˜Úİ[KÜXÚYšXË[š]™\œØ[[Ù[›[Ù[›˜[YKš\œİ™š\œİ›˜[YKÙXÛÛ™œÙXÛÛ™›˜[Y_NÂˆHˆˆŠBˆ\ÜÙ\[\]WÛXœ˜\VÉØ˜\ÙI×VÉØØ\™É×HOH‹[\]WÛXœ˜\Bˆ\ÜÙ\[
X™[[ˆ[\]WÛXœ˜\VÉØ˜\ÙI×VÉİ^	×H›ÜˆX™[[ˆ
ˆ	ù¦m¹ojz,¤ùdª¹ª(y§oÉË	úcèzghº"¬y§-yª(y§oÉË	ùì¯º`n	Ë[\]WÛXœ˜\VÉÛ[Ù[	×Kˆ[\]WÛXœ˜\VÉÙš\œİ	×K[\]WÛXœ˜\VÉÜÙXÛÛ™	×K	ùaj9g¢ú&gú`&¹å*	Ë	ù£!ùk¦¹g¢ú&gÉËˆ
JK[\]WÛXœ˜\Bˆ\ÜÙ\ÚÙ^Nˆ[\]WÛXœ˜\VÚÙ^WH›ÜˆÙ^H[ˆ
	ÜÙX\˜Ú	Ë	Üİ[IË	ÜÜXÚYšXÉË	İ[š]™\œØ[	Ê_HOHÂˆ	ÜÙX\˜Ú	ÎˆK	Üİ[IÎˆK	ÜÜXÚYšXÉÎˆK	İ[š]™\œØ[	ÎˆKˆK[\]WÛXœ˜\Bˆ[™[™×İ[\]WÚ[XYÙHH×BˆYÙKœ›İ]J	ÊŠ‹Ú\ÜİYMNKY[^YY][\]Kœ™ÉË[X™H›İ]Nˆ[™[™×İ[\]WÚ[XYÙK˜\[™
›İ]JJBˆÚ]YÙK™^XİÜ™\]Y\İ
	ÊŠ‹Ú\ÜİYMNKY[^YY][\]Kœ™ÉÊN‚ˆYÙK™]˜[X]JŠ
HOˆİ[\]\Ñ]K[\]\Ë™š[™
OšYOOIÚ\ÜİYMNK][š]™\œØ[	ÊK[X—İ\›IËÚ\ÜİYMNKY[^YY][\]Kœ™ÉÎÜ™[™\•[\]\Ê
NÙØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K][\]KZYWš\ÜİYMNK][š]™\œØ[—H[YÉÊK›ØY[™ÏIÙXYÙ\‰ßHŠBˆ[\]WÜ[™[™ÈHYÙK™]˜[X]JˆˆŠ
HOˆÂˆÛÛœİYYXOYØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K][\]KZYHš\ÜİYMNK][š]™\œØ[—H˜™‹XØ\™[YYXIÊNÂˆ™]\›ˆÚ[XYÙN™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ú[YÉÊJKš\ÚXš[]KXÙZÛ\™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ë˜™‹Z[XYÙK\XÙZÛ\‰ÊJK™\Ü^_NÂˆHˆˆŠBˆ\ÜÙ\[\]WÜ[™[™ÈOHÉÚ[XYÙIÎˆ	ÚY[‰Ë	ÜXÙZÛ\‰Îˆ	ÙÜšY	ßK[\]WÜ[™[™Âˆ\ÜÙ\[Š[™[™×İ[\]WÚ[XYÙJHOHBˆYÙK›ØØ]ÜŠ	ÖÙ]K][\]KZYHš\ÜİYMNK][š]™\œØ[—H˜™‹XØ\™[YYXH[YÉÊK™]˜[X]Jš[YÈOˆ[YË˜Y]™[\İ[™\Š	Ù\œ›Ü‰Ë

HOˆ[YË™]\Ù]\İ\œ›ÜˆH	ÌIÊHŠBˆ[™[™×İ[\]WÚ[XYÙKœÜ

K™[š[
İ]\ÏM›ÙOIÛZ\ÜÚ[™ÉÊBˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K][\]KZYWš\ÜİYMNK][š]™\œØ[—H˜™‹XØ\™[YYXH[YÉÊOË™]\Ù]\İ\œ›ÜOOIÌIÈŠBˆ[\]WÙ˜Z[YHYÙK™]˜[X]JˆˆŠ
HOˆÂˆÛÛœİYYXOYØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K][\]KZYHš\ÜİYMNK][š]™\œØ[—H˜™‹XØ\™[YYXIÊNÂˆ™]\›ˆÚ[XYÙN™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ú[YÉÊJKš\ÚXš[]KXÙZÛ\™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ë˜™‹Z[XYÙK\XÙZÛ\‰ÊJK™\Ü^_NÂˆHˆˆŠBˆ\ÜÙ\[\]WÙ˜Z[YOHÉÚ[XYÙIÎˆ	ÚY[‰Ë	ÜXÙZÛ\‰Îˆ	ÙÜšY	ßK[\]WÙ˜Z[YˆYÙK[œ›İ]J	ÊŠ‹Ú\ÜİYMNKY[^YY][\]Kœ™ÉÊBˆ[™[™×İ[\]WÜİXØÙ\ÜÈH×BˆYÙKœ›İ]J	ÊŠ‹Ú\ÜİYMNK[ÚË][\]Kœ™ÉË[X™H›İ]Nˆ[™[™×İ[\]WÜİXØÙ\ÜË˜\[™
›İ]JJBˆÚ]YÙK™^XİÜ™\]Y\İ
	ÊŠ‹Ú\ÜİYMNK[ÚË][\]Kœ™ÉÊN‚ˆYÙK™]˜[X]JŠ
HOˆİ[\]\Ñ]K[\]\Ë™š[™
OšYOOIÚ\ÜİYMNK][š]™\œØ[	ÊK[X—İ\›IËÚ\ÜİYMNK[ÚË][\]Kœ™ÉÎÜ™[™\•[\]\Ê
NÙØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K][\]KZYWš\ÜİYMNK][š]™\œØ[—H[YÉÊK›ØY[™ÏIÙXYÙ\‰ßHŠBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÖÙ]K][\]KZYHš\ÜİYMNK][š]™\œØ[—H˜™‹XØ\™[YYXH[YÉÊK™]˜[X]Jš[YÈOˆÙ]ÛÛ\]Yİ[J[YÊKš\ÚXš[]HŠHOH	ÚY[‰Âˆ\ÜÙ\[Š[™[™×İ[\]WÜİXØÙ\ÜÊHOHBˆ[™[™×İ[\]WÜİXØÙ\ÜËœÜ

K™[š[
İ]\ÏLŒ›ÙOQÓÓÑÛÛ[İ\OIÚ[XYÙKÜ™ÉÊBˆÛ
YÙKŠ
HOˆÙ]ÛÛ\]Yİ[JØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K][\]KZYWš\ÜİYMNK][š]™\œØ[—H˜™‹XØ\™[YYXH[YÉÊJKš\ÚXš[]OOOIİš\ÚX›IÈŠBˆ[\]WÛØYYHYÙK™]˜[X]JˆˆŠ
HOˆÂˆÛÛœİYYXOYØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K][\]KZYHš\ÜİYMNK][š]™\œØ[—H˜™‹XØ\™[YYXIÊNÂˆ™]\›ˆÚ[XYÙN™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ú[YÉÊJKš\ÚXš[]KXÙZÛ\™Ù]ÛÛ\]Yİ[JYYXKœ]Y\TÙ[XİÜŠ	Ë˜™‹Z[XYÙK\XÙZÛ\‰ÊJK™\Ü^_NÂˆHˆˆŠBˆ\ÜÙ\[\]WÛØYYOHÉÚ[XYÙIÎˆ	İš\ÚX›IË	ÜXÙZÛ\‰Îˆ	Û›Û™IßK[\]WÛØYYˆYÙK[œ›İ]J	ÊŠ‹Ú\ÜİYMNK[ÚË][\]Kœ™ÉÊBˆYÙK™]˜[X]JŠ
HOˆİ[\]\Ñ]K[\]\Ë™š[™
OšYOOIÚ\ÜİYMNK][š]™\œØ[	ÊK[X—İ\›IËÜİ]XËÛZ\ÜÚ[™ËZ\ÜİYMNK][\]Kœ™ÉÎÜ™[™\•[\]\Ê
_HŠBˆš[
	ĞQRS—ÕSTUWÕSP—Ó“×Ñ“TÒÓÒÉÊBˆ›ÜˆÚYZYÚ[ˆ

ÎL
K
ÍL
K
LNL
JN‚ˆYÙKœÙ]İšY]ÜÜÜÚ^™JXİ
ÚY]ÚYZYÚZZYÚ
JBˆXœ˜\WÛ^[İ]HYÙK™]˜[X]JˆˆŠ
HOˆ
ÂˆØÜ›Û™Øİ[Y[™Øİ[Y[[[Y[œØÜ›ÛÚYˆ\ÜÙ]ÛÛ[[œÎ™Ù]ÛÛ\]Yİ[JØİ[Y[™Ù][[Y[RY
	Ø\ÜÙ]YÜšY	ÊJK™ÜšY[\]PÛÛ[[œËœÜ]
	È	ÊK›[™İˆ[\]PÛÛ[[œÎ™Ù]ÛÛ\]Yİ[JØİ[Y[™Ù][[Y[RY
	İ[\]KYÜšY	ÊJK™ÜšY[\]PÛÛ[[œËœÜ]
	È	ÊK›[™İˆ[]RZYÚ™Øİ[Y[œ]Y\TÙ[XİÜŠ	Èİ[\]KYÜšYÙ]KY[]K][\]WIÊOË™Ù]›İ[™[™ĞÛY[™Xİ

KšZYÚˆJHˆˆŠBˆ\ÜÙ\Xœ˜\WÛ^[İ]ÉÜØÜ›Û	×HHÚY
È‹
ÚYXœ˜\WÛ^[İ]
BˆYˆÚYOHÎL‚ˆ\ÜÙ\Xœ˜\WÛ^[İ]Éİ[\]PÛÛ[[œÉ×HOHˆ[™Xœ˜\WÛ^[İ]ÉÙ[]RZYÚ	×HHËXœ˜\WÛ^[İ]ˆYÙKœÙ]İšY]ÜÜÜÚ^™JÉİÚY	ÎˆM	ÚZYÚ	ÎˆLJBˆYÙK™]˜[X]JˆˆŠ
HOˆÂˆ[\]\Ñ]O]Ú[™İË—×Ú\ÜİYMNU[\]\ÎÜÚÜ]O]Ú[™İË—×Ú\ÜİYMNTÚÜÂˆ[]HÚ[™İË—×Ú\ÜİYMNU[\]\ÎÙ[]HÚ[™İË—×Ú\ÜİYMNTÚÜÂˆØš™Xİ˜\ÜÚYÛŠ™[™]Ø[YZ[“Xœ˜\UÛÜšÜÜXÙKœİ]KÜ]Y\N‰ÉËØ]YÛÜN‰ùaj:`ê	Ë[Ù[‰ÉËİ[N‰ÉË\N‰Ø[	ßJNÂˆİ\œ™[Iùaj:`ê	ÎÜ™[™\•[\]UXœÊ
NÜ™[™\•[\]\Ê
NÂˆHˆˆŠBˆš[
	ĞQRS—ÕSTUWÓP”T–WÑ’ST”×ÔPÑRÓT—Ô‘TÔÓ”ÒU‘WÓÒÉÊB‚ˆYÙK™]˜[X]JŠ
HOˆÚ[™İË˜™[™]Ø[‘[œİ\™U[\]QY]ÜŠ
HŠBˆXYÈHYÙK™]˜[X]JˆˆŠ
HOˆ
ØÛÜ™NˆH]Ú[™İË™[™]Ø[ZT™[[İ™UŒ‹YZ[\[ÙˆÚ[™İË˜™YZ[”™[[İ™P˜XÚÙÜ›İ[™İXÚÔ™XYNˆH]Ú[™İË—×Ø™[™]Ø[•[\]TİXÚÔ™XYKYZ[‘›YÎˆH]Ú[™İË—×Ø™YZ[ZT™[[İ™SÛ›UŒ‹[Ù[ÎŠÚÜ]OË›[Ù[ß×JK›[™İJHˆˆŠBˆš[
	ĞQRS—ÔÕPÒ×ÑPQÉËXYÊBˆ\ÜÙ\XYÖÉØÛÜ™I×H[™XYÖÉØYZ[‰×OOIÙ[˜İ[Û‰È[™XYÖÉÜİXÚÔ™XYI×H[™XYÖÉØYZ[‘›YÉ×H[™XYÖÉÛ[Ù[É×HˆXYÂ‚ˆ[\]WŞÜÈH[\]IÊNİÚ[™İË—×ØYZ[”İÜ™YÜÏLËËÈ‚ˆ[\]WŞÜ×Ü™\İ[HYÙK™]˜[X]Jˆˆœ^[ØYOˆÂˆÛÛœİÜšYÚ[˜[]O\İXİ\™YÛÛ™J[\]\Ñ]JKÜšYÚ[˜[Ü[]Ú[™İË›Ü[•[\]QY]ÜÂˆÚ[™İË—×ØYZ[”İÜ™YÜÏLİÚ[™İË—×ØYZ[‘Y]Y[\]OIÉÎÂˆÚ[™İË›Ü[•[\]QY]Ü]˜[YOOİÚ[™İË—×ØYZ[‘Y]Y[\]O]˜[Y_NÂˆ[\]\Ñ]K[\]\ÏVŞÚYœ^[ØY˜[YN‰ùk¢yaj9ª(y§oÉËØ]YÛÜN‰ùá¬ze 	Ë[Ù[ÚY‰Ê‰Ë[š]™\œØ[Y_WNÂˆİ\œ™[Iùaj:`ê	ÎÜ™[™\•[\]\Ê
NÂˆÛÛœİ[›[™R[™\œÏYØİ[Y[œ]Y\TÙ[XİÜ[
	Èİ[\]KYÜšYÛÛ˜ÛXÚ×IÊK›[™İÂˆØİ[Y[œ]Y\TÙ[XİÜŠ	Èİ[\]KYÜšYÙ]KYY]][\]WIÊK˜ÛXÚÊ
NÂˆÛÛœİ™\İ[^Ù^Xİ]YÚ[™İË—×ØYZ[”İÜ™YÜËY]YÚ[™İË—×ØYZ[‘Y]Y[\]K[›[™R[™\œßNÂˆÚ[™İË›Ü[•[\]QY]Ü[ÜšYÚ[˜[Ü[İ[\]\Ñ]O[ÜšYÚ[˜[]NÜ™[™\•[\]\Ê
NÂˆ™]\›ˆ™\İ[ÂˆHˆˆ‹[\]WŞÜÊBˆ\ÜÙ\[\]WŞÜ×Ü™\İ[OHÉÙ^Xİ]Y	Îˆ	ÙY]Y	Îˆ[\]WŞÜË	Ú[›[™R[™\œÉÎˆK[\]WŞÜ×Ü™\İ[ˆš[
	ĞQRS—ÕSTUWÔÕÔ‘QÑUWĞPÕSÓ”×ÓÒÉÊB‚ˆ[\]WÙš^\™WÜ›Ùš[HHYÙK™]˜[X]JˆˆŠ
HOˆÂˆÛÛœİ[Ù[ÏJÚÜ]OË›[Ù[ß×JK™š[\Š][OOš][OËœİ]\ÈOOY˜[ÙJNÂˆÛÛœİİ[\ÏJÚÜ]OËœİ[\ß×JK™š[\Š][OOš][OËœİ]\ÈOOY˜[ÙJNÂˆYŠ[[Ù[Ë›[™İ\İ[\Ë›[™İ
\™]\›ˆ[Âˆ›ÜŠÛÛœİ[Ù[Ùˆ[Ù[Ê^Âˆ[Ù[˜Ø\ÙWÜ›Ùš[\Ï^Ë‹‹Š[Ù[˜Ø\ÙWÜ›Ùš[\ßßJ_NÂˆ›ÜŠÛÛœİİ[HÙˆİ[\Ê^ÂˆYŠ]Ú[™İË™[™]Ø[Ø\ÙT›Ùš[\ÏË˜ÛÛ\]J[Ù[˜Ø\ÙWÜ›Ùš[\ÖÜİ[KšYJJ^Âˆ[Ù[˜Ø\ÙWÜ›Ùš[\ÖÜİ[KšYO^Âˆ™]šY]×ÛX\Ú×Ú[YÎ›[Ù[œ™]šY]×ÛX\Ú×Ú[Yß	Ùš^\™N‹Ëİ[\]K\™]šY]ÉËˆš[Û[™WÚ[YÎ›[Ù[œš[Û[™WÚ[Yß	Ùš^\™N‹Ëİ[\]K\š[	Ëˆš[ŞŒKš[ŞNŒ‹š[İÎÌš[ÚŒMš[Ø[™ÛNŒˆNÂˆBˆBˆBˆ™]\›ˆÛ[Ù[Î›[Ù[Ë›[™İİ[\Îœİ[\Ë›[™İNÂˆHˆˆŠBˆ\ÜÙ\[\]WÙš^\™WÜ›Ùš[K[\]WÙš^\™WÜ›Ùš[BˆYÙK›ØØ]ÜŠ	ÈİšY]Ë][\]\È]X˜\ˆ˜‰ÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	İ[\]K[[Ù[	ÊOË˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊH‹[Y[İ]LÌ
Bˆ[\]WÛÜ[—ÙXYÈHYÙK™]˜[X]JˆˆŠ
HOˆ
ØØ[˜\ÎˆH]š\İX[Ø[˜\Ë[Ù[™Øİ[Y[™Ù][[Y[RY
	İ[[Ù[	ÊOË˜[YKİ[N™Øİ[Y[™Ù][[Y[RY
	İ\İ[IÊOË˜[YK›Ùš[NˆH]Ú[™İË˜™[™]Ø[•[\]T™Y™\™[˜ÙT›Ùš[OËŠ
KX[ÙÜÎÚ[™İË—×İ[\]SÜ[‘X[ÙÜß×_JHˆˆŠBˆš[
	ĞQRS—ÕSTUWÓÔS—ÑPQÉË[\]WÛÜ[—ÙXYÊBˆ\ÜÙ\[\]WÛÜ[—ÙXYÖÉØØ[˜\É×K[\]WÛÜ[—ÙXYÂˆ[\]WÙY]Ü—ÜÜ˜ÈHYÙK›ØØ]ÜŠ	ÜØÜš\ÜÜ˜ÊH˜YZ[‹][\]KYY]Ü‹]Œ‹šœÈ—IÊK™Ù]Ø]šX]J	ÜÜ˜ÉÊBˆ\ÜÙ\[\]WÙY]Ü—ÜÜ˜È[™	İLŒŒL\İ[LIÈ[ˆ[\]WÙY]Ü—ÜÜ˜Ë[\]WÙY]Ü—ÜÜ˜Âˆš[
	ĞQRS—ÑP”’P×ÓV–WÓÒÉÊB‚ˆ[\]WØÛÛ˜XİHYÙK™]˜[X]Jˆˆ˜\Ş[˜È

HOˆÂˆÛÛœİÜšYÚ[˜[ÚÜ\İXİ\™YÛÛ™JÚÜ]JKÜšYÚ[˜[[\]\Ï\İXİ\™YÛÛ™J[\]\Ñ]JKÜšYÚ[˜[Ø]™O]Ú[™İËœØ]™U[\]\ËÜšYÚ[˜[\ØY]Ú[™İË\ØYYZ[’[XYÙNÂˆÛÛœİ[Ù[^ÚY‰ÙÙ[ÛY]K[[Ù[	Ë˜[YN‰ùno¹/eyg¢ú&gÉËœ˜[™‰Ğ\IËİ]\ÎYKØ\ÙWÜ›Ùš[\ÎÂˆÜ\İ[Ü™]šY]×ÛX\Ú×Ú[YÎ‰Ùš^\™N‹ËØÜ\İ[\™]šY]ÉËš[Û[™WÚ[YÎ‰Ùš^\™N‹ËØÜ\İ[\š[	Ëš[İÎÌš[ÚŒMš[ŞŒKš[ŞNŒ‹š[Ø[™ÛNŒKˆZ\œ›ÜÜ™]šY]×ÛX\Ú×Ú[YÎ‰Ùš^\™N‹ËÛZ\œ›Ü‹\™]šY]ÉËš[Û[™WÚ[YÎ‰Ùš^\™N‹ËÛZ\œ›Ü‹\š[	Ëš[İÎÍKš[ÚŒMLš[ŞŒËš[ŞNš[Ø[™ÛNLBˆ_NÂˆÚÜ]O^Øœ˜[™Î–ÉĞ\I×K[Ù[Î–Û[Ù[Kİ[\Î–ŞÚY‰ØÜ\İ[	Ë˜[YN‰ù¦m¹ojIËİ]\ÎY_KÚY‰ÛZ\œ›Ü‰Ë˜[YN‰úcèzgh‰Ëİ]\ÎY_KÚY‰ÛZ\ÜÚ[™ÉË˜[YN‰ù§*ºacyïk‰Ëİ]\ÎY_W_NÂˆÛÛœİ[Ù[Ù[XİYØİ[Y[™Ù][[Y[RY
	İ[[Ù[	ÊKİ[TÙ[XİYØİ[Y[™Ù][[Y[RY
	İ\İ[IÊNÂˆ[Ù[Ù[Xİš[›™\’SIÏÜ[Ûˆ˜[YOH™Ù[ÛY]K[[Ù[¹no¹/eyg¢ú&gÏÛÜ[Û‰ÎÛ[Ù[Ù[Xİ˜[YOIÙÙ[ÛY]K[[Ù[	ÎÂˆİ[TÙ[Xİš[›™\’SIÏÜ[Ûˆ˜[YOH˜Ü\İ[¹¦m¹ojOÛÜ[ÛÜ[Ûˆ˜[YOH›Z\œ›ÜˆºcèzghÛÜ[ÛÜ[Ûˆ˜[YOH›Z\ÜÚ[™È¹§*ºacyïkÛÜ[Û‰ÎÂˆÚ[™İË—×Ø™‘Y][™Õ[\]O[[Âˆİ[TÙ[Xİ˜[YOIØÜ\İ[	ÎÚ[š]Y]ÜŠ
NØÛÛœİÜ\İ[^İÎËNÂˆİ[TÙ[Xİ˜[YOIÛZ\œ›Ü‰ÎÚ[š]Y]ÜŠ
NØÛÛœİZ\œ›Ü^İÎËNÂˆÛÛœİ™Y›Ü™SZ\ÜÚ[™Ï^İÎËNÜİ[TÙ[Xİ˜[YOIÛZ\ÜÚ[™ÉÎØÛÛœİZ\ÜÚ[™Ô™\İ[Z[š]Y]ÜŠ
NØÛÛœİY\“Z\ÜÚ[™Ï^İÎËNÂˆÛÛœİÛ^ÚY‰ÛYØXŞK\İ[K][\]IË˜[YN‰ú""¹«¯9«/¹ª(y§oÉËØ]YÛÜN‰ùá¬ze 	Ë[Ù[ÚY‰Ê‰Ë[š]™\œØ[YKØ\ÙWÜİ[WÚY‰ØÜ\İ[	Ë™Y™\™[˜ÙWÛ[Ù[ÚY‰ÙÙ[ÛY]K[[Ù[	ËÛİ\˜ÙWÜš[İÎÌÛİ\˜ÙWÜš[ÚŒMÛİÎ–×KØš™Xİ×ÚœÛÛİ™\œÚ[Û‰ÍKŒËŒ	ËØš™XİÎ–×__NÂˆ[\]\Ñ]O^İ[\]\Î–ÛÛKØ]YÛÜšY\Î–Éùaj:`ê	Ë	ùá¬ze 	×_NİÚ[™İË—×Ø™‘Y][™Õ[\]O[ÛÂˆØİ[Y[™Ù][[Y[RY
	İZY	ÊK˜[YO[ÛšYÙØİ[Y[™Ù][[Y[RY
	İ[˜[YIÊK˜[YO[Û›˜[YNÙØİ[Y[™Ù][[Y[RY
	İXØ]YÛÜIÊK˜[YO[Û˜Ø]YÛÜNÜİ[TÙ[Xİ˜[YOIØÜ\İ[	ÎÚ[š]Y]ÜŠ×KÛ›Øš™Xİ×ÚœÛÛ‹	ÉÊNÂˆ]Ø\\™Y[[İÚ[™İË\ØYYZ[’[XYÙOX\Ş[˜Ê
OO‰ËÜİ]XËİ\ØYËÙÙ[ÛY]K][\]Kœ™ÉÎİÚ[™İËœØ]™U[\]\ÏX\Ş[˜È™^OØØ\\™Y\İXİ\™YÛÛ™J™^
NÜ™]\›ˆİ™\œÚ[Û‰ÙÙ[ÛY]K]™\œÚ[Û‰ß_NÂˆ]ØZ]Ø]™U[\]J
NÂˆÛÛœİØ]™YXØ\\™Y[\]\Ë™š[™
›İÏOœ›İËšYOO[ÛšY
NÂˆÚ[™İËœØ]™U[\]\Ï[ÜšYÚ[˜[Ø]™NİÚ[™İË\ØYYZ[’[XYÙO[ÜšYÚ[˜[\ØYÜÚÜ]O[ÜšYÚ[˜[ÚÜİ[\]\Ñ]O[ÜšYÚ[˜[[\]\ÎİÚ[™İË—×Ø™‘Y][™Õ[\]O[[Âˆ™]\›ˆØÜ\İ[Z\œ›Ü‹™Y›Ü™SZ\ÜÚ[™ËY\“Z\ÜÚ[™ËZ\ÜÚ[™Ô™\İ[Ø]™YØØ\ÙWÜİ[WÚYœØ]™Y˜Ø\ÙWÜİ[WÚY™Y™\™[˜ÙWÜİ[WÚYœØ]™Yœ™Y™\™[˜ÙWÜİ[WÚYÛİ\˜ÙWÜš[İÎœØ]™YœÛİ\˜ÙWÜš[İËÛİ\˜ÙWÜš[ÚœØ]™YœÛİ\˜ÙWÜš[Ú_NÂˆHˆˆŠBˆ\ÜÙ\[\]WØÛÛ˜XİOHÂˆ	ØÜ\İ[	ÎˆÉİÉÎŒM	Ú	ÎŒK	ÛZ\œ›Ü‰ÎˆÉİÉÎŒML	Ú	ÎŒÌKˆ	Ø™Y›Ü™SZ\ÜÚ[™ÉÎˆÉİÉÎŒML	Ú	ÎŒÌK	ØY\“Z\ÜÚ[™ÉÎˆÉİÉÎŒML	Ú	ÎŒÌKˆ	ÛZ\ÜÚ[™Ô™\İ[	Îˆ˜[ÙKˆ	ÜØ]™Y	ÎˆÉØØ\ÙWÜİ[WÚY	Î‰ØÜ\İ[	Ë	Ü™Y™\™[˜ÙWÜİ[WÚY	Î‰ØÜ\İ[	Ë	ÜÛİ\˜ÙWÜš[İÉÎÌ	ÜÛİ\˜ÙWÜš[Ú	ÎŒMKˆK[\]WØÛÛ˜Xİˆ\ÜÙ\[J	ù«i9g¢ú&gùæ¡9«i9«¯9«/¹l&¹§*ºacyïk¹å'ùå(º,áù¥¦IÈ[ˆ\ÙÈ›Üˆ\ÙÈ[ˆX[ÙÜÊKX[ÙÜÂˆš[
	ĞQRS—ÕSTUWÓSÑSÔÕSWÑÑSÓQU–WÓQĞPÖWÔÕSWÓÒÉË[\]WØÛÛ˜Xİ
B‚ˆYÙK›ØØ]ÜŠ	ÈİšY]Ë][\]\È]X˜\ˆ˜‰ÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	İ[\]K[[Ù[	ÊOË˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊH	‰ˆH]š\İX[Ø[˜\È‹[Y[İ]LÌ
B‚ˆ[\]WÜÙ\™\—ÛÜšYÚ[˜[HYÙK™]˜[X]JŠ
HOˆ
Ù]NœİXİ\™YÛÛ™J[\]\Ñ]JK™\œÚ[Û[\]\Õ™\œÚ[ÛŸJHŠBˆ[\]WİÚ[›™\ˆHÛÜK™Y\ÛÜJ[\]WÜÙ\™\—ÛÜšYÚ[˜[ÉÙ]I×JBˆ[\]WİÚ[›™\–Éİ[\]\É×K˜\[™
ÉÚY	Î‰ØØ\Ë][\]KXIË	Û˜[YIÎ‰ĞĞTÈ9ª(y§oÈIË	ØØ]YÛÜIÎ‰ùá¬ze 	Ë	Û[Ù[ÚY	Î‰Ê‰Ë	İ[š]™\œØ[	Î•Y_JBˆ[\]WİÚ[›™\—Ü™\ÜÛœÙHHYÙKœ™\]Y\İœÜİ
˜\ÙH
È	ËØ\KØYZ[‹ÜØ]™Wİ[\]\ÉË]O^Âˆ	Ù]IÎˆ[\]WİÚ[›™\‹	Ù^XİYİ™\œÚ[Û‰Îˆ[\]WÜÙ\™\—ÛÜšYÚ[˜[Éİ™\œÚ[Û‰×KˆJBˆ\ÜÙ\[\]WİÚ[›™\—Ü™\ÜÛœÙKœİ]\ÈOHŒ[\]WİÚ[›™\—Ü™\ÜÛœÙK^

Bˆ[\]WİÚ[›™\—İ™\œÚ[ÛˆH[\]WİÚ[›™\—Ü™\ÜÛœÙKšœÛÛŠ
VÉİ™\œÚ[Û‰×BˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹İ\ØYÚ[XYÙIË[X™H›İ]Nˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹\›ˆ‹Üİ]XËÛX]\šX[ËØØ\Ë[Üœ[‹œ™ÈŸIÊJBˆ[\]WÜİ[WÙX[ÙÈH[ŠX[ÙÜÊBˆYÙK™]˜[X]JˆˆŠ
HOˆÙØİ[Y[™Ù][[Y[RY
	İZY	ÊK˜[YOIÉÎÙØİ[Y[™Ù][[Y[RY
	İ[˜[YIÊK˜[YOIĞĞTÈ9ª(y§oÈ‰ÎÙØİ[Y[™Ù][[Y[RY
	İXØ]YÛÜIÊK˜[YOIùá¬ze 	ßHˆˆŠBˆYÙK™]˜[X]JŠ
HOˆØ]™U[\]J
HŠBˆ[\]WÜİ[HHYÙK™]˜[X]JˆˆŠ
HOˆ
ÂˆÜ[™Øİ[Y[™Ù][[Y[RY
	İ[\]K[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊKˆ[œ]™Øİ[Y[™Ù][[Y[RY
	İ[˜[YIÊK˜[YKˆØØ[[\]\Ñ]K[\]\ËœÛÛYJO›˜[YOOOIĞĞTÈ9ª(y§oÈ‰ÊKˆ™\œÚ[Û[\]\Õ™\œÚ[Û‚ˆJHˆˆŠBˆ\ÜÙ\[\]WÜİ[HOHÉÛÜ[‰Î•YK	Ú[œ]	Î‰ĞĞTÈ9ª(y§oÈ‰Ë	ÛØØ[	Î‘˜[ÙK	İ™\œÚ[Û‰Î[\]WÜÙ\™\—ÛÜšYÚ[˜[Éİ™\œÚ[Û‰×_K[\]WÜİ[BˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹İ\ØYÚ[XYÙIÊBˆ[\]WÜÙ\™\—ØY\ˆHYÙKœ™\]Y\İ™Ù]
˜\ÙH
È	ËØ\Kİ[\]\ÉÊKšœÛÛŠ
Bˆ\ÜÙ\[\]WÜÙ\™\—ØY\–Éİ™\œÚ[Û‰×HOH[\]WİÚ[›™\—İ™\œÚ[Û‚ˆ\ÜÙ\Ü›İÖÉÚY	×H›Üˆ›İÈ[ˆ[\]WÜÙ\™\—ØY\–ÉÙ]I×VÉİ[\]\É×HYˆ›İË™Ù]
	ÚY	ÊH[ˆ
	ØØ\Ë][\]KXIË	ØØ\Ë][\]KX‰ÊWHOHÉØØ\Ë][\]KXI×Bˆ\ÜÙ\[J	ú,áù¥¦ymìº(ªùam¹.å¹b!ºh y¢%º(çyïk¹¦í9¥¬;ï#:*âúaãy¥¬:/"yaiyo£9a£y/ë¹¥.xà ‰È[ˆ\ÙÈ›Üˆ\ÙÈ[ˆX[ÙÜÖİ[\]WÜİ[WÙX[ÙÎ—JKX[ÙÜÖİ[\]WÜİ[WÙX[ÙÎ—BˆYÙK™]˜[X]JŠ
HOˆØY[\]\ÊYJHŠBˆ™[ØYYİ[\]HHYÙK™]˜[X]J™\œÚ[ÛˆOˆ
İ™\œÚ[Û[\]\Õ™\œÚ[Û‹\ĞN[\]\Ñ]K[\]\ËœÛÛYJOšYOOIØØ\Ë][\]KXIÊK[œ]™Øİ[Y[™Ù][[Y[RY
	İ[˜[YIÊK˜[Y_JH‹[\]WİÚ[›™\—İ™\œÚ[ÛŠBˆ\ÜÙ\™[ØYYİ[\]HOHÉİ™\œÚ[Û‰Î[\]WİÚ[›™\—İ™\œÚ[Û‹	Ú\ĞIÎ•YK	Ú[œ]	Î‰ĞĞTÈ9ª(y§oÈ‰ßK™[ØYYİ[\]Bˆ™\İÜ™Yİ[\]\ÈHYÙKœ™\]Y\İœÜİ
˜\ÙH
È	ËØ\KØYZ[‹ÜØ]™Wİ[\]\ÉË]O^Âˆ	Ù]IÎˆ[\]WÜÙ\™\—ÛÜšYÚ[˜[ÉÙ]I×K	Ù^XİYİ™\œÚ[Û‰Îˆ[\]WİÚ[›™\—İ™\œÚ[Û‹ˆJBˆ\ÜÙ\™\İÜ™Yİ[\]\Ëœİ]\ÈOHŒ™\İÜ™Yİ[\]\Ë^

BˆYÙK™]˜[X]JŠ
HOˆØY[\]\ÊYJHŠBˆš[
	ĞQRS—ÕSTUWÔÕSWĞĞT×ÓÒÉÊB‚ˆYÙK™]˜[X]JˆˆŠ
HOˆ™]È›ÛZ\ÙJ
™\ÛÛ™K™Z™Xİ
OOØÛÛœİÏYØİ[Y[˜Ü™X]Q[[Y[
	ØØ[˜\ÉÊNØËÚYLLØËšZYÚLLØÛÛœİÏXË™Ù]ÛÛ^
	Ì™	ÊNÙË™š[İ[OIÈÙ™™‰ÎÙË™š[™Xİ
LL
NÙË™š[İ[OIÈÙMÍIÎÙË™š[™Xİ
M‹MŠNÙ˜XœšXË’[XYÙK™œ›ÛUT“
ËÑ]UT“
	Ú[XYÙKÜ™ÉÊK[YÏOİ^Ú[YËœÙ]
ÛYËÌ‹ÜÌ‹ÜšYÚ[–‰ØÙ[\‰ËÜšYÚ[–N‰ØÙ[\‰ËØØ[V‹ØØ[VNŒKŒK[™ÛNŒLËÜšYÚ[˜[˜[YN‰ØYZ[‹]\İœ™ÉßJNİš\İX[Ø[˜\Ë˜Y
[YÊNİš\İX[Ø[˜\ËœÙ]Xİ]™SØš™Xİ
[YÊNİš\İX[Ø[˜\Ëœ™\]Y\İ™[™\[

NÜ™\ÛÛ™J
_XØ]Ú
J^Ü™Z™Xİ
J__JNßJHˆˆŠBˆ™Y›Ü™HHYÙK™]˜[X]JˆˆŠ
HOˆØÛÛœİÏ]š\İX[Ø[˜\Ë™Ù]Xİ]™SØš™Xİ

NÜ™]\›ˆİÎ›Ë™Ù]ØØ[YÚY

K›Ë™Ù]ØØ[YZYÚ

K›Ë™Ù]Ù[\”Ú[

KN›Ë™Ù]Ù[\”Ú[

KKN›Ë˜[™Û_NßHˆˆŠBˆYÙK™]˜[X]JŠ
HOˆÚ[™İË˜™YZ[”™[[İ™P˜XÚÙÜ›İ[™

HŠBˆY\ˆHYÙK™]˜[X]JˆˆŠ
HOˆØÛÛœİÏ]š\İX[Ø[˜\Ë™Ù]Xİ]™SØš™Xİ

NÜ™]\›ˆØZNˆH[ÏË˜ZP˜XÚÙÜ›İ[™™[[İ™YÎ›ÏË™Ù]ØØ[YÚY

K›ÏË™Ù]ØØ[YZYÚ

K›ÏË™Ù]Ù[\”Ú[

KN›ÏË™Ù]Ù[\”Ú[

KKN›ÏË˜[™ÛKX›XÔÜ˜Î›ÏËœX›XÔÜ˜ß	ÉßNßHˆˆŠBˆ\ÜÙ\Y\–ÉØZI×H\ÈYKY\‚ˆ›ÜˆÈ[ˆ
	İÉË	Ú	Ë	Ş	Ë	ŞIË	ØIÊN‚ˆ\ÜÙ\XœÊY\–Ú×KX™Y›Ü™VÚ×JHÍK
Ë™Y›Ü™KY\ŠBˆ\ÜÙ\Y\–ÉÜX›XÔÜ˜É×KY\‚‚ˆÈ[[YHØ]™U[\]H\ÈH^K[ØYYY]Ü‹]Œˆİ™\œšYKˆ™\šYH]ÂˆÈ^\İ[™ÈØ[™Y]Hİ]KØ\ŞH›İ[™\K[ˆÛİ™\ˆ[]U[\]HÛË‚ˆ[\]WÛÜšYÚ[˜[HYÙK™]˜[X]JŠ
HOˆİXİ\™YÛÛ™J[\]\Ñ]JHŠBˆ[\]WÜØ]™WÜ™\]Y\İÈH×Bˆ[\]Wİ\ØYÈH×BˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹İ\ØYÚ[XYÙIË[X™H›İ]Nˆ
[\]Wİ\ØYË˜\[™
›İ]Kœ™\]Y\İ\›
K›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹\›ˆ‹Üİ]XËİ\ØYËÚ\ÜİYLK][\]Kœ™ÈŸIÊJJBˆYˆØ]™Wİ[\]WÜ™\ÜÛœÙJ›İ]JN‚ˆ[\]WÜØ]™WÜ™\]Y\İË˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆYˆ[Š[\]WÜØ]™WÜ™\]Y\İÊHOHN‚ˆ›İ]K™[š[
İ]\ÏMLËÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\Èˆ™\œ›ÜˆŸIÊBˆ[ÙN‚ˆ[YKœÛY\
ŒMJBˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹™\œÚ[Ûˆˆ›[ØÚË][\]K]™\œÚ[ÛˆŸIÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜØ]™Wİ[\]\ÉËØ]™Wİ[\]WÜ™\ÜÛœÙJBˆYÙK™]˜[X]JˆˆŠ
HOˆÙØİ[Y[™Ù][[Y[RY
	İZY	ÊK˜[YOIÉÎÙØİ[Y[™Ù][[Y[RY
	İ[˜[YIÊK˜[YOIÒ\ÜİYLyª(y§oÉÎÙØİ[Y[™Ù][[Y[RY
	İXØ]YÛÜIÊK˜[YOIÒ\ÜİYLyb!ºhg‰ßHˆˆŠBˆ™Y›Ü™Wİ[\]WØÛİ[HYÙK™]˜[X]JŠ
HOˆ[\]\Ñ]K[\]\Ë›[™İŠBˆ[\]WÙX[Ù×Üİ\H[ŠX[ÙÜÊBˆYÙK™]˜[X]JŠ
HOˆ›ÛZ\ÙK˜[
ÜØ]™U[\]J
KØ]™U[\]J
WJHŠBˆ[\]WÙ˜Z[YHYÙK™]˜[X]JˆˆŠ
HOˆ
ÂˆÛİ[[\]\Ñ]K[\]\Ë™š[\ŠO›˜[YOOOIÒ\ÜİYLyª(y§oÉÊK›[™İˆÜ[™Øİ[Y[™Ù][[Y[RY
	İ[\]K[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊKˆ˜[YN™Øİ[Y[™Ù][[Y[RY
	İ[˜[YIÊK˜[YKˆ\ØX›Y–Ë‹‹™Øİ[Y[œ]Y\TÙ[XİÜ[
	Èİ[\]K[[Ù[›Yˆ˜‰ÊWK™š[™
O˜‹^ÛÛ[š[˜ÛY\Ê	ùa,¹kf	ÊJOË™\ØX›Y˜[ÙBˆJHˆˆŠBˆ\ÜÙ\[Š[\]WÜØ]™WÜ™\]Y\İÊHOHH[™[Š[\]Wİ\ØYÊHOHK
[\]WÜØ]™WÜ™\]Y\İË[\]Wİ\ØYÊBˆ\ÜÙ\[\]WÙ˜Z[YOHÉØÛİ[	ÎŒ	ÛÜ[‰Î•YK	İ˜[YIÎ‰Ò\ÜİYLyª(y§oÉË	Ù\ØX›Y	Î‘˜[Ù_K[\]WÙ˜Z[Yˆ\ÜÙ\[J	ù§#ybæy¦ªù¦`¹á(y¬åy/oùå*;ï#:*âùê#yo£9a£z*i‰È[ˆ\ÙÈ›Üˆ\ÙÈ[ˆX[ÙÜÖİ[\]WÙX[Ù×Üİ\—JKX[ÙÜÖİ[\]WÙX[Ù×Üİ\—BˆYÙK™]˜[X]JŠ
HOˆ›ÛZ\ÙK˜[
ÜØ]™U[\]J
KØ]™U[\]J
WJHŠBˆ[\]WÜØ]™YHYÙK™]˜[X]JˆˆŠ
HOˆ
Âˆİ[[\]\Ñ]K[\]\Ë›[™İˆÛİ[[\]\Ñ]K[\]\Ë™š[\ŠO›˜[YOOOIÒ\ÜİYLyª(y§oÉÊK›[™İˆÜ[™Øİ[Y[™Ù][[Y[RY
	İ[\]K[[Ù[	ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊBˆJHˆˆŠBˆ\ÜÙ\[Š[\]WÜØ]™WÜ™\]Y\İÊHOHˆ[™[Š[\]Wİ\ØYÊHOH‹
[\]WÜØ]™WÜ™\]Y\İË[\]Wİ\ØYÊBˆ\ÜÙ\[\]WÜØ]™YOHÉİİ[	Î˜™Y›Ü™Wİ[\]WØÛİ[
ÌK	ØÛİ[	ÎŒK	ÛÜ[‰Î‘˜[Ù_K[\]WÜØ]™YˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹İ\ØYÚ[XYÙIÊBˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜØ]™Wİ[\]\ÉÊB‚ˆ[]WÜ™\]Y\İÈH×BˆYÙK™]˜[X]Jˆˆ™]HOˆİ[\]\Ñ]O\İXİ\™YÛÛ™J]JNİ[\]\Ñ]K[\]\Ëœ\Ú
ÚY‰Ú\ÜİYLKY[]K][\]IË˜[YN‰Ò\ÜİYLyb*ºfi9ª(y§oÉËØ]YÛÜN‰ùá¬ze 	ßJNÜ™[™\•[\]UXœÊ
NÜ™[™\•[\]\Ê
NİÚ[™İË—×Ú\ÜİYLPÛÛ™š\›O]Ú[™İË˜ÛÛ™š\›NİÚ[™İË˜ÛÛ™š\›OJ
OOY_Hˆˆ‹[\]WÛÜšYÚ[˜[
BˆYˆ[]Wİ[\]WÜ™\ÜÛœÙJ›İ]JN‚ˆ[]WÜ™\]Y\İË˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆYˆ[Š[]WÜ™\]Y\İÊHOHN‚ˆ›İ]K™[š[
İ]\ÏMLËÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\Èˆ™\œ›ÜˆŸIÊBˆ[ÙN‚ˆ[YKœÛY\
ŒMJBˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹™\œÚ[Ûˆˆ›[ØÚË][\]KY[]K]™\œÚ[ÛˆŸIÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜØ]™Wİ[\]\ÉË[]Wİ[\]WÜ™\ÜÛœÙJBˆYÙK™]˜[X]JŠ
HOˆ›ÛZ\ÙK˜[
Ù[]U[\]J	Ú\ÜİYLKY[]K][\]IÊK[]U[\]J	Ú\ÜİYLKY[]K][\]IÊWJHŠBˆ[]WÙ˜Z[YHYÙK™]˜[X]JŠ
HOˆ[\]\Ñ]K[\]\Ë™š[\ŠOšYOOIÚ\ÜİYLKY[]K][\]IÊK›[™İOOLH	‰ˆØİ[Y[™Ù][[Y[RY
	İ[\]KYÜšY	ÊK^ÛÛ[š[˜ÛY\Ê	Ò\ÜİYLyb*ºfi9ª(y§oÉÊH	‰ˆ][\]Q[]P\ŞHŠBˆ\ÜÙ\[Š[]WÜ™\]Y\İÊHOHH[™[]WÙ˜Z[Y
[]WÜ™\]Y\İË[]WÙ˜Z[Y
Bˆ\ÜÙ\	ù§#ybæy¦ªù¦`¹á(y¬åy/oùå*;ï#:*âùê#yo£9a£z*i‰È[ˆYÙK›ØØ]ÜŠ	ÈØ™‹\›ÙXİ[Y\ÜØYÙIÊKš[›™\—İ^

BˆYÙK™]˜[X]JŠ
HOˆ›ÛZ\ÙK˜[
Ù[]U[\]J	Ú\ÜİYLKY[]K][\]IÊK[]U[\]J	Ú\ÜİYLKY[]K][\]IÊWJHŠBˆ[]WÜØ]™YHYÙK™]˜[X]JŠ
HOˆ][\]\Ñ]K[\]\ËœÛÛYJOšYOOIÚ\ÜİYLKY[]K][\]IÊH	‰ˆ][\]Q[]P\ŞHŠBˆ\ÜÙ\[Š[]WÜ™\]Y\İÊHOHˆ[™[]WÜØ]™Y
[]WÜ™\]Y\İË[]WÜØ]™Y
BˆYÙK[œ›İ]J	ÊŠ‹Ø\KØYZ[‹ÜØ]™Wİ[\]\ÉÊBˆYÙK™]˜[X]J˜\Ş[˜È

HOˆØ]ØZ]ØY[\]\ÊYJNİÚ[™İË˜ÛÛ™š\›O]Ú[™İË—×Ú\ÜİYLPÛÛ™š\›NÙ[]HÚ[™İË—×Ú\ÜİYLPÛÛ™š\›_HŠBˆš[
	ĞQRS—ÕSTUWĞÔ•QÔÕUWÔ‘U–WÑÕP“WÔÕP“RUÓÒÉÊBˆš[
	ĞQRS—ÕÑP’ÒUÓÒÉÊBˆYÙK˜ÛÜÙJ
B‚‚™Yˆ\˜X›WÜ™XÙZ\İ\İ
^]ÜšYÚ˜\ÙJN‚ˆˆˆ”\œÚ\İH™X[ÛÛ[Z]Y™\]Y\İXÜ›ÜÜÈXˆÛÜÙHS‘œ›İÜÙ\ˆ™\İ\ˆˆˆ‚ˆ[™Ú[™HHÙ]]Š^]ÜšYÚÜË™[š\›Û‹™Ù]
	Ğ”“ÕÔÑT—ÑS‘ÒS‘IË	İÙXšÚ]	ÊJBˆYˆYZ[ŠÛÛ^
N‚ˆYÙHHÛÛ^›™]×ÜYÙJ
BˆYÙK™ÛİÊ˜\ÙH
È	ËÛÙÚ[‰ËØZ]İ[[IÙÛXÛÛ[ØYY	ÊBˆYˆ	ËØYZ[‰È›İ[ˆYÙK\›‚ˆYˆ›İYÙK›ØØ]ÜŠ	ÈÜ\ÜİÛÜ™Y›Ü›IÊKš\×İš\ÚX›J
N‚ˆYÙK›ØØ]ÜŠ	ÈÜ\ÜİÛÜ™]ÙÙÛIÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	Ú[œ]Û˜[YOHœ\ÜİÛÜ™—IÊK™š[
	Ù˜[ŒLŒÉÊBˆYÙK›ØØ]ÜŠ	Ø]Û–İ\OHœİX›Z]—K[œ]İ\OHœİX›Z]—IÊK™š\œİ˜ÛXÚÊ
BˆYÙKØZ]Ù›Ü—İ\›
	ÊŠ‹ØYZ[‰ÊBˆÛ
YÙKŠ
HOˆH]Ú[™İË™[™]Ø[ÛÛ[Y\˜ÙHŠBˆYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏH˜ÛÛ[Y\˜ÙH—IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆÚ[™İË™[™]Ø[ÛÛ[Y\˜ÙKœİ]KœÚİ\Ë›[™İŒŠBˆYÙK›ØØ]ÜŠ	ÖÙ]K]XHœİØÚÈ—IÊK˜ÛXÚÊ
Bˆ™]\›ˆYÙBˆÚ][\š[K•[\Ü˜\Q\™XİÜJ
H\È›Ùš[N‚ˆ›ÜˆÚ[™[ˆ
	Ü\˜Ú\ÙIË	Ù^[œÙIÊN‚ˆÛÛ^H[™Ú[™K›][˜ÚÜ\œÚ\İ[ØÛÛ^
›Ùš[KXY\ÜÏUYJBˆN‚ˆYÙHHYZ[ŠÛÛ^
Bˆ™Y›Ü™HH\Û[Ù[K˜ÛÛ[Y\˜ÙKœ™XY

BˆÚİHH™Y›Ü™VÉÜÚİ\É×VÌBˆ\›H	ËØ\KØYZ[‹Ü\˜Ú\ÙWÜ™XÙZ]™Y	ÈYˆÚ[™OH	Ü\˜Ú\ÙIÈ[ÙH	ËØ\KØYZ[‹Ù^[œÙIÂˆÙ[H×BˆYˆÜÙWÜ™\ÜÛœÙJ›İ]JN‚ˆÙ[˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆ\ÜÙ\›İ]K™™]Ú

Kœİ]\ÈOHŒˆ›İ]K˜X›Ü
	Ù˜Z[Y	ÊBˆÛÛ^œ›İ]J	ÊŠ‰È
È\›ÜÙWÜ™\ÜÛœÙJBˆYˆÚ[™OH	Ü\˜Ú\ÙIÎ‚ˆYÙK›ØØ]ÜŠ	ÖÙ]K\ÚİOH‰ÊÜÚİVÉÚY	×JÉÈ—HÙ]K\™XÙZ]™WIÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈÜÜË\™XÙZ]™K\]IÊK™š[
	ÌÉÊBˆYÙK›ØØ]ÜŠ	ÈÜÜËYX[ÙË\İX›Z]	ÊK˜ÛXÚÊ
Bˆ[ÙN‚ˆYÙK›ØØ]ÜŠ	ÖÙ]K]XH™^[œÙ\È—IÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÈÜÜËY^[œÙKX[[İ[	ÊK™š[
	ÌÍËIÊBˆYÙK›ØØ]ÜŠ	ÈÜÜËY^[œÙK[›İIÊK™š[
	Ù\˜X›H™\İ\™XÙZ\	ÊBˆYÙK›ØØ]ÜŠ	ÈÜÜËY^[œÙK\Ø]™IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	ÜÜË[Y\ÜØYÙIÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	Ù\œ›Ü‰ÊHŠBˆØ]™YHYÙK™]˜[X]JŠ
HOˆ”ÓÓ‹œ\œÙJØØ[İÜ˜YÙK™Ù]][J	Ø™‹\ÜÌ‹\[™[™ÉÊJHŠBˆ\ÜÙ\Ø]™YÉØ›ÙI×HOHÙ[ÌBˆÈ^\İ[™ËÛ™]ÈXœÈÙYHHØ[YH™XÙZ\[™Ø[››İ™\XÙH]‚ˆİ\ˆHYZ[ŠÛÛ^
Bˆ\ÜÙ\İ\‹›ØØ]ÜŠ	ÈÜÜË\[™[™ÉÊKš\×İš\ÚX›J
Bˆİ\‹›ØØ]ÜŠ	ÖÙ]K]XH™^[œÙ\È—IÊK˜ÛXÚÊ
Bˆİ\‹›ØØ]ÜŠ	ÈÜÜËY^[œÙKX[[İ[	ÊK™š[
	ÎNNIÊBˆİ\‹›ØØ]ÜŠ	ÈÜÜËY^[œÙK\Ø]™IÊK˜ÛXÚÊ
BˆÛ
İ\‹Š
HOˆØİ[Y[™Ù][[Y[RY
	ÜÜË[Y\ÜØYÙIÊK^ÛÛ[š[˜ÛY\Ê	ù§*º` yaî‰ÊHŠBˆ\ÜÙ\İ\‹™]˜[X]JŠ
HOˆ”ÓÓ‹œ\œÙJØØ[İÜ˜YÙK™Ù]][J	Ø™‹\ÜÌ‹\[™[™ÉÊJHŠHOHØ]™YˆYÙK˜ÛÜÙJ
Bˆİ\‹˜ÛÜÙJ
Bˆš[˜[N‚ˆÛÛ^˜ÛÜÙJ
HÈ^]Èœ›İÜÙ\È™]Z[ˆÛ›HHÛ‹Y\ÚÈ›Ùš[BˆÛÛ^H[™Ú[™K›][˜ÚÜ\œÚ\İ[ØÛÛ^
›Ùš[KXY\ÜÏUYJBˆN‚ˆYÙHHYZ[ŠÛÛ^
Bˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜÜË\[™[™ÉÊKš\×İš\ÚX›J
Bˆ\ÜÙ\YÙK™]˜[X]JŠ
HOˆ”ÓÓ‹œ\œÙJØØ[İÜ˜YÙK™Ù]][J	Ø™‹\ÜÌ‹\[™[™ÉÊJHŠHOHØ]™YˆÈ^\™Y]][XØ][Ûˆ]\İ›İ\ØØ\™[ˆ[˜Ù\Z[ˆ™XÙZ\‚ˆÛÛ^œ›İ]J	ÊŠ‰Êİ\›[X™H›İ]Nˆ›İ]K™[š[
İ]\ÏMKÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\Èˆ™\œ›Üˆ‹›\ÙÈˆ›ÙÚ[ˆ™\]Z\™YŸIÊJBˆYÙK›ØØ]ÜŠ	ÈÜÜË\™]IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[™Ù][[Y[RY
	ÜÜË[Y\ÜØYÙIÊK^ÛÛ[OOIÛÙÚ[ˆ™\]Z\™Y	ÈŠBˆ\ÜÙ\YÙK™]˜[X]JŠ
HOˆ”ÓÓ‹œ\œÙJØØ[İÜ˜YÙK™Ù]][J	Ø™‹\ÜÌ‹\[™[™ÉÊJHŠHOHØ]™YˆÛÛ^[œ›İ]J	ÊŠ‰Êİ\›
BˆYˆ™]J›İ]JN‚ˆÙ[˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆ›İ]K˜ÛÛ[YWÊ
BˆÛÛ^œ›İ]J	ÊŠ‰Êİ\›™]JBˆØœÙ\™\ˆHYZ[ŠÛÛ^
Bˆ\ÜÙ\ØœÙ\™\‹›ØØ]ÜŠ	ÈÜÜË\[™[™ÉÊKš\×İš\ÚX›J
BˆYÙK›ØØ]ÜŠ	ÈÜÜË\™]IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆ[ØØ[İÜ˜YÙK™Ù]][J	Ø™‹\ÜÌ‹\[™[™ÉÊHŠBˆÛ
ØœÙ\™\‹Š
HOˆØİ[Y[™Ù][[Y[RY
	ÜÜË\[™[™ÉÊKšY[ˆŠBˆ\ÜÙ\[ŠÙ[
HOHˆ[™Ù[ÌHOHÙ[ÌWKÙ[ˆY\ˆH\Û[Ù[K˜ÛÛ[Y\˜ÙKœ™XY

BˆYˆÚ[™OH	Ü\˜Ú\ÙIÎ‚ˆ\ÜÙ\Y\–ÉÜÚİ\É×VÌVÉÜİØÚ×Ü]I×HOHÚİVÉÜİØÚ×Ü]I×H
ÈÂˆ[šY\ÈHŞ›Üˆ[ˆY\–ÉÚ[™[ÜWÛYÙ\‰×HYˆ™Ù]
	Ü™XÙZ\ÚY	ÊHOHØ]™YÉØ›ÙI×VÉÚY[\İ[˜ŞWÚÙ^I×WBˆ\ÜÙ\[Š[šY\ÊHOHBˆ[ÙN‚ˆ\ÜÙ\[ŠY\–ÉÙ^[œÙ\É×JHOH[Š™Y›Ü™VÉÙ^[œÙ\É×JH
ÈBˆ[šY\ÈHŞ›Üˆ[ˆY\–ÉÙ^[œÙWÛYÙ\‰×HYˆÉÚY	×HOHØ]™YÉØ›ÙI×VÉÚY[\İ[˜ŞWÚÙ^I×WBˆ\ÜÙ\[Š[šY\ÊHOHBˆš[
	ÑTP“WÔ‘PÑRTĞ”“ÕÔÑT—Ô‘TÕT•ÓÒÉËÚ[™
Bˆš[˜[N‚ˆÛÛ^˜ÛÜÙJ
B‚‚™Yˆ\ÜÚÙ^WÛÙÚ[—İ\İ
œ›İÜÙ\‹˜\ÙJN‚ˆ[ØÚÈHˆˆŠ

HOˆÂˆÚ[™İË”X›XÒÙ^PÜ™Y[X[Y[˜İ[ÛŠ
^ßNİÚ[™İË—×Ü\ÜÚÙ^QÙ]Ø[ÏLİÚ[™İË—×Ü\ÜÚÙ^S[ÙOIÜİXØÙ\ÜÉÎÂˆØš™Xİ™Yš[™T›Ü\J˜]šYØ]Ü‹	ØÜ™Y[X[ÉËØÛÛ™šYİ\˜X›NYK˜[YNÂˆÜ™X]N˜\Ş[˜Ê
OO›[ˆÙ]˜\Ş[˜Ê
OOİÚ[™İË—×Ü\ÜÚÙ^QÙ]Ø[ÊÊÎÚYŠÚ[™İË—×Ü\ÜÚÙ^S[ÙOOOIØØ[˜Ù[	Ê]›İÈ™]ÈÓQ^Ù\[ÛŠ	ØØ[˜Ù[Y	Ë	Ó›İ[İÙY\œ›Ü‰ÊNÜ™]\›ˆÚY‰Û[ØÚË[ÙÚ[‹XÜ™Y[X[	Ë˜]ÒY›™]ÈZ[\œ˜^JÌ—JK˜Y™™\‹\N‰ÜX›XËZÙ^IË]][XØ]Ü]XÚY[‰Ü]›Ü›IËÙ]ÛY[^[œÚ[Û”™\İ[ÎŠ
OOŠßJK™\ÜÛœÙNØÛY[]R”ÓÓ›™]ÈZ[\œ˜^JÌ×JK˜Y™™\‹]][XØ]Ü‘]N›™]ÈZ[\œ˜^JÍJK˜Y™™\‹ÚYÛ˜]\™N›™]ÈZ[\œ˜^JÍWJK˜Y™™\‹\Ù\’[™N›[__Bˆ_JNÂˆJJ
Hˆˆ‚ˆYÙHHœ›İÜÙ\‹›™]×ÜYÙJšY]ÜÜ^ÉİÚY	ÎˆÎL	ÚZYÚ	ÎˆJBˆYÙK˜YÚ[š]ÜØÜš\
[ØÚÊBˆ™\šYHH×BˆYÙKœ›İ]J	ÊŠ‹Ø\KØ]]Ü\ÜÚÙ^KÜİ]\ÉË[X™H›İ]Nˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹˜ÛÛ™šYİ\™YYKš\×ØÜ™Y[X[ÈY_IÊJBˆYÙKœ›İ]J	ÊŠ‹Ø\KØ]]Ü\ÜÚÙ^KÛÜ[ÛœÉË[X™H›İ]Nˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹˜Ù\™[[ÛWÚYˆ›[ØÚË[ÙÚ[ˆ‹œX›XÒÙ^HÈ˜Ú[[™ÙHˆTH‹œœYˆŒLËŒŒŒH‹˜[İĞÜ™Y[X[È–ŞÈ\HˆœX›XËZÙ^H‹šYˆYÈŸWK\Ù\•™\šYšXØ][Ûˆˆœ™\]Z\™YŸ_IÊJBˆYˆ™\šYWÛÙÚ[Š›İ]JN‚ˆ™\šYK˜\[™
›İ]Kœ™\]Y\İœÜİÙ]WÚœÛÛŠBˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹œ™Y\™Xİˆ‹Ø\KÚX[ŸIÊBˆYÙKœ›İ]J	ÊŠ‹Ø\KØ]]Ü\ÜÚÙ^Kİ™\šYIË™\šYWÛÙÚ[ŠBˆYÙK™ÛİÊ˜\ÙH
È	ËÛÙÚ[‰ËØZ]İ[[IÙÛXÛÛ[ØYY	ÊBˆÛ
YÙKŠ
HOˆYØİ[Y[™Ù][[Y[RY
	Ü\ÜÚÙ^K[ÙÚ[‹X]Û‰ÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÚY[‰ÊHŠBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜ\ÜÚÙ^K[ÙÚ[‹X]Û‰ÊKš[›™\—İ^

HOH	ù/oùå*˜XÙHQ9ænùaiIÂˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜ\ÜÚÙ^K[ÙÚ[‹X]Û‰ÊKš\×İš\ÚX›J
H[™›İYÙK›ØØ]ÜŠ	ÈÜ\ÜİÛÜ™Y›Ü›IÊKš\×İš\ÚX›J
Bˆ\ÜÙ\YÙK™]˜[X]J	Ê
HOˆÚ[™İË—×Ü\ÜÚÙ^QÙ]Ø[ÉÊHOHˆYÙK›ØØ]ÜŠ	ÈÜ\ÜÚÙ^K[ÙÚ[‹X]Û‰ÊK˜ÛXÚÊ
BˆYÙKØZ]Ù›Ü—İ\›
	ÊŠ‹Ø\KÚX[	ÊBˆ\ÜÙ\[Š™\šYJHOHH[™™\šYVÌVÉØÙ\™[[ÛWÚY	×HOH	Û[ØÚË[ÙÚ[‰Âˆ\ÜÙ\™\šYVÌVÉØÜ™Y[X[	×VÉØ]][XØ]Ü]XÚY[	×HOH	Ü]›Ü›IÂˆYÙK˜ÛÜÙJ
B‚ˆØ[˜Ù[YHœ›İÜÙ\‹›™]×ÜYÙJšY]ÜÜ^ÉİÚY	ÎˆÎL	ÚZYÚ	ÎˆJBˆØ[˜Ù[Y˜YÚ[š]ÜØÜš\
[ØÚÊBˆØ[˜Ù[Yœ›İ]J	ÊŠ‹Ø\KØ]]Ü\ÜÚÙ^KÜİ]\ÉË[X™H›İ]Nˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹˜ÛÛ™šYİ\™YYKš\×ØÜ™Y[X[ÈY_IÊJBˆØ[˜Ù[Yœ›İ]J	ÊŠ‹Ø\KØ]]Ü\ÜÚÙ^KÛÜ[ÛœÉË[X™H›İ]Nˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOIŞÈœİ]\ÈˆœİXØÙ\ÜÈ‹˜Ù\™[[ÛWÚYˆ›[ØÚËXØ[˜Ù[‹œX›XÒÙ^HÈ˜Ú[[™ÙHˆTH‹œœYˆŒLËŒŒŒH‹˜[İĞÜ™Y[X[È–×K\Ù\•™\šYšXØ][Ûˆˆœ™\]Z\™YŸ_IÊJBˆØ[˜Ù[Y™ÛİÊ˜\ÙH
È	ËÛÙÚ[‰ËØZ]İ[[IÙÛXÛÛ[ØYY	ÊBˆØ[˜Ù[Y™]˜[X]JŠ
HOˆİÚ[™İË—×Ü\ÜÚÙ^S[ÙOIØØ[˜Ù[	ßHŠBˆØ[˜Ù[Y›ØØ]ÜŠ	ÈÜ\ÜÚÙ^K[ÙÚ[‹X]Û‰ÊK˜ÛXÚÊ
BˆÛ
Ø[˜Ù[YŠ
HOˆØİ[Y[™Ù][[Y[RY
	ÛÙÚ[‹[Y\ÜØYÙIÊK^ÛÛ[š[˜ÛY\Ê	ùmì¹cå¹­¢˜XÙHQ:jeú+bIÊHŠBˆØ[˜Ù[Y›ØØ]ÜŠ	ÈÜ\ÜİÛÜ™]ÙÙÛIÊK˜ÛXÚÊ
Bˆ\ÜÙ\Ø[˜Ù[Y›ØØ]ÜŠ	ÈÜ\ÜİÛÜ™Y›Ü›IÊKš\×İš\ÚX›J
BˆØ[˜Ù[Y˜ÛÜÙJ
B‚ˆ[œİ\ÜYHœ›İÜÙ\‹›™]×ÜYÙJšY]ÜÜ^ÉİÚY	ÎˆÎL	ÚZYÚ	ÎˆJBˆ[œİ\ÜY˜YÚ[š]ÜØÜš\
“Øš™Xİ™Yš[™T›Ü\JÚ[™İË	ÔX›XÒÙ^PÜ™Y[X[	ËØÛÛ™šYİ\˜X›NYK˜[YN[™Yš[™YJHŠBˆ[œİ\ÜY™ÛİÊ˜\ÙH
È	ËÛÙÚ[‰ËØZ]İ[[IÙÛXÛÛ[ØYY	ÊBˆÛ
[œİ\ÜYŠ
HOˆØİ[Y[™Ù][[Y[RY
	Ü\ÜİÛÜ™Y›Ü›IÊK˜Û\ÜÓ\İ˜ÛÛZ[œÊ	ÜÚİÉÊHŠBˆ\ÜÙ\[œİ\ÜY›ØØ]ÜŠ	ÈÜ\ÜİÛÜ™Y›Ü›IÊKš\×İš\ÚX›J
Bˆ\ÜÙ\›İ[œİ\ÜY›ØØ]ÜŠ	ÈÜ\ÜÚÙ^K[ÙÚ[‹X]Û‰ÊKš\×İš\ÚX›J
Bˆ[œİ\ÜY˜ÛÜÙJ
Bˆš[
	ÔTÔÒÑVWÓÑÒS—ÕÑP’ÒUÓÒÉÊB‚‚™YˆÜ™\—Üš[İÛÜšÜÜXÙWİ\İ
œ›İÜÙ\‹˜\ÙKÛ
N‚ˆˆˆ”ˆÍŒˆYÙYÜ™\œË^XİÜ›ÜÜË[˜]šYØ][Û‹šXYÙH[™ØY™HXİ[ÛœËˆˆˆ‚ˆœ›ÛH\›X‹œ\œÙH[\Ü\œÙWÜ\Ë\›Ü]ˆYÙHHœ›İÜÙ\‹›™]×ÜYÙJšY]ÜÜ^ÉİÚY	ÎˆLN	ÚZYÚ	ÎˆLJBˆYÙK™ÛİÊ˜\ÙH
È	ËÛÙÚ[‰ËØZ]İ[[IÙÛXÛÛ[ØYY	ÊBˆYˆ›İYÙK›ØØ]ÜŠ	ÈÜ\ÜİÛÜ™Y›Ü›IÊKš\×İš\ÚX›J
N‚ˆYÙK›ØØ]ÜŠ	ÈÜ\ÜİÛÜ™]ÙÙÛIÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	Ú[œ]Û˜[YOHœ\ÜİÛÜ™—IÊK™š[
	Ù˜[ŒLŒÉÊBˆYÙK›ØØ]ÜŠ	Ø]Û–İ\OHœİX›Z]—IÊK™š\œİ˜ÛXÚÊ
BˆYÙKØZ]Ù›Ü—İ\›
	ÊŠ‹ØYZ[‰ÊBˆİ[\H[
[YK[YJ
JBˆÜ™\œÈHÙXİ
Ü™\—ÚYY‰ÓÔ‘T‹^ÚNŒÙIËİ\İÛY\—Û˜[YOIú  yk¨¹.®‰ÈYˆHOHŒ[ÙH	ùk¨¹.®‰Ëˆ[Ù[IÚTÛ™HLÉËİ[OIù¦m¹ojIË^[Y[ÛY]ÙIùãïºaäIËİ]\ÏIùo¡z&eyä!‰Ëˆ[YO\İ[\ZK\×Üš[UYK\×Û[ØÚİ\Q˜[ÙK]X[]OLKİ[LL
Bˆ›ÜˆH[ˆ˜[™ÙJŒJWBˆÜ™\œÖÌŒ×VÉÜİ]\É×HH	ùmì¹k£9¢$	ÂˆYˆÜ™\—Ü›İ]J›İ]JN‚ˆH\œÙWÜ\Ê\›Ü]
›İ]Kœ™\]Y\İ\›
Kœ]Y\JBˆ›İ[™HÜ™\œÂˆYˆ	ÛÜ™\—ÚY	È[ˆˆ›İ[™HÛÈ›ÜˆÈ[ˆ›İ[™YˆÖÉÛÜ™\—ÚY	×HOHÉÛÜ™\—ÚY	×VÌWBˆYˆ	ÜIÈ[ˆˆ›İ[™HÛÈ›ÜˆÈ[ˆ›İ[™YˆÉÜI×VÌK›İÙ\Š
H[ˆ	È	Ëš›Ú[ŠİŠÖÚ×JH›ÜˆÈ[ˆ
	ÛÜ™\—ÚY	Ë	Øİ\İÛY\—Û˜[YIË	Û[Ù[	Ë	Üİ[IË	Ü^[Y[ÛY]Ù	Ë	Üİ]\ÉÊJK›İÙ\Š
WBˆYˆ	Üİ]\ÉÈ[ˆˆ›İ[™HÛÈ›ÜˆÈ[ˆ›İ[™YˆÖÉÜİ]\É×HOHÉÜİ]\É×VÌWBˆÙ™œÙ]H[
™Ù]
	ÛÙ™œÙ]	ËÉÌ	×JVÌJNÛ[Z]H[
™Ù]
	Û[Z]	ËÉÌŒ	×JVÌJBˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOZœÛÛ‹™[\ÊXİ
İ]\ÏIÜİXØÙ\ÜÉË]OY›İ[™ÛÙ™œÙ]›Ù™œÙ]
Û[Z]K\×Û[Ü™O[[Š›İ[™
O›Ù™œÙ]
Û[Z]™^ÛÙ™œÙ][Z[Š[Š›İ[™
KÙ™œÙ]
Û[Z]
K™Y›Ü™O\İ[\
ÌL
JJBˆš[Ü›İÜÏV×Bˆ›Üˆİ]H[ˆ
	ÕS’Ó“ÕÓ‰Ë	ÑRSQ	Ë	ÔÑS‘S‘ÉË	ĞĞSÑSS‘ÉË	ÔÕT•S‘ÉË	Ô‘TT‘Q	Ë	ÔUQUQQ	Ë	Ô’S•S‘ÉË	ĞÓÓTUQ	ÊN‚ˆš[Ü›İÜË˜\[™
Xİ
Ü™\—ÚYIÔ’S•IÊÜİ]Kİ\İÛY\—Û˜[YOIùk¨¹.®‰Ë[Ù[IÚTÛ™HLÉËİ[OIù¦m¹ojIËÜ™\—Üİ]\ÏIùo¡z&eyä!‰Ë[YO\İ[\ˆ\×Üš[UYK›Ùš[WØ]˜Z[X›OUYKš[™[™×Ü™\]Z\™YQ˜[ÙKÚİWÚYIÔÒÕIË›ØYXİ
YIÒ“Ğ‹IÊÜİ]Kİ]O\İ]Kİ]WÛX™[\İ]K›Ùš[WØÛÛ\]OUYK\İÙ\œ›ÜIúb¬ùcl9fç¹h,yi,y¥eÉÈYˆİ]OOIÑRSQ	È[ÙH	ÉÊJJBˆš[Ü›İÜË˜\[™
Xİ
Ü™\—ÚYIÔ’S•P’S‘	Ëİ\İÛY\—Û˜[YOIùk¨¹.®‰Ë[Ù[IÚTÛ™HLÉËİ[OIù¦m¹ojIËÜ™\—Üİ]\ÏIùo¡z&eyä!‰Ë[YO\İ[\ˆ\×Üš[UYK›Ùš[WØ]˜Z[X›OQ˜[ÙKš[™[™×Ü™\]Z\™YUYKÚİWÚYIÉËYØXŞWÛÜ™\UYKÚİWØØ[™Y]\ÏV×K›ØS›Û™JJBˆYˆš[Ü›İ]J›İ]JN‚ˆH\œÙWÜ\Ê\›Ü]
›İ]Kœ™\]Y\İ\›
Kœ]Y\JBˆ]HHÙXİ
Ü™\—ÚYIÓÔ‘T‹LŒ	Ëİ\İÛY\—Û˜[YOIú  yk¨¹.®‰Ë[Ù[IÚTÛ™HLÉËİ[OIù¦m¹ojIËÜ™\—Üİ]\ÏIùo¡z&eyä!‰Ë[YO\İ[\LŒ\×Üš[UYK›Ùš[WØ]˜Z[X›OUYKš[™[™×Ü™\]Z\™YQ˜[ÙKÚİWÚYIÔÒÕIË›ØS›Û™JWHYˆ™Ù]
	ÛÜ™\—ÚY	ÊHOHÉÓÔ‘T‹LŒ	×H[ÙHš[Ü›İÜÂˆ›İ]K™[š[
İ]\ÏLŒÛÛ[İ\OIØ\XØ][Û‹ÚœÛÛ‰Ë›ÙOZœÛÛ‹™[\ÊXİ
İ]\ÏIÜİXØÙ\ÜÉË›İÜÏY]K™[™Ü—Ü™XYOUYK™[™Ü—ØÛÛ›™XİYUYK]šXÙWÚYIÙš^\™IÊJJBˆ]]][ÛœÏV×BˆYÙK›ÛŠ	Ü™\]Y\İ	Ë[X™H™\]Y\İˆ]]][ÛœË˜\[™
™\]Y\İ\›
HYˆ™\]Y\İ›Y]ÙOH	ÑÑU	È[™	ËØ\KØYZ[‹Üš[ÉÈ[ˆ™\]Y\İ\›[ÙH›Û™JBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹ÙÙ]ÛÜ™\œÏÊ‰ËÜ™\—Ü›İ]JBˆYÙKœ›İ]J	ÊŠ‹Ø\KØYZ[‹Üš[Ú›ØœÏÊ‰Ëš[Ü›İ]JBˆYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏH›Ü™\œÈ—IÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÖÙ]K\˜[™ÙOH˜[—IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜ[
	Ë˜™‹[Ü™\‹XØ\™	ÊK›[™İOOLŒ	‰ˆHYØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K[Ü™\‹[[Ü™WIÊHŠBˆYÙK™]˜[X]JŠ
HOˆÚ[™İË—×Ø™”YÙ\]ÛˆHØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K[Ü™\‹[[Ü™WIÊHŠBˆÈ›Ü›X[Ü\š[ÙXÈ™Yœ™\Ú]\İ™\Ù]YÙHK™]™\ˆ\[™YÙH‹‚ˆYÙK™]˜[X]JŠ
HOˆÚ[™İËœ™Yœ™\ÚÜ™\œÊ
HŠBˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜ[
	Ë˜™‹[Ü™\‹XØ\™	ÊK›[™İOOLŒ	‰ˆHYØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K[Ü™\‹[[Ü™WIÊHŠBˆYÙK™]˜[X]JŠ
HOˆÚ[™İËœ™Yœ™\ÚÜ™\œÊ
HŠBˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜ[
	Ë˜™‹[Ü™\‹XØ\™	ÊK›[™İOOLŒ	‰ˆHYØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K[Ü™\‹[[Ü™WIÊHŠBˆ\ÜÙ\YÙK™]˜[X]JŠ
HOˆÚ[™İË—×Ø™”YÙ\]ÛˆOOHØİ[Y[œ]Y\TÙ[XİÜŠ	ÖÙ]K[Ü™\‹[[Ü™WIÊHŠBˆYÙK›ØØ]ÜŠ	ÖÙ]K[Ü™\‹[[Ü™WIÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜ[
	Ë˜™‹[Ü™\‹XØ\™	ÊK›[™İOOLŒHŠBˆYÙK›ØØ]ÜŠ	ÈØ™‹[Ü™\‹\ÙX\˜Ú	ÊK™š[
	ùmì¹k£9¢$	ÊBˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜ[
	Ë˜™‹[Ü™\‹XØ\™	ÊK›[™İOOLH	‰ˆØİ[Y[œ]Y\TÙ[XİÜŠ	Ë˜™‹[Ü™\‹ZY	ÊK^ÛÛ[š[˜ÛY\Ê	ÓÔ‘T‹LŒÉÊHŠBˆYÙK›ØØ]ÜŠ	ÈØ™‹[Ü™\‹\ÙX\˜Ú	ÊK™š[
	ú  yk¨¹.®‰ÊBˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜ[
	Ë˜™‹[Ü™\‹XØ\™	ÊK›[™İOOLH	‰ˆØİ[Y[œ]Y\TÙ[XİÜŠ	Ë˜™‹[Ü™\‹ZY	ÊK^ÛÛ[š[˜ÛY\Ê	ÓÔ‘T‹LŒ	ÊHŠBˆYÙK›ØØ]ÜŠ	ÖÙ]K[Ü™\‹XXİ[ÛHœš[—IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜŠ	ÈİšY]Ë\š[XÙ[\‹˜Xİ]™HœËXØ\™	ÊOË^ÛÛ[š[˜ÛY\Ê	ÓÔ‘T‹LŒ	ÊHŠBˆ\ÜÙ\	ÛÜ™\—ÚYSÔ‘T‹LŒ	È[ˆYÙK›ØØ]ÜŠ	ÈÜËY^Xİ	ÊKš[›™\—İ^

HÜˆ	ÓÔ‘T‹LŒ	È[ˆYÙK›ØØ]ÜŠ	ÈÜËY^Xİ	ÊKš[›™\—İ^

BˆYÙK›ØØ]ÜŠ	ÖÙ]K\ÏH›Ü™\ˆ—IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜŠ	ÈİšY]Ë[Ü™\œË˜Xİ]™H˜™‹[Ü™\‹XØ\™	ÊOË^ÛÛ[š[˜ÛY\Ê	ÓÔ‘T‹LŒ	ÊHŠBˆYÙK›ØØ]ÜŠ	Ë›˜]ˆ]Û–Ù]K]šY]ÏHœš[XÙ[\ˆ—IÊK˜ÛXÚÊ
BˆYÙK›ØØ]ÜŠ	ÖÙ]K\ÏH˜ÛX\‹Y^Xİ—IÊK˜ÛXÚÊ
BˆÛ
YÙKŠ
HOˆØİ[Y[œ]Y\TÙ[XİÜ[
	ÈÜËYÜšYœËXØ\™	ÊK›[™İOOLLŠBˆ›ÜˆÙ^KÛİ[[ˆÊ	Ù^Ù\[Û‰ËJK
	Ø][[Û‰ËJK
	Ü™\\™Y	ËJK
	Ü]Y]YY	ËJK
	Üš[[™ÉËJK
	ØÛÛ\]Y	ËJWN‚ˆYÙK›ØØ]ÜŠ‰ÖÙ]K]šXYÙOHÚÙ^_H—IÊK˜ÛXÚÊ
Bˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜËYÜšYœËXØ\™	ÊK˜Ûİ[

OOXÛİ[
Ù^KYÙK›ØØ]ÜŠ	ÈÜËYÜšYœËXØ\™	ÊK˜Ûİ[

JBˆYÙK›ØØ]ÜŠ	ÖÙ]K]šXYÙOH˜[—IÊK˜ÛXÚÊ
Bˆ›Üˆİ]H[ˆ
	ÕS’Ó“ÕÓ‰Ë	ÔÑS‘S‘ÉË	ĞĞSÑSS‘ÉÊN‚ˆØ\™\YÙK›ØØ]ÜŠ	ËœËXØ\™	ÊK™š[\Š\Ï\YÙK›ØØ]ÜŠ	ËœËZY	Ë\×İ^IÔ’S•IÊÜİ]JJBˆ\ÜÙ\Ø\™›ØØ]ÜŠ	ÖÙ]K\ÏHœÙ[™—IÊK˜Ûİ[

OOLˆ\ÜÙ\Ø\™›ØØ]ÜŠ	ÖÙ]K\ÏHœ™XÛÛ˜Ú[H—IÊK˜Ûİ[

OOLBˆ\ÜÙ\YÙK›ØØ]ÜŠ	ËœËXØ\™	ÊK™š[\Š\Ï\YÙK›ØØ]ÜŠ	ËœËZY	Ë\×İ^IÔ’S•T’S•S‘ÉÊJK›ØØ]ÜŠ	ÖÙ]K\ÏH˜Ø[˜Ù[—IÊK˜Ûİ[

OOLˆ\ÜÙ\YÙK›ØØ]ÜŠ	ËœËXØ\™	ÊK™š[\Š\Ï\YÙK›ØØ]ÜŠ	ËœËZY	Ë\×İ^IÔ’S•QRSQ	ÊJK›ØØ]ÜŠ	ÖÙ]K\ÏHœÙ[™—IÊK˜Ûİ[

OOLˆ\ÜÙ\]]][ÛœÏOV×K]]][ÛœÂˆ›ÜˆÚYZYÚ[ˆ

ÎL
K
ÍL
K
LNL
JN‚ˆYÙKœÙ]İšY]ÜÜÜÚ^™JXİ
ÚY]ÚYZYÚZZYÚ
JBˆ\ÜÙ\YÙK™]˜[X]J	ÙØİ[Y[™Øİ[Y[[[Y[œØÜ›ÛÚYZ[›™\•ÚY
Ì‰ÊKÚYˆ\ÜÙ\YÙK›ØØ]ÜŠ	ÈÜË]šXYÙIÊK™]˜[X]J	ÊJOO™KœØÜ›ÛÚYYK˜ÛY[ÚY	ÊBˆYÙK˜ÛÜÙJ
B‚‚™YˆXZ[Š
N‚ˆÙ\™\ˆHÙ\™\•™XY

NÜÙ\™\‹œİ\

Nİ[YKœÛY\

BˆN‚ˆÚ]Ş[˜×Ü^]ÜšYÚ

H\È‚ˆœ›İÜÙ\ˆHÙ]]ŠÜË™[š\›Û‹™Ù]
	Ğ”“ÕÔÑT—ÑS‘ÒS‘IË	İÙXšÚ]	ÊJK›][˜Ú

BˆN‚ˆ˜\ÙOY‰Ú‹ËÌLËŒŒŒNĞ”“ÕÔÑT—ÕTÕÔÔ•IÎÜ\ÜÚÙ^WÛÙÚ[—İ\İ
œ›İÜÙ\‹˜\ÙJNÙœ›Ûİ\İ
œ›İÜÙ\‹˜\ÙJNÚÛYWÙ˜YØØ][Ù×Ü˜XÙWİ\İ
œ›İÜÙ\‹˜\ÙJNÙ\ÚYÛ—Ù˜Yİ\İ
œ›İÜÙ\‹˜\ÙJNØÚXÚÛİ]İ\İ
œ›İÜÙ\‹˜\ÙJNØYZ[—İ\İ
œ›İÜÙ\‹˜\ÙJNÛÜ™\—Üš[İÛÜšÜÜXÙWİ\İ
œ›İÜÙ\‹˜\ÙKÛ
Bˆ[\Ü[œBˆ[œKœ[—Ü]
İŠ“ÓÕÈ	Ë™Ú]X‹İ\İËİ\İÜÜ×Ù\Ú›Ø\™œIÊJVÉÙ\Ú›Ø\™İ\İ	×Jœ›İÜÙ\‹˜\ÙKÛ
Bˆ[œKœ[—Ü]
İŠ“ÓÕÈ	Ë™Ú]X‹İ\İËİ\İÛ][˜ÚØXØÙ\[˜ÙKœIÊJVÉÛ][˜ÚØXØÙ\[˜ÙWİ\İ	×Jœ›İÜÙ\‹˜\ÙKÛ
Bˆ[œKœ[—Ü]
İŠ“ÓÕÈ	Ë™Ú]X‹İ\İËİ\İÛ[Ù[ØØ]ÚXÛÛ‹œIÊJVÉÛ[Ù[ØØ]ÚXÛÛ—İ\İ	×Jœ›İÜÙ\‹˜\ÙKÛ
Bˆ[œKœ[—Ü]
İŠ“ÓÕÈ	Ë™Ú]X‹İ\İËİ\İØZWÜ›İšY\—Øœ›İÜÙ\‹œIÊJVÉØZWÜ›İšY\—Øœ›İÜÙ\—İ\İ	×Jœ›İÜÙ\‹˜\ÙKÛ
Bˆ[œKœ[—Ü]
İŠ“ÓÕÈ	Ë™Ú]X‹İ\İËİ\İÙY]X›WÜİXÚÙ\œ×Øœ›İÜÙ\‹œIÊJVÉÙY]X›WÜİXÚÙ\—İ\İ	×Jœ›İÜÙ\‹˜\ÙKÛ
Bˆ[œKœ[—Ü]
İŠ“ÓÕÈ	Ë™Ú]X‹İ\İËİ\İÛ][[^Y\—Øœ›İÜÙ\‹œIÊJVÉÛ][[^Y\—Øœ›İÜÙ\—İ\İ	×Jœ›İÜÙ\‹˜\ÙKÛ
Bˆš[˜[Nˆœ›İÜÙ\‹˜ÛÜÙJ
Bˆ\˜X›WÜ™XÙZ\İ\İ
˜\ÙJBˆš[
	ĞRWÑQUÔ—ÕÑP’ÒUÓÒÉÊBˆš[˜[N‚ˆÙ\™\‹˜ÛÜÙJ
BˆÈHÛÛ[Y\˜ÙH\İ[œÈ[ˆØØ[˜[˜XÚÈ[ÙNÈÙY\ÒHÛÜšÜÜXÙ\ÈÛX[‹‚ˆÛÛ[Y\˜ÙHH“ÓÕÈ	ØÛÛ[Y\˜ÙWÙ]KšœÛÛ‰ÂˆYˆÛÛ[Y\˜ÙK™^\İÊ
N‚ˆNˆÛÛ[Y\˜ÙK[›[šÊ
Bˆ^Ù\^Ù\[Ûˆ\ÜÂ‚‚šYˆ×Û˜[YW×ÈOH	××ÛXZ[—×ÉÎˆXZ[Š
B