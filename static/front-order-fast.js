/* 本福丸：訂單改用 multipart 傳 PNG，避免 base64 JSON + Fabric 圖片資料重複上傳。 */
(function(){
  'use strict';
  if(window.__benfuwanFastOrderInstalled)return;
  window.__benfuwanFastOrderInstalled=true;

  function dataUrlToBlob(dataUrl){
    const m=String(dataUrl||'').match(/^data:([^;,]+);base64,(.+)$/);
    if(!m)throw new Error('列印圖片格式錯誤');
    const bin=atob(m[2]);
    const out=new Uint8Array(bin.length);
    for(let i=0;i<bin.length;i++)out[i]=bin.charCodeAt(i);
    return new Blob([out],{type:m[1]||'image/png'});
  }

  // Fabric JSON contains every embedded data URL and can be larger than the
  // actual production PNG. Orders already retain production + preview files,
  // so do not duplicate all source images into IndexedDB/server payloads.
  confirmDesignToCart=async function(){
    if(!ctx.printBase64){toast('請先完成設計預覽');return}
    cartItem={
      modelId:ctx.modelId,modelName:ctx.modelName,
      styleId:ctx.styleId,styleName:ctx.styleName,
      price:parseInt(ctx.price)||390,
      quantity:Math.max(1,ctx.quantity||1),
      printBase64:ctx.printBase64,
      mockupBase64:ctx.mockupBase64||ctx.printBase64,
      payment:ctx.payment||'現金',
      designJson:null
    };
    await idbSet('cart',cartItem);
    updateCartBadge();renderCart();navigate('page-cart');toast('已加入購物車 ♡');
  };

  submitOrder=async function(){
    const surname=$('form-surname').value.trim(),title=$('form-title').value;
    if(!surname){toast('請填寫貴姓');return}
    if(!cartItem)cartItem=await idbGet('cart');
    if(!cartItem||!cartItem.printBase64){toast('購物車沒有設計，請返回重新加入');return}

    const customerName=surname+title,item=cartItem;
    const p=parseInt(item.price)||390,q=Math.max(1,item.quantity||1),total=p*q;
    const btn=$('submit-order');
    btn.disabled=true;btn.textContent='訂單處理中...';
    setBusy(true,'正在快速上傳列印檔...');
    try{
      const fd=new FormData();
      fd.append('print_file',dataUrlToBlob(item.printBase64),'print.png');
      fd.append('mockup_file',dataUrlToBlob(item.mockupBase64||item.printBase64),'preview.png');
      fd.append('model_id',item.modelId||'');
      fd.append('style_id',item.styleId||'');
      fd.append('model_name',item.modelName||'');
      fd.append('style_name',item.styleName||'');
      fd.append('quantity',String(q));
      fd.append('customer_name',customerName);
      fd.append('payment_method',item.payment||ctx.payment||'現金');

      const r=await fetch('/api/create_order_fast',{method:'POST',body:fd,cache:'no-store'});
      let j={};try{j=await r.json()}catch(e){}
      if(!r.ok||j.status!=='success')throw new Error(j.msg||`送單失敗 HTTP ${r.status}`);

      $('success-id').textContent=j.order_id;
      $('success-name').textContent=customerName;
      $('success-pay').textContent=item.payment||ctx.payment||'現金';
      $('success-total').textContent='NT$ '+Number(j.total||total).toLocaleString();
      cartItem=null;await idbDel('cart');updateCartBadge();
      history.pushState({page:'page-success'},'',location.pathname+'#success');
      showPage('page-success');
    }catch(e){
      console.error(e);toast('送單失敗：'+e.message);
    }finally{
      setBusy(false);btn.disabled=false;btn.textContent='確認下單';
    }
  };

  console.info('[ORDER] fast multipart checkout enabled');
})();
