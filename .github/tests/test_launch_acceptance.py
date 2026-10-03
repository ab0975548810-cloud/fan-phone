"""Cold Safari catalog and the existing private commerce settings UI."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def launch_acceptance_test(browser, base, poll):
    page = browser.new_page(viewport={'width': 390, 'height': 844}, device_scale_factor=3, has_touch=True)
    errors = []
    requests = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda req: requests.append(req.url) if '/api/shop_data' in req.url else None)
    # A fresh context, no cached catalog, and a genuinely pending first fetch.
    page.add_init_script("""(() => {
      const nativeFetch=window.fetch.bind(window);
      window.fetch=(input,init)=>{
        const url=String(typeof input==='string'?input:input.url);
        if(!url.includes('/api/shop_data'))return nativeFetch(input,init);
        window.__catalogPending=true;
        return new Promise((resolve,reject)=>{
          window.__releaseCatalog=()=>{window.__catalogPending=false;nativeFetch(input,init).then(resolve,reject)};
        });
      };
    })()""")
    page.goto(base+'/', wait_until='domcontentloaded')
    poll(page, "() => window.__catalogPending && !!window.BenfuwanFrontHomeV1")
    page.locator('.bf-home-primary').click()
    poll(page, "() => document.querySelector('#page-model.active') && document.querySelector('#model-list')?.dataset.catalogState==='loading'")
    assert '正在載入手機型號' in page.locator('#model-list').inner_text()
    assert '找不到符合' not in page.locator('#model-list').inner_text()
    page.wait_for_timeout(500)
    assert page.locator('.model-item').count() == 0
    page.evaluate("() => window.__releaseCatalog()")
    poll(page, "() => document.querySelector('#page-model.active') && document.querySelectorAll('.model-item').length>0")
    assert page.locator('#brand-row').inner_text()
    # The model list needs no thumbnails or external icon font.
    assert page.locator('.model-item img').count() == 0
    assert page.locator('.model-item svg').count() == page.locator('.model-item').count()
    assert page.locator('.model-item .fa-mobile-screen-button').count() == 0
    page.locator('#model-search').fill('not-a-real-phone-zz')
    assert '找不到符合的型號' in page.locator('#model-list').inner_text()
    page.locator('#model-search').fill('')
    assert page.locator('.model-item').count() > 0
    # BFCache restore re-renders existing data, without a second catalog query.
    count = len(requests)
    page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pageshow',{persisted:true}))")
    assert page.locator('.model-item').count() > 0
    assert len(requests) == count
    assert errors == [], errors
    page.close()

    failed = browser.new_page(viewport={'width':390,'height':844})
    failed.route('**/api/shop_data', lambda route: route.fulfill(status=503, content_type='application/json', body='{"status":"error"}'))
    failed.goto(base+'/', wait_until='domcontentloaded')
    poll(failed, "() => document.querySelector('#model-list')?.dataset.catalogState==='error' && !!window.BenfuwanFrontHomeV1")
    failed.locator('.bf-home-primary').click()
    assert '載入失敗' in failed.locator('#model-list').inner_text()
    assert '找不到符合' not in failed.locator('#model-list').inner_text()
    failed.unroute('**/api/shop_data')
    failed.locator('#model-list button').click()
    poll(failed, "() => document.querySelectorAll('.model-item').length>0 && document.querySelector('#page-model.active')")
    failed.close()

    admin = browser.new_page(viewport={'width':1180,'height':900})
    admin.goto(base+'/login', wait_until='domcontentloaded')
    if not admin.locator('#password-form').is_visible():
        admin.locator('#password-toggle').click()
    admin.locator('input[name="password"]').fill('fan123')
    admin.locator('button[type="submit"]').first.click()
    admin.wait_for_url('**/admin')
    admin.locator('.nav button[data-view="commerce"]').click()
    poll(admin, "() => window.BenfuwanCommerce?.state.skus.length>0")
    admin.locator('[data-tab="stock"]').click()
    admin.locator('#pos-series-cost').fill('77')
    admin.once('dialog', lambda dialog: dialog.accept())
    admin.locator('#pos-inherit-cost').click()
    with admin.expect_response('**/api/admin/save_commerce_data') as saved:
        admin.locator('#pos-cost-form button[type="submit"]').click()
    assert saved.value.status == 200
    poll(admin, "() => document.getElementById('pos-message').textContent==='商品設定已儲存'")
    assert '繼承系列' in admin.locator('[data-effective-cost]').first.inner_text()
    assert '77' in admin.locator('[data-effective-cost]').first.inner_text()
    card = admin.locator('.pos-sku').first
    card.locator('[data-field="cost_price"]').fill('88')
    assert 'SKU 覆寫' in card.locator('[data-effective-cost]').inner_text()
    admin.locator('#commerce-save').click()
    poll(admin, "() => document.getElementById('pos-message').textContent==='商品設定已儲存' && BenfuwanCommerce.state.skus.some(s=>s.cost_price===88)")
    assert admin.locator('.pos-sku').first.locator('[data-field="cost_price"]').input_value() == '88'
    admin.locator('[data-tab="reports"]').click()
    tomorrow = (datetime.now(ZoneInfo('Asia/Taipei')).date()+timedelta(days=1)).isoformat()
    admin.locator('#pos-report-start-date').fill(tomorrow)
    with admin.expect_response('**/api/admin/save_commerce_data') as saved:
        admin.locator('#pos-report-settings button').click()
    assert saved.value.status == 200
    poll(admin, "() => document.getElementById('pos-report-range').textContent.includes('尚未開始正式營運')")
    with admin.expect_response(lambda res: '/api/admin/commerce_report?' in res.url and 'include_test=1' in res.url) as response:
        admin.locator('#pos-include-test').check()
    result = response.value.json()['data']
    assert result['range']['includes_test_data'] is True
    assert result['summary']['orders'] > 0
    for width,height in ((390,844),(768,1024),(1180,900)):
        admin.set_viewport_size(dict(width=width,height=height))
        assert admin.evaluate('document.documentElement.scrollWidth<=innerWidth+2'), width
        admin.locator('[data-tab="stock"]').click()
        assert admin.evaluate('document.documentElement.scrollWidth<=innerWidth+2'), width
        admin.locator('[data-tab="reports"]').click()
    # Clean the test setting through the same guarded API; no production data.
    admin.locator('#pos-report-start-date').fill('')
    admin.locator('#pos-report-settings button').click()
    poll(admin, "() => BenfuwanCommerce.state.report_start_date===null")
    admin.close()
    print('LAUNCH_ACCEPTANCE_CATALOG_COST_REPORT_OK')
