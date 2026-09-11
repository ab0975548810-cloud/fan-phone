from flask import Flask, request, jsonify, send_file, session, redirect, url_for, send_from_directory, Response
import os
import json
import time
import base64
import uuid
from io import BytesIO

try:
    import requests
except Exception:
    requests = None

try:
    from supabase import create_client
except Exception:
    create_client = None

app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev_only_change_me')
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'fan123')
app.config['MAX_CONTENT_LENGTH'] = 36 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('SESSION_COOKIE_SECURE', '').lower() in ('1', 'true', 'yes')

# === Local fallback ===
SAVE_DIR = 'orders'
STATIC_DIR = 'static'
STICKER_DIR = os.path.join(STATIC_DIR, 'stickers')
MATERIAL_DIR = os.path.join(STATIC_DIR, 'materials')
DATA_FILE = 'shop_data.json'
ASSETS_FILE = 'assets.json'
TEMPLATES_FILE = 'templates.json'

for d in [SAVE_DIR, STATIC_DIR, STICKER_DIR, MATERIAL_DIR]:
    os.makedirs(d, exist_ok=True)

# === Supabase persistence (enabled only when both env vars exist) ===
SUPABASE_URL = os.environ.get('SUPABASE_URL', '').strip()
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '').strip()
SUPABASE_PUBLIC_BUCKET = os.environ.get('SUPABASE_PUBLIC_BUCKET', 'case-assets').strip() or 'case-assets'
SUPABASE_PRIVATE_BUCKET = os.environ.get('SUPABASE_PRIVATE_BUCKET', 'case-private').strip() or 'case-private'
USE_SUPABASE = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and create_client)
SUPABASE = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY) if USE_SUPABASE else None

# === Self-hosted AI background removal (Runpod Serverless worker) ===
RUNPOD_API_KEY = os.environ.get('RUNPOD_API_KEY', '').strip()
RUNPOD_ENDPOINT_ID = os.environ.get('RUNPOD_ENDPOINT_ID', '').strip()
RUNPOD_API_BASE = os.environ.get('RUNPOD_API_BASE', 'https://api.runpod.ai/v2').strip().rstrip('/')
AI_MODEL_NAME = os.environ.get('AI_MODEL_NAME', 'ZhengPeng7/BiRefNet').strip() or 'ZhengPeng7/BiRefNet'
AI_REMOVE_BG_TIMEOUT = max(60, min(300, int(os.environ.get('AI_REMOVE_BG_TIMEOUT', '300') or 300)))
AI_POLL_INTERVAL = max(0.5, min(5.0, float(os.environ.get('AI_POLL_INTERVAL', '2') or 2)))
AI_HTTP_TIMEOUT = max(5, min(30, int(os.environ.get('AI_HTTP_TIMEOUT', '15') or 15)))
AI_RETRY_FAILED_JOB = os.environ.get('AI_RETRY_FAILED_JOB', 'true').lower() in ('1', 'true', 'yes')
AI_MAX_INPUT_BYTES = 6 * 1024 * 1024
AI_ENABLED = bool(RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID and requests)

DEFAULT_SHOP_DATA = {
    'brands': ['Apple', 'Samsung', 'Google', 'OPPO'],
    'models': [
        {'id':'model_apple_11','brand':'Apple','name':'iPhone 11','status':True},
        {'id':'model_apple_11_pro','brand':'Apple','name':'iPhone 11 Pro','status':True},
        {'id':'model_apple_11_pro_max','brand':'Apple','name':'iPhone 11 Pro Max','status':True},
        {'id':'model_apple_12','brand':'Apple','name':'iPhone 12','status':True},
        {'id':'model_apple_12_pro','brand':'Apple','name':'iPhone 12 Pro','status':True},
        {'id':'model_apple_12_pro_max','brand':'Apple','name':'iPhone 12 Pro Max','status':True},
        {'id':'model_apple_13','brand':'Apple','name':'iPhone 13','status':True},
        {'id':'model_apple_13_pro','brand':'Apple','name':'iPhone 13 Pro','status':True},
        {'id':'model_apple_13_pro_max','brand':'Apple','name':'iPhone 13 Pro Max','status':True},
        {'id':'model_apple_14','brand':'Apple','name':'iPhone 14','status':True},
        {'id':'model_apple_14_pro','brand':'Apple','name':'iPhone 14 Pro','status':True},
        {'id':'model_apple_14_pro_max','brand':'Apple','name':'iPhone 14 Pro Max','status':True},
        {'id':'model_apple_15','brand':'Apple','name':'iPhone 15','status':True},
        {'id':'model_apple_15_pro','brand':'Apple','name':'iPhone 15 Pro','status':True},
        {'id':'model_apple_15_pro_max','brand':'Apple','name':'iPhone 15 Pro Max','status':True},
        {'id':'model_apple_16','brand':'Apple','name':'iPhone 16','status':True},
        {'id':'model_apple_16_pro','brand':'Apple','name':'iPhone 16 Pro','status':True},
        {'id':'model_apple_16_pro_max','brand':'Apple','name':'iPhone 16 Pro Max','status':True},
        {'id':'model_apple_17','brand':'Apple','name':'iPhone 17','status':True},
        {'id':'model_apple_17_pro','brand':'Apple','name':'iPhone 17 Pro','status':True},
        {'id':'model_apple_17_pro_max','brand':'Apple','name':'iPhone 17 Pro Max','status':True}
    ],
    'styles': [
        {'id':'style_clear','name':'透明殼','colors':['透明'],'price':390,'status':True,'print_x':0,'print_y':0,'print_w':80,'print_h':160,'mask_img':'','line_img':''},
        {'id':'style_black','name':'黑邊殼','colors':['黑'],'price':450,'status':True,'print_x':0,'print_y':0,'print_w':80,'print_h':160,'mask_img':'','line_img':''},
        {'id':'style_color','name':'彩色邊框','colors':['粉','藍','紫'],'price':490,'status':True,'print_x':0,'print_y':0,'print_w':80,'print_h':160,'mask_img':'','line_img':''},
        {'id':'style_armor','name':'防摔殼','colors':['透明','黑'],'price':520,'status':True,'print_x':0,'print_y':0,'print_w':80,'print_h':160,'mask_img':'','line_img':''},
        {'id':'style_magsafe','name':'磁吸殼','colors':['透明'],'price':580,'status':True,'print_x':0,'print_y':0,'print_w':80,'print_h':160,'mask_img':'','line_img':''}
    ]
}
DEFAULT_ASSETS = {'stickers': [], 'categories': ['全部', '可愛', 'Y2K', '文字']}
DEFAULT_TEMPLATES = {'templates': [], 'categories': ['全部', '熱門']}


def local_load_json(filepath, default_data):
    if not os.path.exists(filepath):
        local_save_json(filepath, default_data)
        return json.loads(json.dumps(default_data, ensure_ascii=False))
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f'{filepath} JSON 格式損壞：{exc}')


def local_save_json(filepath, data):
    tmp = filepath + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, filepath)


def cloud_get_json(key, local_file, default_data):
    if not USE_SUPABASE:
        return local_load_json(local_file, default_data)
    try:
        result = SUPABASE.table('app_store').select('value').eq('key', key).limit(1).execute()
        if result.data:
            return result.data[0].get('value') or default_data
        seed = local_load_json(local_file, default_data)
        SUPABASE.table('app_store').upsert({'key': key, 'value': seed}).execute()
        return seed
    except Exception as exc:
        raise RuntimeError(f'Supabase 讀取 {key} 失敗：{exc}')


def cloud_save_json(key, local_file, data):
    if not isinstance(data, dict):
        raise ValueError('Payload 必須是 JSON object')
    if not USE_SUPABASE:
        local_save_json(local_file, data)
        return
    try:
        SUPABASE.table('app_store').upsert({'key': key, 'value': data}).execute()
    except Exception as exc:
        raise RuntimeError(f'Supabase 儲存 {key} 失敗：{exc}')


def no_cache_json(payload, status=200):
    resp = jsonify(payload)
    resp.status_code = status
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    return resp


def _supabase_public_url(path):
    res = SUPABASE.storage.from_(SUPABASE_PUBLIC_BUCKET).get_public_url(path)
    if isinstance(res, str):
        return res
    if isinstance(res, dict):
        return res.get('publicUrl') or res.get('publicURL') or res.get('public_url') or ''
    return str(res)


def _supabase_signed_url(path, expires=3600):
    res = SUPABASE.storage.from_(SUPABASE_PRIVATE_BUCKET).create_signed_url(path, expires)
    if isinstance(res, dict):
        return res.get('signedURL') or res.get('signedUrl') or res.get('signed_url') or ''
    return ''


def upload_public_file(file_storage, folder):
    if not file_storage or not file_storage.filename:
        raise ValueError('沒有選擇檔案')
    mime = (file_storage.mimetype or '').lower()
    if mime not in ('image/png', 'image/jpeg', 'image/webp'):
        raise ValueError('只允許 PNG / JPG / WEBP 圖片')
    raw = file_storage.read()
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise ValueError('圖片需小於 10MB')
    ext = {'image/png':'png','image/jpeg':'jpg','image/webp':'webp'}[mime]
    name = f'{folder}/{uuid.uuid4().hex}.{ext}'
    if USE_SUPABASE:
        try:
            SUPABASE.storage.from_(SUPABASE_PUBLIC_BUCKET).upload(name, raw, file_options={'content-type': mime})
            return _supabase_public_url(name)
        except Exception as exc:
            raise RuntimeError(f'圖片雲端上傳失敗：{exc}')
    local_dir = STICKER_DIR if folder == 'stickers' else MATERIAL_DIR
    local_name = os.path.basename(name)
    with open(os.path.join(local_dir, local_name), 'wb') as f:
        f.write(raw)
    local_folder = 'stickers' if folder == 'stickers' else 'materials'
    return f'/static/{local_folder}/{local_name}'


def upload_private_bytes(path, raw, mime='image/png'):
    if USE_SUPABASE:
        SUPABASE.storage.from_(SUPABASE_PRIVATE_BUCKET).upload(path, raw, file_options={'content-type': mime})
        return path
    filename = path.replace('/', '_')
    with open(os.path.join(SAVE_DIR, filename), 'wb') as f:
        f.write(raw)
    return filename


def delete_private_path(path):
    if not path:
        return
    try:
        if USE_SUPABASE:
            SUPABASE.storage.from_(SUPABASE_PRIVATE_BUCKET).remove([path])
        else:
            fp = os.path.join(SAVE_DIR, path)
            if os.path.exists(fp):
                os.remove(fp)
    except Exception as exc:
        print('cleanup warning:', exc)


def decode_png_data_url(value, max_bytes=10 * 1024 * 1024):
    prefix = 'data:image/png;base64,'
    if not isinstance(value, str) or not value.startswith(prefix):
        raise ValueError('圖片資料格式錯誤')
    try:
        raw = base64.b64decode(value[len(prefix):], validate=True)
    except Exception:
        raise ValueError('圖片 Base64 無法解析')
    if len(raw) > max_bytes:
        raise ValueError('圖片超過 10MB')
    if not raw.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('圖片不是有效 PNG')
    return raw


def _runpod_headers(include_json=False):
    headers = {'Authorization': f'Bearer {RUNPOD_API_KEY}'}
    if include_json:
        headers['Content-Type'] = 'application/json'
    return headers


def _runpod_json(resp, action):
    if resp.status_code < 200 or resp.status_code >= 300:
        detail = (resp.text or '').strip()[:500]
        raise RuntimeError(f'{action}失敗（HTTP {resp.status_code}）：{detail or "沒有錯誤內容"}')
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f'{action}回傳格式錯誤') from exc
    if not isinstance(data, dict):
        raise RuntimeError(f'{action}回傳內容不是 JSON object')
    return data


def _runpod_submit(payload):
    endpoint = f'{RUNPOD_API_BASE}/{RUNPOD_ENDPOINT_ID}/run'
    resp = requests.post(
        endpoint,
        headers=_runpod_headers(include_json=True),
        json=payload,
        timeout=AI_HTTP_TIMEOUT,
    )
    data = _runpod_json(resp, 'AI 工作送出')
    job_id = str(data.get('id') or '').strip()
    if not job_id:
        raise RuntimeError('AI 工作送出成功但沒有 Job ID')
    return job_id, data


def _runpod_status(job_id):
    endpoint = f'{RUNPOD_API_BASE}/{RUNPOD_ENDPOINT_ID}/status/{job_id}'
    resp = requests.get(endpoint, headers=_runpod_headers(), timeout=AI_HTTP_TIMEOUT)
    if resp.status_code in (408, 425, 429, 500, 502, 503, 504):
        return {
            'status': 'TRANSIENT_HTTP',
            '_http_status': resp.status_code,
            '_detail': (resp.text or '')[:300],
        }
    return _runpod_json(resp, 'AI 狀態查詢')


def _runpod_retry(job_id):
    endpoint = f'{RUNPOD_API_BASE}/{RUNPOD_ENDPOINT_ID}/retry/{job_id}'
    resp = requests.post(endpoint, headers=_runpod_headers(), timeout=AI_HTTP_TIMEOUT)
    return _runpod_json(resp, 'AI 工作重試')


def _runpod_cancel(job_id):
    if not job_id:
        return
    try:
        endpoint = f'{RUNPOD_API_BASE}/{RUNPOD_ENDPOINT_ID}/cancel/{job_id}'
        requests.post(endpoint, headers=_runpod_headers(), timeout=min(AI_HTTP_TIMEOUT, 8))
    except Exception as exc:
        print('runpod cancel warning:', repr(exc))


def _runpod_wait_for_result(job_id, deadline):
    retried = False
    last_status = 'IN_QUEUE'
    transient_errors = 0

    while time.monotonic() < deadline:
        try:
            result = _runpod_status(job_id)
        except (requests.Timeout, requests.ConnectionError) as exc:
            transient_errors += 1
            print('runpod status transient network error:', job_id, repr(exc))
            time.sleep(min(AI_POLL_INTERVAL, max(0.1, deadline - time.monotonic())))
            continue

        status = str(result.get('status') or '').upper()
        if status == 'TRANSIENT_HTTP':
            transient_errors += 1
            print('runpod status transient http:', job_id, result.get('_http_status'))
            time.sleep(min(AI_POLL_INTERVAL, max(0.1, deadline - time.monotonic())))
            continue

        transient_errors = 0
        last_status = status or last_status

        if status == 'COMPLETED':
            return result, retried

        if status in ('FAILED', 'TIMED_OUT') and AI_RETRY_FAILED_JOB and not retried:
            retry_result = _runpod_retry(job_id)
            retry_status = str(retry_result.get('status') or '').upper()
            if retry_status in ('IN_QUEUE', 'IN_PROGRESS'):
                retried = True
                last_status = retry_status
                time.sleep(min(AI_POLL_INTERVAL, max(0.1, deadline - time.monotonic())))
                continue

        if status in ('FAILED', 'TIMED_OUT', 'ERROR', 'CANCELLED'):
            detail = result.get('error') or result.get('output') or status
            if isinstance(detail, (dict, list)):
                detail = json.dumps(detail, ensure_ascii=False)[:500]
            raise RuntimeError(f'AI 工作失敗（{status}）：{detail}')

        if status not in ('IN_QUEUE', 'IN_PROGRESS', 'RETRY'):
            print('runpod unknown status:', job_id, status, result)

        time.sleep(min(AI_POLL_INTERVAL, max(0.1, deadline - time.monotonic())))

    _runpod_cancel(job_id)
    raise TimeoutError(f'AI 工作等候逾時（最後狀態：{last_status}）')


@app.route('/')
def home():
    return send_file('index.html')


@app.route('/api/health')
def api_health():
    return no_cache_json({
        'status': 'success',
        'persistence': 'supabase' if USE_SUPABASE else 'local',
        'ai_background_removal': AI_ENABLED,
        'ai_provider': 'self-hosted-runpod' if AI_ENABLED else 'not-configured',
        'ai_model': AI_MODEL_NAME if AI_ENABLED else '',
        'ai_queue_mode': 'async-poll' if AI_ENABLED else '',
        'ai_timeout_seconds': AI_REMOVE_BG_TIMEOUT if AI_ENABLED else 0,
    })


@app.route('/api/shop_data', methods=['GET'])
def get_shop_data():
    return no_cache_json({'status': 'success', 'data': cloud_get_json('shop_data', DATA_FILE, DEFAULT_SHOP_DATA)})


@app.route('/api/assets', methods=['GET'])
def get_assets():
    return no_cache_json({'status': 'success', 'data': cloud_get_json('assets', ASSETS_FILE, DEFAULT_ASSETS)})


@app.route('/api/templates', methods=['GET'])
def get_templates():
    return no_cache_json({'status': 'success', 'data': cloud_get_json('templates', TEMPLATES_FILE, DEFAULT_TEMPLATES)})


@app.route('/api/ai/remove-background', methods=['POST'])
def ai_remove_background():
    if not AI_ENABLED:
        return no_cache_json({
            'status':'error',
            'code':'AI_NOT_CONFIGURED',
            'msg':'本福丸自架 AI 尚未連線，請先設定 RUNPOD_ENDPOINT_ID 與 RUNPOD_API_KEY'
        }, 503)

    image = request.files.get('image')
    if not image or not image.filename:
        return no_cache_json({'status':'error','msg':'沒有收到圖片'}, 400)

    mime = (image.mimetype or '').lower()
    if mime not in ('image/png','image/jpeg','image/webp'):
        return no_cache_json({'status':'error','msg':'AI 去背只接受 PNG / JPG / WEBP'}, 400)

    raw = image.read()
    if not raw:
        return no_cache_json({'status':'error','msg':'圖片內容是空的'}, 400)
    if len(raw) > AI_MAX_INPUT_BYTES:
        return no_cache_json({'status':'error','msg':'AI 處理圖片需小於 6MB，請重新選擇圖片'}, 400)

    job_id = ''
    started = time.monotonic()
    try:
        payload = {
            'input': {
                'image_base64': base64.b64encode(raw).decode('ascii'),
                'mime_type': mime,
                'max_output_edge': 1800,
            }
        }
        job_id, submit_result = _runpod_submit(payload)
        deadline = started + AI_REMOVE_BG_TIMEOUT
        result, retried = _runpod_wait_for_result(job_id, deadline)

        output = result.get('output') or {}
        if not isinstance(output, dict):
            return no_cache_json({'status':'error','code':'AI_BAD_OUTPUT','msg':'自架 AI 沒有回傳有效結果'}, 502)
        if output.get('status') == 'error':
            detail = output.get('error') or 'unknown error'
            return no_cache_json({'status':'error','code':'AI_WORKER_ERROR','msg':f'自架 AI 失敗：{detail}'}, 502)

        encoded = output.get('image_base64') or ''
        if not encoded:
            return no_cache_json({'status':'error','code':'AI_EMPTY_OUTPUT','msg':'自架 AI 沒有回傳去背圖片'}, 502)
        try:
            png = base64.b64decode(encoded, validate=True)
        except Exception:
            return no_cache_json({'status':'error','code':'AI_BAD_IMAGE_DATA','msg':'自架 AI 圖片資料無法解析'}, 502)
        if not png.startswith(b'\x89PNG\r\n\x1a\n'):
            return no_cache_json({'status':'error','code':'AI_NOT_PNG','msg':'自架 AI 回傳的不是 PNG'}, 502)
        if len(png) > 14 * 1024 * 1024:
            return no_cache_json({'status':'error','code':'AI_OUTPUT_TOO_LARGE','msg':'自架 AI 回傳圖片過大'}, 502)

        resp = Response(png, mimetype='image/png')
        resp.headers['Cache-Control'] = 'no-store'
        resp.headers['X-AI-Provider'] = 'self-hosted-runpod'
        resp.headers['X-AI-Model'] = str(output.get('model') or AI_MODEL_NAME)[:120]
        resp.headers['X-AI-Job-ID'] = job_id[:120]
        resp.headers['X-AI-Retried'] = '1' if retried else '0'
        if result.get('delayTime') is not None:
            resp.headers['X-AI-Delay-Ms'] = str(result.get('delayTime'))[:30]
        if result.get('executionTime') is not None:
            resp.headers['X-AI-Execution-Ms'] = str(result.get('executionTime'))[:30]
        return resp
    except TimeoutError as exc:
        return no_cache_json({
            'status':'error',
            'code':'AI_TIMEOUT',
            'job_id': job_id,
            'msg':'AI 啟動或排隊時間較久，本次已停止以避免一直計費，請再試一次',
            'detail':str(exc)[:300]
        }, 504)
    except requests.Timeout:
        _runpod_cancel(job_id)
        return no_cache_json({'status':'error','code':'AI_NETWORK_TIMEOUT','msg':'AI 連線暫時逾時，請再試一次'}, 504)
    except requests.RequestException as exc:
        _runpod_cancel(job_id)
        return no_cache_json({'status':'error','code':'AI_NETWORK_ERROR','msg':f'自架 AI 連線失敗：{exc}'}, 502)
    except RuntimeError as exc:
        return no_cache_json({'status':'error','code':'AI_JOB_ERROR','job_id':job_id,'msg':str(exc)}, 502)
    except Exception as exc:
        _runpod_cancel(job_id)
        print('ai_remove_background unexpected error:', repr(exc))
        return no_cache_json({'status':'error','code':'AI_UNKNOWN_ERROR','msg':'AI 去背發生未預期錯誤，請再試一次'}, 500)


@app.route('/api/create_order', methods=['POST'])
def create_order():
    print_path = None
    mockup_path = None
    try:
        data = request.get_json(silent=True) or {}
        model_id = str(data.get('model_id') or '')
        style_id = str(data.get('style_id') or '')
        if not model_id or not style_id:
            raise ValueError('缺少手機型號或手機殼款式')

        shop = cloud_get_json('shop_data', DATA_FILE, DEFAULT_SHOP_DATA)
        model = next((m for m in shop.get('models', []) if str(m.get('id')) == model_id and m.get('status', True)), None)
        style = next((s for s in shop.get('styles', []) if str(s.get('id')) == style_id and s.get('status', True)), None)
        if not model or not style:
            raise ValueError('手機型號或手機殼款式不存在/已停用')

        unit_price = int(style.get('price') or 390)
        if unit_price <= 0:
            raise ValueError('商品售價設定錯誤')
        quantity = max(1, min(99, int(data.get('quantity') or 1)))
        total = unit_price * quantity
        customer_name = str(data.get('customer_name') or '').strip()
        if not customer_name:
            raise ValueError('請填寫貴姓')
        payment_method = str(data.get('payment_method') or '現金')
        if payment_method not in ('現金', 'LINE Pay'):
            raise ValueError('付款方式錯誤')

        print_raw = decode_png_data_url(data.get('print_file'))
        mockup_raw = decode_png_data_url(data.get('mockup_file'))
        order_id = f"{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"
        timestamp = int(time.time())

        print_store_path = f'orders/{order_id}/print.png'
        mockup_store_path = f'orders/{order_id}/preview.png'
        print_path = upload_private_bytes(print_store_path, print_raw)
        mockup_path = upload_private_bytes(mockup_store_path, mockup_raw)

        design_json = data.get('design_json')
        order_payload = {
            'id': order_id,
            'customer_name': customer_name,
            'payment_method': payment_method,
            'model_id': model_id,
            'model_name': model.get('name') or data.get('model_name') or '',
            'style_id': style_id,
            'style_name': style.get('name') or data.get('style_name') or '',
            'unit_price': unit_price,
            'quantity': quantity,
            'total': total,
            'status': '待處理',
            'design_json': design_json,
            'print_path': print_path,
            'mockup_path': mockup_path,
            'created_at_unix': timestamp,
        }

        if USE_SUPABASE:
            try:
                SUPABASE.table('orders').insert(order_payload).execute()
            except Exception:
                delete_private_path(print_path)
                delete_private_path(mockup_path)
                raise
        else:
            local_info = {
                'order_id': order_id,
                'model': order_payload['model_name'],
                'style': order_payload['style_name'],
                'price': unit_price,
                'quantity': quantity,
                'total': total,
                'customer_name': customer_name,
                'customer_phone': '未提供',
                'address': '現場取件',
                'payment_method': payment_method,
                'status': '待處理',
                'time': timestamp,
                'design_json': design_json,
                'print_url': f'/orders/{print_path}',
                'mockup_url': f'/orders/{mockup_path}',
            }
            local_save_json(os.path.join(SAVE_DIR, f'{order_id}_info.json'), local_info)

        return no_cache_json({'status':'success','order_id':order_id,'total':total,'msg':'訂單建立成功'})
    except ValueError as exc:
        return no_cache_json({'status':'error','msg':str(exc)}, 400)
    except Exception as exc:
        print('create_order error:', repr(exc))
        return no_cache_json({'status':'error','msg':f'訂單建立失敗：{exc}'}, 500)


@app.route('/api/admin/get_orders', methods=['GET'])
def admin_get_orders():
    if not session.get('logged_in'):
        return no_cache_json({'status':'error','msg':'未登入'}, 401)
    try:
        if USE_SUPABASE:
            rows = SUPABASE.table('orders').select('*').order('created_at', desc=True).execute().data or []
            orders = []
            for row in rows:
                orders.append({
                    'order_id': row.get('id'),
                    'customer_name': row.get('customer_name'),
                    'model': row.get('model_name'),
                    'style': row.get('style_name'),
                    'price': row.get('unit_price'),
                    'quantity': row.get('quantity'),
                    'total': row.get('total'),
                    'payment_method': row.get('payment_method'),
                    'status': row.get('status'),
                    'time': row.get('created_at_unix'),
                    'design_json': row.get('design_json'),
                    'print_url': _supabase_signed_url(row.get('print_path')) if row.get('print_path') else '',
                    'mockup_url': _supabase_signed_url(row.get('mockup_path')) if row.get('mockup_path') else '',
                })
            return no_cache_json({'status':'success','data':orders})

        orders = []
        for filename in os.listdir(SAVE_DIR):
            if filename.endswith('_info.json'):
                try:
                    orders.append(local_load_json(os.path.join(SAVE_DIR, filename), {}))
                except Exception as exc:
                    print('order read warning:', filename, exc)
        orders.sort(key=lambda x: x.get('time', 0), reverse=True)
        return no_cache_json({'status':'success','data':orders})
    except Exception as exc:
        return no_cache_json({'status':'error','msg':str(exc)}, 500)


@app.route('/admin')
def admin_page():
    if not session.get('logged_in'):
        return redirect(url_for('login_page'))
    return send_file('admin.html')


@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_page'))
        return '密碼錯誤', 401
    return '''
        <body style="display:flex;justify-content:center;align-items:center;height:100vh;background:#fff5f7;font-family:-apple-system,BlinkMacSystemFont,'PingFang TC',sans-serif;">
          <form method="POST" style="background:white;padding:40px;border-radius:20px;box-shadow:0 12px 35px rgba(255,111,154,.15);text-align:center;">
            <h2 style="color:#ff6f9a;margin-top:0;">本福丸訂製 - 管理後台</h2>
            <input type="password" name="password" placeholder="請輸入密碼" style="padding:13px;width:230px;margin-bottom:18px;border:1px solid #ffc5d7;border-radius:12px;outline:none;"><br>
            <button type="submit" style="background:#ff6f9a;color:white;border:none;padding:12px 34px;border-radius:999px;cursor:pointer;font-weight:bold;">登入</button>
          </form>
        </body>
    '''


@app.route('/api/admin/save_shop_data', methods=['POST'])
def admin_save_shop_data():
    if not session.get('logged_in'):
        return no_cache_json({'status':'error'}, 401)
    try:
        cloud_save_json('shop_data', DATA_FILE, request.get_json(silent=True) or {})
        return no_cache_json({'status':'success','msg':'資料儲存成功'})
    except Exception as exc:
        return no_cache_json({'status':'error','msg':str(exc)}, 500)


@app.route('/api/admin/save_templates', methods=['POST'])
def admin_save_templates():
    if not session.get('logged_in'):
        return no_cache_json({'status':'error'}, 401)
    try:
        cloud_save_json('templates', TEMPLATES_FILE, request.get_json(silent=True) or {})
        return no_cache_json({'status':'success','msg':'模板儲存成功'})
    except Exception as exc:
        return no_cache_json({'status':'error','msg':str(exc)}, 500)


@app.route('/api/admin/upload_image', methods=['POST'])
def admin_upload_image():
    if not session.get('logged_in'):
        return no_cache_json({'status':'error'}, 401)
    try:
        file = request.files.get('file')
        upload_type = request.form.get('type', 'material')
        folder = 'templates' if upload_type == 'template' else ('stickers' if upload_type == 'sticker' else 'materials')
        url = upload_public_file(file, folder)
        return no_cache_json({'status':'success','url':url})
    except ValueError as exc:
        return no_cache_json({'status':'error','msg':str(exc)}, 400)
    except Exception as exc:
        return no_cache_json({'status':'error','msg':str(exc)}, 500)


@app.route('/api/admin/batch_upload_stickers', methods=['POST'])
def admin_batch_upload_stickers():
    if not session.get('logged_in'):
        return no_cache_json({'status':'error'}, 401)
    try:
        files = [f for f in request.files.getlist('files') if f and f.filename]
        if not files:
            raise ValueError('沒有選擇檔案')
        category = request.form.get('category', '全部') or '全部'
        assets = cloud_get_json('assets', ASSETS_FILE, DEFAULT_ASSETS)
        uploaded = []
        for file in files:
            url = upload_public_file(file, 'stickers')
            item = {'id': f's_{uuid.uuid4().hex[:12]}', 'category': category, 'url': url}
            assets.setdefault('stickers', []).append(item)
            uploaded.append(item)
        cats = assets.setdefault('categories', ['全部'])
        if category not in cats:
            cats.append(category)
        cloud_save_json('assets', ASSETS_FILE, assets)
        return no_cache_json({'status':'success','msg':f'成功批量上傳 {len(uploaded)} 張素材！','data':uploaded})
    except ValueError as exc:
        return no_cache_json({'status':'error','msg':str(exc)}, 400)
    except Exception as exc:
        return no_cache_json({'status':'error','msg':str(exc)}, 500)


@app.route('/api/admin/delete_sticker', methods=['POST'])
def admin_delete_sticker():
    if not session.get('logged_in'):
        return no_cache_json({'status':'error'}, 401)
    try:
        sticker_id = (request.get_json(silent=True) or {}).get('id')
        assets = cloud_get_json('assets', ASSETS_FILE, DEFAULT_ASSETS)
        assets['stickers'] = [s for s in assets.get('stickers', []) if s.get('id') != sticker_id]
        cloud_save_json('assets', ASSETS_FILE, assets)
        return no_cache_json({'status':'success','msg':'素材已刪除'})
    except Exception as exc:
        return no_cache_json({'status':'error','msg':str(exc)}, 500)


@app.route('/orders/<path:filename>')
def custom_static_orders(filename):
    if USE_SUPABASE:
        return 'Not available in cloud mode', 404
    if not filename.lower().endswith(('.png','.jpg','.jpeg','.webp')):
        return 'Access denied', 403
    return send_from_directory(SAVE_DIR, filename)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
