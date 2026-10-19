"""Protected checkout gate: real browser + HTTP + files + SQLite; no live services."""
import base64
import copy
import io
import os
import sys
import threading
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ.pop('SUPABASE_URL', None)
os.environ.pop('SUPABASE_SERVICE_ROLE_KEY', None)
os.environ['SESSION_COOKIE_SECURE'] = 'false'

from PIL import Image
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server
import test_multilayer_templates as fixture


def run():
    fx = fixture.MultilayerTests()
    fx.setUp()
    app = fixture.app
    raw = io.BytesIO()
    Image.new('RGBA', (2030, 4241), (224, 100, 150, 128)).save(raw, 'PNG', dpi=(720, 720))
    artwork = 'data:image/png;base64,' + base64.b64encode(raw.getvalue()).decode()
    photo = 'data:image/png;base64,' + base64.b64encode(fixture.fixture.image()).decode()
    mixed = {'version': '5.3.1', 'objects': [
        {'type': 'image', 'role': 'photo', 'src': photo},
        {'type': 'image', 'role': 'sticker', 'src': photo},
        {'type': 'textbox', 'text': '正常送單', 'fontFamily': 'Arial'},
    ]}
    removed = copy.deepcopy(mixed)
    removed['objects'][0].update(aiBackgroundRemoved=True, aiRemovalMode='general')
    legacy = copy.deepcopy(mixed)
    legacy.update(template_version=2)
    legacy['objects'][0].update(role='slot-photo', slotId='legacy-slot')
    cases = [
        ('photo-sticker-text', mixed), ('ai-cutout', removed),
        ('transparent-png', {'objects': [mixed['objects'][0]]}),
        ('legacy-template', legacy), ('editable-text', fx.fx.draft),
        ('multilayer-template', fx.design()),
    ]
    server = make_server('127.0.0.1', 0, app.app, threaded=True)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with mock.patch.object(app.print_center, 'enqueue_auto') as enqueue, \
             mock.patch('editable_stickers.public_image', return_value=fixture.fixture.mask()), \
             sync_playwright() as playwright:
            engine = os.environ.get('BROWSER_ENGINE', 'webkit')
            browser = getattr(playwright, engine).launch()
            try:
                for name, design in cases:
                    context = browser.new_context(viewport={'width': 390, 'height': 844},
                                                  has_touch=True, is_mobile=True)
                    page = context.new_page()
                    requests, responses = [], []
                    lose_first = name == 'editable-text'

                    def checkout(route):
                        requests.append(route.request.post_data_json)
                        response = route.fetch()
                        responses.append(response.json())
                        assert response.status == 200, (name, response.status, response.text())
                        if lose_first and len(requests) == 1:
                            route.abort('failed')
                        else:
                            route.fulfill(response=response)

                    page.route('**/api/create_order', checkout)
                    before = app.commerce.read()
                    try:
                        # initializeFront restores IndexedDB cart before its health probe.
                        # Seed the isolated cart only after that real boot lifecycle finishes.
                        with page.expect_response(lambda r: r.url == origin + '/api/health'):
                            page.goto(origin + '/', wait_until='domcontentloaded')
                        page.wait_for_function("() => !!window.BenfuwanOrderPayload && !!window.BenfuwanMultilayerFront && typeof shopData!=='undefined' && shopData.models?.length")
                        page.evaluate('''async data => {
                          if(data.design.layer_contract_version==='multilayer-v1'){
                            const r=await fetch('/api/template_contract/multilayer-fixture?model_id='+encodeURIComponent(data.model)+'&style_id='+encodeURIComponent(data.style));
                            const contract=await r.json();if(!r.ok)throw Error(contract.msg);
                            data.design.templateBinding=contract.binding;
                            for(const item of data.design.objects){item.templateApplicationId=contract.binding.applicationId;item.layerInstanceId=contract.binding.applicationId+':'+item.layerId;}
                          }
                          cartItem={modelId:data.model,styleId:data.style,modelName:'測試型號',styleName:'測試殼款',colorName:'透明',quantity:1,payment:'現金',price:390,
                            printBase64:data.artwork,mockupBase64:data.artwork,designJson:data.design,
                            productionMeta:{ppm:BenfuwanProductionHQ.PPM,dpi:720,width:2030,height:4241}};
                          await idbSet('cart',cartItem);goCheckoutFromCart();
                        }''', dict(model=fx.model, style=fx.style, artwork=artwork, design=design))
                        page.locator('#form-surname').fill('回歸')
                        page.locator('#submit-order').click()
                        if lose_first:
                            page.wait_for_function("() => document.getElementById('toast').textContent.includes('送單失敗') && !document.getElementById('submit-order').disabled")
                            with page.expect_response(lambda r: r.url == origin + '/api/health'):
                                page.reload(wait_until='domcontentloaded')
                            page.wait_for_function("() => !!window.BenfuwanMultilayerFront && typeof cartItem!=='undefined' && cartItem?.orderKey")
                            page.evaluate('() => goCheckoutFromCart()')
                            page.locator('#form-surname').fill('回歸')
                            page.locator('#submit-order').click()
                        page.wait_for_function("() => document.getElementById('page-success').classList.contains('active')")
                        order_id = page.locator('#success-id').inner_text()
                        assert len(requests) == (2 if lose_first else 1), (name, len(requests))
                        if lose_first:
                            assert requests[0]['idempotency_key'] == requests[1]['idempotency_key']
                            assert responses[0]['order_id'] == responses[1]['order_id']
                        after = app.commerce.read()
                        assert len(after['order_finance']) == len(before['order_finance']) + 1
                        sku_id = after['order_finance'][order_id]['sku_id']
                        old_sku = next(s for s in before['skus'] if s['id'] == sku_id)
                        new_sku = next(s for s in after['skus'] if s['id'] == sku_id)
                        assert new_sku['stock_qty'] == old_sku['stock_qty'] - 1
                        assert len([r for r in after['inventory_ledger'] if r['order_id'] == order_id]) == 1
                        order = app.commerce.store.order(order_id)
                        for key in ('print_path', 'mockup_path'):
                            with Image.open(Path(app.SAVE_DIR) / order[key]) as saved:
                                assert saved.size == (2030, 4241)
                                assert abs(saved.info['dpi'][0] - 720) < .1
                        orders = fx.client.get('/api/admin/get_orders', query_string={'order_id': order_id}).json
                        assert any(r.get('order_id', r.get('id')) == order_id for r in orders['data'])
                        assert page.evaluate("() => idbGet('cart')") is None
                        assert fx.fx.fixture.fake.calls == []
                        print('CHECKOUT_PROTECTED_OK', engine, name, 'one order / one deduction / no vendor', flush=True)
                    finally:
                        context.close()
                assert enqueue.call_count == 7  # six orders plus one committed replay
            finally:
                browser.close()
    finally:
        server.shutdown()
        worker.join(timeout=5)
        fx.doCleanups()


if __name__ == '__main__':
    run()
