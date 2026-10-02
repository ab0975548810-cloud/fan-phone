/* 本福丸後台：素材庫工作區。保留既有 assetsVersion/CAS 與分頁資料契約。 */
(function () {
  'use strict';
  if (window.__benfuwanAssetCategoriesInstalled) return;
  window.__benfuwanAssetCategoriesInstalled = true;

  const PAGE_SIZE = 40;
  let shown = PAGE_SIZE;
  let batchMode = false;
  let searchQuery = '';
  let mutationBusy = false;
  let uploadBusy = false;
  let pendingFiles = [];
  let categoryMode = 'create';
  let categoryOriginal = '';
  const selected = new Set();
  const deleting = new Set();

  const clean = value => String(value == null ? '' : value).trim();
  const normal = value => clean(value).toLocaleLowerCase('zh-TW');
  const h = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[ch]);
  const allStickers = () => Array.isArray(assetsData?.stickers) ? assetsData.stickers : [];
  const isUncategorized = sticker => ['全部', '未分類', '', null, undefined].includes(sticker?.category);
  const categories = () => {
    const raw = Array.isArray(assetsData?.categories) ? assetsData.categories : [];
    const user = raw.filter((name, index) => name && name !== '全部' && name !== '未分類' && raw.indexOf(name) === index);
    return ['全部', ...(allStickers().some(isUncategorized) ? ['未分類'] : []), ...user];
  };
  const categoryList = () => {
    if (currentAsset === '全部') return allStickers();
    if (currentAsset === '未分類') return allStickers().filter(isUncategorized);
    return allStickers().filter(sticker => (sticker.category || '未分類') === currentAsset);
  };
  const searchable = sticker => normal([
    sticker?.name, sticker?.original_name, sticker?.filename, sticker?.category,
    clean(sticker?.url).split('/').pop()
  ].filter(Boolean).join(' '));
  const visibleList = () => {
    const list = categoryList();
    const query = normal(searchQuery);
    return query ? list.filter(sticker => searchable(sticker).includes(query)) : list;
  };

  function notify(message, type = 'info') {
    if (window.BenfuwanAdminProductWorkspace?.notify) {
      window.BenfuwanAdminProductWorkspace.notify(message, type);
      return;
    }
    console[type === 'error' ? 'error' : 'info']('[ASSETS]', message);
  }

  function ensureUi() {
    const view = document.getElementById('view-assets');
    if (!view) return;
    const title = view.querySelector('.titlebar');
    if (title && !document.getElementById('bf-asset-cat-actions')) {
      const oldUpload = title.querySelector('button');
      const wrap = document.createElement('div');
      wrap.id = 'bf-asset-cat-actions';
      wrap.className = 'bf-library-actions';
      wrap.innerHTML = `
        <button class="btn alt" type="button" data-asset-create><i class="fa-solid fa-folder-plus"></i> 新增分類</button>
        <button class="btn alt" type="button" data-asset-rename><i class="fa-solid fa-pen"></i> 改名</button>
        <button class="btn danger" type="button" data-asset-delete-category><i class="fa-solid fa-folder-minus"></i> 刪除分類</button>
        <button class="btn alt" id="bf-batch-cat-btn" type="button"><i class="fa-solid fa-check-double"></i> 批量管理</button>`;
      wrap.querySelector('[data-asset-create]').addEventListener('click', () => openCategoryDialog('create'));
      wrap.querySelector('[data-asset-rename]').addEventListener('click', () => openCategoryDialog('rename'));
      wrap.querySelector('[data-asset-delete-category]').addEventListener('click', deleteCategory);
      wrap.querySelector('#bf-batch-cat-btn').addEventListener('click', toggleBatch);
      if (oldUpload) {
        oldUpload.remove();
        oldUpload.id = 'bf-sticker-upload-btn';
        wrap.appendChild(oldUpload);
      }
      title.appendChild(wrap);
    }

    const panel = view.querySelector('.panel');
    if (panel && !document.getElementById('bf-asset-tools')) {
      const tools = document.createElement('div');
      tools.id = 'bf-asset-tools';
      tools.className = 'bf-library-filters bf-asset-filters';
      tools.innerHTML = `
        <label class="bf-library-search"><span>搜尋素材</span><input id="bf-asset-search" type="search" placeholder="搜尋檔名或分類" autocomplete="off"></label>
        <span id="bf-asset-result-count" class="bf-library-count" aria-live="polite"></span>`;
      tools.querySelector('#bf-asset-search').addEventListener('input', event => {
        searchQuery = event.target.value;
        shown = PAGE_SIZE;
        renderAssets();
      });
      panel.insertBefore(tools, panel.firstChild);
    }

    if (panel && !document.getElementById('asset-batchbar')) {
      const bar = document.createElement('div');
      bar.id = 'asset-batchbar';
      bar.innerHTML = `
        <span class="count" id="bf-asset-count">已選 0 張</span>
        <button class="btn alt mini" type="button" id="bf-select-visible">全選目前結果</button>
        <input id="bf-target-category" list="bf-category-list" placeholder="輸入或選擇分類">
        <datalist id="bf-category-list"></datalist>
        <button class="btn mini" type="button" id="bf-move-assets">移到分類</button>
        <button class="btn danger mini" type="button" id="bf-delete-assets"><i class="fa-solid fa-trash"></i> 刪除所選</button>
        <button class="btn danger mini" type="button" id="bf-cancel-batch">取消</button>`;
      panel.insertBefore(bar, document.getElementById('asset-tabs'));
      bar.querySelector('#bf-select-visible').addEventListener('click', selectVisible);
      bar.querySelector('#bf-move-assets').addEventListener('click', moveSelected);
      bar.querySelector('#bf-delete-assets').addEventListener('click', deleteSelected);
      bar.querySelector('#bf-cancel-batch').addEventListener('click', () => {
        batchMode = false;
        selected.clear();
        syncBatchUi();
        renderAssets();
      });
    }

    ensureDialogs();
    refreshDatalist();
    syncBatchUi();
  }

  function ensureDialogs() {
    if (!document.getElementById('bf-asset-category-modal')) {
      const modal = document.createElement('div');
      modal.id = 'bf-asset-category-modal';
      modal.className = 'modal bf-library-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-labelledby', 'bf-asset-category-title');
      modal.innerHTML = `<div class="box bf-library-dialog">
        <div class="mh"><span id="bf-asset-category-title">素材分類</span><button class="btn danger mini" type="button" data-category-close>關閉</button></div>
        <form id="bf-asset-category-form">
          <div class="mb">
            <div class="field"><label for="bf-asset-category-name">分類名稱</label><input id="bf-asset-category-name" maxlength="24" autocomplete="off" required></div>
            <div id="bf-asset-category-error" class="bf-library-error" role="alert"></div>
          </div>
          <div class="mf"><button class="btn danger" type="button" data-category-close>取消</button><button class="btn" id="bf-asset-category-save" type="submit">儲存</button></div>
        </form>
      </div>`;
      document.body.appendChild(modal);
      modal.querySelectorAll('[data-category-close]').forEach(button => button.addEventListener('click', closeCategoryDialog));
      modal.addEventListener('click', event => { if (event.target === modal) closeCategoryDialog(); });
      modal.querySelector('form').addEventListener('submit', submitCategory);
    }

    if (!document.getElementById('bf-asset-upload-modal')) {
      const modal = document.createElement('div');
      modal.id = 'bf-asset-upload-modal';
      modal.className = 'modal bf-library-modal';
      modal.setAttribute('role', 'dialog');
      modal.setAttribute('aria-modal', 'true');
      modal.setAttribute('aria-labelledby', 'bf-asset-upload-title');
      modal.innerHTML = `<div class="box bf-library-dialog">
        <div class="mh"><span id="bf-asset-upload-title">批量上傳素材</span><button class="btn danger mini" type="button" data-upload-close>關閉</button></div>
        <form id="bf-asset-upload-form">
          <div class="mb">
            <p id="bf-asset-upload-summary" class="bf-upload-summary"></p>
            <div class="field"><label for="bf-asset-upload-category">放入既有分類</label><select id="bf-asset-upload-category"></select></div>
            <button class="btn alt mini" type="button" id="bf-asset-new-category-toggle"><i class="fa-solid fa-plus"></i> 直接建立新分類</button>
            <div class="field bf-upload-new-category" id="bf-asset-new-category-field" hidden><label for="bf-asset-upload-new-category">新分類名稱</label><input id="bf-asset-upload-new-category" maxlength="24" autocomplete="off"></div>
            <div id="bf-asset-upload-progress" class="bf-upload-progress" aria-live="polite"></div>
            <div id="bf-asset-upload-error" class="bf-library-error" role="alert"></div>
          </div>
          <div class="mf"><button class="btn danger" type="button" data-upload-close>取消</button><button class="btn" id="bf-asset-upload-confirm" type="submit">確認上傳</button></div>
        </form>
      </div>`;
      document.body.appendChild(modal);
      modal.querySelectorAll('[data-upload-close]').forEach(button => button.addEventListener('click', closeUploadDialog));
      modal.addEventListener('click', event => { if (event.target === modal) closeUploadDialog(); });
      modal.querySelector('#bf-asset-new-category-toggle').addEventListener('click', toggleNewUploadCategory);
      modal.querySelector('form').addEventListener('submit', submitUpload);
    }
  }

  function setDialogBusy(modal, busy) {
    modal?.querySelectorAll('button,input,select').forEach(control => { control.disabled = Boolean(busy); });
  }

  function openCategoryDialog(mode) {
    if (mutationBusy) return;
    if (mode === 'rename' && (!currentAsset || currentAsset === '全部' || currentAsset === '未分類')) {
      notify('請先選擇可改名的自訂分類', 'error');
      return;
    }
    categoryMode = mode;
    categoryOriginal = mode === 'rename' ? currentAsset : '';
    const modal = document.getElementById('bf-asset-category-modal');
    modal.querySelector('#bf-asset-category-title').textContent = mode === 'rename' ? `修改「${categoryOriginal}」` : '新增素材分類';
    modal.querySelector('#bf-asset-category-name').value = categoryOriginal;
    modal.querySelector('#bf-asset-category-error').textContent = '';
    setDialogBusy(modal, false);
    modal.classList.add('show');
    requestAnimationFrame(() => modal.querySelector('#bf-asset-category-name').focus());
  }

  function closeCategoryDialog() {
    if (mutationBusy) return;
    document.getElementById('bf-asset-category-modal')?.classList.remove('show');
  }

  async function submitCategory(event) {
    event.preventDefault();
    if (mutationBusy) return;
    const modal = document.getElementById('bf-asset-category-modal');
    const input = modal.querySelector('#bf-asset-category-name');
    const error = modal.querySelector('#bf-asset-category-error');
    const name = clean(input.value);
    error.textContent = '';
    if (!name) { error.textContent = '請輸入分類名稱'; input.focus(); return; }
    if (name === '全部' || name === '未分類') { error.textContent = '這是系統分類名稱，請使用其他名稱'; return; }
    if (categories().some(existing => existing === name && existing !== categoryOriginal)) {
      error.textContent = '分類名稱已存在';
      return;
    }
    if (categoryMode === 'rename' && name === categoryOriginal) { closeCategoryDialog(); return; }

    mutationBusy = true;
    setDialogBusy(modal, true);
    try {
      const result = await categoryApi(categoryMode === 'rename'
        ? {action: 'rename', old: categoryOriginal, new: name}
        : {action: 'create', name});
      if (categoryMode === 'rename') {
        assetsData.categories = (assetsData.categories || []).map(item => item === categoryOriginal ? name : item);
        allStickers().forEach(sticker => { if ((sticker.category || '未分類') === categoryOriginal) sticker.category = name; });
        notify(`分類已改成「${name}」，共整理 ${result.moved || 0} 張素材`, 'success');
      } else {
        if (!(assetsData.categories || []).includes(name)) assetsData.categories.push(name);
        notify(`已建立分類「${name}」`, 'success');
      }
      currentAsset = name;
      shown = PAGE_SIZE;
      modal.classList.remove('show');
      renderAssetTabs();
      renderAssets();
      refreshDatalist();
    } catch (errorValue) {
      await refreshIfStale(errorValue);
      error.textContent = errorValue.message || '分類儲存失敗';
      notify(error.textContent, 'error');
    } finally {
      mutationBusy = false;
      setDialogBusy(modal, false);
    }
  }

  function openUploadDialog(files) {
    if (uploadBusy || !files.length) return;
    pendingFiles = files;
    const modal = document.getElementById('bf-asset-upload-modal');
    const select = modal.querySelector('#bf-asset-upload-category');
    const choices = categories().filter(name => name !== '全部');
    if (!choices.length) choices.push('未分類');
    select.innerHTML = choices.map(name => `<option value="${h(name)}">${h(name)}</option>`).join('');
    const preferred = currentAsset && currentAsset !== '全部' ? currentAsset : choices[0];
    if (choices.includes(preferred)) select.value = preferred;
    modal.querySelector('#bf-asset-upload-summary').textContent = `已選擇 ${files.length} 張圖片，確認分類後才會開始上傳。`;
    modal.querySelector('#bf-asset-upload-progress').textContent = '';
    modal.querySelector('#bf-asset-upload-error').textContent = '';
    modal.querySelector('#bf-asset-upload-new-category').value = '';
    modal.querySelector('#bf-asset-new-category-field').hidden = true;
    modal.querySelector('#bf-asset-new-category-toggle').setAttribute('aria-expanded', 'false');
    setDialogBusy(modal, false);
    modal.classList.add('show');
  }

  function toggleNewUploadCategory() {
    const modal = document.getElementById('bf-asset-upload-modal');
    const field = modal.querySelector('#bf-asset-new-category-field');
    field.hidden = !field.hidden;
    modal.querySelector('#bf-asset-new-category-toggle').setAttribute('aria-expanded', String(!field.hidden));
    if (!field.hidden) modal.querySelector('#bf-asset-upload-new-category').focus();
  }

  function closeUploadDialog() {
    if (uploadBusy) return;
    document.getElementById('bf-asset-upload-modal')?.classList.remove('show');
    pendingFiles = [];
    const input = document.getElementById('sticker-files');
    if (input) input.value = '';
  }

  async function submitUpload(event) {
    event.preventDefault();
    if (uploadBusy || !pendingFiles.length) return;
    const modal = document.getElementById('bf-asset-upload-modal');
    const newField = modal.querySelector('#bf-asset-new-category-field');
    const usingNew = !newField.hidden;
    const category = clean(usingNew
      ? modal.querySelector('#bf-asset-upload-new-category').value
      : modal.querySelector('#bf-asset-upload-category').value);
    const error = modal.querySelector('#bf-asset-upload-error');
    const progress = modal.querySelector('#bf-asset-upload-progress');
    error.textContent = '';
    if (!category || category === '全部') { error.textContent = '請選擇或建立一個素材分類'; return; }
    if (usingNew && categories().includes(category)) { error.textContent = '分類名稱已存在，請改選既有分類'; return; }

    const files = pendingFiles.slice();
    const form = new FormData();
    files.forEach(file => form.append('files', file));
    form.append('category', category);
    form.append('expected_version', assetsVersion);
    uploadBusy = true;
    setDialogBusy(modal, true);
    progress.textContent = `正在上傳 ${files.length} 張…`;
    try {
      const response = await apiJson('/api/admin/batch_upload_stickers', {method: 'POST', body: form});
      assetsVersion = String(response.version || '');
      const uploaded = Array.isArray(response.data) ? response.data : [];
      if (!(assetsData.categories || []).includes(category)) assetsData.categories.push(category);
      if (uploaded.length) assetsData.stickers.push(...uploaded);
      else await loadAssets(true);
      currentAsset = category;
      shown = PAGE_SIZE;
      pendingFiles = [];
      modal.classList.remove('show');
      const input = document.getElementById('sticker-files');
      if (input) input.value = '';
      renderAssetTabs();
      renderAssets();
      refreshDatalist();
      notify(`已上傳 ${files.length} 張到「${category}」`, 'success');
    } catch (errorValue) {
      await refreshIfStale(errorValue);
      error.textContent = errorValue.message || '素材上傳失敗';
      progress.textContent = '';
      notify(error.textContent, 'error');
    } finally {
      uploadBusy = false;
      setDialogBusy(modal, false);
    }
  }

  async function categoryApi(body) {
    const response = await apiJson('/api/admin/sticker_category', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({...body, expected_version: assetsVersion})
    });
    assetsVersion = String(response.version || '');
    return response;
  }

  async function refreshIfStale(error) {
    if (error?.code !== 'STALE_DATA') return;
    await loadAssets(true);
    renderAssetTabs();
    renderAssets();
  }

  function refreshDatalist() {
    const list = document.getElementById('bf-category-list');
    if (list) list.innerHTML = categories().filter(name => name !== '全部').map(name => `<option value="${h(name)}"></option>`).join('');
  }

  function syncBatchUi() {
    const bar = document.getElementById('asset-batchbar');
    const button = document.getElementById('bf-batch-cat-btn');
    const count = document.getElementById('bf-asset-count');
    bar?.classList.toggle('show', batchMode);
    if (button) button.innerHTML = batchMode
      ? '<i class="fa-solid fa-xmark"></i> 結束選取'
      : '<i class="fa-solid fa-check-double"></i> 批量管理';
    if (count) count.textContent = `已選 ${selected.size} 張`;
  }

  function toggleBatch() {
    if (mutationBusy) return;
    batchMode = !batchMode;
    selected.clear();
    shown = PAGE_SIZE;
    syncBatchUi();
    renderAssets();
  }

  function toggleOne(id) {
    if (selected.has(id)) selected.delete(id); else selected.add(id);
    syncBatchUi();
    renderAssets();
  }

  function selectVisible() {
    if (mutationBusy) return;
    const ids = visibleList().map(sticker => String(sticker.id));
    const allSelected = ids.length && ids.every(id => selected.has(id));
    ids.forEach(id => allSelected ? selected.delete(id) : selected.add(id));
    syncBatchUi();
    renderAssets();
  }

  async function deleteCategory() {
    if (mutationBusy) return;
    const name = currentAsset;
    if (!name || name === '全部' || name === '未分類') {
      notify('系統分類不能刪除；要刪素材請使用批量管理', 'error');
      return;
    }
    const count = allStickers().filter(sticker => (sticker.category || '未分類') === name).length;
    if (!confirm(`刪除分類「${name}」？\n\n${count} 張素材不會被刪掉，會移到「未分類」。`)) return;
    mutationBusy = true;
    try {
      await categoryApi({action: 'delete', name});
      assetsData.categories = (assetsData.categories || []).filter(item => item !== name);
      allStickers().forEach(sticker => { if ((sticker.category || '未分類') === name) sticker.category = '未分類'; });
      currentAsset = '未分類';
      selected.clear();
      batchMode = false;
      shown = PAGE_SIZE;
      renderAssetTabs();
      renderAssets();
      refreshDatalist();
      syncBatchUi();
      notify(`已刪除分類「${name}」`, 'success');
    } catch (error) {
      await refreshIfStale(error);
      notify(error.message || '刪除分類失敗', 'error');
    } finally {
      mutationBusy = false;
    }
  }

  async function moveSelected() {
    if (mutationBusy) return;
    if (!selected.size) { notify('請先選擇素材', 'error'); return; }
    const input = document.getElementById('bf-target-category');
    const name = clean(input?.value);
    if (!name || name === '全部') { notify('請輸入或選擇實際分類', 'error'); return; }
    const ids = [...selected];
    mutationBusy = true;
    syncMutationButtons();
    try {
      const result = await categoryApi({action: 'move', name, ids});
      if (name !== '未分類' && !(assetsData.categories || []).includes(name)) assetsData.categories.push(name);
      const wanted = new Set(ids);
      allStickers().forEach(sticker => { if (wanted.has(String(sticker.id))) sticker.category = name; });
      selected.clear();
      batchMode = false;
      currentAsset = name;
      shown = PAGE_SIZE;
      if (input) input.value = '';
      renderAssetTabs();
      renderAssets();
      refreshDatalist();
      notify(`已移動 ${result.moved || 0} 張素材到「${name}」`, 'success');
    } catch (error) {
      await refreshIfStale(error);
      notify(error.message || '批量移動失敗', 'error');
    } finally {
      mutationBusy = false;
      syncMutationButtons();
    }
  }

  async function deleteSelected() {
    if (mutationBusy) return;
    if (!selected.size) { notify('請先選擇要刪除的素材', 'error'); return; }
    const ids = [...selected];
    if (!confirm(`確定永久刪除這 ${ids.length} 張素材？`)) return;
    mutationBusy = true;
    syncMutationButtons();
    try {
      const result = await categoryApi({action: 'delete_stickers', ids});
      const wanted = new Set(ids);
      assetsData.stickers = allStickers().filter(sticker => !wanted.has(String(sticker.id)));
      selected.clear();
      batchMode = false;
      shown = PAGE_SIZE;
      renderAssetTabs();
      renderAssets();
      notify(`已刪除 ${result.deleted ?? ids.length} 張素材`, 'success');
    } catch (error) {
      await refreshIfStale(error);
      notify(error.message || '批量刪除失敗', 'error');
    } finally {
      mutationBusy = false;
      syncMutationButtons();
    }
  }

  function syncMutationButtons() {
    document.querySelectorAll('#asset-batchbar button').forEach(button => { button.disabled = mutationBusy; });
  }

  function installRenderOverrides() {
    window.renderAssetTabs = function () {
      ensureUi();
      const names = categories();
      if (!names.includes(currentAsset)) currentAsset = '全部';
      const box = document.getElementById('asset-tabs');
      if (!box) return;
      box.innerHTML = '';
      names.forEach(name => {
        const button = document.createElement('button');
        button.className = 'pill' + (name === currentAsset ? ' active' : '');
        button.type = 'button';
        button.textContent = name;
        button.addEventListener('click', () => {
          currentAsset = name;
          shown = PAGE_SIZE;
          renderAssetTabs();
          renderAssets();
        });
        box.appendChild(button);
      });
      refreshDatalist();
    };

    window.renderAssets = function () {
      ensureUi();
      const total = categoryList().length;
      const list = visibleList();
      const count = document.getElementById('bf-asset-result-count');
      if (count) count.textContent = searchQuery
        ? `目前分類 ${total} 張・搜尋到 ${list.length} 張`
        : `目前分類 ${total} 張`;
      const box = document.getElementById('asset-grid');
      if (!box) return;
      box.className = 'grid bf-asset-grid';
      box.innerHTML = '';
      if (!list.length) {
        box.innerHTML = `<div class="empty">${searchQuery ? '找不到符合條件的素材' : '這個分類目前沒有素材'}</div>`;
        return;
      }
      const fragment = document.createDocumentFragment();
      list.slice(0, shown).forEach(sticker => {
        const id = String(sticker.id || '');
        const card = document.createElement('article');
        card.dataset.id = id;
        card.className = 'card bf-asset-card' + (batchMode ? ' bf-selectable' : '') + (selected.has(id) ? ' bf-selected' : '');
        if (batchMode) {
          const check = document.createElement('span');
          check.className = 'bf-asset-check';
          check.innerHTML = selected.has(id) ? '<i class="fa-solid fa-check"></i>' : '';
          card.appendChild(check);
          card.addEventListener('click', event => {
            if (!event.target.closest('[data-delete-sticker]')) toggleOne(id);
          });
        }
        const media = document.createElement('div');
        media.className = 'bf-card-media is-broken';
        const placeholder = document.createElement('div');
        placeholder.className = 'bf-image-placeholder';
        placeholder.innerHTML = '<i class="fa-regular fa-image"></i><span>圖片無法顯示</span>';
        const image = document.createElement('img');
        image.loading = 'lazy';
        image.decoding = 'async';
        image.fetchPriority = 'low';
        image.alt = clean(sticker.name) || '素材預覽';
        image.style.visibility = 'hidden';
        image.addEventListener('load', () => {
          media.classList.remove('is-broken');
          image.style.visibility = 'visible';
        });
        image.addEventListener('error', () => {
          image.style.visibility = 'hidden';
          media.classList.add('is-broken');
        });
        if (sticker.url) image.src = sticker.url;
        media.append(image, placeholder);
        const meta = document.createElement('div');
        meta.className = 'bf-card-meta';
        meta.innerHTML = `<span class="bf-meta-label">分類</span><strong>${h(sticker.category || '未分類')}</strong>`;
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'btn danger mini bf-card-delete';
        remove.dataset.deleteSticker = id;
        remove.innerHTML = '<i class="fa-solid fa-trash-can"></i> 刪除';
        remove.disabled = deleting.has(id);
        remove.addEventListener('click', event => { event.stopPropagation(); deleteSticker(id); });
        card.append(media, meta, remove);
        fragment.appendChild(card);
      });
      box.appendChild(fragment);
      if (shown < list.length) {
        const more = document.createElement('div');
        more.className = 'bf-library-more';
        more.innerHTML = `<span>已顯示 ${Math.min(shown, list.length)} / ${list.length}</span>`;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn alt mini';
        button.textContent = '顯示更多';
        button.addEventListener('click', () => { shown += PAGE_SIZE; renderAssets(); });
        more.appendChild(button);
        box.appendChild(more);
      }
      syncBatchUi();
    };
  }

  function installMutations() {
    window.uploadStickers = function (event) {
      const files = [...(event.target.files || [])];
      if (files.length) openUploadDialog(files);
    };

    window.deleteSticker = async function (id) {
      id = String(id);
      if (deleting.has(id) || !confirm('確定刪除這張素材？')) return;
      deleting.add(id);
      renderAssets();
      try {
        const response = await apiJson('/api/admin/delete_sticker', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({id, expected_version: assetsVersion})
        });
        assetsVersion = String(response.version || '');
        assetsData.stickers = allStickers().filter(sticker => String(sticker.id) !== id);
        selected.delete(id);
        notify('素材已刪除', 'success');
      } catch (error) {
        await refreshIfStale(error);
        notify(error.message || '刪除素材失敗', 'error');
      } finally {
        deleting.delete(id);
        renderAssetTabs();
        renderAssets();
      }
    };
  }

  function boot() {
    ensureUi();
    installRenderOverrides();
    installMutations();
    if (document.getElementById('view-assets')?.classList.contains('active')) {
      renderAssetTabs();
      renderAssets();
    }
    console.info('[ADMIN] asset library workspace enabled');
  }

  window.BenfuwanAdminAssetWorkspace = Object.freeze({
    get searchQuery() { return searchQuery; },
    openCategoryDialog,
    openUploadDialog
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once: true});
  else boot();
})();
