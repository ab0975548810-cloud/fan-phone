"""Immutable composition tests, real public-mask fixtures and isolated API/authority."""
import copy
import io
import json
import math
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw
import template_adaptation as engine
import test_multilayer_templates as fixture

ROOT = Path(__file__).parent
app = fixture.app


def master(kind='mixed'):
    result = fixture.template('source', 'crystal', 1)
    result.update(id='master-fixture', adaptation_contract_version=engine.VERSION,
                  source_canvas_w=200, source_canvas_h=400, source_print_w=100, source_print_h=200)
    bg = result['objects_json']['objects'][0]
    bg.update(adaptationRole='background-crop', fill='#ffe7f0')
    result['objects_json']['objects'] = [bg]
    plans = {
        'full-image': [('image', .5, .5, 1, 1)],
        'photos': [('rect', .3, .46, .26, .2), ('rect', .7, .46, .26, .2), ('rect', .5, .72, .32, .18)],
        'text-sticker': [('textbox', .5, .4, .48, .08), ('rect', .3, .6, .15, .08), ('circle', .68, .62, .18, .09)],
        'subject-title': [('image', .5, .67, .4, .36), ('textbox', .5, .4, .5, .09)],
        'mixed': [('textbox', .5, .4, .45, .08)]+[('rect', .18+.16*(i%5), .53+.08*(i//5), .1, .04) for i in range(25)],
    }
    for i, (kind_, x, y, w, h) in enumerate(plans[kind], 1):
        o = fixture.layer(i, kind_)
        if kind_ == 'circle':o.update(radius=12,width=24,height=24)
        if kind_ == 'textbox':
            o.update(styles=[],text='Happy cats', fontFamily='jf-openhuninn', fontSize=12, width=96, height=32, fill='#643d4b')
        o.update(angle=0, adaptationRole='important-text' if kind_ == 'textbox' else 'subject' if kind_ == 'image' else 'composition',
                 normalizedGeometry=dict(x=x, y=y, width=w, height=h))
        if kind_ == 'rect' and kind == 'photos':
            o.update(templateSlot=True, isSlot=True, slotId='slot-'+str(i), role='template-photo-slot')
        o.update(scaleX=w*200/o['width'], scaleY=h*400/o['height'], left=x*200, top=y*400)
        result['objects_json']['objects'].append(o)
    if kind=='full-image':
        o=result['objects_json']['objects'][1];o.update(isTplBg=True,adaptationRole='background-crop',role='template-bg',locked=True,**{flag:False for flag in fixture.multi.FLAGS if flag!='locked'})
        o['zIndex']=0;result['objects_json']['objects']=[o]
    return result


def target(w=78.87, h=152.15, identity='iphone13'):
    return dict(model_id=identity, style_id='crystal', model_name=identity, style_name='晶彩',
                profile=dict(print_w=w, print_h=h, print_x=1, print_y=2, print_angle=90,
                             preview_mask_img='preview', print_line_img='mask'))


def full_mask(hole=None):
    image = Image.new('L', (192,384), 255)
    if hole: ImageDraw.Draw(image).rectangle(hole, fill=0)
    return image


class GeometryTests(unittest.TestCase):
    def test_reproduces_old_spacing_and_multilayer_stretch(self):
        # iPhone 13 -> 17 Pro uses their real configured physical dimensions.
        rx, ry = 71.63/78.87, 149.61/152.15
        self.assertGreater(abs(rx-ry), .07)
        # Old normalized/v6: point spacing ry, object size min(rx,ry).
        self.assertGreater(abs(100*ry-100*min(rx,ry)), 7)
        # Old multilayer map: independent scales distort a square by >8%.
        self.assertGreater(abs(ry/rx-1), .08)

    def test_one_uniform_transform_and_immutable_master(self):
        m=master();original=copy.deepcopy(m)
        out=engine.adapt(m,target(71.63,149.61),full_mask(),'mask')
        self.assertEqual(m,original)
        source=m['objects_json']['objects'][1:];dest=out['objects_json']['objects'][1:]
        sw,sh=200,400;tw=out['source_canvas_w'];th=out['source_canvas_h'];scale=out['adaptation_report']['scale']
        for a,b in zip(source,dest):
            g,h=a['normalizedGeometry'],b['normalizedGeometry']
            self.assertAlmostEqual(h['width']*tw/(h['height']*th),g['width']*sw/(g['height']*sh),places=9)
            self.assertEqual(a['angle'],b['angle']);self.assertEqual(a['opacity'],b['opacity'])
        for i in range(1,len(source)):
            a,b=source[0]['normalizedGeometry'],source[i]['normalizedGeometry'];c,d=dest[0]['normalizedGeometry'],dest[i]['normalizedGeometry']
            self.assertAlmostEqual(math.hypot((d['x']-c['x'])*tw,(d['y']-c['y'])*th),math.hypot((b['x']-a['x'])*sw,(b['y']-a['y'])*sh)*scale,places=8)
        self.assertEqual(out,engine.adapt(m,target(71.63,149.61),full_mask(),'mask'))
        with self.assertRaisesRegex(ValueError,'再次轉換'):engine.adapt(out,target(),full_mask(),'mask')

    def test_real_masks_five_compositions_four_models_and_camera_positions(self):
        files=[('iphone13',78.87,152.15),('iphone14',78.87,152.15),('iphone14-pro-max',85,166.3),('iphone17-pro',71.63,149.61)]
        for kind in ('full-image','photos','text-sticker','subject-title','mixed'):
            for name,w,h in files:
                with self.subTest(kind=kind,model=name):
                    mask=Image.open(ROOT/'.github/tests/fixtures/preview_masks'/f'{name}-print.png').convert('RGBA').getchannel('A')
                    mask=mask.point(lambda n:255 if n>=224 else 0)
                    out=engine.adapt(master(kind),target(w,h,name),mask,name)
                    self.assertIn(out['adaptation_report']['status'],('success','needs-adjustment'))
                    if out['adaptation_report']['status']=='success':
                        tw,th=out['source_canvas_w'],out['source_canvas_h']
                        rows=[(o['layerId'],o,engine.source_geometry(o,tw,th)) for o in out['objects_json']['objects']]
                        self.assertEqual(engine.check(rows,mask,tw,th),[])
        m=master('text-sticker');m['objects_json']['objects'][1]['normalizedGeometry'].update(x=.12,y=.12,width=.12,height=.06)
        out=engine.adapt(m,target(),full_mask((0,0,60,110)),'left',auto=False)
        self.assertEqual(out['adaptation_report']['status'],'needs-adjustment')
        self.assertNotEqual(engine.adapt(m,target(),full_mask((120,0,191,110)),'right',auto=False)['adaptation_report']['issues'],out['adaptation_report']['issues'])

    def test_uniform_group_shift_smallest_and_manual_fail_closed(self):
        m=master('photos');m['objects_json']['objects'][1]['normalizedGeometry'].update(x=.06,y=.5,width=.08,height=.1)
        safe=full_mask();ImageDraw.Draw(safe).rectangle((0,0,10,383),fill=0)
        out=engine.adapt(m,target(100,200),safe,'edge')
        shift=out['adaptation_report']['autoShift']
        self.assertGreater(shift['x'],0);self.assertEqual(shift['y'],0);self.assertEqual(out['adaptation_report']['status'],'success')
        impossible=Image.new('L',safe.size,0)
        self.assertEqual(engine.adapt(m,target(),impossible,'empty')['adaptation_report']['status'],'needs-adjustment')
        with self.assertRaises(ValueError):engine.adapt(m,target(),safe,'x',{'scale':5})

    def test_legacy_slots_share_distance_scale_rotation_clip_and_editable_area(self):
        m=master('text-sticker');o=m['objects_json']['objects'][2];o.update(angle=37,opacity=.6,flipX=True,clipPath=dict(type='rect',left=30,top=140,width=20,height=20,absolutePositioned=True))
        o['textArea']=dict(x=.1,y=.1,width=.8,height=.8)
        m['slots']=[dict(id='legacy-slot',x=20,y=60,w=25,h=20)]
        out=engine.adapt(m,target(),full_mask(),'m')
        mapped=out['objects_json']['objects'][2]
        for key in ('angle','opacity','flipX','textArea'):self.assertEqual(o[key],mapped[key])
        self.assertAlmostEqual(out['slots'][0]['w']/out['slots'][0]['h'],25/20)
        self.assertAlmostEqual(mapped['clipPath']['scaleX'],out['adaptation_report']['scale'])

    def test_decoration_adjustment_does_not_change_master_or_other_targets(self):
        m=master('text-sticker');m['objects_json']['objects'][2]['adaptationRole']='decoration';original=copy.deepcopy(m)
        a=engine.adapt(m,target(),full_mask(),'m',{'layers':{'layer-2':{'x':.02,'y':.01}}})
        b=engine.adapt(m,target(),full_mask(),'m')
        self.assertEqual(m,original);self.assertNotEqual(a['objects_json']['objects'][2],b['objects_json']['objects'][2])
        self.assertEqual(a['objects_json']['objects'][1],b['objects_json']['objects'][1])
        with self.assertRaises(ValueError):engine.adapt(m,target(),full_mask(),'m',{'layers':{'layer-1':{'x':.01}}})


class ApiTests(unittest.TestCase):
    design=fixture.MultilayerTests.design
    create=fixture.MultilayerTests.create
    # Use the existing isolated SQLite/private-source/renderer fixture.
    def setUp(self):
        fixture.MultilayerTests.setUp(self);engine._MASKS.clear()
        self.tpl=master('text-sticker');self.tpl.update(reference_model_id=self.model,reference_style_id=self.style)
        with mock.patch('editable_stickers.public_image',return_value=fixture.fixture.mask()):fixture.multi.prepare_template(app,self.tpl)
        app.local_save_json(app.TEMPLATES_FILE,{'templates':[self.tpl],'categories':['全部','熱門']})
        with mock.patch('editable_stickers.public_image',return_value=fixture.fixture.mask()):
            self.contract=self.client.get('/api/template_contract/'+self.tpl['id'],query_string={'model_id':self.model,'style_id':self.style}).json
        self.assertEqual(self.contract['status'],'success',self.contract)

    # Do not inherit/re-run tests that intentionally assume the old unadapted fixture.
    def test_auth_targets_exclude_film_and_incomplete(self):
        anon=app.app.test_client()
        self.assertEqual(anon.get('/api/admin/template-adaptation/targets').status_code,401)
        self.assertEqual(anon.post('/api/admin/template-adaptation/preview',json={}).status_code,401)
        self.assertEqual(anon.post('/api/admin/template-adaptation/save',json={}).status_code,401)
        response=self.client.get('/api/admin/template-adaptation/targets').json
        self.assertTrue(response['targets']);self.assertEqual(response['targets'][0]['model_id'],self.model)
        shop=copy.deepcopy(app.DEFAULT_SHOP_DATA);shop['models'][0]['product_type']='camera_film'
        self.assertEqual(engine.targets(shop),[])

    def test_contract_uses_resolved_authority_and_persists_720dpi(self):
        design=self.design();design['objects']=copy.deepcopy(self.contract['template']['objects_json']['objects'])
        for item in design['objects']:
            item['templateApplicationId']=design['templateBinding']['applicationId'];item['layerInstanceId']=item['templateApplicationId']+':'+item['layerId']
        order_id=self.create(design).json['order_id']
        job=app.print_center.prepare(order_id,'master-720-prepare')
        image=Image.open(io.BytesIO(app.print_center._download_artwork(job['artwork_path'])))
        self.assertEqual(image.size,(2030,4241));self.assertAlmostEqual(image.info['dpi'][0],720,delta=.05)
        # Protected background must be compared to TARGET authority, not original source size.
        bad=copy.deepcopy(design);bad['objects'][0]['normalizedGeometry']['x']=.2;self.create(bad,400)

    def test_batch_new_only_cas_and_exact_variants(self):
        original=app.local_load_json(app.TEMPLATES_FILE,{})
        self.client.get('/api/templates')  # Warm the public catalog cache.
        _,version=app.cloud_get_json_versioned('templates',app.TEMPLATES_FILE,app.DEFAULT_TEMPLATES)
        payload=dict(master=self.tpl,targets=[dict(model_id=self.model,style_id=self.style)],expected_version=version)
        with mock.patch('editable_stickers.public_image',return_value=fixture.fixture.mask()):
            result=self.client.post('/api/admin/template-adaptation/save',json=payload)
        self.assertEqual(result.status_code,200,result.json)
        stored=app.local_load_json(app.TEMPLATES_FILE,{})['templates']
        self.assertEqual(stored[0],original['templates'][0]);self.assertEqual(len(stored),3)
        self.assertEqual(stored[-1]['master_template_id'],stored[-2]['id'])
        self.assertEqual(stored[-1]['reference_model_id'],self.model)
        tampered=copy.deepcopy(stored[-1]);tampered['objects_json']['objects'][1]['normalizedGeometry']['x']+=.01
        with self.assertRaisesRegex(ValueError,'版本內容已改變'):fixture.multi.prepare_template(app,tampered)
        self.assertEqual(len(self.client.get('/api/templates').json['data']['templates']),3)
        self.assertEqual(self.client.post('/api/admin/template-adaptation/save',json=payload).status_code,409)
        wrong=self.client.get('/api/template_contract/'+stored[-1]['id'],query_string={'model_id':'other','style_id':self.style})
        self.assertEqual(wrong.status_code,400)

    def test_batch_failure_has_no_partial_write_and_target_change_invalidates_binding(self):
        before=app.local_load_json(app.TEMPLATES_FILE,{})
        _,version=app.cloud_get_json_versioned('templates',app.TEMPLATES_FILE,app.DEFAULT_TEMPLATES)
        response=self.client.post('/api/admin/template-adaptation/save',json=dict(master=self.tpl,expected_version=version,
            targets=[dict(model_id=self.model,style_id=self.style),dict(model_id='absent',style_id=self.style)]))
        self.assertEqual(response.status_code,400,response.json)
        self.assertEqual(app.local_load_json(app.TEMPLATES_FILE,{}),before)
        data=self.design();data['objects']=copy.deepcopy(self.contract['template']['objects_json']['objects'])
        for item in data['objects']:
            item['templateApplicationId']=data['templateBinding']['applicationId'];item['layerInstanceId']=item['templateApplicationId']+':'+item['layerId']
        shop=app.local_load_json(app.DATA_FILE,{})
        shop['models'][0]['case_profiles'][self.style]['print_h']+=10
        app.local_save_json(app.DATA_FILE,shop)
        with self.client.session_transaction() as session:identity=session['_bf_client_id']
        with app.app.test_request_context('/api/create_order'):
            app.session['_bf_client_id']=identity
            with self.assertRaisesRegex(ValueError,'適配設定已更新'):fixture.multi.verify_design(app,data)

    def test_mask_unavailable_fails_no_generic_safe_box(self):
        engine._MASKS.clear()
        with mock.patch('editable_stickers.public_image',side_effect=ValueError('missing')):
            result=self.client.post('/api/admin/template-adaptation/preview',json=dict(master=self.tpl,model_id=self.model,style_id=self.style))
        self.assertEqual(result.status_code,400);self.assertNotIn('template',result.json)


if __name__=='__main__':unittest.main()
