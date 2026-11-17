"""Native-pixel repairs: immutable base, explicit edits, no catalog geometry."""
import base64
import copy
import hashlib
import io
import math
import os
import re
import uuid
import threading
from PIL import Image, ImageChops, ImageCms, PngImagePlugin
import struct
from flask import request, send_file
from design_sources import read
from editable_stickers import image_bytes, nodes, validate
from order_designs import digest, persist_asset

FIELDS=('sku_id','width_mm','height_mm','left_mm','top_mm','angle','copies','channel','spot_color')
_PIXEL_SLOT=threading.BoundedSemaphore(1)


def sha(raw):return hashlib.sha256(raw).hexdigest()


def png(raw, size=None, dpi=False):
    image_bytes(raw)
    im=Image.open(io.BytesIO(raw))
    if im.format!='PNG' or im.width*im.height>18000000:raise ValueError('只接受安全尺寸的原生產 PNG')
    if raw[24]>8:raise ValueError('原圖超過 8 位元色深，禁止自動降色深修補')
    if im.mode not in ('RGB','RGBA','P','L','LA'):raise ValueError('原圖色彩位深需先核對，禁止自動轉換')
    if im.info.get('icc_profile'):
        if len(im.info['icc_profile'])>4000000:raise ValueError('ICC 設定容量無效')
        ImageCms.ImageCmsProfile(io.BytesIO(im.info['icc_profile']))
    if size and im.size!=tuple(size):raise ValueError('修補圖尺寸不符，禁止縮放原圖')
    if dpi and any(abs(n-720)>.1 for n in im.info.get('dpi',(0,0))):raise ValueError('原生產圖缺少可驗證的 720 DPI，禁止推測尺寸')
    return im.convert('RGBA')


def decode(value):
    if not isinstance(value,str) or not value.startswith('data:image/png;base64,') or len(value)>70000000:raise ValueError('修補圖格式或容量無效')
    return base64.b64decode(value.split(',',1)[1],validate=True)


def compose(raw, overlay_raw, erase_raw):
    if not _PIXEL_SLOT.acquire(timeout=5):raise ValueError('像素驗證忙碌，請稍後重試；原圖未變更')
    try:return _compose(raw,overlay_raw,erase_raw)
    finally:_PIXEL_SLOT.release()


def _compose(raw, overlay_raw, erase_raw):
    base=png(raw,dpi=True);overlay=png(overlay_raw,base.size);erase=png(erase_raw,base.size)
    # Safari can embed an ICC profile in canvas PNGs. Convert only NEW pixels
    # into the original color space; never transform the original RGBA buffer.
    if overlay.info.get('icc_profile')!=base.info.get('icc_profile'):
        profile=lambda im:ImageCms.ImageCmsProfile(io.BytesIO(im.info['icc_profile'])) if im.info.get('icc_profile') else ImageCms.createProfile('sRGB')
        overlay=ImageCms.profileToProfile(overlay,profile(overlay),profile(base),outputMode='RGBA')
    alpha=base.getchannel('A');allowed=alpha.point(lambda x:255 if x else 0)
    # No historical mask is inferred: fully transparent original pixels stay exact.
    overlay.putalpha(ImageChops.multiply(overlay.getchannel('A'),allowed))
    erased=ImageChops.multiply(erase.getchannel('A').point(lambda x:255 if x else 0),allowed)
    touched=ImageChops.lighter(overlay.getchannel('A').point(lambda x:255 if x else 0),erased)
    merged=Image.alpha_composite(base,overlay)
    merged.putalpha(ImageChops.subtract(alpha,erased))
    output=Image.composite(merged,base,touched)
    outside=touched.point(lambda x:0 if x else 255)
    for band in range(4):
        if ImageChops.multiply(ImageChops.difference(base.getchannel(band),output.getchannel(band)),outside).getbbox():raise ValueError('未修改區域像素驗證失敗')
    meta=PngImagePlugin.PngInfo()
    if 'gamma' in base.info:meta.add(b'gAMA',struct.pack('>I',round(base.info['gamma']*100000)))
    if 'srgb' in base.info:meta.add(b'sRGB',bytes([base.info['srgb']]))
    out=io.BytesIO();output.save(out,'PNG',dpi=(720,720),icc_profile=base.info.get('icc_profile'),pnginfo=meta)
    return out.getvalue(),{'bounds':touched.getbbox(),'changedPixels':sum(touched.histogram()[1:]),'unchangedRGBA':True,'alphaExpansion':False}


def historical_profile(app, order, raw, size):
    found=[]
    for job in app.print_center.store.jobs_for_order(order['id']):
        if job.get('artwork_sha256')!=sha(raw) or not job.get('profile_complete'):continue
        if any(job.get(k) is None for k in FIELDS):continue
        try:
            if any(abs(float(job[k])*720/25.4-size[i])>1 for i,k in enumerate(('width_mm','height_mm'))):continue
            if not all(math.isfinite(float(job[k])) for k in ('width_mm','height_mm','left_mm','top_mm','angle')):continue
        except (TypeError,ValueError):continue
        found.append({'sourceJobId':job['id'],**{k:job[k] for k in FIELDS}})
    if not found:return None
    if len({digest({k:p[k] for k in FIELDS}) for p in found})!=1:return None
    return found[0]


def artwork_document(document):
    """Normalize only the two server-generated, immutable artwork contracts."""
    if document.get('mode')=='pixel-v1':return document
    proof=document.get('revisionPrint') or {}
    if not isinstance(proof,dict):raise ValueError('修改版生產圖驗證資料無效')
    if proof.get('mode')=='layered-v1':return proof
    raise ValueError('此版本尚無可比較的生產圖；請先儲存修改')


def install(app, store, admin, actor, signer):
    root='/api/admin/order-design/<order_id>/pixel'
    revision_root='/api/admin/order-design/<order_id>/revision'
    def rows(order_id):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,100}',order_id):raise ValueError('訂單識別無效')
        return store.rows(order_id)
    def row(order_id,version):
        r=next((r for r in rows(order_id) if r['version']==version),None)
        if not r or r['document'].get('mode')!='pixel-v1':raise ValueError('找不到像素修補版本')
        return r
    def asset_url(order_id,version,name):return f'/api/admin/order-design/{order_id}/pixel/assets/{version}/{name}'
    def opened(order_id,r):
        d=copy.deepcopy(r['document'])
        for o in nodes({'objects':d.get('objects',[])}):
            if o.get('type')=='image':o['src']=asset_url(order_id,r['version'],sha(o['src'].encode()))
        for key in ('basePath','outputPath'):
            d[key]=asset_url(order_id,r['version'],key)
        token=signer.dumps({'pixel':True,'order':order_id,'version':r['version'],'hash':r['content_hash'],'actor':actor(),'id':uuid.uuid4().hex})
        return app.no_cache_json({'status':'success','design':d,'version':r['version'],'hash':r['content_hash'],'work':token})

    @app.app.route(root+'/open',methods=['POST'])
    @admin
    def open_pixel(order_id):
        versions=rows(order_id)
        if not versions:
            order=app.commerce.store.order(order_id)
            if not order:raise ValueError('訂單不存在')
            raw=read(app,order.get('print_path'));im=png(raw,dpi=True)
            path=persist_asset(app,order_id,raw)
            d={'mode':'pixel-v1','basePath':path,'baseSha':sha(raw),'outputPath':path,'outputSha':sha(raw),'size':list(im.size),'dpi':720,'profile':historical_profile(app,order,raw,im.size),'objects':[],'factor':max(1,math.ceil(max(im.size)/1000))}
            store.append(order_id,0,d,actor(),'pixel-original')
            versions=rows(order_id)
        if versions[-1]['document'].get('mode')!='pixel-v1':raise ValueError('此訂單已有其他編輯版本，請先核對，避免覆蓋店員工作')
        return opened(order_id,versions[-1])

    @app.app.route(root+'/assets/<int:version>/<name>')
    @admin
    def asset(order_id,version,name):
        d=row(order_id,version)['document']
        paths={sha(o['src'].encode()):o['src'] for o in nodes({'objects':d['objects']}) if o.get('type')=='image'}
        paths.update({k:d[k] for k in ('basePath','outputPath')})
        if name not in paths:raise ValueError('素材不存在')
        response=send_file(io.BytesIO(read(app,paths[name])),mimetype='image/png');response.headers['Cache-Control']='private, no-store';return response

    @app.app.route(root+'/save',methods=['POST'])
    @admin
    def save(order_id):
        data=request.get_json() or {};claim=signer.loads(data.get('work',''),max_age=8*3600)
        if not claim.get('pixel') or claim['order']!=order_id or claim['actor']!=actor():raise ValueError('編輯工作副本不符')
        base=row(order_id,claim['version'])['document'];raw=read(app,base['basePath'])
        if sha(raw)!=base['baseSha']:raise ValueError('V1 原圖雜湊不符')
        overlay=decode(data.get('overlay'));erase=decode(data.get('erase'))
        output,proof=compose(raw,overlay,erase)
        if not proof['bounds']:raise ValueError('沒有可保存的修補內容')
        objects=copy.deepcopy(data.get('objects'))
        validate({'render_contract_version':'editable-text-v1','orderDesignVersion':1,'logicalCanvas':dict(zip(('width','height'),[n/base['factor'] for n in base['size']])),'objects':objects})
        total=0
        for o in nodes({'objects':objects}):
            if o.get('type')=='image':
                source=decode(o.get('src'));total+=len(source)
                if total>70000000:raise ValueError('新增素材容量過大')
                o['src']=persist_asset(app,order_id,source)
        d={**base,'objects':objects,'outputPath':persist_asset(app,order_id,output),'outputSha':sha(output),'proof':proof}
        result=store.append(order_id,claim['version'],d,actor(),claim['id'])
        if not result['ok']:return app.no_cache_json({'status':'error','msg':'其他店員已保存，請重新開啟；目前畫布仍保留'},409)
        return opened(order_id,row(order_id,result['version']))

    @app.app.route(revision_root+'/review',methods=['POST'])
    @admin
    def review_revision(order_id):
        data=request.get_json() or {}
        r=next((r for r in rows(order_id) if r['version']==data.get('version') and r['content_hash']==data.get('hash')),None)
        if not r:raise ValueError('設計版本已變更，請重新開啟後比較')
        d=artwork_document(r['document'])
        if not d.get('outputPath'):raise ValueError(d.get('reason') or '缺少可比較的生產圖')
        return app.no_cache_json({'status':'success','version':r['version'],'hash':r['content_hash'],
            'design':{'basePath':f'/api/admin/order-design/{order_id}/revision/assets/{r["version"]}/basePath',
                      'outputPath':f'/api/admin/order-design/{order_id}/revision/assets/{r["version"]}/outputPath',
                      'profile':bool(d.get('profile'))},
            'enabled':os.environ.get('ORDER_PIXEL_REPRINT_ENABLED')=='true'})

    @app.app.route(revision_root+'/assets/<int:version>/<name>')
    @admin
    def revision_asset(order_id,version,name):
        r=next((r for r in rows(order_id) if r['version']==version),None)
        if not r or name not in ('basePath','outputPath'):raise ValueError('生產圖不存在')
        d=artwork_document(r['document']);path=d.get(name)
        if not path:raise ValueError('生產圖尚未通過驗證')
        raw=read(app,path)
        if sha(raw)!=d['baseSha' if name=='basePath' else 'outputSha']:raise ValueError('生產圖雜湊不符')
        png(raw,d['size'],True)
        response=send_file(io.BytesIO(raw),mimetype='image/png');response.headers['Cache-Control']='private, no-store';response.headers['X-Content-Type-Options']='nosniff';return response

    def print_version(order_id,data):
        if os.environ.get('ORDER_PIXEL_REPRINT_ENABLED')!='true':raise ValueError('修改版送印尚未啟用；可先保存與比較')
        versions=rows(order_id)
        r=next((r for r in versions if r['version']==int(data.get('version',0))),None)
        if not r:raise ValueError('找不到設計版本')
        if r['version']<2 or r['content_hash']!=data.get('hash'):raise ValueError('請重新比較並確認此版本')
        if versions[-1]['version']!=r['version']:raise ValueError('已有更新設計版本，請重新比較並確認')
        d=artwork_document(r['document'])
        if not d.get('profile'):raise ValueError('缺少與 V1 雜湊相符的歷史列印定位，禁止送印')
        raw=read(app,d['outputPath'])
        if sha(raw)!=d['outputSha']:raise ValueError('V2 生產圖雜湊不符')
        png(raw,d['size'],True)
        original=read(app,d['basePath'])
        if sha(original)!=d['baseSha']:raise ValueError('V1 生產圖雜湊不符')
        png(original,d['size'],True)
        app.print_center._assert_order_printable(app.print_center._order(order_id))
        return r

    @app.app.route(revision_root+'/confirm',methods=['POST'])
    @app.app.route(root+'/confirm',methods=['POST'])
    @admin
    def confirm(order_id):
        data=request.get_json() or {};r=print_version(order_id,data)
        if data.get('confirm')!='compared-v1-v2':raise ValueError('請先比較 V1／V2 並人工確認')
        reason=str(data.get('reason') or '').strip();cost=data.get('costCents')
        if not reason or len(reason)>500 or type(cost)!=int or not 0<=cost<=100000000:raise ValueError('請填寫重印原因及有效成本')
        from pixel_print_store import authorize
        result=authorize(app,order_id,r,actor(),reason,cost)
        if not result.get('ok'):raise ValueError('版本已變更或已有未結束／不明列印任務，請先查核')
        return app.no_cache_json({'status':'success','jobId':result['job']['id'],'msg':'已建立獨立任務，尚未傳送銳印'})

    @app.app.route(revision_root+'/send',methods=['POST'])
    @app.app.route(root+'/send',methods=['POST'])
    @admin
    def send(order_id):
        data=request.get_json() or {};r=print_version(order_id,data)
        key='pixel-'+digest([order_id,r['version'],r['content_hash']])[:64]
        record=app.print_center.store.request(key)
        if not record or record['request_hash']!=r['content_hash']:raise ValueError('此版本尚未人工確認')
        from print_center import PrintError
        try:job=app.print_center.send(record['job_id'],'pixel-send-'+digest(key)[:64],manual_reprint=True)
        except PrintError as exc:return app.no_cache_json({'status':'error','msg':str(exc),'code':exc.code},exc.status)
        if job['state']=='PREPARED':return app.no_cache_json({'status':'error','msg':'此版本未傳送；請到列印中心查核阻擋原因，勿重複建立送印任務','code':'REVISION_SEND_NOT_STARTED'},409)
        return app.no_cache_json({'status':'success','jobId':job['id'],'state':job['state']})
