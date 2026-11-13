"""Product routing within the existing model/style/SKU catalog (no new store).

The two historical film models are identified by their stable IDs, never by
customer-visible names. They remain unavailable until an admin explicitly
saves their dedicated product and production profile.
"""
import math

LEGACY_FILM_MODELS = frozenset(('m_1792558304007', 'm_1792566644739'))


def product_type(model):
    return model.get('product_type') or ('camera_film' if model.get('id') in LEGACY_FILM_MODELS else 'phone_case')


def compatible(model, style):
    if not model or not style:
        return False
    kind = product_type(model)
    if kind == 'camera_film':
        return (style.get('product_type') == 'camera_film'
                and bool(model.get('direct_style_id'))
                and str(model['direct_style_id']) == str(style.get('id')))
    return kind == 'phone_case' and style.get('product_type', 'phone_case') == 'phone_case'


def film_ready(model, style):
    if not compatible(model, style):
        return False
    if product_type(model) != 'camera_film':
        return True
    profile = (model.get('case_profiles') or {}).get(style['id']) or {}
    try:
        numbers = [float(profile.get(k)) for k in ('print_w', 'print_h', 'print_x', 'print_y', 'print_angle')]
        price = float(style.get('price'))
        return (all(math.isfinite(n) for n in numbers) and min(numbers[:2]) > 0
                and math.isfinite(price) and price > 0 and price.is_integer()
                and bool(profile.get('preview_mask_img')) and bool(profile.get('print_line_img'))
                and not style.get('colors') and not style.get('model_colors'))
    except (ValueError, TypeError):
        return False
