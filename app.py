from flask import Flask, request, jsonify, send_file
import os
import json
import time
import base64

app = Flask(__name__)
app.secret_key = 'fan_super_secret_key_2026' 

SAVE_DIR = "orders"
STATIC_DIR = "static"
DATA_FILE = "shop_data.json"
ASSETS_FILE = "assets.json" # 新增素材資料庫

for d in [SAVE_DIR, STATIC_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

# 預設商品資料
DEFAULT_SHOP_DATA = {
    "brands": ["Apple", "Samsung"],
    "models": [
        {"id": "ip17pm", "brand": "Apple", "name": "iPhone 17 Pro Max"},
        {"id": "ip17p", "brand": "Apple", "name": "iPhone 17 Pro"},
        {"id": "ip16pm", "brand": "Apple", "name": "iPhone 16 Pro Max"}
    ],
    "styles": [
        {"id": "clear", "name": "透明防摔殼", "price": 390, "desc": "軍規防摔", "mask_suffix": "_clear_mask.png"},
        {"id": "black", "name": "黑色邊框殼", "price": 450, "desc": "親膚材質", "mask_suffix": "_black_mask.png"}
    ]
}

# 預設貼紙素材資料 (老闆之後可以在後台替換這些網址或上傳實體檔案)
DEFAULT_ASSETS = {
    "stickers": [
        {"id": "s1", "category": "可愛", "url": "https://cdn-icons-png.flaticon.com/512/826/826963.png"},
        {"id": "s2", "category": "可愛", "url": "https://cdn-icons-png.flaticon.com/512/826/826939.png"},
        {"id": "s3", "category": "Y2K", "url": "https://cdn-icons-png.flaticon.com/512/766/766030.png"},
        {"id": "s4", "category": "動物", "url": "https://cdn-icons-png.flaticon.com/512/2990/2990666.png"},
        {"id": "s5", "category": "動物", "url": "https://cdn-icons-png.flaticon.com/512/3069/3069172.png"}
    ],
    "categories": ["全部", "可愛", "Y2K", "動物"]
}

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

@app.route('/')
def home():
    return send_file('index.html')

@app.route('/api/shop_data', methods=['GET'])
def get_shop_data():
    return jsonify({"status": "success", "data": load_json(DATA_FILE, DEFAULT_SHOP_DATA)})

@app.route('/api/assets', methods=['GET'])
def get_assets():
    """提供前台所有貼紙與素材資料"""
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
            
        return jsonify({"status": "success", "msg": "訂單已成功建立，加入購物車！"})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
