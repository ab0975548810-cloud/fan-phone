"""Private, session + checkout bound image receipts. No customer-selected storage paths."""
import hashlib
import hmac
import io
import json
import re
import time
import uuid
from pathlib import Path
from itsdangerous import URLSafeSerializer, BadSignature
from flask import request, session
from PIL import Image
from PIL.PngImagePlugin import PngInfo

MAX_FILE_BYTES = 24 * 1024 * 1024  # multipart fits the unchanged 36 MB Flask gate
TTL = 24 * 3600
PREFIX = 'design-temp'


def signer(app):
    return URLSafeSerializer(app.app.secret_key, salt='design-source-v1')


def owner(app):
    from security_perf import _cid
    return hmac.new(str(app.app.secret_key).encode(), ('design-source:'+_cid()).encode(), hashlib.sha256).hexdigest()


def checkout(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('來源上傳識別無效')
    return value


def stored_path(app, claims):
    path=f'{PREFIX}/{claims["expires"]}/{claims["id"]}.png'
    return path if app.USE_SUPABASE else path.replace('/', '_')


def receipt(app, token, checkout_id):
    try:
        claims=signer(app).loads(token)
        if (claims['owner']!=owner(app) or claims['checkout']!=checkout(checkout_id)
                or claims['expires']<=time.time() or not re.fullmatch(r'[a-f0-9]{32}',claims['id'])):
            raise ValueError('原始素材不屬於本次使用者／結帳，或已過期，請重新送出')
        return claims
    except (BadSignature, KeyError, TypeError) as exc:
        raise ValueError('原始素材引用無效') from exc


def read(app, path):
    if app.USE_SUPABASE:
        return app.SUPABASE.storage.from_(app.SUPABASE_PRIVATE_BUCKET).download(path)
    return (Path(app.SAVE_DIR)/path).read_bytes()


def existing_order(app,order_id):
    if hasattr(app,'commerce'):return app.commerce.store.order(order_id)
    if app.USE_SUPABASE:
        rows=app.SUPABASE.table('orders').select('id').eq('id',order_id).limit(1).execute().data
        return rows[0] if rows else None
    return (Path(app.SAVE_DIR)/(order_id+'_info.json')).exists()


def cleanup_expired(app, now=None):
    """Bounded oldest-first janitor; touches only expired temporary source namespace."""
    now=int(time.time() if now is None else now)
    if app.USE_SUPABASE:
        bucket=app.SUPABASE.storage.from_(app.SUPABASE_PRIVATE_BUCKET)
        folders=bucket.list(PREFIX, {'limit':20,'sortBy':{'column':'name','order':'asc'}})
        for folder in folders:
            name=folder['name']
            if not name.isdigit() or int(name)>now:continue
            items=bucket.list(f'{PREFIX}/{name}',{'limit':100})
            paths=[f'{PREFIX}/{name}/{item["name"]}' for item in items if re.fullmatch(r'[a-f0-9]{32}\.png',item['name'])]
            if paths:bucket.remove(paths)
    else:
        # Sort by expiry, not object access time; restart does not reset expiration.
        candidates=sorted(Path(app.SAVE_DIR).glob(PREFIX+'_*.png'))
        for path in candidates[:200]:
            match=re.fullmatch(PREFIX+r'_(\d+)_([a-f0-9]{32})\.png',path.name)
            if match and int(match[1])<=now:path.unlink(missing_ok=True)
    cleanup_pending(app,now)


def cleanup_plan(app,order_id):
    # The existing private artwork bucket may allow only image MIME types.
    # Use a real tiny PNG with private metadata, never JSON mislabeled as PNG;
    # this rollback intent is not production artwork or a customer design source.
    expires=((int(time.time())+TTL+3599)//3600)*3600
    intended=f'design-cleanup/{expires}/{order_id}-{uuid.uuid4().hex}.png'
    path=intended if app.USE_SUPABASE else intended.replace('/','_')
    metadata=PngInfo();metadata.add_text('benfuwan_cleanup',json.dumps({'order_id':order_id}))
    raw=io.BytesIO();Image.new('RGBA',(1,1),(0,0,0,0)).save(raw,'PNG',pnginfo=metadata)
    try:app.upload_private_bytes(intended,raw.getvalue(),'image/png')
    except Exception:
        app.delete_private_path(path)
        raise
    return path


def cleanup_pending(app,now):
    """Retry failed storage deletions and unknown DB commits after durable expiration."""
    paths=[]
    if app.USE_SUPABASE:
        bucket=app.SUPABASE.storage.from_(app.SUPABASE_PRIVATE_BUCKET)
        for row in bucket.list('design-cleanup',{'limit':20,'sortBy':{'column':'name','order':'asc'}}):
            name=row['name']
            if name.isdigit() and int(name)<=now:
                paths.extend(f'design-cleanup/{name}/{r["name"]}' for r in bucket.list('design-cleanup/'+name,{'limit':100}) if re.fullmatch(r'[A-Za-z0-9-]+\.(?:png|json)',r['name']))
    else:
        candidates=[p for p in Path(app.SAVE_DIR).glob('design-cleanup_*') if p.suffix in ('.png','.json')]
        for path in sorted(candidates)[:200]:
            parts=path.name.split('_',2)
            if parts[1].isdigit() and int(parts[1])<=now:paths.append(path.name)
    from editable_stickers import delete_order_sources
    for path in paths:
        # On DB outage, keep the private cleanup record. Never guess a commit failed.
        raw=read(app,path)
        if path.endswith('.png'):
            with Image.open(io.BytesIO(raw)) as marker:
                if marker.format!='PNG' or marker.size!=(1,1):raise ValueError('invalid private cleanup marker')
                record=json.loads(marker.info['benfuwan_cleanup'])
        else:record=json.loads(raw)  # Retry existing JSON intents without migration.
        order_id=record['order_id']
        if not isinstance(order_id,str) or not re.fullmatch(r'[A-Za-z0-9-]{1,100}',order_id):raise ValueError('invalid cleanup order identity')
        if existing_order(app,order_id):
            app.delete_private_path(path);continue
        delete_order_sources(app,{'id':order_id})
        for name in ('print.png','preview.png'):
            file=f'orders/{order_id}/{name}';file=file if app.USE_SUPABASE else file.replace('/','_')
            if not app.delete_private_path(file):raise RuntimeError('private cleanup unavailable')
        app.delete_private_path(path)


def release(app, design):
    if not isinstance(design,dict):return
    from editable_stickers import nodes, configured
    if not configured(design):return
    try:items=list(nodes(design))
    except ValueError:return
    for item in items:
        if item.get('sourceRef'):
            try:claims=receipt(app,item['sourceRef'],design.get('sourceCheckout'));app.delete_private_path(stored_path(app,claims))
            except ValueError:pass  # Never delete a foreign or arbitrary client-supplied path.


def identity(app, design):
    """Stable order retry identity ignores only authenticated temporary receipt tokens."""
    import copy
    from editable_stickers import configured,nodes
    if not configured(design):return design
    result=copy.deepcopy(design)
    for item in nodes(result):
        if item['type']!='image':continue
        claim=receipt(app,item.get('sourceRef'),result.get('sourceCheckout'))
        intrinsic=item.get('sourceSize') or {'width':item.get('width'),'height':item.get('height')}
        if item.get('src') or item.get('sourceSha256')!=claim['sha256'] or (intrinsic.get('width'),intrinsic.get('height'))!=(claim['width'],claim['height']):raise ValueError('原始素材引用無效')
        item.pop('sourceRef')
    result.pop('sourceCheckout',None)
    return result


def install(app):
    @app.app.route('/api/design-sources',methods=['POST'])
    def upload_design_source():
        path=None
        try:
            from security_perf import _limited
            blocked,_=_limited('design-source',owner(app),60,1800)
            if blocked:return app.no_cache_json({'status':'error','msg':'來源上傳過於頻繁，請稍後再試'},429)
            checkout_id=checkout(request.form.get('checkout'))
            file=request.files.get('file')
            if not file:raise ValueError('缺少原始圖片')
            raw=file.stream.read(MAX_FILE_BYTES+1)
            if len(raw)>MAX_FILE_BYTES:raise ValueError('單張原始素材上限為 24MB')
            from editable_stickers import image_bytes
            width,height=image_bytes(raw)
            with Image.open(io.BytesIO(raw)) as image:
                mime=Image.MIME[image.format]
                if file.mimetype!=mime:raise ValueError('圖片 MIME 與實際格式不一致')
                # Client uploads lossless PNG; renderer's image reader remains PNG-only.
                if image.format!='PNG':raise ValueError('請上傳 PNG 原始素材')
            expires=((int(time.time())+TTL+3599)//3600)*3600
            claims={'id':uuid.uuid4().hex,'owner':owner(app),'checkout':checkout_id,'expires':expires,
                    'sha256':hashlib.sha256(raw).hexdigest(),'width':width,'height':height,'bytes':len(raw)}
            path=stored_path(app,claims)
            try:cleanup_expired(app)
            except Exception:app.app.logger.warning('temporary design source cleanup unavailable')
            # Track planned path too, covering an upload committed but response lost.
            app.upload_private_bytes(f'{PREFIX}/{expires}/{claims["id"]}.png',raw)
            return app.no_cache_json({'status':'success','sourceRef':signer(app).dumps(claims),
                'sha256':claims['sha256'],'width':width,'height':height,'bytes':len(raw),'expiresAt':expires})
        except ValueError as exc:
            if path:app.delete_private_path(path)
            return app.no_cache_json({'status':'error','msg':str(exc)},400)
        except Exception:
            if path:app.delete_private_path(path)
            return app.no_cache_json({'status':'error','msg':'原始素材暫時無法保存，請重試'},503)

    @app.app.route('/api/design-sources/release',methods=['POST'])
    def release_design_sources():
        data=request.get_json(silent=True) or {}
        release(app,data)
        return app.no_cache_json({'status':'success'})
