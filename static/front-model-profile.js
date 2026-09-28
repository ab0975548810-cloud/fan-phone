/* 本福丸前台：型號級預覽／打印資料契約。缺少正式設定時一律 fail closed。 */
(function () {
  'use strict';
  if (window.__benfuwanModelProfileInstalled) return;
  window.__benfuwanModelProfileInstalled = true;

  const text = value => String(value || '').trim();
  function profileFor(model) {
    const previewUrl = text(model && model.preview_mask_img);
    const printUrl = text(model && model.print_line_img);
    const printW = Number(model && model.print_w);
    const printH = Number(model && model.print_h);
    const missing = [];
    if (!previewUrl) missing.push('preview_mask_img');
    if (!printUrl) missing.push('print_line_img');
    if (!(printW > 0)) missing.push('print_w');
    if (!(printH > 0)) missing.push('print_h');
    return Object.freeze({ ready: missing.length === 0, missing, previewUrl, printUrl, printW, printH });
  }

  function audit(models) {
    const active = (Array.isArray(models) ? models : []).filter(model => model && model.status !== false);
    const configured = [], incomplete = [];
    active.forEach(model => (profileFor(model).ready ? configured : incomplete).push(String(model.id || '')));
    return Object.freeze({ active: active.length, configured, incomplete });
  }

  function currentModel() {
    return (shopData.models || []).find(model => String(model.id) === String(ctx.modelId)) || null;
  }

  function blockUnconfigured(model) {
    const profile = profileFor(model);
    if (profile.ready) return false;
    const name = model && model.name ? `「${model.name}」` : '這個型號';
    toast(`${name}尚未完成預覽與可印範圍設定，請選擇其他型號或聯絡店家。`);
    return true;
  }

  const style = document.createElement('style');
  style.textContent = '.model-item.bf-model-unconfigured{opacity:.58;cursor:not-allowed}.bf-model-config-badge{margin-left:auto;font-size:10px;font-weight:800;color:#9a747f;background:#f7eef1;border-radius:999px;padding:3px 7px}.model-item.bf-model-unconfigured>i:last-child{display:none}';
  document.head.appendChild(style);

  const originalRenderModels = window.renderModels;
  window.renderModels = function () {
    originalRenderModels.apply(this, arguments);
    const byName = new Map((shopData.models || []).filter(model => model && model.status !== false).map(model => [String(model.name || ''), model]));
    document.querySelectorAll('#model-list .model-item').forEach(row => {
      const model = byName.get(row.querySelector('span')?.textContent || '');
      if (!model || profileFor(model).ready) return;
      row.classList.add('bf-model-unconfigured');
      row.setAttribute('aria-disabled', 'true');
      row.onclick = () => blockUnconfigured(model);
      const badge = document.createElement('small');
      badge.className = 'bf-model-config-badge';
      badge.textContent = '尚未配置';
      row.insertBefore(badge, row.lastElementChild);
    });
  };

  const originalSelectModel = window.selectModel;
  window.selectModel = function (model) {
    if (blockUnconfigured(model)) return false;
    originalSelectModel.apply(this, arguments);
    const profile = profileFor(model);
    ctx.maskUrl = profile.previewUrl;
    ctx.printLineUrl = profile.printUrl;
    ctx.printW = profile.printW;
    ctx.printH = profile.printH;
    return true;
  };

  const originalSelectStyle = window.selectStyle;
  window.selectStyle = function (caseStyle) {
    const model = currentModel();
    if (blockUnconfigured(model)) return false;
    originalSelectStyle.apply(this, arguments);
    const profile = profileFor(model);
    ctx.maskUrl = profile.previewUrl;
    ctx.printLineUrl = profile.printUrl;
    ctx.printW = profile.printW;
    ctx.printH = profile.printH;
    return true;
  };

  for (const name of ['openTemplatesFromStyle', 'startEditor']) {
    const original = window[name];
    window[name] = function () {
      if (blockUnconfigured(currentModel())) return false;
      return original.apply(this, arguments);
    };
  }

  window.BenfuwanModelProfile = Object.freeze({ profileFor, audit });
  if (typeof shopData !== 'undefined' && Array.isArray(shopData.models) && shopData.models.length) window.renderModels();
})();
