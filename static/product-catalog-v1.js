/* Shared public/admin product routing. Keep in parity with catalog_products.py. */
(function () {
  'use strict';
  const legacyFilmIds = new Set(['m_1792558304007', 'm_1792566644739']);
  const type = model => model?.product_type || (legacyFilmIds.has(model?.id) ? 'camera_film' : 'phone_case');
  function compatible(model, style) {
    if (!model || !style) return false;
    if (type(model) === 'camera_film') return style.product_type === 'camera_film' && !!model.direct_style_id && String(model.direct_style_id) === String(style.id);
    return type(model) === 'phone_case' && (style.product_type || 'phone_case') === 'phone_case';
  }
  function ready(model, style) {
    if (!compatible(model, style)) return false;
    if (type(model) !== 'camera_film') return true;
    const p = model.case_profiles?.[style.id];
    return !!p && !!p.preview_mask_img && !!p.print_line_img &&
      ['print_w','print_h','print_x','print_y','print_angle'].every(k => p[k] !== null && p[k] !== '' && Number.isFinite(Number(p[k]))) &&
      p.print_w > 0 && p.print_h > 0 && Number.isInteger(Number(style.price)) && Number(style.price) > 0 &&
      !(style.colors?.length) && !Object.keys(style.model_colors || {}).length;
  }
  window.BenfuwanProducts = Object.freeze({type, compatible, ready});
})();
