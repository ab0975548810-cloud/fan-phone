"""Private, append-only order artwork revisions. Never writes commerce or print jobs."""
import copy
import hashlib
import io
import json
import re
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import request, session, send_file
from itsdangerous import URLSafeTimedSerializer, BadSignature

from editable_stickers import FONTS, ROOT, nodes, validate, image_bytes, store_generated
from design_sources import read, receipt, stored_path, owner


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def checkout_context(app, design, order_id, model, style_id, profile, paths):
    """Executed before the existing atomic order commit; cleanup owns every upload."""
    from editable_stickers import public_image
    from catalog_products import product_type
    validate_guides(design)
    validate_sources(design)
    preview = profile.get('preview_mask_img') or model.get('preview_mask_img')
    preview_path = design['production']['maskPath']
    if preview:
        raw = public_image(app, preview)
        intended = f'orders/{order_id}/sources/preview-mask.png'
        preview_path = intended if app.USE_SUPABASE else intended.replace('/', '_')
        paths.append(preview_path)
        app.upload_private_bytes(intended, raw)
    design['editorContext'] = {
        'modelName': model.get('name', ''), 'productType': product_type(model),
        'previewPath': preview_path,
        'printX': profile.get('print_x', 0), 'printY': profile.get('print_y', 0),
        'printAngle': profile.get('print_angle', 0),
    }
    if design.get('layer_contract_version') == 'multilayer-v1':
        design['editorState'] = {'version': 'multilayer-v1', 'id': design['templateBinding']['id'],
            'applicationId': design['templateBinding']['applicationId'],
            'binding': copy.deepcopy(design['templateBinding']),
            'initial': copy.deepcopy(design['objects'] + design.get('emptyTemplateSlots', [])),
            'sourceAssets': copy.deepcopy(design.get('sourceAssets',[]))}
        # The immutable context is part of the order's existing renderer seal.
        from multilayer_templates import seal
        seal(app, design, order_id)


class Revisions:
    def __init__(self, app):
        self.app = app

    def rows(self, order_id):
        if self.app.USE_SUPABASE:
            return self.app.SUPABASE.table('order_design_versions').select('*').eq('order_id', order_id).order('version').execute().data
        with self.app.commerce.store.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS order_design_versions (order_id TEXT, version INTEGER, document TEXT NOT NULL, actor TEXT NOT NULL, request_id TEXT NOT NULL, content_hash TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(order_id,version), UNIQUE(order_id,request_id))')
            db.commit()
            return [dict(zip(('order_id','version','document','actor','request_id','content_hash','created_at'), (r[0],r[1],json.loads(r[2]),*r[3:]))) for r in db.execute('SELECT * FROM order_design_versions WHERE order_id=? ORDER BY version', (order_id,))]

    def append(self, order_id, expected, document, actor, request_id):
        hashed = digest(document)
        if self.app.USE_SUPABASE:
            return self.app.SUPABASE.rpc('append_order_design_version', {
                'p_order':order_id, 'p_expected':expected, 'p_document':document,
                'p_actor':actor, 'p_request':request_id, 'p_hash':hashed}).execute().data
        self.rows(order_id)
        with self.app.commerce.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT version,content_hash FROM order_design_versions WHERE order_id=? AND request_id=?', (order_id,request_id)).fetchone()
            if previous:
                return {'ok':previous[1] == hashed, 'version':previous[0]}
            current = db.execute('SELECT coalesce(max(version),0) FROM order_design_versions WHERE order_id=?', (order_id,)).fetchone()[0]
            if current != expected:
                return {'ok':False, 'version':current}
            db.execute('INSERT INTO order_design_versions VALUES (?,?,?,?,?,?,?)',
                (order_id, current+1, json.dumps(document), actor, request_id, hashed, datetime.now(timezone.utc).isoformat()))
            db.commit()
            return {'ok':True, 'version':current+1}


def check_restore(design):
    if not isinstance(design, dict):
        raise ValueError('此舊訂單沒有原始設計資料，不能將生產 PNG 當成原始圖層')
    if design.get('truncated') or design.get('manifestOnly'):
        raise ValueError('此舊訂單只保存精簡／截斷清單，無法完整恢復圖層')
    if not design.get('logicalCanvas') or not design.get('production', {}).get('maskPath'):
        raise ValueError('此舊訂單缺少原始畫布尺寸或持久刀模快照，無法安全定位圖層')
    validate(design)
    context=design.get('editorContext') or {}
    if context.get('productType') not in ('phone_case','camera_film') or not context.get('previewPath'):
        raise ValueError('此舊訂單缺少商品類型與預覽定位快照，無法安全恢復')
    validate_guides(design)
    validate_sources(design)
    for family, path in FONTS.items():
        if design.get('fontHashes', {}).get(family) != hashlib.sha256((ROOT/path).read_bytes()).hexdigest():
            raise ValueError('原設計字型版本已不存在，無法保證文字位置一致')
    if design.get('layer_contract_version') and not design.get('editorState'):
        raise ValueError('此舊模板訂單缺少完整圖層權限快照，無法安全恢復')


def validate_sources(design):
    assets=design.get('sourceAssets',[])
    if not isinstance(assets,list):raise ValueError('原始素材清單無效')
    ids=[a.get('id') for a in assets]
    if any(not isinstance(i,str) or not re.fullmatch('[0-9a-f]{64}',i) for i in ids) or len(set(ids))!=len(ids):raise ValueError('原始素材識別無效')
    if any(o.get('orderOutlineSourceId') and o['orderOutlineSourceId'] not in ids for o in nodes(design)):raise ValueError('描邊原始素材缺失')


def validate_guides(design):
    guides=design.get('editorGuides',[])
    if not isinstance(guides,list) or len(guides)>100 or any(not isinstance(o,dict) or o.get('type')!='rect' or o.get('role')!='slot-guide' or o.get('objects') or o.get('clipPath') or o.get('src') for o in guides):
        raise ValueError('原始照片框導引資料無效')
    if guides:
        check=copy.deepcopy(design);check['objects']=guides;check['orderDesignVersion']=1;validate(check)


def persist_asset(app, order_id, raw):
    image_bytes(raw)
    return store_generated(app, f'order-design/{order_id}/{hashlib.sha256(raw).hexdigest()}.png', raw)


def asset_paths(design):
    paths = {o['src'] for o in nodes(design) if o.get('type') == 'image'}
    paths.add(design['production']['maskPath'])
    paths.add(design.get('editorContext', {}).get('previewPath', design['production']['maskPath']))
    for o in nodes({'objects':design.get('editorState', {}).get('initial', []),'sourceAssets':design.get('editorState',{}).get('sourceAssets',[])}):
        if o.get('type') == 'image':paths.add(o['src'])
    return paths


def archive(app, order):
    design = copy.deepcopy(order.get('design_json'))
    try:check_restore(design)
    except ValueError:
        from legacy_order_designs import recover
        return recover(app,order)
    if design.get('layer_contract_version'):
        from multilayer_templates import verify_seal
        verify_seal(app, design, order['id'])
    prefix = f'orders/{order["id"]}/sources/' if app.USE_SUPABASE else f'orders_{order["id"]}_sources_'
    mapping = {}
    for path in asset_paths(design):
        if not isinstance(path, str) or not path.startswith(prefix) or '..' in path or '\\' in path:
            raise ValueError('原設計缺少可信任的私有素材來源')
        try:mapping[path] = persist_asset(app, order['id'], read(app,path))
        except (FileNotFoundError, OSError) as exc:raise ValueError('原始圖片素材已不存在，無法完整恢復') from exc
    def replace(value):
        if isinstance(value,str):return mapping.get(value,value)
        if isinstance(value,list):return [replace(v) for v in value]
        if isinstance(value,dict):return {k:replace(v) for k,v in value.items()}
        return value
    design = replace(design)
    design.setdefault('editorContext', {}).update(modelName=order.get('model_name',''),styleName=order.get('style_name',''))
    return design


def protect_layers(base, candidate):
    """Frozen order policy, including renderer geometry and empty photo slots."""
    from multilayer_templates import FLAGS, CONTENT_FIELDS, geometry
    before=base['objects']+base.get('emptyTemplateSlots',[])
    after=candidate['objects']+candidate.get('emptyTemplateSlots',[])
    originals={o.get('layerInstanceId'):o for o in before if o.get('templateLayerId')}
    incoming={o.get('layerInstanceId'):o for o in after if o.get('templateLayerId')}
    if len(incoming)!=sum(bool(o.get('templateLayerId')) for o in after):raise ValueError('模板圖層識別重複')
    def close(a,b):
        return isinstance(a,(int,float)) and not isinstance(a,bool) and isinstance(b,(int,float)) and abs(a-b)<=.0002
    for identity,new in incoming.items():
        old=originals.get(identity)
        if old is None:
            old=originals.get(new.get('duplicateOf'))
            if not old or old.get('locked') or not old.get('canDuplicate'):raise ValueError('禁止新增未知模板圖層')
        flags=FLAGS+('templateLayerId','templateApplicationId','layerId','layerName','assetId','templateSlot','slotId')
        if any(new.get(k)!=old.get(k) for k in flags):raise ValueError('禁止修改模板權限或識別')
        locked=old.get('locked')
        slot=old.get('templateSlot')
        can_edit=old.get('canEdit') is True and (not locked or slot)
        if slot:
            if new.get('role') not in ('slot-guide','slot-photo') or (new.get('role')=='slot-photo' and new.get('type')!='image'):raise ValueError('照片框圖層無效')
            if new.get('role')!=old.get('role') and not can_edit:raise ValueError('照片框禁止替換')
        elif any(new.get(k)!=old.get(k) for k in ('type','role')):raise ValueError('模板圖層類型不可修改')
        g=geometry(new.get('normalizedGeometry'));initial=geometry(old.get('normalizedGeometry'))
        keys=['x','y'] if locked or not old.get('canMove') else []
        text_reflow=can_edit and new.get('type') in ('text','textbox','i-text')
        if locked or (not old.get('canScale') and not text_reflow):keys+=['width','height']
        if any(not close(g[k],initial[k]) for k in keys):raise ValueError('禁止修改保護圖層座標／尺寸')
        if (locked or not old.get('canRotate')) and not close(new.get('angle',0),old.get('angle',0)):raise ValueError('禁止旋轉保護圖層')
        if not can_edit:
            for key in CONTENT_FIELDS+('src','opacity','visible','flipX','flipY','orderOutlineSourceId','aiOutlineStyle','aiOutlineStrength','aiOutlineWidth','aiOutlineColor'):
                if new.get(key)!=old.get(key):raise ValueError('禁止變更保護圖層內容')
    for identity,old in originals.items():
        if identity not in incoming and (old.get('locked') or not old.get('canDelete')):raise ValueError('禁止移除保護圖層')
    fixed=lambda rows:[o.get('layerInstanceId') for o in rows if o.get('templateLayerId') and originals.get(o.get('layerInstanceId'),{}).get('locked')]
    if fixed(base['objects'])!=fixed(candidate['objects']):
        # Empty photo frames may become filled; other fixed layers retain their order.
        exclude={o.get('layerInstanceId') for o in before if o.get('templateSlot')}
        if [i for i in fixed(base['objects']) if i not in exclude]!=[i for i in fixed(candidate['objects']) if i not in exclude]:raise ValueError('固定圖層順序不可修改')
    if candidate.get('layer_contract_version'):
        if any(o.get('zIndex')!=i for i,o in enumerate(candidate['objects'])):raise ValueError('圖層順序無效')


def install(app):
    store=Revisions(app)
    signer=URLSafeTimedSerializer(app.app.secret_key,salt='order-design-work-v1')

    def admin(fn):
        @wraps(fn)
        def wrapped(*args,**kwargs):
            if not session.get('logged_in'):return app.no_cache_json({'status':'error','msg':'請先登入後台'},401)
            if request.method=='POST' and request.headers.get('X-Order-Design')!='1':return app.no_cache_json({'status':'error','msg':'操作來源驗證失敗'},403)
            try:return fn(*args,**kwargs)
            except BadSignature:return app.no_cache_json({'status':'error','msg':'編輯工作副本已失效，請重新開啟訂單設計；原版本未變更'},422)
            except ValueError as exc:return app.no_cache_json({'status':'error','msg':str(exc)},422)
            except Exception:
                app.app.logger.exception('order design operation failed')
                return app.no_cache_json({'status':'error','msg':'設計版本或私有素材暫時無法讀取／保存，請確認 Migration 與儲存服務後重試；原訂單未變更'},503)
        return wrapped

    def actor():
        return str(session.get('passkey_credential_id') or 'admin:'+owner(app))

    def materialize(order_id, version, design):
        design=copy.deepcopy(design)
        mapping={path:f'/api/admin/order-design/{order_id}/assets/{version}/{hashlib.sha256(path.encode()).hexdigest()}' for path in asset_paths(design)}
        def replace(v):
            if isinstance(v,str):return mapping.get(v,v)
            if isinstance(v,list):return [replace(x) for x in v]
            if isinstance(v,dict):return {k:replace(x) for k,x in v.items()}
            return v
        return replace(design)

    @app.app.route('/admin/order-design/<order_id>')
    @admin
    def page(order_id):
        response=app.send_from_directory(str(ROOT),'index.html')
        response.headers['Cache-Control']='no-store'
        return response

    @app.app.route('/api/admin/order-design/<order_id>/assessment')
    @admin
    def assessment(order_id):
        from legacy_order_designs import classify
        order=app.commerce.store.order(order_id)
        if not order:return app.no_cache_json({'status':'error','msg':'訂單不存在'},404)
        category,reason=classify(order)
        return app.no_cache_json({'status':'success','category':category,'reason':reason,'verified':False})

    @app.app.route('/api/admin/order-design/<order_id>/remake',methods=['POST'])
    @admin
    def remake(order_id):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,100}',order_id):raise ValueError('訂單識別無效')
        if (request.get_json() or {}).get('confirm')!='new-design-current-profile':raise ValueError('請明確確認重新製作，這不是舊圖層恢復')
        order=app.commerce.store.order(order_id)
        if not order:return app.no_cache_json({'status':'error','msg':'訂單不存在'},404)
        from print_center import _complete_model_style_profile
        from editable_stickers import public_image, VERSION
        from catalog_products import product_type
        shop=app.cloud_get_json('shop_data',app.DATA_FILE,app.DEFAULT_SHOP_DATA)
        model=next((m for m in shop['models'] if m['id']==order['model_id']),None)
        profile=_complete_model_style_profile(model or {},order['style_id'])
        if not profile:raise ValueError('目前商品缺少完整設定，無法建立獨立重製草稿')
        rows=store.rows(order_id)
        if rows and (len(rows)>1 or not rows[0]['document'].get('legacyOriginal')):raise ValueError('已有設計版本，請重新開啟，避免覆蓋其他店員工作')
        mask=persist_asset(app,order_id,public_image(app,profile['print_line_img']))
        preview=persist_asset(app,order_id,public_image(app,profile['preview_mask_img']))
        d={'version':'5.3.1','render_contract_version':VERSION,'orderDesignVersion':1,'objects':[],'background':'transparent',
           'modelId':order['model_id'],'styleId':order['style_id'],'logicalCanvas':{'width':round(float(profile['print_w'])*3),'height':round(float(profile['print_h'])*3)},
           'production':{'printW':float(profile['print_w']),'printH':float(profile['print_h']),'maskPath':mask},
           'fontHashes':{k:hashlib.sha256((ROOT/v).read_bytes()).hexdigest() for k,v in FONTS.items()},
           'editorContext':{'modelName':order.get('model_name'),'styleName':order.get('style_name'),'productType':product_type(model),'previewPath':preview,'printX':profile.get('print_x',0),'printY':profile.get('print_y',0),'printAngle':profile.get('print_angle',0)},
           'remakeNotice':'全新重製草稿，使用建立草稿時設定；不是舊訂單原圖層恢復'}
        check_restore(d)
        if not rows:
            original=store.append(order_id,0,{'legacyOriginal':True,'design_json':order.get('design_json'),'print_path':order.get('print_path'),'mockup_path':order.get('mockup_path')},actor(),'legacy-original')
            if not original['ok']:raise ValueError('其他店員已建立版本，請重新開啟')
        result=store.append(order_id,1,d,actor(),'explicit-remake')
        if not result['ok']:raise ValueError('其他店員已建立版本，請重新開啟')
        return app.no_cache_json({'status':'success','version':result['version']})

    @app.app.route('/api/admin/order-design/<order_id>/open',methods=['POST'])
    @admin
    def open_work(order_id):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,100}',order_id):raise ValueError('訂單識別無效')
        rows=store.rows(order_id)
        if not rows:
            order=app.commerce.store.order(order_id)
            if not order:return app.no_cache_json({'status':'error','msg':'訂單不存在'},404)
            design=archive(app,order)
            store.append(order_id,0,design,actor(),'original')
            rows=store.rows(order_id)
        latest=rows[-1];check_restore(latest['document'])
        # Verify all referenced objects exist before any editor canvas is opened.
        for path in asset_paths(latest['document']):image_bytes(read(app,path))
        work=signer.dumps({'order':order_id,'version':latest['version'],'actor':actor(),'id':uuid.uuid4().hex})
        return app.no_cache_json({'status':'success','orderId':order_id,'version':latest['version'],'hash':latest['content_hash'],'work':work,
            'design':materialize(order_id,latest['version'],latest['document']),
            'versions':[{k:r[k] for k in ('version','actor','created_at','content_hash')} for r in rows]})

    @app.app.route('/api/admin/order-design/<order_id>/assets/<int:version>/<asset>')
    @admin
    def asset_file(order_id,version,asset):
        row=next((r for r in store.rows(order_id) if r['version']==version and not r['document'].get('legacyOriginal')),None)
        path=next((p for p in asset_paths(row['document']) if hashlib.sha256(p.encode()).hexdigest()==asset),None) if row else None
        if not path:return app.no_cache_json({'status':'error','msg':'素材不存在'},404)
        raw=read(app,path);image_bytes(raw)
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:mime=Image.MIME[image.format]
        response=send_file(io.BytesIO(raw),mimetype=mime)
        response.headers['Cache-Control']='private, no-store'
        response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.app.route('/api/admin/order-design/<order_id>/save',methods=['POST'])
    @admin
    def save_work(order_id):
        data=request.get_json() or {}
        if not isinstance(data,dict) or not isinstance(data.get('work'),str):raise ValueError('缺少有效的編輯工作副本')
        claim=signer.loads(data['work'],max_age=8*3600)
        if claim['order']!=order_id or claim['actor']!=actor():raise ValueError('編輯工作副本不屬於此登入者或訂單')
        rows=store.rows(order_id);base=next((r['document'] for r in rows if r['version']==claim['version']),None)
        if not base:raise ValueError('編輯基準不存在')
        design=validate(copy.deepcopy(data.get('design')))
        validate_guides(design)
        validate_sources(design)
        if any(design.get(k) for k in ('backgroundImage','overlayImage','clipPath')):raise ValueError('不支援額外的畫布外部圖片')
        empty=design.get('emptyTemplateSlots',[])
        if not isinstance(empty,list) or len(empty)>100 or any(not isinstance(o,dict) or o.get('role')!='slot-guide' or not o.get('templateLayerId') for o in empty):raise ValueError('空照片框資料無效')
        for key in ('modelId','styleId','logicalCanvas','fontHashes','layer_contract_version','orderDesignVersion'):
            if design.get(key)!=base.get(key):raise ValueError('禁止修改原訂單型號、畫布或字型契約')
        total=0;pixels=0;seen={}
        for o in nodes(design):
            if o['type']!='image':continue
            token=o.get('sourceRef');c=receipt(app,token,design.get('sourceCheckout'))
            size=o.get('sourceSize') or {'width':o.get('width'),'height':o.get('height')}
            if o.get('sourceSha256')!=c['sha256'] or (size.get('width'),size.get('height'))!=(c['width'],c['height']):raise ValueError('素材尺寸或雜湊不一致')
            for key,extent,limit in (('cropX','width',c['width']),('cropY','height',c['height'])):
                start=o.get(key,0)
                if not isinstance(start,(int,float)) or start<0 or o[extent]<=0 or start+o[extent]>limit+.001:raise ValueError('圖片裁切超出原始素材')
            if token not in seen:
                pixels+=c['width']*c['height']
                from editable_stickers import MAX_SOURCE_PIXELS
                if pixels>MAX_SOURCE_PIXELS:raise ValueError('原始素材總像素過多')
                raw=read(app,stored_path(app,c));total+=len(raw)
                if total>70*1024*1024:raise ValueError('原始素材總容量過大')
                if hashlib.sha256(raw).hexdigest()!=c['sha256'] or image_bytes(raw)!=(c['width'],c['height']):raise ValueError('素材驗證失敗')
                seen[token]=persist_asset(app,order_id,raw)
            o['src']=seen[token];o.pop('sourceRef',None);o.pop('publicSrc',None)
        protect_layers(base,design)
        for key in ('production','editorContext','editorState','templateBinding','remakeNotice','legacyRecovery'):
            if key in base:design[key]=copy.deepcopy(base[key])
            else:design.pop(key,None)
        design.pop('sourceCheckout',None);design.pop('layerSeal',None)
        # Print proofs are server-owned and bind the entire immutable V2 document.
        design.pop('revisionPrint',None)
        from revision_artwork import prepare
        previous=next((r for r in rows if r['request_id']==claim['id']),None)
        # Lost-response retries reuse the committed proof even if Storage or
        # historical job availability changed. append still checks all content.
        if previous:
            if 'revisionPrint' in previous['document']:design['revisionPrint']=copy.deepcopy(previous['document']['revisionPrint'])
        else:design['revisionPrint']=prepare(app,order_id,rows[0]['document'],design)
        result=store.append(order_id,claim['version'],design,actor(),claim['id'])
        if not result['ok']:return app.no_cache_json({'status':'error','msg':'另一位店員已保存新版，或此工作副本已提交不同內容。請重新開啟後再編輯；你的畫布仍保留。'},409)
        next_work=signer.dumps({'order':order_id,'version':result['version'],'actor':actor(),'id':uuid.uuid4().hex})
        return app.no_cache_json({'status':'success','version':result['version'],'hash':digest(design),'work':next_work,'msg':'已另存設計草稿；原生產圖與列印任務未變更'})

    from pixel_order_designs import install as install_pixel
    install_pixel(app,store,admin,actor,signer)
    app.order_designs=store
