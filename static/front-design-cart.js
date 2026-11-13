/* Keep the protected checkout contract: the explicitly selected line occupies 'cart'. */
(function () {
  'use strict';
  const drafts = window.BenfuwanDesignDraft;
  const prefix = 'saved-cart:';
  const summaries = 'cart-summary:';
  let saving = false;
  const same = (a,b) => (!a && !b) || (!!a && !!b && a.draftKey === b.draftKey &&
    a.draftRevision === b.draftRevision && a.orderKey === b.orderKey &&
    a.quantity === b.quantity && a.payment === b.payment && a.printBase64 === b.printBase64);

  async function productStamp(item,catalog) {
    const model=catalog.models.find(m=>m.id===item.modelId && m.status!==false);
    const style=catalog.styles.find(s=>s.id===item.styleId && s.status!==false);
    const resolver=window.BenfuwanModelProfile;
    if (!BenfuwanProducts.ready(model,style)) throw Error('商品已下架或款式已變更，請返回設計確認。');
    const profile=resolver.profileFor(model,style.id);
    if (!profile.ready) throw Error('商品設定已更新，請返回設計確認。');
    const fields=[model.name,style.name,BenfuwanProducts.type(model),Number(style.price),
      style.model_colors?.[model.id] || style.colors,profile.previewUrl,profile.printUrl,
      profile.printW,profile.printH,profile.printX,profile.printY,profile.printAngle];
    const hash=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(fields)));
    return Array.from(new Uint8Array(hash),b=>b.toString(16).padStart(2,'0')).join('');
  }
  async function currentProduct(item) {
    if (!item?.productStamp || item.orderKey) return true;
    try {
      const response=await fetch('/api/shop_data',{cache:'no-store'});
      if (!response.ok) throw Error('無法確認最新商品資料，請連線後再試。');
      const json=await response.json(), catalog=json.data||json;
      if (item.productStamp!==await productStamp(item,catalog)) throw Error('商品或價格已更新，請按「繼續編輯」確認並重新儲存。');
      return true;
    } catch(error){toast(error.message || '無法確認最新商品資料');return false;}
  }

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
          const existing = current?.draftKey===target ? current : parked;
          if (newItem && existing) selected={...newItem,quantity:existing.quantity,payment:existing.payment};
          if (!selected || (newItem && (parked?.orderKey || current?.orderKey))) { tx.abort(); return; }
          if (current && current.draftKey !== target) {
            const key = current.draftKey || crypto.randomUUID();
            store.put({...current,draftKey:key},prefix+key);
            const {modelName,styleName,colorName,quantity,payment,price,orderKey,draftRevision}=current;
            store.put({draftKey:key,modelName,styleName,colorName,quantity,payment,price,orderKey,draftRevision},summaries+key);
          }
          store.delete(prefix+target);
          store.delete(summaries+target);
          store.put(selected,'cart');
        };
      };
      tx.oncomplete = () => resolve(selected);
      tx.onabort = () => reject(Error('購物車狀態已變更，請重新開啟購物車確認。'));
      tx.onerror = () => reject(tx.error);
    });
  }

  function withCartLock(action) {
    if (!navigator.locks) {toast('請使用支援安全購物車鎖定的新版瀏覽器。');return;}
    return navigator.locks.request('benfuwan-cart-write',action);
  }

  async function orderRequestStatus(key) {
    const response=await fetch('/api/order_request_status',{
      method:'POST',cache:'no-store',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({idempotency_key:key})
    });
    const data=await response.json();
    if(!response.ok||data.status!=='success')throw Error(data.msg||'目前無法確認送單結果');
    return data;
  }
  async function resolveSubmitted(item) {
    if(!item?.orderKey)return {state:'NOT_SUBMITTED'};
    try {
      const result=await orderRequestStatus(item.orderKey);
      if(result.state==='COMPLETED')return result;
      if(result.state!=='NOT_FOUND')throw Error('送單狀態不明，請稍後再試，設計已保留');
      // Two reads limit a race with an in-flight checkout. Absence alone is
      // not proof that a request cannot commit; never automatically re-submit.
      await new Promise(resolve=>setTimeout(resolve,900));
      const second=await orderRequestStatus(item.orderKey);
      if(second.state==='COMPLETED')return second;
      if(second.state!=='NOT_FOUND')throw Error('送單狀態仍待確認，請稍後再試');
      return second;
    }catch(error){
      toast(error.message||'無法查核送單結果，請稍後再試');
      return {state:'UNKNOWN'};
    }
  }
  async function unlockForNewDesign(item) {
    return withCartLock(async()=>{
      const db=await openIdb();
      return new Promise((resolve,reject)=>{
        const tx=db.transaction(IDB_STORE,'readwrite'),store=tx.objectStore(IDB_STORE);
        const active=cartItem&&same(cartItem,item);
        const key=active?'cart':prefix+item.draftKey;
        let updated;
        store.get(key).onsuccess=e=>{
          const stored=e.target.result;
          if(!stored||stored.orderKey!==item.orderKey||
             stored.draftKey!==item.draftKey||stored.draftRevision!==item.draftRevision){
            tx.abort();return;
          }
          updated={...stored,orderKey:null};
          store.put(updated,key);
        };
        tx.oncomplete=()=>{
          if(active){cartItem=updated;updateCartBadge();renderCart();}
          resolve(updated);
        };
        tx.onabort=()=>reject(Error('購物車已變更，請重新開啟確認'));
        tx.onerror=()=>reject(tx.error);
      });
    });
  }

  // Checkout, quantity changes and moving lines share the same origin-wide lock.
  for (const name of ['submitOrder','changeQty','choosePayment']) {
    const original = window[name];
    window[name] = function (...args) {
      const expected = cartItem;
      if (!expected || saving) return;
      return withCartLock(async()=>{
        if (name==='submitOrder') {
          if(expected.orderKey){
            const status=await resolveSubmitted(expected);
            if(status.state==='UNKNOWN')return;
            if(status.state==='COMPLETED'){
              toast('這筆設計已成立訂單：'+status.order_id+'。請勿重複下單，可返回購物車建立新設計。');
              return;
            }
          }
          if(!await currentProduct(expected))return;
        }
        if (!same(expected,await idbGet('cart'))) { toast('購物車已變更，請重新開啟確認。');return; }
        return original.apply(this,args);
      });
    };
  }

  const confirmCart = window.confirmDesignToCart;
  window.confirmDesignToCart = async function () {
    if (saving) return;
    const previous = cartItem;
    saving = true;
    try {
      if (previous?.orderKey) throw Error('上次送單結果尚待確認，請先返回結帳確認。');
      const originalKey=drafts.key;
      if (!await drafts.saveNow() || drafts.key!==originalKey) return;
      await confirmCart.apply(this,arguments);
      if (!cartItem || cartItem === previous) return;
      const item = {...cartItem,draftKey:drafts.key,draftRevision:drafts.revision};
      item.productStamp=await productStamp(item,shopData);
      cartItem = await withCartLock(()=>exchange(previous,drafts.key,item));
      if (!cartItem) throw Error('購物車未能保存');
      updateCartBadge();renderCart();navigate('page-cart');toast('已儲存至購物車');
    } catch(error) {
      cartItem = previous;
      toast(error.message || '購物車儲存失敗，草稿已保留。');
    } finally { saving = false; }
  };
  async function remove(item,parked=false) {
    if(!item||saving)return;
    const result=await resolveSubmitted(item);
    if(result.state==='UNKNOWN')return;
    const message=result.state==='COMPLETED'
      ?'這筆商品已成立訂單 '+result.order_id+'。移出購物車不會取消原訂單或退回庫存，確定只清除購物車項目？'
      :'從購物車移除這項商品？已保存的草稿會保留在「我的設計」。';
    if(!confirm(message))return;
    await withCartLock(async()=>{
      try {
        const db=await openIdb(), key=parked?prefix+item.draftKey:'cart';
        await new Promise((resolve,reject)=>{
          const tx=db.transaction(IDB_STORE,'readwrite'),store=tx.objectStore(IDB_STORE);
          store.get(key).onsuccess=e=>{
            const stored=e.target.result;
            if(!stored || stored.orderKey!==item.orderKey || (parked?stored.draftRevision!==item.draftRevision:!same(item,stored))){tx.abort();return;}
            store.delete(key);
            if(parked)store.delete(summaries+item.draftKey);
          };
          tx.oncomplete=resolve;tx.onabort=()=>reject(Error('購物車已變更，請重新確認。'));
        });
        cartItem=await idbGet('cart');updateCartBadge();renderCart();
      } catch(error){toast(error.message);}
    });
  }
  async function edit(item) {
    if(saving)return;
    if(!item.draftKey||!await idbGet(item.draftKey))return toast('此舊項目沒有可還原的編輯草稿，請保留購物車並聯絡店家。');
    try {await loadAll();}catch(error){return toast('無法確認最新商品資料，草稿已保留，請連線後再試。');}
    if(item.orderKey){
      const result=await resolveSubmitted(item);
      if(result.state==='UNKNOWN')return;
      if(result.state==='COMPLETED'&&!confirm(
        '此商品已成立訂單 '+result.order_id+'。繼續編輯將建立新設計，不會修改或取消已成立的訂單。確定？'))return;
      if(result.state==='NOT_FOUND'&&!confirm(
        '伺服器目前未找到這次送單紀錄。若原請求仍在處理，可能稍後成立訂單；確定要以新設計繼續編輯？'))return;
      try {item=await unlockForNewDesign(item);}catch(error){return toast(error.message);}
    }
    if(await drafts.continueEditing(item.draftKey)){
      ctx.quantity=item.quantity;ctx.payment=item.payment;
      const button=document.querySelector('.preview-buttons .primary');
      if(button)button.textContent='儲存購物車修改';
    }else toast('此設計無法安全恢復，草稿已保留。');
  }
  async function others() {
    const db = await openIdb();
    return new Promise((resolve,reject) => {
      const req = db.transaction(IDB_STORE).objectStore(IDB_STORE).getAll(IDBKeyRange.bound(summaries,summaries+'\uffff'));
      req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);
    });
  }
  const badge = window.updateCartBadge;
  let badgeEpoch=0;
  window.updateCartBadge = function(){
    badge();
    const token=++badgeEpoch;
    others().then(items=>{
      if(token!==badgeEpoch)return;
      const count=items.reduce((n,i)=>n+Math.max(1,i.quantity||1),cartItem?Math.max(1,cartItem.quantity||1):0);
      const el=document.getElementById('cart-badge');
      if(el){el.textContent=count;el.classList.toggle('show',count>0);}
    }).catch(console.warn);
  };
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
          try { cartItem=await withCartLock(()=>exchange(cartItem,item.draftKey,null));updateCartBadge();goCheckoutFromCart(); }
          catch(error){toast(error.message);}
        };
        const del=document.createElement('button');del.className='secondary';del.textContent='移出購物車';del.onclick=()=>remove(item,true);
        const detail=document.createElement('p');detail.textContent='NT$ '+Number(item.price).toLocaleString()+' × '+item.quantity;
        row.append(title,detail,editBtn,checkout,del);host.append(row);
      }
    }).catch(error=>toast(error.message));
  };
  const checkout=window.goCheckoutFromCart;
  window.goCheckoutFromCart=async function(){
    const item=cartItem;
    if(!saving && await currentProduct(item) && item===cartItem) checkout.apply(this,arguments);
  };
  window.openCartFromNav=async function(){cartItem=await idbGet('cart');renderCart();navigate('page-cart');};
  window.BenfuwanDraftCart={edit,remove, get staging(){return saving;}};
})();
