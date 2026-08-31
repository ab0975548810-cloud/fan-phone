from flask import Flask, request, jsonify, send_file
import base64
import time
import os

app = Flask(__name__)

SAVE_DIR = "orders"
STATIC_DIR = "static"

for d in [SAVE_DIR, STATIC_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

@app.route('/')
def home():
    return send_file('index.html')

@app.route('/api/get_models', methods=['GET'])
def get_models():
    try:
        models = []
        for filename in os.listdir(STATIC_DIR):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                model_name = os.path.splitext(filename)[0]
                models.append({"name": model_name, "filename": filename})
        return jsonify({"status": "success", "models": models})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)}), 500

@app.route('/api/create_order', methods=['POST'])
def create_order():
    try:
        data = request.json
        print_data = base64.b64decode(data['print_file'].split(',')[1])
        mockup_data = base64.b64decode(data['mockup_file'].split(',')[1])
        
        timestamp = int(time.time())
        
        with open(os.path.join(SAVE_DIR, f"Order_{timestamp}_print.png"), 'wb') as f:
            f.write(print_data)
        with open(os.path.join(SAVE_DIR, f"Order_{timestamp}_mockup.png"), 'wb') as f:
            f.write(mockup_data)
            
        print("✅ 成功接單！")
        return jsonify({"status": "success", "msg": "圖片已存入 orders 資料夾！"})
    except Exception as e:
        print(f"❌ 錯誤: {e}")
        return jsonify({"status": "error", "msg": str(e)}), 500

if __name__ == '__main__':
    # 🌟 適應 Zeabur 雲端環境，讓雲端自己分配 Port
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 雲端伺服器啟動於 Port: {port}")
    app.run(host='0.0.0.0', port=port)