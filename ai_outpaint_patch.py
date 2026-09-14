"""Generative image expansion endpoint backed by the existing Runpod worker."""
import base64
import time
from flask import request, Response

_INSTALLED = False


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    app = app_module.app
    no_cache_json = app_module.no_cache_json

    @app.route('/api/ai/outpaint', methods=['POST'])
    def ai_outpaint():
        if not app_module.AI_ENABLED:
            return no_cache_json({'status':'error','code':'AI_NOT_CONFIGURED','msg':'AI 尚未連線'}, 503)

        image = request.files.get('image')
        if not image or not image.filename:
            return no_cache_json({'status':'error','msg':'沒有收到圖片'}, 400)
        mime = (image.mimetype or '').lower()
        if mime not in ('image/png','image/jpeg','image/webp'):
            return no_cache_json({'status':'error','msg':'AI 擴圖只接受 PNG / JPG / WEBP'}, 400)
        raw = image.read()
        if not raw:
            return no_cache_json({'status':'error','msg':'圖片內容是空的'}, 400)
        if len(raw) > 8 * 1024 * 1024:
            return no_cache_json({'status':'error','msg':'AI 擴圖輸入需小於 8MB，系統會先最佳化後再送出'}, 400)

        direction = str(request.form.get('direction') or 'all').lower()
        if direction not in ('all','left','right','top','up','bottom','down'):
            direction = 'all'
        try:
            ratio = float(request.form.get('expand_ratio') or 1.35)
        except Exception:
            ratio = 1.35
        ratio = max(1.10, min(1.80, ratio))
        prompt = str(request.form.get('prompt') or '').strip()[:500]

        job_id = ''
        started = time.monotonic()
        try:
            payload = {
                'input': {
                    'task': 'outpaint',
                    'image_base64': base64.b64encode(raw).decode('ascii'),
                    'mime_type': mime,
                    'direction': direction,
                    'expand_ratio': ratio,
                    'prompt': prompt,
                    'max_output_edge': 1600,
                }
            }
            job_id, _ = app_module._runpod_submit(payload)
            deadline = started + app_module.AI_REMOVE_BG_TIMEOUT
            result, retried = app_module._runpod_wait_for_result(job_id, deadline)
            output = result.get('output') or {}
            if not isinstance(output, dict) or output.get('status') == 'error':
                detail = output.get('error') if isinstance(output, dict) else 'invalid output'
                return no_cache_json({'status':'error','code':'AI_WORKER_ERROR','msg':f'AI 擴圖失敗：{detail}'}, 502)
            encoded = output.get('image_base64') or ''
            if not encoded:
                return no_cache_json({'status':'error','code':'AI_EMPTY_OUTPUT','msg':'AI 沒有回傳擴圖結果'}, 502)
            try:
                png = base64.b64decode(encoded, validate=True)
            except Exception:
                return no_cache_json({'status':'error','code':'AI_BAD_IMAGE_DATA','msg':'AI 擴圖資料無法解析'}, 502)
            if not png.startswith(b'\x89PNG\r\n\x1a\n'):
                return no_cache_json({'status':'error','code':'AI_NOT_PNG','msg':'AI 擴圖回傳格式錯誤'}, 502)
            if len(png) > 24 * 1024 * 1024:
                return no_cache_json({'status':'error','code':'AI_OUTPUT_TOO_LARGE','msg':'AI 擴圖結果過大'}, 502)

            resp = Response(png, mimetype='image/png')
            resp.headers['Cache-Control'] = 'no-store'
            resp.headers['X-AI-Task'] = 'outpaint'
            resp.headers['X-AI-Model'] = str(output.get('model') or '')[:120]
            resp.headers['X-AI-Job-ID'] = job_id[:120]
            resp.headers['X-AI-Retried'] = '1' if retried else '0'
            return resp
        except TimeoutError as exc:
            return no_cache_json({'status':'error','code':'AI_TIMEOUT','job_id':job_id,'msg':'AI 擴圖排隊或生成逾時，請再試一次','detail':str(exc)[:240]}, 504)
        except Exception as exc:
            try:
                app_module._runpod_cancel(job_id)
            except Exception:
                pass
            print('[AI] outpaint error:', repr(exc), flush=True)
            return no_cache_json({'status':'error','code':'AI_OUTPAINT_ERROR','msg':f'AI 擴圖失敗：{exc}'}, 502)

    print('[AI] shared /api/ai/outpaint endpoint enabled', flush=True)
