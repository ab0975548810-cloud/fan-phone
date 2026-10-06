"""Checkout against an image-only private bucket; no production DB or vendor."""
import io
import json
import time
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import mock
from PIL import Image
from storage3.exceptions import StorageApiError
import test_editable_stickers as fixture
import design_sources
import editable_stickers as editable

app=fixture.app


class ImageOnlyBucket:
    def __init__(self):self.files={};self.uploads=[]
    def upload(self,path,raw,file_options):
        mime=file_options['content-type']
        if mime!='image/png':raise StorageApiError('mime type '+mime+' is not supported','invalid_mime_type',415)
        with Image.open(io.BytesIO(raw)) as image:
            if image.format!='PNG':raise AssertionError('MIME must match actual PNG bytes')
        self.files[path]=raw;self.uploads.append((path,mime))
    def remove(self,paths):
        for path in paths:self.files.pop(path,None)
    def download(self,path):return self.files[path]
    def list(self,prefix,options):
        names={key[len(prefix)+1:].split('/')[0] for key in self.files if key.startswith(prefix+'/')}
        return [{'name':name} for name in sorted(names)[:options['limit']]]


class OrderStorageCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.EditableTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.bucket=ImageOnlyBucket()
        self.fake=SimpleNamespace(storage=SimpleNamespace(from_=lambda name:self.bucket))
        self.shop=app.local_load_json(app.DATA_FILE,app.DEFAULT_SHOP_DATA)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(app,'USE_SUPABASE',True))
        self.stack.enter_context(mock.patch.object(app,'SUPABASE',self.fake))
        # Real storage adapter + real SQLite commerce transactions, isolated from
        # production RPC. Catalog does not depend on the fake storage service.
        self.stack.enter_context(mock.patch.object(app.commerce.store,'app',SimpleNamespace(USE_SUPABASE=False,SAVE_DIR=app.SAVE_DIR)))
        self.stack.enter_context(mock.patch('commerce_patch._shop',return_value=self.shop))
        # Auto-print has its own full safety suite. This fake cloud implements
        # storage only; assert the existing post-commit handoff is still called.
        self.handoff=self.stack.enter_context(mock.patch.object(app.print_center,'enqueue_auto'))

    def test_ordinary_photo_and_legacy_template_do_not_enter_new_contract(self):
        ordinary={'version':'5.3.1','objects':[{'type':'image','role':'photo','src':fixture.PNG}]}
        legacy={'template_version':2,'objects':[{'type':'textbox','text':'ordinary','fontFamily':'Arial'},{'type':'image','role':'slot-photo','src':fixture.PNG,'slotId':'legacy-slot'}]}
        with mock.patch.object(editable,'snapshot') as snapshot,mock.patch('multilayer_templates.verify_design') as verify,mock.patch('multilayer_templates.seal') as seal,mock.patch.object(design_sources,'receipt') as receipt:
            for design in ({},None,ordinary,legacy):
                self.assertFalse(editable.configured(design))
                self.assertIs(design_sources.identity(app,design),design)
                response=self.fx.client.post('/api/create_order',json=self.fx.body(design))
                self.assertEqual(response.status_code,200,response.json)
                order=app.commerce.store.order(response.json['order_id'])
                self.assertEqual(order['design_json'],design)
                self.assertTrue(order['print_path'].endswith('/print.png'))
                self.assertIn(order['print_path'],self.bucket.files)
            snapshot.assert_not_called();verify.assert_not_called();seal.assert_not_called();receipt.assert_not_called()
        self.assertEqual(self.handoff.call_count,4)
        self.assertEqual(self.fx.fixture.fake.calls,[])
        self.assertFalse(any(path.startswith('design-cleanup/') for path in self.bucket.files))
        self.assertTrue(self.bucket.uploads)
        self.assertEqual({mime for _,mime in self.bucket.uploads},{'image/png'})

    def test_real_bucket_rejects_json_so_cleanup_must_be_a_valid_png(self):
        with self.assertRaises(StorageApiError):app.upload_private_bytes('bad.json',b'{}','application/json')
        path=design_sources.cleanup_plan(app,'orphan-123')
        self.assertTrue(path.endswith('.png'))
        with Image.open(io.BytesIO(self.bucket.files[path])) as marker:
            self.assertEqual(marker.size,(1,1));self.assertEqual(marker.format,'PNG')
            self.assertEqual(json.loads(marker.info['benfuwan_cleanup']),{'order_id':'orphan-123'})

    def test_ordinary_retry_keeps_one_order_and_does_not_reupload(self):
        payload=self.fx.body({'objects':[{'type':'image','role':'photo','src':fixture.PNG}]})
        before=len(app.commerce.store.local_orders())
        first=self.fx.client.post('/api/create_order',json=payload)
        self.assertEqual(first.status_code,200,first.json)
        uploads=len(self.bucket.uploads)
        repeat=self.fx.client.post('/api/create_order',json=payload)
        self.assertEqual(repeat.status_code,200,repeat.json)
        self.assertEqual(first.json['order_id'],repeat.json['order_id'])
        self.assertEqual(len(app.commerce.store.local_orders()),before+1)
        self.assertEqual(len(self.bucket.uploads),uploads)

    def test_expired_cleanup_reads_new_png_and_legacy_json(self):
        now=int(time.time())+2*86400
        marker=design_sources.cleanup_plan(app,'orphan-123')
        old=f'design-cleanup/{int(time.time())-100}/orphan-456-abc.json'
        self.bucket.files[old]=json.dumps({'order_id':'orphan-456'}).encode()
        for identity in ('orphan-123','orphan-456'):
            self.bucket.files[f'orders/{identity}/print.png']=fixture.image()
            self.bucket.files[f'orders/{identity}/preview.png']=fixture.image()
            self.bucket.files[f'orders/{identity}/sources/source.png']=fixture.image()
        with mock.patch.object(design_sources,'existing_order',return_value=None):design_sources.cleanup_pending(app,now)
        self.assertEqual(self.bucket.files,{})

    def test_cleanup_keeps_committed_order_artwork(self):
        path=design_sources.cleanup_plan(app,'committed-123')
        self.bucket.files['orders/committed-123/print.png']=fixture.image()
        with mock.patch.object(design_sources,'existing_order',return_value={'id':'committed-123'}):design_sources.cleanup_pending(app,int(time.time())+2*86400)
        self.assertNotIn(path,self.bucket.files)
        self.assertIn('orders/committed-123/print.png',self.bucket.files)

    def test_marker_storage_failure_still_fails_closed(self):
        with mock.patch.object(self.bucket,'upload',side_effect=TimeoutError('storage unavailable')),mock.patch.object(app.commerce,'create') as create:
            response=self.fx.client.post('/api/create_order',json=self.fx.body({}))
        self.assertEqual(response.status_code,500);create.assert_not_called()

    def test_failed_ordinary_commerce_rolls_back_artwork_and_marker(self):
        from commerce_store import CommerceError
        with mock.patch.object(app.commerce,'create',side_effect=CommerceError('NO_STOCK','stock unavailable')):
            response=self.fx.client.post('/api/create_order',json=self.fx.body({}))
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.bucket.files,{})
        self.handoff.assert_not_called()

    def test_editable_source_contract_still_validates_and_snapshots(self):
        uploaded=self.fx.upload(self.fx.draft)
        with mock.patch.object(editable,'public_image',return_value=fixture.mask()):
            response=self.fx.client.post('/api/create_order',json=self.fx.body(uploaded))
        self.assertEqual(response.status_code,200,response.json)
        order=app.commerce.store.order(response.json['order_id'])
        self.assertEqual(order['design_json']['render_contract_version'],editable.VERSION)
        self.assertIn(order['design_json']['objects'][0]['src'],self.bucket.files)


if __name__=='__main__':unittest.main(verbosity=2)
