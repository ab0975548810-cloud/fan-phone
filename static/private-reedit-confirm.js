(async()=>{
  const [snapshot,challenge]=location.hash.slice(1).split('.');
  history.replaceState(null,'',location.pathname);
  try{
    const r=await fetch('/api/admin/reedit-test/confirm',{method:'POST',
      headers:{'Content-Type':'application/json','X-Reedit-Test':'1'},body:JSON.stringify({snapshot,challenge})});
    if(!r.ok)throw Error();
    location.replace((await r.json()).location);
  }catch{
    document.querySelector('[role=status]').textContent='此交接與本次 Passkey 不符或已過期。請返回訂單列表重新開啟。';
  }
})();
