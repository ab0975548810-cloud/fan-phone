"""Server authority for the existing templates JSON and #71 rendering contract."""
import copy
import hashlib
import hmac
import io
import json
import math
import re
import uuid
from collections import defaultdict
from itsdangerous import URLSafeTimedSerializer, BadSignature
from PIL import Image

VERSION='multilayer-v1'
FLAGS=('locked','canMove','canScale','canRotate','canDelete','canDuplicate','canEdit')
TEXT_FIELDS=('text','fontFamily','fontSize','fontWeight','fontStyle','fill','stroke','strokeWidth','textAlign','charSpacing','lineHeight','styles','textArea','minFontSize','requestedFontSize')
CONTENT_FIELDS=TEXT_FIELDS+('width','height','cropX','cropY','clipPath','radius','rx','ry','path','pathOffset','points','x1','y1','x2','y2','strokeUniform','strokeDashArray','shadow','underline','overline','linethrough','backgroundColor','paintFirst')


def validate_gradient(value):
    if not isinstance(value,dict) or value.get('type') not in ('linear','radial') or set(value)-{'type','coords','colorStops','offsetX','offsetY','gradientUnits','gradientTransform','id'}:raise ValueError('不支援此背景填色')
    stops=value.get('colorStops')
    if not isinstance(stops,list) or not 1<=len(stops)<=16:raise ValueError('漸層色標無效')
    for stop in stops:
        if not isinstance(stop,dict) or not isinstance(stop.get('color'),str) or len(stop['color'])>64 or any(token in stop['color'].lower() for token in ('url(','<','>')) or not isinstance(stop.get('offset'),(int,float)) or not 0<=stop['offset']<=1:raise ValueError('漸層色標無效')
    coords=value.get('coords',{})
    if not isinstance(coords,dict) or set(coords)-{'x1','y1','x2','y2','r1','r2'} or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or abs(n)>10000 for n in coords.values()):raise ValueError('漸層座標無效')
    matrix=value.get('gradientTransform')
    if matrix is not None and (not isinstance(matrix,list) or len(matrix)!=6 or any(not isinstance(n,(int,float)) or not math.isfinite(n) or abs(n)>10000 for n in matrix)):raise ValueError('漸層變形無效')


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def image_digest(raw):
    with Image.open(io.BytesIO(raw)) as image:
        if image.format!='PNG':raise ValueError('多圖層素材需為 PNG，請重新上傳原始素材')
        rgba=image.convert('RGBA')
        return hashlib.sha256(str(rgba.size).encode()+rgba.tobytes()).hexdigest(),image.size


def geometry(value):
    if not isinstance(value,dict):raise ValueError('圖層相對座標缺失')
    for k in ('x','y','width','height'):
        n=value.get(k)
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or not 0<=n<=1 or k in ('width','height') and n==0:raise ValueError('圖層座標需為 0～1')
    return value


def raw_template(template):
    data=template.get('objects_json')
    if isinstance(data,str):data=json.loads(data)
    if not isinstance(data,dict) or data.get('layer_contract_version')!=VERSION:raise ValueError('多圖層模板結構缺失')
    return data


def prepare_template(app,template,images=None):
    """Validate only opted-in templates; legacy v1/v2/v3 remain untouched."""
    if template.get('layer_contract_version')!=VERSION:
        raw=template.get('objects_json')
        if isinstance(raw,dict) and raw.get('layer_contract_version')==VERSION:raise ValueError('模板契約版本不一致')
        return template
    from editable_stickers import image_bytes,public_image,check_ordinary_font,check_glyphs,STICKER_FONTS,normalized_area
    data=raw_template(template);items=data.get('objects');ids=set();instances=set()
    if not isinstance(items,list) or not 1<=len(items)<=100:raise ValueError('多圖層模板需為 1～100 個獨立圖層')
    if int(template.get('template_version',0))<2:raise ValueError('多圖層需保留新版模板格式')
    canvas=data.get('sourceCanvas') or {}
    for k in ('width','height'):
        n=canvas.get(k)
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not 1<=n<=2000:raise ValueError('模板 logical canvas 無效')
    cache=images if images is not None else {};pixels=total=0;pairs=defaultdict(list)
    for index,item in enumerate(items):
        if item.get('type') not in ('image','text','textbox','i-text','rect','circle','ellipse','triangle','line','path','polygon','polyline') or item.get('objects'):raise ValueError('V1 僅接受獨立圖層，不支援群組')
        identity=item.get('layerId');instance=item.get('layerInstanceId')
        if not isinstance(identity,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',identity) or identity in ids:raise ValueError('圖層 layerId 缺失或重複')
        if not isinstance(instance,str) or not 1<=len(instance)<=150 or instance in instances:raise ValueError('圖層 instance ID 缺失或重複')
        ids.add(identity);instances.add(instance)
        if item.get('templateLayerId')!=identity or item.get('zIndex')!=index:raise ValueError('圖層 identity／順序無效')
        geometry(item.get('normalizedGeometry'))
        if isinstance(item.get('fill'),dict):validate_gradient(item['fill'])
        for flag in FLAGS:
            if not isinstance(item.get(flag),bool):raise ValueError('圖層權限需為 boolean')
        if item['locked'] and any(item[f] for f in FLAGS[1:]):raise ValueError('鎖定圖層不可同時開放客人編輯')
        if not isinstance(item.get('layerName'),str) or len(item['layerName'])>100:raise ValueError('圖層名稱無效')
        for k in ('angle','opacity'):
            n=item.get(k)
            if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or k=='opacity' and not 0<=n<=1:raise ValueError('圖層旋轉／透明度無效')
        if item['type'] in ('text','textbox','i-text'):
            if item.get('role')=='editable-sticker-text':
                if item.get('fontFamily') not in STICKER_FONTS:raise ValueError('文字貼紙需使用站內字型')
                check_glyphs(item['fontFamily'],item.get('text',''));normalized_area(item.get('textArea'))
            else:check_ordinary_font(item.get('fontFamily'),item.get('text',''))
        if item.get('editableStickerInstanceId'):pairs[item['editableStickerInstanceId']].append(item)
        if item['type']=='image':
            src=item.get('src')
            if not isinstance(src,str) or not src or src.startswith(('data:','blob:')):raise ValueError('模板需引用已保存的原始 PNG')
            if src not in cache:
                raw=public_image(app,src);image_bytes(raw);cache[src]=(raw,*image_digest(raw))
                pixels+=cache[src][2][0]*cache[src][2][1];total+=len(raw)
            raw,pixel_hash,size=cache[src]
            if pixels>64000000 or total>70*1024*1024:raise ValueError('模板原始素材總量過大')
            item['assetPixelHash']=pixel_hash;item['sourceSize']={'width':size[0],'height':size[1]}
    for pair in pairs.values():
        if len(pair)!=2 or {p.get('role') for p in pair}!={'editable-sticker-bg','editable-sticker-text'}:raise ValueError('文字貼紙缺少配對圖層')
        if any(pair[0][flag]!=pair[1][flag] for flag in FLAGS):raise ValueError('文字貼紙配對需使用相同權限')
    template['objects_json']=data
    return template


def signer(app):return URLSafeTimedSerializer(app.app.secret_key,salt='multilayer-template-v1')


def find_template(app,identity):
    data=app.cloud_get_json('templates',app.TEMPLATES_FILE,app.DEFAULT_TEMPLATES)
    item=next((t for t in data.get('templates',[]) if t.get('id')==identity),None)
    if not item or item.get('layer_contract_version')!=VERSION:raise ValueError('多圖層模板不存在，請重新選擇模板')
    return item


def binding(app,template,model_id,style_id,application_id):
    from design_sources import owner
    claims={'id':template['id'],'hash':digest(template),'modelId':model_id,'styleId':style_id,'applicationId':application_id,'owner':owner(app)}
    return {k:v for k,v in claims.items() if k!='owner'}|{'ticket':signer(app).dumps(claims)}


def verify_design(app,design):
    from design_sources import owner
    if design.get('layer_contract_version')!=VERSION:raise ValueError('多圖層設計契約缺失')
    claim=design.get('templateBinding') or {}
    try:verified=signer(app).loads(claim.get('ticket'),max_age=86400)
    except (BadSignature,TypeError) as exc:raise ValueError('模板授權已過期，請返回編輯器重新確認') from exc
    if verified.get('owner')!=owner(app) or any(verified.get(k)!=claim.get(k) for k in ('id','hash','modelId','styleId','applicationId')) or verified['modelId']!=design.get('modelId') or verified['styleId']!=design.get('styleId'):raise ValueError('模板授權與目前設計不一致')
    template=find_template(app,claim['id'])
    if digest(template)!=claim['hash']:raise ValueError('模板已更新，請重新套用模板')
    data=raw_template(template);original={o['layerId']:o for o in data['objects']}
    app_id=claim['applicationId'];seen=set();members=defaultdict(list)
    objects=design.get('objects',[]);empty=design.get('emptyTemplateSlots',[])
    if any(o.get('zIndex')!=index or isinstance(o.get('zIndex'),bool) for index,o in enumerate(objects)):raise ValueError('圖層輸出順序無效')
    if not isinstance(empty,list) or len(empty)>100:raise ValueError('照片框資料無效')
    for index,item in enumerate(objects+empty):
        layer_id=item.get('templateLayerId')
        if not layer_id:continue
        expected=original.get(layer_id)
        if not expected or item.get('templateApplicationId')!=app_id:raise ValueError('未知模板圖層')
        instance=item.get('layerInstanceId')
        if not isinstance(instance,str) or not 1<=len(instance)<=150 or instance in seen:raise ValueError('圖層 instance ID 重複或缺失')
        seen.add(instance);members[layer_id].append(item)
        if instance!=app_id+':'+layer_id and (not expected['canDuplicate'] or item.get('duplicateOf')!=app_id+':'+layer_id):raise ValueError('此模板圖層不可複製')
        if any(item.get(flag)!=expected[flag] for flag in FLAGS):raise ValueError('模板圖層權限不可由客戶修改')
        if item.get('layerName')!=expected['layerName']:raise ValueError('模板圖層識別不一致')
        if item.get('assetId')!=expected.get('assetId'):raise ValueError('模板素材引用不一致')
        g=geometry(item.get('normalizedGeometry'));initial=expected['normalizedGeometry']
        def close(a,b):return isinstance(a,(int,float)) and isinstance(b,(int,float)) and abs(a-b)<=.0002
        keys=['x','y'] if not expected['canMove'] else []
        if not expected['canScale'] and not (expected['canEdit'] and item['type'] in ('text','textbox','i-text')):keys+=['width','height']
        if any(not close(g[k],initial[k]) for k in keys):raise ValueError('固定圖層的座標／尺寸已被修改')
        if not expected['canRotate'] and not close(item.get('angle',0),expected.get('angle',0)):raise ValueError('固定圖層不可旋轉')
        if not expected['canEdit']:
            if any(item.get(k,False)!=expected.get(k,False) for k in ('flipX','flipY','visible')) or not close(item.get('opacity'),expected['opacity']):raise ValueError('固定圖層顯示設定已被修改')
            if not (expected.get('templateSlot') and item in empty):
                for k in CONTENT_FIELDS:
                    if item.get(k)!=expected.get(k):raise ValueError('固定圖層內容已被修改')
        if expected.get('templateSlot'):
            if item in empty and item.get('type')!='rect':raise ValueError('照片框初始資料無效')
            if item in objects and (item.get('role')!='slot-photo' or item.get('type')!='image' or not expected['canEdit']):raise ValueError('照片框不可替換')
        elif item.get('type')!=expected.get('type') or item.get('role')!=expected.get('role'):raise ValueError('模板圖層類型不可修改')
    for identity,expected in original.items():
        rows=members[identity];origin=app_id+':'+identity
        if not expected['canDelete'] and not any(o['layerInstanceId']==origin for o in rows):raise ValueError('固定圖層不可刪除')
        if len(rows)>1 and not expected['canDuplicate']:raise ValueError('固定圖層不可複製')
    actual_locked=[o['templateLayerId'] for o in objects if o.get('templateLayerId') and original[o['templateLayerId']]['locked']]
    expected_locked=[o['layerId'] for o in data['objects'] if o['locked'] and not o.get('templateSlot')]
    if actual_locked!=expected_locked:raise ValueError('固定圖層順序不可修改')
    design['templateAuthority']={'id':template['id'],'hash':claim['hash'],'applicationId':app_id,'layers':original}
    return design


def verify_source(design,item,raw):
    expected=(design.get('templateAuthority') or {}).get('layers',{}).get(item.get('templateLayerId'))
    if expected and expected['type']=='image' and not expected['canEdit'] and image_digest(raw)[0]!=expected.get('assetPixelHash'):raise ValueError('固定模板素材不可替換')


def seal(app,design,order_id):
    payload={'orderId':order_id,'design':{k:v for k,v in design.items() if k!='layerSeal'}}
    design['layerSeal']=hmac.new(str(app.app.secret_key).encode(),('multilayer-order:'+digest(payload)).encode(),hashlib.sha256).hexdigest()


def verify_seal(app,design,order_id):
    expected=design.get('layerSeal');copy_=copy.deepcopy(design);seal(app,copy_,order_id)
    if not isinstance(expected,str) or not hmac.compare_digest(expected,copy_['layerSeal']):raise ValueError('模板生產契約驗證失敗')


def install(app):
    @app.app.route('/api/template_contract/<template_id>')
    def template_contract(template_id):
        try:
            from print_center import _complete_model_style_profile
            model_id=app.request.args.get('model_id','');style_id=app.request.args.get('style_id','')
            shop=app.cloud_get_json('shop_data',app.DATA_FILE,app.DEFAULT_SHOP_DATA)
            model=next((m for m in shop['models'] if m['id']==model_id and m.get('status',True)),None)
            if not model or not _complete_model_style_profile(model,style_id):raise ValueError('型號與殼款尚未配置')
            application_id=app.request.args.get('application_id') or str(uuid.uuid4())
            uuid.UUID(application_id)
            template=find_template(app,template_id)
            if template.get('case_style_id') and template['case_style_id']!=style_id:raise ValueError('模板不適用此殼款')
            return app.no_cache_json({'status':'success','template':template,'binding':binding(app,template,model_id,style_id,application_id)})
        except (ValueError,KeyError) as exc:return app.no_cache_json({'status':'error','msg':str(exc)},400)
