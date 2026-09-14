"""Generative outpaint endpoint using a dedicated Runpod endpoint.

Background removal stays on the lightweight BiRefNet endpoint. Outpainting is
routed to RUNPOD_OUTPAINT_ENDPOINT_ID so the large diffusion image can never
slow or block normal background removal.
"""
import base64
import os
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
    requests_lib = app_module.requests

    outpaint_endpoint_id = (os.environ.get('RUNPOD_OUTPAINT_ENDPOINT_ID') or '').strip()
    outpaint_api_base = (os.environ.get('RUNPOD_OUTPAINT_API_BASE') or app_module.RUNPOD_API_BASE or 'https://api.runpod.ai/v2').strip().rstrip('/')
    try:
        outpaint_timeout = int(os.environ.get('AI_OUTPAINT_TIMEOUT', '150') or 150)
    except Exception:
        outpaint_timeout = 150
    outpaint_timeout = max(60, min(240, outpaint_timeout))

    def _headers(include_json=False):
        h = {'Authorization': f'Bearer {app_module.RUNPOD_API_KEY}'}
        if include_json:
            h['Content-Type'] = 'application/json'
        return h

    def _json(resp, action):
        if resp.status_code < 200 or resp.status_code >= 300:
            detail = (resp.text or '').strip()[:400]
            raise RuntimeError(f'{action}失敗（HTTP {resp.status_code}）：{detail or "沒有錯誤內容"}')
        try:
            data = resp.json()
        except Exception as exc:
            raise RuntimeError(f'{action}回傳格式錯誤') from exc
        if not isinstance(data, dict):
            raise RuntimeError(f'{action}回傳內容不是 JSON object')
        return data

    def _submit(payload):
        resp = requests_lib.post(
            f'{outpaint_api_base}/{outpaint_endpoint_id}/run',
            headers=_headers(True),
            json=payload,
            timeout=15,
        )
        data = _json(resp, 'AI 擴圖工作送出')
        job_id = str(data.get('id') or '').strip()
        if not job_id:
            raise RuntimeError('AI 擴圖工作沒有 Job ID')
        return job_id

    def _cancel(job_id):
        if not job_id:
            return
        try:
            requests_lib.post(
                f'{outpaint_api_base}/{outpaint_endpoint_id}/cancel/{job_id}',
                headers=_headers(), timeout=8
            )
        except Exception:
            pass

    def _wait(job_id, deadline):
        last = 'IN_QUEUE'
        while time.monotonic() < deadline:
            try:
                resp = requests_lib.get(
                    f'{outpaint_api_base}/{outpaint_endpoint_id}/status/{job_id}',
                    headers=_headers(), timeout=15
                )
            except Exception as exc:
                print('[AI] outpaint status transient:', repr(exc), flush=True)
                time.sleep(1.5)
                continue
            if resp.status_code in (408, 425, 429, 500, 502, 503, 504):
                time.sleep(1.5)
                continue
            data = _json(resp, 'AI 擴圖狀態查詢')
            status = str(data.get('status') or '').upper()
            last = status or last
            if status == 'COMPLETED':
                return data
            if status in ('FAILED', 'TIMED_OUT', 'ERROR', 'CANCELLED'):
                detail = data.get('error') or data.get('output') or status
                raise RuntimeError(f'AI 擴圖工作失敗（{status}）：{str(detail)[:400]}')
            time.sleep(1.5)
        _cancel(job_id)
        raise TimeoutError(f'AI 擴圖等待逾時（最後狀態：{last}）')

    @app.route('/api/ai/outpaint', methods=['POST'])
    def ai_outpaint():
        if not app_module.RUNPOD_API_KEY or not requests_lib:
            return no_cache_json({'status':'error','code':'AI_NOT_CONFIGURED','msg':'AI 尚未連線'}, 503)
        if not outpaint_endpoint_id:
            return no_cache_json({
                'status':'error',
                'code':'OUTPAINT_NOT_CONFIGURED',
                'msg':'AI 擴圖專用端點尚未設定，請先完成 Runpod 擴圖端點連線'
            }, 503)

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
            return no_cache_json({'status':'error','msg':'AI 擴圖輸入需小於 8MB'}, 400)

        direction = str(request.form.get('direction') or 'all').lower()
        if direction not in ('all','left','right','top','up','bottom','down'):
            direction = 'all'
        try:
            ratio = float(request.form.get('expand_ratio') or 1.4)
        except Exception:
            ratio = 1.4
        ratio = max(1.10, min(1.65, ratio))
        prompt = str(request.form.get('prompt') or '').strip()[:500]

        job_id = ''
        try:
            payload = {
                'input': {
                    'task': 'outpaint',
                    'image_base64': base64.b64encode(raw).decode('ascii'),
                    'mime_type': mime,
                    'direction': direction,
                    'expand_ratio': ratio,
                    'prompt': prompt,
                    'steps': 18,
                    'guidance_scale': 6.5,
                }
            }
            job_id = _submit(payload)
            result = _wait(job_id, time.monotonic() + outpaint_timeout)
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
            return resp
        except TimeoutError as exc:
            return no_cache_json({'status':'error','code':'AI_TIMEOUT','job_id':job_id,'msg':'AI 擴圖等候太久，已自動停止，請再試一次','detail':str(exc)[:240]}, 504)
        except Exception as exc:
            _cancel(job_id)
            print('[AI] outpaint error:', repr(exc), flush=True)
            return no_cache_json({'status':'error','code':'AI_OUTPAINT_ERROR','msg':f'AI 擴圖失敗：{exc}'}, 502)

    print('[AI] dedicated outpaint endpoint support enabled:', bool(outpaint_endpoint_id), flush=True)
