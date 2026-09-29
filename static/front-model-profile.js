/* 本福丸前台：型號 × 殼款預覽／打印資料契約。缺少正式設定時一律 fail closed。 */
(function () {
  'use strict';
  if (window.__benfuwanModelProfileInstalled) return;
  window.__benfuwanModelProfileInstalled = true;

  const LEGACY_CRYSTAL_STYLE_ID = 'style_1789287807818';
  const text = value => String(value || '').trim();

  function rawProfileFor(model, styleId) {
    if (!model || !styleId) return null;
    const profiles = model.case_profiles && typeof model.case_profiles === 'object' ? model.case_profiles : {};
    if (Object.prototype.hasOwnProperty.call(profiles, styleId)) return profiles[styleId] || {};
    return styleId === LEGACY_CRYSTAL_STYLE_ID ? model : null;
  }

  function profileFor(model, styleId) {
    const raw = rawProfileFor(model, String(styleId || ''));
    const previewUrl = text(raw && raw.preview_mask_img);
    const printUrl = text(raw && raw.print_line_img);
    const printW = Number(raw && raw.print_w);
    const printH = Number(raw && raw.print_h);
    const missing = [];
    if (!previewUrl) missing.push('preview_mask_img');
    if (!printUrl) missing.push('print_line_img');
    if (!(printW > 0)) missing.push('print_w');
    if (!(printH > 0)) missing.push('print_h');
    return Object.freeze({
      ready: missing.length === 0, missing, previewUrl, printUrl, printW, printH,
      printX: Number(raw && raw.print_x) || 0,
      printY: Number(raw && raw.print_y) || 0,
      printAngle: Number(raw && raw.print_angle) || 0,
      legacy: Boolean(raw && raw === model),
    });
  }

  function audit(models, styles) {
    const activeModels = (Array.isArray(models) ? models : []).filter(model => model && model.status !== false);
    const activeStyles = (Array.isArray(styles) ? styles : []).filter(caseStyle => caseStyle && caseStyle.status !== false);
    const configured = [], incomplete = [];
    activeModels.forEach(model => activeStyles.forEach(caseStyle => {
      const key = `${String(model.id || '')}:${String(caseStyle.id || '')}`;
      (profileFor(model, caseStyle.id).ready ? configured : incomplete).push(key);
    }));
    return Object.freeze({ activeModels: activeModels.length, activeStyles: activeStyles.length, configured, incomplete });
  }

  function currentModel() {
    return (shopData.models || []).find(model => String(model.id) === String(ctx.modelId)) || null;
  }

  function currentStyle() {
    return (shopData.styles || []).find(caseStyle => String(caseStyle.id) === String(ctx.styleId)) || null;
  }

  function blockUnconfigured(model, caseStyle) {
    const profile = profileFor(model, caseStyle && caseStyle.id);
    if (profile.ready) return false;
    const name = model && model.name ? `「${model.name}」` : '這個型號';
    const styleName = caseStyle && caseStyle.name ? `的「${caseStyle.name}」` : '的這個殼款';
    toast(`${name}${styleName}尚未完成生產設定，請選擇其他殼款或聯絡店家。`);
    return true;
  }

  const style = document.createElement('style');
  style.textContent = '.style-card.bf-style-unconfigured{opacity:.58}.bf-style-config-badge{position:absolute;left:9px;top:9px;font-size:10px;font-weight:800;color:#9a747f;background:#fff;border:1px solid #eadce1;border-radius:999px;padding:3px 7px;z-index:2}';
  document.head.appendChild(style);

  const originalRenderStyles = window.renderStyles;
  window.renderStyles = function () {
    originalRenderStyles.apply(this, arguments);
    const model = currentModel();
    const styles = (shopData.styles || []).filter(caseStyle => caseStyle && caseStyle.status !== false);
    document.querySelectorAll('#style-grid .style-card').forEach((card, index) => {
      const caseStyle = styles[index];
      if (!caseStyle || profileFor(model, caseStyle.id).ready) return;
      card.classList.add('bf-style-unconfigured');
      card.setAttribute('aria-disabled', 'true');
      card.onclick = () => blockUnconfigured(model, caseStyle);
      const badge = document.createElement('small');
      badge.className = 'bf-style-config-badge';
      badge.textContent = '尚未配置';
      card.appendChild(badge);
    });
  };

  const originalSelectModel = window.selectModel;
  window.selectModel = function (model) {
    originalSelectModel.apply(this, arguments);
    return true;
  };

  const originalSelectStyle = window.selectStyle;
  window.selectStyle = function (caseStyle) {
    const model = currentModel();
    if (blockUnconfigured(model, caseStyle)) return false;
    originalSelectStyle.apply(this, arguments);
    const profile = profileFor(model, caseStyle.id);
    ctx.maskUrl = profile.previewUrl;
    ctx.printLineUrl = profile.printUrl;
    ctx.printX = profile.printX;
    ctx.printY = profile.printY;
    ctx.printW = profile.printW;
    ctx.printH = profile.printH;
    ctx.printAngle = profile.printAngle;
    return true;
  };

  for (const name of ['openTemplatesFromStyle', 'startEditor']) {
    const original = window[name];
    window[name] = function () {
      if (blockUnconfigured(currentModel(), currentStyle())) return false;
      return original.apply(this, arguments);
    };
  }

  window.BenfuwanModelProfile = Object.freeze({ LEGACY_CRYSTAL_STYLE_ID, profileFor, audit });
})();
