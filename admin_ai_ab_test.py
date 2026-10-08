"""Admin-only, sequential AI provider comparison.

This module deliberately bypasses the customer provider selector and fallback
chain. It never stores uploaded images or exposes provider credentials/job IDs.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import threading
import time
import uuid
from io import BytesIO

from flask import request, session
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from PIL import Image


_INSTALLED = False
_RUN_LOCK = threading.Lock()
_STATS_LOCK = threading.RLock()
_STATS_KEY = 'ai_ab_test_stats'
_STATS_FILE = os.path.join('__pycache__', 'ai_ab_test_stats.json')
_MAX_INPUT_PIXELS = 32_000_000
_MAX_INPUT_BYTES = 6 * 1024 * 1024
_RATING_MAX_AGE = 24 * 60 * 60
_DEFAULT_STATS = {
    'version': 1,
    'koukoutu_wins': 0,
    'runpod_wins': 0,
    'ties': 0,
    'koukoutu_completed': 0,
    'koukoutu_total_ms': 0,
    'runpod_completed': 0,
    'runpod_total_ms': 0,
    'rated_operation_ids': [],
}


def _admin(app_module):
    if session.get('logged_in'):
        return None
    return app_module.no_cache_json({'status': 'error', 'msg': '未登入'}, 401)


def _safe_stats(raw):
    data = copy.deepcopy(_DEFAULT_STATS)
    if isinstance(raw, dict):
        for key in data:
            if key == 'rated_operation_ids':
                values = raw.get(key)
                if isinstance(values, list):
                    data[key] = [str(value)[:64] for value in values[-500:]]
            else:
                try:
                    data[key] = max(0, int(raw.get(key, data[key])))
                except (TypeError, ValueError):
                    pass
    return data


def _public_stats(data):
    data = _safe_stats(data)
    k_count = data['koukoutu_completed']
    r_count = data['runpod_completed']
    return {
        'koukoutu_wins': data['koukoutu_wins'],
        'runpod_wins': data['runpod_wins'],
        'ties': data['ties'],
        'rated': data['koukoutu_wins'] + data['runpod_wins'] + data['ties'],
        'koukoutu_completed': k_count,
        'runpod_completed': r_count,
        'koukoutu_average_ms': round(data['koukoutu_total_ms'] / k_count) if k_count else None,
        'runpod_average_ms': round(data['runpod_total_ms'] / r_count) if r_count else None,
    }


def _mutate_stats(app_module, mutate):
    os.makedirs(os.path.dirname(_STATS_FILE), exist_ok=True)
    with _STATS_LOCK:
        last_error = None
        for _ in range(4):
            current, version = app_module.cloud_get_json_versioned(
                _STATS_KEY, _STATS_FILE, _DEFAULT_STATS,
            )
            updated = _safe_stats(current)
            mutate(updated)
            try:
                app_module.cloud_compare_and_swap_json(
                    _STATS_KEY, _STATS_FILE, updated, version,
                )
                return _public_stats(updated)
            except app_module.StaleDataError as exc:
                last_error = exc
        raise last_error or RuntimeError('A/B 統計暫時無法更新')


def _load_stats(app_module):
    os.makedirs(os.path.dirname(_STATS_FILE), exist_ok=True)
    data, _ = app_module.cloud_get_json_versioned(
        _STATS_KEY, _STATS_FILE, _DEFAULT_STATS,
    )
    return _public_stats(data)


def _input(app_module):
    upload = request.files.get('image')
    if not upload or not upload.filename:
        raise ValueError('請選擇圖片')
    mime = (upload.mimetype or '').lower()
    raw = upload.read(_MAX_INPUT_BYTES + 1)
    if not raw or len(raw) > _MAX_INPUT_BYTES:
        raise ValueError('測試圖片需小於 6MB')
    detected = ''
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        detected = 'image/png'
    elif raw.startswith(b'\xff\xd8\xff'):
        detected = 'image/jpeg'
    elif len(raw) >= 12 and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        detected = 'image/webp'
    if not detected or (mime and mime not in ('image/png', 'image/jpeg', 'image/webp')):
        raise ValueError('只接受 PNG、JPG 或 WEBP 圖片')
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError()
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > _MAX_INPUT_PIXELS:
                raise ValueError()
            image.verify()
    except Exception as exc:
        raise ValueError('圖片內容或像素容量無效') from exc
    return raw, detected, width, height


def _png_metrics(png):
    with Image.open(BytesIO(png)) as image:
        image.load()
        rgba = image.convert('RGBA')
        low, high = rgba.getchannel('A').getextrema()
        return {
            'width': image.width,
            'height': image.height,
            'bytes': len(png),
            'valid_alpha': low < 247 and high > 8,
        }


def _koukoutu(app_module, raw, mime):
    import ai_remove_provider as provider
    if not (app_module.KOUKOUTU_API_KEY and app_module.requests):
        raise RuntimeError('Koukoutu 尚未設定')
    deadline = time.monotonic() + app_module.AI_REMOVE_BG_TIMEOUT
    task = provider.submit(app_module, raw, mime, 'general', deadline)
    png = provider.wait(app_module, task, 'general', deadline)
    provider.validate_png(png)
    return png, 'koukoutu', provider.MODELS['general']


def _runpod(app_module, raw, mime):
    import ai_remove_provider as provider
    if not app_module.AI_ENABLED:
        raise RuntimeError('RunPod 尚未設定')
    job_id = ''
    deadline = time.monotonic() + app_module.AI_REMOVE_BG_TIMEOUT
    try:
        job_id, _ = app_module._runpod_submit({'input': {
            'image_base64': base64.b64encode(raw).decode('ascii'),
            'mime_type': mime,
            'max_output_edge': 1800,
        }})
        result, _ = app_module._runpod_wait_for_result(job_id, deadline)
        output = result.get('output')
        if not isinstance(output, dict) or output.get('status') == 'error':
            raise RuntimeError('RunPod 沒有回傳有效結果')
        png = base64.b64decode(output.get('image_base64') or '', validate=True)
        provider.validate_png(png)
        return png, 'runpod', str(output.get('model') or app_module.AI_MODEL_NAME)[:120]
    except Exception:
        if job_id:
            app_module._runpod_cancel(job_id)
        raise


def _provider_result(app_module, name, call):
    started = time.monotonic()
    try:
        png, actual_provider, model = call()
        elapsed = max(0, round((time.monotonic() - started) * 1000))
        metrics = _png_metrics(png)
        return {
            'ok': True,
            'label': name,
            'provider': actual_provider,
            'model': model,
            'elapsed_ms': elapsed,
            'png_base64': base64.b64encode(png).decode('ascii'),
            **metrics,
        }
    except Exception as exc:
        elapsed = max(0, round((time.monotonic() - started) * 1000))
        print(f'[AI A/B] {name} failed:', repr(exc), flush=True)
        return {
            'ok': False,
            'label': name,
            'provider': 'koukoutu' if name == 'Koukoutu' else 'runpod',
            'model': 'background-removal' if name == 'Koukoutu' else app_module.AI_MODEL_NAME,
            'elapsed_ms': elapsed,
            'error': f'{name} 測試失敗，請查看伺服器診斷紀錄',
        }


def install(app_module):
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    app = app_module.app
    signer = URLSafeTimedSerializer(app.secret_key, salt='benfuwan-ai-ab-v1')

    @app.route('/admin/ai-ab-test', methods=['GET'])
    def admin_ai_ab_test_page():
        if not session.get('logged_in'):
            return app_module.redirect(app_module.url_for('login_page'))
        return app_module.send_file('admin_ai_ab_test.html')

    @app.route('/api/admin/ai-ab-test/summary', methods=['GET'])
    def admin_ai_ab_summary():
        denied = _admin(app_module)
        if denied:
            return denied
        try:
            return app_module.no_cache_json({'status': 'success', 'stats': _load_stats(app_module)})
        except Exception as exc:
            print('[AI A/B] stats read failed:', repr(exc), flush=True)
            return app_module.no_cache_json({'status': 'error', 'msg': 'A/B 統計暫時無法讀取'}, 503)

    @app.route('/api/admin/ai-ab-test/run', methods=['POST'])
    def admin_ai_ab_run():
        denied = _admin(app_module)
        if denied:
            return denied
        if not _RUN_LOCK.acquire(blocking=False):
            return app_module.no_cache_json({
                'status': 'error', 'code': 'AI_AB_BUSY', 'msg': '已有 A/B 測試正在執行，請稍候',
            }, 429)
        try:
            try:
                raw, mime, width, height = _input(app_module)
            except ValueError as exc:
                return app_module.no_cache_json({'status': 'error', 'msg': str(exc)}, 400)

            # Deliberately sequential. Koukoutu failures do not trigger RunPod as a
            # fallback; B starts only after A has finished or failed.
            result_a = _provider_result(
                app_module, 'Koukoutu', lambda: _koukoutu(app_module, raw, mime),
            )
            result_b = _provider_result(
                app_module, 'RunPod', lambda: _runpod(app_module, raw, mime),
            )
            operation_id = uuid.uuid4().hex

            def add_timings(stats):
                if result_a['ok']:
                    stats['koukoutu_completed'] += 1
                    stats['koukoutu_total_ms'] += result_a['elapsed_ms']
                if result_b['ok']:
                    stats['runpod_completed'] += 1
                    stats['runpod_total_ms'] += result_b['elapsed_ms']

            stats_warning = ''
            try:
                stats = _mutate_stats(app_module, add_timings)
            except Exception as exc:
                print('[AI A/B] timing stats update failed:', repr(exc), flush=True)
                stats = None
                stats_warning = '測試完成，但累積統計暫時無法更新'

            token = ''
            if result_a['ok'] and result_b['ok']:
                token = signer.dumps({'operation_id': operation_id, 'both_ok': True})
            return app_module.no_cache_json({
                'status': 'success',
                'original': {'width': width, 'height': height, 'bytes': len(raw)},
                'koukoutu': result_a,
                'runpod': result_b,
                'rating_token': token,
                'stats': stats,
                'stats_warning': stats_warning,
            })
        finally:
            _RUN_LOCK.release()

    @app.route('/api/admin/ai-ab-test/rate', methods=['POST'])
    def admin_ai_ab_rate():
        denied = _admin(app_module)
        if denied:
            return denied
        payload = request.get_json(silent=True) or {}
        choice = str(payload.get('choice') or '')
        if choice not in ('koukoutu', 'runpod', 'tie'):
            return app_module.no_cache_json({'status': 'error', 'msg': '評分選項無效'}, 400)
        try:
            signed = signer.loads(str(payload.get('rating_token') or ''), max_age=_RATING_MAX_AGE)
            operation_id = str(signed.get('operation_id') or '')
            if not signed.get('both_ok') or not operation_id:
                raise BadSignature('invalid comparison')
        except SignatureExpired:
            return app_module.no_cache_json({'status': 'error', 'msg': '這次比較已過期，請重新測試'}, 400)
        except BadSignature:
            return app_module.no_cache_json({'status': 'error', 'msg': '比較評分憑證無效'}, 400)

        duplicate = False

        def add_rating(stats):
            nonlocal duplicate
            rated = stats['rated_operation_ids']
            if operation_id in rated:
                duplicate = True
                return
            stats[choice + '_wins' if choice != 'tie' else 'ties'] += 1
            rated.append(operation_id)
            stats['rated_operation_ids'] = rated[-500:]

        try:
            stats = _mutate_stats(app_module, add_rating)
        except Exception as exc:
            print('[AI A/B] rating update failed:', repr(exc), flush=True)
            return app_module.no_cache_json({'status': 'error', 'msg': '評分暫時無法儲存'}, 503)
        if duplicate:
            return app_module.no_cache_json({'status': 'error', 'code': 'ALREADY_RATED', 'msg': '這次比較已評分'}, 409)
        return app_module.no_cache_json({'status': 'success', 'stats': stats})
