"""Overview browser acceptance, using real API reads plus controlled edge cases."""
import copy
import json
import os
from pathlib import Path


def dashboard_test(browser, base, poll):
    page = browser.new_page(viewport={'width':1440,'height':900})
    errors=[]
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.goto(base+'/login',wait_until='domcontentloaded')
    page.locator('input[name="password"]').fill('fan123')
    page.locator('button[type="submit"]').first.click()
    page.wait_for_url('**/admin')
    poll(page,'() => !!window.BenfuwanCommerce')
    page.locator('.nav button[data-view="commerce"]').click()
    poll(page,"() => document.querySelectorAll('#pos-overview-kpis .pos-metric').length===8")
    assert page.locator('[data-tab="overview"]').get_attribute('class')=='selected'
    assert page.locator('#pos-overview-period').input_value()=='month'
    actual=page.request.get(base+'/api/admin/replenishment').json()['data']
    assert page.locator('[data-restock="needed"]').inner_text()==str(sum(actual['counts'][x] for x in ('out','low','threshold')))
    assert page.locator('[data-restock="suggested"]').inner_text()==str(actual['total_suggested'])
    assert page.locator('[data-restock="missing"]').inner_text()==str(actual['missing_targets'])
    financial=page.request.get(base+'/api/admin/commerce_report?period=month').json()['data']
    def ready():
        poll(page,"() => !document.getElementById('pos-overview-content').hidden && !document.getElementById('pos-overview-panel').hasAttribute('aria-busy')")
    def kpi(key):return page.locator('[data-kpi="'+key+'"] b').inner_text()
    for period in ('today','week','month','year'):
        page.locator('#pos-overview-period').select_option(period)
        ready()
        interval=page.request.get(base+'/api/admin/commerce_report?period='+period).json()['data']['range']
        assert interval['start']+' ～ '+interval['end'] in page.locator('#pos-overview-range').inner_text()
    for button,panel in (('restock','stock'),('report','report'),('expense','expense')):
        page.locator('#pos-overview-'+button).click()
        assert page.locator('#pos-'+panel+'-panel').is_visible()
        if button=='restock': assert page.locator('#commerce-low-only').is_checked()
        if button=='report': assert page.locator('#pos-period').input_value()=='year'
        if button=='expense': assert page.locator('#pos-expense-date').evaluate('(e)=>e===document.activeElement')
        page.locator('[data-tab="overview"]').click();ready()
    # Reuse the report contract, including monetary nulls; no server mutations.
    fixture=copy.deepcopy(financial)
    fixture['summary'].update(revenue=1000,orders=4,units=5,average_order_value=250,product_cost=300,gross_profit=700,expenses=50,net_profit=650,cost_complete=True,unknown_cost_orders=0,known_cost=300)
    fixture['series']=[dict(series_id=str(i),series_name=name,revenue=revenue,orders=2,units=3,gross_profit=10,cost_complete=i!=1) for i,(name,revenue) in enumerate([('晶彩',100),('鏡面',500),('透明',200),('長系列名稱'*10,400),('<img src=x onerror=alert(1)>',300),('六',50)])]
    stock=copy.deepcopy(actual)
    stock.update(counts=dict(out=2,low=3,threshold=1,normal=9,untracked=4),total_suggested=25,missing_targets=1)
    stock['groups']=[dict(series_id='a',series_name='晶彩',items=[dict(sku_id=str(i),model_name='iPhone '+str(i),color='透明',stock_qty=i, status=('out' if i<2 else 'low' if i<5 else 'threshold'),status_label='缺貨' if i<2 else '低於警戒值',suggested_quantity=None if i==0 else 5) for i in range(6)])]
    seen=[]
    def report_response(route):
        seen.append(route.request.url)
        route.fulfill(status=200,content_type='application/json',body=json.dumps(dict(status='success',data=fixture)))
    page.route('**/api/admin/commerce_report?*',report_response)
    page.route('**/api/admin/replenishment',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(dict(status='success',data=stock))))
    page.locator('#pos-overview-period').select_option('month');ready()
    for key,expected in dict(revenue='NT$ 1,000',orders='4 筆',units='5 件',average_order_value='NT$ 250',product_cost='NT$ 300',gross_profit='NT$ 700',expenses='NT$ 50',net_profit='NT$ 650').items():assert kpi(key)==expected,(key,kpi(key))
    assert page.locator('#pos-overview-series li').count()==5
    names=page.locator('.pos-rank-heading strong').all_text_contents()
    assert names[0]=='1. 鏡面' and names[2]=='3. <img src=x onerror=alert(1)>' and names[4]=='5. 晶彩',names
    assert page.locator('#pos-overview-series img').count()==0
    assert '成本資料不足' in page.locator('#pos-overview-series li').first.inner_text()
    assert page.locator('#pos-overview-restock-list li').count()==5
    assert '先設定目標' in page.locator('#pos-overview-restock-list li').first.inner_text()
    assert page.locator('[data-restock="needed"]').inner_text()=='6'
    assert page.locator('[data-restock="suggested"]').inner_text()=='25'
    fixture['summary'].update(product_cost=None,gross_profit=None,net_profit=None,cost_complete=False,unknown_cost_orders=2,known_cost=70)
    page.locator('#pos-overview-period').select_option('today');ready()
    for key in ('product_cost','gross_profit','net_profit'):assert kpi(key)=='成本資料不足'
    assert '2 筆成本未知' in page.locator('#pos-overview-cost-note').inner_text()
    assert 'NT$ 70' in page.locator('#pos-overview-cost-note').inner_text()
    assert kpi('revenue')=='NT$ 1,000' and kpi('expenses')=='NT$ 50'
    for width,height in ((390,844),(1024,768),(1440,900)):
        page.set_viewport_size(dict(width=width,height=height))
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
        for selector in ('#pos-overview-kpis','#pos-overview-series','#pos-overview-restock-list'):
            assert page.locator(selector).evaluate('(e)=>e.scrollWidth<=e.clientWidth+2'),(width,selector)
        if os.environ.get('POS_SCREENSHOT_DIR'):
            folder=Path(os.environ['POS_SCREENSHOT_DIR']);folder.mkdir(parents=True,exist_ok=True)
            page.locator('#pos-overview-panel').screenshot(path=str(folder/f'overview-{width}.png'))
    fixture['series']=[]
    fixture['summary'].update(revenue=0,orders=0,units=0,average_order_value=0,product_cost=0,gross_profit=0,net_profit=-50,cost_complete=True,unknown_cost_orders=0,known_cost=0)
    stock.update(groups=[],counts=dict(out=0,low=0,threshold=0),total_suggested=0,missing_targets=0)
    page.locator('#pos-overview-period').select_option('month');ready()
    assert page.locator('#pos-overview-empty').is_visible()
    assert '目前沒有需要補貨' in page.locator('#pos-overview-restock-list').inner_text()
    assert '尚無系列銷售' in page.locator('#pos-overview-series').inner_text()
    assert kpi('product_cost')=='NT$ 0' and kpi('net_profit')=='NT$ -50'
    page.unroute('**/api/admin/commerce_report?*')
    page.route('**/api/admin/commerce_report?*',lambda route:route.fulfill(status=503,content_type='application/json',body='{"status":"error","msg":"temporarily unavailable"}'))
    page.locator('#pos-overview-period').select_option('week')
    poll(page,"() => document.getElementById('pos-overview-status').textContent.includes('總覽載入失敗')")
    assert page.locator('#pos-overview-content').is_hidden()
    assert not errors,errors
    page.close()
    print('DASHBOARD_DEFAULT_PERIOD_KPIS_RESTOCK_RANKING_NAV_EMPTY_RESPONSIVE_OK')
