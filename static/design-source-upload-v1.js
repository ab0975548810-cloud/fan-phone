/* Images stay in local cart/draft; only verified receipts enter create_order JSON. */
(function(){
  'use strict';
  const MAX_FILE=24*1024*1024,MAX_TOTAL=70*1024*1024,MAX_PIXELS=64000000;
  async function prepare(design){
    const result=structuredClone(design),checkout=crypto.randomUUID().replaceAll('-','');
    result.sourceCheckout=checkout;
    const seen=new Map();let total=0,pixels=0;
    async function visit(items){for(const item of items){
      if(item.type==='image'){
        if(!/^data:image\/png;base64,/.test(item.src||''))throw Error('原始素材缺失，請重新加入購物車');
        const encoded=item.src.split(',')[1];if(encoded.length>Math.ceil(MAX_FILE/3)*4)throw Error('單張原始素材上限為 24MB');
        const decoded=atob(encoded),bytes=new Uint8Array(decoded.length);for(let i=0;i<decoded.length;i++)bytes[i]=decoded.charCodeAt(i);
        const blob=new Blob([bytes],{type:'image/png'});
        if(!blob.size||blob.size>MAX_FILE)throw Error('單張原始素材上限為 24MB');
        const hash=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await blob.arrayBuffer())),v=>v.toString(16).padStart(2,'0')).join('');
        if(!seen.has(hash)){
          const intrinsic=item.sourceSize||item;total+=blob.size;pixels+=intrinsic.width*intrinsic.height;
          if(total>MAX_TOTAL||pixels>MAX_PIXELS)throw Error('原始素材總容量或總像素過大，請減少圖片');
          const form=new FormData();form.append('checkout',checkout);form.append('file',blob,'source.png');
          const response=await fetch('/api/design-sources',{method:'POST',body:form,credentials:'same-origin',cache:'no-store'}),data=await response.json();
          if(!response.ok||data.status!=='success')throw Error(data.msg||'原始素材上傳失敗');
          if(data.sha256!==hash||data.width!==intrinsic.width||data.height!==intrinsic.height)throw Error('原始素材驗證不一致');
          seen.set(hash,data);
        }
        const source=seen.get(hash);item.sourceRef=source.sourceRef;item.sourceSha256=hash;delete item.src;delete item.publicSrc;
      }
      if(item.objects)await visit(item.objects);
      if(item.clipPath)await visit([item.clipPath]);
    }}
    try{await visit(result.objects);return result;}catch(error){await release(result);throw error;}
  }
  async function release(design){const objects=[];const scan=items=>{for(const o of items||[]){if(o.sourceRef)objects.push({sourceRef:o.sourceRef});scan(o.objects);if(o.clipPath)scan([o.clipPath]);}};scan(design.objects);if(!objects.length)return;try{await fetch('/api/design-sources/release',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({render_contract_version:design.render_contract_version,sourceCheckout:design.sourceCheckout,objects}),credentials:'same-origin'});}catch(_){} }
  window.BenfuwanDesignSources={prepare,release};
})();
