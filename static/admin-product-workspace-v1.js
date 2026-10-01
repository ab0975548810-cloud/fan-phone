/* 本福丸後台：商品設定工作區 V1。只整理品牌、型號與殼款管理 UX。 */
(function () {
  'use strict';
  if (window.__benfuwanAdminProductWorkspaceInstalled) return;
  window.__benfuwanAdminProductWorkspaceInstalled = true;

  const state = {
    modelQuery: '',
    modelBrand: '',
    modelStatus: 'all',
    styleQuery: '',
    styleStatus: 'all',
    brandOriginal: '',
  };

  const clean = value => String(value == null ? '' : value).trim();
  const normal = value => clean(value).toLocaleLowerCase('zh-TW');
  const stylesForProfiles = () => (shopData.styles || []).filter(row => row && row.status !== false && row.id);
  const completeProfile = profile => window.BenfuwanCaseProfiles?.complete?.(profile) === true;
  const profileFor = (model, styleId) => window.BenfuwanCaseProfiles?.profileFor?.(model, styleId);

  function ensureChrome() {
    if (!document.getElementById('bf-product-message')) {
      const host = document.createElement('div');
      host.id = 'bf-product-message';
      host.className = 'bf-product-message';
      host.setAttribute('aria-live', 'polite');
      host.setAttribute('aria-atomic', 'true');
      document.body.appendChild(host);
    }

    if (!document.getElementById('bf-brand-modal')) {
      const modal = document.createElement('div');
      modal.id = 'bf-brand-modal';
      modal.className = 'modal bf-brand-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-labelledby', 'bf-brand-title');
      modal.innerHTML = `<div class="box bf-brand-box">
        <div class="mh"><span id="bf-brand-title">品牌設定</span><button class="btn danger mini" type="button" data-brand-close>關閉</button></div>
        <form id="bf-brand-form">
          <div class="mb">
            <div class="field"><label for="bf-brand-name">品牌名稱</label><input id="bf-brand-name" autocomplete="off" maxlength="80" required></div>
            <div id="bf-brand-error" class="bf-field-message" role="alert"></div>
          </div>
          <div class="mf"><button class="btn danger" type="button" data-brand-close>取消</button><button class="btn" id="bf-brand-save" type="submit">儲存品牌</button></div>
        </form>
      </div>`;
      document.body.appendChild(modal);
      modal.querySelectorAll('[data-brand-close]').forEach(button => button.addEventListener('click', closeBrandDialog));
      modal.addEventListener('click', event => {
        if (event.target === modal) closeBrandDialog();
      });
      modal.querySelector('#bf-brand-form').addEventListener('submit', submitBrand);
    }

    ensureModelFilters();
    ensureStyleFilters();
  }

  let messageTimer = 0;
  function notify(message, type = 'info') {
    ensureChrome();
    const host = document.getElementById('bf-product-message');
    host.className = `bf-product-message show ${type === 'success' ? 'success' : type === 'error' ? 'error' : 'info'}`;
    host.textContent = clean(message);
    clearTimeout(messageTimer);
    messageTimer = setTimeout(() => host.classList.remove('show'), 4200);
  }

  function ensureModelFilters() {
    const view = document.getElementById('model-admin-view');
    const wrap = view?.querySelector('.table-wrap');
    if (!wrap || document.getElementById('bf-model-filters')) return;
    const bar = document.createElement('div');
    bar.id = 'bf-model-filters';
    bar.className = 'bf-catalog-filters';
    bar.innerHTML = `
      <label class="bf-filter-search"><span>搜尋型號</span><input id="bf-model-search" type="search" placeholder="搜尋品牌或型號"></label>
      <label><span>品牌</span><select id="bf-model-brand-filter"><option value="">全部品牌</option></select></label>
      <label><span>上架狀態</span><select id="bf-model-status-filter"><option value="all">全部</option><option value="active">上架中</option><option value="inactive">已下架</option></select></label>
      <span id="bf-model-result-count" class="bf-result-count"></span>`;
    wrap.before(bar);
    bar.querySelector('#bf-model-search').addEventListener('input', event => {
      state.modelQuery = event.target.value;
      renderModels();
    });
    bar.querySelector('#bf-model-brand-filter').addEventListener('change', event => {
      state.modelBrand = event.target.value;
      renderModels();
    });
    bar.querySelector('#bf-model-status-filter').addEventListener('change', event => {
      state.modelStatus = event.target.value;
      renderModels();
    });
  }

  function ensureStyleFilters() {
    const panel = document.querySelector('#view-styles .panel');
    const wrap = panel?.querySelector('.table-wrap');
    if (!wrap || document.getElementById('bf-style-filters')) return;
    const bar = document.createElement('div');
    bar.id = 'bf-style-filters';
    bar.className = 'bf-catalog-filters bf-style-filters';
    bar.innerHTML = `
      <label class="bf-filter-search"><span>搜尋殼款</span><input id="bf-style-search" type="search" placeholder="搜尋殼款名稱或顏色"></label>
      <label><span>上架狀態</span><select id="bf-style-status-filter"><option value="all">全部</option><option value="active">上架中</option><option value="inactive">已下架</option></select></label>
      <span id="bf-style-result-count" class="bf-result-count"></span>`;
    wrap.before(bar);
    bar.querySelector('#bf-style-search').addEventListener('input', event => {
      state.styleQuery = event.target.value;
      renderStyles();
    });
    bar.querySelector('#bf-style-status-filter').addEventListener('change', event => {
      state.styleStatus = event.target.value;
      renderStyles();
    });
  }

  function modelMatches(model) {
    const text = normal(`${model.brand || ''} ${model.name || ''}`);
    if (normal(state.modelQuery) && !text.includes(normal(state.modelQuery))) return false;
    if (state.modelBrand && String(model.brand || '') !== state.modelBrand) return false;
    if (state.modelStatus === 'active' && model.status === false) return false;
    if (state.modelStatus === 'inactive' && model.status !== false) return false;
    return true;
  }

  function styleMatches(style) {
    const colors = Array.isArray(style.colors) ? style.colors.join(' ') : '';
    const text = normal(`${style.name || ''} ${colors}`);
    if (normal(state.styleQuery) && !text.includes(normal(state.styleQuery))) return false;
    if (state.styleStatus === 'active' && style.status === false) return false;
    if (state.styleStatus === 'inactive' && style.status !== false) return false;
    return true;
  }

  function refreshBrandFilter() {
    ensureModelFilters();
    const select = document.getElementById('bf-model-brand-filter');
    if (!select) return;
    const brands = [...new Set((shopData.brands || []).map(clean).filter(Boolean))];
    if (state.modelBrand && !brands.includes(state.modelBrand)) state.modelBrand = '';
    select.innerHTML = '<option value="">全部品牌</option>' + brands.map(brand => `<option value="${esc(brand)}">${esc(brand)}</option>`).join('');
    select.value = state.modelBrand;
  }

  function renderBrandsWorkspace() {
    ensureChrome();
    const body = document.getElementById('brands-body');
    if (!body) return;
    const brands = shopData.brands || [];
    const counts = new Map();
    (shopData.models || []).forEach(model => counts.set(String(model.brand || ''), (counts.get(String(model.brand || '')) || 0) + 1));
    body.innerHTML = brands.length ? brands.map((brand, index) => `<tr data-brand="${esc(brand)}">
      <td data-label="序號">${index + 1}</td>
      <td data-label="品牌"><b>${esc(brand)}</b></td>
      <td data-label="型號數"><span class="bf-count-chip">${counts.get(String(brand)) || 0} 個型號</span></td>
      <td data-label="操作" class="bf-actions"><button type="button" class="btn alt mini" data-edit-brand="${esc(brand)}">編輯</button><button type="button" class="btn danger mini" data-delete-brand="${esc(brand)}">刪除</button></td>
    </tr>`).join('') : '<tr><td colspan="4" class="empty">目前沒有品牌</td></tr>';
    body.querySelectorAll('[data-edit-brand]').forEach(button => button.onclick = () => editBrand(button.dataset.editBrand));
    body.querySelectorAll('[data-delete-brand]').forEach(button => button.onclick = () => deleteBrand(button.dataset.deleteBrand));
  }

  function renderModelsWorkspace() {
    ensureChrome();
    refreshBrandFilter();
    const body = document.getElementById('models-body');
    if (!body) return;
    const models = (shopData.models || []).filter(modelMatches);
    const caseStyles = stylesForProfiles();
    body.innerHTML = models.length ? models.map((model, index) => {
      const statuses = caseStyles.length ? caseStyles.map(caseStyle => {
        const ready = completeProfile(profileFor(model, caseStyle.id));
        return `<button type="button" class="bf-model-profile-status ${ready ? 'ready' : 'bad'}" data-model-style="${esc(caseStyle.id)}" data-model-id="${esc(model.id)}" aria-label="編輯 ${esc(model.name)} ${esc(caseStyle.name || caseStyle.id)}生產設定">${esc(caseStyle.name || caseStyle.id)}：${ready ? '已設定' : '未設定'}</button>`;
      }).join('') : '<span class="bad">目前沒有上架殼款</span>';
      return `<tr data-model-id="${esc(model.id)}">
        <td data-label="序號">${index + 1}</td>
        <td data-label="品牌">${esc(model.brand || '未分類')}</td>
        <td data-label="型號"><b>${esc(model.name)}</b><br><small class="${model.status === false ? 'bad' : 'ok'}">${model.status === false ? '已下架' : '上架中'}</small></td>
        <td data-label="各殼款設定"><div class="bf-model-profile-statuses">${statuses}</div></td>
        <td data-label="操作" class="bf-actions"><button type="button" class="btn alt mini" data-edit-model="${esc(model.id)}">編輯</button><button type="button" class="btn danger mini" data-delete-model="${esc(model.id)}">刪除</button></td>
      </tr>`;
    }).join('') : '<tr><td colspan="5" class="empty">沒有符合條件的型號</td></tr>';
    body.querySelectorAll('[data-model-style]').forEach(button => button.onclick = () => openModelEditor(button.dataset.modelId, button.dataset.modelStyle));
    body.querySelectorAll('[data-edit-model]').forEach(button => button.onclick = () => openModelEditor(button.dataset.editModel));
    body.querySelectorAll('[data-delete-model]').forEach(button => button.onclick = () => deleteModel(button.dataset.deleteModel));
    const count = document.getElementById('bf-model-result-count');
    if (count) count.textContent = `顯示 ${models.length} / ${(shopData.models || []).length} 個型號`;
  }

  function cleanList(value) {
    const rows = Array.isArray(value) ? value : String(value || '').split(/[,，]/);
    return [...new Set(rows.map(clean).filter(Boolean))];
  }

  function renderStylesWorkspace() {
    ensureChrome();
    const body = document.getElementById('styles-body');
    if (!body) return;
    const styles = (shopData.styles || []).filter(styleMatches);
    body.innerHTML = styles.length ? styles.map(style => {
      const defaults = cleanList(style.colors);
      const overrides = Object.keys(style.model_colors || {}).filter(modelId => cleanList(style.model_colors[modelId]).length).length;
      const mask = clean(style.mask_img);
      return `<tr data-style-id="${esc(style.id)}">
        <td data-label="殼款"><b>${esc(style.name)}</b><br><small class="${style.status === false ? 'bad' : 'ok'}">${style.status === false ? '已下架' : '上架中'}</small></td>
        <td data-label="售價">NT$ ${Number(style.price || 0).toLocaleString()}</td>
        <td data-label="預設顏色" class="bf-style-color-summary"><b>${esc(defaults.join('、') || '不分顏色')}</b><small>${overrides ? `另有 ${overrides} 個型號使用獨立顏色` : '所有型號使用預設顏色'}</small></td>
        <td data-label="預覽遮罩">${mask ? `<img class="mini-preview" loading="lazy" src="${esc(mask)}" alt="${esc(style.name)}預覽遮罩">` : '<span class="bad">未上傳</span>'}</td>
        <td data-label="操作" class="bf-actions"><button type="button" class="btn alt mini" data-edit-style="${esc(style.id)}">編輯</button><button type="button" class="btn danger mini" data-delete-style="${esc(style.id)}">刪除</button></td>
      </tr>`;
    }).join('') : '<tr><td colspan="5" class="empty">沒有符合條件的手機殼材質</td></tr>';
    body.querySelectorAll('[data-edit-style]').forEach(button => button.onclick = () => openStyleEditor(button.dataset.editStyle));
    body.querySelectorAll('[data-delete-style]').forEach(button => button.onclick = () => deleteStyle(button.dataset.deleteStyle));
    const count = document.getElementById('bf-style-result-count');
    if (count) count.textContent = `顯示 ${styles.length} / ${(shopData.styles || []).length} 個殼款`;
  }

  function setBrandError(message = '') {
    const error = document.getElementById('bf-brand-error');
    const input = document.getElementById('bf-brand-name');
    if (error) error.textContent = message;
    if (input) input.setAttribute('aria-invalid', message ? 'true' : 'false');
  }

  function openBrandDialog(original = '') {
    ensureChrome();
    state.brandOriginal = original;
    const modal = document.getElementById('bf-brand-modal');
    document.getElementById('bf-brand-title').textContent = original ? '修改品牌' : '新增品牌';
    document.getElementById('bf-brand-name').value = original;
    document.getElementById('bf-brand-save').textContent = original ? '儲存修改' : '新增品牌';
    setBrandError('');
    modal.classList.add('show');
    setTimeout(() => document.getElementById('bf-brand-name')?.focus(), 0);
  }

  function closeBrandDialog() {
    document.getElementById('bf-brand-modal')?.classList.remove('show');
    state.brandOriginal = '';
    setBrandError('');
  }

  async function submitBrand(event) {
    event?.preventDefault?.();
    if (shopMutationBusy) return;
    const name = clean(document.getElementById('bf-brand-name')?.value);
    const original = state.brandOriginal;
    if (!name) return setBrandError('請輸入品牌名稱');
    const duplicate = (shopData.brands || []).some(brand => normal(brand) === normal(name) && String(brand) !== String(original));
    if (duplicate) return setBrandError('品牌已存在，請使用其他名稱');
    if (original && name === original) {
      closeBrandDialog();
      return;
    }

    const next = structuredClone(shopData);
    next.brands = Array.isArray(next.brands) ? next.brands : [];
    if (original) {
      const index = next.brands.indexOf(original);
      if (index < 0) return setBrandError('找不到原品牌，請重新整理後再試');
      next.brands[index] = name;
      (next.models || []).forEach(model => {
        if (model.brand === original) model.brand = name;
      });
    } else {
      next.brands.push(name);
    }

    const button = document.getElementById('bf-brand-save');
    shopMutationBusy = true;
    if (button) button.disabled = true;
    try {
      await saveShop(next);
      shopData = next;
      closeBrandDialog();
      renderBrands();
      renderModels();
      notify(original ? '品牌名稱已更新' : '品牌已新增', 'success');
    } catch (error) {
      setBrandError((original ? '修改' : '新增') + '品牌失敗：' + (error.message || error));
    } finally {
      shopMutationBusy = false;
      if (button) button.disabled = false;
    }
  }

  async function deleteBrandWorkspace(name) {
    if (shopMutationBusy) return;
    const used = (shopData.models || []).filter(model => model.brand === name).length;
    const question = used
      ? `品牌「${name}」底下還有 ${used} 個型號。刪除品牌後，型號資料仍會保留但品牌名稱會變成「未分類」。確定刪除？`
      : `確定刪除品牌「${name}」？`;
    if (!confirm(question)) return;
    const next = structuredClone(shopData);
    if (used) {
      (next.models || []).forEach(model => {
        if (model.brand === name) model.brand = '未分類';
      });
      if (!next.brands.includes('未分類')) next.brands.push('未分類');
    }
    next.brands = next.brands.filter(brand => brand !== name);
    shopMutationBusy = true;
    try {
      await saveShop(next);
      shopData = next;
      renderBrands();
      renderModels();
      notify('品牌已刪除', 'success');
    } catch (error) {
      notify('刪除品牌失敗：' + (error.message || error), 'error');
    } finally {
      shopMutationBusy = false;
    }
  }

  async function deleteModelWorkspace(id) {
    if (shopMutationBusy || !confirm('確定刪除這個型號？')) return;
    const next = structuredClone(shopData);
    next.models = (next.models || []).filter(model => String(model.id) !== String(id));
    shopMutationBusy = true;
    try {
      await saveShop(next);
      shopData = next;
      renderBrands();
      renderModels();
      notify('型號已刪除', 'success');
    } catch (error) {
      notify('刪除型號失敗：' + (error.message || error), 'error');
    } finally {
      shopMutationBusy = false;
    }
  }

  async function deleteStyleWorkspace(id) {
    if (shopMutationBusy || !confirm('確定刪除這個材質？')) return;
    const next = structuredClone(shopData);
    next.styles = (next.styles || []).filter(style => String(style.id) !== String(id));
    shopMutationBusy = true;
    try {
      await saveShop(next);
      shopData = next;
      renderModels();
      renderStyles();
      notify('手機殼材質已刪除', 'success');
    } catch (error) {
      notify('刪除材質失敗：' + (error.message || error), 'error');
    } finally {
      shopMutationBusy = false;
    }
  }

  window.BenfuwanAdminProductWorkspace = Object.freeze({
    notify,
    submitBrand,
    filters: state,
  });
  window.renderBrands = renderBrandsWorkspace;
  window.renderModels = renderModelsWorkspace;
  window.renderStyles = renderStylesWorkspace;
  window.addBrand = () => openBrandDialog('');
  window.editBrand = name => openBrandDialog(name);
  window.deleteBrand = deleteBrandWorkspace;
  window.deleteModel = deleteModelWorkspace;
  window.deleteStyle = deleteStyleWorkspace;
  window.uploadStyleImage = async function (event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const url = await uploadAdminImage(file, 'material');
      imgPreview('style-mask', url);
    } catch (error) {
      notify(error.message || error, 'error');
    } finally {
      event.target.value = '';
    }
  };

  function init() {
    ensureChrome();
    renderBrands();
    renderModels();
    renderStyles();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
