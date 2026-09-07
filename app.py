from flask import Flask, request, jsonify, send_file, session, redirect, url_for
import os
import json
import time
import base64
import uuid # 新增這個來產生安全檔名

# ... (中間的設定保留不變) ...

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
                # 解決破圖：取得副檔名，並用 uuid 產生絕對安全的英數亂碼檔名
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

# ... (下方保留不變) ...
