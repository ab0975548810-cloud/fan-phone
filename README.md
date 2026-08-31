
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
<!DOCTYPE html>
<html lang="zh-TW">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>客製化手機殼 - 純淨無暇版</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/fabric.js/5.3.1/fabric.min.js"></script>
    <style>
        :root { --bg-color: #f7f7f7; --canvas-bg: #e2e4e9; --text-main: #333333; --primary-color: #4A90E2; --panel-bg: #ffffff; --border-color: #eeeeee; }
        body { margin: 0; padding: 0; font-family: -apple-system, sans-serif; background-color: var(--bg-color); color: var(--text-main); display: flex; justify-content: center; height: 100vh; overflow: hidden; touch-action: manipulation; }
        .app-container { width: 100%; max-width: 500px; background: var(--bg-color); display: flex; flex-direction: column; height: 100%; position: relative; overflow: hidden; }
        .page { display: none; flex-direction: column; height: 100%; animation: fadeIn 0.3s ease; }
        .page.active { display: flex; }
        @keyframes fadeIn { from { opacity: 0; transform: translateX(10px); } to { opacity: 1; transform: translateX(0); } }
        .top-nav { height: 50px; background: var(--panel-bg); display: flex; justify-content: space-between; align-items: center; padding: 0 15px; border-bottom: 1px solid var(--border-color); flex-shrink: 0; z-index: 10; }
        .nav-btn { background: none; border: none; font-size: 16px; color: var(--text-main); cursor: pointer; font-weight: bold;}
        .title { font-weight: 600; font-size: 16px; }
        .content { flex: 1; overflow-y: auto; padding: 20px; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }
        .card-btn { background: var(--panel-bg); border: 2px solid var(--border-color); border-radius: 12px; padding: 20px 10px; text-align: center; font-weight: bold; cursor: pointer; transition: 0.2s; }
        .card-btn:hover, .card-btn.selected { border-color: var(--primary-color); background: #f0f7ff; color: var(--primary-color); }
        .workspace { flex: 1; background: var(--canvas-bg); display: flex; justify-content: center; align-items: center; position: relative; }
        .canvas-container-wrapper { width: 260px; height: 520px; background: white; border-radius: 35px; box-shadow: 0 10px 30px rgba(0,0,0,0.1); position: relative; overflow: hidden; }
        .phone-mask-img { position: absolute; top: 0; left: 0; width: 100%; height: 100%; pointer-events: none; z-index: 5; object-fit: contain; }
        .bottom-panel { background: var(--panel-bg); border-top: 1px solid var(--border-color); padding-bottom: 10px; z-index: 10;}
        .toolbar { display: flex; justify-content: space-around; padding: 10px; overflow-x: auto; white-space: nowrap; scrollbar-width: none; }
        .toolbar::-webkit-scrollbar { display: none; }
        .tool-btn { display: flex; flex-direction: column; align-items: center; gap: 6px; background: none; border: none; min-width: 60px; color: var(--text-main); cursor: pointer; }
        .tool-btn i { font-size: 20px; } .tool-btn span { font-size: 11px; }
        #toolbar-main { display: flex; }
        #toolbar-object { display: none; }
        .editing-mode #toolbar-main { display: none; }
        .editing-mode #toolbar-object { display: flex; }
        .drawer { position: absolute; bottom: -100%; left: 0; width: 100%; height: 280px; background: white; border-radius: 20px 20px 0 0; box-shadow: 0 -5px 15px rgba(0,0,0,0.1); transition: bottom 0.3s cubic-bezier(0.25, 0.8, 0.25, 1); z-index: 20; display: flex; flex-direction: column; }
        .drawer.active { bottom: 0; }
        .drawer-header { display: flex; justify-content: space-between; padding: 15px 20px; border-bottom: 1px solid #eee; font-weight: bold; }
        .drawer-content { flex: 1; overflow-y: auto; padding: 20px; }
        .close-drawer { background: none; border: none; font-size: 20px; cursor: pointer; color: #888; }
        .sticker-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; }
        .sticker-item { text-align: center; background: #f4f4f4; border-radius: 10px; padding: 10px; cursor: pointer; display: flex; flex-direction: column; justify-content: center; align-items: center; overflow: hidden; height: 100px; }
        .sticker-item img { width: 100%; height: 100%; object-fit: cover; border-radius: 5px; }
        .text-input-box { width: 90%; padding: 15px; border: 1px solid #ddd; border-radius: 10px; font-size: 16px; margin-bottom: 15px; }
        .add-text-btn { background: var(--primary-color); color: white; border: none; padding: 12px 20px; border-radius: 10px; font-weight: bold; width: 100%; cursor: pointer;}
        .overlay { position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.4); z-index: 15; display: none; opacity: 0; transition: opacity 0.3s; }
        .overlay.active { display: block; opacity: 1; }
        .checkout-btn { width: 100%; background: var(--primary-color); color: white; border: none; padding: 15px; border-radius: 12px; font-size: 16px; font-weight: bold; margin-top: 20px; cursor: pointer;}
        .cart-preview-container { position: relative; width: 150px; height: 300px; margin: 10px auto; border-radius: 20px; overflow: hidden; box-shadow: 0 5px 15px rgba(0,0,0,0.1); background: white; }
        .preview-img { width: 100%; height: 100%; object-fit: cover; display: block; }
    </style>
</head>
<body>
<div class="app-container">
    <div id="page-model" class="page active">
        <div class="top-nav"><button class="nav-btn"></button><div class="title">選擇手機型號</div><button class="nav-btn"></button></div>
        <div class="content">
            <h3 style="margin-top:0;">支援的型號列表</h3>
            <div class="grid-2" id="auto-model-grid">
                <div style="grid-column: span 2; text-align: center; color: #888;">正在掃描資料夾...</div>
            </div>
        </div>
    </div>
    <div id="page-style" class="page">
        <div class="top-nav"><button class="nav-btn" onclick="goToPage('page-model')"><i class="fa-solid fa-chevron-left"></i></button><div class="title">殼套材質</div><button class="nav-btn"></button></div>
        <div class="content">
            <h3 style="margin-top:0;">選擇材質</h3>
            <div class="grid-2"><div class="card-btn" onclick="selectStyle(this, '雙料防摔軟殼')">雙料防摔軟殼</div></div>
            <button class="checkout-btn" onclick="goToPage('page-mode')">確認，下一步</button>
        </div>
    </div>
    <div id="page-mode" class="page">
        <div class="top-nav"><button class="nav-btn" onclick="goToPage('page-style')"><i class="fa-solid fa-chevron-left"></i></button><div class="title">選擇設計方式</div><button class="nav-btn"></button></div>
        <div class="content" style="display: flex; flex-direction: column; gap: 20px; justify-content: center;">
            <div class="card-btn" style="padding: 40px 20px;" onclick="goToPage('page-editor'); initCanvas();">
                <i class="fa-solid fa-pen-ruler" style="font-size: 40px; color:var(--primary-color); margin-bottom: 15px;"></i>
                <h2>客製 DIY (點此進入)</h2>
            </div>
        </div>
    </div>
    
    <div id="page-editor" class="page">
        <div class="top-nav">
            <button class="nav-btn" onclick="goToPage('page-mode')"><i class="fa-solid fa-chevron-left"></i></button>
            <div class="title" id="editor-title" style="font-size: 14px;">自訂義手機殼</div>
            <button class="nav-btn" style="color:var(--primary-color);" onclick="exportToCart()">完成</button>
        </div>
        <div class="workspace" id="workspace">
            <div class="canvas-container-wrapper">
                <canvas id="main-canvas"></canvas>
                <!-- 乾淨的遮罩圖片，沒有假鏡頭干擾 -->
                <img id="real-phone-mask" class="phone-mask-img" src="" alt="機型遮罩" onerror="this.style.display='none'" onload="this.style.display='block'">
            </div>
            
            <div class="overlay" id="overlay" onclick="closeAllDrawers()"></div>
            <div class="drawer" id="drawer-bg">
                <div class="drawer-header"><span>選擇滿版底圖</span><button class="close-drawer" onclick="closeAllDrawers()"><i class="fa-solid fa-xmark"></i></button></div>
                <div class="drawer-content">
                    <div class="sticker-grid">
                        <div class="sticker-item" onclick="setBackground('https://wsrv.nl/?url=https://images.unsplash.com/photo-1508614589041-895b88991e3e?w=400&q=80')"><img src="https://wsrv.nl/?url=https://images.unsplash.com/photo-1508614589041-895b88991e3e?w=400&q=80"></div>
                        <div class="sticker-item" onclick="removeBackground()" style="background:#fff; border:2px dashed #ccc;"><span style="font-size: 12px; font-weight:bold; color:#888;">移除底圖</span></div>
                    </div>
                </div>
            </div>
            <div class="drawer" id="drawer-text">
                <div class="drawer-header"><span>輸入文字</span><button class="close-drawer" onclick="closeAllDrawers()"><i class="fa-solid fa-xmark"></i></button></div>
                <div class="drawer-content">
                    <input type="text" id="custom-text-input" class="text-input-box" placeholder="輸入你想打的字">
                    <button class="add-text-btn" onclick="addText()">確認</button>
                </div>
            </div>
            <input type="file" id="real-file-upload" accept="image/*" style="display: none;" onchange="uploadImage(event)">
        </div>
        
        <div class="bottom-panel" id="bottom-panel">
            <div class="toolbar" id="toolbar-object">
                <button class="tool-btn" onclick="deselectAll()"><i class="fa-solid fa-check"></i><span>完成</span></button>
                <div style="width: 1px; background: #eee; margin: 5px; height: 30px;"></div>
                <button class="tool-btn" onclick="bringForward()"><i class="fa-solid fa-layer-group"></i><span>上移</span></button>
                <button class="tool-btn" onclick="sendBackward()"><i class="fa-solid fa-layer-group" style="transform: rotate(180deg);"></i><span>下移</span></button>
                <button class="tool-btn" onclick="deleteObject()" style="color:red;"><i class="fa-solid fa-trash"></i><span>刪除</span></button>
            </div>
            <div class="toolbar" id="toolbar-main">
                <button class="tool-btn" onclick="openDrawer('drawer-bg')"><i class="fa-solid fa-border-all" style="color:var(--primary-color);"></i><span style="color:var(--primary-color);">選底圖</span></button>
                <button class="tool-btn" onclick="document.getElementById('real-file-upload').click()"><i class="fa-solid fa-image"></i><span>上傳圖片</span></button>
                <button class="tool-btn" onclick="openDrawer('drawer-text')"><i class="fa-solid fa-t"></i><span>加文字</span></button>
            </div>
        </div>
    </div>
    
    <div id="page-cart" class="page">
        <div class="top-nav"><button class="nav-btn" onclick="goToPage('page-editor')"><i class="fa-solid fa-chevron-left"></i></button><div class="title">確認訂單</div><button class="nav-btn"></button></div>
        <div class="content">
            <h2 style="text-align:center;">🛒 您的專屬設計</h2>
            <div class="cart-preview-container">
                <img id="final-preview-img" class="preview-img" src="">
                <img id="cart-phone-mask" class="phone-mask-img" src="">
            </div>
            <button class="checkout-btn" onclick="submitOrderToServer()"><i class="fa-solid fa-print"></i> 送單並列印</button>
        </div>
    </div>
</div>

<script>
    let currentMaskUrl = "";
    
    window.onload = async () => {
        try {
            const res = await fetch('/api/get_models');
            const data = await res.json();
            const grid = document.getElementById('auto-model-grid');
            grid.innerHTML = '';
            if (data.models.length > 0) {
                data.models.forEach(m => {
                    const btn = document.createElement('div');
                    btn.className = 'card-btn';
                    btn.innerText = m.name;
                    btn.onclick = () => selectModel(m.filename);
                    grid.appendChild(btn);
                });
            } else {
                grid.innerHTML = '<div style="grid-column:span 2; text-align:center; color:red;">static 資料夾裡沒有圖片！</div>';
            }
        } catch (e) {
            document.getElementById('auto-model-grid').innerHTML = '<div style="grid-column:span 2; text-align:center; color:red;">載入失敗，請確認終端機沒報錯</div>';
        }
    };

    function selectModel(filename) {
        currentMaskUrl = "/static/" + filename;
        document.getElementById('real-phone-mask').src = currentMaskUrl;
        document.getElementById('cart-phone-mask').src = currentMaskUrl;
        goToPage('page-style');
    }

    function selectStyle(btn, value) { document.querySelectorAll('.card-btn').forEach(el => el.classList.remove('selected')); btn.classList.add('selected'); }
    function goToPage(id) { document.querySelectorAll('.page').forEach(p => p.classList.remove('active')); document.getElementById(id).classList.add('active'); }

    let canvas; 
    function initCanvas() {
        if(canvas) return;
        canvas = new fabric.Canvas('main-canvas', { width: 260, height: 520, backgroundColor: '#ffffff', preserveObjectStacking: true });
        canvas.on('selection:created', showObjectToolbar); canvas.on('selection:updated', showObjectToolbar); canvas.on('selection:cleared', showMainToolbar);
        fabric.Object.prototype.set({ transparentCorners: false, cornerColor: '#4A90E2', borderColor: '#4A90E2' });
    }

    function setBackground(url) { fabric.Image.fromURL(url, img => { const scale = Math.max(canvas.width/img.width, canvas.height/img.height); img.set({ originX:'center', originY:'center', left:canvas.width/2, top:canvas.height/2, scaleX:scale, scaleY:scale }); canvas.setBackgroundImage(img, canvas.renderAll.bind(canvas)); closeAllDrawers(); }, { crossOrigin: 'anonymous' }); }
    function removeBackground() { canvas.setBackgroundImage(null, canvas.renderAll.bind(canvas)); closeAllDrawers(); }
    function addText() { const t = document.getElementById('custom-text-input').value; if(t) { const obj = new fabric.Textbox(t, { left:50, top:200, width:150, fontSize:30 }); canvas.add(obj); canvas.setActiveObject(obj); } closeAllDrawers(); }
    function uploadImage(e) { const f = e.target.files[0]; if(!f) return; const r = new FileReader(); r.onload = f => { fabric.Image.fromURL(f.target.result, img => { img.scaleToWidth(200); canvas.add(img); canvas.setActiveObject(img); }); }; r.readAsDataURL(f); e.target.value=''; }
    function deleteObject() { const obj = canvas.getActiveObject(); if(obj) canvas.remove(obj); }
    function bringForward() { const obj = canvas.getActiveObject(); if(obj) canvas.bringForward(obj); }
    function sendBackward() { const obj = canvas.getActiveObject(); if(obj) canvas.sendBackwards(obj); }
    function deselectAll() { canvas.discardActiveObject(); canvas.renderAll(); }
    function showObjectToolbar() { document.getElementById('bottom-panel').classList.add('editing-mode'); }
    function showMainToolbar() { document.getElementById('bottom-panel').classList.remove('editing-mode'); }
    function openDrawer(id) { document.getElementById('overlay').classList.add('active'); document.getElementById(id).classList.add('active'); }
    function closeAllDrawers() { document.getElementById('overlay').classList.remove('active'); document.querySelectorAll('.drawer').forEach(d => d.classList.remove('active')); }

    function exportToCart() { if(!canvas) return; deselectAll(); document.getElementById('final-preview-img').src = canvas.toDataURL({format:'png', multiplier:2}); goToPage('page-cart'); }

    async function submitOrderToServer() {
        if (!canvas) return;
        deselectAll(); 
        
        const printBase64 = canvas.toDataURL({ format: 'png', multiplier: 2 });
        alert("🔄 產生預覽圖中...");
        
        fabric.Image.fromURL(currentMaskUrl, async function(maskImg) {
            maskImg.set({ left: 0, top: 0, width: 260, height: 520, selectable: false });
            canvas.add(maskImg);
            canvas.renderAll();
            
            const mockupBase64 = canvas.toDataURL({ format: 'png', multiplier: 2 });
            
            canvas.remove(maskImg);
            canvas.renderAll();

            try {
                const res = await fetch('/api/create_order', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ print_file: printBase64, mockup_file: mockupBase64 })
                });
                const result = await res.json();
                if(res.ok) alert("✅ 成功！\n圖片已存入 orders 資料夾！");
                else alert("⚠️ 失敗：" + result.msg);
            } catch (err) { alert("連線錯誤！"); }
        });
    }
</script>
</body>
</html>
