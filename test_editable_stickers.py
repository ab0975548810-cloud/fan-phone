"""Real Fabric renderer plus API/CAS/legacy safety tests, no production/vendor access."""
import base64
import copy
import hashlib
import io
import unittest
from unittest import mock
from PIL import Image,ImageDraw
import editable_stickers as editable
import design_sources
import security_perf
import test_print_center as print_fixture
app,PNG=print_fixture.app,print_fixture.PNG
app.app._got_first_request=False
security_perf.install(app)
app.app.config['SESSION_COOKIE_SECURE']=False


def image(width=512,height=256):
    im=Image.new('RGBA',(width,height),(0,0,0,0));ImageDraw.Draw(im).rounded_rectangle((8,8,width-8,height-8),radius=32,fill='white',outline='#d56c96',width=5)
    out=io.BytesIO();im.save(out,'PNG');return out.getvalue()


def mask():
    im=Image.new('RGBA',(200,400),(0,0,0,0));d=ImageDraw.Draw(im);d.rectangle((10,10,189,389),fill='black');d.ellipse((18,18,58,58),fill=(0,0,0,0));out=io.BytesIO();im.save(out,'PNG');return out.getvalue()


def design(model,style):
    common={'editableStickerId':'dialog-a','editableStickerInstanceId':'instance-a','originX':'center','originY':'center','left':100,'top':200,'scaleX':.35,'scaleY':.35,'angle':0,'flipX':False,'flipY':False,'opacity':1,'visible':True}
    text={'type':'textbox','role':'editable-sticker-text','text':'繁體中文\n文字貼紙測試','fontFamily':'jf-openhuninn','fontSize':36,'requestedFontSize':36,'minFontSize':12,'fontWeight':'400','fontStyle':'normal','fill':'#332222','stroke':'#fff','strokeWidth':0,'textAlign':'center','charSpacing':20,'lineHeight':1.2,'width':350,'height':75,'textArea':{'x':.15,'y':.2,'width':.7,'height':.45},**common}
    bg={'type':'image','role':'editable-sticker-bg','assetId':'dialog-a','src':'data:image/png;base64,'+base64.b64encode(image()).decode(),'width':512,'height':256,**common}
    return {'render_contract_version':editable.VERSION,'fontHashes':{family:hashlib.sha256((editable.ROOT/file).read_bytes()).hexdigest() for family,file in editable.FONTS.items()},'modelId':model,'styleId':style,'logicalCanvas':{'width':200,'height':400},'production':{'printW':71.63,'printH':149.61},'objects':[bg,text],'background':'transparent'}


class EditableTests(unittest.TestCase):
    def setUp(self):
        security_perf._HITS.clear();security_perf._CACHE.clear()
        self.fixture=print_fixture.PrintCenterTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.client=self.fixture.client
        self.model=app.DEFAULT_SHOP_DATA['models'][0]['id'];self.style=app.DEFAULT_SHOP_DATA['styles'][0]['id']
        shop=copy.deepcopy(app.DEFAULT_SHOP_DATA);shop['models'][0]['case_profiles']={self.style:{'preview_mask_img':'/static/dialog-preview.png','print_line_img':'/static/dialog-mask.png','print_w':71.63,'print_h':149.61,'print_x':12,'print_y':13,'print_angle':90}}
        app.local_save_json(app.DATA_FILE,shop)
        app.print_center.store.save_profiles([{'sku_id':self.fixture.sku_id,'width_mm':71.63,'height_mm':149.61,'left_mm':12,'top_mm':13,'angle':90,'copies':1,'channel':'1','spot_color':''}])
        self.draft=design(self.model,self.style)

    def create(self,draft=None):
        draft=self.upload(draft or self.draft)
        with mock.patch.object(editable,'public_image',return_value=mask()):
            response=self.client.post('/api/create_order',json=self.body(draft))
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        return response.json['order_id']

    def body(self,draft,key=None):
        return {'idempotency_key':key or 'structured-'+__import__('uuid').uuid4().hex,'model_id':self.model,'style_id':self.style,'quantity':1,'customer_name':'文字貼紙','payment_method':'現金','print_file':PNG,'mockup_file':PNG,'design_json':draft}

    def upload(self,draft,client=None):
        client=client or self.client;draft=copy.deepcopy(draft);draft['sourceCheckout']=__import__('uuid').uuid4().hex
        for item in editable.nodes(draft):
            if item['type']!='image':continue
            raw=base64.b64decode(item.pop('src').split(',')[1])
            result=client.post('/api/design-sources',data={'checkout':draft['sourceCheckout'],'file':(io.BytesIO(raw),'source.png','image/png')})
            self.assertEqual(result.status_code,200,result.json)
            item.update(sourceRef=result.json['sourceRef'],sourceSha256=result.json['sha256'])
        return draft

    def test_schema_and_normalized_area(self):
        editable.validate(self.draft)
        for area in ({'x':.8,'y':.1,'width':.3,'height':.5},{'x':0,'y':0,'width':0,'height':1},{'x':True,'y':0,'width':.5,'height':1}):
            with self.assertRaises(ValueError):editable.normalized_area(area)
        bad=copy.deepcopy(self.draft);bad['objects'].pop()
        with self.assertRaises(ValueError):editable.validate(bad)
        bad=copy.deepcopy(self.draft);bad['objects'][1]['text']='\U0001fae8'
        with self.assertRaises(ValueError):editable.validate(bad)

    def test_sources_and_complete_text_contract_persist(self):
        order=app.commerce.store.order(self.create());data=order['design_json']
        self.assertEqual(data['render_contract_version'],editable.VERSION)
        self.assertTrue(data['objects'][0]['src'].startswith(f'orders_{order["id"]}_sources_'))
        self.assertEqual(app.print_center._download_artwork(data['objects'][0]['src']),image())
        for key,value in self.draft['objects'][1].items():self.assertEqual(data['objects'][1][key],value)
        self.assertEqual(set(data['fontHashes']),set(editable.FONTS))
        self.assertEqual(Image.open(io.BytesIO(app.print_center._download_artwork(order['print_path']))).size,(1,1))

    def test_real_high_resolution_prepare_ignores_client_raster(self):
        order_id=self.create();order=app.commerce.store.order(order_id)
        job=app.print_center.prepare(order_id,'editable-prepare')
        self.assertNotEqual(job['artwork_path'],order['print_path'])
        raw=app.print_center._download_artwork(job['artwork_path']);im=Image.open(io.BytesIO(raw))
        self.assertEqual(im.size,(2030,4241));self.assertAlmostEqual(im.info['dpi'][0],720,delta=.05)
        self.assertEqual(job['artwork_sha256'],hashlib.sha256(raw).hexdigest())
        self.assertEqual(im.getpixel((0,0))[3],0)
        self.assertEqual(app.commerce.store.order(order_id)['print_path'],order['print_path'])
        self.assertEqual(app.print_center.prepare(order_id,'editable-prepare')['id'],job['id'])
        self.assertEqual(self.fixture.fake.calls,[])

    def test_missing_font_and_missing_asset_fail_closed(self):
        order=app.commerce.store.order(self.create());profile=app.print_center.store.profile(self.fixture.sku_id)
        bad=copy.deepcopy(order);bad['design_json']['fontHashes']['jf-openhuninn']='bad'
        with self.assertRaises(ValueError):editable.render(app,bad,profile,app.print_center._download_artwork)
        with self.assertRaises(Exception):editable.render(app,order,profile,lambda path: (_ for _ in ()).throw(FileNotFoundError(path)))
        bad=copy.deepcopy(self.draft);bad['objects'][1]['fontFamily']='https://evil.invalid/font.ttf'
        with self.assertRaises(ValueError):editable.validate(bad)

    def test_stale_browser_font_hash_is_rejected_before_order(self):
        bad=copy.deepcopy(self.draft);bad['fontHashes']['jf-openhuninn']='stale'
        with mock.patch.object(editable,'public_image',return_value=mask()),mock.patch.object(app,'upload_private_bytes') as upload:
            model=app.cloud_get_json('shop_data',app.DATA_FILE,app.DEFAULT_SHOP_DATA)['models'][0]
            with self.assertRaises(ValueError):editable.snapshot(app,bad,'font-stale',model,self.style,[])
        upload.assert_not_called()

    def test_geometry_change_fail_closed(self):
        order=app.commerce.store.order(self.create());profile=app.print_center.store.profile(self.fixture.sku_id);profile['width_mm']=80
        with self.assertRaises(ValueError):editable.render(app,order,profile,app.print_center._download_artwork)

    def test_legacy_order_still_uses_print_path(self):
        order=app.commerce.store.order(self.fixture.order_id);job=app.print_center.prepare(order['id'],'legacy-preserved')
        self.assertEqual(job['artwork_path'],order['print_path'])

    def test_generated_artifact_retry_is_immutable(self):
        path='orders/fixture/rendered/content.png';raw=image()
        saved=editable.store_generated(app,path,raw)
        full=__import__('pathlib').Path(app.SAVE_DIR)/saved;stamp=full.stat().st_mtime_ns
        self.assertEqual(editable.store_generated(app,path,raw),saved);self.assertEqual(full.stat().st_mtime_ns,stamp)
        with self.assertRaises(ValueError):editable.store_generated(app,path,b'wrong')

    def test_storage_conflict_or_lost_response_reuses_only_exact_artifact(self):
        from types import SimpleNamespace
        bucket=mock.Mock();bucket.download.return_value=image()
        storage=mock.Mock();storage.from_.return_value=bucket
        fake=SimpleNamespace(USE_SUPABASE=True,SUPABASE=SimpleNamespace(storage=storage),SUPABASE_PRIVATE_BUCKET='test-only',upload_private_bytes=mock.Mock(side_effect=TimeoutError('lost reply')))
        self.assertEqual(editable.store_generated(fake,'orders/test/rendered/hash.png',image()),'orders/test/rendered/hash.png')
        bucket.download.return_value=b'wrong'
        with self.assertRaises(ValueError):editable.store_generated(fake,'orders/test/rendered/hash.png',image())

    def test_total_source_pixel_guard_runs_before_upload(self):
        model=app.cloud_get_json('shop_data',app.DATA_FILE,app.DEFAULT_SHOP_DATA)['models'][0]
        with mock.patch.object(editable,'MAX_SOURCE_PIXELS',1),mock.patch.object(app,'upload_private_bytes') as upload:
            with self.assertRaises(ValueError):editable.snapshot(app,self.draft,'pixel-limit',model,self.style,[])
        upload.assert_not_called()

    def test_cross_order_source_is_rejected_before_read(self):
        order=app.commerce.store.order(self.create());profile=app.print_center.store.profile(self.fixture.sku_id)
        order['design_json']['objects'][0]['src']='orders_other_sources_wrong.png'
        reader=mock.Mock()
        with self.assertRaises(ValueError):editable.render(app,order,profile,reader)
        reader.assert_not_called()

    def test_admin_auth_cas_and_defaults(self):
        old=app.ASSETS_FILE;app.ASSETS_FILE=str(__import__('pathlib').Path(self.fixture.tmp.name)/'assets.json');self.addCleanup(setattr,app,'ASSETS_FILE',old)
        anonymous=app.app.test_client();self.assertEqual(anonymous.post('/api/admin/editable_sticker',json={}).status_code,401)
        _,version=app.cloud_get_json_versioned('assets',app.ASSETS_FILE,app.DEFAULT_ASSETS)
        body={'name':'對話框','imageSrc':'/static/dialog.png','textArea':self.draft['objects'][1]['textArea'],'defaultTextStyle':{k:v for k,v in self.draft['objects'][1].items() if k in ('text','fontFamily','fontSize','minFontSize','fontWeight','fontStyle','fill','stroke','strokeWidth','textAlign','charSpacing','lineHeight')},'expected_version':version}
        with mock.patch('editable_sticker_admin.public_image',return_value=image()):
            result=self.client.post('/api/admin/editable_sticker',json=body)
            self.assertEqual(result.status_code,200,result.json)
            self.assertEqual(self.client.post('/api/admin/editable_sticker',json=body).status_code,409)
        row=result.json['data']['editable_stickers'][0]
        self.assertEqual(row['intrinsicSize'],{'width':512,'height':256});self.assertEqual(row['textArea'],body['textArea'])
        self.assertEqual(result.json['data']['stickers'],app.DEFAULT_ASSETS['stickers'])

    def test_large_photo_uses_receipt_under_production_gates(self):
        # Incompressible PNG really exceeds 2MB; install production middleware.
        raw=__import__('os').urandom(1100*1100*4)
        photo=Image.frombytes('RGBA',(1100,1100),raw);buffer=io.BytesIO();photo.save(buffer,'PNG');raw=buffer.getvalue()
        self.assertGreater(len(raw),2*1024*1024)
        draft=copy.deepcopy(self.draft)
        draft['objects'].append({'type':'image','src':'data:image/png;base64,'+base64.b64encode(raw).decode(),'width':1100,'height':1100,'left':0,'top':0})
        uploaded=self.upload(draft);body=self.body(uploaded)
        self.assertLess(len(__import__('json').dumps(body)),2000000)
        self.assertNotIn('base64',__import__('json').dumps(uploaded))
        with mock.patch.object(editable,'public_image',return_value=mask()):
            response=self.client.post('/api/create_order',json=body)
        self.assertEqual(response.status_code,200,response.json)
        self.assertEqual(app.app.config['MAX_CONTENT_LENGTH'],36*1024*1024)

    def test_foreign_checkout_and_expired_receipts_fail_closed(self):
        uploaded=self.upload(self.draft);other=app.app.test_client()
        with mock.patch.object(editable,'public_image',return_value=mask()):
            self.assertEqual(other.post('/api/create_order',json=self.body(uploaded)).status_code,400)
            changed=copy.deepcopy(uploaded);changed['sourceCheckout']=__import__('uuid').uuid4().hex
            self.assertEqual(self.client.post('/api/create_order',json=self.body(changed)).status_code,400)
            with mock.patch('design_sources.time.time',return_value=__import__('time').time()+2*86400):
                self.assertEqual(self.client.post('/api/create_order',json=self.body(uploaded)).status_code,400)

    def test_preupload_mime_file_and_total_guards(self):
        checkout=__import__('uuid').uuid4().hex
        self.assertEqual(self.client.post('/api/design-sources',data={'checkout':checkout,'file':(io.BytesIO(image()),'x.png','image/jpeg')}).status_code,400)
        with mock.patch.object(design_sources,'MAX_FILE_BYTES',10):
            self.assertEqual(self.client.post('/api/design-sources',data={'checkout':checkout,'file':(io.BytesIO(image()),'x.png','image/png')}).status_code,400)
        for field in ('MAX_BYTES','MAX_SOURCE_PIXELS'):
            uploaded=self.upload(self.draft)
            with mock.patch.object(editable,field,1),mock.patch.object(editable,'public_image',return_value=mask()):
                response=self.client.post('/api/create_order',json=self.body(uploaded))
            self.assertEqual(response.status_code,400,response.json)
            self.assertEqual(self.order_files(),[])

    def order_files(self):
        from pathlib import Path
        return [p.name for p in Path(app.SAVE_DIR).glob('orders_*') if self.fixture.order_id not in p.name]

    def test_rollback_snapshot_commerce_and_database_failure(self):
        from commerce_patch import CommerceError
        for failure in (ValueError('snapshot failed'),CommerceError('NO_STOCK','不足'),RuntimeError('database failed')):
            uploaded=self.upload(self.draft)
            target=mock.patch.object(editable,'public_image',side_effect=failure) if isinstance(failure,ValueError) else mock.patch.object(app.commerce,'create',side_effect=failure)
            with mock.patch.object(editable,'public_image',return_value=mask()),target:
                response=self.client.post('/api/create_order',json=self.body(uploaded))
            self.assertGreaterEqual(response.status_code,400)
            self.assertEqual(self.order_files(),[])
            self.assertEqual(list(__import__('pathlib').Path(app.SAVE_DIR).glob('design-temp*')),[])

    def test_duplicate_order_and_permanent_delete_cleanup(self):
        uploaded=self.upload(self.draft);body=self.body(uploaded)
        with mock.patch.object(editable,'public_image',return_value=mask()):
            first=self.client.post('/api/create_order',json=body)
        self.assertEqual(first.status_code,200,first.json);order_id=first.json['order_id']
        before=set(self.order_files())
        # A new pre-upload on retry must not orphan files, even if replay short-circuits the view.
        repeated=self.upload(self.draft);body['design_json']=repeated
        with mock.patch.object(editable,'public_image',return_value=mask()):
            second=self.client.post('/api/create_order',json=body)
        self.assertEqual(second.json['order_id'],order_id)
        # Client releases preuploads when middleware replies with an existing order.
        self.client.post('/api/design-sources/release',json=repeated)
        self.assertEqual(set(self.order_files()),before)
        app.commerce.action(order_id,'void','作廢')
        with app.print_center.store.connection(write=True) as db:
            db.execute("UPDATE print_jobs SET state='CANCELED' WHERE order_id=?",(order_id,))
        app.commerce.action(order_id,'delete','作廢')
        self.assertFalse(any(order_id in name for name in self.order_files()))

    def test_expiration_janitor_survives_restart(self):
        uploaded=self.upload(self.draft)
        files=list(__import__('pathlib').Path(app.SAVE_DIR).glob('design-temp*'));self.assertTrue(files)
        design_sources.cleanup_expired(app,now=__import__('time').time()+2*86400)
        self.assertTrue(all(not path.exists() for path in files))

    def test_ordinary_font_and_emoji_contract(self):
        for family,text in [('Arial','Arial 普通文字'),('serif','明體文字'),('cursive','手寫文字'),('Times New Roman','🐱💖')]:
            draft=copy.deepcopy(self.draft);draft['objects'].append({'type':'textbox','fontFamily':family,'fontSize':24,'text':text,'width':160,'left':10,'top':20})
            editable.validate(draft)
            self.assertTrue(self.create(draft))

    def test_cache_invalidation_for_editable_sticker_mutations(self):
        old=app.ASSETS_FILE;app.ASSETS_FILE=str(__import__('pathlib').Path(self.fixture.tmp.name)/'cache-assets.json');self.addCleanup(setattr,app,'ASSETS_FILE',old)
        body={'name':'cache test','imageSrc':'/static/dialog.png','textArea':self.draft['objects'][1]['textArea'],
              'defaultTextStyle':{k:v for k,v in self.draft['objects'][1].items() if k in ('text','fontFamily','fontSize','minFontSize','fontWeight','fontStyle','fill','stroke','strokeWidth','textAlign','charSpacing','lineHeight')}}
        for action in ('create','edit','delete'):
            self.assertEqual(self.client.get('/api/assets').status_code,200)
            self.assertEqual(self.client.get('/api/templates').status_code,200)
            self.assertIn('/api/assets',security_perf._CACHE);self.assertIn('/api/templates',security_perf._CACHE)
            _,body['expected_version']=app.cloud_get_json_versioned('assets',app.ASSETS_FILE,app.DEFAULT_ASSETS)
            if action=='delete':body['action']='delete'
            if action=='edit':body['name']='edited cache test'
            with mock.patch('editable_sticker_admin.public_image',return_value=image()):
                response=self.client.post('/api/admin/editable_sticker',json=body)
            self.assertEqual(response.status_code,200,response.json)
            if action=='create':body['id']=response.json['data']['editable_stickers'][0]['id']
            self.assertNotIn('/api/assets',security_perf._CACHE);self.assertNotIn('/api/templates',security_perf._CACHE)

    def test_partial_upload_lost_reply_cleans_print_preview_and_sources(self):
        actual=app.upload_private_bytes
        for fail_at in ('/print.png','/preview.png','/sources/print-mask.png'):
            uploaded=self.upload(self.draft)
            def lost(path,raw,mime='image/png'):
                result=actual(path,raw,mime)
                if path.endswith(fail_at):raise TimeoutError('uploaded then lost response')
                return result
            with mock.patch.object(app,'upload_private_bytes',side_effect=lost),mock.patch.object(editable,'public_image',return_value=mask()):
                response=self.client.post('/api/create_order',json=self.body(uploaded))
            self.assertGreaterEqual(response.status_code,400)
            self.assertEqual(self.order_files(),[])

    def test_commit_reply_lost_keeps_successful_order_sources(self):
        uploaded=self.upload(self.draft);body=self.body(uploaded);actual=app.commerce.create
        def committed_then_lost(order):
            actual(order);raise TimeoutError('committed then response lost')
        with mock.patch.object(app.commerce,'create',side_effect=committed_then_lost),mock.patch.object(editable,'public_image',return_value=mask()):
            response=self.client.post('/api/create_order',json=body)
        self.assertEqual(response.status_code,500)
        self.assertTrue(self.order_files())
        body['design_json']=self.upload(self.draft)
        repeat=self.client.post('/api/create_order',json=body)
        self.assertEqual(repeat.status_code,200,repeat.json)
        order=app.commerce.store.order(repeat.json['order_id'])
        self.assertEqual(app.print_center._download_artwork(order['design_json']['objects'][0]['src']),image())

    def test_failed_storage_cleanup_is_durable_and_retried(self):
        uploaded=self.upload(self.draft)
        actual=app.delete_private_path
        def fail_image(path):return False if path and path.endswith('.png') and path.startswith('orders_') else actual(path)
        with mock.patch.object(app,'delete_private_path',side_effect=fail_image),mock.patch.object(app.commerce,'create',side_effect=RuntimeError('DB failure')),mock.patch.object(editable,'public_image',return_value=mask()):
            self.assertEqual(self.client.post('/api/create_order',json=self.body(uploaded)).status_code,500)
        root=__import__('pathlib').Path(app.SAVE_DIR)
        self.assertTrue(list(root.glob('design-cleanup*')));self.assertTrue(self.order_files())
        design_sources.cleanup_expired(app,now=__import__('time').time()+2*86400)
        self.assertEqual(self.order_files(),[]);self.assertFalse(list(root.glob('design-cleanup*')))

    def test_cloud_commit_still_pending_does_not_delete_artwork(self):
        uploaded=self.upload(self.draft);claims=design_sources.signer(app).loads(uploaded['objects'][0]['sourceRef'])
        files={f'design-temp/{claims["expires"]}/{claims["id"]}.png':image()}
        bucket=mock.Mock();bucket.download.side_effect=lambda path:files[path]
        storage=mock.Mock();storage.from_.return_value=bucket
        from types import SimpleNamespace
        fake=SimpleNamespace(storage=storage)
        shop=app.cloud_get_json('shop_data',app.DATA_FILE,app.DEFAULT_SHOP_DATA)
        def upload(path,raw,mime='image/png'):files[path]=raw;return path
        def delete(path):files.pop(path,None);return True
        cookie=self.client.get_cookie('session').value
        with app.app.test_request_context('/api/create_order',method='POST',json=self.body(uploaded),headers={'Cookie':'session='+cookie}),mock.patch.object(app,'USE_SUPABASE',True),mock.patch.object(app,'SUPABASE',fake),mock.patch.object(app,'upload_private_bytes',side_effect=upload),mock.patch.object(app,'delete_private_path',side_effect=delete),mock.patch.object(app.commerce,'create',side_effect=TimeoutError('RPC still running')),mock.patch.object(app.commerce.store,'order',return_value=None),mock.patch.object(editable,'public_image',return_value=mask()):
            app.g.commerce_shop=shop
            response=app.create_order()
        self.assertEqual(response.status_code,500)
        self.assertTrue(any(path.startswith('orders/') and '/sources/' in path for path in files))
        self.assertTrue(any(path.startswith('design-cleanup/') for path in files))

if __name__=='__main__':unittest.main(verbosity=2)
