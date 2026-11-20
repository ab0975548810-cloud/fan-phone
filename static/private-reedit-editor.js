/* Loaded only by the isolated order editor. Drafts stay in the private volume. */
(() => {
  const banner=document.createElement('aside');
  banner.id='private-reedit-status';
  banner.setAttribute('role','status');
  banner.style.cssText='position:relative;z-index:10;background:#fff1c2;color:#462f00;padding:6px;text-align:center';
  banner.textContent='重新編輯（測試）· 私有工作副本 · 僅使用假設備';
  document.body.prepend(banner);
  async function references(){
    const r=await fetch('/private/info',{cache:'no-store'});
    if(!r.ok)return;
    const info=await r.json();
    const details=document.createElement('details');
    const summary=document.createElement('summary');
    summary.textContent='原圖、定位與測試製作紀錄';
    details.append(summary);
    const preview=document.createElement('a');
    preview.href='/private/reference/preview';
    preview.textContent='查看封存預覽圖';
    preview.target='_blank';preview.rel='noopener';
    details.append(preview);
    for(const note of info.review){
      const p=document.createElement('p');p.textContent=note;details.append(p);
    }
    for(const record of info.orders){
      const p=document.createElement('p'),link=document.createElement('a');
      link.href='/admin/order-design/'+record.order+location.search;
      link.textContent=record.order+' · '+record.state+(record.task?' · '+record.task:'');
      p.append(link);details.append(p);
    }
    if(info.alignment&&new URLSearchParams(location.search).get('pixel')==='1'){
      const label=document.createElement('label'),check=document.createElement('input');
      check.type='checkbox';label.append(check,' 顯示原始刀模');
      const opacity=document.createElement('input');
      opacity.type='range';opacity.min='0';opacity.max='100';opacity.value='65';opacity.setAttribute('aria-label','刀模透明度');
      const guide=new Image();guide.alt='原始刀模';
      guide.style.cssText='position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:8;opacity:.65';
      check.onchange=()=>{
        if(check.checked&&!guide.src){
          document.querySelector('#canvas-shell').append(guide);
          guide.src='/private/reference/alignment';
          guide.onerror=()=>{guide.remove();label.textContent='此刀模缺少可顯示的印刷邊界';opacity.disabled=true;};
        }
        guide.hidden=!check.checked;
      };
      opacity.oninput=()=>guide.style.opacity=Number(opacity.value)/100;
      details.append(label,opacity);
    }
    banner.after(details);
  }
  references().catch(()=>{});
  window.privateReeditFinished=async (id,work)=>{
    const response=await fetch('/private/finish/'+encodeURIComponent(id),{method:'POST',
      headers:{'X-Reedit-Test':'1','Content-Type':'application/json'},
      body:JSON.stringify({hash:work.hash,version:work.version})});
    if(!response.ok)throw Error('草稿已保存，測試製作單尚未確認');
    const result=await response.json();
    const link=document.createElement('a');
    link.href=result.location;
    link.textContent='重新編輯 '+result.order;
    banner.replaceChildren('測試模式 · '+result.state+' · ',link);
  };
  async function checkpoint(id,method,body){
    const r=await fetch('/private/checkpoint/'+encodeURIComponent(id),{method,
      headers:{'X-Reedit-Test':'1','Content-Type':'application/json'},body});
    if(!r.ok)throw Error('私有草稿暫時無法存取');
    return r.json();
  }
  window.BenfuwanPixelRecovery={
    async read(id){
      const draft=await checkpoint(id,'GET');
      if(draft)draft.assets=draft.assets.map(([url,data])=>[url,Uint8Array.from(atob(data),c=>c.charCodeAt(0)).buffer]);
      return draft;
    },
    async write(id,draft){
      const assets=await Promise.all(draft.assets.map(async ([url,bytes])=>{
        const blob=bytes instanceof Blob?bytes:new Blob([bytes]);
        const data=await new Promise((resolve,reject)=>{
          const reader=new FileReader();
          reader.onload=()=>resolve(reader.result.split(',')[1]);
          reader.onerror=reject;
          reader.readAsDataURL(blob);
        });
        return [url,data];
      }));
      await checkpoint(id,'POST',JSON.stringify({...draft,assets}));
    },
    remove:id=>checkpoint(id,'DELETE')
  };
  async function refresh(){
    try{
      if(!(await fetch('/private/active',{cache:'no-store'})).ok)throw Error();
    }catch{
      location.replace('/private/enter');
    }
  }
  window.addEventListener('pageshow',refresh);
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  setInterval(refresh,15000);
})();
