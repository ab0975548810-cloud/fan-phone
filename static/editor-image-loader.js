/* Preserve original image bytes before insertion: drafts never need a cross-origin fetch. */
(function(){
  'use strict';
  const messages={network:'貼紙下載失敗，請確認網路連線後再點選一次。',timeout:'貼紙載入逾時，請稍後再試。',http:'貼紙素材暫時無法使用，請換一張或通知店員。',decode:'貼紙圖片無法解碼，請換一張或通知店員。',size:'貼紙圖片過大，請換一張或通知店員。',cancel:'設計已切換，已取消加入貼紙。'};
  const fail=(code)=>Object.assign(new Error(messages[code]),{imageLoadCode:code});
  function source(url){
    const u=new URL(String(url||''),location.href);
    if(!url||!['https:','http:','data:','blob:'].includes(u.protocol))throw fail('http');
    if(u.protocol==='data:'&&!/^data:image\//i.test(url))throw fail('decode');
    return ['data:','blob:'].includes(u.protocol)||u.origin===location.origin?u.href:'/api/public/asset_proxy?url='+encodeURIComponent(u.href);
  }
  async function read(url){
    const src=source(url);
    // fetch(data:) is also blocked by connect-src 'self'; decode locally.
    if(src.startsWith('data:')){
      const match=src.match(/^data:image\/(?:png|jpeg|webp);base64,([a-z0-9+/=\s]+)$/i);
      if(!match)throw fail('decode');
      if(match[1].length>25*1024*1024)throw fail('size');
      let length;try{length=atob(match[1]).length;}catch(_){throw fail('decode');}
      if(!length)throw fail('decode');if(length>18*1024*1024)throw fail('size');return src;
    }
    for(let attempt=0;attempt<2;attempt++){
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
      try{
        const response=await fetch(src,{signal:controller.signal,credentials:'same-origin'});
        if(!response.ok){const error=fail('http');error.retry=response.status===429||response.status>=500;error.status=response.status;throw error;}
        if(Number(response.headers.get('content-length'))>18*1024*1024)throw fail('size');
        const blob=await response.blob();
        if(!blob.size||!/^image\/(png|jpeg|webp)$/i.test(blob.type))throw fail('decode');
        if(blob.size>18*1024*1024)throw fail('size');
        return await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(fail('decode'));reader.readAsDataURL(blob);});
      }catch(error){
        const wrapped=error.imageLoadCode?error:fail(controller.signal.aborted?'timeout':'network');
        console.warn('[EDITOR IMAGE]',{stage:'download',attempt:attempt+1,status:error.status||0,code:wrapped.imageLoadCode});
        if(attempt||error.imageLoadCode&&!error.retry)throw wrapped;
      }finally{clearTimeout(timer);}
      await new Promise(resolve=>setTimeout(resolve,250));
    }
  }
  async function image(url){
    const data=await read(url);
    return new Promise((resolve,reject)=>{
      let done=false;const timer=setTimeout(()=>{done=true;reject(fail('timeout'));},5000);
      fabric.Image.fromURL(data,(img,error)=>{
        if(done)return;done=true;clearTimeout(timer);
        if(error||!img?.width||!img?.height){reject(fail('decode'));return;}
        if(img.width>8192||img.height>8192||img.width*img.height>32000000){reject(fail('size'));return;}
        resolve(img);
      });
    });
  }
  let pending=null;
  async function insert(key,button,create){
    // One bounded insertion at a time prevents double taps and preserves order.
    if(pending){toast('貼紙載入中，請稍候。');return false;}
    const c=canvas,model=ctx.modelId,style=ctx.styleId;
    const editorActive=()=>document.getElementById('page-editor')?.classList.contains('active');
    if(!c||!editorActive())return false;
    const task={cancelled:false};pending=task;
    const cancelled=()=>task.cancelled=true;c.on('canvas:cleared',cancelled);
    const valid=()=>!task.cancelled&&canvas===c&&ctx.modelId===model&&ctx.styleId===style&&editorActive();
    const status=document.getElementById('sticker-load-status')||document.createElement('p');
    status.id='sticker-load-status';status.setAttribute('role','status');status.setAttribute('aria-live','polite');status.textContent='貼紙載入中…';
    if(!status.isConnected)document.querySelector('#sheet-sticker .sheet-body')?.prepend(status);
    if(button){button.disabled=true;button.setAttribute('aria-busy','true');}
    let deadline;
    try{
      await Promise.race([create(c,valid),new Promise((_,reject)=>{deadline=setTimeout(()=>{task.cancelled=true;reject(fail('timeout'));},23000);})]);
      status.textContent='貼紙已加入';recordHistory();renderLayerList();closeSheets();return true;
    }catch(error){
      const message=error.imageLoadCode?error.message:messages.network;
      console.warn('[STICKER INSERT]',{code:error.imageLoadCode||'other',message:error.message});
      status.textContent=message;if(canvas===c&&editorActive())toast(message);return false;
    }finally{
      clearTimeout(deadline);c.off('canvas:cleared',cancelled);pending=null;
      if(button){button.disabled=false;button.removeAttribute('aria-busy');}
    }
  }
  window.BenfuwanEditorImage={read,image,insert,fail};
})();
