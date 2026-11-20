"""Verify the real orders-list JS, two origins and MK chain on loopback HTTPS."""
import os
from pathlib import Path
import sys
import threading
from unittest.mock import patch
import logging
import json
import sqlite3
from contextlib import closing
from PIL import Image

from flask import jsonify
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from test_private_reedit_http import PrivateHttpTests


def run():
    fx=PrivateHttpTests()
    fx.art_size=(2030,4241)
    fx.setUp()
    servers=[]
    try:
        source=fx.prod.application
        source.static_folder=str(ROOT/'static')
        @source.get('/admin')
        def orders():
            return '<div id="view-orders"><div class="panel"></div></div><script src="/static/admin-orders-v3.js"></script>'
        @source.get('/api/admin/get_orders')
        def order_list():
            return jsonify(status='success',data=[dict(order_id='A',time=1,has_print=True)])
        @source.get('/api/admin/print/order-summaries')
        def jobs():
            return jsonify(status='success',jobs={'A':{}})
        for application in (source,fx.qa_app):
            server=make_server('127.0.0.1',0,application,threaded=True,ssl_context='adhoc')
            servers.append(server)
            threading.Thread(target=server.serve_forever,daemon=True).start()
        shop='https://localhost:'+str(servers[0].server_port)
        private='https://127.0.0.1:'+str(servers[1].server_port)
        fx.service.config.origin=shop
        fx.login()
        reader=lambda k:os.environ[k]
        with patch.dict(os.environ,{'ADMIN_REEDIT_SOURCE_ORIGIN':shop,'ADMIN_REEDIT_PRIVATE_ORIGIN':private}), \
             patch('reedit_transport.origin',reader),patch('reedit_private_site.origin',reader),sync_playwright() as p:
            engine=os.getenv('BROWSER_ENGINE','webkit')
            browser=getattr(p,engine).launch()
            context=browser.new_context(ignore_https_errors=True,viewport={'width':390,'height':844},has_touch=True)
            context.add_cookies([dict(name=c.key,value=c.value,url=shop) for c in fx.prod._cookies.values()])
            page=context.new_page()
            page.goto(shop+'/admin')
            page.get_by_role('button',name='重新編輯（測試）').click()
            for step in (1,2):
                page.wait_for_function("document.querySelector('#pixel-status')?.textContent.includes('正在編輯 V1')")
                page.locator('#pixel-cover').click()
                if step==2:
                    page.evaluate("""()=>{
                        const layer=canvas.getObjects().at(-1);
                        layer.set({left:100,top:120,angle:15});
                        layer.setCoords();
                        canvas.fire('object:modified',{target:layer});
                        recordHistory();
                    }""")
                page.locator('#pixel-save').click()
                link=page.locator('#private-reedit-status a')
                link.wait_for()
                assert '假設備已接收' in page.locator('#private-reedit-status').text_content()
                if step==1:link.click()
            private_db=next(fx.volume.glob('*/work.db'))
            with closing(sqlite3.connect(private_db)) as db:
                rows=db.execute('select document from order_design_versions where version=2 order by rowid').fetchall()
                assert len(rows)==2
                docs=[json.loads(row[0]) for row in rows]
                assert docs[0]['outputSha']!=docs[1]['outputSha']
                for document in docs:
                    with Image.open(private_db.parent/document['outputPath']) as output:
                        assert output.size==(2030,4241) and abs(output.info['dpi'][0]-720)<.1
                        assert output.getpixel((2020,4200))==(255,0,0,255)
            assert fx.before==fx.source_contents()
            fx.credentials.clear()
            assert page.evaluate("fetch('/private/active').then(r=>r.status)") == 403
            browser.close()
            print('Private list → bound HTTPS handoff → storefront canvas → MK B → MK C; revocation passed:',engine)
    finally:
        for server in servers:server.shutdown()
        fx.doCleanups()


if __name__=='__main__':
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    run()
