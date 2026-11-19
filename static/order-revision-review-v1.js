/* Both editing modes compare immutable server artwork before separate dispatch. */
(function(){
  'use strict';
  const style=document.createElement('style');style.textContent='.revision-compare{max-width:95vw;max-height:90vh;overflow:auto}.revision-compare button,.revision-compare input{min-height:44px;margin:4px;font-size:16px;max-width:100%}.revision-pair{display:flex;gap:8px}.revision-pair a{width:50%;min-width:0;text-align:center}.revision-pair img{display:block;width:100%;height:45vh;object-fit:contain;background:repeating-conic-gradient(#ddd 0% 25%,#fff 0% 50%) 0/12px 12px}';document.head.append(style);
  window.BenfuwanRevisionReview={async open({orderId,work,valid,prefix='revision'}){
    if(document.getElementById(prefix+'-compare'))return;
    const api=async(path,data)=>{const r=await fetch('/api/admin/order-design/'+encodeURIComponent(orderId)+'/revision'+path,{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-Order-Design':'1'},body:JSON.stringify(data)});const j=await r.json();if(!r.ok||j.status!=='success')throw Error(j.msg||'版本服務暫時無法使用');return j;};
    const identity={version:work.version,hash:work.hash};
    const reviewed=await api('/review',identity);
    if(document.getElementById(prefix+'-compare'))return;
    if(!valid())throw Error('設計已變更，請重新保存與比較');
    const dialog=document.createElement('dialog');dialog.id=prefix+'-compare';dialog.className='revision-compare';
    const label=document.createElement('p');label.textContent='V1 原生產圖 ／ V'+work.version+' 修改生產圖（可開原尺寸圖片核對）';dialog.append(label);
    const pair=document.createElement('div');pair.className='revision-pair';dialog.append(pair);const loaded=[];
    for(const key of ['basePath','outputPath']){const a=document.createElement('a');a.href=reviewed.design[key];a.target='_blank';a.rel='noopener';const caption=document.createElement('strong');caption.textContent=key==='basePath'?'V1 原圖':'V'+work.version+' 修改圖';const im=new Image();im.alt=caption.textContent;loaded.push(new Promise((ok,no)=>{im.onload=ok;im.onerror=()=>no(Error('比較圖片載入失敗，禁止確認'));}));im.src=reviewed.design[key==='basePath'?'basePreview':'outputPreview']||a.href;a.append(caption,im);pair.append(a);}
    const warning=document.createElement('p');warning.textContent=!reviewed.design.profile?'缺少可核對的歷史列印定位：可保存修改，但禁止送印。':!reviewed.enabled?'修改版送印尚未啟用；可先保存與比較。':'沿用與 V1 雜湊相符的歷史列印定位。確認只建立獨立任務，仍需另按傳送。';dialog.append(warning);
    const reason=document.createElement('input');reason.placeholder='重印原因';reason.id=prefix+'-reason';dialog.append(reason);
    const cost=document.createElement('input');cost.type='number';cost.min='0';cost.step='0.01';cost.placeholder='重印成本（元）';cost.id=prefix+'-cost';dialog.append(cost);
    const button=(text,id,fn)=>{const b=document.createElement('button');b.textContent=text;b.id=prefix+'-'+id;b.onclick=fn;dialog.append(b);return b;};
    const confirm=button('已比較，確認此版本並建立重印任務','confirm',async()=>{
      confirm.disabled=true;
      try{if(!valid())throw Error('設計已變更，請重新保存與比較');const cents=Number(cost.value)*100;if(!cost.value||!Number.isFinite(cents)||Math.abs(cents-Math.round(cents))>1e-6)throw Error('請填有效成本，最多兩位小數');const r=await api('/confirm',{...identity,confirm:'compared-v1-v2',reason:reason.value,costCents:Math.round(cents)});warning.textContent=r.msg;send.disabled=false;}
      catch(e){warning.textContent=e.message;confirm.disabled=false;}
    });confirm.disabled=true;
    const send=button('傳送此獨立任務至銳印','send',async()=>{
      if(!valid()){warning.textContent='設計已變更，請重新保存與比較';send.disabled=true;return;}
      if(!window.confirm('確定將已確認的 V'+work.version+' 傳送至銳印？不會新增銷售訂單。'))return;
      send.disabled=true;try{const r=await api('/send',identity);warning.textContent='任務 '+r.jobId+'：'+r.state;}
      catch(e){warning.textContent=e.message+'；請到列印中心查核，不要重複建立版本送印';}
    });send.disabled=true;
    dialog.addEventListener('close',()=>{
      for(const img of pair.querySelectorAll('img'))img.removeAttribute('src');
      dialog.remove();
    },{once:true});
    button('關閉','close',()=>dialog.close());document.body.append(dialog);dialog.showModal();
    try{await Promise.all(loaded);confirm.disabled=!reviewed.design.profile||!reviewed.enabled||work.version<2||!valid();}catch(e){warning.textContent=e.message;}
  }};
})();
