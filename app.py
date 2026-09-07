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

for d in [SAVE_DIR, STATIC_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

DEFAULT_SHOP_DATA = {
    "brands": ["Apple", "Samsung", "Google", "OPPO"],
    "models": [
        {"id": "ip17pm", "brand": "Apple", "name": "iPhone 17 Pro Max"},
        {"id": "ip17p", "brand": "Apple", "name": "iPhone 17 Pro"},
        {"id": "ip17", "brand": "Apple", "name": "iPhone 17"},
        {"id": "ip16pm", "brand": "Apple", "name": "iPhone 16 Pro Max"},
        {"id": "ip16p", "brand": "Apple", "name": "iPhone 16 Pro"}
    ],
    "styles": [
        {"id": "clear", "name": "透明防摔殼", "price": 390, "desc": "軍規防摔，晶瑩剔透", "mask_suffix": "_clear_mask.png"},
        {"id": "black", "name": "黑色邊框殼", "price": 450, "desc": "親膚材質，手感極佳", "mask_suffix": "_black_mask.png"},
        {"id": "magsafe", "name": "撞色磁吸殼", "price": 590, "desc": "支援 MagSafe 磁吸充電", "mask_suffix": "_mag_mask.png"}
    ]
}

def load_shop_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_SHOP_DATA, f, ensure_ascii=False, indent=4)
        return DEFAULT_SHOP_DATA
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return DEFAULT_SHOP_DATA

@app.route('/')
def home():
    return send_file('index.html')

@app.route('/api/shop_data', methods=['GET'])
def get_shop_data():
    return jsonify({"status": "success", "data": load_shop_data()})

@app.route('/api/create_order', methods=['POST'])
def create_order():
    try:
        data = request.json
        print_data = base64.b64decode(data['print_file'].split(',')[1])
        mockup_data = base64.b64decode(data['mockup_file'].split(',')[1])
        
        # 取得訂單資訊
        model_name = data.get('model_name', 'Unknown')
        style_name = data.get('style_name', 'Unknown')
        price = data.get('price', 0)
        
        timestamp = int(time.time())
        order_prefix = f"Order_{timestamp}_{model_name}"
        
        # 存圖片
        with open(os.path.join(SAVE_DIR, f"{order_prefix}_print.png"), 'wb') as f:
            f.write(print_data)
        with open(os.path.join(SAVE_DIR, f"{order_prefix}_mockup.png"), 'wb') as f:
            f.write(mockup_data)
            
        # 存訂單明細
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
        print(f"❌ 錯誤: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
