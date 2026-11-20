"""Run both HTTP applications with disposable databases and synthetic artwork."""
import base64
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from flask import Flask
from PIL import Image
from reedit_access import fingerprint
from reedit_private_site import create_private_site, cleanup
from reedit_transport import install

SOURCE='https://shop.test'
QA='https://private.test'


def png(color):
    out=io.BytesIO()
    Image.new('RGBA',(32,64),color).save(out,'PNG',dpi=(720,720))
    return out.getvalue()


class PrivateHttpTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.source=Path(temp.name)/'shop'
        self.volume=Path(temp.name)/'private'
        self.source.mkdir()
        self.volume.mkdir()
        self.credentials=[dict(credential_id='credential-'+self._testMethodName,public_key='publickey')]
        self.identity=fingerprint(self.credentials[0])
        self.env=patch.dict(os.environ,dict(ADMIN_REEDIT_TEST_ENABLED='true',ADMIN_REEDIT_GENERATION='0123456789abcdef',

            ADMIN_REEDIT_TEST_CREDENTIAL_SHA256=self.identity,ADMIN_REEDIT_PRIVATE_ORIGIN=QA,
            ADMIN_REEDIT_SOURCE_ORIGIN=SOURCE, ADMIN_REEDIT_TRANSFER_KEY='k'*45))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.art=png('red')
        for name in ('print','preview','sources_mask'):
            (self.source/('orders_A_'+name+'.png')).write_bytes(self.art)
        mask=Image.new('RGBA',(34,66))
        mask.paste('white',(1,1,33,65))
        mask.save(self.source/'orders_A_sources_mask.png')
        dims=[n*25.4/720 for n in (32,64)]
        row=dict(id='A',model_id='m',model_name='M',style_id='s',style_name='S',customer_name='PRIVATE-TEST',
                 print_path='orders_A_print.png',mockup_path='orders_A_preview.png',design_json=dict(
                     modelId='m',styleId='s',production=dict(printW=dims[0],printH=dims[1],maskPath='orders_A_sources_mask.png'),
                     editorContext=dict(printX=0,printY=0,printAngle=0)))
        path=self.source/'original.db'
        with closing(sqlite3.connect(path)) as db,db:
            db.execute('create table orders(id text,value text)')
            db.execute('insert into orders values (?,?)',('A',json.dumps(row)))
            db.execute('create table print_jobs(order_id,artwork_sha256,profile_complete,manual_independent,width_mm,height_mm,left_mm,top_mm,angle)')
            db.execute('insert into print_jobs values (?,?,?,?,?,?,?,?,?)',('A',hashlib.sha256(self.art).hexdigest(),1,0,*dims,0,0,0))
        app=Flask('source')
        app.secret_key='production-only-test-signing-key'
        store=SimpleNamespace(store=SimpleNamespace(path=path))
        module=SimpleNamespace(app=app,USE_SUPABASE=False,SAVE_DIR=self.source,commerce=store,print_center=store)
        service=SimpleNamespace(config=SimpleNamespace(origin=SOURCE),registered_for_reedit=lambda:self.credentials)
        self.service=service
        install(module,service)
        self.prod=app.test_client()
        self.introspect=app.test_client()
        def authorize(claim,proof=None,challenge=None):
            headers={'X-Test-Claim':claim}
            if proof:headers.update({'X-Browser-Proof':proof,'X-Browser-Challenge':challenge})
            resp=self.introspect.post('/internal/reedit-test/authorize',headers=headers)
            return resp.status_code==200
        self.qa_app=create_private_site(self.volume,'private-session-secret'*3,authorize)
        self.qa=self.qa_app.test_client()
        def transfer(url,**kwargs):
            self.assertEqual(url,os.environ['ADMIN_REEDIT_PRIVATE_ORIGIN']+'/private/import')
            self.assertNotIn(b'PRIVATE-TEST',kwargs['data'])
            self.assertNotIn('Cookie',kwargs['headers'])
            response=self.qa_app.test_client().post('/private/import',data=kwargs['data'],headers=kwargs['headers'])
            return SimpleNamespace(status_code=response.status_code,json=response.get_json)
        transport=patch('reedit_transport.requests.post',side_effect=transfer)
        transport.start()
        self.addCleanup(transport.stop)
        self.start='/api/admin/reedit-test/A/start'
        self.src_headers={'Origin':SOURCE,'X-Reedit-Test':'1'}
        self.headers={'Origin':QA,'X-Order-Design':'1','X-Reedit-Test':'1'}
        self.before=self.source_contents()

    def source_contents(self):
        return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.source.iterdir()}

    def login(self):
        with self.prod.session_transaction() as sess:
            sess.update(logged_in=True,auth_method='passkey',reedit_fingerprint=self.identity,reedit_verified_at=int(time.time()))

    def enter(self):
        self.login()
        resp=self.prod.post(self.start,headers=self.src_headers)
        self.assertEqual(resp.status_code,200,resp.data)
        snapshot,code=urlsplit(resp.json['location']).fragment.split('.')
        redeem=dict(snapshot=snapshot,code=code)
        bound=self.qa.post('/private/bind',headers=self.headers,json=redeem)
        challenge=urlsplit(bound.json['location']).fragment.split('.')[1]
        confirm=dict(snapshot=snapshot,challenge=challenge)
        unrelated=self.prod.application.test_client()
        self.assertEqual(unrelated.post('/api/admin/reedit-test/confirm',headers=self.src_headers,json=confirm).status_code,403)
        signed=self.prod.post('/api/admin/reedit-test/confirm',headers=self.src_headers,json=confirm)
        proof=dict(proof=urlsplit(signed.json['location']).fragment)
        self.assertEqual(self.qa_app.test_client().post('/private/redeem',headers=self.headers,json=proof).status_code,403)
        self.assertEqual(self.qa.post('/private/redeem',headers=self.headers,json=proof).status_code,200)
        self.assertEqual(self.qa.post('/private/redeem',headers=self.headers,json=redeem).status_code,403)
        return snapshot

    def make(self,key,color,expected='假設備已接收'):
        path='/api/admin/order-design/'+key+'/pixel'
        work=self.qa.post(path+'/open',headers=self.headers,json={}).json
        self.assertTrue(work.get('work'),work)
        dataurl=lambda data:'data:image/png;base64,'+base64.b64encode(data).decode()
        payload=dict(work=work['work'],overlay=dataurl(png(color)),erase=dataurl(png((0,0,0,0))),objects=[])
        result=self.qa.post(path+'/save',headers=self.headers,json=payload)
        self.assertEqual(result.status_code,200,result.data)
        fields=dict(hash=result.json['hash'],version=result.json['version'])
        submit='/private/finish/'+key
        first=self.qa.post(submit,headers=self.headers,json=fields)
        self.assertEqual(first.status_code,200,first.data)
        self.assertEqual(self.qa.post(submit,headers=self.headers,json=fields).json,first.json)
        self.assertEqual(first.json['parent'],key)
        self.assertEqual(first.json['state'],expected)
        return first.json['order'],work['design']['previewPath']

    def test_private_a_b_c_rollback_retention(self):
        self.assertFalse(self.prod.get('/api/admin/reedit-test/access').json['enabled'])
        self.assertEqual(self.prod.post(self.start,headers=self.src_headers).status_code,403)
        self.login()
        self.assertEqual(self.prod.post(self.start,headers={'Origin':QA}).status_code,403)
        root=self.enter()
        first,image=self.make(root,'blue')
        second,_=self.make(first,'green')
        self.assertNotEqual(first,second)
        page=self.qa.get('/admin/order-design/'+second)
        self.assertIn(b'window.__privateReedit=true',page.data)
        self.assertIn(b'front-editor-controls-v1.js',page.data)
        self.assertEqual(self.qa.get(image).status_code,200)
        shared=self.qa_app.test_client()
        with shared.session_transaction() as s:s['logged_in']=True
        self.assertEqual(shared.get(image).status_code,403)
        self.assertEqual(self.qa.post('/api/create_order',json={}).status_code,404)
        self.assertEqual(self.qa.post('/api/admin/order-design/'+root+'/pixel/send',json={}).status_code,404)
        with closing(sqlite3.connect(self.volume/root/'work.db')) as db:
            self.assertEqual(db.execute('select parent,id from made order by rowid').fetchall(),[(root,first),(first,second)])
            self.assertEqual(db.execute('select count(distinct task) from made').fetchone(),(2,))
        with patch.dict(os.environ,{'ADMIN_REEDIT_TEST_ENABLED':'false'}):
            for path in (image,'/private/active','/private/checkpoint/'+root):
                self.assertEqual(self.qa.get(path).status_code,403)
            for path in ('/private/finish/'+root,'/api/admin/order-design/'+root+'/pixel/save'):
                self.assertEqual(self.qa.post(path,headers=self.headers,json={}).status_code,403)
            cleanup(self.volume,revoke=True)
        self.assertEqual(self.qa.get(image).status_code,403)
        cleanup(self.volume,now=time.time()+7*86400+1)
        self.assertFalse((self.volume/root).exists())
        self.assertEqual(self.source_contents(),self.before)

    def test_layered_snapshot_private_assets_and_history(self):
        from editable_stickers import ROOT,FONTS,VERSION
        photo=png('navy')
        sha=hashlib.sha256(photo).hexdigest()
        asset='orders_A_sources_'+sha+'.png'
        (self.source/asset).write_bytes(photo)
        with closing(sqlite3.connect(self.source/'original.db')) as db,db:
            order=json.loads(db.execute('select value from orders').fetchone()[0])
            d=order['design_json']
            d['editorContext'].update(productType='camera_film',previewPath='orders_A_sources_mask.png')
            d.update(version='5.3.1',background='transparent',render_contract_version=VERSION,orderDesignVersion=1,
                     logicalCanvas=dict(width=32,height=64),fontHashes={k:hashlib.sha256((ROOT/v).read_bytes()).hexdigest() for k,v in FONTS.items()},
                     objects=[dict(type='image',src=asset,width=32,height=64,sourceSha256=sha,originalName='PRIVATE-TEST.jpg'),
                              dict(type='rect',width=4,height=7,left=2,top=3,angle=27)])
            db.execute('update orders set value=?',(json.dumps(order),))
            db.execute('delete from print_jobs')
        before=self.source_contents()
        key=self.enter()
        root='/api/admin/order-design/'+key
        work=self.qa.post(root+'/open',headers=self.headers,json={}).json
        d=work['design']
        image=d['objects'][0]
        self.assertEqual(self.qa.get(image['src']).data,photo)
        self.assertNotIn('originalName',image)
        self.assertEqual(d['editorContext']['productType'],'camera_film')
        self.assertEqual(d['objects'][1]['angle'],27)
        checkout='a'*32
        upload=self.qa.post('/api/design-sources',headers=self.headers,data={'checkout':checkout,'file':(io.BytesIO(photo),'part.png','image/png')})
        self.assertEqual(upload.status_code,200,upload.data)
        image.pop('src');image['sourceRef']=upload.json['sourceRef']
        d['sourceCheckout']=checkout
        d['objects'][1]['angle']=42
        save=self.qa.post(root+'/save',headers=self.headers,json={'work':work['work'],'design':d})
        self.assertEqual(save.status_code,200,save.data)
        made=self.qa.post('/private/finish/'+key,headers=self.headers,json=dict(hash=save.json['hash'],version=save.json['version'])).json
        self.assertEqual(made['state'],'待核對')
        self.assertEqual(key,self.enter())
        reopen=self.qa.post('/api/admin/order-design/'+made['order']+'/open',headers=self.headers,json={}).json
        self.assertEqual(reopen['design']['objects'][1]['angle'],42)
        self.assertEqual(self.source_contents(),before)

    def test_tampered_bundle_and_service_outage(self):
        import requests
        from reedit_private_site import online
        with patch('requests.post',side_effect=requests.Timeout):
            self.assertFalse(online('test'))
        bad=self.qa.post('/private/import',data=b'not a bundle',headers={'X-Test-Claim':'invalid','X-Test-Signature':'0'*64})
        self.assertEqual(bad.status_code,403)
        self.assertEqual([p.name for p in self.volume.iterdir()],['access.db'])
        from reedit_private_handoffs import PrivateHandoffs
        self.login()
        with patch.object(PrivateHandoffs,'record_issue',side_effect=ValueError('cancel')):
            self.assertEqual(self.prod.post(self.start,headers=self.src_headers).status_code,422)
        self.assertEqual([p.name for p in self.volume.iterdir()],['access.db'])
        with closing(sqlite3.connect(self.volume/'access.db')) as db:
            self.assertEqual(db.execute('select count(*) from snapshots').fetchone(),(0,))
            self.assertEqual(db.execute('select count(*) from handoffs').fetchone(),(0,))

    def test_fake_rejection_unknown_and_missing_evidence(self):
        key=self.enter()
        with patch.dict(os.environ,{'PRIVATE_REEDIT_FAKE_RESULT':'timeout'}):
            key,_=self.make(key,'blue','待核對（假設備回應不明）')
        with patch.dict(os.environ,{'PRIVATE_REEDIT_FAKE_RESULT':'rejected'}):
            key,_=self.make(key,'green','假設備拒絕')
        (self.source/'orders_A_sources_mask.png').unlink()
        key=self.enter()
        self.make(key,'blue','待核對')
        self.assertTrue(self.qa.get('/private/info').json['review'])

    def test_removed_registration_cannot_open_or_view(self):
        root=self.enter()
        self.credentials.clear()
        self.assertEqual(self.qa.get('/admin/order-design/'+root).status_code,403)
        self.assertFalse(self.prod.get('/api/admin/reedit-test/access').json['enabled'])
        self.assertEqual(self.source_contents(),self.before)
