"""Unified AI endpoints for Benfuwan: background removal + real generative outpainting."""
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

    def _run(task):
        if not app_module.AI_ENABLED:
            return no_cache_json({'status':'error','code':'AI_NOT_CONFIGURED','msg':'AI 尚未連線'}, 503)
        image = request.files.get('image')
        if not image or not image.filename:
            return no_cache_json({'status':'error','msg':'沒有收到圖片'}, 400)
        mime = (image.mimetype or '').lower()
        if mime not in ('image/png','image/jpeg','image/webp'):
            return no_cache_json({'status':'error','msg':'只接受 PNG / JPG / WEBP'}, 400)
        raw = image.read()
        if not raw:
            return no_cache_json({'status':'error','msg':'圖片內容是空的'}, 400)
        if len(raw) > 8 * 1024 * 1024:
            return no_cache_json({'status':'error','msg':'AI 圖片需小於 8MB，系統會先自動最佳化'}, 400)

        job_id = ''
        started = time.monotonic()
        try:
            inp = {
                'task': task,
                'image_base64': base64.b64encode(raw).decode('ascii'),
                'mime_type': mime,
                'max_output_edge': 1800 if task == 'remove_background' else 1280,
            }
            if task == 'outpaint':
                inp.update({
                    'direction': str(request.form.get('direction') or 'all'),
                    'expand_ratio': float(request.form.get('expand_ratio') or 1.35),
                    'prompt': str(request.form.get('prompt') or '').strip(),
                    'preserve_subject': True,
                })
            job_id, _ = app_module._runpod_submit({'input': inp})
            deadline = started + app_module.AI_REMOVE_BG_TIMEOUT
            result, retried = app_module._runpod_wait_for_result(job_id, deadline)
            output = result.get('output') or {}
            if not isinstance(output, dict) or output.get('status') == 'error':
                detail = output.get('error') if isinstance(output, dict) else 'invalid output'
                return no_cache_json({'status':'error','code':'AI_WORKER_ERROR','msg':f'AI 處理失敗：{detail}'}, 502)
            encoded = output.get('image_base64') or ''
            png = base64.b64decode(encoded, validate=True)
            if not png.startswith(b'\x89PNG\r\n\x1a\n'):
                return no_cache_json({'status':'error','code':'AI_NOT_PNG','msg':'AI 回傳格式錯誤'}, 502)
            resp = Response(png, mimetype='image/png')
            resp.headers['Cache-Control'] = 'no-store'
            resp.headers['X-AI-Task'] = task
            resp.headers['X-AI-Job-ID'] = job_id[:120]
            resp.headers['X-AI-Retried'] = '1' if retried else '0'
            resp.headers['X-AI-Model'] = str(output.get('model') or '')[:160]
            if output.get('width') is not None:
                resp.headers['X-AI-Width'] = str(output.get('width'))
            if output.get('height') is not None:
                resp.headers['X-AI-Height'] = str(output.get('height'))
            return resp
        except TimeoutError as exc:
            return no_cache_json({'status':'error','code':'AI_TIMEOUT','job_id':job_id,'msg':'AI 啟動或排隊時間較久，請再試一次','detail':str(exc)[:300]}, 504)
        except Exception as exc:
            try:
                app_module._runpod_cancel(job_id)
            except Exception:
                pass
            print('[AI TOOLS] error:', task, repr(exc), flush=True)
            return no_cache_json({'status':'error','code':'AI_ERROR','msg':f'AI 處理失敗：{exc}'}, 502)

    @app.route('/api/ai/outpaint', methods=['POST'])
    def ai_outpaint():
        return _run('outpaint')

    @app.route('/api/ai/remove-background-v2', methods=['POST'])
    def ai_remove_background_v2():
        return _run('remove_background')

    print('[AI] unified remove-background + real outpaint endpoints enabled', flush=True)
