"""Real Fabric renderer plus API/CAS/legacy safety tests, no production/vendor access."""
import base64
import copy
import hashlib
import io
import unittest
from unittest import mock
from PIL import Image,ImageDraw
import editable_stickers as editable
import test_print_center as print_fixture
app,PNG=print_fixture.app,print_fixture.PNG


def image(width=512,height=256):
    im=Image.new('RGBA',(width,height),(0,0,0,0));ImageDraw.Draw(im).rounded_rectangle((8,8,width-8,height-8),radius=32,fill='white',outline='#d56c96',width=5)
    out=io.BytesIO();im.save(out,'PNG');return out.getvalue()


def mask():
    im=Image.new('RGBA',(200,400),(0,0,0,0));d=ImageDraw.Draw(im);d.rectangle((10,10,189,389),fill='black');d.ellipse((18,18,58,58),fill=(0,0,0,0));out=io.BytesIO();im.save(out,'PNG');return out.getvalue()


def design(model,style):
    common={'editableStickerId':'dialog-a','editableStickerInstanceId':'instance-a','originX':'center','originY':'center','left':100,'top':200,'scaleX':.35,'scaleY':.35,'angle':0,'flipX':False,'flipY':False,'opacity':1,'visible':True}
    text={'type':'textbox','role':'editable-sticker-text','text':'繁體中文\n文字貼紙測試','fontFamily':'jf-openhuninn','fontSize':36,'requestedFontSize':36,'minFontSize':12,'fontWeight':'400','fontStyle':'normal','fill':'#332222','stroke':'#fff','strokeWidth':0,'textAlign':'center','charSpacing':20,'lineHeight':1.2,'width':350,'height':75,'textArea':{'x':.15,'y':.2,'width':.7,'height':.45},**common}
    bg={'type':'image','role':'editable-sticker-bg','assetId':'dialog-a','src':'data:image/png;base64,'+base64.b64encode(image()).decode(),'width':512,'height':256,**common}
    return {'render_contract_version':editable.VERSION,'modelId':model,'styleId':style,'logicalCanvas':{'width':200,'height':400},'production':{'printW':71.63,'printH':149.61},'objects':[bg,text],'background':'transparent'}


class EditableTests(unittest.TestCase):
    def setUp(self):
        self.fixture=print_fixture.PrintCenterTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.client=self.fixture.client
        self.model=app.DEFAULT_SHOP_DATA['models'][0]['id'];self.style=app.DEFAULT_SHOP_DATA['styles'][0]['id']
        shop=copy.deepcopy(app.DEFAULT_SHOP_DATA);shop['models'][0]['case_profiles']={self.style:{'preview_mask_img':'/static/dialog-preview.png','print_line_img':'/static/dialog-mask.png','print_w':71.63,'print_h':149.61,'print_x':12,'print_y':13,'print_angle':90}}
        app.local_save_json(app.DATA_FILE,shop)
        app.print_center.store.save_profiles([{'sku_id':self.fixture.sku_id,'width_mm':71.63,'height_mm':149.61,'left_mm':12,'top_mm':13,'angle':90,'copies':1,'channel':'1','spot_color':''}])
        self.draft=design(self.model,self.style)

    def create(self,draft=None):
        with mock.patch.object(editable,'public_image',return_value=mask()):
            response=self.client.post('/api/create_order',json={'idempotency_key':'structured-'+__import__('uuid').uuid4().hex,'model_id':self.model,'style_id':self.style,'quantity':1,'customer_name':'文字貼紙','payment_method':'現金','print_file':PNG,'mockup_file':PNG,'design_json':self.draft if draft is None else draft})
        self.assertEqual(response.status_code,200,response.get_data(as_text=True))
        return response.json['order_id']

    def test_schema_and_normalized_area(self):
        editable.validate(self.draft)
        for area in ({'x':.8,'y':.1,'width':.3,'height':.5},{'x':0,'y':0,'width':0,'height':1},{'x':True,'y':0,'width':.5,'height':1}):
            with self.assertRaises(ValueError):editable.normalized_area(area)
        bad=copy.deepcopy(self.draft);bad['objects'].pop()
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

    def test_geometry_change_fail_closed(self):
        order=app.commerce.store.order(self.create());profile=app.print_center.store.profile(self.fixture.sku_id);profile['width_mm']=80
        with self.assertRaises(ValueError):editable.render(app,order,profile,app.print_center._download_artwork)

    def test_legacy_order_still_uses_print_path(self):
        order=app.commerce.store.order(self.fixture.order_id);job=app.print_center.prepare(order['id'],'legacy-preserved')
        self.assertEqual(job['artwork_path'],order['print_path'])

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

if __name__=='__main__':unittest.main(verbosity=2)
