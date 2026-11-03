/* 本福丸前台：只在此裝置保存未完成設計；恢復時一律重新解析最新型號 × 殼款生產設定。 */
(function () {
  'use strict';
  if (window.__bfFrontDesignDraftV1) return;
  window.__bfFrontDesignDraftV1 = true;

  const DRAFT_KEY = 'design-draft-v1';
  const DRAFT_VERSION = 1;
  const DEBOUNCE_MS = 650;
  const DRAFT_CUSTOM_PROPS = [
    ...CUSTOM_PROPS, 'bfUserLocked', 'stickerId', 'originalPublicSrc', 'aiOutlineViewport',
    'aiRemovalMode',
    'aiOutlineSource',
    'aiOutlineStrength',
    'aiOutlineStyle',
    'aiOutlineWidth',
    'aiOutlineColor',
  ];
  const GEOMETRY_ERROR = '此手機殼設定已更新，舊設計無法安全恢復，請重新製作。';
  const INVALID_ERROR = '上次的設計草稿已無法安全恢復，請刪除舊草稿並重新開始。';
  const QUOTA_ERROR = '此設計圖片較大，自動儲存空間不足，請不要關閉頁面。';

  let saveTimer = 0;
  let suspended = false;
  let autosaveEnabled = true;
  let cachedDraft = null;

  let promptState = 'hidden';

  const byId = id => document.getElementById(id);
  const getCanvas = () => {
    try { return typeof canvas !== 'undefined' ? canvas : null; } catch (e) { return null; }
  };
  const getContext = () => {
    try { return typeof ctx !== 'undefined' ? ctx : null; } catch (e) { return null; }
  };
  const currentShopData = () => {
    try { return typeof shopData !== 'undefined' ? shopData : null; } catch (e) { return null; }
  };

  function isQuotaError(error) {
    return error && (
      error.name === 'QuotaExceededError' ||
      error.name === 'NS_ERROR_DOM_QUOTA_REACHED' ||
      Number(error.code) === 22 ||
      Number(error.code) === 1014
    );
  }

  const store = window.BenfuwanDraftStore;
  let activeKey = DRAFT_KEY, revision = null, draftName = '';
  let queue = Promise.resolve();
  function warnSave(error) {
    console.warn('[DESIGN DRAFT]', error);
    toast(isQuotaError(error) ? QUOTA_ERROR : (error?.message || '草稿未能保存，請不要關閉頁面。'));
  }
  function activate(key, raw) {
    activeKey = key;
    revision = raw?.revision || raw?.updatedAt || null;
    draftName = raw?.name || '';
    store.resetImages();
  }
  function buildDraft() {
    const c = getCanvas(), state = getContext();
    if (!editorHasSession || !c || !state || !state.modelId || !state.styleId) return null;
    const canvasJson = structuredClone(c.toDatalessJSON(DRAFT_CUSTOM_PROPS));
    return {
      version: DRAFT_VERSION,
      updatedAt: new Date().toISOString(),
      modelId: String(state.modelId),
      styleId: String(state.styleId),
      colorName: String(state.colorName || ''),
      backgroundColor: String(state.backgroundColor || 'transparent'),
      backgroundOpacity: Math.max(0, Math.min(1, Number(state.backgroundOpacity) || 0)),
      logicalCanvasWidth: Number(c.width),
      logicalCanvasHeight: Number(c.height),
      canvasJson,
    };
  }

  async function saveNow() {
    clearTimeout(saveTimer);
    saveTimer = 0;
    if (suspended || !autosaveEnabled) return false;
    let draft;
    try { draft = buildDraft(); } catch (error) { warnSave(error); return false; }
    if (!draft) return false;
    const key = activeKey;
    const run = async () => {
      if (key !== activeKey || suspended || !autosaveEnabled) return false;
      const next = {...draft, name:draftName || [ctx.modelName,ctx.styleName].filter(Boolean).join(' · '), revision:crypto.randomUUID()};
      let packedCopy;
      try {
        packedCopy = await store.pack(next);
        await store.change(key,revision,()=>packedCopy);
        revision = next.revision;
        return true;
      } catch(error) {
        if(error?.name==='DraftConflict' && key===activeKey) {
          activate(DRAFT_KEY+':'+crypto.randomUUID(),null);
          draftName=(next.name || '未命名設計')+'（分頁副本）';
          try {
            await store.change(activeKey,null,()=>({...packedCopy,name:draftName}));
            revision=next.revision;
            toast('另一分頁已變更，這次修改已另存為分頁副本。');
            return true;
          } catch(copyError) {warnSave(copyError);return false;}
        }
        warnSave(error); return false;
      }
    };
    queue = queue.then(run,run);
    return queue;
  }

  function scheduleSave() {
    if (suspended || !autosaveEnabled || !getCanvas() || !byId('page-editor')?.classList.contains('active')) return;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => { saveNow(); }, DEBOUNCE_MS);
  }

  async function readDraft(key) {
    try {
      key ||= (await store.list())[0]?.key;
      cachedDraft = key ? await store.unpack(await idbGet(key)) : null;
      if (cachedDraft) cachedDraft.key = key;
      await prepareDraftGeometry(cachedDraft);
      return cachedDraft;
    } catch (error) {
      console.warn('[DESIGN DRAFT] read failed', error);
      cachedDraft = null;
      return null;
    }
  }

  async function prepareDraftGeometry(raw) {
    const model=(currentShopData()?.models||[]).find(m=>String(m.id)===String(raw?.modelId));
    const resolver=window.BenfuwanModelProfile;
    if(resolver?.isFilm(model)) {
      // Resolve current source geometry, never trust a draft's mask or old dimensions.
      try { await resolver.prepareEditorGeometry(model, raw.styleId); }
      catch(error) { console.warn('[DESIGN DRAFT] film geometry unavailable',error); }
    }
  }

  async function clearDraft() {
    clearTimeout(saveTimer);
    saveTimer = 0;
    try {
      await queue;
      const key = cachedDraft?.key || activeKey;
      if ((await idbGet('cart'))?.draftKey===key || await idbGet('saved-cart:'+key)) {toast('此設計仍在購物車中。');return false;}
      await store.change(key,cachedDraft?.revision || cachedDraft?.updatedAt || revision,()=>null);
      if (key === activeKey) activate(DRAFT_KEY,null);
      cachedDraft = null;
      setPrompt('hidden');
      return true;
    } catch (error) {
      console.warn('[DESIGN DRAFT] delete failed', error);
      return false;
    }
  }

  function parseCanvasJson(value) {
    const parsed = typeof value === 'string' ? JSON.parse(value) : value;
    if (!parsed || typeof parsed !== 'object' || !Array.isArray(parsed.objects)) throw new Error('Invalid Fabric canvas JSON');
    return parsed;
  }

  function cleanColors(value) {
    const source = Array.isArray(value) ? value : String(value || '').split(/[,，]/);
    return [...new Set(source.map(item => String(item || '').trim()).filter(Boolean))];
  }

  function colorsFor(model, style) {
    const mapping = style && style.model_colors && typeof style.model_colors === 'object' ? style.model_colors : {};
    const modelColors = cleanColors(mapping[model.id] || []);
    return modelColors.length ? modelColors : cleanColors(style && style.colors || []);
  }

  function inspectDraft(raw) {
    try {
      if (!raw || typeof raw !== 'object' || Number(raw.version) !== DRAFT_VERSION) throw new Error('Unsupported draft');
      if (!raw.modelId || !raw.styleId || !raw.updatedAt) throw new Error('Incomplete draft');
      const canvasJson = parseCanvasJson(raw.canvasJson);
      const savedWidth = Number(raw.logicalCanvasWidth), savedHeight = Number(raw.logicalCanvasHeight);
      if (!(savedWidth > 0 && savedHeight > 0)) throw new Error('Missing logical geometry');

      const data = currentShopData();
      const model = (data && data.models || []).find(item => item && item.status !== false && String(item.id) === String(raw.modelId));
      const style = (data && data.styles || []).find(item => item && item.status !== false && String(item.id) === String(raw.styleId));
      if (!model || !style) return { ok: false, reason: 'missing-product', message: INVALID_ERROR };
      const resolver = window.BenfuwanModelProfile;
      const profile = resolver && resolver.profileFor ? resolver.profileFor(model, style.id) : null;
      if (!profile || !profile.ready) return { ok: false, reason: 'profile-not-ready', message: INVALID_ERROR };
      const availableColors = colorsFor(model, style);
      const savedColor = String(raw.colorName || '');
      if (availableColors.length && savedColor && !availableColors.includes(savedColor) || availableColors.length > 1 && !savedColor) {
        return { ok: false, reason: 'color-not-available', message: INVALID_ERROR };
      }

      const geometry=resolver.editorGeometry(model,profile);
      const currentWidth = geometry.width;
      const currentHeight = geometry.height;
      if (savedWidth !== currentWidth || savedHeight !== currentHeight) {
        return { ok: false, reason: 'geometry-changed', message: GEOMETRY_ERROR, model, style, profile };
      }
      return { ok: true, raw, canvasJson, model, style, profile, currentWidth, currentHeight, colorName: availableColors.length === 1 ? availableColors[0] : savedColor };
    } catch (error) {
      console.warn('[DESIGN DRAFT] invalid draft', error);
      return { ok: false, reason: 'corrupted', message: INVALID_ERROR };
    }
  }

  function installPrompt() {
    if (byId('design-draft-prompt')) return;
    const host = document.querySelector('#page-home .home-section');
    if (!host) return;
    const style = document.createElement('style');
    style.id = 'design-draft-v1-css';
    style.textContent = `
      #design-draft-prompt{display:none;margin:0 0 12px;padding:15px;border:1px solid #ffd1df;border-radius:18px;background:#fff7fa;box-shadow:0 6px 18px rgba(121,74,90,.08)}
      #design-draft-prompt.show{display:block}
      #design-draft-prompt strong{display:block;font-size:14px;color:#6d5660;margin-bottom:5px}
      #design-draft-prompt p{margin:0 0 12px;color:#8c7881;font-size:11px;line-height:1.55}
      #design-draft-prompt .actions{display:grid;grid-template-columns:1fr 1fr;gap:8px}
      #design-draft-prompt button{min-height:42px;border-radius:12px;font-weight:900}
      #design-draft-prompt .discard{border:1px solid #eadce1;background:#fff;color:#7b6870}
      #design-draft-prompt.invalid .actions{grid-template-columns:1fr}
      #design-draft-prompt.invalid .continue{display:none}
    `;
    document.head.appendChild(style);
    const prompt = document.createElement('div');
    prompt.id = 'design-draft-prompt';
    prompt.setAttribute('role', 'status');
    prompt.innerHTML = '<strong id="design-draft-title">發現上次未完成的設計</strong><p id="design-draft-message">可以從上次中斷的位置繼續編輯。</p><div class="actions"><button class="primary continue" type="button">繼續編輯</button><button class="discard" type="button">重新開始</button></div>';
    prompt.querySelector('.continue').addEventListener('click', () => { continueEditing(); });
    prompt.querySelector('.discard').addEventListener('click', () => { discardAndStart(); });
    host.prepend(prompt);
  }

  function setPrompt(state, message) {
    installPrompt();
    const prompt = byId('design-draft-prompt');
    if (!prompt) return;
    promptState = state;
    prompt.classList.toggle('show', state !== 'hidden');
    prompt.classList.toggle('invalid', state === 'invalid');
    byId('design-draft-title').textContent = state === 'invalid' ? '舊設計無法恢復' : '發現上次未完成的設計';
    byId('design-draft-message').textContent = message || (state === 'invalid' ? INVALID_ERROR : '可以從上次中斷的位置繼續編輯。');
  }

  async function refreshPrompt() {
    installPrompt();
    const raw = await readDraft();
    if (!raw) { setPrompt('hidden'); return null; }
    const inspection = inspectDraft(raw);
    setPrompt(inspection.ok ? 'ready' : 'invalid', inspection.message);
    return inspection;
  }

  function loadCanvasJson(c, json) {
    return new Promise((resolve, reject) => {
      try { c.loadFromJSON(json, () => resolve()); } catch (error) { reject(error); }
    });
  }

  async function continueEditing(key) {
    if (suspended) return false;
    await queue;
    const raw = await readDraft(key || cachedDraft?.key);
    await prepareDraftGeometry(raw);
    const inspection = inspectDraft(raw);
    if (!inspection.ok) { setPrompt('invalid', inspection.message); return false; }
    autosaveEnabled = true;
    suspended = true;
    clearTimeout(saveTimer);
    saveTimer = 0;
    try {
      activate(raw.key, raw);
      setBusy(true, '正在恢復上次的設計...');
      selectModel(inspection.model);
      if (selectStyle(inspection.style) === false) throw new Error('Profile is no longer available');
      if (inspection.colorName && typeof window.chooseCaseColor === 'function') window.chooseCaseColor(inspection.colorName);
      else ctx.colorName = inspection.colorName || '';
      ctx.backgroundColor = typeof raw.backgroundColor === 'string' ? raw.backgroundColor : 'transparent';
      ctx.backgroundOpacity = Math.max(0, Math.min(1, Number(raw.backgroundOpacity) || 0));
      ctx.printBase64 = null;
      ctx.mockupBase64 = null;
      ctx.productionMeta = null;
      await startEditor(false);
      if (!canvas || Number(canvas.width) !== inspection.currentWidth || Number(canvas.height) !== inspection.currentHeight) throw new Error('Logical canvas changed');

      restoringHistory = true;
      await loadCanvasJson(canvas, inspection.canvasJson);
      if (canvas.getObjects().length !== inspection.canvasJson.objects.length)
        throw Error('圖片未完整恢復，請確認連線後再試。');
      rehydrateCanvas();
      if (typeof ensureCanvasFonts === 'function') await ensureCanvasFonts();
      await new Promise(resolve => canvas.setBackgroundColor(backgroundRgba(), resolve));
      canvas.discardActiveObject();
      canvas.requestRenderAll();
      ctx.printBase64 = null;
      ctx.mockupBase64 = null;
      ctx.productionMeta = null;
      historyStack = [];
      historyIndex = -1;
      restoringHistory = false;
      originalRecordHistory(true);
      renderLayerList();
      editorHasSession = true;
      setPrompt('hidden');
      return true;
    } catch (error) {
      console.warn('[DESIGN DRAFT] recovery failed', error);
      try { resetDesignState(true); } catch (e) {}
      try { history.replaceState({ page: 'page-home' }, '', location.pathname + '#home'); showPage('page-home'); } catch (e) {}
      setPrompt('invalid', error && error.message === 'Logical canvas changed' ? GEOMETRY_ERROR : INVALID_ERROR);
      return false;
    } finally {
      try { restoringHistory = false; } catch (e) {}
      suspended = false;
      setBusy(false);
    }
  }

  async function confirmDiscard() {
    return window.confirm('目前有未完成的設計，要放棄並重新開始嗎？');
  }

  async function discardAndStart() {
    if (!await confirmDiscard()) return false;
    suspended = true;
    let cleared = false;
    try { cleared = await clearDraft(); } finally { suspended = false; }
    if (!cleared) { toast('草稿刪除失敗，請再試一次。'); return false; }
    autosaveEnabled = true;
    originalStartNewDesign();
    return true;
  }

  const originalRecordHistory = window.recordHistory;
  if (typeof originalRecordHistory === 'function') {
    window.recordHistory = function () {
      const result = originalRecordHistory.apply(this, arguments);
      scheduleSave();
      return result;
    };
  }

  const originalChangeBackgroundOpacity = window.changeBackgroundOpacity;
  if (typeof originalChangeBackgroundOpacity === 'function') {
    window.changeBackgroundOpacity = function () {
      const result = originalChangeBackgroundOpacity.apply(this, arguments);
      scheduleSave();
      return result;
    };
  }

  const originalStartNewDesign = window.startNewDesign;
  if (typeof originalStartNewDesign === 'function') {
    window.startNewDesign = async function () {
      if (saveTimer && editorHasSession && getCanvas() && !await saveNow()) return false;
      const rows = await store.list();
      activate(rows.some(row=>row.key===DRAFT_KEY) ? DRAFT_KEY + ':' + crypto.randomUUID() : DRAFT_KEY,null);
      cachedDraft = null;
      autosaveEnabled = true;
      byId('design-library')?.remove();
      document.querySelector('.preview-buttons .primary').textContent='加入購物車';
      return originalStartNewDesign.apply(this, arguments);
    };
  }

  const originalLoadAll = window.loadAll;
  if (typeof originalLoadAll === 'function') {
    window.loadAll = async function () {
      const result = await originalLoadAll.apply(this, arguments);
      await refreshPrompt();
      return result;
    };
  }

  const originalSubmitOrder = window.submitOrder;
  if (typeof originalSubmitOrder === 'function') {
    window.submitOrder = async function () {
      const ordered = cartItem || await idbGet('cart');
      const wasSuccess = byId('page-success') && byId('page-success').classList.contains('active');
      const result = await originalSubmitOrder.apply(this, arguments);
      const success = byId('page-success') && byId('page-success').classList.contains('active');
      let emptyCart = false;
      try { emptyCart = typeof cartItem !== 'undefined' && cartItem === null; } catch (e) {}
      if (!wasSuccess && success && emptyCart) {
        if (ordered?.draftKey) {
          if (ordered.draftKey === activeKey) { autosaveEnabled = false; clearTimeout(saveTimer); }
          await queue;
          try { await store.change(ordered.draftKey,ordered.draftRevision,()=>null); }
          catch(error) { console.warn('[DESIGN DRAFT] kept newer draft',error); }
          cachedDraft = null;
        }
      }
      return result;
    };
  }

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && byId('page-editor')?.classList.contains('active')) saveNow();
  });

  window.addEventListener('pagehide', () => { if (saveTimer) saveNow(); });
  const show = window.showPage;
  window.showPage = function(page) {
    if (page !== 'page-editor' && saveTimer && byId('page-editor')?.classList.contains('active')) saveNow();
    return show.apply(this,arguments);
  };

  window.BenfuwanDesignDraft = Object.freeze({
    version: DRAFT_VERSION,
    get key() { return activeKey; },
    get revision() { return revision; },
    renamed(key,expected,name,next) { if(activeKey===key && revision===expected){revision=next;draftName=name;} },
    debounceMs: DEBOUNCE_MS,
    saveNow,
    scheduleSave,
    readDraft,
    inspectDraft,
    refreshPrompt,
    continueEditing,
    clearDraft,
    state: () => ({ prompt: promptState, suspended, autosaveEnabled, hasDraft: Boolean(cachedDraft) }),
  });
  console.info('[DESIGN DRAFT] local autosave and recovery enabled');
})();
