/* The order workspace owns navigation and loads the sticker catalog on demand. */
(() => {
  const openStickers = window.openStickerSheet;
  let stickers;
  window.openStickerSheet = async function () {
    if (!stickers) {
      stickers = fetch('/api/assets', {cache: 'no-store'}).then(async response => {
        if (!response.ok) throw Error('貼紙庫暫時無法載入');
        const result = await response.json();
        assetsData = result.data || result;
      }).catch(error => { stickers = null; throw error; });
    }
    try {
      await stickers;
      return openStickers();
    } catch (error) {
      toast(error.message);
    }
  };
  window.BenfuwanOrderWorkspace = {
    openEditor() {
      document.getElementById('workspace-loading')?.remove();
      history.replaceState({page: 'page-editor'}, '', location.href);
      showPage('page-editor');
    },
    addGuide(url, message, panel, existing = false) {
      const controls = document.createElement('fieldset');
      controls.id = 'order-alignment-controls';
      const hint = document.createElement('p');
      hint.textContent = message;
      controls.append(hint);
      panel.append(controls);
      if (!url && !existing) return hint;
      const canvasShell = document.getElementById('canvas-shell');
      const guide = new Image();
      guide.id = 'order-alignment-image';
      guide.alt = '';
      guide.setAttribute('aria-hidden', 'true');
      guide.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;z-index:8;pointer-events:none;opacity:.65';
      const visible = document.createElement('input');
      visible.type = 'checkbox';
      visible.checked = true;
      const alpha = document.createElement('input');
      alpha.type = 'range';
      alpha.min = '0'; alpha.max = '100'; alpha.value = '65';
      const label = (text, input) => {
        const label = document.createElement('label');
        label.append(input, ' ' + text);
        return label;
      };
      controls.append(label('顯示原始蒙版', visible), label('蒙版透明度', alpha));
      const apply = () => {
        const opacity = visible.checked ? Number(alpha.value) / 100 : 0;
        if (existing) canvasShell.style.setProperty('--order-guide-opacity', opacity);
        else {
          guide.hidden = !visible.checked;
          guide.style.opacity = String(opacity);
        }
      };
      visible.onchange = alpha.oninput = apply;
      if (existing) {
        canvasShell.classList.add('order-existing-alignment');
        apply();
        return hint;
      }
      guide.onerror = () => {
        guide.remove();
        visible.disabled = alpha.disabled = true;
        hint.textContent = '原始蒙版缺失或無法讀取，暫停顯示。';
      };
      canvasShell.append(guide);
      guide.src = url;
      return hint;
    }
  };
})();
