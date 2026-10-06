"""Real #71 source snapshots and 720 DPI renderer; local DB/fake vendor only."""
import base64
import copy
import io
import json
import unittest
import uuid
from pathlib import Path
from unittest import mock
from PIL import Image
import test_editable_stickers as fixture
import multilayer_templates as multi
import editable_stickers as editable

app=fixture.app


def layer(index,kind='rect',locked=False):
    identity='layer-'+str(index)
    item={'type':kind,'role':'template-bg' if locked else 'template-text' if kind=='textbox' else 'template-sticker',
          'layerId':identity,'templateLayerId':identity,'layerInstanceId':str(uuid.uuid4()),'layerName':'背景' if locked else '圖層 '+str(index),'assetId':identity,
          'left':100,'top':200,'width':40,'height':30,'originX':'center','originY':'center','scaleX':1,'scaleY':1,'angle':0,'opacity':1,'flipX':False,'flipY':False,'visible':True,'strokeWidth':0,'fill':'#ffc4dd','zIndex':index,
          'normalizedGeometry':{'x':.5,'y':.5,'width':.2,'height':.075},**{flag:locked if flag=='locked' else not locked for flag in multi.FLAGS}}
    if locked:item.update(width=200,height=400,fill='#ffffff',isTplBg=True,normalizedGeometry={'x':.5,'y':.5,'width':1,'height':1})
    if kind=='image':item.update(src='/static/multi-layer.png',publicSrc='/static/multi-layer.png',width=512,height=256,sourceSize={'width':512,'height':256})
    if kind=='textbox':item.update(text='模板中文\nEditable text',fontFamily='jf-openhuninn',fontSize=24,fontWeight='400',fontStyle='normal',textAlign='center',charSpacing=0,lineHeight=1.2,stroke=None)
    return item


def template(model,style,count=30):
    items=[layer(0,locked=True)]+[layer(i,'textbox' if i==1 else 'image' if i%3==0 else 'rect') for i in range(1,count)]
    return {'id':'multilayer-fixture','name':'30-layer template','category':'熱門','template_version':3,'layer_contract_version':multi.VERSION,
            'model_id':'*','universal':True,'reference_model_id':model,'reference_style_id':style,'source_print_w':71.63,'source_print_h':149.61,'source_canvas_w':200,'source_canvas_h':400,
            'objects_json':{'version':'5.3.1','background':'transparent','layer_contract_version':multi.VERSION,'sourceCanvas':{'width':200,'height':400},'objects':items},'slots':[]}


class MultilayerTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixture.EditableTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups)
        self.client=self.fx.client;self.model=self.fx.model;self.style=self.fx.style
        self.saved=app.TEMPLATES_FILE;app.TEMPLATES_FILE=str(Path(self.fx.fixture.tmp.name)/'templates.json');self.addCleanup(setattr,app,'TEMPLATES_FILE',self.saved)
        self.tpl=template(self.model,self.style)
        with mock.patch('editable_stickers.public_image',return_value=fixture.image()):multi.prepare_template(app,self.tpl)
        app.local_save_json(app.TEMPLATES_FILE,{'templates':[self.tpl],'categories':['全部','熱門']})
        self.contract=self.client.get('/api/template_contract/'+self.tpl['id'],query_string={'model_id':self.model,'style_id':self.style}).json
        self.assertEqual(self.contract['status'],'success',self.contract)

    def design(self):
        result=fixture.design(self.model,self.style);result['objects']=copy.deepcopy(self.tpl['objects_json']['objects']);result['layer_contract_version']=multi.VERSION;result['templateBinding']=self.contract['binding']
        for item in result['objects']:
            item['templateApplicationId']=result['templateBinding']['applicationId'];item['layerInstanceId']=item['templateApplicationId']+':'+item['layerId']
            if item['type']=='image':item['src']='data:image/png;base64,'+base64.b64encode(fixture.image()).decode()
        return result

    def create(self,design=None,expected=200):
        body=self.fx.body(self.fx.upload(design or self.design()))
        with mock.patch('editable_stickers.public_image',return_value=fixture.mask()):response=self.client.post('/api/create_order',json=body)
        self.assertEqual(response.status_code,expected,response.json)
        return response

    def test_template_authoring_auth_cas_and_legacy(self):
        anon=app.app.test_client();self.assertEqual(anon.post('/api/admin/save_templates',json={}).status_code,401)
        _,version=app.cloud_get_json_versioned('templates',app.TEMPLATES_FILE,app.DEFAULT_TEMPLATES)
        body={'data':{'templates':[self.tpl,{'id':'old','template_version':1,'thumb_url':'old.png','slots':[]}],'categories':['全部']},'expected_version':version}
        with mock.patch('editable_stickers.public_image',return_value=fixture.image()):
            response=self.client.post('/api/admin/save_templates',json=body)
            self.assertEqual(response.status_code,200,response.json)
            self.assertEqual(self.client.post('/api/admin/save_templates',json=body).status_code,409)
        records=app.cloud_get_json('templates',app.TEMPLATES_FILE,app.DEFAULT_TEMPLATES)['templates']
        self.assertEqual(records[1],body['data']['templates'][1]);self.assertEqual(len(records[0]['objects_json']['objects']),30)
        self.assertTrue(records[0]['objects_json']['objects'][3]['assetPixelHash'])

    def test_normalized_and_unique_layer_contract(self):
        for change in ('geometry','identity','locked'):
            bad=copy.deepcopy(self.tpl)
            if change=='geometry':bad['objects_json']['objects'][1]['normalizedGeometry']['width']=1.2
            if change=='identity':bad['objects_json']['objects'][1]['layerId']='layer-0'
            if change=='locked':bad['objects_json']['objects'][0]['canMove']=True
            with mock.patch('editable_stickers.public_image',return_value=fixture.image()),self.assertRaises(ValueError):multi.prepare_template(app,bad)

    def test_locked_tamper_delete_duplicate_and_order_are_rejected(self):
        for change in ('permission','position','content','delete','duplicate','ordering'):
            data=self.design();bg=data['objects'][0]
            if change=='permission':bg['locked']=False;bg['canMove']=True
            if change=='position':bg['normalizedGeometry']['x']=.1
            if change=='content':bg['fill']='#000000'
            if change=='delete':data['objects'].pop(0)
            if change=='duplicate':extra=copy.deepcopy(bg);extra['layerInstanceId']=str(uuid.uuid4());extra['duplicateOf']=bg['layerInstanceId'];data['objects'].append(extra)
            if change=='ordering':bg['zIndex']=99
            if change!='ordering':
                for index,item in enumerate(data['objects']):item['zIndex']=index
            self.create(data,400)

    def test_locked_skew_and_compositing_cannot_change_artwork(self):
        for field,value in (('skewX',30),('skewY',30),('globalCompositeOperation','destination-out')):
            data=self.design();data['objects'][0][field]=value
            with self.client.session_transaction() as session:identity=session['_bf_client_id']
            with app.app.test_request_context('/api/create_order'):
                app.session['_bf_client_id']=identity
                with self.assertRaisesRegex(ValueError,'固定圖層內容'):multi.verify_design(app,data)

    def test_shared_authoring_download_cache_does_not_bypass_template_pixel_budget(self):
        data=copy.deepcopy(self.tpl);cache={};raw=fixture.image()
        for index in (3,6,9):
            src='/static/budget-'+str(index)+'.png';data['objects_json']['objects'][index]['src']=src
            cache[src]=(raw,multi.image_digest(raw)[0],(6000,5000))
        with mock.patch('editable_stickers.public_image',return_value=raw),self.assertRaisesRegex(ValueError,'總量過大'):
            multi.prepare_template(app,data,cache)

    def test_binding_owner_and_updated_template_fail_closed(self):
        uploaded=self.fx.upload(self.design());other=app.app.test_client()
        with mock.patch('editable_stickers.public_image',return_value=fixture.mask()):self.assertEqual(other.post('/api/create_order',json=self.fx.body(uploaded)).status_code,400)
        changed=copy.deepcopy(self.tpl);changed['name']='updated'
        app.local_save_json(app.TEMPLATES_FILE,{'templates':[changed],'categories':['全部']});self.create(expected=400)

    def test_unlocked_duplicate_has_unique_instance_and_same_source_identity(self):
        data=self.design();copy_=copy.deepcopy(data['objects'][1]);copy_['duplicateOf']=copy_['layerInstanceId'];copy_['layerInstanceId']=str(uuid.uuid4());copy_['normalizedGeometry']['x']=.3;data['objects'].append(copy_)
        for i,item in enumerate(data['objects']):item['zIndex']=i
        order=app.commerce.store.order(self.create(data).json['order_id'])
        texts=[o for o in order['design_json']['objects'] if o['templateLayerId']=='layer-1']
        self.assertEqual(len(texts),2);self.assertNotEqual(texts[0]['layerInstanceId'],texts[1]['layerInstanceId'])

    def test_thirty_layers_private_sources_and_real_720_dpi_rebuild(self):
        order_id=self.create().json['order_id'];order=app.commerce.store.order(order_id)
        self.assertEqual(len(order['design_json']['objects']),30);self.assertTrue(order['design_json']['layerSeal'])
        self.assertNotIn('base64',json.dumps(order['design_json']))
        job=app.print_center.prepare(order_id,'multilayer-render-test');raw=app.print_center._download_artwork(job['artwork_path']);image=Image.open(io.BytesIO(raw))
        self.assertEqual(image.size,(2030,4241));self.assertAlmostEqual(image.info['dpi'][0],720,delta=.05)
        self.assertNotEqual(job['artwork_path'],order['print_path']);self.assertEqual(self.fx.fixture.fake.calls,[])

    def test_historical_contract_does_not_depend_on_today_template(self):
        order=app.commerce.store.order(self.create().json['order_id']);app.local_save_json(app.TEMPLATES_FILE,{'templates':[],'categories':[]})
        multi.verify_seal(app,order['design_json'],order['id'])
        bad=copy.deepcopy(order['design_json']);bad['objects'][0]['locked']=False
        with self.assertRaises(ValueError):multi.verify_seal(app,bad,order['id'])

    def test_fixed_image_source_cannot_be_replaced(self):
        self.tpl['objects_json']['objects'][3].update(locked=True,**{flag:False for flag in multi.FLAGS[1:]})
        app.local_save_json(app.TEMPLATES_FILE,{'templates':[self.tpl],'categories':[]});self.contract=self.client.get('/api/template_contract/'+self.tpl['id'],query_string={'model_id':self.model,'style_id':self.style}).json
        data=self.design();image=Image.new('RGBA',(512,256),'blue');out=io.BytesIO();image.save(out,'PNG');data['objects'][3]['src']='data:image/png;base64,'+base64.b64encode(out.getvalue()).decode()
        self.create(data,400)

    def test_photo_slot_native_crop_preserves_intrinsic_source(self):
        slot=layer(30);slot.update(role='template-photo-slot',templateSlot=True,isSlot=True,slotId='slot-a');self.tpl['objects_json']['objects'].append(slot)
        app.local_save_json(app.TEMPLATES_FILE,{'templates':[self.tpl],'categories':[]});self.contract=self.client.get('/api/template_contract/'+self.tpl['id'],query_string={'model_id':self.model,'style_id':self.style}).json
        data=self.design();photo=data['objects'][-1];photo.update(type='image',role='slot-photo',isSlot=False,src='data:image/png;base64,'+base64.b64encode(fixture.image()).decode(),width=100,height=100,cropX=180,cropY=50,sourceSize={'width':512,'height':256})
        order=app.commerce.store.order(self.create(data).json['order_id']);saved=order['design_json']['objects'][-1]
        self.assertEqual(saved['sourceSize'],{'width':512,'height':256});self.assertEqual(saved['cropX'],180);self.assertEqual(editable.image_bytes(app.print_center._download_artwork(saved['src'])),(512,256))

    def test_no_multilayer_contract_cannot_downgrade_to_legacy(self):
        data=self.design();data.pop('layer_contract_version')
        with self.assertRaises(ValueError):editable.validate(data)

    def test_multilayer_asset_upload_preserves_original_png(self):
        import quality_perf_patch
        maximum=app.app.config['MAX_CONTENT_LENGTH'];quality_perf_patch.install(app);app.app.config['MAX_CONTENT_LENGTH']=maximum
        raw=fixture.image();response=self.client.post('/api/admin/upload_image',data={'type':'template','source_contract':multi.VERSION,'file':(io.BytesIO(raw),'original.png','image/png')})
        self.assertEqual(response.status_code,200,response.json)
        self.assertTrue(response.json['url'].endswith('.png'))
        path=editable.ROOT/response.json['url'].lstrip('/');self.addCleanup(path.unlink,missing_ok=True)
        self.assertEqual(path.read_bytes(),raw)
        bad=self.client.post('/api/admin/upload_image',data={'type':'template','source_contract':multi.VERSION,'file':(io.BytesIO(b'not png'),'bad.png','image/png')})
        self.assertGreaterEqual(bad.status_code,400)

if __name__=='__main__':unittest.main(verbosity=2)
