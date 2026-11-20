"""Time-limited Railway smoke site. Only internally generated art can enter."""
import ctypes
import errno
import hashlib
import hmac
import io
import os
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from threading import BoundedSemaphore

from flask import Flask, abort, jsonify, redirect, request, session
from itsdangerous import URLSafeTimedSerializer, BadData
from PIL import Image, ImageDraw
from reedit_private_site import create_private_site, cleanup
from reedit_transport import pack, signed_headers

VOLUME = Path('/private-reedit')
SID = hashlib.sha256(b'117 synthetic 720dpi v1').hexdigest()[:32]
PUBLIC = 'https://private-reedit-117-iphone-qa.up.railway.app'


def check_environment():
    required = {'RAILWAY_PROJECT_ID':'62673372-609e-4fc2-b86f-c0e75b46fdaa',
                'RAILWAY_ENVIRONMENT_ID':'49f531ce-e0ae-46e9-b37f-55e08218eb42',
                'RAILWAY_SERVICE_ID':'234aa5c3-d734-42b3-be07-170f8fc340f3'}
    if any(os.getenv(k)!=v for k,v in required.items()) or not os.path.ismount(VOLUME):
        raise RuntimeError('Dedicated QA service and mount required')
    if any(os.getenv(k) for k in os.environ if k.startswith(('SUPABASE','YUN_PRINT','STRIPE','RUNPOD')) or
           k in ('ADMIN_PASSWORD','DATABASE_URL','ADMIN_REEDIT_TEST_ENABLED','ADMIN_REEDIT_TEST_CREDENTIAL_SHA256')):
        raise RuntimeError('Unexpected integration configured')
    if not 0 < float(os.environ['QA_END_EPOCH'])-time.time() <= 86400:
        raise RuntimeError('QA budget window expired')
    keys=[os.environ[k] for k in ('PRIVATE_REEDIT_SESSION_SECRET','ADMIN_REEDIT_TRANSFER_KEY','QA_LOGIN_SHA256')]
    if min(map(len,keys))<40 or len(set(keys))!=3:
        raise RuntimeError('Dedicated keys required')


def deny_outbound():
    # Gunicorn already owns the listening socket. Workers can accept inbound
    # connections but cannot initiate connections, even from a child process.
    lib=ctypes.CDLL('libseccomp.so.2')
    lib.seccomp_init.restype=ctypes.c_void_p
    ctx=ctypes.c_void_p(lib.seccomp_init(0x7fff0000))
    if not ctx:raise RuntimeError('seccomp unavailable')
    try:
        for name in (b'connect',b'io_uring_setup'):
            nr=lib.seccomp_syscall_resolve_name(name)
            if nr<0 or lib.seccomp_rule_add(ctx,0x50000|errno.EPERM,nr,0):
                raise RuntimeError('Cannot apply outbound policy')
        class Arg(ctypes.Structure):
            _fields_=[('arg',ctypes.c_uint),('op',ctypes.c_int),('a',ctypes.c_uint64),('b',ctypes.c_uint64)]
        for family in (socket.AF_INET,socket.AF_INET6,socket.AF_PACKET if hasattr(socket,'AF_PACKET') else 17):
            rule=Arg(0,4,int(family),0)
            if lib.seccomp_rule_add_array(ctx,0x50000|errno.EPERM,lib.seccomp_syscall_resolve_name(b'socket'),1,ctypes.byref(rule)):
                raise RuntimeError('Cannot disable outbound sockets')
        if lib.seccomp_load(ctx):raise RuntimeError('Outbound policy unavailable')
    finally:
        lib.seccomp_release(ctx)
    for family in (socket.AF_INET,socket.AF_INET6):
        try:
            with socket.socket(family):pass
        except PermissionError:continue
        raise RuntimeError('Outbound socket was available')


def fixture():
    size=(2030,4241)
    image=Image.new('RGBA',size,'#efcbb2')
    draw=ImageDraw.Draw(image)
    draw.ellipse((380,350,1280,1250),fill='#f9f3df')
    draw.ellipse((645,620,1015,990),fill='#e89422')
    draw.polygon([(220,1900),(970,2150),(1660,1860),(1660,2480),(970,2200),(220,2510)],fill='#d45479')
    def png(im):
        data=io.BytesIO();im.save(data,'PNG',dpi=(720,720));return data.getvalue()
    files={}
    def entry(im):
        raw=png(im);sha=hashlib.sha256(raw).hexdigest();files[sha]=raw
        return dict(sha256=sha,size=list(im.size),dpi=[720,720])
    art=entry(image)
    image.thumbnail((255,530));preview=entry(image)
    mask=Image.new('RGBA',(205,426));ImageDraw.Draw(mask).rectangle((1,1,203,424),fill='white')
    alignment=entry(mask)
    geo=[size[0]*25.4/720,size[1]*25.4/720,0,0,0]
    alignment['geometry']=geo
    return pack(dict(snapshot=SID,operator='synthetic-owner',print=art,preview=preview,alignment=alignment,
                     profile=dict(zip(('width_mm','height_mm','left_mm','top_mm','angle'),geo)),review=[]),files)


def application():
    check_environment()
    deny_outbound()
    os.environ.update(ADMIN_REEDIT_SOURCE_ORIGIN=PUBLIC,ADMIN_REEDIT_PRIVATE_ORIGIN=PUBLIC)
    secret=os.environ['PRIVATE_REEDIT_SESSION_SECRET']
    signer=URLSafeTimedSerializer(secret,salt='synthetic-pr117-source')
    def authorize(claim,proof=None,challenge=None):
        try:
            issued=signer.loads(claim,max_age=900)
            if issued.get('fixture')!=SID or time.time()>=float(os.environ['QA_END_EPOCH']):return False
            return proof is None or signer.loads(proof,max_age=45)==[claim,challenge]
        except BadData:return False
    editor=create_private_site(VOLUME,secret,authorize)
    editor.view_functions['catalog_original']=editor.view_functions['catalog']
    def offline_catalog(kind):
        if kind=='assets':
            return jsonify(data={'categories':['合成驗收'],'stickers':[{'id':'qa-bow','category':'合成驗收','url':'/private/sticker/qa-bow'}]})
        return editor.view_functions['catalog_original'](kind)
    def offline_sticker(name):
        if name!='qa-bow':abort(404)
        image=Image.new('RGBA',(160,90))
        ImageDraw.Draw(image).polygon([(5,5),(80,40),(155,5),(155,85),(80,50),(5,85)],fill='#c94672')
        buffer=io.BytesIO()
        image.save(buffer,'PNG')
        return editor.response_class(buffer.getvalue(),mimetype='image/png')
    editor.view_functions.update(catalog=offline_catalog,sticker_image=offline_sticker)
    cleanup(VOLUME)
    source=Flask('synthetic-qa',static_folder=None)
    source.secret_key=secrets.token_bytes(48)
    source.config.update(SESSION_COOKIE_NAME='__Host-demo-source',SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SECURE=True,
                         SESSION_COOKIE_SAMESITE='Strict',MAX_CONTENT_LENGTH=2048)
    slot=BoundedSemaphore(1)

    @source.get('/qa/health')
    def health():
        return jsonify(mode='synthetic-only',outbound='blocked',expires=int(os.environ['QA_END_EPOCH']))

    @source.get('/')
    def login():
        return """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
        <title>本福丸私有驗收</title><h1>合成訂單測試</h1><form method=post action=/qa/start>
        <label>專用測試碼 <input name=key type=password required></label><button>開啟測試訂單</button></form>"""

    @source.post('/qa/start')
    def start():
        if request.headers.get('Origin')!=PUBLIC or not hmac.compare_digest(
                hashlib.sha256(request.form.get('key','').encode()).hexdigest(),os.environ['QA_LOGIN_SHA256']):
            abort(403)
        if not slot.acquire(False):abort(429)
        try:
            claim=signer.dumps({'fixture':SID,'nonce':secrets.token_hex(16)})
            raw=fixture()
            response=editor.test_client().post('/private/import',data=raw,headers=signed_headers(raw,claim))
            if response.status_code!=201:abort(response.status_code)
            session.clear();session.update(claim=claim,pending_until=time.time()+45)
            return redirect('/private/enter#'+SID+'.'+response.json['code'],303)
        finally:slot.release()

    @source.get('/admin/reedit-test/confirm')
    def confirm_page():
        return '<meta charset=utf-8><p role=status>正確認測試身分…</p><script src="/static/private-reedit-confirm.js"></script>'

    @source.post('/api/admin/reedit-test/confirm')
    def confirm():
        import re
        if request.headers.get('Origin')!=PUBLIC or request.headers.get('X-Reedit-Test')!='1':abort(403)
        data=request.get_json()
        if (data.get('snapshot')!=SID or not re.fullmatch('[0-9a-f]{64}',data.get('challenge',''))
                or session.pop('pending_until',0)<=time.time()):abort(403)
        return jsonify(location='/private/return#'+signer.dumps([session['claim'],data['challenge']]))

    @source.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Frame-Options':'DENY'})
        return response

    routes={r.rule for r in source.url_map.iter_rules()}
    budget=VOLUME/'traffic.db'
    with closing(sqlite3.connect(budget)) as db,db:
        db.execute('create table if not exists usage(bytes integer not null)')
        db.execute('insert into usage select 0 where not exists(select 1 from usage)')
    def dispatch(env,start_response):
        path=env.get('PATH_INFO')
        if path=='/private/import' or time.time()>=float(os.environ['QA_END_EPOCH']):
            start_response('403 Forbidden',[('Content-Length','0')]);return []
        def bounded(status,headers,exc_info=None):
            # Flask responses here have known lengths. Reserve bytes before sending
            # and keep the cumulative allowance through Railway restarts.
            length=dict(headers).get('Content-Length')
            if length is None and env['REQUEST_METHOD']!='HEAD':
                raise ValueError('Unbounded QA response')
            charge=int(length or 0)+2048
            with closing(sqlite3.connect(budget)) as db,db:
                if db.execute('update usage set bytes=bytes+? where bytes+?<=?',(charge,charge,2*1024**3)).rowcount!=1:
                    os.kill(os.getppid(),signal.SIGTERM)
                    raise RuntimeError('QA transfer budget exhausted')
            return start_response(status,headers,exc_info)
        return (source if path in routes else editor)(env,bounded)
    return dispatch


if __name__=='__main__':
    check_environment()
    worker=subprocess.Popen(['gunicorn','-c','private_reedit_gunicorn.py','synthetic_reedit_qa:application()'])
    signal.signal(signal.SIGTERM,lambda *_:worker.terminate())
    try:
        sys.exit(worker.wait(timeout=max(0,float(os.environ['QA_END_EPOCH'])-time.time())))
    except subprocess.TimeoutExpired:
        worker.terminate()
        worker.wait(timeout=30)
        cleanup(VOLUME,now=time.time()+8*86400,revoke=True)
