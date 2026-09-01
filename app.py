from flask import Flask, request, jsonify, send_file, session, redirect, url_for
import base64
import time
import os
import json

app = Flask(__name__)
# 設定 Session 的安全密鑰 (必須要有才能使用密碼驗證)
app.secret_key = 'fan_super_secret_key_2026' 

# 定義資料夾與檔案路徑
SAVE_DIR = "orders"
STATIC_DIR = "static"
CONFIG_FILE = "models_config.json"
ADMIN_PASSWORD = "fan123" # 老闆專屬後台密碼

# 確保資料夾存在
for d in [SAVE_DIR, STATIC_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

# 確保參數設定檔存在
if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump({}, f)

# 讀取參數設定
def load_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

# 儲存參數設定
def save_config(data):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# ==================== 前台路由與 API ====================

@app.route('/')
def home():
    return send_file('index.html')

@app.route('/api/get_models', methods=['GET'])
def get_models():
    try:
        config_data = load_config()
        models = []
        # 將設定檔內的資料轉換為前端需要的格式
        for key, info in config_data.items():
            models.append({
                "id": key,
                "name": info.get("name", "未命名"),
                "filename": info.get("mask_img", ""),
                "print_width": info.get("print_width", 0),
                "print_height": info.get("print_height", 0)
            })
        return jsonify({"status": "success", "models": models})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/create_order', methods=['POST'])
def create_order():
    try:
        data = request.json
        print_data = base64.b64decode(data['print_file'].split(',')[1])
        mockup_data = base64.b64decode(data['mockup_file'].split(',')[1])
        model_id = data.get('model_id', 'unknown')
        
        timestamp = int(time.time())
        order_prefix = f"Order_{timestamp}_{model_id}"
        
        # 儲存圖片
        with open(os.path.join(SAVE_DIR, f"{order_prefix}_print.png"), 'wb') as f:
            f.write(print_data)
        with open(os.path.join(SAVE_DIR, f"{order_prefix}_mockup.png"), 'wb') as f:
            f.write(mockup_data)
            
        # 讀取並儲存該型號的列印參數 (給印表機用)
        config_data = load_config()
        if model_id in config_data:
            with open(os.path.join(SAVE_DIR, f"{order_prefix}_settings.json"), 'w', encoding='utf-8') as f:
                json.dump(config_data[model_id], f, ensure_ascii=False, indent=4)
            
        return jsonify({"status": "success", "msg": "訂單與參數已成功存入 orders！"})
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

# ==================== 後台路由與 API (需密碼保護) ====================

@app.route('/admin')
def admin_page():
    # 檢查是否有登入權限
    if not session.get('logged_in'):
        return redirect(url_for('login_page'))
    return send_file('admin.html')

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        # 簡易的前端登入驗證
        password = request.form.get('password')
        if password == ADMIN_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('admin_page'))
        else:
            return "密碼錯誤，請回上一頁重試", 401
    
    # 登入畫面 HTML (直接寫在伺服器裡最安全)
    return '''
        <html>
            <head><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>後台登入</title></head>
            <body style="font-family: sans-serif; display: flex; justify-content: center; align-items: center; height: 100vh; background: #f0f0f0;">
                <form method="POST" style="background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 10px rgba(0,0,0,0.1); text-align: center;">
                    <h2 style="color: #ff6a48; margin-top:0;">後台管理系統</h2>
                    <input type="password" name="password" placeholder="請輸入管理員密碼" style="padding: 10px; width: 200px; margin-bottom: 15px; border: 1px solid #ccc; border-radius: 5px;"><br>
                    <button type="submit" style="background: #ff6a48; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; font-weight: bold;">登入</button>
                </form>
            </body>
        </html>
    '''

@app.route('/api/admin/save_model', methods=['POST'])
def admin_save_model():
    if not session.get('logged_in'):
        return jsonify({"status": "error", "msg": "未授權"}), 401
    
    try:
        data = request.json
        model_id = data.get('id')
        if not model_id:
            return jsonify({"status": "error", "msg": "缺少型號 ID"}), 400
            
        config_data = load_config()
        # 寫入或更新該型號的所有參數
        config_data[model_id] = {
            "name": data.get("name"),
            "mask_img": data.get("mask_img"),
            "base_img": data.get("base_img"),
            "print_width": float(data.get("print_width", 0)),
            "print_height": float(data.get("print_height", 0)),
            "start_x": float(data.get("start_x", 0)),
            "start_y": float(data.get("start_y", 0)),
            "angle": float(data.get("angle", 0))
        }
        save_config(config_data)
        return jsonify({"status": "success", "msg": "參數儲存成功"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/admin/get_all_models', methods=['GET'])
def admin_get_all_models():
    if not session.get('logged_in'):
        return jsonify({"status": "error", "msg": "未授權"}), 401
    return jsonify({"status": "success", "data": load_config()})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
