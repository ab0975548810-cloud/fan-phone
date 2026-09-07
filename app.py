from flask import Flask, request, jsonify, send_file, session, redirect, url_for
import os
import json
import time
import base64

app = Flask(__name__)
app.secret_key = 'fan_super_secret_key_2026' 
ADMIN_PASSWORD = "fan123"

# 資料夾架構
SAVE_DIR = "orders"
STATIC_DIR = "static"
STICKER_DIR = os.path.join(STATIC_DIR, "stickers")
MATERIAL_DIR = os.path.join(STATIC_DIR, "materials") # 新增：放遮罩與線圖的資料夾
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

# 預設商品資料架構 (加入完整的材質參數)
DEFAULT_SHOP_DATA = {
    "brands": ["蘋果", "三星"],
    "models": [
        {"id": "ip17pm", "brand": "蘋果", "name": "iPhone 17 Pro Max", "status": True}
    ],
    "styles": [
        {
            "id": "clear_01", 
            "name": "氣囊防摔透明殼", 
            "colors": "透明",
            "status": True,
            "print_x": 0, "print_y": 0, "print_w": 80, "print_h": 160,
            "mask_img": "", "line_img": ""
        }
    ]
}
DEFAULT_ASSETS = {"stickers": [], "categories": ["全部", "可愛", "Y2K", "文字"]}

@app.route('/')
def home():
    return send_file('index.html')

@app.route('/api/shop_data', methods=['GET'])
def get_shop_data():
    return jsonify({"status": "success", "data": load_json(DATA_FILE, DEFAULT_SHOP_DATA)})

@app.route('/api/assets', methods=['GET'])
def get_assets():
    return jsonify({"status": "success", "data": load_json(ASSETS_FILE, DEFAULT_ASSETS)})

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
        # 直接寫入，保證 (片鏡頭貼) 等特殊字眼不會被修改
        save_json(DATA_FILE, request.json)
        return jsonify({"status": "success", "msg": "資料儲存成功"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

# === 升級：支援批量上傳的 API ===
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
                # 加上微秒防止檔名重複
                filename = f"s_{int(time.time()*1000)}_{file.filename}"
                filepath = os.path.join(STICKER_DIR, filename)
                file.save(filepath)
                
                assets['stickers'].append({
                    "id": filename,
                    "category": category,
                    "url": f"/static/stickers/{filename}"
                })
                count += 1
                
        if category not in assets['categories']:
            assets['categories'].append(category)
            
        save_json(ASSETS_FILE, assets)
        return jsonify({"status": "success", "msg": f"成功批量上傳 {count} 張素材！"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/admin/delete_sticker', methods=['POST'])
def admin_delete_sticker():
    if not session.get('logged_in'): return jsonify({"status": "error"}), 401
    try:
        sticker_id = request.json.get('id')
        assets = load_json(ASSETS_FILE, DEFAULT_ASSETS)
        assets['stickers'] = [s for s in assets['stickers'] if s['id'] != sticker_id]
        save_json(ASSETS_FILE, assets)
        return jsonify({"status": "success", "msg": "素材已刪除"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
