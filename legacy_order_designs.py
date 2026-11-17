"""Read-only legacy evidence verifier. No live catalog fallback or business writes."""
import base64
import copy
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path
from PIL import Image
from editable_stickers import nodes, ROOT, VERSION, image_bytes, numeric, MAX_BYTES, MAX_SOURCE_PIXELS, _RENDER_SLOT
from order_designs import digest, check_restore, asset_paths, persist_asset
from design_sources import read


def classify(order):
    design=order.get('design_json')
    if not isinstance(design,dict):return 'unrecoverable','沒有原始設計資料，成品 PNG 不能還原獨立圖層'
    if design.get('truncated') or design.get('manifestOnly'):return 'unrecoverable','設計清單已截斷，無法確定全部圖層'
    try:
        images=[o for o in nodes(design) if o.get('type')=='image']
    except ValueError:return 'unrecoverable','設計圖層結構無效'
    if any(not o.get('src') for o in images):return 'unrecoverable','原始圖片來源已從訂單移除；需要原始設計備份，不能以成品圖代替'
    if any(str(o['src']).startswith('blob:') for o in images):return 'unrecoverable','圖片只保留原裝置 blob 暫存網址，其他裝置無法恢復'
    try:check_restore(design)
    except ValueError:return 'needs_evidence','尚缺訂單當時的畫布、刀模／模板與字型證據；不能套用目前設定'
    return 'complete','完整快照仍須驗證素材可讀取'


def evidence(order):
    root=os.environ.get('ORDER_DESIGN_HISTORY_DIR')
    if not root:raise ValueError(classify(order)[1])
    folder=(Path(root)/order['id']).resolve()
    if folder.parent!=Path(root).resolve():raise ValueError('歷史證據路徑無效')
    path=folder/'manifest.json'
    if not path.is_file():raise ValueError(classify(order)[1])
    manifest=json.loads(path.read_text('utf-8'))
    if manifest.get('orderId')!=order['id'] or manifest.get('originalDesignHash')!=digest(order.get('design_json')):
        raise ValueError('歷史證據不屬於此訂單或原始設計已改變')
    if not manifest.get('archiveReference') or not manifest.get('archivedAt'):raise ValueError('缺少可追溯的歷史備份識別')
    return folder,manifest


def verified(order,app):
    """Return a candidate and bytes only. Caller archives after every check passes."""
    category,reason=classify(order)
    if category=='unrecoverable':raise ValueError(reason)
    folder,m=evidence(order)
    candidate=copy.deepcopy(order['design_json'])
    # Never replace authored objects/geometry from a proposed replacement design.
    for key in ('logicalCanvas','production','editorContext','fontHashes','templateBinding','editorState','layer_contract_version'):
        if key not in candidate and key in m:candidate[key]=copy.deepcopy(m[key])
    candidate.update(render_contract_version=VERSION,orderDesignVersion=1,modelId=order['model_id'],styleId=order['style_id'])
    assets={};total=0;pixels=0
    for name,expected in m.get('assets',{}).items():
        if not re.fullmatch(r'[A-Za-z0-9_-]+\.(png|jpg|jpeg|webp)',name):raise ValueError('歷史素材檔名無效')
        path=(folder/name).resolve()
        if path.parent!=folder or not path.is_file():raise ValueError('歷史原始素材已不存在')
        total+=path.stat().st_size
        if total>MAX_BYTES:raise ValueError('歷史素材總容量超出安全範圍')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('歷史素材雜湊不一致')
        w,h=image_bytes(raw);pixels+=w*h
        if pixels>MAX_SOURCE_PIXELS:raise ValueError('歷史素材總像素超出安全範圍')
        assets[name]=raw
    for o in nodes(candidate):
        if o.get('type')=='image':
            original=o.get('src');mapped=m.get('sourceMap',{}).get(original)
            if mapped not in assets:raise ValueError('歷史圖層缺少經雜湊驗證的原始素材')
            o['src']=mapped
    state=candidate.get('editorState')
    if state:
        for o in nodes({'objects':state.get('initial',[]),'sourceAssets':state.get('sourceAssets',[])}):
            if o.get('type')=='image':o['src']=m.get('sourceMap',{}).get(o.get('src'),o.get('src'))
    check_restore(candidate)
    if candidate.get('layer_contract_version'):
        from order_designs import protect_layers
        if state.get('binding')!=candidate.get('templateBinding'):raise ValueError('歷史模板權限快照不一致')
        protect_layers({'objects':state['initial']},candidate)
    if not asset_paths(candidate)<=assets.keys():raise ValueError('缺少歷史刀模、預覽或模板素材')
    original=read(app,order['print_path'])
    if hashlib.sha256(original).hexdigest()!=m.get('originalPrintHash'):raise ValueError('原始生產圖與歷史證據不一致')
    production=candidate['production']
    width=math.floor(numeric(production.get('printW'),.1,1000,'歷史列印寬度')*720/25.4+.5)
    height=math.floor(numeric(production.get('printH'),.1,1000,'歷史列印高度')*720/25.4+.5)
    if width*height>18000000:raise ValueError('歷史生產尺寸超出安全範圍')
    if len(original)>MAX_BYTES:raise ValueError('原始生產圖容量超出安全範圍')
    with Image.open(io.BytesIO(original)) as png:
        if png.format!='PNG' or png.size!=(width,height) or any(abs(d-720)>.1 for d in png.info.get('dpi',(0,0))):raise ValueError('原始生產圖並非可驗證的 720 DPI 尺寸')
        expected=png.convert('RGBA').tobytes()
    payload=copy.deepcopy(candidate)
    for o in nodes(payload):
        if o.get('type')=='image':o['src']='https://renderer.invalid/asset/'+o['src']
    resources={'/asset/'+name:base64.b64encode(raw).decode() for name,raw in assets.items()}
    if not _RENDER_SLOT.acquire(timeout=5):raise ValueError('歷史生產圖驗證忙碌，請稍後再試')
    try:
        result=subprocess.run([sys.executable,str(ROOT/'editable_stickers.py'),'--worker'],input=json.dumps({'design':payload,'resources':resources,'mask':'https://renderer.invalid/asset/'+production['maskPath'],'width':width,'height':height}),text=True,encoding='utf-8',capture_output=True,check=True,timeout=90)
    except (subprocess.SubprocessError,OSError) as exc:raise ValueError('歷史生產圖無法驗證：原始素材、字型或 renderer 不可用') from exc
    finally:_RENDER_SLOT.release()
    raw=base64.b64decode(json.loads(result.stdout)['png'].split(',')[1])
    with Image.open(io.BytesIO(raw)) as rebuilt:
        if rebuilt.size!=(width,height) or rebuilt.convert('RGBA').tobytes()!=expected:raise ValueError('圖層重建與原始 720 DPI 生產圖不一致，禁止恢復')
    candidate['legacyRecovery']={'originalDesignHash':m['originalDesignHash'],'originalPrintHash':m['originalPrintHash'],'archiveReference':m['archiveReference'],'archivedAt':m['archivedAt'],'verification':'rgba-exact-720dpi'}
    return candidate,assets


def recover(app,order):
    candidate,assets=verified(order,app)
    mapping={name:persist_asset(app,order['id'],raw) for name,raw in assets.items()}
    def replace(v):
        if isinstance(v,str):return mapping.get(v,v)
        if isinstance(v,list):return [replace(x) for x in v]
        if isinstance(v,dict):return {k:replace(x) for k,x in v.items()}
        return v
    return replace(candidate)
