/* 本福丸後台模板：AI 大頭摳圖。沿用現有 AI 摳圖，再以裝置端臉部 AI 製作大頭素材。 */
(function(){
  'use strict';
  if(window.__bfAdminAiHeadCutout)return;window.__bfAdminAiHeadCutout=true;
  const by=id=>document.getElementById(id),cv=()=>window.visualCanvas||null,active=()=>cv()?.getActiveObject?.()||null;
  let busy=false;
  const isImage=o=>!!(o&&o.type==='image'&&!o.isTplBg&&!o.isSlot);
  const status=s=>{const e=by('bf-tpl-status');if(e)e.textContent=s};

  function css(){
    if(by('bf-admin-ai-head-css'))return;
    const s=document.createElement('style');s.id='bf-admin-ai-head-css';s.textContent=`
      #bf-tpl-objectbar .bf-head-btn{display:none}#bf-tpl-objectbar.has-image .bf-head-btn{display:inline-block}
      #bf-tpl-ai-head-main[disabled],#bf-tpl-objectbar .bf-head-btn[disabled]{opacity:.45}
    `;document.head.appendChild(s);
  }

  function ensureUi(){
    css();
    const top=by('bf-tpl-frontbar');
    if(top&&!by('bf-tpl-ai-head-main')){
      const b=document.createElement('button');b.id='bf-tpl-ai-head-main';b.className='bf-tpl-main-tool';b.innerHTML='<span class="ico"><i class="fa-solid fa-user-large"></i></span>AI 大頭';b.onclick=e=>{e.preventDefault();run()};top.appendChild(b);
    }
    const bar=by('bf-tpl-objectbar');
    if(bar&&!bar.querySelector('.bf-head-btn')){
      const b=document.createElement('button');b.className='bf-head-btn';b.textContent='AI 大頭';b.onclick=e=>{e.preventDefault();e.stopPropagation();run()};
      const danger=bar.querySelector('.danger');if(danger)bar.insertBefore(b,danger);else bar.appendChild(b);
    }
    refresh();
  }

  function refresh(){
    const o=active(),ok=isImage(o);
    const top=by('bf-tpl-ai-head-main');if(top){top.disabled=busy||!ok;top.title=o?.aiHeadCutout?'這張已做過 AI 大頭':'AI 大頭摳圖'}
    document.querySelectorAll('#bf-tpl-objectbar .bf-head-btn').forEach(b=>{b.disabled=busy||!ok;b.title=o?.aiHeadCutout?'這張已做過 AI 大頭':'AI 大頭摳圖'});
  }

  function load(src){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(new Error('大頭圖片載入失敗'));im.src=src})}

  async function replace(old,cut){
    const c=cv();if(!c)throw new Error('模板畫布尚未載入');
    const blob=await window.BenfuwanHeadCutout.canvasBlob(cut.canvas),publicSrc=await uploadAdminImage(new File([blob],'ai-head-cutout.png',{type:'image/png'}),'template');
    const local=URL.createObjectURL(blob);let el;try{el=await load(local)}finally{URL.revokeObjectURL(local)}
    const idx=c.getObjects().indexOf(old),center=old.getCenterPoint(),displayW=Math.max(1,old.getScaledWidth?.()||((old.width||1)*(old.scaleX||1)));
    const neo=new fabric.Image(el,{left:center.x,top:center.y,originX:'center',originY:'center',angle:old.angle||0,flipX:!!old.flipX,flipY:!!old.flipY,opacity:old.opacity??1,objectCaching:true,centeredScaling:true,centeredRotation:true});
    const scale=displayW/Math.max(1,neo.width);neo.set({scaleX:scale,scaleY:scale,publicSrc,originalName:old.originalName||'AI大頭',stickerId:old.stickerId||'',role:old.role,aiBackgroundRemoved:true,aiHeadCutout:true,aiHeadMode:cut.mode,transparentCorners:false,cornerColor:'#ff6f9a',cornerStrokeColor:'#ffffff',borderColor:'#ff6f9a',cornerSize:13,touchCornerSize:28,padding:2});
    c.remove(old);c.insertAt(neo,Math.max(0,idx),false);c.setActiveObject(neo);neo.setCoords();c.requestRenderAll();c.fire('object:modified',{target:neo});return neo;
  }

  async function run(){
    if(busy)return;let old=active();if(!isImage(old))return alert('請先選取一張圖片');
    if(old.aiHeadCutout)return alert('這張圖片已經做過 AI 大頭摳圖');
    const core=window.BenfuwanHeadCutout;if(!core)return alert('AI 大頭工具尚未載入');
    busy=true;refresh();let face=null;
    try{
      status('AI 正在辨識主要臉部…');
      try{face=await core.detectFace(old.getElement?.()||old._element)}catch(e){console.warn('[ADMIN AI HEAD] face detect fallback',e)}
      if(!old.aiBackgroundRemoved){
        if(typeof window.bfAdminRemoveBackground!=='function')throw new Error('AI 摳圖功能尚未載入');
        await window.bfAdminRemoveBackground();old=active();
        if(!isImage(old)||!old.aiBackgroundRemoved)throw new Error('AI 摳圖未完成，請再試一次');
      }
      status(face?'正在保留頭髮與臉部輪廓…':'找不到正臉，改用透明輪廓智慧裁切…');
      const cut=core.cropTransparent(old.getElement?.()||old._element,face);await replace(old,cut);
      status(face?.count>1?'AI 大頭完成 ✓（多人照片已取最主要臉部）':face?'AI 大頭摳圖完成 ✓':'AI 大頭完成 ✓（輪廓智慧裁切）');
    }catch(e){console.error('[ADMIN AI HEAD]',e);alert(e.message||'AI 大頭摳圖失敗');status('AI 大頭摳圖失敗，請再試一次')}
    finally{busy=false;refresh()}
  }

  window.bfAdminHeadCutout=run;
  function boot(){ensureUi();let last=null;setInterval(()=>{ensureUi();const c=cv();if(c&&c!==last){last=c;['selection:created','selection:updated','selection:cleared','object:added','object:removed','object:modified'].forEach(evt=>c.on(evt,()=>setTimeout(refresh,0))) }refresh()},600);console.info('[ADMIN] AI head cutout enabled')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
