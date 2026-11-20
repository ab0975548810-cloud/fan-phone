"""Read source-order artwork without ever initializing or appending a design version."""
import hashlib
import io
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path
import re

from PIL import Image

from design_sources import read


def export_artwork(app, order_id):
    if not re.fullmatch(r'[A-Za-z0-9-]{1,100}',order_id):
        raise ValueError('訂單識別無效')
    fields=('id','model_id','model_name','style_id','style_name','print_path','mockup_path','design_json')
    if app.USE_SUPABASE:
        rows=app.SUPABASE.table('orders').select(','.join(fields)).eq('id',order_id).limit(1).execute().data
        order=next(iter(rows),None)
    else:
        with closing(sqlite3.connect(Path(app.commerce.store.path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            result = db.execute('select value from orders where id=?',(order_id,)).fetchone()
        order = json.loads(result[0]) if result else None
    if not order or order['id']!=order_id:
        raise ValueError('找不到來源訂單')
    manifest={field:order[field] for field in fields[1:5]}
    files={}
    for kind,field in [('print','print_path'),('preview','mockup_path')]:
        expected=f'orders/{order_id}/{kind}.png'
        if not app.USE_SUPABASE:
            expected=expected.replace('/','_')
        if order.get(field)!=expected:
            raise ValueError('來源圖檔路徑與訂單不符')
        raw=read(app,expected)
        if len(raw)>48*1024*1024:
            raise ValueError('來源圖檔過大')
        with Image.open(io.BytesIO(raw)) as image:
            if image.format!='PNG' or image.width*image.height>18000000:
                raise ValueError('來源圖片格式或尺寸無效')
            size=image.size
            dpi=image.info.get('dpi',())
            image.verify()
        sha=hashlib.sha256(raw).hexdigest()
        files[sha]=raw
        manifest[kind]=dict(sha256=sha,size=size,dpi=dpi)
    manifest['review'] = []
    if len(manifest['print']['dpi']) != 2 or any(abs(v - 720) > .1 for v in manifest['print']['dpi']):
        raise ValueError('原生產圖無法驗證為 720 DPI')
    design = order.get('design_json')
    try:
        manifest['design'], dependencies = export_layers(app, order_id, design, manifest, files)
        files.update(dependencies)
    except (ValueError, KeyError, TypeError, OSError):
        manifest['review'].append('原始圖層或封存素材不完整，保留原始生產圖進行像素修改')
    profile = read_profile(app, order_id, manifest['print'])
    if profile:
        manifest['profile'] = {k: profile[k] for k in ('width_mm','height_mm','left_mm','top_mm','angle')}
    else:
        manifest['review'].append('缺少與原圖雜湊及尺寸吻合的歷史列印定位')
    if isinstance(design,dict):
        production, context = design.get('production') or {}, design.get('editorContext') or {}
        try:
            prefix = f'orders/{order_id}/sources/' if app.USE_SUPABASE else f'orders_{order_id}_sources_'
            path = production['maskPath']
            if not path.startswith(prefix) or not re.fullmatch(r'[A-Za-z0-9_-]+\.png',path[len(prefix):]):
                raise ValueError()
            raw=read(app,path)
            from editable_stickers import image_bytes
            image_bytes(raw)
            sha=hashlib.sha256(raw).hexdigest()
            geometry=[float(production[k]) for k in ('printW','printH')]+[float(context[k]) for k in ('printX','printY','printAngle')]
            if not all(map(math.isfinite,geometry)) or design.get('modelId')!=order['model_id'] or design.get('styleId')!=order['style_id']:
                raise ValueError()
            if any(abs(mm*720/25.4-px)>1 for mm,px in zip(geometry[:2],manifest['print']['size'])):
                raise ValueError()
            if profile and any(abs(a-profile[k])>.05 for a,k in zip(geometry,PROFILE_FIELDS)):
                raise ValueError()
            manifest['alignment']=dict(sha256=sha,geometry=geometry)
            files[sha]=raw
        except (ValueError,TypeError,AttributeError,KeyError,OSError):
            pass
    if 'alignment' not in manifest:
        manifest['review'].append('缺少可核對的封存刀模與原始列印座標')
    return manifest,files


PROFILE_FIELDS=('width_mm','height_mm','left_mm','top_mm','angle')


def read_profile(app,order_id,art):
    if not hasattr(app,'print_center'):
        return None
    cols=','.join(PROFILE_FIELDS)
    if app.USE_SUPABASE:
        rows=(app.SUPABASE.table('print_jobs').select(cols).eq('order_id',order_id)
              .eq('artwork_sha256',art['sha256']).eq('profile_complete',True).eq('manual_independent',False).execute().data)
    else:
        with closing(sqlite3.connect(Path(app.print_center.store.path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            if not db.execute("select 1 from sqlite_master where name='print_jobs'").fetchone():
                return None
            rows=db.execute('select '+cols+' from print_jobs where order_id=? and artwork_sha256=? and profile_complete=1 and manual_independent=0',
                            (order_id,art['sha256'])).fetchall()
    try:
        values={tuple(float(row[k]) for k in PROFILE_FIELDS) for row in rows}
        if len(values)==1:
            geometry=values.pop()
            if all(map(math.isfinite,geometry)) and all(abs(mm*720/25.4-px)<=1 for mm,px in zip(geometry[:2],art['size'])):
                return dict(zip(PROFILE_FIELDS,geometry))
    except (ValueError,TypeError):
        pass
    return None


# Export only editor properties. Extra commerce data or upload receipts cannot
# become part of the handoff, even when present inside the stored design JSON.
OBJECT_KEYS = set("""type version originX originY left top width height scaleX scaleY angle skewX skewY flipX flipY
    opacity visible fill stroke strokeWidth strokeDashArray strokeLineCap strokeDashOffset strokeLineJoin
    strokeUniform strokeMiterLimit paintFirst fillRule globalCompositeOperation backgroundColor shadow
    rx ry radius startAngle endAngle x1 y1 x2 y2 points x y path pathOffset cropX cropY src crossOrigin
    objects clipPath inverted absolutePositioned text fontFamily fontSize fontWeight fontStyle lineHeight
    charSpacing textAlign direction underline overline linethrough textBackgroundColor styles deltaY
    splitByGrapheme minWidth lockMovementX lockMovementY lockScalingX lockScalingY lockRotation selectable
    evented hasControls hasBorders role slotId isTplBg isSlot bfScaleBaseX bfScaleBaseY materialType
    editableStickerInstanceId editableStickerId textArea requestedFontSize orderOutlineSourceId id
    sourceSha256 sourceSize aiBackgroundRemoved templateLayerId templateRole templatePermissions
    color blur offsetX offsetY affectStroke filters topLeft bottomRight layerId layerInstanceId
    templateApplicationId layerName assetId duplicateOf normalizedGeometry zIndex adaptationRole locked canMove
    canScale canRotate canDelete canDuplicate canEdit templateSlot slotMeta layer_contract_version
    start end widthRatio heightRatio aiOutlineStyle aiOutlineStrength aiOutlineWidth aiOutlineColor
    aiRemovalMode offset gradientUnits gradientTransform colorStops coords x1 y1 x2 y2 offsetX offsetY""".split())


def export_layers(app, order_id, design, manifest, files):
    from order_designs import asset_paths, check_restore
    from editable_stickers import image_bytes
    check_restore(design)
    if design['modelId'] != manifest['model_id'] or design['styleId'] != manifest['style_id']:
        raise ValueError('型號或殼款不符')
    if design.get('layer_contract_version'):
        from multilayer_templates import verify_seal
        verify_seal(app, design, order_id)
    prefix = f'orders/{order_id}/sources/' if app.USE_SUPABASE else f'orders_{order_id}_sources_'
    mapping, assets = {}, {}
    total = sum(map(len, files.values()))
    for path in asset_paths(design):
        if not path.startswith(prefix) or not re.fullmatch(r'[A-Za-z0-9_.-]+',path[len(prefix):]) or '..' in path:
            raise ValueError('素材歸屬不符')
        raw = read(app,path)
        image_bytes(raw)
        sha = hashlib.sha256(raw).hexdigest()
        if sha not in assets and sha not in files:
            total += len(raw)
            if total > 94 * 1024 * 1024:
                raise ValueError('快照素材總量過大')
            assets[sha] = raw
        mapping[path] = sha

    def layer(value):
        if isinstance(value, list):
            return [layer(item) for item in value]
        if isinstance(value, dict):
            result = {}
            for k,v in value.items():
                if k in ('publicSrc','originalName','maskUrl','sourceRef','sourceCheckout'):
                    continue
                if k not in OBJECT_KEYS and not k.isdigit():
                    raise ValueError('圖層含未支援的屬性')
                result[k] = mapping[v] if k == 'src' else layer(v)
            return result
        if isinstance(value,str) and ('://' in value or value.startswith(('data:','blob:','//'))):
            raise ValueError('禁止外部資源')
        return value

    allowed = ('version','modelId','styleId','render_contract_version','orderDesignVersion','background','fontHashes')
    result = {key:design[key] for key in allowed if key in design}
    result['fontHashes'] = {k:design['fontHashes'][k] for k in __import__('editable_stickers').FONTS}
    result['logicalCanvas'] = {k:design['logicalCanvas'][k] for k in ('width','height')}
    for key in ('objects','sourceAssets','editorGuides','emptyTemplateSlots'):
        if key in design:
            result[key] = layer(design[key])
    production, ctx = design['production'], design['editorContext']
    result['production'] = {k:production[k] for k in ('printW','printH')}
    result['production']['maskPath'] = mapping[production['maskPath']]
    result['editorContext'] = {k:ctx[k] for k in ('productType','printX','printY','printAngle')}
    result['editorContext']['previewPath'] = mapping[ctx['previewPath']]
    if design.get('layer_contract_version'):
        result['layer_contract_version'] = design['layer_contract_version']
        binding = {k:design['templateBinding'][k] for k in ('id','hash','modelId','styleId','applicationId','geometryHash')
                   if k in design['templateBinding']}
        result['templateBinding'] = binding
        state = design['editorState']
        result['editorState'] = dict(version='multilayer-v1',id=binding['id'], applicationId=binding['applicationId'],
                                     binding=binding,initial=layer(state['initial']),sourceAssets=layer(state.get('sourceAssets',[])))
    return result, assets
