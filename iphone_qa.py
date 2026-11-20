"""Standalone Railway entry point for the synthetic iPhone acceptance site."""
import json
import os
from pathlib import Path
import resource
import threading
import time

from flask import abort, g, redirect, request, session
from PIL import Image, ImageDraw

# Require dedicated staging credentials and fail closed on any live integration.
if os.environ.get('RAILWAY_PROJECT_ID') != '62673372-609e-4fc2-b86f-c0e75b46fdaa' or os.environ.get('RAILWAY_ENVIRONMENT_ID') != '49f531ce-e0ae-46e9-b37f-55e08218eb42':
    raise RuntimeError('Must run in the isolated iPhone QA project and environment')
password = os.environ.get('ADMIN_PASSWORD', '')
secret = os.environ.get('FLASK_SECRET_KEY', '')
if os.environ.get('IPHONE_QA') != '1' or len(password) < 20 or len(secret) < 32:
    raise RuntimeError('Dedicated QA credentials and IPHONE_QA are required')
if any(os.environ.get(key) for key in ('SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY',
                                      'YUN_PRINT_DEVICE_ID', 'YUN_PRINT_DEVICE_KEY', 'RUNPOD_API_KEY')):
    raise RuntimeError('External service credentials are forbidden in iPhone QA')
os.environ.update(SESSION_COOKIE_SECURE='true', BENFUWAN_PRODUCTION='1',
                  COMMERCE_DURABLE_LOCAL='1', YUN_PRINT_ENABLED='false',
                  YUN_AUTO_PRINT_ENABLED='false', ORDER_PIXEL_REPRINT_ENABLED='false')
volume = Path('/qa-data')
mounts = Path('/proc/self/mountinfo').read_text().splitlines()
if not volume.is_dir() or not any(line.split()[4] == str(volume) for line in mounts):
    raise RuntimeError('Dedicated persistent QA volume required')
data = volume / 'pr116'
data.mkdir(exist_ok=True)
os.environ['COMMERCE_DB_PATH'] = str(data / 'qa.sqlite3')
os.environ['PRINT_DB_PATH'] = str(data / 'qa.sqlite3')

import app as module
from commerce_patch import install as install_commerce
from order_designs import install as install_designs
from print_center import install as install_print
from security_perf import install as install_security

app = module.app
app.config.update(SESSION_COOKIE_NAME='iphone_qa_session', MAX_CONTENT_LENGTH=45*1024*1024)
module.SAVE_DIR = str(data / 'artwork')
module.DATA_FILE = str(data / 'catalog.json')
module.ASSETS_FILE = str(data / 'assets.json')
module.TEMPLATES_FILE = str(data / 'templates.json')
Path(module.SAVE_DIR).mkdir(exist_ok=True)
install_security(module)
install_commerce(module)
install_print(module)
if not hasattr(module, 'order_designs'):
    install_designs(module)

FIXTURES = {
    'IPHONE-QA-116-MASK': ('有歷史蒙版', True),
    'IPHONE-QA-116-NO-MASK': ('無歷史蒙版', False),
    'IPHONE-QA-116-VERIFY': ('環境驗證用', True),
}
SIZE = (2030, 4241)
MODEL = 'qa-116-phone'
STYLE = 'qa-116-case'
PRINT_W, PRINT_H = (pixels * 25.4 / 720 for pixels in SIZE)
BUILD = '6451aed10d63be782a461e42c68d176c26e34e0b'
DIAG = data / 'diagnostics.jsonl'
lock = threading.Lock()


def original_art():
    path = Path(module.SAVE_DIR, 'qa-original.png')
    if not path.exists():
        image = Image.new('RGBA', SIZE)
        d = ImageDraw.Draw(image)
        # Separate cat, fried egg and bow. The lower pair intentionally overlap.
        for x,y in [(370,410),(480,2580)]:
            d.ellipse((x,y+55,x+475,y+420),fill='#bd814f')
            d.polygon([(x+15,y+150),(x+52,y),(x+180,y+97)],fill='#bd814f')
            d.polygon([(x+290,y+97),(x+422,y),(x+460,y+150)],fill='#bd814f')
            for eye in (x+145,x+300):
                d.ellipse((eye,y+210,eye+34,y+254),fill='#392b24')
            d.ellipse((x+222,y+259,x+258,y+288),fill='#603e36')
        for x,y in [(1050,1100),(800,2760)]:
            d.ellipse((x-2,y+33,x+482,y+432),fill=(255,240,203,82))
            d.ellipse((x,y+35,x+480,y+430),fill='#fff0cb')
            d.ellipse((x+147,y+120,x+337,y+310),fill='#f9ad24')
        d.polygon([(365,1810),(600,1920),(365,2070)],fill='#db376b')
        d.polygon([(860,1810),(625,1920),(860,2070)],fill='#db376b')
        d.ellipse((540,1870,685,2010),fill='#f75b87')
        image.save(path, 'PNG', dpi=(720,720))
    return path.name


def fixture_orders():
    artwork = original_art()
    with module.commerce.store.connection() as db:
        for order_id, (label, has_mask) in FIXTURES.items():
            design = {}
            if has_mask:
                path = f'orders_{order_id}_sources_frozen-mask.png'
                # Like the renderer, the alignment guide normalizes the painted
                # extent. Preserve padding and the actual camera cutout here.
                image = Image.new('RGBA', (480, 960))
                draw = ImageDraw.Draw(image)
                draw.rounded_rectangle((25,25,454,923),radius=47,fill='white')
                draw.rounded_rectangle((58,63,180,185),radius=21,fill=(0,0,0,0))
                image.save(Path(module.SAVE_DIR, path), 'PNG')
                design = {
                    'modelId':MODEL, 'styleId':STYLE,
                    'production':{'maskPath':path,'printW':PRINT_W,'printH':PRINT_H},
                    'editorContext':{'printX':2.5,'printY':-1.75,'printAngle':0},
                }
            order = dict(id=order_id, customer_name='Synthetic QA', model_id=MODEL,
                         model_name='720 DPI 測試手機殼', style_id=STYLE,
                         style_name=label, print_path=artwork, status='待處理', design_json=design)
            db.execute('INSERT OR IGNORE INTO orders(id,value) VALUES (?,?)',
                       (order_id,json.dumps(order,ensure_ascii=False)))
        db.commit()
    # The current synthetic profile intentionally differs in X. The guide must
    # still display the order-owned file and report that the profile changed.
    current = {'print_w':PRINT_W,'print_h':PRINT_H,'print_x':3.25,'print_y':-1.75,
               'print_angle':0,'print_line_img':'/static/synthetic-current.png',
               'preview_mask_img':'/static/synthetic-current.png'}
    Path(module.DATA_FILE).write_text(json.dumps({'brands':['QA'],
        'models':[{'id':MODEL,'name':'QA','case_profiles':{STYLE:current}}],
        'styles':[{'id':STYLE,'name':'QA','price':1}]}), encoding='utf-8')


def fixture_stickers():
    import base64
    import io
    items = []
    for category,color in [('花朵','#ef6880'),('星星','#f5ba28')]:
        image = Image.new('RGBA',(96,96))
        draw = ImageDraw.Draw(image)
        if category == '星星':
            draw.polygon([(48,5),(59,34),(91,35),(65,55),(75,87),(48,68),(20,87),(30,55),(5,35),(37,34)],fill=color)
        else:
            for x,y in ((25,5),(5,35),(45,35),(25,55)):
                draw.ellipse((x,y,x+36,y+36),fill=color)
        out = io.BytesIO()
        image.save(out,'PNG')
        items.append({'category':category,'url':'data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()})
    Path(module.ASSETS_FILE).write_text(json.dumps({'categories':['花朵','星星'],'stickers':items}),encoding='utf-8')

fixture_stickers()
fixture_orders()


def editor_fixture(path):
    prefix = '/admin/order-design/'
    if not path.startswith(prefix):
        return None
    order = path[len(prefix):]
    return order if order in FIXTURES else None


def api_fixture(path):
    prefix = '/api/admin/order-design/'
    if not path.startswith(prefix):
        return None, ''
    order, sep, tail = path[len(prefix):].partition('/')
    return (order, tail) if sep and order in FIXTURES else (None, '')


@app.before_request
def restrict_routes():
    g.qa_start = time.monotonic()
    path = request.path
    if path == '/login' and request.method == 'GET':
        return '''<!doctype html><html lang="zh-Hant"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>iPhone 測試登入</title><main><h1>本福丸 iPhone 測試</h1>
        <form method="post"><label>測試密碼 <input required type="password" name="password"
        autocomplete="current-password" style="font-size:16px"></label> <button>登入</button></form></main></html>'''
    if path in ('/login','/_qa_health') or path.startswith('/static/'):
        return None
    if not session.get('logged_in'):
        return redirect('/login') if request.method == 'GET' else ('Login required',401)
    if path in ('/','/admin','/logout','/qa/results','/qa/metrics','/api/health','/api/assets','/api/admin/order-design/stickers'):
        return None
    if request.method == 'GET' and editor_fixture(path):
        return None
    order, tail = api_fixture(path)
    if order and (
        request.method == 'POST' and tail in ('pixel/open','pixel/extract','pixel/save','revision/review','revision/finish')
        or request.method == 'GET' and (
            tail == 'pixel/alignment' or tail.startswith(('pixel/assets/','revision/assets/'))
        )
    ):
        return None
    abort(404)


@app.after_request
def tag_qa(response):
    response.headers['X-Robots-Tag']='noindex, nofollow'
    if session.get('logged_in') and response.status_code == 200 and (
        editor_fixture(request.path) or request.path in ('/', '/admin')
    ):
        response.direct_passthrough=False
        html=response.get_data(as_text=True).replace(
            '</head>', '<script defer src="/static/iphone-qa-metrics.js?v=116"></script></head>', 1)
        response.set_data(html)
    order, tail = api_fixture(request.path)
    if order and session.get('logged_in') and hasattr(g,'qa_start') and tail in (
        'pixel/extract','pixel/save','pixel/open','pixel/alignment'
    ):
        ms=round((time.monotonic()-g.qa_start)*1000,1)
        response.headers['Server-Timing']=f'app;dur={ms}'
        append({'kind':'server','fixture':order,'path':tail.split('/')[-1],
                'ms':ms,'request_bytes':request.content_length,'status':response.status_code,
                'server_peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    return response


def append(row):
    with lock:
        if DIAG.exists() and DIAG.stat().st_size >= 2_000_000:
            return
        with DIAG.open('a',encoding='utf-8') as f:
            f.write(json.dumps({'utc':time.time(),**row},ensure_ascii=False)+'\n')


@app.get('/_qa_health')
def qa_health():
    return {'qa':'iphone-safari','isolated':not module.USE_SUPABASE,'reprint':'off','baseSha':BUILD}


@app.get('/')
def qa_home():
    return """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>#116 iPhone Safari 驗收</title>
    <style>body{font:17px system-ui;padding:1em;color:#252530}a,button{display:inline-block;padding:.55em .3em;min-height:28px}main{max-width:45em;margin:auto}</style></head>
    <body><main><h1>#116 iPhone Safari 驗收</h1>
    <p>兩筆獨立訂單都使用 2030×4241、720 DPI 的透明測試圖。上方有貓咪、荷包蛋、蝴蝶結，下方有重疊圖案。</p>
    <ul>
      <li><a data-qa-action="open-mask" href="/admin/order-design/IPHONE-QA-116-MASK?pixel=1">有歷史封存蒙版</a>。測試顯示、隱藏、透明度和版本差異提示。</li>
      <li><a data-qa-action="open-no-mask" href="/admin/order-design/IPHONE-QA-116-NO-MASK?pixel=1">無歷史封存蒙版</a>。測試缺少歷史證據的提示。</li>
    </ul>
    <p>可先新增素材並刪除，再用「清除原圖選取區」處理荷包蛋，儲存 V2 後返回這頁再開啟。</p>
    <p><a href="/qa/results">查看效能紀錄</a></p>
    <form action="/logout" method="post"><button>登出</button></form></main></body></html>"""



app.view_functions['admin_page'] = qa_home


@app.post('/qa/metrics')
def qa_metrics():
    if not request.content_length or request.content_length > 4096:
        abort(413)
    row=request.get_json(silent=True)
    if not isinstance(row,dict) or row.get('kind') not in ('ready','fetch','gesture','pagehide','memory','lifecycle','js-error','editor','action'):
        abort(400)
    safe={k:v for k,v in row.items() if k in ('kind','name','ms','uploadBytes','frameGapMs','heapBytes','supported','status','device','width','height','serverMs','uploadEstimateMs','loadId','previousLoad','previousState','persisted','navigation','file','line','pixels','cause','screen','fixture','fromScreen','navMs','responseBytes')
          and type(v) in (str,int,float,bool) and (not isinstance(v,str) or len(v)<=120)}
    append(safe)
    return '',204


@app.get('/qa/results')
def qa_results():
    device = request.args.get('device')
    rows=DIAG.read_text(encoding='utf-8').splitlines()[-150:] if DIAG.exists() else []
    records = [json.loads(row) for row in rows]
    if device == 'iPhone':
        records = [row for row in records if row.get('device') == 'iPhone']
    return module.no_cache_json({'baseSha':BUILD,'records':records})
