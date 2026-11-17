"""Isolated order design version, asset authorization and unchanged commerce tests."""
import copy
import io
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock
import test_editable_stickers as fx
from order_designs import Revisions, check_restore

app=fx.app
HEADERS={'X-Order-Design':'1'}


class OrderDesignTests(fx.EditableTests):
    # Reuse fixture setup/upload; run only this feature's test cases here.
    def create_original(self):
        self.draft['orderDesignVersion']=1
        return self.create()

    def open(self,order_id,client=None):
        r=(client or self.client).post(f'/api/admin/order-design/{order_id}/open',headers=HEADERS)
        self.assertEqual(r.status_code,200,r.json)
        return r.json

    def candidate(self,work,client=None):
        design=copy.deepcopy(work['design'])
        for o in fx.editable.nodes(design):
            if o['type']=='image':
                raw=(client or self.client).get(o['src']).data
                o['src']='data:image/png;base64,'+fx.base64.b64encode(raw).decode()
        return self.upload(design,client)

    def save(self,order,work,design,client=None):
        return (client or self.client).post(f'/api/admin/order-design/{order}/save',headers=HEADERS,json={'work':work['work'],'design':design})

    def test_revision_retention_cas_restart_and_no_business_mutation(self):
        order=self.create_original();original=app.commerce.store.order(order)
        commerce=copy.deepcopy(app.commerce.store.read())
        work=self.open(order);other=self.open(order)
        design=self.candidate(work);design['objects'][0]['left']+=3
        result=self.save(order,work,design);self.assertEqual(result.status_code,200,result.json)
        self.assertEqual(result.json['version'],2)
        self.assertEqual(self.save(order,work,design).status_code,200)  # lost response retry
        self.assertEqual(self.save(order,other,design).status_code,409)
        versions=Revisions(app).rows(order);self.assertEqual(len(versions),2)
        self.assertEqual(versions[0]['document']['objects'][0]['left'],original['design_json']['objects'][0]['left'])
        self.assertEqual(versions[0]['document']['objects'][1],versions[1]['document']['objects'][1])
        self.assertEqual(app.commerce.store.order(order),original)
        self.assertEqual(app.commerce.store.read(),commerce)
        self.assertEqual(self.fixture.fake.calls,[])
        client=app.app.test_client()
        with client.session_transaction() as s:s['logged_in']=True
        reopened=self.open(order,client);self.assertEqual(reopened['version'],2)
        self.assertEqual(reopened['design']['objects'][0]['left'],design['objects'][0]['left'])
        self.assertEqual(self.save(order,work,design,client).status_code,422)

    def test_private_assets_and_forged_work_are_denied(self):
        order=self.create_original();work=self.open(order);anonymous=app.app.test_client()
        url=work['design']['objects'][0]['src']
        self.assertEqual(anonymous.get(url).status_code,401)
        self.assertEqual(anonymous.get('/admin/order-design/'+order).status_code,401)
        self.assertEqual(anonymous.post(f'/api/admin/order-design/{order}/open',headers=HEADERS).status_code,401)
        self.assertEqual(self.client.post(f'/api/admin/order-design/{order}/open').status_code,403)
        r=self.client.get(url);self.assertEqual(r.status_code,200)
        self.assertIn('no-store',r.headers['Cache-Control'])
        self.assertEqual(self.client.get(url.replace(order,'foreign')).status_code,404)
        self.assertEqual(self.client.post(f'/api/admin/order-design/{order}/save',headers=HEADERS,json={'work':'forged'}).status_code,422)

    def test_legacy_incomplete_missing_sources_and_font_versions_fail_closed(self):
        for bad in (None,{}, {'manifestOnly':True}, {'truncated':True}):
            with self.assertRaises(ValueError):check_restore(bad)
        order=self.create_original();original=app.commerce.store.order(order)
        Path(app.SAVE_DIR,original['design_json']['objects'][0]['src']).unlink()
        r=self.client.post(f'/api/admin/order-design/{order}/open',headers=HEADERS)
        self.assertEqual(r.status_code,422,r.json)
        self.assertEqual(app.order_designs.rows(order),[])
        self.assertEqual(app.commerce.store.order(order),original)

    def test_plain_photo_sticker_text_contract_and_cleanup_survival(self):
        self.draft['orderDesignVersion']=1
        self.draft['objects'][0]['role']='photo'
        for o in self.draft['objects']:
            o.pop('editableStickerId',None);o.pop('editableStickerInstanceId',None)
        self.draft['objects'][1]['role']='text'
        order=self.create();work=self.open(order)
        fx.design_sources.cleanup_expired(app,now=2**40)
        self.assertEqual(self.client.get(work['design']['objects'][0]['src']).status_code,200)
        self.assertEqual(self.open(order)['version'],1)

    def test_template_policy_and_normalized_geometry_cannot_be_forged(self):
        import test_multilayer_templates as multi
        mf=multi.MultilayerTests();mf.setUp();self.addCleanup(mf.doCleanups)
        design=mf.design();design['orderDesignVersion']=1
        order=mf.create(design).json['order_id'];work=self.open(order,mf.client)
        candidate=self.candidate(work,mf.client)
        for key,value in (('locked',False),('angle',15),('fill','#000000'),('src','forged')):
            bad=copy.deepcopy(candidate);bad['objects'][0][key]=value
            self.assertEqual(self.save(order,work,bad,mf.client).status_code,422)
        bad=copy.deepcopy(candidate);bad['objects'][0]['normalizedGeometry']['x']=.1
        self.assertEqual(self.save(order,work,bad,mf.client).status_code,422)
        bad=copy.deepcopy(candidate);bad['objects'].pop(0)
        self.assertEqual(self.save(order,work,bad,mf.client).status_code,422)
        self.assertEqual(len(app.order_designs.rows(order)),1)
        candidate['objects'][3]['left']+=2
        candidate['objects'][3]['normalizedGeometry']['x']+=.01
        self.assertEqual(self.save(order,work,candidate,mf.client).status_code,200)

    def test_concurrent_version_append_only_one_winner(self):
        order=self.create_original();self.open(order)
        document=app.order_designs.rows(order)[0]['document']
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda n:Revisions(app).append(order,1,document,'fixture','save-'+str(n)),range(2)))
        self.assertEqual(sum(r['ok'] for r in results),1)
        self.assertEqual(len(app.order_designs.rows(order)),2)


# Avoid rerunning the inherited renderer suite in this module's entry point.
if __name__=='__main__':
    suite=unittest.TestSuite(OrderDesignTests(name) for name in OrderDesignTests.__dict__ if name.startswith('test_'))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
