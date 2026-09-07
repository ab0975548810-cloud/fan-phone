from flask import Flask, request, jsonify, send_file, session, redirect, url_for
import os
import json
import time
import base64

app = Flask(__name__)
# 這是後台的密碼鎖
app.secret_key = 'fan_super_secret_key_2026' 
ADMIN_PASSWORD = "fan123"

SAVE_DIR = "orders"
STATIC_DIR = "static"
DATA_FILE = "shop_data.json"
ASSETS_FILE = "assets.json"

for d in [SAVE_DIR, STATIC_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

# === JSON 讀寫輔助函式 ===
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

# 預設資料
DEFAULT_SHOP_DATA = {
    "brands": ["蘋果", "華為", "小米"],
    "models": [
        {"id": "ip17pm", "brand": "蘋果", "name": "iPhone 17 Pro Max", "status": True},
        {"id": "ip17p", "brand": "蘋果", "name": "iPhone 17 Pro", "status": True}
    ],
    "styles": [
        {"id": "clear", "name": "透明防摔殼", "price": 390, "desc": "軍規防摔", "mask_suffix": "_clear_mask.png"}
    ]
}

DEFAULT_ASSETS = {"stickers": [], "categories": ["全部"]}

# === 前台 API ===
@app.route('/')
def home():
    return send_file('index.html')

@app.route('/api/shop_data', methods=['GET'])
def get_shop_data():
    return jsonify({"status": "success", "data": load_json(DATA_FILE, DEFAULT_SHOP_DATA)})

@app.route('/api/assets', methods=['GET'])
def get_assets():
    return jsonify({"status": "success", "data": load_json(ASSETS_FILE, DEFAULT_ASSETS)})

@app.route('/api/create_order', methods=['POST'])
def create_order():
    try:
        data = request.json
        print_data = base64.b64decode(data['print_file'].split(',')[1])
        mockup_data = base64.b64decode(data['mockup_file'].split(',')[1])
        model_name = data.get('model_name', 'Unknown')
        style_name = data.get('style_name', 'Unknown')
        price = data.get('price', 0)
        
        timestamp = int(time.time())
        order_prefix = f"Order_{timestamp}_{model_name}"
        
        with open(os.path.join(SAVE_DIR, f"{order_prefix}_print.png"), 'wb') as f:
            f.write(print_data)
        with open(os.path.join(SAVE_DIR, f"{order_prefix}_mockup.png"), 'wb') as f:
            f.write(mockup_data)
            
        order_info = {
            "order_id": f"ORD{timestamp}",
            "model": model_name,
            "style": style_name,
            "price": price,
            "status": "待付款",
            "time": timestamp
        }
        with open(os.path.join(SAVE_DIR, f"{order_prefix}_info.json"), 'w', encoding='utf-8') as f:
            json.dump(order_info, f, ensure_ascii=False, indent=4)
            
        return jsonify({"status": "success", "msg": "訂單建立成功"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

# === 後台管理 API ===
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
        else:
            return "密碼錯誤", 401
    return '''
        <body style="display:flex; justify-content:center; align-items:center; height:100vh; background:#f0f2f5; font-family:sans-serif;">
            <form method="POST" style="background:white; padding:40px; border-radius:8px; box-shadow:0 2px 12px rgba(0,0,0,0.1); text-align:center;">
                <h2 style="color:#409EFF; margin-top:0;">後台管理系統</h2>
                <input type="password" name="password" placeholder="請輸入密碼" style="padding:10px; width:220px; margin-bottom:20px; border:1px solid #dcdfe6; border-radius:4px;"><br>
                <button type="submit" style="background:#409EFF; color:white; border:none; padding:10px 30px; border-radius:4px; cursor:pointer;">登入</button>
            </form>
        </body>
    '''

@app.route('/api/admin/save_shop_data', methods=['POST'])
def admin_save_shop_data():
    if not session.get('logged_in'):
        return jsonify({"status": "error", "msg": "未授權"}), 401
    try:
        data = request.json
        # 直接覆寫 shop_data.json，保留所有原汁原味的品項名稱與縮寫
        save_json(DATA_FILE, data)
        return jsonify({"status": "success", "msg": "資料儲存成功"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
