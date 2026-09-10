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

REMOVEBG_API_KEY = os.environ.get('REMOVEBG_API_KEY', '').strip()
REMOVEBG_ENDPOINT = os.environ.get('REMOVEBG_ENDPOINT', 'https://api.remove.bg/v1.0/removebg').strip()

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


@app.route('/')
def home():
    return send_file('index.html')


@app.route('/api/health')
def api_health():
    return no_cache_json({
        'status': 'success',
        'persistence': 'supabase' if USE_SUPABASE else 'local',
        'ai_background_removal': bool(REMOVEBG_API_KEY)
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
    if not REMOVEBG_API_KEY:
        return no_cache_json({'status':'error','code':'AI_NOT_CONFIGURED','msg':'AI 去背尚未設定 API Key'}, 503)
    if requests is None:
        return no_cache_json({'status':'error','msg':'伺服器缺少 requests 套件'}, 500)
    image = request.files.get('image')
    if not image or not image.filename:
        return no_cache_json({'status':'error','msg':'沒有收到圖片'}, 400)
    if (image.mimetype or '').lower() not in ('image/png','image/jpeg','image/webp'):
        return no_cache_json({'status':'error','msg':'AI 去背只接受 PNG / JPG / WEBP'}, 400)
    raw = image.read()
    if not raw or len(raw) > 10 * 1024 * 1024:
        return no_cache_json({'status':'error','msg':'圖片需小於 10MB'}, 400)
    try:
        r = requests.post(
            REMOVEBG_ENDPOINT,
            files={'image_file': (image.filename, raw, image.mimetype)},
            data={'size':'auto','format':'png'},
            headers={'X-Api-Key': REMOVEBG_API_KEY},
            timeout=75,
        )
        if r.status_code != 200:
            detail = r.text[:300] if r.text else f'HTTP {r.status_code}'
            return no_cache_json({'status':'error','msg':f'AI 去背失敗：{detail}'}, 502)
        resp = Response(r.content, mimetype='image/png')
        resp.headers['Cache-Control'] = 'no-store'
        return resp
    except requests.RequestException as exc:
        return no_cache_json({'status':'error','msg':f'AI 去背連線失敗：{exc}'}, 502)


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
