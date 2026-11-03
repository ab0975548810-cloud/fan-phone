/* Keep the protected checkout contract: the explicitly selected line occupies 'cart'. */
(function () {
  'use strict';
  const drafts = window.BenfuwanDesignDraft;
  const prefix = 'saved-cart:';
  let saving = false;
  const same = (a,b) => (!a && !b) || (!!a && !!b && a.draftKey === b.draftKey &&
    a.draftRevision === b.draftRevision && a.orderKey === b.orderKey &&
    a.quantity === b.quantity && a.payment === b.payment && a.printBase64 === b.printBase64);

  async function exchange(expected, target, newItem) {
    const db = await openIdb();
    return new Promise((resolve,reject) => {
      const tx = db.transaction(IDB_STORE,'readwrite'), store = tx.objectStore(IDB_STORE);
      let selected;
      store.get('cart').onsuccess = e => {
        const current = e.target.result;
        if (!same(current,expected)) { tx.abort(); return; }
        store.get(prefix+target).onsuccess = e => {
          const parked = e.target.result;
          selected = newItem || parked;
          if (!selected || (newItem && (parked?.orderKey || current?.orderKey))) { tx.abort(); return; }
          if (current && current.draftKey !== target) {
            const key = current.draftKey || crypto.randomUUID();
            store.put({...current,draftKey:key},prefix+key);
          }
          store.delete(prefix+target);
          store.put(selected,'cart');
        };
      };
      tx.oncomplete = () => resolve(selected);
      tx.onabort = () => reject(Error('購物車狀態已變更，請重新開啟購物車確認。'));
      tx.onerror = () => reject(tx.error);
    });
  }

  const confirmCart = window.confirmDesignToCart;
  window.confirmDesignToCart = async function () {
    if (saving) return;
    const previous = cartItem;
    saving = true;
    try {
      if (previous?.orderKey) throw Error('上次送單結果尚待確認，請先返回結帳確認。');
      if (!await drafts.saveNow()) return;
      await confirmCart.apply(this,arguments);
      if (!cartItem || cartItem === previous) return;
      const item = {...cartItem,draftKey:drafts.key,draftRevision:drafts.revision};
      cartItem = await exchange(previous,drafts.key,item);
      updateCartBadge();renderCart();navigate('page-cart');toast('已儲存至購物車');
    } catch(error) {
      cartItem = previous;
      toast(error.message || '購物車儲存失敗，草稿已保留。');
    } finally { saving = false; }
  };
  async function edit(item) {
    if (saving) return;
    if (item.orderKey) return toast('此項目已有送單紀錄，請先確認送單結果。');
    if (!item.draftKey || !await idbGet(item.draftKey)) return toast('此舊項目沒有可還原的編輯草稿。');
    if (await drafts.continueEditing(item.draftKey)) {
      ctx.quantity = item.quantity; ctx.payment = item.payment;
      document.querySelector('.preview-buttons .primary').textContent = '儲存購物車修改';
    } else toast('此設計無法安全恢復，草稿已保留。');
  }
  async function others() {
    const db = await openIdb();
    return new Promise((resolve,reject) => {
      const req = db.transaction(IDB_STORE).objectStore(IDB_STORE).getAll(IDBKeyRange.bound(prefix,prefix+'\uffff'));
      req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);
    });
  }
  let epoch=0;
  const render = window.renderCart;
  window.renderCart = function () {
    render.apply(this,arguments);
    const token=++epoch, host=document.getElementById('cart-other-items');
    host.replaceChildren();
    others().then(items=>{
      if (token!==epoch) return;
      if(items.length) document.getElementById('cart-empty').classList.remove('show');
      for(const item of items){
        const row=document.createElement('div'), title=document.createElement('h3');
        row.className='card';title.textContent=[item.modelName,item.styleName,item.colorName].filter(Boolean).join(' · ');
        const editBtn=document.createElement('button'),checkout=document.createElement('button');
        editBtn.className='secondary';checkout.className='primary';
        editBtn.textContent='繼續編輯';checkout.textContent='前往結帳';
        editBtn.onclick=()=>edit(item);
        checkout.onclick=async()=>{
          try { cartItem=await exchange(cartItem,item.draftKey,null);updateCartBadge();goCheckoutFromCart(); }
          catch(error){toast(error.message);}
        };
        row.append(title,editBtn,checkout);host.append(row);
      }
    }).catch(error=>toast(error.message));
  };
  window.openCartFromNav=async function(){cartItem=await idbGet('cart');renderCart();navigate('page-cart');};
  window.BenfuwanDraftCart={edit, get staging(){return saving;}};
})();
