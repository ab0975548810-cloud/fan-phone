"""Opt-in cloud adapters; one persistent reservation covers the whole operation.

Public API contracts: doc.koukoutu.com/444674398e0, /444687820e0,
/444686434e0 and /444687824e0. Never forward credentials to result URLs.
"""
import base64
import ipaddress
import socket
import time
from io import BytesIO
from urllib.parse import urlsplit, urljoin

from flask import Response
from PIL import Image

from ai_quota import AiQuotaRejected, AiQuotaUnavailable, QUOTA_UNAVAILABLE_MESSAGE

MODELS = {'general': 'background-removal', 'stamp': 'stamp-background-removal'}
MAX_OUTPUT = 14 * 1024 * 1024


def _timeout(app, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('AI 處理逾時')
    return min(app.AI_HTTP_TIMEOUT, remaining)


def _json(response):
    # Do not expose vendor response text: it can contain credentials or URLs.
    try:
        if not 200 <= response.status_code < 300:
            raise ValueError()
        data = response.json()
        if not isinstance(data, dict) or data.get('code') != 200 or not isinstance(data.get('data'), dict):
            raise ValueError()
        return data['data']
    except (ValueError, TypeError) as exc:
        raise RuntimeError('雲端 AI 回應格式或狀態錯誤') from exc


def submit(app, raw, mime, mode, deadline):
    response = app.requests.post(
        'https://async.koukoutu.com/v1/create',
        headers={'X-API-Key': app.KOUKOUTU_API_KEY},
        data={'model_key': MODELS[mode], 'output_format': 'png',
              'crop': '0', 'border': '0', 'stamp_crop': '0'},
        files={'image_file': ('input.' + {'image/png':'png', 'image/jpeg':'jpg', 'image/webp':'webp'}[mime], raw, mime)},
        timeout=_timeout(app, deadline), allow_redirects=False,
    )
    task = _json(response).get('task_id')
    if isinstance(task, bool) or not isinstance(task, (str, int)) or not str(task).strip() or len(str(task)) > 120:
        raise RuntimeError('雲端 AI 沒有回傳任務編號')
    return str(task)


def _public_url(url):
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and parsed.port in (None, 443)
    except ValueError as exc:
        raise RuntimeError('雲端 AI 結果網址無效') from exc
    if not valid:
        raise RuntimeError('雲端 AI 結果網址無效')
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise RuntimeError('雲端 AI 結果網址無效')


def download(app, url, deadline):
    # Public HTTPS only, validate every redirect, bound streamed bytes and time.
    for _ in range(4):
        _public_url(url)
        with app.requests.get(url, timeout=_timeout(app, deadline), stream=True, allow_redirects=False) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                url = urljoin(url, response.headers.get('Location', ''))
                continue
            if response.status_code != 200:
                raise RuntimeError('雲端 AI 結果下載失敗')
            body = bytearray()
            for chunk in response.iter_content(64 * 1024):
                _timeout(app, deadline)
                body.extend(chunk)
                if len(body) > MAX_OUTPUT:
                    raise RuntimeError('雲端 AI 回傳圖片過大')
            return bytes(body)
    raise RuntimeError('雲端 AI 結果重新導向過多')


def wait(app, task, mode, deadline):
    while True:
        response = app.requests.post(
            'https://async.koukoutu.com/v1/query',
            headers={'X-API-Key': app.KOUKOUTU_API_KEY},
            data={'task_id': task, 'response': 'url'},
            timeout=_timeout(app, deadline), allow_redirects=False,
        )
        data = _json(response)
        state = data.get('state')
        if type(state) is not int:
            raise RuntimeError('雲端 AI 任務狀態無效')
        if state == 1:
            url = data.get('result_file')
            if not isinstance(url, str) or not url:
                raise RuntimeError('雲端 AI 沒有回傳透明圖片')
            return download(app, url, deadline)
        if state != 0:
            raise RuntimeError('雲端 AI 任務失敗')
        time.sleep(min(app.AI_POLL_INTERVAL, _timeout(app, deadline)))


def validate_png(png):
    if len(png) > MAX_OUTPUT or not png.startswith(b'\x89PNG\r\n\x1a\n'):
        raise RuntimeError('雲端 AI 回傳的不是有效 PNG')
    try:
        with Image.open(BytesIO(png)) as image:
            if image.format != 'PNG' or image.width * image.height > 32_000_000:
                raise ValueError()
            image.load()
            alpha = image.convert('RGBA').getchannel('A')
            low, high = alpha.getextrema()
            if low >= 247 or high <= 8:
                raise ValueError()
    except Exception as exc:
        raise RuntimeError('雲端 AI 回傳沒有有效透明主體，原圖已保留') from exc


def handle(app, raw, mime, mode):
    import security_perf
    try:
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > 32_000_000 or source.format not in ('PNG', 'JPEG', 'WEBP'):
                raise ValueError()
            source.verify()
    except Exception:
        return app.no_cache_json({'status': 'error', 'code': 'AI_BAD_INPUT', 'msg': 'AI 圖片格式或像素容量無效'}, 400)
    fail = lambda code, msg, status: app.no_cache_json({'status': 'error', 'code': code, 'msg': msg}, status)
    try:
        reservation = app.AI_QUOTA.reserve(security_perf._cid(), security_perf._ip())
    except AiQuotaRejected as exc:
        return fail(exc.code, str(exc), 429)
    except AiQuotaUnavailable:
        return fail('AI_QUOTA_UNAVAILABLE', QUOTA_UNAVAILABLE_MESSAGE, 503)

    counted = False
    runpod_job = ''
    deadline = time.monotonic() + app.AI_REMOVE_BG_TIMEOUT

    def mark(job):
        nonlocal counted
        if not counted:
            app.AI_QUOTA.mark_submitted(reservation, job)
            counted = True

    try:
        provider = 'koukoutu'
        model = MODELS[mode]
        try:
            # Leave time for a single bounded fallback within the same deadline.
            first_deadline = min(deadline, time.monotonic() + app.AI_REMOVE_BG_TIMEOUT * .5) if app.AI_REMOVE_PROVIDER == 'auto' else deadline
            if not app.KOUKOUTU_API_KEY:
                raise RuntimeError('雲端 AI 尚未設定')
            task = submit(app, raw, mime, mode, first_deadline)
            # Existing text RPC/column stores the first accepted provider job.
            mark('koukoutu:' + task)
            png = wait(app, task, mode, first_deadline)
            validate_png(png)
        except AiQuotaUnavailable:
            # Never submit a fallback after a ledger failure.
            raise
        except (RuntimeError, OSError, app.requests.RequestException):
            if app.AI_REMOVE_PROVIDER != 'auto' or not app.AI_ENABLED:
                raise
            _timeout(app, deadline)
            provider, model = 'runpod', app.AI_MODEL_NAME
            runpod_job, _ = app._runpod_submit({'input': {
                'image_base64': base64.b64encode(raw).decode('ascii'),
                'mime_type': mime, 'max_output_edge': 1800,
            }})
            mark(runpod_job)
            result, _ = app._runpod_wait_for_result(runpod_job, deadline)
            output = result.get('output')
            if not isinstance(output, dict) or output.get('status') == 'error':
                raise RuntimeError('AI 沒有回傳有效結果')
            try:
                png = base64.b64decode(output.get('image_base64', ''), validate=True)
            except Exception as exc:
                raise RuntimeError('AI 圖片資料無法解析') from exc
            validate_png(png)
        app.AI_QUOTA.finish(reservation, 'COMPLETED')
        response = Response(png, mimetype='image/png')
        response.headers.update({'Cache-Control': 'no-store', 'X-AI-Provider': provider, 'X-AI-Model': model})
        return response
    except AiQuotaUnavailable:
        app._runpod_cancel(runpod_job) if runpod_job else None
        return fail('AI_QUOTA_UNAVAILABLE', QUOTA_UNAVAILABLE_MESSAGE, 503)
    except Exception as exc:
        if runpod_job:
            app._runpod_cancel(runpod_job)
        try:
            if counted:
                app.AI_QUOTA.finish(reservation, 'FAILED')
            else:
                app.AI_QUOTA.release(reservation)
        except AiQuotaUnavailable:
            return fail('AI_QUOTA_UNAVAILABLE', QUOTA_UNAVAILABLE_MESSAGE, 503)
        timeout = isinstance(exc, (TimeoutError, app.requests.Timeout))
        return fail('AI_TIMEOUT' if timeout else 'AI_PROVIDER_ERROR',
                    'AI 處理逾時，原圖已保留' if timeout else 'AI 摳圖服務暫時無法使用，原圖已保留', 504 if timeout else 502)
