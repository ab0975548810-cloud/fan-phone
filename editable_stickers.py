"""Editable-text JSON contract and isolated Fabric production renderer. No vendor calls."""
import base64
import copy
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import tempfile
from functools import lru_cache
from bisect import bisect_left
from urllib.parse import urlsplit

from PIL import Image

VERSION = 'editable-text-v1'
ROOT = Path(__file__).resolve().parent
FONTS = {'jf-openhuninn': 'static/fonts/jf-openhuninn-2.1.ttf', 'NotoSansTC': 'static/fonts/NotoSansTC.woff2'}
STICKER_FONTS=set(FONTS)
FONTS.update({name:'static/fonts/'+name+'.woff2' for name in ('BF-Arimo','BF-ArimoItalic','BF-Tinos','BF-TinosBold','BF-TinosItalic','BF-TinosBoldItalic','BF-Caveat','BF-Emoji','BF-SerifTC')})
LEGACY_FONTS={'Arial':'BF-Arimo, NotoSansTC, BF-Emoji','sans-serif':'NotoSansTC, BF-Emoji','serif':'BF-Tinos, BF-SerifTC, BF-Emoji','cursive':'BF-Caveat, jf-openhuninn, BF-Emoji','Times New Roman':'BF-Tinos, BF-SerifTC, BF-Emoji'}
MAX_BYTES = 70 * 1024 * 1024
MAX_SOURCE_PIXELS = 64000000
_RENDER_SLOT = threading.BoundedSemaphore(1)


@lru_cache(maxsize=16)
def glyph_ranges(family):
    manifest=json.loads((ROOT/'static/fonts/editable-font-manifest.json').read_text(encoding='utf-8'))
    ranges=manifest[family]['ranges']
    return ranges,[b for a,b in ranges]


def check_glyphs(family,text):
    ranges,ends=glyph_ranges(family)
    for ch in text:
        point=ord(ch);index=bisect_left(ends,point)
        if point not in (9,10,13) and (index>=len(ranges) or ranges[index][0]>point):
            raise ValueError('字型不支援部分字元，請更換字型或文字')


def check_ordinary_font(family,text):
    mapped=LEGACY_FONTS.get(family,family)
    if mapped in STICKER_FONTS:return check_glyphs(mapped,text)
    if mapped not in set(LEGACY_FONTS.values())|{'BF-Emoji'}:raise ValueError('請先選擇站內固定字型')
    families=mapped.split(', ')
    for ch in text:
        if ord(ch) in (9,10,13,0x200d,0xfe0e,0xfe0f):continue
        for part in families:
            try:check_glyphs(part,ch);break
            except ValueError:pass
        else:raise ValueError('站內固定字型不支援部分字元')


def normalized_area(value):
    if not isinstance(value, dict):
        raise ValueError('文字安全區缺失')
    out = {}
    for name in ('x', 'y', 'width', 'height'):
        n = value.get(name)
        if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or not 0 <= n <= 1:
            raise ValueError('文字安全區需為 0～1 座標')
        out[name] = n
    if not out['width'] or not out['height'] or out['x'] + out['width'] > 1.000001 or out['y'] + out['height'] > 1.000001:
        raise ValueError('文字安全區超出對話框')
    return out


def numeric(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(label + '格式錯誤')
    return value


def text_style(value):
    if not isinstance(value, dict) or value.get('fontFamily') not in STICKER_FONTS:
        raise ValueError('請選站內字型')
    out = {key: value.get(key) for key in ('text', 'fontFamily', 'fontWeight', 'fontStyle', 'fill', 'stroke', 'textAlign')}
    if not isinstance(out['text'], str) or len(out['text']) > 2000:
        raise ValueError('文字最多 2000 字')
    check_glyphs(out['fontFamily'],out['text'])
    if str(out['fontWeight']) not in ('100','200','300','400','500','600','700','800','900','normal','bold') or out['fontStyle'] not in ('normal', 'italic') or out['textAlign'] not in ('left', 'center', 'right'):
        raise ValueError('文字樣式格式錯誤')
    for key in ('fill', 'stroke'):
        if out[key] is not None and (not isinstance(out[key], str) or len(out[key]) > 64 or any(x in out[key].lower() for x in ('url(', '<', '>'))):
            raise ValueError('文字顏色格式錯誤')
    for key, low, high in (('fontSize', 1, 1000), ('minFontSize', 1, 1000), ('strokeWidth', 0, 30), ('charSpacing', -100, 1000), ('lineHeight', .8, 3)):
        out[key] = numeric(value.get(key), low, high, key)
    if out['minFontSize'] > out['fontSize']:
        raise ValueError('最小字級不可大於設定字級')
    return out


def configured(design):
    return isinstance(design, dict) and design.get('render_contract_version') == VERSION


def nodes(design):
    count = 0
    def visit(items, depth=0):
        nonlocal count
        if not isinstance(items, list) or depth > 4:
            raise ValueError('設計物件結構無效')
        for item in items:
            count += 1
            if count > 300 or not isinstance(item, dict):
                raise ValueError('設計物件過多或無效')
            yield item
            if 'objects' in item:
                yield from visit(item['objects'], depth + 1)
            if item.get('clipPath'):
                yield from visit([item['clipPath']], depth + 1)
    yield from visit(design.get('objects'))


def validate(design):
    if not configured(design) or design.get('truncated'):
        raise ValueError('新版文字貼紙缺少可重建設計')
    if design.get('background') is not None and not isinstance(design['background'],str):
        raise ValueError('不支援程式化背景')
    logical = design.get('logicalCanvas') or {}
    for key in ('width', 'height'):
        numeric(logical.get(key), 1, 2000, '畫布' + key)
    if logical['width'] * logical['height'] > 2000000:
        raise ValueError('設計畫布過大')
    pairs = {}
    allowed = {'image', 'textbox', 'text', 'i-text', 'rect', 'circle', 'ellipse', 'triangle', 'line', 'polygon', 'polyline', 'path', 'group'}
    for item in nodes(design):
        if item.get('type') not in allowed:
            raise ValueError('不支援的設計物件')
        for key in ('fill', 'stroke', 'backgroundColor'):
            if item.get(key) is not None and not isinstance(item[key], str):
                raise ValueError('不支援動態圖案或程式化填色')
        if item.get('filters'):
            raise ValueError('請先套用圖片濾鏡再保存')
        for key in ('left', 'top', 'width', 'height', 'scaleX', 'scaleY', 'angle', 'opacity'):
            if key in item:
                numeric(item[key], -100000, 100000, key)
        if item['type'] == 'image' and not (item.get('src') or item.get('sourceRef')):
            raise ValueError('缺少原始圖片')
        if item['type'] in ('text', 'textbox', 'i-text'):
            if not isinstance(item.get('text'),str) or len(item['text'])>2000:
                raise ValueError('文字最多 2000 字')
            numeric(item.get('fontSize'),1,1000,'字級')
            if item.get('role')=='editable-sticker-text':
                if item.get('fontFamily') not in STICKER_FONTS:raise ValueError('文字貼紙必須使用站內字型')
                check_glyphs(item['fontFamily'],item['text'])
            else:check_ordinary_font(item.get('fontFamily'),item['text'])
            def style_values(value,depth=0):
                if depth>5:raise ValueError('文字樣式過於複雜')
                if isinstance(value,list):
                    for part in value:style_values(part,depth+1)
                elif isinstance(value,dict):
                    for key,part in value.items():
                        if key=='fontFamily' and part!=item['fontFamily']:raise ValueError('請對整段文字使用同一站內字型')
                        if key=='fontSize':numeric(part,1,1000,'字級')
                        if key in ('fill','stroke','textBackgroundColor') and part is not None and not isinstance(part,str):raise ValueError('不支援程式化文字填色')
                        if isinstance(part,(list,dict)):style_values(part,depth+1)
            style_values(item.get('styles',{}))
        if item.get('path') and len(item['path'])>5000:
            raise ValueError('向量路徑過於複雜')
        role = item.get('role')
        if role in ('editable-sticker-bg', 'editable-sticker-text'):
            if item.get('type') != ('image' if role.endswith('-bg') else 'textbox'):
                raise ValueError('文字貼紙物件類型錯誤')
            instance = item.get('editableStickerInstanceId')
            if not isinstance(instance, str) or not 1 <= len(instance) <= 100 or not item.get('editableStickerId'):
                raise ValueError('文字貼紙識別缺失')
            group = pairs.setdefault(instance, {})
            if role in group:
                raise ValueError('重複的文字貼紙成員')
            group[role] = item
            if role.endswith('-text'):
                normalized_area(item.get('textArea'))
                text_style({**item, 'fontSize': item.get('requestedFontSize', item.get('fontSize'))})
    if not pairs or any(set(p) != {'editable-sticker-bg', 'editable-sticker-text'} for p in pairs.values()):
        raise ValueError('文字貼紙缺少圖片或文字')
    if any(p['editable-sticker-bg']['editableStickerId'] != p['editable-sticker-text']['editableStickerId'] for p in pairs.values()):
        raise ValueError('文字貼紙成員識別不一致')
    return design


def image_bytes(raw, *, transparent=False):
    if not raw or len(raw) > 50 * 1024 * 1024:
        raise ValueError('原始圖片容量無效')
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in ('PNG', 'JPEG', 'WEBP') or image.width * image.height > 32000000:
            raise ValueError('原始圖片格式或像素數無效')
        dimensions = image.size
        image.verify()
    if transparent:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format != 'PNG' or 'A' not in image.getbands() or image.getchannel('A').getextrema()[0] == 255:
                raise ValueError('對話框需使用透明 PNG')
    return dimensions


def public_image(app, url):
    if url.startswith('/static/') and not urlsplit(url).query:
        path = (ROOT / url.lstrip('/')).resolve()
        if not path.is_relative_to(ROOT / 'static'):
            raise ValueError('圖片路徑無效')
        raw = path.read_bytes()
    else:
        # URL comes only from admin-owned profile/assets, never arbitrary customer URLs.
        from ai_remove_provider import _public_url
        raw = None
        for _ in range(4):
            _public_url(url)
            response = app.requests.get(url, timeout=15, stream=True, allow_redirects=False)
            try:
                if response.is_redirect:
                    from urllib.parse import urljoin
                    url = urljoin(url, response.headers['Location']);continue
                response.raise_for_status();parts=[];length=0
                for chunk in response.iter_content(65536):
                    length += len(chunk)
                    if length > 50 * 1024 * 1024:raise ValueError('原始圖片過大')
                    parts.append(chunk)
                raw=b''.join(parts);break
            finally:response.close()
        if raw is None:raise ValueError('圖片重新導向過多')
    image_bytes(raw)
    return raw


def snapshot(app, design, order_id, model, style_id, upload_paths):
    from print_center import _complete_model_style_profile
    design=validate(copy.deepcopy(design))
    hashes={family:hashlib.sha256((ROOT/file).read_bytes()).hexdigest() for family,file in FONTS.items()}
    if design.get('fontHashes')!=hashes:raise ValueError('字型版本已更新，請重新開啟設計')
    profile=_complete_model_style_profile(model, style_id)
    if not profile:raise ValueError('型號與殼款尚未完成生產設定')
    if design.get('modelId') != model['id'] or design.get('styleId') != style_id:
        raise ValueError('設計與訂單型號／殼款不一致')
    for key, source in (('printW','print_w'),('printH','print_h')):
        if abs(float((design.get('production') or {}).get(key,0))-float(profile[source])) > .001:
            raise ValueError('生產尺寸已更新，請重新設計')
    from design_sources import receipt, stored_path, read
    seen={};total=0
    pixels=0
    for item in nodes(design):
        if item['type'] != 'image':continue
        src=item.get('sourceRef')
        if src not in seen:
            if not isinstance(src,str) or item.get('src'):
                raise ValueError('新版訂單必須先上傳原始素材，不可嵌入圖片資料')
            claim=receipt(app,src,design.get('sourceCheckout'))
            if item.get('sourceSha256')!=claim['sha256'] or (item.get('width'),item.get('height'))!=(claim['width'],claim['height']):raise ValueError('原始素材引用與尺寸不一致')
            total+=claim['bytes'];pixels+=claim['width']*claim['height']
            if total > MAX_BYTES:raise ValueError('設計原始素材總容量過大')
            if pixels>MAX_SOURCE_PIXELS:raise ValueError('原始素材總像素過多，請減少圖片')
            seen[src]=claim
    # Full preflight before promotion; no partial uploads when total guards fail.
    for src,claim in list(seen.items()):
            raw=read(app,stored_path(app,claim));size=image_bytes(raw)
            if len(raw)!=claim['bytes'] or hashlib.sha256(raw).hexdigest()!=claim['sha256'] or size!=(claim['width'],claim['height']):raise ValueError('原始素材驗證失敗')
            digest=hashlib.sha256(raw).hexdigest()
            intended=f'orders/{order_id}/sources/{digest}.png'
            path=intended if app.USE_SUPABASE else intended.replace('/','_')
            if path not in upload_paths:
                upload_paths.append(path);app.upload_private_bytes(intended,raw)
            seen[src]=(path,size)
    for item in nodes(design):
        if item['type']!='image':continue
        src=item['sourceRef']
        path,size=seen[src]
        if (item.get('width'),item.get('height')) != size:raise ValueError('原始圖片尺寸與結構不一致')
        item['src']=path;item.pop('sourceRef',None)
    mask=public_image(app,profile['print_line_img'])
    intended=f'orders/{order_id}/sources/print-mask.png'
    mask_path=intended if app.USE_SUPABASE else intended.replace('/','_')
    upload_paths.append(mask_path);app.upload_private_bytes(intended,mask)
    design['production']={'printW':float(profile['print_w']),'printH':float(profile['print_h']), 'maskPath':mask_path,'maskUrl':profile['print_line_img']}
    design['fontHashes']=hashes
    design.pop('sourceCheckout',None)
    return design


def _worker(payload):
    from playwright.sync_api import sync_playwright
    resources=payload['resources']
    html='<html><head></head><body><script src="/static/vendor/fabric-5.3.1.min.js"></script><script src="/static/front-print-mask.js"></script><script src="/static/editable-sticker-core-v1.js"></script></body></html>'
    scripts={'/static/vendor/fabric-5.3.1.min.js','/static/front-print-mask.js','/static/editable-sticker-core-v1.js'}
    with sync_playwright() as p:
        browser=p.chromium.launch()
        try:
            context=browser.new_context(service_workers='block')
            def serve(route):
                parsed=urlsplit(route.request.url);path=parsed.path
                if parsed.hostname != 'renderer.invalid':return route.abort()
                if path=='/':return route.fulfill(status=200,body=html,content_type='text/html')
                if path in scripts:return route.fulfill(status=200,body=(ROOT/path.lstrip('/')).read_bytes(),content_type='text/javascript')
                if path=='/static/fonts/editable-font-manifest.json':return route.fulfill(status=200,body=(ROOT/path.lstrip('/')).read_bytes(),content_type='application/json')
                if path in resources:return route.fulfill(status=200,body=base64.b64decode(resources[path]),content_type='image/png')
                if path.lstrip('/') in FONTS.values():return route.fulfill(status=200,body=(ROOT/path.lstrip('/')).read_bytes(),content_type='font/ttf')
                return route.abort()
            context.route('**/*',serve);page=context.new_page();page.goto('https://renderer.invalid/')
            result=page.evaluate('async p=>BenfuwanEditableSticker.render(p.design,p.mask,p.width,p.height)',payload)
            print(json.dumps(result),flush=True)
        finally:browser.close()


def render(app, order, profile, read):
    design=validate(copy.deepcopy(order.get('design_json')))
    contract=design['production']
    for field,key in (('width_mm','printW'),('height_mm','printH')):
        if abs(float(profile[field])-float(contract[key]))>.001:raise ValueError('生產尺寸已更新，生產圖無法重建')
    for family,path in FONTS.items():
        if design.get('fontHashes',{}).get(family)!=hashlib.sha256((ROOT/path).read_bytes()).hexdigest():raise ValueError('字型版本不一致，生產圖無法重建')
    resources={};source_cache={};pixels=0;prefix=f'orders/{order["id"]}/sources/' if app.USE_SUPABASE else f'orders_{order["id"]}_sources_'
    def resource(path):
        nonlocal pixels
        if not isinstance(path,str) or not path.startswith(prefix) or '..' in path or '\\' in path:raise ValueError('原始素材不屬於此訂單')
        if path in source_cache:return source_cache[path]
        raw=read(path);w,h=image_bytes(raw);pixels+=w*h
        if pixels>MAX_SOURCE_PIXELS:raise ValueError('原始素材總像素過多，生產圖無法重建')
        url='/asset/'+hashlib.sha256(raw).hexdigest()+'.png';resources[url]=base64.b64encode(raw).decode();source_cache[path]='https://renderer.invalid'+url;return source_cache[path]
    for item in nodes(design):
        if item['type']=='image':item['src']=resource(item['src'])
    mask=resource(contract['maskPath'])
    width=int(math.floor(float(profile['width_mm'])*720/25.4+.5));height=int(math.floor(float(profile['height_mm'])*720/25.4+.5))
    if width<=0 or height<=0 or width*height>18000000:raise ValueError('生產尺寸無效')
    if not _RENDER_SLOT.acquire(timeout=5):raise ValueError('生產重繪忙碌，請稍後再試')
    try:
        result=subprocess.run([sys.executable,str(Path(__file__)),'--worker'],input=json.dumps({'design':design,'resources':resources,'mask':mask,'width':width,'height':height}),text=True,encoding='utf-8',capture_output=True,timeout=90,check=True)
        output=json.loads(result.stdout)
    except (subprocess.SubprocessError,OSError,ValueError) as exc:
        raise ValueError('生產圖無法重建：字型、原始素材或 renderer 不可用') from exc
    finally:_RENDER_SLOT.release()
    raw=base64.b64decode(output['png'].split(',',1)[1],validate=True)
    if image_bytes(raw)!=(width,height):raise ValueError('生產圖尺寸不一致')
    image=Image.open(io.BytesIO(raw));buffer=io.BytesIO();image.save(buffer,'PNG',dpi=(720,720));raw=buffer.getvalue()
    path=store_generated(app,f'orders/{order["id"]}/rendered/{hashlib.sha256(raw).hexdigest()}.png',raw)
    return path,raw,output['layouts']


def store_generated(app,path,raw):
    """Immutable artifact; concurrent retries cannot expose a partly-written PNG."""
    if app.USE_SUPABASE:
        try:return app.upload_private_bytes(path,raw)
        except Exception as exc:
            try:existing=app.SUPABASE.storage.from_(app.SUPABASE_PRIVATE_BUCKET).download(path)
            except Exception:raise ValueError('生產圖無法保存') from exc
            if existing!=raw:raise ValueError('生產圖保存衝突') from exc
            return path
    filename=path.replace('/','_');full=Path(app.SAVE_DIR)/filename
    if full.exists():
        if full.read_bytes()!=raw:raise ValueError('生產圖保存衝突')
        return filename
    with tempfile.NamedTemporaryFile(dir=app.SAVE_DIR,delete=False) as temp:
        temp.write(raw);temporary=Path(temp.name)
    try:os.replace(temporary,full)
    finally:temporary.unlink(missing_ok=True)
    return filename


def delete_order_sources(app, order):
    """Delete owned sources and generated artifacts after permanent order deletion."""
    order_id=order['id']
    if not __import__('re').fullmatch(r'[A-Za-z0-9-]+',order_id):raise ValueError('訂單識別無效')
    if app.USE_SUPABASE:
        bucket=app.SUPABASE.storage.from_(app.SUPABASE_PRIVATE_BUCKET)
        for folder in ('sources','rendered'):
            prefix=f'orders/{order_id}/{folder}'
            while True:
                rows=bucket.list(prefix,{'limit':100})
                paths=[prefix+'/'+r['name'] for r in rows if '/' not in r['name'] and '\\' not in r['name'] and r['name'] not in ('.','..')]
                if not paths:break
                bucket.remove(paths)
    else:
        for folder in ('sources','rendered'):
            for path in Path(app.SAVE_DIR).glob(f'orders_{order_id}_{folder}_*'):
                path.unlink(missing_ok=True)


if __name__=='__main__' and '--worker' in sys.argv:
    _worker(json.load(sys.stdin))
