"""Trusted revision rendering. Historical print evidence, never current catalog data."""
import copy
import hashlib

from design_sources import read
from order_designs import asset_paths, check_restore, persist_asset, protect_layers


def render_revision(app, order_id, document):
    """Adapt validated archived private assets without weakening the order renderer."""
    import editable_stickers
    check_restore(document)
    candidate = copy.deepcopy(document)
    paths = asset_paths(candidate)
    archive_prefix = f'order-design/{order_id}/' if app.USE_SUPABASE else f'order-design_{order_id}_'
    source_prefix = f'orders/{order_id}/sources/' if app.USE_SUPABASE else f'orders_{order_id}_sources_'
    mapping, resources = {}, {}
    for path in paths:
        if not isinstance(path, str) or not path.startswith(archive_prefix) or '..' in path or '\\' in path:
            raise ValueError('修改版素材不屬於此訂單的私有封存')
        raw = read(app, path)
        hashed = hashlib.sha256(raw).hexdigest()
        if not path.endswith(hashed + '.png'):
            raise ValueError('修改版封存素材雜湊不符')
        target = source_prefix + hashed + '.png'
        mapping[path], resources[target] = target, raw
    def replace(value):
        if isinstance(value, str): return mapping.get(value, value)
        if isinstance(value, list): return [replace(v) for v in value]
        if isinstance(value, dict): return {k: replace(v) for k, v in value.items()}
        return value
    candidate = replace(candidate)
    # Only server-validated frozen revisions reach here. Client seals are never trusted.
    if candidate.get('layer_contract_version') == 'multilayer-v1':
        from multilayer_templates import seal
        seal(app, candidate, order_id)
    profile = {'width_mm': candidate['production']['printW'], 'height_mm': candidate['production']['printH']}
    _, raw, _ = editable_stickers.render(app, {'id': order_id, 'design_json': candidate}, profile, resources.__getitem__)
    return raw


def prepare(app, order_id, original, candidate):
    """A failed proof never discards a staff draft; dispatch remains unavailable."""
    from pixel_order_designs import historical_profile, png, sha
    unavailable = {'mode': 'layered-v1', 'profile': None}
    try:
        jobs = app.print_center.store.jobs_for_order(order_id)
        if not any(j.get('profile_complete') and not j.get('manual_independent') for j in jobs):
            return {**unavailable, 'reason': '缺少原始列印任務定位證據；草稿已保存，禁止送印'}
        check_restore(original)
        protect_layers(original, candidate)
        base_raw = render_revision(app, order_id, original)
        base_image = png(base_raw, dpi=True)
        profile = historical_profile(app, {'id': order_id}, base_raw, base_image.size)
        if not profile:
            return {**unavailable, 'reason': 'V1 重建圖與歷史列印任務雜湊不符，禁止使用現行定位送印'}
        source = next(j for j in jobs if j['id'] == profile['sourceJobId'])
        actual = read(app, source['artwork_path'])
        if sha(actual) != sha(base_raw):
            raise ValueError('原始列印任務的生產圖雜湊不符')
        output = render_revision(app, order_id, candidate)
        png(output, base_image.size, True)
        return {'mode': 'layered-v1', 'profile': profile, 'dpi': 720,
                'basePath': persist_asset(app, order_id, actual), 'baseSha': sha(actual),
                'outputPath': persist_asset(app, order_id, output), 'outputSha': sha(output),
                'size': list(base_image.size), 'proof': {'historicalV1Exact': True, 'frozenGeometry': True}}
    except Exception as exc:
        # Proof availability must not discard an already validated staff draft.
        # Remote exceptions can contain credentials or signed URLs; log only type.
        app.app.logger.warning('revision_proof_unavailable order_ref=%s exception_type=%s',hashlib.sha256(order_id.encode()).hexdigest()[:12],type(exc).__name__)
        return {**unavailable, 'reason': '原始素材、字型或歷史生產圖驗證未通過；草稿已保存，禁止送印'}
