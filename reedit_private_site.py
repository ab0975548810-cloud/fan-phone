"""Dedicated private QA WSGI application. Intentionally never imports the shop app."""
import hashlib
import io
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import tempfile
import time
from contextlib import closing, contextmanager
from types import SimpleNamespace
from zipfile import BadZipFile

import requests
from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory, session


from reedit_private_handoffs import PrivateHandoffs
from reedit_transport import MAX_BUNDLE, origin, signed_headers, unpack

ROOT = Path(__file__).resolve().parent
TTL = 7 * 86400


def online(claim, proof=None, challenge=None):
    try:
        headers={'X-Test-Claim':claim}
        if proof:
            headers.update({'X-Browser-Proof':proof,'X-Browser-Challenge':challenge})
        response = requests.post(origin('ADMIN_REEDIT_SOURCE_ORIGIN') + '/internal/reedit-test/authorize',
                                 headers=headers, allow_redirects=False, timeout=(2,3))
        return response.status_code == 200 and response.json().get('authorized') is True
    except (ValueError, requests.RequestException):
        return False


def cleanup(volume, now=None, revoke=False):
    now = int(time.time() if now is None else now)
    with closing(sqlite3.connect(volume/'access.db')) as db, db:
        db.execute('begin immediate')
        if revoke:
            db.execute('insert or replace into controls values (1,1)')
            db.execute('delete from handoffs')
            db.execute('insert into audit values (?,?,?)',('','disabled',now))
        for (sid,) in db.execute('select id from snapshots where expires<=?',(now,)).fetchall():
            if not re.fullmatch('[0-9a-f]{32}',sid):
                raise ValueError('無效的隔離工作區')
            folder = volume/sid
            if folder.exists():
                shutil.rmtree(folder)
            db.execute('delete from handoffs where snapshot=?',(sid,))
            db.execute('delete from snapshots where id=?',(sid,))
            db.execute('insert into audit values (?,?,?)',(sid,'expired',now))
        db.execute('delete from handoffs where created<?',(now-900,))
        # Recover directories stranded by a worker crash between rename and commit.
        for entry in volume.iterdir():
            if (entry.is_dir() and not entry.is_symlink() and entry.stat().st_mtime <= now-300
                    and (re.fullmatch('tmp[a-zA-Z0-9_-]+',entry.name) or
                         (re.fullmatch('[a-f0-9]{32}',entry.name) and
                          not db.execute('select 1 from snapshots where id=?',(entry.name,)).fetchone()))):
                shutil.rmtree(entry)


def replace_paths(value, mapping):
    if isinstance(value, dict):
        return {k:(mapping[v] if k in ('src','maskPath','previewPath') else replace_paths(v,mapping)) for k,v in value.items()}
    if isinstance(value, list):
        return [replace_paths(v,mapping) for v in value]
    return value


def create_private_site(volume, secret, authorize=online, clock=time.time):
    volume = Path(volume).resolve()
    if not volume.is_dir() or len(secret)<32:
        raise ValueError('需要獨立的測試儲存區與工作階段金鑰')
    dbpath = volume/'access.db'
    app = Flask(__name__,static_folder=str(ROOT/'static'))
    app.secret_key = secret
    app.config.update(SESSION_COOKIE_NAME='__Host-private-reedit',SESSION_COOKIE_SECURE=True,
                      SESSION_COOKIE_SAMESITE='Strict',MAX_CONTENT_LENGTH=MAX_BUNDLE)
    with closing(sqlite3.connect(dbpath)) as db:
        db.executescript('''
            create table if not exists snapshots (id text primary key, claim text not null, expires integer not null);
            create table if not exists audit (snapshot text, event text, at integer);
            create table if not exists controls (id integer primary key, disabled integer not null);
            create table if not exists operations(snapshot text, operator text, operation text, at integer);
        ''')
    store = PrivateHandoffs(dbpath,authorize,clock)

    def access():
        sid = session.get('snapshot','')
        with closing(sqlite3.connect(dbpath)) as db:
            row = db.execute('select claim from snapshots where id=? and expires>? and not exists(select 1 from controls where disabled=1)',(sid,clock())).fetchone()
        if not row:
            abort(403)
        try:
            if store.access(session.get('grant',''), sid)!=row[0]:
                abort(403)
        except PermissionError:
            abort(403)
        return sid

    def audit(sid,event):
        with closing(sqlite3.connect(dbpath)) as db, db:
            db.execute('insert into audit values (?,?,?)',(sid,event,int(clock())))

    @app.post('/private/import')
    def receive():
        claim = request.headers.get('X-Test-Claim','')
        signature=request.headers.get('X-Test-Signature','')
        if not claim or len(claim)>2000 or not re.fullmatch('[a-f0-9]{64}',signature) or not authorize(claim):
            abort(403)
        raw=request.get_data()
        if not hmac.compare_digest(signature,signed_headers(raw,claim)['X-Test-Signature']):
            abort(403)
        try:
            manifest,files = unpack(raw)
            sid = manifest['snapshot']
            if not re.fullmatch('[0-9a-f]{32}',sid):
                raise ValueError()
            with tempfile.TemporaryDirectory(dir=volume) as stage:
                source = Path(stage)/sid
                source.mkdir()
                (source/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
                for digest,data in files.items():
                    (source/digest).write_bytes(data)
                with closing(sqlite3.connect(dbpath)) as db, db:
                    db.execute('begin immediate')
                    if db.execute('select 1 from controls where disabled=1').fetchone():
                        abort(403)
                    existing=db.execute('select expires from snapshots where id=?',(sid,)).fetchone()
                    if existing:
                        if existing[0]<=clock() or not (volume/sid/'manifest.json').is_file():
                            raise ValueError('工作區已到期')
                        db.execute('update snapshots set claim=? where id=?',(claim,sid))
                    else:
                        db.execute('insert into snapshots values (?,?,?)',(sid,claim,int(clock())+TTL))
                    code=store.record_issue(db,claim,sid)
                    if not authorize(claim):
                        abort(403)
                    db.execute('insert into audit values (?,?,?)',(sid,'resumed' if existing else 'imported',int(clock())))
                    if not existing:
                        source.rename(volume/sid)
            return jsonify(code=code),201
        except (ValueError,KeyError,BadZipFile,sqlite3.IntegrityError):
            return jsonify(msg='無法接受測試快照'),422

    @app.get('/private/return')
    @app.get('/private/enter')
    def enter():
        return """<!doctype html><meta charset=utf-8><title>重新編輯測試</title>
        <p role=status>正在進入私有測試編輯器…</p><script src="/static/private-reedit-enter.js"></script>"""

    @app.post('/private/bind')
    def bind_browser():
        if request.headers.get('Origin') != origin('ADMIN_REEDIT_PRIVATE_ORIGIN') or not request.is_json:
            abort(403)
        data=request.get_json()
        sid,code=data.get('snapshot',''),data.get('code','')
        if not re.fullmatch('[0-9a-f]{32}',sid) or not re.fullmatch('[A-Za-z0-9_-]{43}',code):
            abort(403)
        session.clear()
        challenge=secrets.token_hex(32)
        session.update(pending_snapshot=sid,pending_code=code,pending_challenge=challenge)
        return jsonify(location=origin('ADMIN_REEDIT_SOURCE_ORIGIN')+'/admin/reedit-test/confirm#'+sid+'.'+challenge)

    @app.post('/private/redeem')
    def redeem():
        if request.headers.get('Origin') != origin('ADMIN_REEDIT_PRIVATE_ORIGIN') or not request.is_json:
            abort(403)
        body = request.get_json()
        sid = session.get('pending_snapshot','')
        with closing(sqlite3.connect(dbpath)) as db:
            row = db.execute('select claim from snapshots where id=? and expires>?',(sid,clock())).fetchone()
        if not row:
            abort(403)
        try:
            proof=body.get('proof')
            if not isinstance(proof,str) or not proof or not authorize(row[0],proof,session.get('pending_challenge','')):
                abort(403)
            token = store.redeem(session.get('pending_code',''),row[0])
        except PermissionError:
            abort(403)
        session.clear()
        # Mint the shared editor's actor before the first parallel page, image
        # and heartbeat requests. Later read responses must never replace it.
        session.update(grant=token,snapshot=sid,logged_in=True,_bf_client_id=secrets.token_urlsafe(24))
        audit(sid,'redeemed')
        manifest = json.loads((volume/sid/'manifest.json').read_text('utf-8'))
        return jsonify(location='/admin/order-design/'+sid+('' if manifest.get('design') else '?pixel=1'))

    def data_folder():
        return volume/g.snapshot

    class CheckedConnection(sqlite3.Connection):
        def commit(self):
            # Serialize local kill and publication, including the fake-device receipt.
            with closing(sqlite3.connect(dbpath)) as guard,guard:
                guard.execute('begin immediate')
                access()
                super().commit()

    @contextmanager
    def connection():
        with closing(sqlite3.connect(data_folder()/'work.db',factory=CheckedConnection)) as db:
            yield db

    def private_editor_page(order_id):
        html = (ROOT/'index.html').read_text('utf-8').replace('window.__bfOrderDesignMode=',
             'window.__privateReedit=true;window.__bfOrderDesignMode=', 1)
        return app.response_class(html,mimetype='text/html')

    def historical_jobs(key):
        profile = g.manifest.get('profile')
        if not profile:
            return []
        return [dict(profile, id='snapshot', profile_complete=True, manual_independent=False,
                     sku_id='qa',copies=1,channel='fake',spot_color='qa',
                     artwork_sha256=g.manifest['print']['sha256'],artwork_path=g.manifest['print']['sha256'])]

    def upload(path,data):
        access()
        (data_folder()/path.replace('/','_')).write_bytes(data)

    class EditorContext(SimpleNamespace):
        @property
        def SAVE_DIR(self):
            return str(data_folder())

    module = EditorContext(app=app,USE_SUPABASE=False,
        send_from_directory=send_from_directory,no_cache_json=lambda data,status=200:(jsonify(data),status),
        commerce=SimpleNamespace(store=SimpleNamespace(connection=connection)),
        print_center=SimpleNamespace(store=SimpleNamespace(jobs_for_order=historical_jobs)),
        upload_private_bytes=upload,delete_private_path=lambda path:(data_folder()/path).unlink(missing_ok=True))
    from order_designs import install as install_editor, digest
    from design_sources import install as install_sources
    install_editor(module)
    install_sources(module)
    app.view_functions['page'] = private_editor_page

    def seed(key):
        from math import ceil
        manifest = g.manifest
        if manifest.get('design'):
            design = manifest['design']
            design=copy_document(design,key)
        else:
            sha = manifest['print']['sha256']
            size = manifest['print']['size']
            profile = historical_jobs(key)
            design=dict(mode='pixel-v1',basePath=sha,baseSha=sha,outputPath=sha,outputSha=sha,
                        size=size,dpi=720,profile=profile[0] if profile else None,objects=[],
                        factor=max(1,ceil(max(size)/1000)))
        module.order_designs.append(key,0,design,'private-qa','original')

    @app.before_request
    def protect():
        if request.endpoint in {'static','enter','bind_browser','redeem','receive'}:
            return
        if request.endpoint not in {'page','open_work','open_pixel','asset','asset_file','save','save_work','extract',
                                    'upload_design_source','release_design_sources','finish','catalog','checkpoint','heartbeat','info','reference_image','sticker_image'}:
            abort(404)
        if request.method not in ('GET','HEAD') and request.headers.get('Origin')!=origin('ADMIN_REEDIT_PRIVATE_ORIGIN'):
            abort(403)
        g.snapshot=access()
        g.manifest=json.loads((data_folder()/'manifest.json').read_text('utf-8'))
        # Only redemption initializes the host-only cookie. Authorization remains live.
        key=(request.view_args or {}).get('order_id')
        if key and key!=g.snapshot:
            if not re.fullmatch('MK-[0-9a-f]{32}',key):
                abort(404)
            with connection() as db:
                if not db.execute("select 1 from sqlite_master where name='made'").fetchone() or not db.execute(
                        'select 1 from made where id=?',(key,)).fetchone():
                    abort(404)
        if key==g.snapshot and request.endpoint in ('open_work','open_pixel') and not module.order_designs.rows(key):
            seed(key)

    @app.after_request
    def privacy(response):
        if request.endpoint not in {'static','enter','bind_browser','redeem','receive'} and response.status_code<400:
            access()
            if request.endpoint not in {'heartbeat','catalog','info','sticker_image'}:
                with closing(sqlite3.connect(dbpath)) as db, db:
                    db.execute('insert into operations values (?,?,?,?)',
                               (g.snapshot,g.manifest['operator'],request.endpoint,int(clock())))
        response.headers.update({'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer',
            'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY',
            'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self' blob: data:; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"})
        return response

    @app.get('/private/info')
    def info():
        made=[]
        with connection() as db:
            if db.execute("select 1 from sqlite_master where name='made'").fetchone():
                made=[dict(order=i,parent=p,state=s,task=t) for i,p,s,t in db.execute('select id,parent,status,task from made order by rowid')]
        return jsonify(review=g.manifest['review'],alignment=bool(g.manifest.get('alignment')),orders=made)

    @app.get('/private/reference/<any(preview,alignment):kind>')
    def reference_image(kind):
        from flask import send_file
        entry=g.manifest.get(kind)
        if not entry:
            abort(404)
        raw=(data_folder()/entry['sha256']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=entry['sha256']:
            abort(409)
        if kind=='alignment':
            from PIL import Image, ImageChops, ImageFilter
            with Image.open(io.BytesIO(raw)) as image:
                alpha=image.convert('RGBA').getchannel('A')
            bounds=alpha.getbbox()
            if not bounds or alpha.getextrema()[0]!=0:
                abort(422)
            w,h=g.manifest['print']['size']
            scale=min(1,1200/max(w,h))
            area=alpha.crop(bounds).resize((max(1,round(w*scale)),max(1,round(h*scale))))
            area=area.point(lambda v:255 if v>=24 else 0)
            edge=ImageChops.subtract(area,area.filter(ImageFilter.MinFilter(3)))
            guide=Image.new('RGBA',area.size,'#e82376')
            guide.putalpha(ImageChops.lighter(edge,area.point(lambda v:25 if v else 0)))
            out=io.BytesIO()
            guide.save(out,'PNG')
            raw=out.getvalue()
        return send_file(io.BytesIO(raw),mimetype='image/png')

    @app.get('/private/active')
    def heartbeat():
        return jsonify(active=True)

    @app.route('/private/checkpoint/<order_id>',methods=['GET','POST','DELETE'])
    def checkpoint(order_id):
        if request.method!='GET' and request.headers.get('X-Reedit-Test')!='1':
            abort(403)
        from flask import Response
        path=data_folder()/('checkpoint-'+order_id)
        if request.method=='POST':
            blob=request.get_data()
            if len(blob)>16*1024*1024:abort(413)
            access()
            with tempfile.NamedTemporaryFile(dir=data_folder(),delete=False) as tmp:
                tmp.write(blob)
            os.replace(tmp.name,path)
        elif request.method=='DELETE':
            access()
            path.unlink(missing_ok=True)
        elif path.exists():
            return Response(path.read_bytes(),mimetype='application/json')
        return jsonify(None)

    sticker_catalog=json.loads((ROOT/'private_reedit_stickers.json').read_text('utf-8'))
    sticker_names={s['url'] for s in sticker_catalog['stickers']}
    for sticker in sticker_catalog['stickers']:
        name=sticker['url']
        if not re.fullmatch(r'[a-zA-Z0-9_-]+\.png',name):
            raise ValueError('素材清單含無效檔名')
        sticker['url']='/private/sticker/'+name

    @app.get('/private/sticker/<name>')
    def sticker_image(name):
        if name not in sticker_names:
            abort(404)
        from flask import send_file
        from editable_stickers import image_bytes
        path=volume/('sticker-'+name)
        if not path.exists():
            url='https://sazoqqgeabjiyzbihpdy.supabase.co/storage/v1/object/public/case-assets/stickers/'+name
            with requests.get(url,stream=True,timeout=(3,12),allow_redirects=False) as upstream:
                if upstream.status_code!=200:
                    abort(502)
                buffer=io.BytesIO()
                for block in upstream.iter_content(65536):
                    buffer.write(block)
                    if buffer.tell()>16*1024*1024:abort(413)
                image_bytes(buffer.getvalue())
                with tempfile.NamedTemporaryFile(dir=volume,delete=False) as tmp:
                    tmp.write(buffer.getbuffer())
                os.replace(tmp.name,path)
        return send_file(path,mimetype='image/png')

    @app.get('/api/<any(shop_data,assets,templates):kind>')
    def catalog(kind):
        if kind=='shop_data':
            return jsonify(data=dict(models=[],styles=[],brands=[]))
        return jsonify(data=sticker_catalog if kind=='assets' else {'templates':[]})

    def copy_document(doc, key):
        from order_designs import asset_paths, persist_asset
        mapping={}
        for path in asset_paths(doc):
            mapping[path]=persist_asset(module,key,(data_folder()/path).read_bytes())
        return replace_paths(doc,mapping)

    @app.post('/private/finish/<order_id>')
    def finish(order_id):
        if request.headers.get('X-Reedit-Test')!='1':
            abort(403)
        payload=request.get_json()
        rows=module.order_designs.rows(order_id)
        record=next((r for r in rows if r['version']==payload.get('version') and r['content_hash']==payload.get('hash')),None)
        if not record or record['version']<2:
            abort(409)
        key='MK-'+digest([order_id,record['content_hash'],record['version']])[:32]
        doc=record['document']
        proof=doc if doc.get('mode')=='pixel-v1' else doc.get('revisionPrint',{})
        status='待核對'
        if g.manifest.get('alignment') and proof.get('profile') and proof.get('outputSha') and not proof.get('proof',{}).get('alphaExpansion'):
            original=(data_folder()/g.manifest['print']['sha256']).read_bytes()
            output=(data_folder()/proof['outputPath']).read_bytes()
            from pixel_order_designs import png, sha
            from PIL import ImageChops
            base=png(original,dpi=True)
            edited=png(output,base.size,True)
            if sha(output)==proof['outputSha'] and not ImageChops.subtract(
                    edited.getchannel('A').point(bool_alpha),base.getchannel('A').point(bool_alpha)).getbbox():
                status='假設備已接收'
        # Publish a child and its initial editable revision together.
        with connection() as db:
            db.execute('begin immediate')
            db.execute('create table if not exists made(id text primary key,parent text,status text,task text)')
            if not db.execute('select 1 from made where id=?',(key,)).fetchone():
                current=db.execute('select max(version) from order_design_versions where order_id=?',(order_id,)).fetchone()[0]
                if current!=record['version']:
                    abort(409)
                version=1
                if doc.get('mode')!='pixel-v1':
                    baseline=copy_document(rows[0]['document'],key)
                    db.execute('insert into order_design_versions values (?,?,?,?,?,?,CURRENT_TIMESTAMP)',
                               (key,1,json.dumps(baseline),'private-qa','baseline',digest(baseline)))
                    doc=copy_document(doc,key)
                    version=2
                task=None
                if status=='假設備已接收':
                    access()
                    status,task=fake_receipt(db,key,proof['outputSha'])
                db.execute('insert into made values (?,?,?,?)',(key,order_id,status,task))
                db.execute('insert into order_design_versions values (?,?,?,?,?,?,CURRENT_TIMESTAMP)',
                           (key,version,json.dumps(doc),'private-qa','original',digest(doc)))
                db.commit()
            else:
                status,task=db.execute('select status,task from made where id=?',(key,)).fetchone()
        audit(g.snapshot,'finished')
        return jsonify(order=key,parent=order_id,state=status,task=task,location='/admin/order-design/'+key+('?pixel=1' if doc.get('mode')=='pixel-v1' else ''))

    return app


def fake_receipt(db,key,artwork_hash):
    """The QA device keeps an immutable local receipt and has no network client."""
    db.execute('create table if not exists fake_device_receipts (order_id text primary key,sha256 text,task text unique)')
    result=os.environ.get('PRIVATE_REEDIT_FAKE_RESULT','accepted')
    if result=='rejected':
        return '假設備拒絕',None
    if result!='accepted':
        return '待核對（假設備回應不明）',None
    task='FAKE-'+key
    db.execute('insert into fake_device_receipts values (?,?,?)',(key,artwork_hash,task))
    return '假設備已接收',task


def bool_alpha(value):
    return 255 if value else 0
