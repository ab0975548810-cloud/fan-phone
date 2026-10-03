"""Real picker clicks and local PNG success/pending/error presentation."""
import os
from pathlib import Path


def model_cat_icon_test(browser, base, poll):
    for width, height in ((390, 844), (768, 1024), (1180, 900)):
        page = browser.new_page(viewport=dict(width=width, height=height), device_scale_factor=3, has_touch=True)
        page.goto(base+'/', wait_until='domcontentloaded')
        poll(page, "() => window.BenfuwanFrontHomeV1?.isCatalogReady() && document.querySelectorAll('.model-item').length>0")
        page.locator('.bf-home-primary').click()
        poll(page, "() => document.querySelector('#page-model.active')")
        poll(page, """() => [...document.querySelectorAll('.model-cat-icon img')].every(img=>img.complete&&img.naturalWidth>0&&getComputedStyle(img).visibility==='visible')""")
        layout = page.locator('.model-item').first.evaluate("""row=>{
          const img=row.querySelector('.model-cat-icon img'),icon=img.parentElement,name=icon.nextElementSibling,arrow=row.lastElementChild;
          const box=el=>{const r=el.getBoundingClientRect();return {x:r.x,right:r.right,width:r.width,height:r.height}};
          return {icon:box(icon),image:box(img),name:box(name),arrow:box(arrow),fit:getComputedStyle(img).objectFit,shrink:getComputedStyle(icon).flexShrink,fallback:getComputedStyle(icon.querySelector('svg')).visibility};
        }""")
        assert layout['icon']['width']==36 and layout['icon']['height']==32, layout
        assert layout['image']['width']==36 and layout['image']['height']==32, layout
        assert layout['fit']=='contain' and layout['shrink']=='0', layout
        assert layout['name']['width']>100 and layout['icon']['right']<=layout['name']['x'] and layout['name']['right']<=layout['arrow']['x'], layout
        assert layout['fallback']=='hidden', layout
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+2'), width
        if os.environ.get('CAT_ICON_SCREENSHOT_DIR'):
            folder=Path(os.environ['CAT_ICON_SCREENSHOT_DIR']);folder.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(folder/f"{os.environ.get('BROWSER_ENGINE','webkit')}-{width}.png"))
        # Selection and next step are still real, unchanged actions.
        selected_name=page.locator('.model-item').first.locator(':scope > span').nth(1).inner_text()
        page.locator('.model-item').first.click()
        assert page.evaluate('ctx.modelName')==selected_name
        page.locator('#model-next').click()
        assert page.locator('#page-style').is_visible()
        page.close()

    for response_status in (200, 404):
        page=browser.new_page(viewport=dict(width=390,height=844))
        pending=[]
        page.route('**/static/images/benfuwan-cat-peek.png', lambda route:pending.append(route))
        page.goto(base+'/', wait_until='domcontentloaded')
        poll(page, "() => window.BenfuwanFrontHomeV1?.isCatalogReady() && document.querySelectorAll('.model-item').length>0")
        page.locator('.bf-home-primary').click()
        poll(page, "() => document.querySelector('#page-model.active')")
        assert pending
        def presentation():
            return page.locator('.model-cat-icon').evaluate_all("""icons=>icons.map(icon=>({image:getComputedStyle(icon.querySelector('img')).visibility,fallback:getComputedStyle(icon.querySelector('svg')).visibility,loaded:icon.querySelector('img').naturalWidth>0}))""")
        assert all(x==dict(image='hidden',fallback='visible',loaded=False) for x in presentation())
        for route in pending:
            if response_status==200:
                route.fulfill(status=200,content_type='image/png',path=str(Path(__file__).resolve().parents[2]/'static/images/benfuwan-cat-peek.png'))
            else:
                route.fulfill(status=404,content_type='text/plain',body='not found')
        poll(page, "() => [...document.querySelectorAll('.model-cat-icon img')].every(img=>img.complete)")
        expected=dict(image='visible',fallback='hidden',loaded=True) if response_status==200 else dict(image='hidden',fallback='visible',loaded=False)
        assert all(x==expected for x in presentation()), (response_status,presentation())
        page.close()
    print('MODEL_CAT_ICON_RESPONSIVE_NO_FLASH_FALLBACK_OK')

