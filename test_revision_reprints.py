"""Full-layer V2 uses immutable historical artwork and fake vendor dispatch only."""
import copy
import io
import os
import unittest
from unittest import mock
from PIL import Image
import test_order_designs as fixtures
from pixel_order_designs import sha

app=fixtures.app
HEAD={'X-Order-Design':'1'}


class RevisionReprintTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.OrderDesignTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.fx.draft['objects'][1]['styles']=[]  # Fabric toObject() representation.
        self.client=self.fx.client

    def prepare(self, product='phone_case'):
        shop=app.cloud_get_json('shop_data',app.DATA_FILE,app.DEFAULT_SHOP_DATA)
        model=shop['models'][0];model['product_type']=product;model['direct_style_id']=self.fx.style;shop['styles'][0]['product_type']=product
        if product=='camera_film':
            shop['styles'][0].update(colors=[],model_colors={},price=1)
            model['case_profiles'][self.fx.style].update(print_w=41.1,print_h=21.7)
            self.fx.draft['production'].update(printW=41.1,printH=21.7)
        app.local_save_json(app.DATA_FILE,shop)
        import security_perf
        security_perf._CACHE.clear()
        order=self.fx.create_original()
        job=app.print_center.prepare(order,'revision-original-'+order)
        job=app.print_center.store.patch_job(job['id'],{'state':'COMPLETED'})
        return order,job

    def revised(self, order):
        work=self.fx.open(order);candidate=self.fx.candidate(work)
        candidate['objects'][0]['left']+=5
        result=self.fx.save(order,work,candidate)
        self.assertEqual(result.status_code,200,result.json)
        return result.json

    def payload(self, saved):
        return {'version':saved['version'],'hash':saved['hash'],'confirm':'compared-v1-v2','reason':'僅移動一張貼紙','costCents':1250}

    def test_real_720_two_products_private_compare_immutable_v1_and_fake_dispatch(self):
        for product in ('phone_case','camera_film'):
            with self.subTest(product=product):
                order,source=self.prepare(product);original=copy.deepcopy(app.commerce.store.order(order));finance=copy.deepcopy(app.commerce.read())
                saved=self.revised(order);rows=app.order_designs.rows(order);proof=rows[-1]['document']['revisionPrint']
                self.assertTrue(proof.get('profile'),proof)
                self.assertEqual(proof['baseSha'],source['artwork_sha256'])
                self.assertNotEqual(proof['outputSha'],proof['baseSha'])
                self.assertEqual(rows[0]['document']['objects'][1],rows[-1]['document']['objects'][1])
                root=f'/api/admin/order-design/{order}/revision';payload=self.payload(saved)
                reviewed=self.client.post(root+'/review',headers=HEAD,json=payload)
                self.assertEqual(reviewed.status_code,200,reviewed.json)
                self.assertFalse(reviewed.json['enabled'])
                for key in ('basePath','outputPath'):
                    url=reviewed.json['design'][key]
                    self.assertEqual(app.app.test_client().get(url).status_code,401)
                    raw=self.client.get(url).data;im=Image.open(io.BytesIO(raw))
                    self.assertEqual(im.size,tuple(proof['size']));self.assertAlmostEqual(im.info['dpi'][0],720,delta=.1)
                    self.assertEqual(sha(raw),proof['baseSha' if key=='basePath' else 'outputSha'])
                self.assertEqual(self.client.post(root+'/confirm',headers=HEAD,json=payload).status_code,422)
                with mock.patch.dict(os.environ,{'ORDER_PIXEL_REPRINT_ENABLED':'true'}):
                    result=self.client.post(root+'/confirm',headers=HEAD,json=payload);self.assertEqual(result.status_code,200,result.json)
                    again=self.client.post(root+'/confirm',headers=HEAD,json=payload);self.assertEqual(again.json['jobId'],result.json['jobId'])
                    self.fx.fixture.fake.responses['/api/Device/receiveTask']={'code':0,'data':{'taskid':'revision-'+order,'status':0}}
                    calls=len(self.fx.fixture.fake.calls)
                    for _ in range(2):
                        sent=self.client.post(root+'/send',headers=HEAD,json=payload);self.assertEqual(sent.status_code,200,sent.json)
                    self.assertEqual(len(self.fx.fixture.fake.calls),calls+1)
                self.assertEqual(app.print_center.store.job(source['id']),source)
                self.assertEqual(app.commerce.store.order(order),original);self.assertEqual(app.commerce.read(),finance)
                reopened=self.fx.open(order);self.assertEqual(reopened['version'],2);self.assertEqual(reopened['hash'],saved['hash'])

    def test_no_historical_profile_preserves_draft_but_rejects_forged_proof(self):
        order=self.fx.create_original();work=self.fx.open(order);candidate=self.fx.candidate(work)
        candidate['revisionPrint']={'mode':'layered-v1','profile':{'sourceJobId':'forged'},'outputPath':'other-order.png'}
        result=self.fx.save(order,work,candidate);self.assertEqual(result.status_code,200,result.json)
        proof=app.order_designs.rows(order)[-1]['document']['revisionPrint'];self.assertIsNone(proof['profile'])
        self.assertNotIn('outputPath',proof)
        root=f'/api/admin/order-design/{order}/revision'
        with mock.patch.dict(os.environ,{'ORDER_PIXEL_REPRINT_ENABLED':'true'}):
            self.assertEqual(self.client.post(root+'/review',headers=HEAD,json=self.payload(result.json)).status_code,422)
            self.assertEqual(self.client.post(root+'/confirm',headers=HEAD,json=self.payload(result.json)).status_code,422)
        self.assertEqual(self.fx.fixture.fake.calls,[])

    def test_multilayer_archived_revision_reseals_only_validated_frozen_policy(self):
        import test_multilayer_templates as templates
        layered=templates.MultilayerTests();layered.setUp();self.addCleanup(layered.doCleanups)
        design=layered.design();design['orderDesignVersion']=1
        design['objects'][1]['styles']=[]
        order=layered.create(design).json['order_id']
        source=app.print_center.prepare(order,'revision-multilayer-original-'+order)
        source=app.print_center.store.patch_job(source['id'],{'state':'COMPLETED'})
        original=copy.deepcopy(app.commerce.store.order(order));finance=copy.deepcopy(app.commerce.read())
        work=self.fx.open(order,layered.client)
        v1=copy.deepcopy(app.order_designs.rows(order)[0])
        self.assertEqual(v1['document']['layer_contract_version'],'multilayer-v1')
        self.assertEqual(len(v1['document']['objects']),30)
        candidate=self.fx.candidate(work,layered.client)
        forged=copy.deepcopy(candidate);forged['objects'][0]['locked']=False;forged['objects'][0]['canMove']=True
        denied=self.fx.save(order,work,forged,layered.client)
        self.assertEqual(denied.status_code,422,denied.json)
        self.assertEqual(app.order_designs.rows(order),[v1])
        # Remove today's template entirely: archived V1 permissions and assets
        # must remain sufficient to render and verify an allowed sticker move.
        app.local_save_json(app.TEMPLATES_FILE,{'templates':[],'categories':[]})
        moved=27
        self.assertEqual(candidate['objects'][moved]['type'],'image')
        self.assertTrue(candidate['objects'][moved]['canMove'])
        candidate['objects'][moved]['left']+=40
        candidate['objects'][moved]['normalizedGeometry']['x']+=.2
        saved=self.fx.save(order,work,candidate,layered.client)
        self.assertEqual(saved.status_code,200,saved.json)
        rows=app.order_designs.rows(order);self.assertEqual(rows[0],v1)
        proof=rows[-1]['document']['revisionPrint']
        self.assertTrue(proof.get('profile'),proof)
        self.assertEqual(proof['baseSha'],source['artwork_sha256'])
        self.assertNotEqual(proof['outputSha'],proof['baseSha'])
        for index,(before,after) in enumerate(zip(v1['document']['objects'],rows[-1]['document']['objects'])):
            if index!=moved:
                # Saving intentionally removes obsolete public URL hints; private
                # src, all visual properties, identity and permissions stay exact.
                retained={k:v for k,v in before.items() if k!='publicSrc'}
                self.assertEqual(retained,after,('unchanged layer',index))
        raw=app.print_center._download_artwork(proof['outputPath'])
        output=Image.open(io.BytesIO(raw))
        self.assertEqual(output.size,(2030,4241));self.assertAlmostEqual(output.info['dpi'][0],720,delta=.1)
        self.assertEqual(sha(raw),proof['outputSha'])
        self.assertEqual(app.print_center.store.job(source['id']),source)
        self.assertEqual(app.commerce.store.order(order),original);self.assertEqual(app.commerce.read(),finance)
        self.assertEqual(layered.fx.fixture.fake.calls,[])

    def test_untrusted_archive_and_changed_historical_artwork_fail_closed(self):
        from revision_artwork import render_revision
        order,job=self.prepare('camera_film');work=self.fx.open(order)
        bad=copy.deepcopy(app.order_designs.rows(order)[0]['document']);bad['objects'][0]['src']='order-design_foreign_bad.png'
        with self.assertRaises(ValueError):render_revision(app,order,bad)
        with app.print_center.store.connection(True) as db:db.execute('UPDATE print_jobs SET artwork_sha256=? WHERE id=?',('0'*64,job['id']))
        result=self.revised(order);proof=app.order_designs.rows(order)[-1]['document']['revisionPrint']
        self.assertIsNone(proof['profile']);self.assertIn('雜湊',proof['reason'])
        self.assertEqual(result['version'],2);self.assertEqual(self.fx.fixture.fake.calls,[])

    def test_optional_proof_outage_preserves_validated_draft_without_dispatch(self):
        order=self.fx.create_original();work=self.fx.open(order);candidate=self.fx.candidate(work)
        candidate['objects'][0]['left']+=4
        with mock.patch.object(app.print_center.store,'jobs_for_order',side_effect=RuntimeError('storage token must not leak')):
            result=self.fx.save(order,work,candidate)
        self.assertEqual(result.status_code,200,result.json)
        retry=self.fx.save(order,work,candidate)
        self.assertEqual(retry.status_code,200,retry.json);self.assertEqual(retry.json['hash'],result.json['hash'])
        proof=app.order_designs.rows(order)[-1]['document']['revisionPrint']
        self.assertIsNone(proof['profile']);self.assertNotIn('token',proof['reason'])
        with mock.patch.dict(os.environ,{'ORDER_PIXEL_REPRINT_ENABLED':'true'}):
            response=self.client.post(f'/api/admin/order-design/{order}/revision/confirm',headers=HEAD,json=self.payload(result.json))
            self.assertEqual(response.status_code,422)
        self.assertEqual(self.fx.fixture.fake.calls,[])

    def test_active_task_or_unknown_blocks_revision_confirmation(self):
        order,source=self.prepare('camera_film');saved=self.revised(order)
        with mock.patch.dict(os.environ,{'ORDER_PIXEL_REPRINT_ENABLED':'true'}):
            for state in ('PREPARED','QUEUED','UNKNOWN'):
                app.print_center.store.patch_job(source['id'],{'state':state})
                response=self.client.post(f'/api/admin/order-design/{order}/revision/confirm',headers=HEAD,json=self.payload(saved))
                self.assertEqual(response.status_code,422,response.json)
        self.assertEqual(self.fx.fixture.fake.calls,[])

    def test_approval_cannot_send_after_competing_task_or_newer_version(self):
        order,source=self.prepare('camera_film');saved=self.revised(order);payload=self.payload(saved)
        root=f'/api/admin/order-design/{order}/revision'
        with mock.patch.dict(os.environ,{'ORDER_PIXEL_REPRINT_ENABLED':'true'}):
            confirmed=self.client.post(root+'/confirm',headers=HEAD,json=payload)
            self.assertEqual(confirmed.status_code,200,confirmed.json)
            for state in ('QUEUED','UNKNOWN'):
                app.print_center.store.patch_job(source['id'],{'state':state})
                response=self.client.post(root+'/send',headers=HEAD,json=payload)
                self.assertGreaterEqual(response.status_code,400,response.json)
            app.print_center.store.patch_job(source['id'],{'state':'COMPLETED'})
            newer=self.revised(order);self.assertEqual(newer['version'],3)
            self.assertEqual(self.client.post(root+'/send',headers=HEAD,json=payload).status_code,422)
        self.assertEqual(self.fx.fixture.fake.calls,[])


if __name__=='__main__':unittest.main(verbosity=2)
