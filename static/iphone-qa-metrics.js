(() => {
  const send = window.fetch.bind(window);
  const loadId = crypto.randomUUID();
  const device = /iPhone/.test(navigator.userAgent) ? 'iPhone' : 'other';
  const log = row => {
    const body = JSON.stringify({loadId,device,width:innerWidth,height:innerHeight,...row});
    void send('/qa/metrics',{method:'POST',headers:{'Content-Type':'application/json'},body,keepalive:true}).catch(()=>{});
  };
  const memory = name => {
    const bytes=performance.memory?.usedJSHeapSize;
    log({kind:'memory',name,supported:Number.isFinite(bytes),heapBytes:bytes});
  };
  window.fetch = async (input, options) => {
    const url = new URL(typeof input==='string'?input:input.url,location.href);
    const match = url.pathname.match(/\/pixel\/(open|extract|save)$/);
    if (!match || url.origin!==location.origin) return send(input,options);
    const form = options?.body;
    const uploadBytes = form instanceof FormData
      ? [...form.values()].reduce((sum,v)=>sum+(typeof v==='string'?new TextEncoder().encode(v).length:v.size),0)
      : typeof form==='string'?new TextEncoder().encode(form).length:0;
    const start = performance.now();
    const response = await send(input,options);
    const ms = performance.now()-start;
    const serverMs = Number(response.headers.get('Server-Timing')?.split('dur=')[1]);
    log({kind:'fetch',name:match[1],ms,serverMs,status:response.status,uploadBytes,
         uploadEstimateMs:Number.isFinite(serverMs)?Math.max(0,ms-serverMs):null});
    memory(match[1]);
    return response;
  };
  const ready = setInterval(() => {
    if (!document.querySelector('#pixel-status')?.textContent.includes('正在編輯 V')) return;
    clearInterval(ready);
    log({kind:'ready',name:'navigation-to-editor',ms:performance.now()});
    memory('ready');
  },100);
  setTimeout(()=>clearInterval(ready),60000);
  let gesture;
  function watch(now){
    if(!gesture)return;
    gesture.max=Math.max(gesture.max,now-gesture.frame);
    gesture.frame=now;
    requestAnimationFrame(watch);
  }
  window.addEventListener('touchstart',e=>{
    if(gesture||!e.target.closest('.upper-canvas'))return;
    const now=performance.now();
    gesture={start:now,frame:now,max:0}; requestAnimationFrame(watch);
  },{passive:true,capture:true});
  for(const name of ['touchend','touchcancel'])window.addEventListener(name,e=>{
    if(!gesture||e.touches.length)return;
    log({kind:'gesture',name,ms:performance.now()-gesture.start,frameGapMs:gesture.max});
    gesture=null;
  },{passive:true,capture:true});
  window.addEventListener('pagehide',()=>log({kind:'pagehide',ms:performance.now()}));
})();
