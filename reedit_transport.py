"""Private test handoff protocol. Transport credentials are independent of login cookies."""
import hashlib
import hmac
import io
import json
import os
import re
import uuid
import time
import zipfile
from urllib.parse import urlsplit

import requests
from flask import abort, jsonify, request, session
from itsdangerous import BadData, URLSafeTimedSerializer

from reedit_access import allowed, session_identity
from reedit_snapshot import export_artwork

MAX_BUNDLE = 96 * 1024 * 1024
MAX_MANIFEST = 2 * 1024 * 1024


def origin(setting):
    value = os.environ.get(setting, '')
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or value != 'https://' + parsed.hostname:
        raise ValueError('測試服務網址尚未完成設定')
    return value


def service_key():
    value = os.environ.get('ADMIN_REEDIT_TRANSFER_KEY', '')
    if len(value) < 40:
        raise ValueError('測試服務尚未配對')
    return value


def pack(manifest, files):
    payload = json.dumps(manifest, ensure_ascii=False, allow_nan=False).encode()
    if len(payload) > MAX_MANIFEST or len(files) > 303 or sum(map(len, files.values())) + len(payload) > MAX_BUNDLE - 65536:
        raise ValueError('測試快照容量超過限制')
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_STORED) as archive:
        archive.writestr('manifest.json', payload)
        for digest, data in files.items():
            archive.writestr(digest, data)
    return result.getvalue()


def unpack(raw):
    if len(raw) > MAX_BUNDLE:
        raise ValueError('快照容量超過限制')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        items = archive.infolist()
        if len(items) > 304 or len(set(archive.namelist())) != len(items) or sum(i.file_size for i in items) > MAX_BUNDLE:
            raise ValueError('快照內容無效')
        files = {}
        for item in items:
            if item.compress_type != zipfile.ZIP_STORED:
                raise ValueError('快照格式無效')
            if item.filename == 'manifest.json' and item.file_size <= MAX_MANIFEST:
                manifest = json.loads(archive.read(item))
            elif re.fullmatch('[0-9a-f]{64}', item.filename):
                data = archive.read(item)
                if hashlib.sha256(data).hexdigest() != item.filename:
                    raise ValueError('圖檔驗證失敗')
                files[item.filename] = data
            else:
                raise ValueError('快照檔名無效')
        if 'manifest.json' not in archive.namelist() or any(manifest[k]['sha256'] not in files for k in ('print', 'preview')):
            raise ValueError('快照不完整')
    return manifest, files


def signed_headers(raw, claim):
    signature = hmac.digest(service_key().encode(), claim.encode() + b'\0' + raw, 'sha256').hex()
    return {'X-Test-Claim': claim, 'X-Test-Signature': signature, 'Content-Type': 'application/octet-stream'}


def install(module, service):
    app = module.app
    signer = URLSafeTimedSerializer(app.secret_key, salt='private-reedit-online-v1')

    def configured():
        qa = origin('ADMIN_REEDIT_PRIVATE_ORIGIN')
        service_key()
        epoch = os.environ.get('ADMIN_REEDIT_GENERATION', '')
        if len(epoch) < 16 or qa == service.config.origin:
            raise ValueError('測試環境尚未獨立設定')
        return qa, epoch

    @app.get('/api/admin/reedit-test/access')
    def reedit_capability():
        try:
            active = bool(session_identity(service) and configured())
        except Exception:
            active = False
        return jsonify(enabled=active), 200, {'Cache-Control': 'no-store'}

    @app.get('/admin/reedit-test/confirm')
    def confirm_page():
        return ('<!doctype html><meta charset=utf-8><p role=status>正在確認測試編輯權限…</p>'
                '<script src="/static/private-reedit-confirm.js"></script>'),200,{'Cache-Control':'no-store'}

    @app.post('/api/admin/reedit-test/confirm')
    def confirm_browser():
        if request.headers.get('Origin')!=service.config.origin or request.headers.get('X-Reedit-Test')!='1':
            abort(403)
        qa,epoch=configured()
        data=request.get_json()
        pending=session.get('private_reedit_pending') or {}
        identity=session_identity(service)
        if (not identity or pending.get('subject')!=identity or pending.get('snapshot')!=data.get('snapshot')
                or pending.get('expires',0)<=time.time() or not re.fullmatch('[0-9a-f]{64}',data.get('challenge',''))):
            abort(403)
        session.pop('private_reedit_pending',None)
        proof=signer.dumps(dict(**pending,challenge=data['challenge'],generation=epoch))
        return jsonify(location=qa+'/private/return#'+proof),200,{'Cache-Control':'no-store'}

    @app.post('/internal/reedit-test/authorize')
    def reedit_authorize():
        try:
            claim = signer.loads(request.headers.get('X-Test-Claim', ''), max_age=900)
            _, epoch = configured()
            ok = (claim['generation'] == epoch and claim['until'] > time.time()
                  and allowed(service, claim['subject']))
            if request.headers.get('X-Browser-Proof'):
                proof=signer.loads(request.headers['X-Browser-Proof'],max_age=45)
                ok=ok and (proof['expires']>time.time() and proof['subject']==claim['subject']
                           and proof['generation']==epoch and proof['snapshot']==claim['snapshot']
                           and proof['challenge']==request.headers.get('X-Browser-Challenge'))
        except Exception:
            ok = False
        return jsonify(authorized=bool(ok)), 200 if ok else 403, {'Cache-Control': 'no-store'}

    @app.post('/api/admin/reedit-test/<order_id>/start')
    def reedit_start(order_id):
        if request.headers.get('Origin') != service.config.origin or request.headers.get('X-Reedit-Test') != '1':
            abort(403)
        try:
            subject = session_identity(service)
            if not subject:
                abort(403)
            
            qa, epoch = configured()
            snapshot = uuid.uuid4().hex
            claim = signer.dumps(dict(subject=subject, snapshot=snapshot, generation=epoch,
                                      until=session['reedit_verified_at']+900))
            from security_perf import _limited
            if _limited('private-reedit-export',subject,4,60)[0]:
                return jsonify(msg='請稍後再開啟測試設計'),429
            manifest, files = export_artwork(module, order_id)
            manifest['snapshot'] = snapshot
            raw = pack(manifest, files)
            if not session_identity(service):
                abort(403)
            result = requests.post(qa + '/private/import', data=raw, headers=signed_headers(raw, claim),
                                   timeout=(3, 25), allow_redirects=False)
            if result.status_code != 201:
                raise ValueError('隔離站未接受交接，請重新開啟')
            code = result.json()['code']
            if not re.fullmatch('[a-zA-Z0-9_-]{43}', code):
                raise ValueError('交接回應無效')
            session['private_reedit_pending']=dict(snapshot=snapshot,subject=subject,expires=int(time.time())+45)
            return jsonify(location=qa + '/private/enter#' + snapshot + '.' + code), 200, {'Cache-Control':'no-store'}
        except (requests.RequestException, ValueError, KeyError, OSError):
            return jsonify(msg='測試交接未完成，請確認原圖與隔離站狀態後再試'), 422
