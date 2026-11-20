/* The order workspace owns navigation and loads the sticker catalog on demand. */
(() => {
  const openStickers = window.openStickerSheet;
  let stickers, catalogTag;
  window.openStickerSheet = async function () {
    if (!stickers) {
      stickers = fetch('/api/admin/order-design/stickers', {cache:'no-store',credentials:'same-origin',headers:catalogTag?{'If-None-Match':catalogTag}:{}}).then(async response => {
        if(response.status===304)return;
        if (!response.ok) throw Error('貼紙庫暫時無法載入');
        const result = await response.json();
        assetsData = result.data;
        catalogTag=response.headers.get('ETag');
      }).finally(() => { stickers = null; });
    }
    try {
      await stickers;
      return openStickers();
    } catch (error) {
      toast(error.message);
    }
  };
  window.BenfuwanOrderWorkspace = {
    async finish(orderId, work) {
      const response=await fetch('/api/admin/order-design/'+encodeURIComponent(orderId)+'/revision/finish',{
        method:'POST',credentials:'same-origin',cache:'no-store',
        headers:{'Content-Type':'application/json','X-Order-Design':'1'},
        body:JSON.stringify({version:work.version,hash:work.hash})
      });
      const data=await response.json();
      if(!response.ok||data.status!=='success')throw Error(data.msg||'請到列印中心核對製作狀態');
      let link=document.getElementById('production-order-edit');
      if(!link){
        link=document.createElement('a');
        link.id='production-order-edit';
        document.querySelector('#pixel-tools,#order-design-banner').append(link);
      }
      link.href='/admin/order-design/'+encodeURIComponent(data.productionOrder);
      link.textContent='重新編輯 '+data.productionOrder;
      return 'V'+work.version+' 已保存；製作單 '+data.productionOrder+' · '+data.msg;
    },
    openEditor() {
      document.querySelector('#page-editor .done').onclick=()=>window.confirmDesignToCart();
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
        if (existing) canvasShell.querySelectorAll('#phone-mask,#print-area-guide,#safe-guide').forEach(el=>el.style.setProperty('opacity',opacity,'important'));
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
