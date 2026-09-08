from flask import Flask, request, jsonify, send_file, session, redirect, url_for
import os
import json
import time
import base64
import uuid

app = Flask(__name__)
app.secret_key = 'fan_super_secret_key_2026' 
ADMIN_PASSWORD = "fan123"

# === 系統資料夾架構 ===
SAVE_DIR = "orders"
STATIC_DIR = "static"
STICKER_DIR = os.path.join(STATIC_DIR, "stickers")
MATERIAL_DIR = os.path.join(STATIC_DIR, "materials")
DATA_FILE = "shop_data.json"
ASSETS_FILE = "assets.json"

for d in [SAVE_DIR, STATIC_DIR, STICKER_DIR, MATERIAL_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

def load_json(filepath, default_data):
    if not os.path.exists(filepath):
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)
        return default_data
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return default_data

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

DEFAULT_SHOP_DATA = {
    "brands": ["蘋果", "三星"],
    "models": [{"id": "model_apple_ip17pm", "brand": "蘋果", "name": "iPhone 17 Pro Max", "status": True}],
    "styles": [{
        "id": "style_clear_01", "name": "氣囊防摔透明殼", "colors": ["透明"], "status": True,
        "print_x": 0, "print_y": 0, "print_w": 80, "print_h": 160, "mask_img": "", "line_img": ""
    }]
}
DEFAULT_ASSETS = {"stickers": [], "categories": ["全部", "可愛", "Y2K", "文字"]}

@app.route('/')
def home(): return send_file('index.html')

@app.route('/api/shop_data', methods=['GET'])
def get_shop_data(): return jsonify({"status": "success", "data": load_json(DATA_FILE, DEFAULT_SHOP_DATA)})

@app.route('/api/assets', methods=['GET'])
def get_assets(): return jsonify({"status": "success", "data": load_json(ASSETS_FILE, DEFAULT_ASSETS)})

# === 訂單系統 API (升級版：加入客資) ===
@app.route('/api/create_order', methods=['POST'])
def create_order():
    try:
        data = request.json
        print_data = base64.b64decode(data['print_file'].split(',')[1])
        mockup_data = base64.b64decode(data['mockup_file'].split(',')[1])
        
        # 接收商品與客資
        model_name = data.get('model_name', 'Unknown')
        style_name = data.get('style_name', 'Unknown')
        price = data.get('price', 0)
        customer_name = data.get('customer_name', '未提供')
        customer_phone = data.get('customer_phone', '未提供')
        address = data.get('address', '未提供')
        payment_method = data.get('payment_method', '貨到付款')
        
        timestamp = int(time.time())
        # 生成正式訂單編號，例如 20260908xxxx
        order_id = f"{time.strftime('%Y%m%d%H%M%S')}"
        
        # 存圖
        with open(os.path.join(SAVE_DIR, f"{order_id}_print.png"), 'wb') as f: f.write(print_data)
        with open(os.path.join(SAVE_DIR, f"{order_id}_mockup.png"), 'wb') as f: f.write(mockup_data)
            
        # 存訂單 JSON
        order_info = {
            "order_id": order_id,
            "model": model_name,
            "style": style_name,
            "price": price,
            "customer_name": customer_name,
            "customer_phone": customer_phone,
            "address": address,
            "payment_method": payment_method,
            "status": "待處理",
            "time": timestamp,
            "print_url": f"/orders/{order_id}_print.png",
            "mockup_url": f"/orders/{order_id}_mockup.png"
        }
        with open(os.path.join(SAVE_DIR, f"{order_id}_info.json"), 'w', encoding='utf-8') as f:
            json.dump(order_info, f, ensure_ascii=False, indent=4)
            
        return jsonify({"status": "success", "order_id": order_id, "msg": "訂單建立成功"})
    except Exception as e: return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/admin/get_orders', methods=['GET'])
def admin_get_orders():
    if not session.get('logged_in'): return jsonify({"status": "error"}), 401
    orders = []
    try:
        for filename in os.listdir(SAVE_DIR):
            if filename.endswith("_info.json"):
                with open(os.path.join(SAVE_DIR, filename), 'r', encoding='utf-8') as f:
                    orders.append(json.load(f))
        orders.sort(key=lambda x: x.get('time', 0), reverse=True)
        return jsonify({"status": "success", "data": orders})
    except Exception as e: return jsonify({"status": "error", "msg": str(e)}), 500

# === 後台管理介面 ===
@app.route('/admin')
def admin_page():
    if not session.get('logged_in'): return redirect(url_for('login_page'))
    return send_file('admin.html')

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_page'))
        return "密碼錯誤", 401
    return '''
        <body style="display:flex; justify-content:center; align-items:center; height:100vh; background:#fff5f7; font-family:sans-serif;">
            <form method="POST" style="background:white; padding:40px; border-radius:12px; box-shadow:0 4px 15px rgba(255,133,153,0.1); text-align:center;">
                <h2 style="color:#ff8599; margin-top:0;">本福丸訂製 - 管理後台</h2>
                <input type="password" name="password" placeholder="請輸入密碼" style="padding:12px; width:220px; margin-bottom:20px; border:1px solid #ffcccd; border-radius:6px; outline:none;"><br>
                <button type="submit" style="background:#ff8599; color:white; border:none; padding:12px 30px; border-radius:20px; cursor:pointer; font-weight:bold;">登入</button>
            </form>
        </body>
    '''

@app.route('/api/admin/save_shop_data', methods=['POST'])
def admin_save_shop_data():
    if not session.get('logged_in'): return jsonify({"status": "error"}), 401
    try:
        save_json(DATA_FILE, request.json)
        return jsonify({"status": "success", "msg": "資料儲存成功"})
    except Exception as e: return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/admin/upload_image', methods=['POST'])
def admin_upload_image():
    if not session.get('logged_in'): return jsonify({"status": "error"}), 401
    try:
        file = request.files.get('file')
        upload_type = request.form.get('type', 'sticker')
        if not file: return jsonify({"status": "error", "msg": "沒有檔案"}), 400
        target_dir = MATERIAL_DIR if upload_type == 'material' else STICKER_DIR
        prefix = "m_" if upload_type == 'material' else "s_"
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
        safe_filename = f"{prefix}{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
        filepath = os.path.join(target_dir, safe_filename)
        file.save(filepath)
        folder_name = "materials" if upload_type == 'material' else "stickers"
        url = f"/static/{folder_name}/{safe_filename}"
        return jsonify({"status": "success", "url": url, "msg": "上傳成功"})
    except Exception as e: return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/admin/batch_upload_stickers', methods=['POST'])
def admin_batch_upload_stickers():
    if not session.get('logged_in'): return jsonify({"status": "error"}), 401
    try:
        files = request.files.getlist('files')
        category = request.form.get('category', '全部')
        if not files or files[0].filename == '': return jsonify({"status": "error", "msg": "沒有選擇檔案"}), 400
        assets = load_json(ASSETS_FILE, DEFAULT_ASSETS)
        count = 0
        for file in files:
            if file.filename:
                ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'png'
                safe_filename = f"s_{int(time.time())}_{uuid.uuid4().hex[:6]}.{ext}"
                filepath = os.path.join(STICKER_DIR, safe_filename)
                file.save(filepath)
                assets['stickers'].append({"id": safe_filename, "category": category, "url": f"/static/stickers/{safe_filename}"})
                count += 1
        if category not in assets['categories']: assets['categories'].append(category)
        save_json(ASSETS_FILE, assets)
        return jsonify({"status": "success", "msg": f"成功批量上傳 {count} 張素材！"})
    except Exception as e: return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/admin/delete_sticker', methods=['POST'])
def admin_delete_sticker():
    if not session.get('logged_in'): return jsonify({"status": "error"}), 401
    try:
        sticker_id = request.json.get('id')
        assets = load_json(ASSETS_FILE, DEFAULT_ASSETS)
        assets['stickers'] = [s for s in assets['stickers'] if s['id'] != sticker_id]
        save_json(ASSETS_FILE, assets)
        return jsonify({"status": "success", "msg": "素材已刪除"})
    except Exception as e: return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/orders/<path:filename>')
def custom_static_orders(filename):
    return send_file(os.path.join(SAVE_DIR, filename))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
