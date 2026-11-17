"""Real admin click -> same tab editor -> save/reload, isolated data and fake vendor."""
import base64
import copy
import os
import sys
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));os.chdir(ROOT)
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_order_designs as fixtures
from test_order_design_browser import wait
from admin_perf_patch import install as install_admin_perf
install_admin_perf(fixtures.app)


def run():
    fx=fixtures.OrderDesignTests();fx.setUp();app=fixtures.app
    # Match Fabric's serialized Textbox contract (the API-only fixture omits it).
    fx.draft['objects'][1]['styles']=[]
    photo='data:image/png;base64,'+base64.b64encode(fixtures.fx.image()).decode()
    for role,left in (('photo',15),('sticker',45)):
        fx.draft['objects'].append({'type':'image','role':role,'src':photo,'width':512,'height':256,
            'left':left,'top':40,'scaleX':.2,'scaleY':.2,'visible':True,'opacity':1})
    order_id=fx.create_original();old_id=fx.fixture.order_id
    original=copy.deepcopy(app.commerce.store.order(order_id));old=copy.deepcopy(app.commerce.store.order(old_id))
    finance=copy.deepcopy(app.commerce.store.read())
    server=make_server('127.0.0.1',0,app.app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base='http://127.0.0.1:'+str(server.server_port)
    try:
        with sync_playwright() as p:
            engine=os.environ.get('BROWSER_ENGINE','webkit')
            browser=getattr(p,engine).launch()
            context=browser.new_context(viewport={'width':390 if engine=='webkit' else 1280,'height':844},has_touch=engine=='webkit')
            context.add_cookies([{'name':c.key,'value':c.value,'url':base} for c in fx.client._cookies.values()])
            page=context.new_page();popups=[];errors=[]
            page.on('popup',lambda popup:popups.append(popup))
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('dialog',lambda dialog:dialog.accept())

            def click_editor(identity):
                page.goto(base+'/admin')
                link=page.locator(f'a[href="/admin/order-design/{identity}"]')
                link.wait_for();link.click()
                try:page.wait_for_url(base+'/admin/order-design/'+identity,timeout=5000)
                except Exception:
                    print('EDIT_NAVIGATION_FAILURE',{'current':page.url,'popups':len(popups),'pages':len(context.pages)},flush=True)
                    raise
                assert not popups and len(context.pages)==1,'Edit opened a second tab'

            click_editor(order_id)
            wait(page,"document.querySelector('#order-design-save')?.disabled===false")
            assert page.evaluate("canvas.getObjects().length") == 4
            assert set(page.evaluate('canvas.getObjects().map(o=>o.role)'))=={'photo','sticker','editable-sticker-bg','editable-sticker-text'}
            before=page.evaluate("canvas.getObjects().find(o=>o.role==='photo').left")
            page.evaluate("()=>{canvas.setActiveObject(canvas.getObjects().find(o=>o.role==='photo'));nudgeActive(5,0)}")
            page.locator('#order-design-save').click()
            wait(page,"document.querySelector('#order-design-status').textContent.includes('V2 草稿已保存')")
            page.reload()
            wait(page,"document.querySelector('#order-design-save')?.disabled===false")
            assert 'V2' in page.locator('#order-design-status').inner_text()
            assert page.evaluate('canvas.getObjects().length')==4
            assert page.evaluate("canvas.getObjects().find(o=>o.role==='photo').left")==before+5
            assert len(app.order_designs.rows(order_id))==2
            asset=page.evaluate("canvas.getObjects().find(o=>o.role==='photo').getSrc()")

            click_editor(old_id)
            page.get_by_text('以原始生產圖進行修改（保留排版）',exact=True).wait_for()
            assert '無法重新編輯此訂單' in page.locator('body').inner_text()
            assert '設計圖層結構無效' in page.locator('body').inner_text(),page.locator('body').inner_text()
            assert not app.order_designs.rows(old_id)
            anonymous=browser.new_context();denied=anonymous.new_page()
            response=denied.goto(base+'/admin/order-design/'+order_id)
            assert response.status==401 and response.json()['msg']=='請先登入後台'
            assert anonymous.request.get(asset).status==401
            denied.goto(base+'/admin');assert '/login' in denied.url
            assert app.commerce.store.order(order_id)==original
            assert app.commerce.store.order(old_id)==old
            assert app.commerce.store.read()==finance and fx.fixture.fake.calls==[]
            assert not errors,errors
            anonymous.close();context.close();browser.close()
            print('ADMIN_ORDER_EDIT_SAME_TAB_AUTH_RELOAD_V2_LEGACY_OK',engine,flush=True)
    finally:
        server.shutdown();server.server_close();fx.doCleanups()


if __name__=='__main__':run()
