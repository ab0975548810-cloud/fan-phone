/* Loaded only by the isolated order editor. Drafts stay in the private volume. */
(() => {
  const banner=document.createElement('aside');
  banner.id='private-reedit-status';
  banner.setAttribute('role','status');
  banner.style.cssText='position:relative;z-index:10;background:#fff1c2;color:#462f00;padding:6px;text-align:center';
  banner.textContent='重新編輯（測試）· 私有工作副本 · 僅使用假設備';
  document.body.prepend(banner);
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
