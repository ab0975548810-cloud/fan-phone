"""Browser-only Admin AI A/B UI regression; provider responses are intercepted."""
import base64
import json


PIXEL = base64.b64encode(
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89'
    b'\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82'
).decode()


def admin_ai_ab_browser_test(browser, base, poll):
    page = browser.new_page(viewport={'width': 390, 'height': 844})
    page.goto(base + '/login', wait_until='domcontentloaded')
    if not page.locator('#password-form').is_visible():
        page.locator('#password-toggle').click()
    page.locator('input[name="password"]').fill('fan123')
    page.locator('button[type="submit"]').first.click()
    page.wait_for_url('**/admin')
    page.goto(base + '/admin/ai-ab-test', wait_until='domcontentloaded')
    assert page.locator('h1').inner_text() == 'AI 去背 A/B 測試'
    assert page.locator('text=AI_REMOVE_PROVIDER').count() == 0
    assert page.locator('script[src*="playwright"],script[src*="chromium"]').count() == 0
    page.route('**/api/admin/ai-ab-test/summary', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps({'status':'success','stats':{
            'koukoutu_wins':2,'runpod_wins':1,'ties':1,'koukoutu_average_ms':1200,'runpod_average_ms':2300,
        }})))
    sequence = []
    def run(route):
        sequence.append('single-sequential-endpoint')
        result = lambda provider, model, elapsed: {
            'ok':True,'provider':provider,'model':model,'elapsed_ms':elapsed,
            'width':1,'height':1,'bytes':len(base64.b64decode(PIXEL)),
            'valid_alpha':True,'png_base64':PIXEL,
        }
        route.fulfill(status=200, content_type='application/json', body=json.dumps({
            'status':'success','original':{'width':1600,'height':2400,'bytes':999},
            'koukoutu':result('koukoutu','background-removal',1200),
            'runpod':result('runpod','ZhengPeng7/BiRefNet',2300),
            'rating_token':'signed-test-token','stats':{'koukoutu_wins':2,'runpod_wins':1,'ties':1,'koukoutu_average_ms':1200,'runpod_average_ms':2300},
            'stats_warning':'',
        }))
    page.route('**/api/admin/ai-ab-test/run', run)
    page.route('**/api/admin/ai-ab-test/rate', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps({'status':'success','stats':{
            'koukoutu_wins':3,'runpod_wins':1,'ties':1,'koukoutu_average_ms':1200,'runpod_average_ms':2300,
        }})))
    page.set_input_files('#ab-input', {'name':'cat.png','mimeType':'image/png','buffer':base64.b64decode(PIXEL)})
    page.locator('#ab-run').click()
    poll(page, "() => document.getElementById('koukoutu-meta').textContent.includes('background-removal') && document.getElementById('runpod-meta').textContent.includes('BiRefNet')")
    assert sequence == ['single-sequential-endpoint']
    assert page.locator('#koukoutu-image').is_visible()
    assert page.locator('#runpod-image').is_visible()
    assert page.locator('[data-choice="koukoutu"]').is_enabled()
    page.locator('[data-choice="koukoutu"]').click()
    poll(page, "() => document.getElementById('sum-k-win').textContent==='3'")
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    page.set_viewport_size({'width':768,'height':1024})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    page.set_viewport_size({'width':1180,'height':900})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    page.close()
