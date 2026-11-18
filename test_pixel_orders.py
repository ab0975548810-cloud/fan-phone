import base64
import copy
import io
import os
import unittest
from unittest import mock
from PIL import Image, ImageDraw
from pathlib import Path
import test_print_center as fx
from pixel_order_designs import compose, sha, png

app=fx.app
HEAD={'X-Order-Design':'1'}

def picture(size=(72,144),color=(20,90,140,255)):
    im=Image.new('RGBA',size,color);ImageDraw.Draw(im).rectangle((0,0,9,9),fill=(15,25,35,0))
    return encode(im)

def encode(im):
    out=io.BytesIO();im.save(out,'PNG',dpi=(720,720));return out.getvalue()

def data(raw):return 'data:image/png;base64,'+base64.b64encode(raw).decode()

class PixelTests(unittest.TestCase):
    def setUp(self):
        import security_perf
        security_perf._CACHE.clear();security_perf._HITS.clear()
        self.fx=fx.PrintCenterTests();self.fx.setUp();self.addCleanup(self.fx.doCleanups);self.addCleanup(self.fx.tearDown)
        self.client=self.fx.client;self.order=self.fx.order_id
        self.raw=picture();order=app.commerce.store.order(self.order)
        Path(app.SAVE_DIR,order['print_path']).write_bytes(self.raw)
        self.original=copy.deepcopy(order);self.finance=copy.deepcopy(app.commerce.read())
        self.fx.save_profile()
        self.finance=copy.deepcopy(app.commerce.read())
        with app.app.test_request_context('/'):
            job=app.print_center.prepare(self.order,'pixel-fixture-prepare-1234')
        self.source=app.print_center.store.patch_job(job['id'],{'state':'COMPLETED','width_mm':2.54,'height_mm':5.08})
        self.url=f'/api/admin/order-design/{self.order}/pixel'
        self.env=mock.patch.dict(os.environ,{'ORDER_PIXEL_REPRINT_ENABLED':'true'});self.env.start();self.addCleanup(self.env.stop)

    def open(self):
        r=self.client.post(self.url+'/open',headers=HEAD);self.assertEqual(r.status_code,200,r.json);return r.json

    def save(self,work):
        overlay=Image.new('RGBA',(72,144));ImageDraw.Draw(overlay).rectangle((20,30,29,39),fill='red')
        erase=Image.new('RGBA',(72,144));ImageDraw.Draw(erase).rectangle((40,50,44,54),fill='white')
        r=self.client.post(self.url+'/save',headers=HEAD,json={'work':work['work'],'overlay':data(encode(overlay)),'erase':data(encode(erase)),'objects':[{'type':'rect','left':20,'top':30,'width':10,'height':10,'fill':'red'}]})
        self.assertEqual(r.status_code,200,r.json);return r.json

    def test_pixels_no_expansion_and_wrong_size(self):
        overlay=Image.new('RGBA',(72,144),(200,0,0,255));erase=Image.new('RGBA',(72,144))
        out,proof=compose(self.raw,encode(overlay),encode(erase));result=Image.open(io.BytesIO(out))
        self.assertEqual(result.getpixel((0,0)),(15,25,35,0))
        self.assertEqual(result.size,(72,144));self.assertAlmostEqual(result.info['dpi'][0],720,delta=.1)
        with self.assertRaises(ValueError):compose(self.raw,picture((71,144)),encode(erase))

    def test_16_bit_color_is_not_silently_reduced(self):
        import struct,zlib
        def chunk(name,value):return struct.pack('>I',len(value))+name+value+struct.pack('>I',zlib.crc32(name+value))
        raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,16,6,0,0,0))+chunk(b'IDAT',zlib.compress(b'\x00'+b'\x00\xff'*4))+chunk(b'IEND',b'')
        with self.assertRaisesRegex(ValueError,'色深'):png(raw)

    def test_version_compare_confirm_send_no_business_changes(self):
        first=self.open();second=self.save(first);self.assertEqual(second['version'],2)
        output=self.client.get(second['design']['outputPath']).data
        im=Image.open(io.BytesIO(output));self.assertEqual(im.getpixel((11,11)),(20,90,140,255));self.assertEqual(im.getpixel((22,32)),(255,0,0,255));self.assertEqual(im.getpixel((42,52))[3],0)
        payload={'version':2,'hash':second['hash'],'confirm':'compared-v1-v2','reason':'貼紙遮蓋','costCents':2500}
        r=self.client.post(self.url+'/confirm',headers=HEAD,json=payload);self.assertEqual(r.status_code,200,r.json)
        again=self.client.post(self.url+'/confirm',headers=HEAD,json=payload);self.assertEqual(r.json['jobId'],again.json['jobId'])
        self.assertEqual(self.fx.fake.calls,[])
        self.assertEqual(app.print_center.store.job(self.source['id']),self.source)
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            app.print_center.store.patch_job(r.json['jobId'],{'left_mm':self.source['left_mm']+1})
        self.assertEqual(app.print_center.store.job(r.json['jobId'])['left_mm'],self.source['left_mm'])
        self.fx.fake.responses['/api/Device/receiveTask']={'code':0,'data':{'taskid':'pixel-fixture-task','status':0}}
        for _ in range(2):
            sent=self.client.post(self.url+'/send',headers=HEAD,json=payload);self.assertEqual(sent.status_code,200,sent.json)
        self.assertEqual(len(self.fx.fake.calls),1)
        self.assertEqual(app.commerce.store.order(self.order),self.original);self.assertEqual(app.commerce.read(),self.finance)
        self.assertEqual(app.print_center.store.job(self.source['id']),self.source)
        self.assertEqual(self.open()['version'],2)

    def test_auth_missing_evidence_stale_save(self):
        self.assertEqual(app.app.test_client().post(self.url+'/open',headers=HEAD).status_code,401)
        self.assertEqual(self.client.post(self.url+'/open').status_code,403)
        with app.print_center.store.connection(True) as db:db.execute('UPDATE print_jobs SET artwork_sha256=? WHERE id=?',('0'*64,self.source['id']))
        first=self.open();self.assertIsNone(first['design']['profile']);second=self.save(first)
        self.assertEqual(self.client.get(first['design']['basePath']).data,self.raw)
        r=self.client.post(self.url+'/confirm',headers=HEAD,json={'version':2,'hash':second['hash']});self.assertEqual(r.status_code,422)
        anonymous=app.app.test_client();self.assertEqual(anonymous.get(first['design']['basePath']).status_code,401)
        stale={**first,'work':self.open()['work']};self.save(stale)
        r=self.client.post(self.url+'/save',headers=HEAD,json={'work':second['work'],'overlay':data(picture()),'erase':data(encode(Image.new('RGBA',(72,144)))),'objects':[]})
        self.assertEqual(r.status_code,409,r.json)

    def test_unknown_send_does_not_submit_again(self):
        second=self.save(self.open());payload={'version':2,'hash':second['hash'],'confirm':'compared-v1-v2','reason':'修補','costCents':0}
        self.assertEqual(self.client.post(self.url+'/confirm',headers=HEAD,json=payload).status_code,200)
        self.fx.fake.timeout_paths.add('/api/Device/receiveTask')
        self.assertEqual(self.client.post(self.url+'/send',headers=HEAD,json=payload).status_code,503)
        replay=self.client.post(self.url+'/send',headers=HEAD,json=payload)
        self.assertEqual(replay.status_code,200);self.assertEqual(replay.json['state'],'UNKNOWN')
        self.assertEqual(len(self.fx.fake.calls),1)
        self.assertEqual(app.print_center.store.jobs_for_order(self.order)[0]['state'],'UNKNOWN')

    def test_active_original_blocks_confirmation_and_feature_default_off(self):
        second=self.save(self.open());payload={'version':2,'hash':second['hash'],'confirm':'compared-v1-v2','reason':'修補','costCents':0}
        app.print_center.store.patch_job(self.source['id'],{'state':'UNKNOWN'})
        self.assertEqual(self.client.post(self.url+'/confirm',headers=HEAD,json=payload).status_code,422)
        with mock.patch.dict(os.environ,{'ORDER_PIXEL_REPRINT_ENABLED':'false'}):
            self.assertEqual(self.client.post(self.url+'/send',headers=HEAD,json=payload).status_code,422)
        self.assertEqual(self.fx.fake.calls,[])

if __name__=='__main__':unittest.main(verbosity=2)
