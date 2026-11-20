(async () => {
  const fragment=location.hash.slice(1);
  const parts=fragment.split('.');
  const returning=location.pathname==='/private/return';
  history.replaceState(null, '', location.pathname);
  try {
    const r = await fetch(returning?'/private/redeem':'/private/bind', {method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(returning?{proof:fragment}:{snapshot:parts[0],code:parts[1]})});
    if (!r.ok) throw Error();
    location.replace((await r.json()).location);
  } catch {
    document.querySelector('[role=status]').textContent='交接已失效。請返回正式後台，以獲准的 Passkey 重新開啟。';
  }
})();
