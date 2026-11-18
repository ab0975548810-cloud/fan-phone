"""Real full editor -> immutable V2 comparison -> independent fake reprint."""
import copy
import os
import sys
import threading
from pathlib import Path
from unittest import mock
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT));os.chdir(ROOT)
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_revision_reprints as fixtures
from test_order_design_browser import wait


def run():
    with sync_playwright() as p:
        browser=getattr(p,os.environ.get('BROWSER_ENGINE','webkit')).launch()
        for product,width in (('phone_case',390),('camera_film',1280)):
            fx=fixtures.RevisionReprintTests();fx.setUp();app=fixtures.app
            # Independent photo and text layers (an editable speech-bubble pair
            # intentionally moves both members together and is covered elsewhere).
            for item,role in zip(fx.fx.draft['objects'],('photo','text')):
                item['role']=role;item.pop('editableStickerId',None);item.pop('editableStickerInstanceId',None)
            order,source=fx.prepare(product);original=copy.deepcopy(app.commerce.store.order(order));finance=copy.deepcopy(app.commerce.read())
            server=make_server('127.0.0.1',0,app.app,threaded=True);threading.Thread(target=server.serve_forever,daemon=True).start();base='http://127.0.0.1:'+str(server.server_port)
            def context():
                c=browser.new_context(viewport={'width':width,'height':844},has_touch=width==390)
                c.add_cookies([{'name':k.key,'value':k.value,'url':base} for k in fx.client._cookies.values()]);return c
            try:
                c=context();page=c.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('console',lambda message:print('BROWSER_ERROR',message.text,flush=True) if message.type=='error' else None)
                page.goto(base+'/admin/order-design/'+order);wait(page,"document.querySelector('#order-design-save')?.disabled===false",60000)
                before=page.evaluate('canvas.getObjects()[1].toObject(CUSTOM_PROPS)')
                page.evaluate("()=>{const o=canvas.getObjects()[0];o.set('left',o.left+5);canvas.fire('object:modified',{target:o});canvas.renderAll();}")
                page.locator('#order-design-save').click();wait(page,"document.querySelector('#order-design-status').textContent.includes('V2 草稿已保存')",180000)
                assert page.evaluate('canvas.getObjects()[1].toObject(CUSTOM_PROPS)')==before
                rows=app.order_designs.rows(order);assert rows[-1]['document']['revisionPrint']['profile'],rows[-1]['document']['revisionPrint']
                page.locator('#order-design-review').click();page.locator('#revision-compare').wait_for()
                wait(page,"document.querySelector('#revision-compare').textContent.includes('尚未啟用')")
                assert page.locator('#revision-confirm').is_disabled();page.locator('#revision-close').click()
                page.screenshot(path=str(ROOT/'__pycache__'/('revision-'+browser.browser_type.name+'-'+product+'.png')))
                c.close();c=context();page=c.new_page();page.goto(base+'/admin/order-design/'+order)
                wait(page,"document.querySelector('#order-design-status')?.textContent.includes('正在編輯 V2')",60000)
                with mock.patch.dict(os.environ,{'ORDER_PIXEL_REPRINT_ENABLED':'true'}):
                    page.locator('#order-design-review').click();page.locator('#revision-reason').fill('隔離完整圖層測試');page.locator('#revision-cost').fill('12.50')
                    page.locator('#revision-confirm').click();wait(page,"document.querySelector('#revision-send')?.disabled===false")
                    assert fx.fx.fixture.fake.calls==[]
                    fx.fx.fixture.fake.responses['/api/Device/receiveTask']={'code':0,'data':{'taskid':'revision-browser-'+product,'status':0}}
                    page.on('dialog',lambda d:d.accept());page.locator('#revision-send').click();wait(page,"document.querySelector('#revision-compare').textContent.includes('QUEUED')")
                    assert len(fx.fx.fixture.fake.calls)==1
                assert app.print_center.store.job(source['id'])==source
                assert app.commerce.store.order(order)==original and app.commerce.read()==finance
                assert not errors,errors
                c.close();print('LAYERED_V2_HISTORICAL_720_COMPARE_REPRINT_OK',browser.browser_type.name,product,width,flush=True)
            finally:server.shutdown();server.server_close();fx.doCleanups()
        browser.close()


if __name__=='__main__':run()
