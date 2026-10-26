"""One immutable-master -> case target transform, shared by preview and authority.

No production dimensions, source pixels, checkout or printer operations change.
The contract is opt-in; unconverted legacy templates retain their old renderer.
"""
import copy
import hashlib
import io
import json
import math
import threading
import time
import uuid
from collections import OrderedDict

from PIL import Image, ImageChops, ImageDraw, ImageFilter

VERSION = 'master-v1'
ROLES = ('composition', 'subject', 'important-text', 'background-crop', 'decoration')
_MASKS = OrderedDict()
_LOCK = threading.Lock()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def number(value, default=0):
    try:
        n = float(value)
        return n if math.isfinite(n) else default
    except (TypeError, ValueError):
        return default


def raw(template):
    value = template.get('objects_json')
    return json.loads(value) if isinstance(value, str) else copy.deepcopy(value or {})


def content_hash(template):
    return digest({'objects_json':raw(template),'slots':template.get('slots') or [],
                   **{key:template.get(key) for key in ('source_canvas_w','source_canvas_h','source_print_w','source_print_h')}})


def validate(template):
    if template.get('adaptation_contract_version') != VERSION:
        return
    if template.get('adaptation_target') and template.get('adaptation_content_hash') != content_hash(template):
        raise ValueError('型號版本內容已改變，請從原始母版重新微調與驗證')
    data = raw(template)
    if not isinstance(data.get('objects'), list) or not 1 <= len(data['objects']) <= 100:
        raise ValueError('母版需有 1～100 個獨立物件')
    if not all(number(template.get('source_canvas_' + axis)) > 0 for axis in ('w', 'h')):
        raise ValueError('母版缺少原始畫布尺寸')
    if not all(number(template.get('source_print_' + axis)) > 0 for axis in ('w', 'h')):
        raise ValueError('母版缺少原始列印尺寸')
    for item in data['objects']:
        if item.get('adaptationRole', 'composition') not in ROLES:
            raise ValueError('母版元素適配策略無效')
        # Skew/group geometry cannot be safely approximated by rotated rectangles.
        if item.get('objects') or number(item.get('skewX')) or number(item.get('skewY')):
            raise ValueError('母版尚不支援群組／斜切，請保留為一般舊模板')


def targets(shop):
    from catalog_products import compatible, product_type
    from print_center import _complete_model_style_profile
    rows = []
    for model in shop.get('models', []):
        if model.get('status') is False or product_type(model) != 'phone_case':
            continue
        for style in shop.get('styles', []):
            profile = _complete_model_style_profile(model, style.get('id'))
            if style.get('status') is False or not compatible(model, style) or not profile:
                continue
            if not all(profile.get(k) is not None and profile.get(k) != '' and
                       math.isfinite(number(profile[k], math.nan)) for k in ('print_w', 'print_h', 'print_x', 'print_y', 'print_angle')):
                continue
            rows.append({'model_id': model['id'], 'style_id': style['id'], 'model_name': model.get('name', model['id']),
                         'style_name': style.get('name', style['id']), 'profile': profile})
    return rows


def target_for(shop, model_id, style_id):
    found = next((t for t in targets(shop) if t['model_id'] == model_id and t['style_id'] == style_id), None)
    if not found:
        raise ValueError('此手機殼型號 × 殼款沒有完整有效的列印設定')
    return found


def mask(app, url):
    """Full source frame; internal camera holes are never cropped away."""
    from editable_stickers import public_image
    with _LOCK:
        cached = _MASKS.get(url)
        if cached and time.monotonic() - cached[0] < 60:
            _MASKS.move_to_end(url)
            return cached[1]
    content = public_image(app, url)
    with Image.open(io.BytesIO(content)) as image:
        alpha = image.convert('RGBA').getchannel('A')
        if not alpha.getbbox():
            raise ValueError('刀模沒有可印區')
        # Bounded analysis canvas, preserves source aspect; output pixels are unchanged.
        ratio = 384 / max(image.size)
        size = (max(16, round(image.width * ratio)), max(16, round(image.height * ratio)))
        binary = alpha.point(lambda p:255 if p>=224 else 0)
        # Conservative min-pooling, not average interpolation: even a tiny hole
        # in a high-resolution source must make its analysis cell unsafe.
        safe = Image.new('L',size)
        cells=[]
        for y in range(size[1]):
            top=math.floor(y*alpha.height/size[1]);bottom=math.ceil((y+1)*alpha.height/size[1])
            for x in range(size[0]):
                left=math.floor(x*alpha.width/size[0]);right=math.ceil((x+1)*alpha.width/size[0])
                cells.append(binary.crop((left,top,right,bottom)).getextrema()[0])
        safe.putdata(cells)
        safe = safe.filter(ImageFilter.MinFilter(5))
    result = (safe, hashlib.sha256(content).hexdigest())
    with _LOCK:
        _MASKS[url] = (time.monotonic(), result)
        while len(_MASKS) > 32:
            _MASKS.popitem(last=False)
    return result


def source_geometry(item, width, height):
    g = item.get('normalizedGeometry')
    if g:
        return dict(x=number(g['x']) * width, y=number(g['y']) * height,
                    width=number(g['width']) * width, height=number(g['height']) * height)
    sx, sy = abs(number(item.get('scaleX'), 1)), abs(number(item.get('scaleY'), 1))
    sw = 0 if item.get('strokeUniform') else number(item.get('strokeWidth'))
    w, h = (number(item.get('width')) + sw) * sx, (number(item.get('height')) + sw) * sy
    if item.get('strokeUniform'):
        w += number(item.get('strokeWidth')); h += number(item.get('strokeWidth'))
    dx = w * (.5 if item.get('originX', 'left') == 'left' else -.5 if item.get('originX') == 'right' else 0)
    dy = h * (.5 if item.get('originY', 'top') == 'top' else -.5 if item.get('originY') == 'bottom' else 0)
    a = math.radians(number(item.get('angle')))
    return dict(x=number(item.get('left')) + dx * math.cos(a) - dy * math.sin(a),
                y=number(item.get('top')) + dx * math.sin(a) + dy * math.cos(a), width=w, height=h)


def corners(g, angle):
    a = math.radians(angle); co, si = math.cos(a), math.sin(a)
    return [(g['x'] + dx * co - dy * si, g['y'] + dx * si + dy * co)
            for dx, dy in ((-g['width']/2, -g['height']/2), (g['width']/2, -g['height']/2),
                           (g['width']/2, g['height']/2), (-g['width']/2, g['height']/2))]


def check(rows, safe, tw, th):
    issues = []
    for identity, item, g in rows:
        if item.get('adaptationRole') == 'background-crop':
            continue
        if not (0<=g['x']<=tw and 0<=g['y']<=th and 0<g['width']<=tw and 0<g['height']<=th):
            issues.append({'layerId':identity,'reason':'geometry-outside-contract'})
            continue
        if item.get('visible') is False or item.get('isTplBg'):
            continue
        points = corners(g, number(item.get('angle')))
        outside = any(x < 0 or y < 0 or x > tw or y > th for x, y in points)
        footprint = Image.new('L', safe.size)
        ImageDraw.Draw(footprint).polygon([(x/tw*safe.width, y/th*safe.height) for x, y in points], fill=255)
        collision = ImageChops.subtract(footprint, safe).getbbox() is not None
        if outside or collision:
            issues.append({'layerId': identity, 'reason': 'outside-canvas' if outside else 'mask-or-safety-area'})
    return issues


def adjustment(value):
    value = value or {}
    if not isinstance(value, dict) or set(value) - {'x', 'y', 'scale', 'layers'}:
        raise ValueError('型號微調設定無效')
    result = {key: number(value.get(key), default) for key, default in (('x', 0), ('y', 0), ('scale', 1))}
    if abs(result['x']) > .15 or abs(result['y']) > .15 or not .5 <= result['scale'] <= 1.15:
        raise ValueError('型號微調超出安全範圍')
    result['layers'] = value.get('layers') or {}
    if not isinstance(result['layers'], dict) or len(result['layers']) > 100:
        raise ValueError('元素微調設定無效')
    for key, offset in result['layers'].items():
        if not isinstance(offset, dict) or set(offset) - {'x', 'y'} or any(abs(number(offset.get(a))) > .1 for a in ('x', 'y')):
            raise ValueError('裝飾微調超出安全範圍')
    return result


def adapt(template, target, safe, mask_hash, overrides=None, auto=True):
    """Pure function. Does not mutate master, target, mask or any prior result."""
    validate(template)
    if template.get('adaptation_contract_version') != VERSION:
        raise ValueError('請先確認此模板為不可變母版')
    if template.get('adaptation_target'):
        raise ValueError('不可從已適配版本再次轉換；請開啟原始母版')
    profile = target['profile']; sw, sh = number(template['source_canvas_w']), number(template['source_canvas_h'])
    # Mirror the existing rounded customer logical canvas exactly, expressed in
    # admin units (the existing legacy base renderer multiplies by 3/2).
    tw, th = math.floor(number(profile['print_w']) * 3 + .5) / 1.5, math.floor(number(profile['print_h']) * 3 + .5) / 1.5
    if not 0 < tw <= 2000 or not 0 < th <= 2000:
        raise ValueError('目標畫布尺寸無效')
    options = adjustment(overrides); data = raw(template); objects = data['objects']
    source = [(str(o.get('layerId') or 'object-'+str(i)), o, source_geometry(o, sw, sh)) for i, o in enumerate(objects)]
    # Legacy slots are millimetres, serialized on the same source canvas transform.
    for i, slot in enumerate(template.get('slots') or []):
        mx, my = sw/number(template['source_print_w']), sh/number(template['source_print_h'])
        w, h = number(slot.get('w', slot.get('width'))) * mx, number(slot.get('h', slot.get('height'))) * my
        source.append(('slot-'+str(i), slot, dict(x=number(slot.get('x'))*mx+w/2, y=number(slot.get('y'))*my+h/2, width=w, height=h)))
    unknown = set(options['layers']) - {i for i, _, _ in source}
    if unknown:
        raise ValueError('未知母版元素')
    for identity, item, _ in source:
        if identity in options['layers'] and item.get('adaptationRole') != 'decoration':
            raise ValueError('只有明確標記的可移動裝飾能獨立微調')
    base = min(tw/sw, th/sh) * options['scale']

    def mapped(dx=0, dy=0):
        rows = []
        for identity, item, g in source:
            offset = options['layers'].get(identity, {})
            ng = dict(x=tw/2+(g['x']-sw/2)*base+(options['x']+number(offset.get('x')))*tw+dx,
                      y=th/2+(g['y']-sh/2)*base+(options['y']+number(offset.get('y')))*th+dy,
                      width=g['width']*base, height=g['height']*base)
            if item.get('adaptationRole') == 'background-crop':
                # A cover operation is uniform; source crop is performed by the existing print clip.
                cover = max(tw/max(.001, g['width']), th/max(.001, g['height']))
                ng = dict(x=tw/2, y=th/2, width=g['width']*cover, height=g['height']*cover)
            rows.append((identity, item, ng))
        return rows

    rows = mapped(); issues = check(rows, safe, tw, th); delta = (0, 0)
    if issues and auto:
        # Try the smallest translation first, with a strict 4% canvas bound.
        # No per-object shuffling, stretching, resizing or invented generic safe box.
        shifts = sorted(((x*tw*.01, y*th*.01) for x in range(-4, 5) for y in range(-4, 5) if x or y), key=lambda p: (math.hypot(*p), p))
        for dx, dy in shifts:
            candidate = mapped(dx, dy)
            if not check(candidate, safe, tw, th):
                rows, issues, delta = candidate, [], (dx, dy)
                break
    out = copy.deepcopy(template)
    for i, (_, item, g) in enumerate(rows[:len(objects)]):
        obj = data['objects'][i]
        obj['normalizedGeometry'] = dict(x=g['x']/tw, y=g['y']/th, width=g['width']/tw, height=g['height']/th)
        obj.update(left=g['x'], top=g['y'], originX='center', originY='center')
        # Fabric pixel dimensions remain unchanged; text reflow is never introduced.
        original = source[i][2]
        swidth = number(item.get('strokeWidth'))
        fixed_stroke = swidth if item.get('strokeUniform') else 0
        scaled_stroke = 0 if item.get('strokeUniform') else swidth
        # normalizedGeometry is the source of truth. Raw Fabric scaleX/Y were
        # rounded to two decimals at save and must not be multiplied again.
        obj['scaleX'] = (g['width']-fixed_stroke)/max(.00001, number(item.get('width'))+scaled_stroke)
        obj['scaleY'] = (g['height']-fixed_stroke)/max(.00001, number(item.get('height'))+scaled_stroke)
        if item.get('adaptationRole') == 'background-crop':
            # Cover by changing the SOURCE crop viewport, never by stretching.
            if item.get('type') not in ('image', 'rect') or number(item.get('angle')):
                raise ValueError('可裁切背景需為未旋轉圖片或矩形')
            # Choose a source crop on a two-decimal grid with the EXACT target
            # aspect ratio. Independent rounding of width/height would introduce
            # a small stretch when Fabric later maps normalized width/height.
            cw, ch = round(tw*1.5), round(th*1.5)
            unit = math.floor(min(number(item['width'])/cw,number(item['height'])/ch)*100)/100
            if unit <= 0:raise ValueError('背景素材尺寸不足，無法安全裁切')
            new_w, new_h = cw*unit, ch*unit
            cover = tw/new_w
            obj['scaleX'] = obj['scaleY'] = cover
            if item.get('type') == 'image':
                obj['cropX'] = max(0,round(number(item.get('cropX'))+(number(item.get('width'))-new_w)/2, 2))
                obj['cropY'] = max(0,round(number(item.get('cropY'))+(number(item.get('height'))-new_h)/2, 2))
            # Match Fabric 5's existing NUM_FRACTION_DIGITS=2 serialization,
            # without loosening locked-layer content validation at checkout.
            obj.update(width=round(new_w, 2), height=round(new_h, 2), left=tw/2, top=th/2,
                       normalizedGeometry=dict(x=.5, y=.5, width=1, height=1))
        # Absolute clipping belongs to the same canvas transform, not a second mapping.
        clip = obj.get('clipPath')
        if clip and clip.get('absolutePositioned'):
            if number(clip.get('skewX')) or number(clip.get('skewY')):
                raise ValueError('母版裁切不支援斜切')
            clip['left'] = tw/2+(number(clip.get('left'))-sw/2)*base+options['x']*tw+delta[0]
            clip['top'] = th/2+(number(clip.get('top'))-sh/2)*base+options['y']*th+delta[1]
            clip['scaleX'] = number(clip.get('scaleX'), 1)*base
            clip['scaleY'] = number(clip.get('scaleY'), 1)*base
            for key in ('left','top','scaleX','scaleY'):clip[key]=round(clip[key], 2)
    out['slots'] = [{**copy.deepcopy(slot), 'x':(g['x']-g['width']/2)/2, 'y':(g['y']-g['height']/2)/2, 'w':g['width']/2, 'h':g['height']/2}
                    for (_, slot, g) in rows[len(objects):]]
    data['sourceCanvas'] = dict(width=tw, height=th)
    out.update(objects_json=data, source_canvas_w=tw, source_canvas_h=th,
               source_print_w=profile['print_w'], source_print_h=profile['print_h'])
    profile_hash = digest({k: profile.get(k) for k in ('print_w', 'print_h', 'print_line_img', 'preview_mask_img')})
    out['adaptation_target'] = dict(model_id=target['model_id'], style_id=target['style_id'], profile_hash=profile_hash, mask_hash=mask_hash)
    out['adaptation_overrides'] = options
    # Measured residuals, rather than claiming a successful visual fit from a scale alone.
    aspect_errors = []
    layout = []
    for (identity, item, before), (_, _, after) in zip(source, rows):
        crop = item.get('adaptationRole') == 'background-crop'
        error = 0 if crop else abs(after['width']/max(.00001, after['height']) - before['width']/max(.00001, before['height']))
        if not crop:aspect_errors.append(error)
        layout.append(dict(layerId=identity, source=before, target=after, angle=number(item.get('angle')),
                           strategy=item.get('adaptationRole','composition'), aspectError=error))
    distances = []
    regular = [(a,b) for a,b in zip(source,rows) if a[1].get('adaptationRole')!='background-crop' and a[0] not in options['layers']]
    if regular:
        a,b=regular[0]
        for c,d in regular[1:]:
            length=lambda p,q:math.hypot(p['x']-q['x'],p['y']-q['y'])
            distances.append(abs(length(b[2],d[2])-length(a[2],c[2])*base))
    out['adaptation_report'] = dict(status='needs-adjustment' if issues else 'success', issues=issues,
        scale=base, translation=dict(x=(tw-sw*base)/2+options['x']*tw+delta[0], y=(th-sh*base)/2+options['y']*th+delta[1]),
        autoShift=dict(x=delta[0], y=delta[1]), sourceCanvas=dict(width=sw, height=sh), targetCanvas=dict(width=tw, height=th),
        maskHash=mask_hash, safetyPixels=2, analysisSize=list(safe.size), maxAspectError=max(aspect_errors,default=0),
        relativeDistanceError=max(distances,default=0), layers=layout, masterHash=digest(template), engine=VERSION)
    out['adaptation_content_hash'] = content_hash(out)
    return out


def resolve(app, template, shop, model_id, style_id):
    """Authoritative result for both public application and permission checks."""
    if template.get('adaptation_contract_version') != VERSION:
        return template
    validate(template)
    target = target_for(shop, model_id, style_id); safe, sha = mask(app, target['profile']['print_line_img'])
    if template.get('adaptation_target'):
        expected = template['adaptation_target']
        profile_hash = digest({k: target['profile'].get(k) for k in ('print_w', 'print_h', 'print_line_img', 'preview_mask_img')})
        if expected != dict(model_id=model_id, style_id=style_id, profile_hash=profile_hash, mask_hash=sha):
            raise ValueError('此型號套版已過期，請店家從原始母版重新預覽')
        result = template
    else:
        result = adapt(template, target, safe, sha)
    if result['adaptation_report']['status'] != 'success':
        raise ValueError('此模板在目前型號需要人工微調，請選擇其他模板')
    return result


def install(app):
    def shop():
        return app.cloud_get_json('shop_data', app.DATA_FILE, app.DEFAULT_SHOP_DATA)

    @app.app.route('/api/admin/template-adaptation/targets')
    def adaptation_targets():
        if not app.session.get('logged_in'):
            return app.no_cache_json({'status':'error'}, 401)
        return app.no_cache_json({'status':'success', 'targets':targets(shop())})

    @app.app.route('/api/admin/template-adaptation/preview', methods=['POST'])
    def adaptation_preview():
        if not app.session.get('logged_in'):
            return app.no_cache_json({'status':'error'}, 401)
        try:
            body = app.request.get_json() or {}; master = copy.deepcopy(body['master']); validate(master)
            target = target_for(shop(), body['model_id'], body['style_id'])
            safe, sha = mask(app, target['profile']['print_line_img'])
            result = adapt(master, target, safe, sha, body.get('overrides'), auto=not bool(body.get('overrides')))
            return app.no_cache_json({'status':'success', 'template':result, 'report':result['adaptation_report']})
        except (ValueError, KeyError, TypeError) as exc:
            return app.no_cache_json({'status':'error','msg':str(exc)}, 400)
        except Exception:
            return app.no_cache_json({'status':'error','msg':'刀模或素材無法讀取，未進行套版'}, 503)

    @app.app.route('/api/template_adaptation/<template_id>')
    def public_adaptation(template_id):
        try:
            data = app.cloud_get_json('templates', app.TEMPLATES_FILE, app.DEFAULT_TEMPLATES)
            template = next(t for t in data.get('templates', []) if t.get('id') == template_id)
            result = resolve(app, template, shop(), app.request.args.get('model_id'), app.request.args.get('style_id'))
            return app.no_cache_json({'status':'success','template':result})
        except (ValueError, KeyError, StopIteration) as exc:
            return app.no_cache_json({'status':'error','msg':str(exc) or '模板不存在'}, 400)
        except Exception:
            return app.no_cache_json({'status':'error','msg':'刀模無法驗證，請稍後再試'}, 503)

    @app.app.route('/api/admin/template-adaptation/save', methods=['POST'])
    def adaptation_save():
        if not app.session.get('logged_in'):
            return app.no_cache_json({'status':'error'}, 401)
        try:
            from multilayer_templates import prepare_template
            body = app.request.get_json() or {}; master = copy.deepcopy(body['master']); validate(master)
            # Only create NEW templates: a batch can never overwrite an existing master/variant.
            document, version = app.cloud_get_json_versioned('templates', app.TEMPLATES_FILE, app.DEFAULT_TEMPLATES)
            if body.get('expected_version') != version:
                raise app.StaleDataError()
            master['id'] = 'master_'+uuid.uuid4().hex
            master.pop('adaptation_target', None); master.pop('adaptation_report', None)
            images = {}; prepare_template(app, master, images)
            selected = body.get('targets')
            if not isinstance(selected, list) or not 1 <= len(selected) <= 200:
                raise ValueError('請選擇 1～200 個已確認型號')
            next_ = copy.deepcopy(document); new = [master]; seen = set(); catalog = shop()
            for spec in selected:
                key = (spec['model_id'], spec['style_id'])
                if key in seen:
                    raise ValueError('不可重複儲存同一型號 × 殼款')
                seen.add(key); target = target_for(catalog, *key)
                safe, sha = mask(app, target['profile']['print_line_img'])
                variant = adapt(master, target, safe, sha, spec.get('overrides'), auto=not bool(spec.get('overrides')))
                if variant['adaptation_report']['status'] != 'success':
                    raise ValueError(target['model_name']+'仍需要人工微調，整批未儲存')
                variant.update(thumb_url=spec.get('thumb_url',''), id='adapted_'+uuid.uuid4().hex, master_template_id=master['id'], master_hash=digest(master),
                               name=master['name']+' · '+target['model_name'], case_style_id=target['style_id'],
                               reference_model_id=target['model_id'],reference_style_id=target['style_id'])
                prepare_template(app, variant, images); new.append(variant)
            next_.setdefault('templates', []).extend(new)
            if master.get('category') not in next_.setdefault('categories', []):
                next_['categories'].append(master.get('category') or '熱門')
            saved = app.cloud_compare_and_swap_json('templates', app.TEMPLATES_FILE, next_, version)
            return app.no_cache_json({'status':'success', 'version':saved, 'ids':[t['id'] for t in new]})
        except app.StaleDataError as exc:
            return app.no_cache_json({'status':'error','code':'STALE_DATA','msg':str(exc)}, 409)
        except (ValueError, KeyError, TypeError) as exc:
            return app.no_cache_json({'status':'error','msg':str(exc)}, 400)
        except Exception:
            return app.no_cache_json({'status':'error','msg':'批次儲存失敗，請重新檢查資料'}, 503)
