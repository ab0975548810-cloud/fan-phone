from flask import Flask, request, jsonify, send_file, session, redirect, url_for
import os
import json
import time

app = Flask(__name__)
app.secret_key = 'fan_super_secret_key_2026' 

# 系統檔案路徑設定
SAVE_DIR = "orders"
STATIC_DIR = "static"
DATA_FILE = "shop_data.json"

# 確保資料夾存在
for d in [SAVE_DIR, STATIC_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

# 預設商品資料庫 (如果沒有檔案，伺服器會自動建立這份初始資料)
DEFAULT_SHOP_DATA = {
    "brands": ["Apple", "Samsung", "Google"],
    "models": [
        {"id": "ip17pm", "brand": "Apple", "name": "iPhone 17 Pro Max"},
        {"id": "ip17p", "brand": "Apple", "name": "iPhone 17 Pro"},
        {"id": "ip17", "brand": "Apple", "name": "iPhone 17"},
        {"id": "ip16pm", "brand": "Apple", "name": "iPhone 16 Pro Max"},
        {"id": "ip16p", "brand": "Apple", "name": "iPhone 16 Pro"},
        {"id": "ip16", "brand": "Apple", "name": "iPhone 16"},
        {"id": "ip15pm", "brand": "Apple", "name": "iPhone 15 Pro Max"},
        {"id": "ip15p", "brand": "Apple", "name": "iPhone 15 Pro"},
        {"id": "s24u", "brand": "Samsung", "name": "Galaxy S24 Ultra"}
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

# ==================== 前台 API ====================

@app.route('/')
def home():
    return send_file('index.html')

@app.route('/api/shop_data', methods=['GET'])
def get_shop_data():
    """提供前台所有品牌、型號與款式資料"""
    return jsonify({"status": "success", "data": load_shop_data()})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
