"""Order-owned alignment artwork in the existing print PNG coordinate space."""
import base64
import io
import math

from PIL import Image, ImageChops, ImageFilter

from design_sources import read
from editable_stickers import public_image
from print_center import _complete_model_style_profile


def alignment(app, order, size=None, verified_profile=None):
    design = order.get('design_json') or {}
    if not isinstance(design, dict):
        return missing()
    production = design.get('production') or {}
    context = design.get('editorContext') or {}
    if not isinstance(production, dict) or not isinstance(context, dict):
        return missing()
    path = production.get('maskPath')
    prefix = f'orders/{order["id"]}/sources/' if app.USE_SUPABASE else f'orders_{order["id"]}_sources_'
    if (not isinstance(path, str) or not path.startswith(prefix) or '..' in path
            or '\\' in path or design.get('modelId') != order.get('model_id')
            or design.get('styleId') != order.get('style_id')):
        return missing()
    try:
        geometry = tuple(float(value) for value in (
            production['printW'], production['printH'], context['printX'],
            context['printY'], context['printAngle']))
        if not all(map(math.isfinite, geometry)) or min(geometry[:2]) <= 0:
            return missing()
        if size and any(abs(int(math.floor(mm * 720 / 25.4 + .5)) - pixels) > 1
               for mm, pixels in zip(geometry[:2], size)):
            return missing()
        if verified_profile:
            job_geometry = tuple(float(verified_profile[key]) for key in (
                'width_mm', 'height_mm', 'left_mm', 'top_mm', 'angle'))
            if any(not math.isclose(a,b,rel_tol=0,abs_tol=.05) for a,b in zip(geometry,job_geometry)):
                return missing()
        raw = read(app, path)
        guide = guide_png(raw, size) if size else None
    except (KeyError, TypeError, ValueError, OSError):
        return missing()
    except Exception:
        return {'note':'原始蒙版暫時無法讀取，保留原圖編輯。'}

    note = '使用此訂單封存的原始刀模。粉色邊線標示印刷範圍與孔位。'
    try:
        catalog = app.cloud_get_json('shop_data', app.DATA_FILE, app.DEFAULT_SHOP_DATA)
        model = next((item for item in catalog['models'] if item['id'] == order['model_id']), {})
        current = _complete_model_style_profile(model, order['style_id'])
        if not current:
            note += ' 目前後台已無相符的商品設定。'
        else:
            present = tuple(float(current[key]) for key in ('print_w','print_h','print_x','print_y','print_angle'))
            if present != geometry or public_image(app, current['print_line_img']) != raw:
                note += ' 目前後台的刀模或定位已不同，仍使用原始版本。'
    except Exception:
        note += ' 目前設定暫時無法比對。'
    result = {'note': note}
    if guide:
        result['guide'] = 'data:image/png;base64,' + base64.b64encode(guide).decode()
    return result


def missing():
    return {'note':'此舊訂單缺少可核對的原始蒙版或列印定位。保留原圖編輯，未套用目前商品蒙版。'}


def guide_png(raw, size):
    with Image.open(io.BytesIO(raw)) as image:
        if image.format != 'PNG' or image.width * image.height > 18_000_000:
            raise ValueError('Invalid alignment image')
        alpha = image.convert('RGBA').getchannel('A')
    bounds = alpha.getbbox()
    if not bounds or alpha.getextrema()[0] != 0:
        raise ValueError('Invalid alignment alpha')
    scale = min(1, 1200 / max(size))
    preview_size = tuple(max(1, round(n * scale)) for n in size)
    # The print renderer normalizes the nontransparent bounds before resizing.
    area = alpha.crop(bounds).resize(preview_size, Image.Resampling.LANCZOS).point(lambda x: 255 if x >= 24 else 0)
    padded = Image.new('L', (area.width + 2, area.height + 2))
    padded.paste(area, (1, 1))
    inset = padded.filter(ImageFilter.MinFilter(3)).crop((1, 1, area.width + 1, area.height + 1))
    outline = ImageChops.subtract(area, inset)
    guide = Image.new('RGBA', preview_size, (251, 240, 247, 0))
    guide.putalpha(area.point(lambda x: 25 if x else 0))
    edge = Image.new('RGBA', preview_size, (232, 35, 118, 0))
    edge.putalpha(outline)
    output = io.BytesIO()
    Image.alpha_composite(guide, edge).save(output, 'PNG')
    return output.getvalue()
