/* 本福丸：共用打印蒙版、透明鏡頭孔及公制輸出。載入於其他前台修補程式之後。 */
(function () {
  'use strict';

  const PIXELS_PER_MM = 20; // 508 DPI；與 1:1 素材的 20 px/mm 相同。
  const MAX_RASTER_ROUNDING_PX = 1;
  const OVERLAY_AUDIT_MAX_EDGE = 256;
  const MAX_DROPPED_OVERLAY_ALPHA_RATIO = 0.02;
  const states = new WeakMap();
  const overlayStates = new WeakMap();
  let previewBusy = false;

  function safeAssetUrl(url) {
    url = String(url || '').trim();
    if (!url || url.startsWith('data:') || url.startsWith('blob:') || url.startsWith('/')) return url;
    try {
      const u = new URL(url, location.href);
      if (u.origin === location.origin) return u.href;
    } catch (e) {}
    return '/api/public/asset_proxy?url=' + encodeURIComponent(url);
  }

  function loadImage(url, message) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const timer = setTimeout(() => finish(new Error(message)), 15000);
      function finish(error) {
        clearTimeout(timer);
        img.onload = img.onerror = null;
        if (error) reject(error);
        else resolve(img);
      }
      img.onload = () => finish(img.naturalWidth && img.naturalHeight ? null : new Error(message));
      img.onerror = () => finish(new Error(message));
      img.src = safeAssetUrl(url);
    });
  }

  function makeCanvas(width, height) {
    const el = document.createElement('canvas');
    el.width = width;
    el.height = height;
    return el;
  }

  function normalizeAlphaImage(img, requireTransparency, message) {
    const sourceWidth = img.naturalWidth || img.width;
    const sourceHeight = img.naturalHeight || img.height;
    if (!(sourceWidth > 0 && sourceHeight > 0)) throw new Error(message);
    const source = makeCanvas(sourceWidth, sourceHeight);
    const g = source.getContext('2d', { willReadFrequently: true });
    g.drawImage(img, 0, 0, sourceWidth, sourceHeight);
    const pixels = g.getImageData(0, 0, sourceWidth, sourceHeight).data;
    let left = sourceWidth, top = sourceHeight, right = -1, bottom = -1, transparent = false;
    for (let y = 0; y < sourceHeight; y++) {
      for (let x = 0; x < sourceWidth; x++) {
        const alpha = pixels[(y * sourceWidth + x) * 4 + 3];
        if (alpha > 0) {
          if (x < left) left = x;
          if (x > right) right = x;
          if (y < top) top = y;
          if (y > bottom) bottom = y;
        } else {
          transparent = true;
        }
      }
    }
    if (right < left || bottom < top || (requireTransparency && !transparent)) throw new Error(message);
    const width = right - left + 1, height = bottom - top + 1;
    const normalized = makeCanvas(width, height);
    const ng = normalized.getContext('2d');
    ng.drawImage(source, left, top, width, height, 0, 0, width, height);
    source.width = source.height = 1;
    return {
      canvas: normalized,
      bounds: { left, top, right, bottom, width, height },
      sourceWidth,
      sourceHeight
    };
  }

  function normalizeMaskImage(img) {
    return normalizeAlphaImage(img, true, '這個型號的可印範圍尚未設定完成，請聯絡店家。');
  }

  function resampleMask(mask, width, height) {
    const source = mask && mask.canvas ? mask.canvas : mask;
    if (!source || !(width > 0 && height > 0)) throw new Error('可印範圍尺寸無效。');
    const output = makeCanvas(width, height);
    const g = output.getContext('2d');
    g.imageSmoothingEnabled = true;
    g.imageSmoothingQuality = 'high';
    g.drawImage(source, 0, 0, source.width, source.height, 0, 0, width, height);
    return output;
  }

  function ensureClip(target, url, retry = false) {
    const key = [url, target.width, target.height].join('|');
    let state = states.get(target);
    if (state && state.key === key && !(retry && state.error)) {
      target.clipPath = state.clip;
      target.requestRenderAll();
      return state.ready;
    }
    const empty = new fabric.Rect({ width: 0, height: 0, strokeWidth: 0, excludeFromExport: true });
    state = { key, clip: empty, image: null, error: null };
    states.set(target, state);
    target.clipPath = empty;
    target.requestRenderAll();
    state.ready = (async () => {
      try {
        if (!url) throw new Error('這個型號尚未設定可印範圍，請選擇其他型號或聯絡店家。');
        const img = await loadImage(url, '可印範圍讀取失敗，請稍後重新預覽。');
        const mask = normalizeMaskImage(img);
        if (canvas !== target || states.get(target) !== state) throw new Error('型號已切換，請重新預覽。');
        state.image = img;
        state.mask = mask;
        state.clip = new fabric.Image(mask.canvas, {
          left: 0, top: 0, originX: 'left', originY: 'top',
          scaleX: target.width / mask.canvas.width,
          scaleY: target.height / mask.canvas.height,
          absolutePositioned: true, selectable: false, evented: false,
          excludeFromExport: true
        });
        target.clipPath = state.clip;
        target.requestRenderAll();
        return state;
      } catch (error) {
        state.error = error;
        throw error;
      }
    })();
    return state.ready;
  }

  window.applyCaseBoundaryClip = function () {
    if (typeof canvas === 'undefined' || !canvas) return;
    const target = canvas, context = ctx;
    const maskUrl = context.printLineUrl || '', overlayUrl = context.maskUrl || '';
    const overlay = document.getElementById('phone-mask');
    const editorGuide = document.getElementById('print-area-guide');
    if (editorGuide) editorGuide.style.display = 'none';
    queueMicrotask(() => {
      if (canvas === target && ctx === context && overlay) {
        overlay.removeAttribute('src');
        overlay.style.display = 'none';
      }
    });
    ensureClip(target, maskUrl).then(async state => {
      applyEditorGuide(target, state.mask);
      return [state, await ensurePreviewOverlay(target, overlayUrl, state.mask)];
    }).then(([, overlayState]) => {
      if (canvas !== target || ctx !== context || context.printLineUrl !== maskUrl || context.maskUrl !== overlayUrl) return;
      if (!overlay) return;
      overlay.src = overlayState.dataUrl;
      overlay.style.display = overlayState.dataUrl ? 'block' : 'none';
    }).catch(error => {
      if (canvas === target && typeof toast === 'function') toast(/[\u3400-\u9fff]/.test(error.message) ? error.message : '可印範圍無法讀取，請聯絡店家。');
    });
  };

  function withMetricScale(dataUrl) {
    const binary = atob(dataUrl.split(',')[1]);
    const input = Uint8Array.from(binary, char => char.charCodeAt(0));
    const chunk = new Uint8Array(21);
    const view = new DataView(chunk.buffer);
    view.setUint32(0, 9);
    chunk.set([112, 72, 89, 115], 4);
    view.setUint32(8, PIXELS_PER_MM * 1000);
    view.setUint32(12, PIXELS_PER_MM * 1000);
    chunk[16] = 1;
    let crc = 0xffffffff;
    for (const byte of chunk.subarray(4, 17)) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
    view.setUint32(17, (crc ^ 0xffffffff) >>> 0);
    const parts = [input.subarray(0, 33), chunk];
    const sourceView = new DataView(input.buffer);
    for (let pos = 33; pos < input.length;) {
      const end = pos + sourceView.getUint32(pos) + 12;
      if (!(input[pos + 4] === 112 && input[pos + 5] === 72 && input[pos + 6] === 89 && input[pos + 7] === 115)) parts.push(input.subarray(pos, end));
      pos = end;
    }
    const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
    let offset = 0;
    for (const part of parts) { out.set(part, offset); offset += part.length; }
    const strings = [];
    for (let pos = 0; pos < out.length; pos += 32768) strings.push(String.fromCharCode(...out.subarray(pos, pos + 32768)));
    return 'data:image/png;base64,' + btoa(strings.join(''));
  }

  function renderPrint(target, mask, width, height) {
    const hidden = target.getObjects().filter(o => ['guide', 'slot-guide'].includes(o.role));
    const visibility = hidden.map(o => o.visible);
    const originalClip = target.clipPath;
    let source;
    try {
      hidden.forEach(o => { o.visible = false; });
      target.clipPath = null;
      source = target.toCanvasElement(Math.max(width / target.width, height / target.height));
    } finally {
      target.clipPath = originalClip;
      hidden.forEach((o, i) => { o.visible = visibility[i]; });
      target.renderAll();
    }
    const output = makeCanvas(width, height);
    const g = output.getContext('2d');
    g.imageSmoothingEnabled = true;
    g.imageSmoothingQuality = 'high';
    g.drawImage(source, 0, 0, width, height);
    const maskLayer = resampleMask(mask, width, height);
    g.globalCompositeOperation = 'destination-in';
    g.drawImage(maskLayer, 0, 0);
    g.globalCompositeOperation = 'source-over';
    source.width = source.height = 1;
    maskLayer.width = maskLayer.height = 1;
    return output;
  }

  function mapImageToCanonicalFrame(img, canonical) {
    const sourceWidth = img.naturalWidth || img.width;
    const sourceHeight = img.naturalHeight || img.height;
    if (!canonical || !(sourceWidth > 0 && sourceHeight > 0)) return null;
    const scaleX = sourceWidth / canonical.sourceWidth;
    const scaleY = sourceHeight / canonical.sourceHeight;
    if (Math.abs(canonical.sourceHeight * scaleX - sourceHeight) > MAX_RASTER_ROUNDING_PX ||
        Math.abs(canonical.sourceWidth * scaleY - sourceWidth) > MAX_RASTER_ROUNDING_PX) return null;
    const crop = {
      left: canonical.bounds.left * scaleX,
      top: canonical.bounds.top * scaleY,
      width: canonical.bounds.width * scaleX,
      height: canonical.bounds.height * scaleY
    };
    if (crop.left < 0 || crop.top < 0 || crop.left + crop.width > sourceWidth + MAX_RASTER_ROUNDING_PX ||
        crop.top + crop.height > sourceHeight + MAX_RASTER_ROUNDING_PX) return null;
    const auditScale = Math.min(1, OVERLAY_AUDIT_MAX_EDGE / Math.max(sourceWidth, sourceHeight));
    const auditWidth = Math.max(1, Math.round(sourceWidth * auditScale));
    const auditHeight = Math.max(1, Math.round(sourceHeight * auditScale));
    const audit = makeCanvas(auditWidth, auditHeight);
    const ag = audit.getContext('2d', { willReadFrequently: true });
    ag.drawImage(img, 0, 0, auditWidth, auditHeight);
    const auditPixels = ag.getImageData(0, 0, auditWidth, auditHeight).data;
    const auditCrop = {
      left: crop.left * auditWidth / sourceWidth,
      top: crop.top * auditHeight / sourceHeight,
      right: (crop.left + crop.width) * auditWidth / sourceWidth,
      bottom: (crop.top + crop.height) * auditHeight / sourceHeight
    };
    let visibleAlpha = 0, droppedAlpha = 0;
    for (let y = 0; y < auditHeight; y++) {
      for (let x = 0; x < auditWidth; x++) {
        if (auditPixels[(y * auditWidth + x) * 4 + 3] === 0) continue;
        visibleAlpha++;
        if (x + .5 < auditCrop.left || x + .5 > auditCrop.right || y + .5 < auditCrop.top || y + .5 > auditCrop.bottom) droppedAlpha++;
      }
    }
    audit.width = audit.height = 1;
    if (!visibleAlpha || droppedAlpha / visibleAlpha > MAX_DROPPED_OVERLAY_ALPHA_RATIO) return null;
    const mapped = makeCanvas(canonical.canvas.width, canonical.canvas.height);
    const g = mapped.getContext('2d', { willReadFrequently: true });
    g.imageSmoothingEnabled = true;
    g.imageSmoothingQuality = 'high';
    g.drawImage(img, crop.left, crop.top, crop.width, crop.height, 0, 0, mapped.width, mapped.height);
    const pixels = g.getImageData(0, 0, mapped.width, mapped.height).data;
    let visible = false;
    for (let i = 3; i < pixels.length; i += 4) {
      if (pixels[i] > 0) { visible = true; break; }
    }
    if (!visible) return null;
    return { canvas: mapped, crop, sourceWidth, sourceHeight };
  }

  function renderEditorGuide(mask, width, height) {
    const layer = resampleMask(mask, width, height);
    const g = layer.getContext('2d', { willReadFrequently: true });
    const source = g.getImageData(0, 0, width, height);
    const output = g.createImageData(width, height);
    const inside = (x, y) => x >= 0 && y >= 0 && x < width && y < height && source.data[(y * width + x) * 4 + 3] > 24;
    for (let y = 0; y < height; y++) {
      for (let x = 0; x < width; x++) {
        if (!inside(x, y)) continue;
        const offset = (y * width + x) * 4;
        const edge = !inside(x - 1, y) || !inside(x + 1, y) || !inside(x, y - 1) || !inside(x, y + 1);
        if (edge && (Math.floor((x + y) / 5) % 2 === 0)) {
          output.data.set([255, 111, 154, 220], offset);
        } else {
          output.data.set([255, 255, 255, 190], offset);
        }
      }
    }
    g.putImageData(output, 0, 0);
    return layer;
  }

  function applyEditorGuide(target, mask) {
    const shell = document.getElementById('canvas-shell');
    if (!shell) return;
    let guide = document.getElementById('print-area-guide');
    if (!guide) {
      guide = document.createElement('img');
      guide.id = 'print-area-guide';
      guide.alt = '';
      guide.setAttribute('aria-hidden', 'true');
      guide.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;object-fit:fill;pointer-events:none;z-index:0';
      shell.prepend(guide);
    }
    guide.src = renderEditorGuide(mask, target.width, target.height).toDataURL('image/png');
    guide.style.display = 'block';
    target.wrapperEl.style.zIndex = '1';
    const oldGuide = document.getElementById('safe-guide');
    if (oldGuide) oldGuide.style.display = 'none';
  }

  function renderPreviewFallback(mask, width, height) {
    const fill = makeCanvas(width, height);
    const fg = fill.getContext('2d');
    fg.fillStyle = '#f8f8f8';
    fg.fillRect(0, 0, width, height);
    fg.globalCompositeOperation = 'destination-in';
    const maskLayer = resampleMask(mask, width, height);
    fg.drawImage(maskLayer, 0, 0);
    maskLayer.width = maskLayer.height = 1;
    return fill;
  }

  function ensurePreviewOverlay(target, url, canonical, retry = false) {
    const geometryKey = canonical ? [canonical.sourceWidth, canonical.sourceHeight, canonical.bounds.left, canonical.bounds.top, canonical.bounds.width, canonical.bounds.height].join(':') : '';
    const key = [url, target.width, target.height, geometryKey].join('|');
    let state = overlayStates.get(target);
    if (state && state.key === key && !(retry && state.error)) return state.ready;
    state = { key, image: null, overlay: null, dataUrl: '', error: null };
    overlayStates.set(target, state);
    state.ready = (async () => {
      try {
        if (!url) return state;
        const img = await loadImage(url, '手機殼預覽讀取失敗，請再試一次。');
        const overlay = mapImageToCanonicalFrame(img, canonical);
        if (canvas !== target || overlayStates.get(target) !== state) throw new Error('型號已切換，請重新預覽。');
        state.image = img;
        state.overlay = overlay;
        state.dataUrl = overlay ? overlay.canvas.toDataURL('image/png') : '';
        state.hiddenReason = overlay ? '' : '預覽外框與可印範圍的原始比例不一致，已隱藏外框。';
        return state;
      } catch (error) {
        state.error = error;
        state.hiddenReason = '手機殼預覽無法可靠對齊，已隱藏外框。';
        if (canvas !== target || overlayStates.get(target) !== state) throw error;
        return state;
      }
    })();
    return state.ready;
  }

  window.BenfuwanPrintMask = Object.freeze({
    PIXELS_PER_MM,
    loadImage,
    normalizeMaskImage,
    resampleMask,
    mapImageToCanonicalFrame,
    renderEditorGuide,
    renderPreviewFallback,
    ensureClip,
    ensurePreviewOverlay,
    renderPrint,
    pixelsForMm: mm => Math.round(Number(mm) * PIXELS_PER_MM)
  });

  window.openPreview = async function () {
    if (typeof canvas === 'undefined' || !canvas || previewBusy) return;
    previewBusy = true;
    const target = canvas, context = ctx;
    const maskUrl = context.printLineUrl || '', overlayUrl = context.maskUrl || '';
    context.printBase64 = context.mockupBase64 = null;
    setBusy(true, '正在產生高畫質預覽...');
    try {
      const state = await ensureClip(target, maskUrl, true);
      const overlayState = await ensurePreviewOverlay(target, overlayUrl, state.mask, true);
      if (canvas !== target || ctx !== context || context.printLineUrl !== maskUrl || context.maskUrl !== overlayUrl) throw new Error('型號已切換，請重新預覽。');
      const width = Math.round(Number(context.printW) * PIXELS_PER_MM);
      const height = Math.round(Number(context.printH) * PIXELS_PER_MM);
      if (!(width > 0 && height > 0) || width * height > 16000000) throw new Error('手機殼尺寸設定有誤，請聯絡店家。');
      target.discardActiveObject();
      document.getElementById('object-bar')?.classList.remove('show');
      const print = renderPrint(target, state.mask, width, height);
      const printData = withMetricScale(print.toDataURL('image/png'));
      const scale = Math.min(1, 1200 / Math.max(width, height));
      const mockup = makeCanvas(Math.round(width * scale), Math.round(height * scale));
      const g = mockup.getContext('2d');
      if (!overlayState.overlay) {
        const fallback = renderPreviewFallback(state.mask, mockup.width, mockup.height);
        g.drawImage(fallback, 0, 0);
        fallback.width = fallback.height = 1;
      }
      g.drawImage(print, 0, 0, mockup.width, mockup.height);
      if (overlayState.overlay) g.drawImage(overlayState.overlay.canvas, 0, 0, mockup.width, mockup.height);
      const mockupData = mockup.toDataURL('image/png');
      print.width = print.height = 1;
      mockup.width = mockup.height = 1;
      context.printBase64 = printData;
      context.mockupBase64 = mockupData;
      const oldOverlay = document.getElementById('preview-phone-mask');
      if (oldOverlay) oldOverlay.style.display = 'none';
      const checker = document.querySelector('.design-checker');
      if (checker) checker.style.aspectRatio = width + ' / ' + height;
      document.getElementById('preview-image').src = mockupData;
      document.getElementById('preview-title').textContent = [context.modelName, context.styleName, context.colorName].filter(Boolean).join('・');
      const info = document.querySelector('.preview-info p');
      if (info) info.textContent = overlayState.overlay
        ? '請確認照片、文字與貼紙的位置。鏡頭孔及不可印刷的位置不會印上圖案；手機殼外框供預覽參考。'
        : '請確認照片、文字與貼紙的位置。此型號暫時隱藏無法可靠對齊的手機殼外框；白色區域代表可印範圍，鏡頭孔不會印上圖案。';
      navigate('page-preview');
    } catch (error) {
      console.error('[PREVIEW]', error);
      const msg = error && error.name === 'SecurityError' ? '圖片安全載入失敗，請重新整理後再按一次完成。' : (/[\u3400-\u9fff]/.test(error.message||'') ? error.message : '預覽產生失敗，請再試一次。');
      toast(msg);
    } finally {
      previewBusy = false;
      setBusy(false);
    }
  };

  if (typeof canvas !== 'undefined' && canvas) window.applyCaseBoundaryClip();
})();
