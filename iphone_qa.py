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
data = Path('/qa-data')
mounts = Path('/proc/self/mountinfo').read_text().splitlines()
if not data.is_dir() or not any(line.split()[4] == str(data) for line in mounts):
    raise RuntimeError('Dedicated persistent QA volume required')
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

ORDER = 'IPHONE-QA-112'
EDITOR = f'/admin/order-design/{ORDER}'
API = f'/api/admin/order-design/{ORDER}'
DIAG = data / 'diagnostics.jsonl'
lock = threading.Lock()


def fixture():
    path = Path(module.SAVE_DIR, 'qa-original.png')
    if not path.exists():
        image = Image.new('RGBA', (2030, 4241))
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
            d.ellipse((x,y+35,x+480,y+430),fill='#fff0cb')
            d.ellipse((x+147,y+120,x+337,y+310),fill='#f9ad24')
        d.polygon([(365,1810),(600,1920),(365,2070)],fill='#db376b')
        d.polygon([(860,1810),(625,1920),(860,2070)],fill='#db376b')
        d.ellipse((540,1870,685,2010),fill='#f75b87')
        image.save(path, 'PNG', dpi=(720,720))
    order = dict(id=ORDER, customer_name='Synthetic QA', model_id='qa-phone',
                 model_name='720 DPI 測試圖', style_id='qa-case', style_name='隔離驗收',
                 print_path=path.name, status='待處理', design_json={})
    with module.commerce.store.connection() as db:
        db.execute('INSERT OR IGNORE INTO orders(id,value) VALUES (?,?)',
                   (ORDER,json.dumps(order,ensure_ascii=False)))
        db.commit()


fixture()


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
    if path in ('/','/admin','/logout','/qa/results','/qa/metrics','/api/health',
                '/api/shop_data','/api/assets','/api/templates',EDITOR):
        return None
    if path.startswith(API + '/'):
        tail = path[len(API):]
        if tail in ('/pixel/open','/pixel/extract','/pixel/save','/revision/review') or (
            request.method == 'GET' and tail.startswith(('/pixel/assets/','/revision/assets/'))
        ):
            return None
    abort(404)


@app.after_request
def tag_qa(response):
    response.headers['X-Robots-Tag']='noindex, nofollow'
    if request.path == EDITOR and response.status_code == 200:
        response.direct_passthrough=False
        html=response.get_data(as_text=True).replace(
            'const fixes=[','const fixes=[\n      \'<script src="/static/iphone-qa-metrics.js?v=20261119p0"><\\/script>\',')
        response.set_data(html)
    if session.get('logged_in') and hasattr(g,'qa_start') and request.path in (API+'/pixel/extract',API+'/pixel/save',API+'/pixel/open'):
        ms=round((time.monotonic()-g.qa_start)*1000,1)
        response.headers['Server-Timing']=f'app;dur={ms}'
        append({'kind':'server','path':request.path.rsplit('/',1)[-1],'ms':ms,
                'request_bytes':request.content_length,'status':response.status_code,
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
    return {'qa':'iphone-safari','isolated':not module.USE_SUPABASE,'reprint':'off'}


@app.get('/')
def qa_home():
    return f'''<!doctype html><html lang="zh-Hant"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>本福丸 iPhone 驗收</title><main><h1>iPhone Safari 驗收</h1>
    <p>2030×4241、720 DPI 合成圖。上方有獨立貓咪、荷包蛋與蝴蝶結，下方有重疊圖案。</p>
    <p>請依序提取、拖曳、縮放、旋轉、刪除，儲存後回到此頁再開啟，檢查修改是否保留。</p>
    <p><a href="{EDITOR}?pixel=1">開啟測試訂單</a></p>
    <p><a href="/qa/results">查看效能記錄</a></p><form action="/logout" method="post"><button>登出</button></form></main></html>'''


app.view_functions['admin_page'] = qa_home


@app.post('/qa/metrics')
def qa_metrics():
    if not request.content_length or request.content_length > 4096:
        abort(413)
    row=request.get_json(silent=True)
    if not isinstance(row,dict) or row.get('kind') not in ('ready','fetch','gesture','pagehide','memory','lifecycle','js-error','editor'):
        abort(400)
    safe={k:v for k,v in row.items() if k in ('kind','name','ms','uploadBytes','frameGapMs','heapBytes','supported','status','device','width','height','serverMs','uploadEstimateMs','loadId','previousLoad','previousState','persisted','navigation','file','line','pixels')
          and type(v) in (str,int,float,bool) and (not isinstance(v,str) or len(v)<=120)}
    append(safe)
    return '',204


@app.get('/qa/results')
def qa_results():
    rows=DIAG.read_text(encoding='utf-8').splitlines()[-150:] if DIAG.exists() else []
    return module.no_cache_json({'records':[json.loads(row) for row in rows]})
