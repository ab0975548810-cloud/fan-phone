/* 本福丸：共用打印蒙版、透明鏡頭孔及公制輸出。載入於其他前台修補程式之後。 */
(function () {
  'use strict';

  const PIXELS_PER_MM = 20; // 508 DPI；與 1:1 素材的 20 px/mm 相同。
  const states = new WeakMap();
  let previewBusy = false;

  function loadImage(url, message) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = 'anonymous';
      const timer = setTimeout(() => finish(new Error(message)), 15000);
      function finish(error) {
        clearTimeout(timer);
        img.onload = img.onerror = null;
        if (error) reject(error);
        else resolve(img);
      }
      img.onload = () => finish(img.naturalWidth && img.naturalHeight ? null : new Error(message));
      img.onerror = () => finish(new Error(message));
      img.src = url;
    });
  }

  function makeCanvas(width, height) {
    const el = document.createElement('canvas');
    el.width = width;
    el.height = height;
    return el;
  }

  function validateAlpha(img) {
    const check = makeCanvas(128, 128);
    const g = check.getContext('2d', { willReadFrequently: true });
    g.drawImage(img, 0, 0, 128, 128);
    const pixels = g.getImageData(0, 0, 128, 128).data;
    let transparent = false, printable = false;
    for (let i = 3; i < pixels.length; i += 4) {
      transparent ||= pixels[i] === 0;
      printable ||= pixels[i] > 0;
    }
    if (!transparent || !printable) throw new Error('這個型號的可印範圍尚未設定完成，請聯絡店家。');
  }

  function ensureClip(target, url, retry = false) {
    const key = [url, target.width, target.height].join('|');
    let state = states.get(target);
    if (state && state.key === key && !(retry && state.error)) {
      target.clipPath = state.clip;
      target.requestRenderAll();
      return state.ready;
    }
    // Loading or failed masks must never expose an unmasked production design.
    const empty = new fabric.Rect({ width: 0, height: 0, strokeWidth: 0, excludeFromExport: true });
    state = { key, clip: empty, image: null, error: null };
    states.set(target, state);
    target.clipPath = empty;
    target.requestRenderAll();
    state.ready = (async () => {
      try {
        if (!url) throw new Error('這個型號尚未設定可印範圍，請選擇其他型號或聯絡店家。');
        const img = await loadImage(url, '可印範圍讀取失敗，請稍後重新預覽。');
        validateAlpha(img);
        if (canvas !== target || states.get(target) !== state) throw new Error('型號已切換，請重新預覽。');
        state.image = img;
        state.clip = new fabric.Image(img, {
          left: 0, top: 0, originX: 'left', originY: 'top',
          scaleX: target.width / img.naturalWidth,
          scaleY: target.height / img.naturalHeight,
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
    const target = canvas;
    ensureClip(target, ctx.printLineUrl || '').catch(error => {
      if (canvas === target && typeof toast === 'function') toast(/[\u3400-\u9fff]/.test(error.message) ? error.message : '可印範圍無法讀取，請聯絡店家。');
    });
  };

  // PNG pHYs preserves physical size. Browser canvas otherwise writes 96 DPI.
  function withMetricScale(dataUrl) {
    const binary = atob(dataUrl.split(',')[1]);
    const input = Uint8Array.from(binary, char => char.charCodeAt(0));
    const chunk = new Uint8Array(21);
    const view = new DataView(chunk.buffer);
    view.setUint32(0, 9);
    chunk.set([112, 72, 89, 115], 4); // pHYs
    view.setUint32(8, PIXELS_PER_MM * 1000);
    view.setUint32(12, PIXELS_PER_MM * 1000);
    chunk[16] = 1; // metre
    let crc = 0xffffffff;
    for (const byte of chunk.subarray(4, 17)) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
    view.setUint32(17, (crc ^ 0xffffffff) >>> 0);
    const parts = [input.subarray(0, 33), chunk]; // PNG signature + IHDR
    const sourceView = new DataView(input.buffer);
    for (let pos = 33; pos < input.length;) {
      const end = pos + sourceView.getUint32(pos) + 12;
      if (!(input[pos + 4] === 112 && input[pos + 5] === 72 && input[pos + 6] === 89 && input[pos + 7] === 115)) {
        parts.push(input.subarray(pos, end));
      }
      pos = end;
    }
    const out = new Uint8Array(parts.reduce((sum, part) => sum + part.length, 0));
    let offset = 0;
    for (const part of parts) { out.set(part, offset); offset += part.length; }
    const strings = [];
    for (let pos = 0; pos < out.length; pos += 32768) strings.push(String.fromCharCode(...out.subarray(pos, pos + 32768)));
    return 'data:image/png;base64,' + btoa(strings.join(''));
  }

  function renderPrint(target, maskImage, width, height) {
    const hidden = target.getObjects().filter(o => ['guide', 'slot-guide'].includes(o.role));
    const visibility = hidden.map(o => o.visible);
    const originalClip = target.clipPath;
    let source;
    try {
      hidden.forEach(o => { o.visible = false; });
      // Render objects with their own photo crops, then apply the original mask
      // once at output resolution, avoiding a second softened/cached mask edge.
      target.clipPath = null;
      source = target.toCanvasElement(Math.max(width / target.width, height / target.height));
    } finally {
      target.clipPath = originalClip;
      hidden.forEach((o, i) => { o.visible = visibility[i]; });
      target.renderAll();
    }
    const output = makeCanvas(width, height);
    const g = output.getContext('2d');
    g.drawImage(source, 0, 0, width, height);
    g.globalCompositeOperation = 'destination-in';
    g.drawImage(maskImage, 0, 0, width, height);
    g.globalCompositeOperation = 'source-over';
    source.width = source.height = 1;
    return output;
  }

  window.openPreview = async function () {
    if (typeof canvas === 'undefined' || !canvas || previewBusy) return;
    previewBusy = true;
    const target = canvas, context = ctx;
    const maskUrl = context.printLineUrl || '', overlayUrl = context.maskUrl || '';
    context.printBase64 = context.mockupBase64 = null;
    setBusy(true, '正在產生高畫質預覽...');
    try {
      const [state, overlay] = await Promise.all([
        ensureClip(target, maskUrl, true),
        overlayUrl ? loadImage(overlayUrl, '手機殼預覽讀取失敗，請再試一次。') : Promise.resolve(null)
      ]);
      if (canvas !== target || ctx !== context || context.printLineUrl !== maskUrl || context.maskUrl !== overlayUrl) {
        throw new Error('型號已切換，請重新預覽。');
      }
      const width = Math.round(Number(context.printW) * PIXELS_PER_MM);
      const height = Math.round(Number(context.printH) * PIXELS_PER_MM);
      if (!(width > 0 && height > 0) || width * height > 16000000) throw new Error('手機殼尺寸設定有誤，請聯絡店家。');
      target.discardActiveObject();
      document.getElementById('object-bar')?.classList.remove('show');
      const print = renderPrint(target, state.image, width, height);
      const printData = withMetricScale(print.toDataURL('image/png'));
      const scale = Math.min(1, 1200 / Math.max(width, height));
      const mockup = makeCanvas(Math.round(width * scale), Math.round(height * scale));
      const g = mockup.getContext('2d');
      g.drawImage(print, 0, 0, mockup.width, mockup.height);
      if (overlay) g.drawImage(overlay, 0, 0, mockup.width, mockup.height);
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
      if (info) info.textContent = '請確認照片、文字與貼紙的位置。鏡頭孔及不可印刷的位置不會印上圖案；手機殼外框供預覽參考。';
      navigate('page-preview');
    } catch (error) {
      console.error(error);
      toast(/[\u3400-\u9fff]/.test(error.message) ? error.message : '預覽產生失敗，請再試一次。');
    } finally {
      previewBusy = false;
      setBusy(false);
    }
  };

  if (typeof canvas !== 'undefined' && canvas) window.applyCaseBoundaryClip();
})();
