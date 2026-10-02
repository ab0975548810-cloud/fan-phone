/* 本福丸後台：模板庫列表與管理篩選。編輯器仍由原本 lazy stack 提供。 */
(function () {
  'use strict';
  if (window.__benfuwanAdminLibraryWorkspaceInstalled) return;
  window.__benfuwanAdminLibraryWorkspaceInstalled = true;

  const state = {query: '', category: '全部', model: '', style: '', type: 'all'};
  const deleting = new Set();
  const clean = value => String(value == null ? '' : value).trim();
  const normal = value => clean(value).toLocaleLowerCase('zh-TW');

  function notify(message, type = 'info') {
    if (window.BenfuwanAdminProductWorkspace?.notify) {
      window.BenfuwanAdminProductWorkspace.notify(message, type);
      return;
    }
    console[type === 'error' ? 'error' : 'info']('[TEMPLATES]', message);
  }

  const templates = () => Array.isArray(templatesData?.templates) ? templatesData.templates : [];
  const models = () => Array.isArray(shopData?.models) ? shopData.models : [];
  const styles = () => Array.isArray(shopData?.styles) ? shopData.styles : [];
  const isUniversal = template => template?.universal === true || template?.model_id === '*';
  const referenceModelId = template => clean(template?.reference_model_id || (template?.model_id && template.model_id !== '*' ? template.model_id : ''));
  const explicitStyleId = template => clean(template?.reference_style_id || template?.case_style_id);
  const referenceStyleId = template => {
    const explicit = explicitStyleId(template);
    if (explicit) return explicit;
    return isUniversal(template) ? clean(window.BenfuwanCaseProfiles?.LEGACY_CRYSTAL_STYLE_ID) : '';
  };
  const modelName = id => models().find(model => String(model.id) === String(id))?.name || (id ? `未知型號（${id}）` : '未指定');
  const styleName = (template, id) => {
    const name = styles().find(style => String(style.id) === String(id))?.name;
    if (name) return !explicitStyleId(template) && isUniversal(template) ? `${name}（舊版相容）` : name;
    return id ? `未知殼款（${id}）` : '未指定';
  };

  function ensureTemplateUi() {
    const view = document.getElementById('view-templates');
    const panel = view?.querySelector('.panel');
    if (!panel || document.getElementById('bf-template-filters')) return;
    const bar = document.createElement('div');
    bar.id = 'bf-template-filters';
    bar.className = 'bf-library-filters bf-template-filters';
    bar.innerHTML = `
      <label class="bf-library-search"><span>搜尋模板名稱</span><input id="bf-template-search" type="search" placeholder="輸入模板名稱" autocomplete="off"></label>
      <label><span>分類</span><select id="bf-template-category-filter"></select></label>
      <label><span>基準型號</span><select id="bf-template-model-filter"></select></label>
      <label><span>基準殼款</span><select id="bf-template-style-filter"></select></label>
      <label><span>模板類型</span><select id="bf-template-type-filter"><option value="all">全部類型</option><option value="universal">全型號通用</option><option value="specific">舊版指定型號</option></select></label>
      <span id="bf-template-result-count" class="bf-library-count" aria-live="polite"></span>`;
    panel.insertBefore(bar, panel.firstChild);
    bar.querySelector('#bf-template-search').addEventListener('input', event => { state.query = event.target.value; renderTemplates(); });
    bar.querySelector('#bf-template-category-filter').addEventListener('change', event => {
      state.category = event.target.value;
      currentTpl = state.category;
      renderTemplateTabs();
      renderTemplates();
    });
    bar.querySelector('#bf-template-model-filter').addEventListener('change', event => { state.model = event.target.value; renderTemplates(); });
    bar.querySelector('#bf-template-style-filter').addEventListener('change', event => { state.style = event.target.value; renderTemplates(); });
    bar.querySelector('#bf-template-type-filter').addEventListener('change', event => { state.type = event.target.value; renderTemplates(); });
    syncTemplateFilterOptions();
  }

  function option(value, label, selected) {
    const node = document.createElement('option');
    node.value = value;
    node.textContent = label;
    node.selected = String(value) === String(selected);
    return node;
  }

  function fillSelect(select, rows, allLabel, selected) {
    if (!select) return;
    select.replaceChildren(option('', allLabel, !selected), ...rows.map(row => option(row.id, row.name, selected)));
    if ([...select.options].some(item => item.value === String(selected))) select.value = selected;
    else select.value = '';
  }

  function syncTemplateFilterOptions() {
    const categories = Array.isArray(templatesData?.categories) && templatesData.categories.length
      ? templatesData.categories : ['全部', '熱門'];
    if (!categories.includes(state.category)) state.category = categories.includes(currentTpl) ? currentTpl : '全部';
    const category = document.getElementById('bf-template-category-filter');
    if (category) {
      category.replaceChildren(...categories.map(name => option(name, name === '全部' ? '全部分類' : name, state.category)));
      category.value = state.category;
    }
    const modelRows = models().map(model => ({id: String(model.id), name: model.name || model.id}));
    templates().map(referenceModelId).filter(Boolean).forEach(id => {
      if (!modelRows.some(row => row.id === id)) modelRows.push({id, name: `未知型號（${id}）`});
    });
    const styleRows = styles().map(style => ({id: String(style.id), name: style.name || style.id}));
    templates().map(referenceStyleId).filter(Boolean).forEach(id => {
      if (!styleRows.some(row => row.id === id)) styleRows.push({id, name: `未知殼款（${id}）`});
    });
    fillSelect(document.getElementById('bf-template-model-filter'), modelRows, '全部基準型號', state.model);
    fillSelect(document.getElementById('bf-template-style-filter'), styleRows, '全部基準殼款', state.style);
    const type = document.getElementById('bf-template-type-filter');
    if (type) type.value = state.type;
  }

  function filteredTemplates() {
    const query = normal(state.query);
    return templates().filter(template => {
      if (state.category !== '全部' && template.category !== state.category) return false;
      if (state.model && referenceModelId(template) !== state.model) return false;
      if (state.style && referenceStyleId(template) !== state.style) return false;
      if (state.type === 'universal' && !isUniversal(template)) return false;
      if (state.type === 'specific' && isUniversal(template)) return false;
      return !query || normal(template.name).includes(query);
    });
  }

  function buildTemplateCard(template) {
    const card = document.createElement('article');
    card.className = 'card bf-template-card';
    card.dataset.templateId = clean(template.id);

    const media = document.createElement('div');
    media.className = 'bf-card-media bf-template-media';
    const image = document.createElement('img');
    image.loading = 'lazy';
    image.decoding = 'async';
    image.alt = clean(template.name) ? `${template.name} 縮圖` : '模板縮圖';
    const placeholder = document.createElement('div');
    placeholder.className = 'bf-image-placeholder';
    placeholder.innerHTML = '<i class="fa-regular fa-image"></i><span>尚無模板縮圖</span>';
    image.addEventListener('load', () => media.classList.remove('is-broken'));
    image.addEventListener('error', () => media.classList.add('is-broken'));
    if (template.thumb_url) image.src = template.thumb_url; else media.classList.add('is-broken');
    media.append(image, placeholder);

    const body = document.createElement('div');
    body.className = 'bf-template-body';
    const title = document.createElement('div');
    title.className = 'name';
    title.textContent = clean(template.name) || '未命名模板';
    const metadata = document.createElement('dl');
    metadata.className = 'bf-template-meta';
    const rows = [
      ['分類', template.category || '未分類'],
      ['基準型號', modelName(referenceModelId(template))],
      ['基準殼款', styleName(template, referenceStyleId(template))]
    ];
    rows.forEach(([label, value]) => {
      const term = document.createElement('dt'); term.textContent = label;
      const definition = document.createElement('dd'); definition.textContent = value;
      metadata.append(term, definition);
    });
    const badge = document.createElement('span');
    badge.className = 'bf-template-type ' + (isUniversal(template) ? 'universal' : 'specific');
    badge.textContent = isUniversal(template) ? '全型號通用' : '指定型號';
    const actions = document.createElement('div');
    actions.className = 'bf-card-actions';
    const edit = document.createElement('button');
    edit.type = 'button';
    edit.className = 'btn alt mini';
    edit.dataset.editTemplate = clean(template.id);
    edit.innerHTML = '<i class="fa-solid fa-pen"></i> 編輯';
    edit.addEventListener('click', () => openTemplateEditor(clean(template.id)));
    const remove = document.createElement('button');
    remove.type = 'button';
    remove.className = 'btn danger mini';
    remove.dataset.deleteTemplate = clean(template.id);
    remove.innerHTML = '<i class="fa-solid fa-trash-can"></i> 刪除';
    remove.disabled = deleting.has(clean(template.id));
    remove.addEventListener('click', () => deleteTemplate(clean(template.id)));
    actions.append(edit, remove);
    body.append(title, metadata, badge, actions);
    card.append(media, body);
    return card;
  }

  function installTemplateRender() {
    window.renderTemplateTabs = function () {
      ensureTemplateUi();
      const categories = Array.isArray(templatesData?.categories) && templatesData.categories.length
        ? templatesData.categories : ['全部', '熱門'];
      if (!categories.includes(currentTpl)) currentTpl = '全部';
      state.category = currentTpl;
      const box = document.getElementById('template-tabs');
      if (!box) return;
      box.replaceChildren(...categories.map(name => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'pill' + (name === currentTpl ? ' active' : '');
        button.textContent = name;
        button.addEventListener('click', () => {
          currentTpl = name;
          state.category = name;
          renderTemplateTabs();
          renderTemplates();
        });
        return button;
      }));
      syncTemplateFilterOptions();
    };

    window.renderTemplates = function () {
      ensureTemplateUi();
      syncTemplateFilterOptions();
      const list = filteredTemplates();
      const count = document.getElementById('bf-template-result-count');
      if (count) count.textContent = `符合條件 ${list.length} 個模板`;
      const box = document.getElementById('template-grid');
      if (!box) return;
      box.className = 'grid bf-template-grid';
      box.innerHTML = '';
      if (!list.length) {
        box.innerHTML = '<div class="empty">目前沒有符合條件的模板</div>';
        return;
      }
      const fragment = document.createDocumentFragment();
      list.forEach(template => fragment.appendChild(buildTemplateCard(template)));
      box.appendChild(fragment);
    };
  }

  window.deleteTemplate = async function (id) {
    id = clean(id);
    if (templateDeleteBusy || deleting.has(id) || !confirm('確定刪除這個模板？')) return;
    const next = structuredClone(templatesData);
    next.templates = (next.templates || []).filter(template => String(template.id) !== id);
    templateDeleteBusy = true;
    deleting.add(id);
    renderTemplates();
    try {
      await saveTemplates(next);
      templatesData = next;
      renderTemplateTabs();
      renderTemplates();
      notify('模板已刪除', 'success');
    } catch (error) {
      if (error?.code === 'STALE_DATA') await loadTemplates(true);
      notify('刪除模板失敗：' + (error.message || error), 'error');
    } finally {
      templateDeleteBusy = false;
      deleting.delete(id);
      renderTemplates();
    }
  };

  function init() {
    ensureTemplateUi();
    installTemplateRender();
    if (document.getElementById('view-templates')?.classList.contains('active')) {
      renderTemplateTabs();
      renderTemplates();
    }
    console.info('[ADMIN] template library workspace enabled');
  }

  window.BenfuwanAdminLibraryWorkspace = Object.freeze({state, installTemplateRender});
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once: true});
  else init();
})();
