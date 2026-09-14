/* 本福丸後台模板 AI v5：與前台共用 API；修復 AI 去背並加入真正生成式 AI 擴圖。 */
(function(){
  'use strict';
  if(window.__benfuwanTemplateAiV5Installed)return;
  window.__benfuwanTemplateAiV5Installed=true;
  const by=id=>document.getElementById(id),canvas=()=>window.visualCanvas||null;
  const isImage=o=>!!o&&o.type==='image'&&!o.isTplBg&&!o.isSlot;
  let busy=false,dir='all';

  function status(s){const e=by('bf-tpl-status');if(e)e.textContent=s}
  function css(){if(by('bf-tpl-ai-v5-css'))return;const s=document.createElement('style');s.id='bf-tpl-ai-v5-css';s.textContent=`
    #bf-tpl-ai-v5-panel{display:none;margin-top:8px;padding:11px;border:1px solid #efdfe5;background:#fff;border-radius:14px}#bf-tpl-ai-v5-panel.show{display:block}.bf-aiv5-head{display:flex;justify-content:space-between;align-items:center;color:#d95580;font-size:12px;font-weight:900;margin-bottom:9px}.bf-aiv5-head button{border:1px solid #efd3dc;background:#fff;color:#d95580;border-radius:999px;padding:5px 9px}.bf-aiv5-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:7px}.bf-aiv5-grid button{border:1px solid #efdfe5;background:#fff;border-radius:11px;padding:8px 3px;font-size:10px;font-weight:900;color:#655b60}.bf-aiv5-grid button.active{background:#fff0f5;border-color:#ff6f9a;color:#f54f84}.bf-aiv5-row{display:flex;align-items:center;gap:8px;margin-top:9px}.bf-aiv5-row label{font-size:10px;font-weight:900;width:58px}.bf-aiv5-row select,.bf-aiv5-row input{flex:1;border:1px solid #eadde2;border-radius:10px;padding:8px;background:#fff}.bf-aiv5-run{margin-top:10px;width:100%;border:0;border-radius:999px;padding:10px;background:#ff6f9a;color:#fff;font-weight:900}.bf-aiv5-note{font-size:10px;color:#8e8288;line-height:1.55;margin-top:8px}@media(max-width:700px){.bf-aiv5-grid{grid-template-columns:repeat(3,1fr)}}
  `;document.head.appendChild(s)}

  function ensureUi(){
    css();const tools=by('bf-tpl-tools');if(!tools)return;
    if(!by('bf-tpl-ai-v5-panel')){
      const p=document.createElement('div');p.id='bf-tpl-ai-v5-panel';p.innerHTML=`<div class="bf-aiv5-head"><span>AI 擴圖</span><button type="button" data-close>收起</button></div><div class="bf-aiv5-grid"><button type="button" class="active" data-dir="all">四周</button><button type="button" data-dir="left">左邊</button><button type="button" data-dir="right">右邊</button><button type="button" data-dir="top">上方</button><button type="button" data-dir="bottom">下方</button></div><div class="bf-aiv5-row"><label>擴張大小</label><select id="bf-aiv5-ratio"><option value="1.2">120%</option><option value="1.4" selected>140%</option><option value="1.6">160%</option></select></div><div class="bf-aiv5-row"><label>效果提示</label><input id="bf-aiv5-prompt" maxlength="180" placeholder="可留空"></div><button id="bf-aiv5-run" class="bf-aiv5-run">開始 AI 擴圖</button><div class="bf-aiv5-note">真正生成式擴圖：原圖主體保留，只生成外圍新區域。第一次使用若 Runpod 冷啟動會稍久。</div>`;tools.appendChild(p);p.querySelector('[data-close]').onclick=()=>p.classList.remove('show');p.querySelectorAll('[data-dir]').forEach(b=>b.onclick=()=>{dir=b.dataset.dir;p.querySelectorAll('[data-dir]').forEach(x=>x.classList.toggle('active',x===b))});by('bf-aiv5-run').onclick=runExpand;
    }
    // Rename old smart-expand controls so there is only one meaning in the UI.
    const top=by('bf-tpl-expand-v4');if(top){top.innerHTML='<span class="ico"><i class="fa-solid fa-expand"></i></span>AI 擴圖'}
    document.querySelectorAll('#bf-tpl-objectbar .bf-expand-btn').forEach(b=>b.textContent='AI 擴圖');
    const oldPanel=by('bf-tpl-ai-panel-v4');if(oldPanel)oldPanel.style.display='none';
  }

  function imgBlob(o,maxEdge=1700){return new Promise(async(resolve,reject)=>{try{const el=o.getElement?.()||o._element;if(!el)throw new Error('圖片讀取失敗');const iw=el.naturalWidth||el.width,ih=el.naturalHeight||el.height,r=Math.min(1,maxEdge/Math.max(iw,ih)),w=Math.max(1,Math.round(iw*r)),h=Math.max(1,Math.round(ih*r)),c=document.createElement('canvas');c.width=w;c.height=h;c.getContext('2d').drawImage(el,0,0,w,h);let q=.92,b=await new Promise((res,rej)=>c.toBlob(x=>x?res(x):rej(new Error('圖片處理失敗')),'image/webp',q));while(b.size>7.5*1024*1024&&q>.64){q-=.07;b=await new Promise((res,rej)=>c.toBlob(x=>x?res(x):rej(new Error('圖片處理失敗')),'image/webp',q))}c.width=c.height=1;resolve(b)}catch(e){reject(e)}})}
  function blobData(blob){return new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(String(r.result||''));r.onerror=()=>rej(new Error('圖片讀取失敗'));r.readAsDataURL(blob)})}

  async function replace(oldObj,blob,publicUrl,meta={}){
    const c=canvas();if(!c||!oldObj)throw new Error('模板畫布尚未準備好');const src=await blobData(blob),center=oldObj.getCenterPoint(),idx=c.getObjects().indexOf(oldObj),dw=oldObj.getScaledWidth(),dh=oldObj.getScaledHeight();return new Promise((resolve,reject)=>fabric.Image.fromURL(src,img=>{try{const fit=Math.min(dw/Math.max(1,img.width),dh/Math.max(1,img.height));img.set({left:center.x,top:center.y,originX:'center',originY:'center',scaleX:fit,scaleY:fit,angle:oldObj.angle||0,flipX:!!oldObj.flipX,flipY:!!oldObj.flipY,opacity:oldObj.opacity??1,objectCaching:true,centeredScaling:true});img.publicSrc=publicUrl;img.originalName=oldObj.originalName||'AI圖片';img.stickerId=oldObj.stickerId||'';img.role=oldObj.role;img.aiBackgroundRemoved=!!meta.removed;img.aiExpanded=!!meta.expanded;img.aiOutlineStyle='none';img.aiOutlineWidth=undefined;img.aiOutlineColor=undefined;img.aiOutlineSourcePublic=undefined;c.remove(oldObj);c.insertAt(img,Math.max(0,idx),false);c.setActiveObject(img);img.setCoords();c.requestRenderAll();c.fire('object:modified',{target:img});resolve(img)}catch(e){reject(e)}},{crossOrigin:'anonymous'}))}

  async function call(path,oldObj,fields){const input=await imgBlob(oldObj),fd=new FormData();fd.append('image',input,'ai.webp');Object.entries(fields||{}).forEach(([k,v])=>fd.append(k,String(v)));const r=await fetch(path,{method:'POST',body:fd,cache:'no-store'});if(!r.ok){let msg='AI 處理失敗';try{const j=await r.json();msg=j.msg||msg}catch(e){}throw new Error(msg)}const out=await r.blob();if(!out.size)throw new Error('AI 沒有回傳圖片');const file=new File([out],path.includes('outpaint')?'ai-expand.png':'ai-cutout.png',{type:'image/png'}),url=await uploadAdminImage(file,'template');return {out,url}}

  async function runRemove(){if(busy)return;const old=canvas()?.getActiveObject();if(!isImage(old))return alert('請先點選一張圖片');busy=true;status('AI 正在摳圖…');try{const {out,url}=await call('/api/ai/remove-background',old,{});await replace(old,out,url,{removed:true});status('AI 摳圖完成 ✓')}catch(e){console.error('[ADMIN AI REMOVE]',e);alert(e.message||'AI 摳圖失敗')}finally{busy=false}}
  function openExpand(){ensureUi();if(!isImage(canvas()?.getActiveObject()))return alert('請先點選一張圖片');by('bf-tpl-ai-v5-panel')?.classList.add('show')}
  async function runExpand(){if(busy)return;const old=canvas()?.getActiveObject();if(!isImage(old))return alert('請先點選一張圖片');busy=true;const run=by('bf-aiv5-run');if(run){run.disabled=true;run.textContent='AI 生成中…'}status('AI 正在擴圖…');try{const {out,url}=await call('/api/ai/outpaint',old,{direction:dir,expand_ratio:by('bf-aiv5-ratio')?.value||1.4,prompt:by('bf-aiv5-prompt')?.value.trim()||''});await replace(old,out,url,{expanded:true});by('bf-tpl-ai-v5-panel')?.classList.remove('show');status('AI 擴圖完成 ✓')}catch(e){console.error('[ADMIN AI EXPAND]',e);alert(e.message||'AI 擴圖失敗')}finally{busy=false;if(run){run.disabled=false;run.textContent='開始 AI 擴圖'}}}

  // Capture at document level so broken/old v4 handlers never get the click first.
  document.addEventListener('click',ev=>{
    const t=ev.target.closest?.('#bf-tpl-ai-v4,#bf-tpl-objectbar .bf-ai-btn,#bf-tpl-expand-v4,#bf-tpl-objectbar .bf-expand-btn');if(!t)return;ev.preventDefault();ev.stopPropagation();ev.stopImmediatePropagation();if(t.matches('#bf-tpl-ai-v4,#bf-tpl-objectbar .bf-ai-btn'))runRemove();else openExpand();
  },true);

  function boot(){ensureUi();setInterval(ensureUi,1500);console.info('[ADMIN] template AI v5 enabled: shared remove + generative outpaint')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
