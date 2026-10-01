/* 本福丸後台：型號 × 殼款生產設定。 */
(function () {
  'use strict';
  if (window.__benfuwanModelProfilesAdminInstalled) return;
  window.__benfuwanModelProfilesAdminInstalled = true;

  const LEGACY_CRYSTAL_STYLE_ID = 'style_1789287807818';
  let editingModel = null;
  let activeStyleId = '';
  let profileSnapshot = '';

  const notify = (message, type = 'error') => {
    const workspace = window.BenfuwanAdminProductWorkspace;
    if (workspace && typeof workspace.notify === 'function') workspace.notify(message, type);
    else alert(message);
  };

  const activeStyles = () => (shopData.styles || []).filter(row => row && row.status !== false && row.id);
  const complete = profile => Boolean(
    profile && String(profile.preview_mask_img || '').trim() && String(profile.print_line_img || '').trim()
    && Number(profile.print_w) > 0 && Number(profile.print_h) > 0
  );
  function profileFor(model, styleId) {
    if (!model || !styleId) return null;
    const profiles = model.case_profiles && typeof model.case_profiles === 'object' ? model.case_profiles : {};
    if (Object.prototype.hasOwnProperty.call(profiles, styleId)) return profiles[styleId] || {};
    return styleId === LEGACY_CRYSTAL_STYLE_ID ? model : null;
  }
  window.BenfuwanCaseProfiles = Object.freeze({LEGACY_CRYSTAL_STYLE_ID, profileFor, complete});

  function ensureStyles() {
    if (document.getElementById('bf-model-profile-admin-style')) return;
    const style = document.createElement('style');
    style.id = 'bf-model-profile-admin-style';
    style.textContent = `
      .bf-profile-tabs{display:flex;gap:7px;overflow:auto;padding:4px 0 12px}.bf-profile-tab{border:1px solid #eadce1;background:#fff;border-radius:999px;padding:8px 12px;white-space:nowrap;font-size:12px;font-weight:900;color:#766a70;cursor:pointer}.bf-profile-tab.active{background:var(--pink);border-color:var(--pink);color:#fff}.bf-profile-tab .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:5px;background:#dc5064}.bf-profile-tab.ready .dot{background:#27a266}.bf-profile-tab.active .dot{box-shadow:0 0 0 2px rgba(255,255,255,.45)}
      .bf-profile-panel{border:1px solid #f1dfe6;border-radius:16px;padding:13px;background:#fffafb}.bf-profile-heading{display:flex;justify-content:space-between;gap:10px;align-items:center;margin-bottom:10px}.bf-profile-heading b{color:#d95680}.bf-profile-state{font-size:11px;font-weight:900}.bf-profile-state.ready{color:#27a266}.bf-profile-state.bad{color:#dc5064}.bf-profile-state.legacy{color:#8e6bc5}.bf-model-profile-statuses{display:flex;gap:5px;flex-wrap:wrap}.bf-model-profile-status{display:inline-flex;padding:4px 8px;border-radius:999px;font-size:10px;font-weight:900}.bf-model-profile-status.ready{background:#eaf8f1;color:#218657}.bf-model-profile-status.bad{background:#fff0f2;color:#c94d60}
      @media(max-width:680px){.bf-profile-heading{align-items:flex-start;flex-direction:column}}
    `;
    document.head.appendChild(style);
  }

  function renderModelList() {
    ensureStyles();
    const body = document.getElementById('models-body');
    if (!body) return;
    const styles = activeStyles(), models = shopData.models || [];
    body.innerHTML = models.length ? models.map((model, index) => {
      const statuses = styles.length ? styles.map(caseStyle => {
        const ready = complete(profileFor(model, caseStyle.id));
        return `<span class="bf-model-profile-status ${ready ? 'ready' : 'bad'}">${esc(caseStyle.name || caseStyle.id)}：${ready ? '已設定' : '未設定'}</span>`;
      }).join('') : '<span class="bad">目前沒有上架殼款</span>';
      return `<tr><td>${index + 1}</td><td>${esc(model.brand)}</td><td><b>${esc(model.name)}</b><br><small class="${model.status === false ? 'bad' : 'ok'}">${model.status === false ? '已下架' : '上架中'}</small></td><td><div class="bf-model-profile-statuses">${statuses}</div></td><td><button class="btn alt mini" data-edit-model="${esc(model.id)}">編輯</button><button class="btn danger mini" data-delete-model="${esc(model.id)}">刪除</button></td></tr>`;
    }).join('') : '<tr><td colspan="5" class="empty">目前沒有型號</td></tr>';
    body.querySelectorAll('[data-edit-model]').forEach(button => button.onclick = () => window.openModelEditor(button.dataset.editModel));
    body.querySelectorAll('[data-delete-model]').forEach(button => button.onclick = () => deleteModel(button.dataset.deleteModel));
  }

  function value(id, fallback = '') {
    const element = document.getElementById(id);
    return element ? element.value : fallback;
  }

  function currentProfileSnapshot() {
    return JSON.stringify({
      preview_mask_img: value('model-profile-mask-url').trim(),
      print_line_img: value('model-profile-line-url').trim(),
      print_x: value('model-profile-x', '0'),
      print_y: value('model-profile-y', '0'),
      print_w: value('model-profile-w'),
      print_h: value('model-profile-h'),
      print_angle: value('model-profile-angle', '0'),
    });
  }

  function profileIsDirty() {
    return Boolean(profileSnapshot && currentProfileSnapshot() !== profileSnapshot);
  }

  function renderProfilePanel() {
    const host = document.getElementById('model-profile-admin');
    if (!host) return;
    const styles = activeStyles();
    if (!styles.length) {
      activeStyleId = '';
      host.innerHTML = '<div class="notice bad">請先建立並上架至少一個手機殼款，再設定生產資料。</div>';
      return;
    }
    if (!styles.some(row => String(row.id) === String(activeStyleId))) activeStyleId = styles[0].id;
    const selected = styles.find(row => String(row.id) === String(activeStyleId));
    const profile = profileFor(editingModel, activeStyleId) || {};
    const tabs = styles.map(caseStyle => {
      const ready = complete(profileFor(editingModel, caseStyle.id));
      return `<button type="button" class="bf-profile-tab ${ready ? 'ready' : ''} ${caseStyle.id === activeStyleId ? 'active' : ''}" data-profile-style="${esc(caseStyle.id)}"><span class="dot"></span>${esc(caseStyle.name || caseStyle.id)}</button>`;
    }).join('');
    const stateClass = complete(profile) ? (profile === editingModel ? 'legacy' : 'ready') : 'bad';
    const stateText = complete(profile) ? (profile === editingModel ? '沿用舊晶彩設定；儲存後轉為獨立設定' : '已設定') : '尚未設定';
    host.innerHTML = `<div class="bf-profile-tabs">${tabs}</div><div class="bf-profile-panel">
      <div class="bf-profile-heading"><b>${esc(selected.name || selected.id)}生產設定</b><span class="bf-profile-state ${stateClass}">${stateText}</span></div>
      <div class="row"><div class="field"><label>預覽遮罩 PNG</label><div class="upload"><img id="model-profile-mask-img" style="${profile.preview_mask_img ? '' : 'display:none'}" src="${esc(profile.preview_mask_img || '')}"><input id="model-profile-mask-url" type="hidden" value="${esc(profile.preview_mask_img || '')}"><button type="button" class="btn alt mini" data-upload-profile="mask">上傳遮罩</button><input id="model-profile-mask-file" type="file" accept="image/png,image/jpeg,image/webp" hidden></div></div>
      <div class="field"><label>打印線圖 PNG</label><div class="upload"><img id="model-profile-line-img" style="${profile.print_line_img ? '' : 'display:none'}" src="${esc(profile.print_line_img || '')}"><input id="model-profile-line-url" type="hidden" value="${esc(profile.print_line_img || '')}"><button type="button" class="btn alt mini" data-upload-profile="line">上傳線圖</button><input id="model-profile-line-file" type="file" accept="image/png,image/jpeg,image/webp" hidden></div></div></div>
      <div class="notice"><b>A5 Desktop 列印參數</b><br>X / Y 是治具定位，座標原點在治具右下角；W / H 是實際列印尺寸。A5 有效範圍為 200 × 230 mm。儲存後只同步此型號、此殼款啟用中的商品 SKU；不同顏色共用本設定。</div>
      <div class="row four"><div class="field"><label>定位 X mm</label><input id="model-profile-x" type="number" step="0.1" value="${esc(profile.print_x ?? 0)}"></div><div class="field"><label>定位 Y mm</label><input id="model-profile-y" type="number" step="0.1" value="${esc(profile.print_y ?? 0)}"></div><div class="field"><label>列印 W mm</label><input id="model-profile-w" type="number" step="0.1" min="0.001" value="${esc(profile.print_w ?? '')}"></div><div class="field"><label>列印 H mm</label><input id="model-profile-h" type="number" step="0.1" min="0.001" value="${esc(profile.print_h ?? '')}"></div></div>
      <div class="field"><label>角度（預設 0°）</label><input id="model-profile-angle" type="number" step="0.1" value="${esc(profile.print_angle ?? 0)}"></div>
    </div>`;
    host.querySelectorAll('[data-profile-style]').forEach(button => button.onclick = () => {
      const nextStyleId = button.dataset.profileStyle;
      if (String(nextStyleId) === String(activeStyleId)) return;
      if (profileIsDirty() && !confirm('目前殼款有尚未儲存的修改，確定要切換殼款並放棄修改嗎？')) return;
      activeStyleId = nextStyleId;
      renderProfilePanel();
    });
    host.querySelectorAll('[data-upload-profile]').forEach(button => button.onclick = () => {
      document.getElementById(`model-profile-${button.dataset.uploadProfile}-file`)?.click();
    });
    ['mask', 'line'].forEach(kind => {
      document.getElementById(`model-profile-${kind}-file`)?.addEventListener('change', event => uploadProfileImage(event, kind));
    });
    profileSnapshot = currentProfileSnapshot();
  }

  async function uploadProfileImage(event, kind) {
    const file = event.target.files && event.target.files[0];
    if (!file) return;
    try {
      const url = await uploadAdminImage(file, 'material');
      const hidden = document.getElementById(`model-profile-${kind}-url`);
      const image = document.getElementById(`model-profile-${kind}-img`);
      hidden.value = url;
      image.src = url;
      image.style.display = 'block';
    } catch (error) {
      notify(error.message || error);
    } finally {
      event.target.value = '';
    }
  }

  window.renderModels = renderModelList;
  window.openModelEditor = function (id = '', requestedStyleId = '') {
    ensureStyles();
    editingModel = id ? (shopData.models || []).find(row => String(row.id) === String(id)) || null : null;
    document.getElementById('model-id').value = id;
    document.getElementById('model-brand').innerHTML = (shopData.brands || []).map(brand => `<option value="${esc(brand)}">${esc(brand)}</option>`).join('');
    document.getElementById('model-brand').value = editingModel?.brand || shopData.brands?.[0] || '';
    document.getElementById('model-name').value = editingModel?.name || '';
    document.getElementById('model-active').checked = editingModel?.status !== false;
    const styles = activeStyles();
    activeStyleId = styles.some(row => String(row.id) === String(requestedStyleId))
      ? requestedStyleId
      : (styles.some(row => row.id === LEGACY_CRYSTAL_STYLE_ID) ? LEGACY_CRYSTAL_STYLE_ID : (styles[0]?.id || ''));
    renderProfilePanel();
    openModal('model-modal');
  };

  window.saveModel = async function () {
    if (modelSaveBusy || !activeStyleId) return;
    const id = document.getElementById('model-id').value || `m_${Date.now()}`;
    const name = document.getElementById('model-name').value.trim();
    const profile = {
      preview_mask_img: value('model-profile-mask-url').trim(),
      print_line_img: value('model-profile-line-url').trim(),
      print_x: Number(value('model-profile-x', 0)) || 0,
      print_y: Number(value('model-profile-y', 0)) || 0,
      print_w: Number(value('model-profile-w')),
      print_h: Number(value('model-profile-h')),
      print_angle: Number(value('model-profile-angle', 0)) || 0,
    };
    if (!name) return notify('請填型號名稱');
    if (!complete(profile)) return notify('請上傳此殼款的預覽遮罩、打印線圖，並確認列印 W / H 大於 0');
    const previous = editingModel || {};
    const patch = {
      ...previous, id, brand: document.getElementById('model-brand').value, name,
      status: document.getElementById('model-active').checked,
      case_profiles: {...(previous.case_profiles && typeof previous.case_profiles === 'object' ? previous.case_profiles : {}), [activeStyleId]: profile},
    };
    const next = structuredClone(shopData), index = next.models.findIndex(row => String(row.id) === String(id));
    if (index >= 0) next.models[index] = patch; else next.models.push(patch);
    const button = document.getElementById('model-save');
    modelSaveBusy = true;
    if (button) button.disabled = true;
    try {
      const result = await apiJson('/api/admin/print/model-profiles', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({model_id: id, style_id: activeStyleId, shop_data: next, expected_version: shopVersion}),
      });
      shopVersion = String(result.version || '');
      shopData = next;
      renderModels();
      closeModal('model-modal');
      notify('型號與目前殼款設定已儲存', 'success');
    } catch (error) {
      if (error.code === 'PROFILE_SYNC_FAILED' && error.version) {
        shopVersion = String(error.version);
        shopData = next;
        editingModel = patch;
        document.getElementById('model-id').value = id;
        renderModels();
        renderProfilePanel();
      }
      notify('儲存失敗：' + (error.message || error));
    } finally {
      modelSaveBusy = false;
      if (button) button.disabled = false;
    }
  };

  window.BenfuwanModelProfilesAdmin = Object.freeze({
    getActiveStyleId: () => activeStyleId,
    isDirty: profileIsDirty,
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { ensureStyles(); renderModels(); }, {once: true});
  else { ensureStyles(); renderModels(); }
})();
