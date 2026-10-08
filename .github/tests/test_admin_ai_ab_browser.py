"""Browser-only Admin AI A/B UI regression; paid provider responses are intercepted."""
import base64
import io
import json

from PIL import Image, ImageDraw


ORIGINAL_RGB = (17, 101, 203)


def _png(width, height, rgba, alpha_region=None):
    image = Image.new('RGBA', (width, height), rgba)
    if alpha_region:
        axis, start, alpha = alpha_region
        fill = (rgba[0], rgba[1], rgba[2], alpha)
        if axis == 'x':
            ImageDraw.Draw(image).rectangle((start, 0, width, height), fill=fill)
        else:
            ImageDraw.Draw(image).rectangle((0, start, width, height), fill=fill)
    out = io.BytesIO()
    image.save(out, format='PNG', optimize=True)
    return out.getvalue()


ORIGINAL = _png(2400, 1800, (*ORIGINAL_RGB, 255))
KOUKOUTU_MASK = _png(2400, 1800, (249, 12, 31, 255), ('x', 1200, 64))
RUNPOD_MASK = _png(1800, 1350, (3, 241, 19, 255), ('y', 675, 96))


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
    assert page.locator('script[src*="ai-remove-client-v2.js"]').count() == 1
    page.evaluate("""() => {
      window.__abNormalize = null;
      const api = window.BenfuwanAiRemoveV2;
      const original = api.sourceBlobFromElement;
      api.sourceBlobFromElement = async (element, options) => {
        const blob = await original(element, options);
        const url = URL.createObjectURL(blob);
        const dimensions = await new Promise((resolve, reject) => {
          const image = new Image();
          image.onload = () => resolve({width:image.naturalWidth,height:image.naturalHeight});
          image.onerror = reject;
          image.src = url;
        });
        URL.revokeObjectURL(url);
        window.__abNormalize = {options, ...dimensions, bytes:blob.size, type:blob.type};
        return blob;
      };
    }""")
    page.route('**/api/admin/ai-ab-test/summary', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps({'status':'success','stats':{
            'koukoutu_wins':2,'runpod_wins':1,'ties':1,'koukoutu_average_ms':1200,'runpod_average_ms':2300,
        }})))
    sequence = []
    normalized_upload = {}

    def run(route):
        sequence.append('single-sequential-endpoint')
        normalized_upload['content_type'] = route.request.headers.get('content-type', '')

        def result(provider, model, elapsed, png, width, height):
            return {
                'ok':True,'provider':provider,'model':model,'elapsed_ms':elapsed,
                'width':width,'height':height,'bytes':len(png),
                'valid_alpha':True,'png_base64':base64.b64encode(png).decode(),
            }

        route.fulfill(status=200, content_type='application/json', body=json.dumps({
            'status':'success','original':{'width':2400,'height':1800,'bytes':len(ORIGINAL)},
            'koukoutu':result('koukoutu','background-removal',1200,KOUKOUTU_MASK,2400,1800),
            'runpod':result('runpod','ZhengPeng7/BiRefNet',2300,RUNPOD_MASK,1800,1350),
            'rating_token':'signed-test-token','stats':{'koukoutu_wins':2,'runpod_wins':1,'ties':1,'koukoutu_average_ms':1200,'runpod_average_ms':2300},
            'stats_warning':'',
        }))

    page.route('**/api/admin/ai-ab-test/run', run)
    page.route('**/api/admin/ai-ab-test/rate', lambda route: route.fulfill(
        status=200, content_type='application/json', body=json.dumps({'status':'success','stats':{
            'koukoutu_wins':3,'runpod_wins':1,'ties':1,'koukoutu_average_ms':1200,'runpod_average_ms':2300,
        }})))
    page.set_input_files('#ab-input', {'name':'cat.png','mimeType':'image/png','buffer':ORIGINAL})
    page.locator('#ab-run').click()
    poll(page, "() => !document.querySelector('[data-choice=koukoutu]').disabled || document.getElementById('ab-message').classList.contains('error')")
    assert page.locator('[data-choice="koukoutu"]').is_enabled(), {
        'message': page.locator('#ab-message').inner_text(),
        'koukoutu': page.locator('#koukoutu-meta').inner_text(),
        'runpod': page.locator('#runpod-meta').inner_text(),
        'normalized': page.evaluate('window.__abNormalize'),
    }
    assert sequence == ['single-sequential-endpoint']
    assert 'multipart/form-data' in normalized_upload['content_type']
    normalized = page.evaluate('window.__abNormalize')
    assert normalized['width'] == 2400 and normalized['height'] == 1800
    assert normalized['bytes'] <= int(5.5 * 1024 * 1024)
    assert normalized['type'] == 'image/png'
    assert normalized['options']['maxEdge'] == 4096
    assert normalized['options']['maxBytes'] == 5.5 * 1024 * 1024
    assert page.locator('#koukoutu-image').is_visible()
    assert page.locator('#runpod-image').is_visible()
    assert '2400 × 1800' in page.locator('#koukoutu-meta').inner_text()
    runpod_meta = page.locator('#runpod-meta').inner_text()
    assert '1800 × 1350' in runpod_meta
    assert '2400 × 1800' in runpod_meta

    pixels = page.evaluate("""async () => {
      const read = (id, points) => {
        const image = document.getElementById(id);
        const canvas = document.createElement('canvas');
        canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
        const context = canvas.getContext('2d', {willReadFrequently:true});
        context.drawImage(image, 0, 0);
        return {width:image.naturalWidth,height:image.naturalHeight,pixels:points.map(([x,y])=>Array.from(context.getImageData(x,y,1,1).data))};
      };
      return {
        koukoutu: read('koukoutu-image', [[100,100],[1800,900]]),
        runpod: read('runpod-image', [[100,100],[1200,1400]])
      };
    }""")
    assert pixels['koukoutu']['width'] == 2400 and pixels['koukoutu']['height'] == 1800
    assert pixels['runpod']['width'] == 2400 and pixels['runpod']['height'] == 1800
    assert pixels['koukoutu']['pixels'][0][:3] == list(ORIGINAL_RGB)
    assert pixels['runpod']['pixels'][0][:3] == list(ORIGINAL_RGB)
    assert abs(pixels['koukoutu']['pixels'][1][3] - 64) <= 1
    assert abs(pixels['runpod']['pixels'][1][3] - 96) <= 1

    page.locator('[data-choice="koukoutu"]').click()
    poll(page, "() => document.getElementById('sum-k-win').textContent==='3'")
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    page.set_viewport_size({'width':768,'height':1024})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    page.set_viewport_size({'width':1180,'height':900})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2')
    page.close()
