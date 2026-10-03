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
        fakeTabs:labels.filter(label=>['模板','我的作品','會員'].includes(label)),
        draftState
      };
    }""")
    assert home['title'] == '本福丸訂製' and home['image'] == [960, 1026], home
    assert abs(home['appWidth'] - 390) <= 1 and home['pageWidth'] <= 391 and home['documentWidth'] <= 391, home
    assert home['heroBottom'] <= home['ctaTop'] + 1 and home['copyBottom'] <= home['artTop'] + 1 and home['artBottom'] <= home['heroBottom'] + 1 and home['textFits'], home
    assert home['labels'] == ['首頁','開始製作','購物車'] and home['fakeTabs'] == [], home
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
    poll(page, "() => document.getElementById('toast')?.textContent.includes('目前沒有未完成設計')")
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
      templatesData={categories:['全部'],templates:[
        {id:'broken-thumb',name:'壞圖模板',model_id:'*',universal:true,thumb_url:'/broken-template-thumb.png'},
        {id:'empty-thumb',name:'空圖模板',model_id:'*',universal:true,thumb_url:''}
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
    assert '像素過大' in upload_regression['pixelError'] and '50MB' in upload_regression['byteError'], upload_regression
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
      document.getElementById('text-input').value='本福丸可愛粉圓';
      document.getElementById('text-font').value='jf-openhuninn';
      document.getElementById('text-bold').checked=false;
      await addTextFromControls();
      const o=canvas.getActiveObject();
      await ensureCanvasFonts();
      const serialized=canvas.toJSON(CUSTOM_PROPS).objects.find(item=>item.role==='text');
      const exported=canvas.toDataURL({format:'png',multiplier:1});
      return {family:o?.fontFamily,loaded:document.fonts.check('16px "jf-openhuninn"','本福丸可愛粉圓'),serialized:serialized?.fontFamily,exported:exported.startsWith('data:image/png;base64,'),option:document.querySelector('#text-font option[value="jf-openhuninn"]')?.textContent};
    }""")
    assert font_result == {'family':'jf-openhuninn','loaded':True,'serialized':'jf-openhuninn','exported':True,'option':'可愛粉圓'}, font_result
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
        style.setdefault('model_colors', {})[model['id']] = ['透明', '黑']
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
      const colorList=(model,style)=>{const raw=style.model_colors?.[model.id]||style.colors||[];return (Array.isArray(raw)?raw:String(raw||'').split(/[,，]/)).map(x=>String(x).trim()).filter(Boolean)};
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
      await ensureEditorFont('jf-openhuninn','粉圓恢復');
      const sticker=new fabric.Text('★',{left:42,top:51,role:'sticker',fontSize:28,fill:'#ff5d91',clipPath:baseClip});
      const text=new fabric.Textbox('粉圓恢復',{left:88,top:122,width:130,role:'text',fontFamily:'jf-openhuninn',fontSize:30,opacity:.84,clipPath:baseClip});
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
    assert page.locator('#design-draft-title').inner_text() == '發現上次未完成的設計'
    assert page.locator('#home-design-title').inner_text() == '繼續上次設計'
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
        font:text.fontFamily,fontLoaded:document.fonts.check('16px "jf-openhuninn"','粉圓恢復'),
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
      document.getElementById('form-surname').value='草稿';
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
    assert page.locator('#design-draft-message').inner_text() == '此手機殼設定已更新，舊設計無法安全恢復，請重新製作。'
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
    assert page.locator('#design-draft-message').inner_text() == '上次的設計草稿已無法安全恢復，請刪除舊草稿並重新開始。'
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
    assert loading == {'title':'我的設計','subtitle':'正在檢查上次設計…','promptInvalid':False,'promptVisible':False}, loading
    page.locator('#home-design-card').click()
    page.wait_for_timeout(100)
    assert not page.locator('#design-draft-prompt.invalid').count()
    page.evaluate("() => window.__releaseShopData()")
    poll(page, "() => window.BenfuwanFrontHomeV1?.isCatalogReady() && document.getElementById('home-design-card')?.dataset.draftState==='ready'")
    assert page.locator('#home-design-title').inner_text() == '繼續上次設計'
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


def admin_steward_test(page):
    requests_seen = []
    mode = {
        'quota_used': 10,
        'active': 0,
        'quota_unavailable': False,
        'ai_failure': False,
        'print_failure': False,
        'print_states': ['PREPARED', 'COMPLETED'],
    }
    now = int(time.time())
    orders = [
        {'order_id': 'TODAY-PENDING', 'status': '待處理', 'time': now},
        {'order_id': 'TODAY-DONE', 'status': '已完成', 'time': now},
        {'order_id': 'TODAY-MAKING', 'status': '製作中', 'time': now},
        {'order_id': 'YESTERDAY', 'status': '待處理', 'time': now - 86400},
    ]

    def reply(route, payload, status=200):
        requests_seen.append({'method': route.request.method, 'url': route.request.url})
        route.fulfill(status=status, content_type='application/json', body=json.dumps(payload, ensure_ascii=False))

    def health(route):
        reply(route, {'status': 'success', 'persistence': 'supabase'})

    def ai(route):
        if mode['ai_failure']:
            reply(route, {'status': 'error', 'code': 'AI_DIAG_UNAVAILABLE'}, 500)
            return
        quota = {
            'client_limit_24h': 5, 'ip_limit_24h': 15, 'global_limit_24h': 60,
            'active_limit': 2,
            'global_used_24h': None if mode['quota_unavailable'] else mode['quota_used'],
            'active_now': None if mode['quota_unavailable'] else mode['active'],
        }
        reply(route, {'status': 'transport_ok', 'ai_quota': quota})

    def order_list(route):
        reply(route, {'status': 'success', 'data': orders})

    def print_jobs(route):
        if mode['print_failure']:
            reply(route, {'status': 'error', 'code': 'PRINT_UNAVAILABLE'}, 500)
            return
        rows = [{'order_id': f'PRINT-{index}', 'job': {'state': state}} for index, state in enumerate(mode['print_states'])]
        reply(route, {'status': 'success', 'rows': rows, 'vendor_ready': True, 'vendor_connected': True})

    page.route('**/api/health*', health)
    page.route('**/api/admin/ai_remove_diagnose*', ai)
    page.route('**/api/admin/get_orders*', order_list)
    page.route('**/api/admin/print/jobs*', print_jobs)
    poll(page, "() => !!window.BenfuwanStewardV1 && !!document.getElementById('bf-steward-launch')")
    assert requests_seen == [], requests_seen
    assert page.locator('#bf-steward-launch').inner_text() == '🐱 本福丸'

    page.set_viewport_size({'width': 390, 'height': 844})
    page.locator('#bf-steward-launch').click()
    poll(page, "() => window.BenfuwanStewardV1.lastOverall==='normal'")
    assert page.locator('#bf-steward-panel').get_attribute('aria-hidden') == 'false'
    assert page.locator('#bf-steward-overall-text').inner_text() == '系統目前正常 ฅ^•ﻌ•^ฅ'
    assert page.locator('#bf-steward-ai-usage').inner_text() == '10 / 60'
    assert page.locator('#bf-steward-ai-active').inner_text() == '0 / 2'
    assert page.locator('#bf-steward-order-total').inner_text() == '3'
    assert page.locator('#bf-steward-order-pending').inner_text() == '1'
    assert page.locator('#bf-steward-order-completed').inner_text() == '1'
    assert page.locator('#bf-steward-print-pending').inner_text() == '1'
    assert page.locator('#bf-steward-print-failed').inner_text() == '0'
    assert page.locator('#bf-steward-print-unknown').inner_text() == '0'
    assert len(requests_seen) == 4 and {row['method'] for row in requests_seen} == {'GET'}, requests_seen
    mobile_box = page.locator('#bf-steward-panel').bounding_box()
    assert mobile_box and mobile_box['width'] <= 390 and mobile_box['height'] <= 844 * .83, mobile_box
    assert page.locator('.bf-steward-backdrop').count() == 0
    page.locator('#bf-steward-close').click()
    assert page.locator('#bf-steward-panel').get_attribute('aria-hidden') == 'true'

    page.set_viewport_size({'width': 768, 'height': 1024})
    page.locator('#bf-steward-launch').click()
    poll(page, "() => document.getElementById('bf-steward-panel').classList.contains('open')")
    poll(page, "() => !document.getElementById('bf-steward-refresh').disabled")
    ipad_box = page.locator('#bf-steward-panel').bounding_box()
    assert ipad_box and ipad_box['width'] <= 402 and ipad_box['x'] >= 350, ipad_box

    mode['quota_used'] = 45
    page.evaluate("() => window.BenfuwanStewardV1.refresh()")
    assert page.evaluate("() => window.BenfuwanStewardV1.lastOverall") == 'attention'
    assert page.locator('#bf-steward-overall-text').inner_text() == '有幾個項目需要注意，我已經幫你標出來。'

    mode.update(quota_used=10, print_states=['FAILED', 'UNKNOWN', 'COMPLETED'])
    page.evaluate("() => window.BenfuwanStewardV1.refresh()")
    assert page.evaluate("() => window.BenfuwanStewardV1.lastOverall") == 'attention'
    assert page.locator('#bf-steward-print-failed').inner_text() == '1'
    assert page.locator('#bf-steward-print-unknown').inner_text() == '1'

    mode.update(quota_unavailable=True, print_states=['COMPLETED'])
    page.evaluate("() => window.BenfuwanStewardV1.refresh()")
    assert page.evaluate("() => window.BenfuwanStewardV1.lastOverall") == 'error'
    assert page.locator('#bf-steward-quota').get_attribute('data-level') == 'error'

    mode.update(quota_unavailable=False, ai_failure=True, quota_used=10)
    page.evaluate("() => window.BenfuwanStewardV1.refresh()")
    assert page.evaluate("() => window.BenfuwanStewardV1.lastOverall") == 'error'
    assert page.locator('#bf-steward-runpod').get_attribute('data-level') == 'error'
    assert page.locator('#bf-steward-order-total').inner_text() == '3'
    assert page.locator('#bf-steward-print-failed').inner_text() == '0'

    mode['ai_failure'] = False
    before_refresh = len(requests_seen)
    page.locator('#bf-steward-refresh').click()
    poll(page, "() => !document.getElementById('bf-steward-refresh').disabled")
    assert len(requests_seen) >= before_refresh + 4, requests_seen[before_refresh:]
    assert {row['method'] for row in requests_seen[before_refresh:]} == {'GET'}, requests_seen[before_refresh:]

    page.locator('#bf-steward-orders-link').click()
    poll(page, "() => document.getElementById('view-orders').classList.contains('active') && document.getElementById('bf-steward-panel').getAttribute('aria-hidden')==='true'")
    page.locator('#bf-steward-launch').click()
    poll(page, "() => document.getElementById('bf-steward-panel').classList.contains('open')")
    page.locator('#bf-steward-print-link').click()
    poll(page, "() => document.getElementById('view-print-center').classList.contains('active') && document.getElementById('bf-steward-panel').getAttribute('aria-hidden')==='true'")

    page.unroute('**/api/health*')
    page.unroute('**/api/admin/ai_remove_diagnose*')
    page.unroute('**/api/admin/get_orders*')
    page.unroute('**/api/admin/print/jobs*')
    page.set_viewport_size({'width': 1180, 'height': 900})
    print('ADMIN_BENFUWAN_STEWARD_READ_ONLY_RESPONSIVE_OK')


def admin_shell_test(page):
    poll(page, "() => !!window.BenfuwanAdminShellV1 && !!document.querySelector('.nav button[data-view=\"commerce\"]') && !!document.querySelector('.nav button[data-view=\"print-center\"]')")
    expected = {
        'operations': ['orders', 'commerce', 'print-center'],
        'catalog': ['models', 'styles', 'assets', 'templates'],
        'system': ['security'],
    }
    groups = page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('[data-nav-group]')].map(group=>[
      group.dataset.navGroup,[...group.querySelectorAll('.admin-nav-items>button[data-view]')].map(button=>button.dataset.view)
    ]))""")
    assert groups == expected, groups
    assert page.locator('[data-nav-group="operations"] .admin-nav-label').inner_text() == '營運'
    assert page.locator('[data-nav-group="catalog"] .admin-nav-label').inner_text() == '商品設定'
    assert page.locator('[data-nav-group="system"] .admin-nav-label').inner_text() == '系統'

    writes = []
    def capture_write(request):
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            writes.append({'method': request.method, 'url': request.url})
    page.on('request', capture_write)

    page.set_viewport_size({'width': 1180, 'height': 900})
    desktop = page.evaluate("""() => {
      const side=document.getElementById('admin-sidebar'),menu=document.getElementById('admin-menu-toggle');
      return {width:side.getBoundingClientRect().width,menu:getComputedStyle(menu).display,labels:[...document.querySelectorAll('.nav button span')].every(node=>getComputedStyle(node).display!=='none'),inert:side.inert};
    }""")
    assert desktop['width'] >= 230 and desktop['menu'] == 'none' and desktop['labels'] and not desktop['inert'], desktop

    for view, label in (
        ('orders', '訂單管理'), ('commerce', '商品與營運'), ('print-center', '列印中心'),
        ('models', '品牌及型號'), ('styles', '手機殼材質'), ('assets', '素材庫'),
        ('templates', '模板庫'), ('security', '登入安全'),
    ):
        page.locator(f'.nav button[data-view="{view}"]').click()
        poll(page, f"() => document.getElementById('view-{view}')?.classList.contains('active') && document.getElementById('admin-workspace-title')?.textContent==={json.dumps(label, ensure_ascii=False)}")
        assert page.locator(f'.nav button[data-view="{view}"]').get_attribute('aria-current') == 'page'

    page.evaluate("() => openModal('model-modal')")
    layers = page.evaluate("""() => ({
      modal:+getComputedStyle(document.getElementById('model-modal')).zIndex,
      sidebar:+getComputedStyle(document.getElementById('admin-sidebar')).zIndex||0
    })""")
    assert layers['modal'] > layers['sidebar'], layers
    page.evaluate("() => closeModal('model-modal')")

    page.set_viewport_size({'width': 390, 'height': 844})
    poll(page, "() => document.getElementById('admin-sidebar').getAttribute('aria-hidden')==='true' && document.getElementById('admin-sidebar').inert===true")
    poll(page, "() => document.getElementById('admin-sidebar').getBoundingClientRect().x < -1")
    mobile = page.evaluate("""() => ({
      viewport:document.documentElement.clientWidth,
      main:document.querySelector('.main').getBoundingClientRect().width,
      menu:getComputedStyle(document.getElementById('admin-menu-toggle')).display,
      sideX:document.getElementById('admin-sidebar').getBoundingClientRect().x
    })""")
    assert mobile['main'] == mobile['viewport'] == 390 and mobile['menu'] != 'none' and mobile['sideX'] < -1, mobile
    page.evaluate("() => document.activeElement?.blur()")
    page.keyboard.press('Tab')
    assert not page.evaluate("() => document.getElementById('admin-sidebar').contains(document.activeElement)")
    page.locator('#admin-menu-toggle').click()
    poll(page, "() => document.body.classList.contains('admin-nav-open') && document.getElementById('admin-sidebar').getBoundingClientRect().x>=-1 && document.getElementById('admin-sidebar').inert===false")
    assert page.evaluate("() => document.getElementById('admin-sidebar').contains(document.activeElement) && document.activeElement.matches('.nav button.active')")
    page.locator('.nav button[data-view="models"]').click()
    poll(page, "() => !document.body.classList.contains('admin-nav-open') && document.getElementById('admin-sidebar').inert===true && document.getElementById('admin-workspace-title').textContent==='品牌及型號'")
    page.locator('#admin-menu-toggle').click()
    poll(page, "() => document.body.classList.contains('admin-nav-open')")
    page.keyboard.press('Escape')
    poll(page, "() => !document.body.classList.contains('admin-nav-open') && document.getElementById('admin-sidebar').inert===true")
    page.locator('#admin-menu-toggle').click()
    poll(page, "() => document.body.classList.contains('admin-nav-open') && document.getElementById('admin-sidebar').inert===false")
    page.locator('#admin-nav-backdrop').click(position={'x': 380, 'y': 20})
    poll(page, "() => !document.body.classList.contains('admin-nav-open') && document.getElementById('admin-sidebar').inert===true")

    page.locator('#admin-actions-toggle').click()
    poll(page, "() => document.querySelector('.top').classList.contains('admin-actions-open')")
    actions = page.evaluate("""() => [...document.querySelectorAll('#admin-top-actions>a,#admin-top-actions>form')].map(node=>{
      const box=node.getBoundingClientRect();return {visible:box.width>0&&box.height>0,top:box.top,bottom:box.bottom};
    })""")
    assert len(actions) == 3 and all(row['visible'] for row in actions), actions
    assert actions[0]['bottom'] <= actions[1]['top'] + 1 and actions[1]['bottom'] <= actions[2]['top'] + 1, actions
    page.keyboard.press('Escape')
    assert not page.evaluate("() => document.querySelector('.top').classList.contains('admin-actions-open')")

    page.set_viewport_size({'width': 768, 'height': 1024})
    poll(page, "() => document.getElementById('admin-sidebar').inert===false")
    ipad = page.evaluate("""() => ({
      width:document.getElementById('admin-sidebar').getBoundingClientRect().width,
      menu:getComputedStyle(document.getElementById('admin-menu-toggle')).display,
      labels:[...document.querySelectorAll('.nav button span')].every(node=>getComputedStyle(node).display!=='none'&&node.getBoundingClientRect().width>0),
      inert:document.getElementById('admin-sidebar').inert
    })""")
    assert 160 <= ipad['width'] <= 190 and ipad['menu'] == 'none' and ipad['labels'] and not ipad['inert'], ipad
    assert writes == [], writes
    page.remove_listener('request', capture_write)
    page.set_viewport_size({'width': 1180, 'height': 900})
    print('ADMIN_NAVIGATION_SHELL_RESPONSIVE_READ_ONLY_OK', {'desktop':desktop,'mobile':mobile,'ipad':ipad,'groups':groups})


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

    admin_steward_test(page)
    admin_shell_test(page)

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

    # Product settings workspace keeps the existing catalog contracts while
    # replacing prompts/wide mobile tables with explicit, filterable controls.
    workspace_original = page.evaluate("() => ({data:structuredClone(shopData),version:shopVersion})")
    workspace_fixture = {
        'brands':['Apple','Samsung'],
        'styles':[
            {'id':'style_1789287807818','name':'晶彩','price':490,'colors':['白色','黑色'],'model_colors':{'model-a':['透明']},'mask_img':'fixture://crystal-mask','status':True},
            {'id':'style-mirror','name':'鏡面','price':590,'colors':['黑色'],'model_colors':{},'mask_img':'fixture://mirror-mask','status':True},
            {'id':'style-off','name':'停售殼款','price':390,'colors':['白色'],'model_colors':{},'mask_img':'','status':False},
        ],
        'models':[
            {'id':'model-a','brand':'Apple','name':'iPhone 17 Pro','status':True,'case_profiles':{
                'style_1789287807818':{'preview_mask_img':'fixture://a-preview','print_line_img':'fixture://a-print','print_x':11,'print_y':12,'print_w':71,'print_h':150,'print_angle':90},
                'style-mirror':{'preview_mask_img':'fixture://b-preview','print_line_img':'fixture://b-print','print_x':21,'print_y':22,'print_w':72,'print_h':151,'print_angle':0},
            }},
            {'id':'model-b','brand':'Samsung','name':'Galaxy S25','status':False,'case_profiles':{}},
        ],
    }
    page.evaluate("fixture => {shopData=structuredClone(fixture);renderBrands();renderModels();renderStyles()}", workspace_fixture)
    page.evaluate("() => {showView('models',document.querySelector('.nav button[data-view=\"models\"]'));switchModelAdminTab('brands')}")
    prompt_calls = page.evaluate("""() => {window.__workspacePrompt=window.prompt;window.__workspacePromptCalls=0;window.prompt=()=>{window.__workspacePromptCalls++;return '不應呼叫'};return window.__workspacePromptCalls}""")
    assert prompt_calls == 0

    # A pending brand mutation owns its dialog until the request settles. A
    # stale response must never close or write errors into a newer editor.
    page.evaluate("""() => {
      window.__workspaceRealFetch=window.fetch;
      window.__workspaceBrandPending=[];
      window.fetch=(input,options)=>{
        if(String(input).includes('/api/admin/save_shop_data')){
          return new Promise(resolve=>window.__workspaceBrandPending.push(resolve));
        }
        return window.__workspaceRealFetch(input,options);
      };
    }""")
    page.locator('#brand-admin-view .titlebar .btn').click()
    page.locator('#bf-brand-name').fill('延遲儲存品牌')
    page.locator('#bf-brand-save').click()
    poll(page, "() => window.__workspaceBrandPending.length===1")
    saving_brand = page.evaluate("""() => ({
      open:document.getElementById('bf-brand-modal').classList.contains('show'),
      busy:document.getElementById('bf-brand-modal').getAttribute('aria-busy'),
      saveDisabled:document.getElementById('bf-brand-save').disabled,
      closeDisabled:[...document.querySelectorAll('#bf-brand-modal [data-brand-close]')].every(button=>button.disabled),
      value:document.getElementById('bf-brand-name').value
    })""")
    assert saving_brand == {'open':True,'busy':'true','saveDisabled':True,'closeDisabled':True,'value':'延遲儲存品牌'}, saving_brand
    blocked_close = page.evaluate("""() => {
      document.querySelector('#bf-brand-modal [data-brand-close]').click();
      document.getElementById('bf-brand-modal').click();
      addBrand();
      editBrand('Apple');
      return {
        open:document.getElementById('bf-brand-modal').classList.contains('show'),
        title:document.getElementById('bf-brand-title').textContent,
        value:document.getElementById('bf-brand-name').value,
        pending:window.__workspaceBrandPending.length
      };
    }""")
    assert blocked_close == {'open':True,'title':'新增品牌','value':'延遲儲存品牌','pending':1}, blocked_close
    page.evaluate("""() => window.__workspaceBrandPending.shift()(new Response(JSON.stringify({status:'success',version:'brand-delayed-success'}),{status:200,headers:{'Content-Type':'application/json'}}))""")
    poll(page, "() => shopData.brands.includes('延遲儲存品牌') && !document.getElementById('bf-brand-modal').classList.contains('show')")

    page.locator('#brand-admin-view .titlebar .btn').click()
    page.locator('#bf-brand-name').fill('延遲失敗品牌')
    page.locator('#bf-brand-save').click()
    poll(page, "() => window.__workspaceBrandPending.length===1")
    page.evaluate("""() => window.__workspaceBrandPending.shift()(new Response(JSON.stringify({status:'error',msg:'延遲儲存失敗'}),{status:503,headers:{'Content-Type':'application/json'}}))""")
    poll(page, "() => document.getElementById('bf-brand-error').textContent.includes('延遲儲存失敗')")
    failed_brand = page.evaluate("""() => ({
      open:document.getElementById('bf-brand-modal').classList.contains('show'),
      value:document.getElementById('bf-brand-name').value,
      saveDisabled:document.getElementById('bf-brand-save').disabled,
      closeDisabled:[...document.querySelectorAll('#bf-brand-modal [data-brand-close]')].some(button=>button.disabled),
      error:document.getElementById('bf-brand-error').textContent
    })""")
    assert failed_brand['open'] and failed_brand['value'] == '延遲失敗品牌', failed_brand
    assert not failed_brand['saveDisabled'] and not failed_brand['closeDisabled'] and '延遲儲存失敗' in failed_brand['error'], failed_brand
    page.locator('#bf-brand-modal [data-brand-close]').last.click()
    page.evaluate("""() => {window.fetch=window.__workspaceRealFetch;delete window.__workspaceRealFetch;delete window.__workspaceBrandPending}""")

    workspace_writes = []
    def workspace_save(route):
        workspace_writes.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"workspace-version"}')
    page.route('**/api/admin/save_shop_data', workspace_save)
    page.locator('#brand-admin-view .titlebar .btn').click()
    assert page.locator('#bf-brand-modal.show').count() == 1
    page.locator('#bf-brand-name').fill('Apple')
    page.locator('#bf-brand-save').click()
    poll(page, "() => document.getElementById('bf-brand-error').textContent.includes('品牌已存在')")
    assert workspace_writes == [] and page.evaluate("() => window.__workspacePromptCalls") == 0
    page.locator('#bf-brand-name').fill('Google')
    page.locator('#bf-brand-save').click()
    poll(page, "() => shopData.brands.includes('Google') && !document.getElementById('bf-brand-modal').classList.contains('show')")
    page.locator('#brands-body [data-edit-brand="Apple"]').click()
    page.locator('#bf-brand-name').fill('Apple Inc.')
    page.locator('#bf-brand-save').click()
    poll(page, "() => shopData.brands.includes('Apple Inc.') && shopData.models.find(x=>x.id==='model-a').brand==='Apple Inc.'")
    assert len(workspace_writes) == 2 and page.evaluate("() => window.__workspacePromptCalls") == 0
    assert page.locator('#brands-body tr[data-brand="Apple Inc."] .bf-count-chip').inner_text() == '1 個型號'
    page.unroute('**/api/admin/save_shop_data')

    page.locator('#model-tab-btn').click()
    page.locator('#bf-model-search').fill('17 Pro')
    assert page.locator('#models-body tr[data-model-id]').count() == 1
    page.locator('#bf-model-search').fill('')
    page.locator('#bf-model-brand-filter').select_option('Samsung')
    assert page.locator('#models-body tr[data-model-id="model-b"]').count() == 1
    page.locator('#bf-model-brand-filter').select_option('')
    page.locator('#bf-model-status-filter').select_option('active')
    assert page.locator('#models-body tr[data-model-id]').count() == 1
    page.locator('#bf-model-status-filter').select_option('all')

    page.locator('#models-body [data-model-id="model-a"][data-model-style="style-mirror"]').click()
    assert page.evaluate("() => BenfuwanModelProfilesAdmin.getActiveStyleId()") == 'style-mirror'
    assert page.locator('#model-profile-x').input_value() == '21'
    page.locator('#model-profile-x').fill('99')
    dirty_guard = page.evaluate("""() => {window.__workspaceConfirm=window.confirm;window.__workspaceConfirmCalls=0;window.confirm=()=>{window.__workspaceConfirmCalls++;return false};document.querySelector('[data-profile-style="style_1789287807818"]').click();return {calls:window.__workspaceConfirmCalls,style:BenfuwanModelProfilesAdmin.getActiveStyleId(),dirty:BenfuwanModelProfilesAdmin.isDirty()}}""")
    assert dirty_guard == {'calls':1,'style':'style-mirror','dirty':True}, dirty_guard
    page.evaluate("() => {window.confirm=()=>true;document.querySelector('[data-profile-style=\"style_1789287807818\"]').click()}")
    assert page.evaluate("() => BenfuwanModelProfilesAdmin.getActiveStyleId()") == 'style_1789287807818'
    assert page.locator('#model-profile-x').input_value() == '11'
    page.evaluate("() => {window.confirm=window.__workspaceConfirm;delete window.__workspaceConfirm;delete window.__workspaceConfirmCalls}")

    profile_writes = []
    def workspace_profile_save(route):
        profile_writes.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"workspace-profile-version"}')
    page.route('**/api/admin/print/model-profiles', workspace_profile_save)
    page.locator('#model-profile-x').fill('13.5')
    page.locator('#model-save').click()
    poll(page, "() => !document.getElementById('model-modal').classList.contains('show')")
    assert len(profile_writes) == 1
    saved_model = next(row for row in profile_writes[0]['shop_data']['models'] if row['id'] == 'model-a')
    assert profile_writes[0]['style_id'] == 'style_1789287807818'
    assert saved_model['case_profiles']['style_1789287807818']['print_x'] == 13.5
    assert saved_model['case_profiles']['style-mirror'] == workspace_fixture['models'][0]['case_profiles']['style-mirror']
    page.unroute('**/api/admin/print/model-profiles')

    page.locator('.nav button[data-view="styles"]').click()
    page.locator('#bf-style-search').fill('鏡面')
    assert page.locator('#styles-body tr[data-style-id="style-mirror"]').count() == 1
    page.locator('#bf-style-search').fill('')
    page.locator('#bf-style-status-filter').select_option('inactive')
    assert page.locator('#styles-body tr[data-style-id="style-off"]').count() == 1
    page.locator('#bf-style-status-filter').select_option('all')
    page.locator('#styles-body [data-edit-style="style_1789287807818"]').click()
    assert page.locator('#style-colors').input_value() == '白色, 黑色'
    assert page.locator('#bf-model-color-list [data-model-id="model-a"]').input_value() == '透明'
    page.locator('#style-modal .mh button').click()

    for width, height in ((390,844),(768,1024),(1180,900)):
        page.set_viewport_size({'width':width,'height':height})
        page.locator('.nav button[data-view="models"]').click() if width >= 600 else page.evaluate("() => showView('models',document.querySelector('.nav button[data-view=\"models\"]'))")
        page.locator('#model-tab-btn').click()
        layout = page.evaluate("""() => ({scroll:document.documentElement.scrollWidth,viewport:document.documentElement.clientWidth,row:getComputedStyle(document.querySelector('#models-body tr[data-model-id]')).display})""")
        assert layout['scroll'] <= layout['viewport'] + 2, (width, layout)
        assert (layout['row'] == 'grid') == (width < 600), (width, layout)
    page.set_viewport_size({'width':1180,'height':900})
    page.evaluate("snapshot => {shopData=structuredClone(snapshot.data);shopVersion=snapshot.version;window.prompt=window.__workspacePrompt;delete window.__workspacePrompt;delete window.__workspacePromptCalls;renderBrands();renderModels();renderStyles()}", workspace_original)
    print('ADMIN_PRODUCT_SETTINGS_WORKSPACE_V1_OK')

    model_color_src = page.locator('script[src*="admin-model-colors.js"]').get_attribute('src')
    assert model_color_src and 'v=20260926audit1' in model_color_src, model_color_src
    model_profile_src = page.locator('script[src*="admin-model-profiles.js"]').get_attribute('src')
    assert model_profile_src and 'v=20260929style1' in model_profile_src, model_profile_src
    product_workspace_src = page.locator('script[src*="admin-product-workspace-v1.js"]').get_attribute('src')
    assert product_workspace_src and 'v=20261001b' in product_workspace_src, product_workspace_src
    asset_category_src = page.locator('script[src*="admin-asset-categories.js"]').get_attribute('src')
    assert asset_category_src and 'v=20261002a' in asset_category_src, asset_category_src
    template_loader_src = page.locator('script[src*="admin-template-loader.js"]').get_attribute('src')
    assert template_loader_src and 'v=20261002a' in template_loader_src, template_loader_src
    library_workspace_src = page.locator('script[src*="admin-library-workspace-v1.js"]').get_attribute('src')
    assert library_workspace_src and 'v=20261002a' in library_workspace_src, library_workspace_src
    commerce_src = page.locator('script[src*="admin-commerce-v1.js"]').get_attribute('src')
    assert commerce_src and 'v=20261003launch1' in commerce_src, commerce_src
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
    assert '服務暫時無法使用，請稍後再試' in page.locator('#bf-product-message').inner_text()
    style_failure_layers = page.evaluate("""() => {
      const message=document.getElementById('bf-product-message');
      const modal=document.getElementById('style-modal');
      return {
        messageZ:Number.parseInt(getComputedStyle(message).zIndex,10),
        modalZ:Number.parseInt(getComputedStyle(modal).zIndex,10),
        visible:message.classList.contains('show') && Number.parseFloat(getComputedStyle(message).opacity)>0
      };
    }""")
    assert style_failure_layers['messageZ'] > style_failure_layers['modalZ'] and style_failure_layers['visible'], style_failure_layers
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
    page.evaluate("() => {window.__issue29Confirm=window.confirm}")

    def catalog_case(label, action, failure_check, success_check, feedback_check):
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
        page.evaluate(action)
        failed = page.evaluate(failure_check)
        assert len(requests) == 1 and failed, (label, requests, failed)
        assert page.evaluate(feedback_check), label
        page.evaluate(action)
        saved = page.evaluate(success_check)
        assert len(requests) == 2 and saved, (label, requests, saved)
        page.unroute('**/api/admin/save_shop_data')

    catalog_case(
        'addBrand',
        """() => {addBrand();document.getElementById('bf-brand-name').value='Issue29新增品牌';return Promise.all([BenfuwanAdminProductWorkspace.submitBrand(),BenfuwanAdminProductWorkspace.submitBrand()])}""",
        """() => JSON.stringify(shopData)===JSON.stringify({brands:['Issue29品牌','Issue29空品牌'],models:[{id:'issue29-model',brand:'Issue29品牌',name:'Issue29型號',status:true}],styles:[{id:'issue29-style',name:'Issue29系列',price:390,colors:['透明'],status:true}]}) && !shopMutationBusy""",
        """() => shopData.brands.filter(x=>x==='Issue29新增品牌').length===1 && !shopMutationBusy""",
        """() => document.getElementById('bf-brand-error').textContent.includes('服務暫時無法使用')""",
    )
    catalog_case(
        'editBrand',
        """() => {editBrand('Issue29品牌');document.getElementById('bf-brand-name').value='Issue29品牌改名';return Promise.all([BenfuwanAdminProductWorkspace.submitBrand(),BenfuwanAdminProductWorkspace.submitBrand()])}""",
        """() => shopData.brands.includes('Issue29品牌') && !shopData.brands.includes('Issue29品牌改名') && shopData.models[0].brand==='Issue29品牌' && !shopMutationBusy""",
        """() => !shopData.brands.includes('Issue29品牌') && shopData.brands.filter(x=>x==='Issue29品牌改名').length===1 && shopData.models[0].brand==='Issue29品牌改名' && !shopMutationBusy""",
        """() => document.getElementById('bf-brand-error').textContent.includes('服務暫時無法使用')""",
    )
    catalog_case(
        'deleteBrand',
        """() => {window.confirm=()=>true;return Promise.all([deleteBrand('Issue29品牌'),deleteBrand('Issue29品牌')])}""",
        """() => shopData.brands.includes('Issue29品牌') && !shopData.brands.includes('未分類') && shopData.models[0].brand==='Issue29品牌' && !shopMutationBusy""",
        """() => !shopData.brands.includes('Issue29品牌') && shopData.brands.filter(x=>x==='未分類').length===1 && shopData.models[0].brand==='未分類' && !shopMutationBusy""",
        """() => document.getElementById('bf-product-message').textContent.includes('服務暫時無法使用')""",
    )
    catalog_case(
        'deleteModel',
        """() => {window.confirm=()=>true;return Promise.all([deleteModel('issue29-model'),deleteModel('issue29-model')])}""",
        """() => shopData.models.some(x=>x.id==='issue29-model') && document.getElementById('models-body').textContent.includes('Issue29型號') && !shopMutationBusy""",
        """() => !shopData.models.some(x=>x.id==='issue29-model') && !shopMutationBusy""",
        """() => document.getElementById('bf-product-message').textContent.includes('服務暫時無法使用')""",
    )
    catalog_case(
        'deleteStyle',
        """() => {window.confirm=()=>true;return Promise.all([deleteStyle('issue29-style'),deleteStyle('issue29-style')])}""",
        """() => shopData.styles.some(x=>x.id==='issue29-style') && document.getElementById('styles-body').textContent.includes('Issue29系列') && !shopMutationBusy""",
        """() => !shopData.styles.some(x=>x.id==='issue29-style') && !shopMutationBusy""",
        """() => document.getElementById('bf-product-message').textContent.includes('服務暫時無法使用')""",
    )
    page.evaluate("async () => {await loadShop(true);window.confirm=window.__issue29Confirm;delete window.__issue29Confirm}")
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
    assert '型號資料已儲存，但正式列印參數同步失敗' in page.locator('#bf-product-message').inner_text()
    model_failure_layers = page.evaluate("""() => {
      const message=document.getElementById('bf-product-message');
      const modal=document.getElementById('model-modal');
      return {
        messageZ:Number.parseInt(getComputedStyle(message).zIndex,10),
        modalZ:Number.parseInt(getComputedStyle(modal).zIndex,10),
        visible:message.classList.contains('show') && Number.parseFloat(getComputedStyle(message).opacity)>0
      };
    }""")
    assert model_failure_layers['messageZ'] > model_failure_layers['modalZ'] and model_failure_layers['visible'], model_failure_layers
    fresh_after_partial = page.request.get(base + '/api/shop_data')
    assert fresh_after_partial.headers.get('x-benfuwan-cache') == 'MISS', fresh_after_partial.headers
    fresh_after_partial_data = fresh_after_partial.json()
    assert fresh_after_partial_data['version'] == server_partial_version
    assert next(row for row in fresh_after_partial_data['data']['models'] if row['id'] == partial_before['model']['id'])['name'] == partial_model_name
    print('ADMIN_MODEL_PROFILE_PARTIAL_SUCCESS_CACHE_INVALIDATION_OK')

    page.evaluate("""async brand => {addBrand();document.getElementById('bf-brand-name').value=brand;await BenfuwanAdminProductWorkspace.submitBrand()}""", partial_brand)
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
    assert '資料已被其他分頁或裝置更新，請重新載入後再修改。' in page.locator('#bf-product-message').inner_text()
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
    prompt_count = page.evaluate("() => {window.__issue59Prompt=window.prompt;window.__issue59PromptCount=0;window.prompt=()=>{window.__issue59PromptCount++;return 'unexpected'};document.querySelector('[data-asset-create]').click();return window.__issue59PromptCount}")
    assert prompt_count == 0
    page.locator('#bf-asset-category-name').fill(asset_b)
    page.locator('#bf-asset-category-save').click()
    poll(page, f"() => assetsVersion==={json.dumps(asset_winner_version)}")
    asset_stale_state = page.evaluate("""names => ({
      version:assetsVersion,
      hasA:assetsData.categories.includes(names.a),
      hasB:assetsData.categories.includes(names.b)
    })""", {'a': asset_a, 'b': asset_b})
    assert asset_stale_state == {'version': asset_winner_version, 'hasA': True, 'hasB': False}, asset_stale_state
    assert '資料已被其他分頁或裝置更新' in page.locator('#bf-asset-category-error').inner_text()
    assert page.locator('#bf-asset-category-modal').get_attribute('class').find('show') >= 0
    assert page.evaluate("() => window.__issue59PromptCount") == 0
    page.locator('#bf-asset-category-modal [data-category-close]').first.click()
    asset_restore = page.request.post(base + '/api/admin/sticker_category', data={
        'action': 'delete', 'name': asset_a, 'expected_version': asset_winner_version,
    })
    assert asset_restore.status == 200, asset_restore.text()
    page.evaluate("async () => {await loadAssets(true)}")
    print('ADMIN_ASSET_STALE_CAS_CACHE_INVALIDATION_OK')

    asset_workspace = page.evaluate("""() => {
      window.__issue59Assets=structuredClone(assetsData);
      assetsData={categories:['全部','貓咪','花朵'],stickers:[
        {id:'asset-cat-a',name:'睡覺貓咪',category:'貓咪',url:'/static/missing-issue59-asset.png'},
        {id:'asset-cat-b',name:'橘色小花',category:'花朵',url:'/static/image.png'},
        {id:'asset-cat-c',name:'站立貓咪',category:'貓咪',url:'/static/image.png'}
      ]};
      currentAsset='全部';renderAssetTabs();renderAssets();
      document.querySelector('[data-asset-create]').click();
      document.getElementById('bf-asset-category-name').value='貓咪';
      document.getElementById('bf-asset-category-form').requestSubmit();
      return {
        promptCalls:window.__issue59PromptCount||0,
        duplicate:document.getElementById('bf-asset-category-error').textContent,
        count:document.getElementById('bf-asset-result-count').textContent,
        cards:document.querySelectorAll('#asset-grid .bf-asset-card').length,
        explicitDelete:document.querySelectorAll('#asset-grid [data-delete-sticker]').length
      };
    }""")
    assert asset_workspace == {
        'promptCalls': 0, 'duplicate': '分類名稱已存在',
        'count': '目前分類 3 張', 'cards': 3, 'explicitDelete': 3,
    }, asset_workspace
    pending_asset_image = []
    page.route('**/issue59-delayed-asset.png', lambda route: pending_asset_image.append(route))
    with page.expect_request('**/issue59-delayed-asset.png'):
        page.evaluate("() => {assetsData.stickers.find(x=>x.id==='asset-cat-a').url='/issue59-delayed-asset.png';renderAssets();document.querySelector('[data-id=\"asset-cat-a\"] img').loading='eager'}")
    asset_pending = page.evaluate("""() => {
      const media=document.querySelector('[data-id="asset-cat-a"] .bf-card-media');
      return {image:getComputedStyle(media.querySelector('img')).visibility,placeholder:getComputedStyle(media.querySelector('.bf-image-placeholder')).display};
    }""")
    assert asset_pending == {'image': 'hidden', 'placeholder': 'grid'}, asset_pending
    assert len(pending_asset_image) == 1
    page.locator('[data-id="asset-cat-a"] .bf-card-media img').evaluate("img => img.addEventListener('error', () => img.dataset.testError = '1')")
    pending_asset_image.pop().fulfill(status=404, body='missing')
    poll(page, "() => document.querySelector('[data-id=\"asset-cat-a\"] .bf-card-media img')?.dataset.testError==='1'")
    asset_failed = page.evaluate("""() => {
      const media=document.querySelector('[data-id="asset-cat-a"] .bf-card-media');
      return {image:getComputedStyle(media.querySelector('img')).visibility,placeholder:getComputedStyle(media.querySelector('.bf-image-placeholder')).display};
    }""")
    assert asset_failed == {'image': 'hidden', 'placeholder': 'grid'}, asset_failed
    page.unroute('**/issue59-delayed-asset.png')
    pending_asset_success = []
    page.route('**/issue59-ok-asset.png', lambda route: pending_asset_success.append(route))
    with page.expect_request('**/issue59-ok-asset.png'):
        page.evaluate("() => {assetsData.stickers.find(x=>x.id==='asset-cat-a').url='/issue59-ok-asset.png';renderAssets();document.querySelector('[data-id=\"asset-cat-a\"] img').loading='eager'}")
    assert page.locator('[data-id="asset-cat-a"] .bf-card-media img').evaluate("img => getComputedStyle(img).visibility") == 'hidden'
    assert len(pending_asset_success) == 1
    pending_asset_success.pop().fulfill(status=200, body=GOOD, content_type='image/png')
    poll(page, "() => getComputedStyle(document.querySelector('[data-id=\"asset-cat-a\"] .bf-card-media img')).visibility==='visible'")
    asset_loaded = page.evaluate("""() => {
      const media=document.querySelector('[data-id="asset-cat-a"] .bf-card-media');
      return {image:getComputedStyle(media.querySelector('img')).visibility,placeholder:getComputedStyle(media.querySelector('.bf-image-placeholder')).display};
    }""")
    assert asset_loaded == {'image': 'visible', 'placeholder': 'none'}, asset_loaded
    page.unroute('**/issue59-ok-asset.png')
    page.evaluate("() => {assetsData.stickers.find(x=>x.id==='asset-cat-a').url='/static/missing-issue59-asset.png';renderAssets()}")
    print('ADMIN_ASSET_THUMB_NO_FLASH_OK')
    page.locator('#bf-asset-category-modal [data-category-close]').first.click()
    page.evaluate("() => {currentAsset='貓咪';renderAssetTabs();renderAssets();document.querySelector('[data-asset-rename]').click()}")
    assert page.locator('#bf-asset-category-name').input_value() == '貓咪'
    assert page.evaluate("() => window.__issue59PromptCount") == 0
    page.locator('#bf-asset-category-modal [data-category-close]').first.click()
    page.evaluate("() => {currentAsset='全部';renderAssetTabs();renderAssets()}")
    page.locator('#bf-asset-search').fill('貓咪')
    assert page.locator('#asset-grid .bf-asset-card').count() == 2
    assert '搜尋到 2 張' in page.locator('#bf-asset-result-count').inner_text()

    page.locator('#bf-asset-search').fill('')
    page.locator('#bf-batch-cat-btn').click()
    page.locator('[data-id="asset-cat-a"]').click()
    move_requests = []
    def move_asset_response(route):
        move_requests.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/json', body='{"status":"success","moved":1,"version":"issue59-move"}')
    page.route('**/api/admin/sticker_category', move_asset_response)
    page.locator('#bf-target-category').fill('精選')
    page.locator('#bf-move-assets').click()
    poll(page, "() => assetsData.stickers.find(x=>x.id==='asset-cat-a')?.category==='精選'")
    assert len(move_requests) == 1 and move_requests[0]['action'] == 'move' and move_requests[0]['ids'] == ['asset-cat-a'], move_requests
    page.unroute('**/api/admin/sticker_category')

    page.locator('#bf-batch-cat-btn').click()
    page.locator('[data-id="asset-cat-a"]').click()
    delete_assets = []
    def delete_assets_response(route):
        delete_assets.append(route.request.post_data_json)
        route.fulfill(status=200, content_type='application/json', body='{"status":"success","deleted":1,"version":"issue59-delete"}')
    page.route('**/api/admin/sticker_category', delete_assets_response)
    page.evaluate("() => {window.__issue59Confirm=window.confirm;window.confirm=()=>true}")
    page.locator('#bf-delete-assets').click()
    poll(page, "() => !assetsData.stickers.some(x=>x.id==='asset-cat-a')")
    assert len(delete_assets) == 1 and delete_assets[0]['action'] == 'delete_stickers', delete_assets
    page.unroute('**/api/admin/sticker_category')

    upload_attempts = []
    def upload_asset_failure(route):
        upload_attempts.append(route.request.post_data)
        route.fulfill(status=503, content_type='application/json', body='{"status":"error","msg":"上傳暫時失敗"}')
    page.route('**/api/admin/batch_upload_stickers', upload_asset_failure)
    page.locator('#sticker-files').set_input_files(files=[{
        'name': 'issue59.png', 'mimeType': 'image/png',
        'buffer': b'issue59-upload-fixture',
    }])
    assert page.locator('#bf-asset-upload-modal').get_attribute('class').find('show') >= 0
    assert '已選擇 1 張圖片' in page.locator('#bf-asset-upload-summary').inner_text()
    page.locator('#bf-asset-new-category-toggle').click()
    page.locator('#bf-asset-upload-new-category').fill('批次新分類')
    page.locator('#bf-asset-upload-confirm').click()
    poll(page, "() => document.getElementById('bf-asset-upload-error').textContent.includes('上傳暫時失敗')")
    assert len(upload_attempts) == 1
    assert page.locator('#bf-asset-upload-modal').get_attribute('class').find('show') >= 0
    assert '已選擇 1 張圖片' in page.locator('#bf-asset-upload-summary').inner_text()
    assert page.locator('#bf-asset-upload-new-category').input_value() == '批次新分類'
    page.unroute('**/api/admin/batch_upload_stickers')
    upload_success = []
    def upload_asset_success(route):
        upload_success.append(route.request.post_data)
        route.fulfill(status=200, content_type='application/json', body='{"status":"success","version":"issue59-upload","data":[{"id":"issue59-uploaded","category":"批次新分類","url":"/static/missing-issue59-upload.png"}]}')
    page.route('**/api/admin/batch_upload_stickers', upload_asset_success)
    page.evaluate("() => {const form=document.getElementById('bf-asset-upload-form');form.requestSubmit();form.requestSubmit()}")
    poll(page, "() => !document.getElementById('bf-asset-upload-modal').classList.contains('show')")
    assert len(upload_success) == 1
    assert '已上傳 1 張到「批次新分類」' in page.locator('#bf-product-message').inner_text()
    page.unroute('**/api/admin/batch_upload_stickers')

    page.set_viewport_size({'width':390,'height':844})
    page.evaluate("() => {currentAsset='全部';renderAssetTabs();renderAssets();document.getElementById('bf-batch-cat-btn').click()}")
    asset_mobile = page.evaluate("""() => ({
      scroll:document.documentElement.scrollWidth,
      columns:getComputedStyle(document.getElementById('asset-grid')).gridTemplateColumns.split(' ').length,
      deleteHeight:document.querySelector('#asset-grid [data-delete-sticker]')?.getBoundingClientRect().height||0,
      batchOverflow:getComputedStyle(document.getElementById('asset-batchbar')).overflowX
    })""")
    assert asset_mobile['scroll'] <= 392 and asset_mobile['columns'] == 2 and asset_mobile['deleteHeight'] >= 43, asset_mobile
    assert asset_mobile['batchOverflow'] == 'auto', asset_mobile
    page.set_viewport_size({'width':1180,'height':900})

    page.evaluate("""() => {
      if(document.getElementById('asset-batchbar').classList.contains('show'))document.getElementById('bf-batch-cat-btn').click();
      assetsData=window.__issue59Assets;delete window.__issue59Assets;
      window.confirm=window.__issue59Confirm;delete window.__issue59Confirm;
      window.prompt=window.__issue59Prompt;delete window.__issue59Prompt;delete window.__issue59PromptCount;
      currentAsset='全部';renderAssetTabs();renderAssets();
    }""")
    print('ADMIN_ASSET_LIBRARY_WORKSPACE_OK')

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
    lazy_before = page.evaluate("""() => ({
      ready:!!window.__benfuwanTemplateStackReady,
      universalScripts:document.querySelectorAll('script[src*="admin-universal-templates.js"]').length,
      editorScripts:document.querySelectorAll('script[src*="admin-template-editor-v2.js"]').length,
      filters:!!document.getElementById('bf-template-filters')
    })""")
    assert lazy_before == {'ready': False, 'universalScripts': 0, 'editorScripts': 0, 'filters': True}, lazy_before

    template_library = page.evaluate("""() => {
      window.__issue59Templates=structuredClone(templatesData);
      window.__issue59Shop=structuredClone(shopData);
      const model=(shopData.models||[])[0]||{id:'issue59-model',name:'測試型號',status:true};
      if(!(shopData.models||[]).length)shopData.models=[model];
      const first=(shopData.styles||[])[0]||{id:'issue59-crystal',name:'晶彩',status:true};
      if(!(shopData.styles||[]).length)shopData.styles=[first];
      const second=(shopData.styles||[])[1]||{id:'issue59-mirror',name:'鏡面',status:true};
      if(!(shopData.styles||[]).some(x=>x.id===second.id))shopData.styles.push(second);
      templatesData={categories:['全部','精選','季節'],templates:[
        {id:'issue59-universal',name:'晶彩貓咪模板',category:'精選',model_id:'*',universal:true,reference_model_id:model.id,reference_style_id:first.id,thumb_url:'/static/missing-issue59-template.png'},
        {id:'issue59-specific',name:'鏡面花朵模板',category:'精選',model_id:model.id,case_style_id:second.id,thumb_url:'/static/image.png'}
      ]};
      currentTpl='全部';
      Object.assign(BenfuwanAdminLibraryWorkspace.state,{query:'',category:'全部',model:'',style:'',type:'all'});
      renderTemplateTabs();renderTemplates();
      const base={cards:document.querySelectorAll('#template-grid .bf-template-card').length,text:document.getElementById('template-grid').textContent};
      BenfuwanAdminLibraryWorkspace.state.query='晶彩';renderTemplates();const search=document.querySelectorAll('#template-grid .bf-template-card').length;
      Object.assign(BenfuwanAdminLibraryWorkspace.state,{query:'',category:'精選',model:'',style:first.id,type:'all'});renderTemplates();const style=document.querySelectorAll('#template-grid .bf-template-card').length;
      Object.assign(BenfuwanAdminLibraryWorkspace.state,{query:'',category:'精選',model:model.id,style:'',type:'specific'});renderTemplates();const specific=document.querySelectorAll('#template-grid .bf-template-card').length;
      Object.assign(BenfuwanAdminLibraryWorkspace.state,{query:'',category:'精選',model:model.id,style:'',type:'universal'});renderTemplates();const universal=document.querySelectorAll('#template-grid .bf-template-card').length;
      Object.assign(BenfuwanAdminLibraryWorkspace.state,{query:'',category:'全部',model:'',style:'',type:'all'});currentTpl='全部';renderTemplateTabs();renderTemplates();
      return {base,search,style,specific,universal,model:model.name,first:first.name,second:second.name};
    }""")
    assert template_library['base']['cards'] == 2, template_library
    assert all(label in template_library['base']['text'] for label in (
        '晶彩貓咪模板', '鏡面花朵模板', '精選', template_library['model'],
        template_library['first'], template_library['second'], '全型號通用', '指定型號',
    )), template_library
    assert {key: template_library[key] for key in ('search','style','specific','universal')} == {
        'search': 1, 'style': 1, 'specific': 1, 'universal': 1,
    }, template_library
    pending_template_image = []
    page.route('**/issue59-delayed-template.png', lambda route: pending_template_image.append(route))
    with page.expect_request('**/issue59-delayed-template.png'):
        page.evaluate("() => {templatesData.templates.find(x=>x.id==='issue59-universal').thumb_url='/issue59-delayed-template.png';renderTemplates();document.querySelector('[data-template-id=\"issue59-universal\"] img').loading='eager'}")
    template_pending = page.evaluate("""() => {
      const media=document.querySelector('[data-template-id="issue59-universal"] .bf-card-media');
      return {image:getComputedStyle(media.querySelector('img')).visibility,placeholder:getComputedStyle(media.querySelector('.bf-image-placeholder')).display};
    }""")
    assert template_pending == {'image': 'hidden', 'placeholder': 'grid'}, template_pending
    assert len(pending_template_image) == 1
    page.locator('[data-template-id="issue59-universal"] .bf-card-media img').evaluate("img => img.addEventListener('error', () => img.dataset.testError = '1')")
    pending_template_image.pop().fulfill(status=404, body='missing')
    poll(page, "() => document.querySelector('[data-template-id=\"issue59-universal\"] .bf-card-media img')?.dataset.testError==='1'")
    template_failed = page.evaluate("""() => {
      const media=document.querySelector('[data-template-id="issue59-universal"] .bf-card-media');
      return {image:getComputedStyle(media.querySelector('img')).visibility,placeholder:getComputedStyle(media.querySelector('.bf-image-placeholder')).display};
    }""")
    assert template_failed == {'image': 'hidden', 'placeholder': 'grid'}, template_failed
    page.unroute('**/issue59-delayed-template.png')
    pending_template_success = []
    page.route('**/issue59-ok-template.png', lambda route: pending_template_success.append(route))
    with page.expect_request('**/issue59-ok-template.png'):
        page.evaluate("() => {templatesData.templates.find(x=>x.id==='issue59-universal').thumb_url='/issue59-ok-template.png';renderTemplates();document.querySelector('[data-template-id=\"issue59-universal\"] img').loading='eager'}")
    assert page.locator('[data-template-id="issue59-universal"] .bf-card-media img').evaluate("img => getComputedStyle(img).visibility") == 'hidden'
    assert len(pending_template_success) == 1
    pending_template_success.pop().fulfill(status=200, body=GOOD, content_type='image/png')
    poll(page, "() => getComputedStyle(document.querySelector('[data-template-id=\"issue59-universal\"] .bf-card-media img')).visibility==='visible'")
    template_loaded = page.evaluate("""() => {
      const media=document.querySelector('[data-template-id="issue59-universal"] .bf-card-media');
      return {image:getComputedStyle(media.querySelector('img')).visibility,placeholder:getComputedStyle(media.querySelector('.bf-image-placeholder')).display};
    }""")
    assert template_loaded == {'image': 'visible', 'placeholder': 'none'}, template_loaded
    page.unroute('**/issue59-ok-template.png')
    page.evaluate("() => {templatesData.templates.find(x=>x.id==='issue59-universal').thumb_url='/static/missing-issue59-template.png';renderTemplates()}")
    print('ADMIN_TEMPLATE_THUMB_NO_FLASH_OK')
    for width, height in ((390,844),(768,1024),(1180,900)):
        page.set_viewport_size(dict(width=width,height=height))
        library_layout = page.evaluate("""() => ({
          scroll:document.documentElement.scrollWidth,
          assetColumns:getComputedStyle(document.getElementById('asset-grid')).gridTemplateColumns.split(' ').length,
          templateColumns:getComputedStyle(document.getElementById('template-grid')).gridTemplateColumns.split(' ').length,
          deleteHeight:document.querySelector('#template-grid [data-delete-template]')?.getBoundingClientRect().height||0
        })""")
        assert library_layout['scroll'] <= width + 2, (width, library_layout)
        if width == 390:
            assert library_layout['templateColumns'] == 2 and library_layout['deleteHeight'] >= 43, library_layout
    page.set_viewport_size({'width': 1440, 'height': 900})
    page.evaluate("""() => {
      templatesData=window.__issue59Templates;shopData=window.__issue59Shop;
      delete window.__issue59Templates;delete window.__issue59Shop;
      Object.assign(BenfuwanAdminLibraryWorkspace.state,{query:'',category:'全部',model:'',style:'',type:'all'});
      currentTpl='全部';renderTemplateTabs();renderTemplates();
    }""")
    print('ADMIN_TEMPLATE_LIBRARY_FILTERS_PLACEHOLDER_RESPONSIVE_OK')

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

    template_fixture_profile = page.evaluate("""() => {
      const models=(shopData?.models||[]).filter(item=>item?.status!==false);
      const styles=(shopData?.styles||[]).filter(item=>item?.status!==false);
      if(!models.length||!styles.length)return null;
      for(const model of models){
        model.case_profiles={...(model.case_profiles||{})};
        for(const style of styles){
          if(!window.BenfuwanCaseProfiles?.complete(model.case_profiles[style.id])){
            model.case_profiles[style.id]={
              preview_mask_img:model.preview_mask_img||'fixture://template-preview',
              print_line_img:model.print_line_img||'fixture://template-print',
              print_x:1,print_y:2,print_w:70,print_h:140,print_angle:0
            };
          }
        }
      }
      return {models:models.length,styles:styles.length};
    }""")
    assert template_fixture_profile, template_fixture_profile
    page.locator('#view-templates .titlebar .btn').click()
    poll(page, "() => document.getElementById('template-modal')?.classList.contains('show')", timeout=30000)
    template_open_diag = page.evaluate("""() => ({canvas:!!visualCanvas,model:document.getElementById('tpl-model')?.value,style:document.getElementById('tpl-style')?.value,profile:!!window.benfuwanTemplateReferenceProfile?.(),dialogs:window.__templateOpenDialogs||[]})""")
    print('ADMIN_TEMPLATE_OPEN_DIAG', template_open_diag)
    assert template_open_diag['canvas'], template_open_diag
    template_editor_src = page.locator('script[src*="admin-template-editor-v2.js"]').get_attribute('src')
    assert template_editor_src and 'v=20260929style1' in template_editor_src, template_editor_src
    print('ADMIN_FABRIC_LAZY_OK')

    template_contract = page.evaluate("""async () => {
      const originalShop=structuredClone(shopData),originalTemplates=structuredClone(templatesData),originalSave=window.saveTemplates,originalUpload=window.uploadAdminImage;
      const model={id:'geometry-model',name:'幾何型號',brand:'Apple',status:true,case_profiles:{
        crystal:{preview_mask_img:'fixture://crystal-preview',print_line_img:'fixture://crystal-print',print_w:70,print_h:140,print_x:1,print_y:2,print_angle:0},
        mirror:{preview_mask_img:'fixture://mirror-preview',print_line_img:'fixture://mirror-print',print_w:75,print_h:150,print_x:3,print_y:4,print_angle:90}
      }};
      shopData={brands:['Apple'],models:[model],styles:[{id:'crystal',name:'晶彩',status:true},{id:'mirror',name:'鏡面',status:true},{id:'missing',name:'未配置',status:true}]};
      const modelSelect=document.getElementById('tpl-model'),styleSelect=document.getElementById('tpl-style');
      modelSelect.innerHTML='<option value="geometry-model">幾何型號</option>';modelSelect.value='geometry-model';
      styleSelect.innerHTML='<option value="crystal">晶彩</option><option value="mirror">鏡面</option><option value="missing">未配置</option>';
      window.__bfEditingTemplate=null;
      styleSelect.value='crystal';initEditor();const crystal={w:tplW,h:tplH};
      styleSelect.value='mirror';initEditor();const mirror={w:tplW,h:tplH};
      const beforeMissing={w:tplW,h:tplH};styleSelect.value='missing';const missingResult=initEditor();const afterMissing={w:tplW,h:tplH};
      const old={id:'legacy-style-template',name:'舊殼款模板',category:'熱門',model_id:'*',universal:true,case_style_id:'crystal',reference_model_id:'geometry-model',source_print_w:70,source_print_h:140,slots:[],objects_json:{version:'5.3.0',objects:[]}};
      templatesData={templates:[old],categories:['全部','熱門']};window.__bfEditingTemplate=old;
      document.getElementById('tpl-id').value=old.id;document.getElementById('tpl-name').value=old.name;document.getElementById('tpl-category').value=old.category;styleSelect.value='crystal';initEditor([],old.objects_json,'');
      let captured=null;window.uploadAdminImage=async()=>'/static/uploads/geometry-template.png';window.saveTemplates=async next=>{captured=structuredClone(next);return {version:'geometry-version'}};
      await saveTemplate();
      const saved=captured.templates.find(row=>row.id===old.id);
      window.saveTemplates=originalSave;window.uploadAdminImage=originalUpload;shopData=originalShop;templatesData=originalTemplates;window.__bfEditingTemplate=null;
      return {crystal,mirror,beforeMissing,afterMissing,missingResult,saved:{case_style_id:saved.case_style_id,reference_style_id:saved.reference_style_id,source_print_w:saved.source_print_w,source_print_h:saved.source_print_h}};
    }""")
    assert template_contract == {
        'crystal': {'w':140,'h':280}, 'mirror': {'w':150,'h':300},
        'beforeMissing': {'w':150,'h':300}, 'afterMissing': {'w':150,'h':300},
        'missingResult': False,
        'saved': {'case_style_id':'crystal','reference_style_id':'crystal','source_print_w':70,'source_print_h':140},
    }, template_contract
    assert any('此型號的此殼款尚未配置生產資料' in msg for msg in dialogs), dialogs
    print('ADMIN_TEMPLATE_MODEL_STYLE_GEOMETRY_LEGACY_STYLE_OK', template_contract)

    page.locator('#view-templates .titlebar .btn').click()
    poll(page, "() => document.getElementById('template-modal')?.classList.contains('show') && !!visualCanvas", timeout=30000)

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
    page.evaluate("() => Promise.all([deleteTemplate('issue29-delete-template'),deleteTemplate('issue29-delete-template')])")
    delete_failed = page.evaluate("() => templatesData.templates.filter(x=>x.id==='issue29-delete-template').length===1 && document.getElementById('template-grid').textContent.includes('Issue29刪除模板') && !templateDeleteBusy")
    assert len(delete_requests) == 1 and delete_failed, (delete_requests, delete_failed)
    assert '服務暫時無法使用，請稍後再試' in page.locator('#bf-product-message').inner_text()
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


def order_print_workspace_test(browser, base, poll):
    """PR #60: paged orders, exact cross-navigation, triage and safe actions."""
    from urllib.parse import parse_qs, urlsplit
    page = browser.new_page(viewport={'width': 1180, 'height': 900})
    page.goto(base + '/login', wait_until='domcontentloaded')
    if not page.locator('#password-form').is_visible():
        page.locator('#password-toggle').click()
    page.locator('input[name="password"]').fill('fan123')
    page.locator('button[type="submit"]').first.click()
    page.wait_for_url('**/admin')
    stamp = int(time.time())
    orders = [dict(order_id=f'ORDER-{i:03d}', customer_name='老客人' if i == 204 else '客人',
                   model='iPhone 13', style='晶彩', payment_method='現金', status='待處理',
                   time=stamp-i, has_print=True, has_mockup=False, quantity=1, total=100)
              for i in range(205)]
    orders[203]['status'] = '已完成'
    def order_route(route):
        p = parse_qs(urlsplit(route.request.url).query)
        found = orders
        if 'order_id' in p: found = [o for o in found if o['order_id'] == p['order_id'][0]]
        if 'q' in p: found = [o for o in found if p['q'][0].lower() in ' '.join(str(o[k]) for k in ('order_id','customer_name','model','style','payment_method','status')).lower()]
        if 'status' in p: found = [o for o in found if o['status'] == p['status'][0]]
        offset = int(p.get('offset', ['0'])[0]);limit = int(p.get('limit', ['200'])[0])
        route.fulfill(status=200, content_type='application/json', body=json.dumps(dict(status='success',data=found[offset:offset+limit],has_more=len(found)>offset+limit,next_offset=min(len(found),offset+limit),before=stamp+10)))
    print_rows=[]
    for state in ('UNKNOWN','FAILED','SENDING','CANCELING','STARTING','PREPARED','QUEUED','PRINTING','COMPLETED'):
        print_rows.append(dict(order_id='PRINT-'+state,customer_name='客人',model='iPhone 13',style='晶彩',order_status='待處理',time=stamp,
                               has_print=True,profile_available=True,binding_required=False,sku_id='SKU',job=dict(id='JOB-'+state,state=state,state_label=state,profile_complete=True,last_error='銳印回報失敗' if state=='FAILED' else '')))
    print_rows.append(dict(order_id='PRINT-BIND',customer_name='客人',model='iPhone 13',style='晶彩',order_status='待處理',time=stamp,
                           has_print=True,profile_available=False,binding_required=True,sku_id='',legacy_order=True,sku_candidates=[],job=None))
    def print_route(route):
        p = parse_qs(urlsplit(route.request.url).query)
        data = [dict(order_id='ORDER-204',customer_name='老客人',model='iPhone 13',style='晶彩',order_status='待處理',time=stamp-204,has_print=True,profile_available=True,binding_required=False,sku_id='SKU',job=None)] if p.get('order_id') == ['ORDER-204'] else print_rows
        route.fulfill(status=200,content_type='application/json',body=json.dumps(dict(status='success',rows=data,vendor_ready=True,vendor_connected=True,device_id='fixture')))
    mutations=[]
    page.on('request',lambda request: mutations.append(request.url) if request.method != 'GET' and '/api/admin/print/' in request.url else None)
    page.route('**/api/admin/get_orders?*',order_route)
    page.route('**/api/admin/print/jobs?*',print_route)
    page.locator('.nav button[data-view="orders"]').click()
    page.locator('[data-range="all"]').click()
    poll(page,"() => document.querySelectorAll('.bf-order-card').length===200 && !!document.querySelector('[data-order-more]')")
    page.evaluate("() => window.__bfPagerButton = document.querySelector('[data-order-more]')")
    # Normal/periodic refresh must reset page 1, never append page 2.
    page.evaluate("() => window.refreshOrders()")
    poll(page,"() => document.querySelectorAll('.bf-order-card').length===200 && !!document.querySelector('[data-order-more]')")
    page.evaluate("() => window.refreshOrders()")
    poll(page,"() => document.querySelectorAll('.bf-order-card').length===200 && !!document.querySelector('[data-order-more]')")
    assert page.evaluate("() => window.__bfPagerButton === document.querySelector('[data-order-more]')")
    page.locator('[data-order-more]').click()
    poll(page,"() => document.querySelectorAll('.bf-order-card').length===205")
    page.locator('#bf-order-search').fill('已完成')
    poll(page,"() => document.querySelectorAll('.bf-order-card').length===1 && document.querySelector('.bf-order-id').textContent.includes('ORDER-203')")
    page.locator('#bf-order-search').fill('老客人')
    poll(page,"() => document.querySelectorAll('.bf-order-card').length===1 && document.querySelector('.bf-order-id').textContent.includes('ORDER-204')")
    page.locator('[data-order-action="print"]').click()
    poll(page,"() => document.querySelector('#view-print-center.active .pc-card')?.textContent.includes('ORDER-204')")
    assert 'order_id=ORDER-204' in page.locator('#pc-exact').inner_text() or 'ORDER-204' in page.locator('#pc-exact').inner_text()
    page.locator('[data-pc="order"]').click()
    poll(page,"() => document.querySelector('#view-orders.active .bf-order-card')?.textContent.includes('ORDER-204')")
    page.locator('.nav button[data-view="print-center"]').click()
    page.locator('[data-pc="clear-exact"]').click()
    poll(page,"() => document.querySelectorAll('#pc-grid .pc-card').length===10")
    for key,count in [('exception',5),('attention',1),('prepared',1),('queued',1),('printing',1),('completed',1)]:
        page.locator(f'[data-triage="{key}"]').click()
        assert page.locator('#pc-grid .pc-card').count()==count,(key,page.locator('#pc-grid .pc-card').count())
    page.locator('[data-triage="all"]').click()
    for state in ('UNKNOWN','SENDING','CANCELING'):
        card=page.locator('.pc-card').filter(has=page.locator('.pc-id',has_text='PRINT-'+state))
        assert card.locator('[data-pc="send"]').count()==0
        assert card.locator('[data-pc="reconcile"]').count()==1
    assert page.locator('.pc-card').filter(has=page.locator('.pc-id',has_text='PRINT-PRINTING')).locator('[data-pc="cancel"]').count()==0
    assert page.locator('.pc-card').filter(has=page.locator('.pc-id',has_text='PRINT-FAILED')).locator('[data-pc="send"]').count()==0
    assert mutations==[],mutations
    for width,height in ((390,844),(768,1024),(1180,900)):
        page.set_viewport_size(dict(width=width,height=height))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'),width
        assert page.locator('#pc-triage').evaluate('(e)=>e.scrollWidth>=e.clientWidth')
    page.close()


def main():
    server = ServerThread();server.start();time.sleep(.8)
    try:
        with sync_playwright() as p:
            browser = getattr(p, os.environ.get('BROWSER_ENGINE', 'webkit')).launch()
            try:
                base=f'http://127.0.0.1:{BROWSER_TEST_PORT}';passkey_login_test(browser,base);front_test(browser,base);home_draft_catalog_race_test(browser,base);design_draft_test(browser,base);checkout_test(browser,base);admin_test(browser,base);order_print_workspace_test(browser,base,poll)
                import runpy
                runpy.run_path(str(ROOT / '.github/tests/test_pos_dashboard.py'))['dashboard_test'](browser,base,poll)
                runpy.run_path(str(ROOT / '.github/tests/test_launch_acceptance.py'))['launch_acceptance_test'](browser,base,poll)
                runpy.run_path(str(ROOT / '.github/tests/test_model_cat_icon.py'))['model_cat_icon_test'](browser,base,poll)
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
