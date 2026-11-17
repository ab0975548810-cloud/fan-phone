import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import test_order_designs as fx
from legacy_order_designs import classify, verified
from order_designs import digest, asset_paths

class LegacyTests(unittest.TestCase):
    def setUp(self):
        self.fx=fx.OrderDesignTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)

    def test_categories_and_unauthorized(self):
        for design in (None,{'objects':[{'type':'image'}]},{'objects':[{'type':'image','src':'blob:lost'}]}):
            self.assertEqual(classify({'design_json':design})[0],'unrecoverable')
        self.assertEqual(classify({'design_json':{'objects':[{'type':'image','src':'https://example.invalid/a.png'}]}})[0],'needs_evidence')
        client=fx.app.app.test_client()
        self.assertEqual(client.get('/api/admin/order-design/unknown/assessment').status_code,401)
        self.assertEqual(client.post('/api/admin/order-design/unknown/remake').status_code,401)

    def test_history_hash_geometry_and_exact_output_gate(self):
        order_id=self.fx.create_original();order=fx.app.commerce.store.order(order_id)
        original=copy.deepcopy(order);full=order['design_json']
        _,png,_=fx.fx.editable.render(fx.app,order,{'width_mm':full['production']['printW'],'height_mm':full['production']['printH']},fx.app.print_center._download_artwork)
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/order_id;folder.mkdir()
            mapping={p:str(i)+'.png' for i,p in enumerate(sorted(asset_paths(full)))}
            assets={}
            for source,name in mapping.items():
                raw=fx.app.print_center._download_artwork(source);(folder/name).write_bytes(raw);assets[name]=hashlib.sha256(raw).hexdigest()
            legacy=copy.deepcopy(full)
            metadata={k:legacy.pop(k) for k in ('logicalCanvas','production','editorContext','fontHashes')}
            legacy.pop('render_contract_version');legacy.pop('orderDesignVersion')
            metadata['production']['maskPath']=mapping[metadata['production']['maskPath']]
            metadata['editorContext']['previewPath']=mapping[metadata['editorContext']['previewPath']]
            order['design_json']=legacy
            manifest={**metadata,'orderId':order_id,'originalDesignHash':digest(legacy),'originalPrintHash':hashlib.sha256(png).hexdigest(),'archiveReference':'isolated-backup','archivedAt':'2026-01-01','sourceMap':mapping,'assets':assets}
            path=folder/'manifest.json';path.write_text(json.dumps(manifest),'utf-8')
            with mock.patch.dict(os.environ,{'ORDER_DESIGN_HISTORY_DIR':root}),mock.patch('legacy_order_designs.read',return_value=png):
                result,_=verified(order,fx.app);self.assertEqual(result['legacyRecovery']['verification'],'rgba-exact-720dpi')
                for key,value in (('archiveReference',''),('orderId','another-order'),('originalDesignHash','0'*64),('originalPrintHash','0'*64),('sourceMap',{}),('assets',{})):
                    changed=copy.deepcopy(manifest);changed[key]=value;path.write_text(json.dumps(changed),'utf-8')
                    with self.subTest(key=key),self.assertRaises(ValueError):verified(order,fx.app)
                manifest['logicalCanvas']['width']+=20;path.write_text(json.dumps(manifest),'utf-8')
                with self.assertRaises(ValueError):verified(order,fx.app)
            self.assertEqual(fx.app.commerce.store.order(order_id),original)
            self.assertEqual(self.fx.fixture.fake.calls,[])

    def test_remake_is_explicit_separate_and_does_not_change_commerce(self):
        order_id=self.fx.create() # old structured order without the new editor context
        original=fx.app.commerce.store.order(order_id);finance=copy.deepcopy(fx.app.commerce.store.read())
        client=self.fx.client;url=f'/api/admin/order-design/{order_id}/remake'
        self.assertEqual(client.post(url,headers=fx.HEADERS,json={}).status_code,422)
        with mock.patch('editable_stickers.public_image',return_value=fx.fx.mask()):
            response=client.post(url,headers=fx.HEADERS,json={'confirm':'new-design-current-profile'})
        self.assertEqual(response.status_code,200,response.json)
        versions=fx.app.order_designs.rows(order_id)
        self.assertEqual(versions[0]['document']['design_json'],original['design_json'])
        self.assertEqual(versions[1]['document']['objects'],[])
        self.assertTrue(versions[1]['document']['remakeNotice'])
        self.assertEqual(self.fx.open(order_id)['version'],2)
        self.assertEqual(fx.app.commerce.store.order(order_id),original)
        self.assertEqual(fx.app.commerce.store.read(),finance)
        self.assertEqual(self.fx.fixture.fake.calls,[])

    def test_remake_rejects_competing_original_without_appending_v2(self):
        order_id=self.fx.create();store=fx.app.order_designs;append=store.append
        def racing_append(order,expected,document,actor,request):
            if expected==0:
                append(order,0,{'concurrentOriginal':True},'other-admin','original')
            return append(order,expected,document,actor,request)
        with mock.patch.object(store,'append',side_effect=racing_append),mock.patch('editable_stickers.public_image',return_value=fx.fx.mask()):
            response=self.fx.client.post(f'/api/admin/order-design/{order_id}/remake',headers=fx.HEADERS,json={'confirm':'new-design-current-profile'})
        self.assertEqual(response.status_code,422,response.json)
        self.assertEqual(len(store.rows(order_id)),1)
        self.assertTrue(store.rows(order_id)[0]['document']['concurrentOriginal'])

if __name__=='__main__':unittest.main(verbosity=2)
