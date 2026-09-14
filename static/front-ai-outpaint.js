/* 本福丸前台：真正生成式 AI 擴圖。與 AI 去背共用 Runpod，選取照片後可向四周延伸。 */
(function(){
  'use strict';
  if(window.__benfuwanFrontAiOutpaintInstalled)return;
  window.__benfuwanFrontAiOutpaintInstalled=true;

  const by=id=>document.getElementById(id);
  const active=()=>{try{return canvas?.getActiveObject?.()||null}catch(e){return null}};
  const isPhoto=o=>!!o&&o.type==='image'&&!o.isTplBg&&(!o.role||['photo','slot-photo','image'].includes(o.role));
  let busy=false;

  function css(){if(by('bf-ai-expand-css'))return;const s=document.createElement('style');s.id='bf-ai-expand-css';s.textContent=`
    #bf-ai-expand-btn{display:none}#bf-ai-expand-btn.show{display:block}
    .bf-expand-box{display:flex;flex-direction:column;gap:12px}.bf-expand-tip{font-size:11px;line-height:1.6;color:#8c7d84}.bf-expand-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.bf-expand-choice{border:1px solid var(--line);background:#fff;border-radius:13px;padding:11px 5px;font-size:11px;font-weight:900;color:#665b60}.bf-expand-choice.active{background:var(--pink-soft);border-color:var(--pink);color:var(--pink-dark)}.bf-expand-row{display:flex;align-items:center;gap:10px}.bf-expand-row label{font-size:11px;font-weight:900;width:64px}.bf-expand-row select,.bf-expand-row input{flex:1;border:1px solid var(--line);border-radius:12px;padding:9px;background:#fff}.bf-expand-run{width:100%;border:0;background:linear-gradient(135deg,var(--pink),var(--pink-dark));color:#fff;border-radius:999px;padding:12px;font-weight:900}.bf-expand-run:disabled{opacity:.5}.bf-expand-note{font-size:10px;color:#998b91;line-height:1.5}
  `;document.head.appendChild(s)}

  function ensureUi(){
    css();const bar=by('object-bar'),app=by('app');if(!bar||!app)return;
    if(!by('bf-ai-expand-btn')){
      const b=document.createElement('button');b.id='bf-ai-expand-btn';b.type='button';b.innerHTML='<i class="fa-solid fa-expand"></i>AI擴圖';b.onclick=()=>window.openAiExpandSheet?.();
      const outline=by('bf-ai-outline-btn'),del=[...bar.querySelectorAll('button')].find(x=>/deleteActive/.test(x.getAttribute('onclick')||''));
      if(outline?.nextSibling)bar.insertBefore(b,outline.nextSibling);else if(del)bar.insertBefore(b,del);else bar.appendChild(b);
    }
    if(!by('sheet-ai-expand')){
      const sh=document.createElement('div');sh.className='sheet';sh.id='sheet-ai-expand';sh.innerHTML=`<div class="sheet-header"><span>AI 擴圖</span><button class="sheet-close" onclick="closeSheets()"><i class="fa-solid fa-xmark"></i></button></div><div class="sheet-body"><div class="bf-expand-box"><div class="bf-expand-tip">照片不夠寬、人物太滿時，用 AI 自動延伸原本背景。原圖主體會保留，AI 只生成外圍的新區域。</div><div class="bf-expand-grid"><button class="bf-expand-choice active" data-dir="all">四周</button><button class="bf-expand-choice" data-dir="left">左邊</button><button class="bf-expand-choice" data-dir="right">右邊</button><button class="bf-expand-choice" data-dir="top">上方</button><button class="bf-expand-choice" data-dir="bottom">下方</button></div><div class="bf-expand-row"><label>擴張大小</label><select id="bf-expand-ratio"><option value="1.2">小・120%</option><option value="1.4" selected>中・140%</option><option value="1.6">大・160%</option></select></div><div class="bf-expand-row"><label>想要效果</label><input id="bf-expand-prompt" maxlength="180" placeholder="可留空，例：延伸天空與草地"></div><button id="bf-expand-run" class="bf-expand-run">開始 AI 擴圖</button><div class="bf-expand-note">第一次使用可能因 AI 冷啟動需要較久；完成後仍可拖曳、縮放、裁切與再去背。</div></div></div>`;app.appendChild(sh);
      sh.querySelectorAll('[data-dir]').forEach(b=>b.onclick=()=>{sh.querySelectorAll('[data-dir]').forEach(x=>x.classList.remove('active'));b.classList.add('active')});
      by('bf-expand-run').onclick=run;
    }
    sync();
  }

  function sync(){const b=by('bf-ai-expand-btn');if(b)b.classList.toggle('show',isPhoto(active()))}
  window.openAiExpandSheet=function(){ensureUi();if(!isPhoto(active())){toast?.('請先選取一張照片');return}if(typeof openSheet==='function')openSheet('sheet-ai-expand')};

  function toBlob(c,type='image/webp',q=.9){return new Promise((res,rej)=>c.toBlob(b=>b?res(b):rej(new Error('圖片處理失敗')),type,q))}
  async function objectBlob(o,maxEdge=1600){
    const el=o.getElement?.()||o._element;if(!el)throw new Error('讀不到圖片');const iw=el.naturalWidth||el.width,ih=el.naturalHeight||el.height;if(!iw||!ih)throw new Error('圖片尺寸錯誤');const r=Math.min(1,maxEdge/Math.max(iw,ih)),w=Math.max(1,Math.round(iw*r)),h=Math.max(1,Math.round(ih*r)),c=document.createElement('canvas');c.width=w;c.height=h;const g=c.getContext('2d');g.drawImage(el,0,0,w,h);let q=.92,b=await toBlob(c,'image/webp',q);while(b.size>7.5*1024*1024&&q>.65){q-=.07;b=await toBlob(c,'image/webp',q)}c.width=c.height=1;return b;
  }
  function blobUrl(blob){return new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(String(r.result||''));r.onerror=()=>rej(new Error('AI 圖片讀取失敗'));r.readAsDataURL(blob)})}

  async function replace(oldObj,blob){
    const src=await blobUrl(blob),center=oldObj.getCenterPoint(),idx=canvas.getObjects().indexOf(oldObj),displayW=oldObj.getScaledWidth(),displayH=oldObj.getScaledHeight();
    return new Promise((resolve,reject)=>fabric.Image.fromURL(src,img=>{try{
      const fit=Math.min(displayW/Math.max(1,img.width),displayH/Math.max(1,img.height));
      img.set({left:center.x,top:center.y,originX:'center',originY:'center',scaleX:fit,scaleY:fit,angle:oldObj.angle||0,flipX:!!oldObj.flipX,flipY:!!oldObj.flipY,opacity:oldObj.opacity??1,role:oldObj.role||'photo',slotId:oldObj.slotId,slotMeta:oldObj.slotMeta,originalName:oldObj.originalName||'AI擴圖',materialType:oldObj.materialType,clipPath:oldObj.clipPath||undefined,aiExpanded:true,aiBackgroundRemoved:false});
      if(typeof styleEditableObject==='function')styleEditableObject(img);canvas.remove(oldObj);canvas.insertAt(img,Math.max(0,idx),false);canvas.setActiveObject(img);img.setCoords();canvas.requestRenderAll();recordHistory?.();renderLayerList?.();sync();resolve(img);
    }catch(e){reject(e)}},{crossOrigin:'anonymous'}));
  }

  async function run(){if(busy)return;const old=active();if(!isPhoto(old))return toast?.('請先選取一張照片');busy=true;const btn=by('bf-expand-run'),dir=by('sheet-ai-expand')?.querySelector('[data-dir].active')?.dataset.dir||'all',ratio=by('bf-expand-ratio')?.value||'1.4',prompt=by('bf-expand-prompt')?.value.trim()||'';if(btn){btn.disabled=true;btn.textContent='AI 正在延伸照片…'}setBusy?.(true,'AI 正在擴圖，請稍候...');try{
      const blob=await objectBlob(old),fd=new FormData();fd.append('image',blob,'expand.webp');fd.append('direction',dir);fd.append('expand_ratio',ratio);fd.append('prompt',prompt);
      const r=await fetch('/api/ai/outpaint',{method:'POST',body:fd,cache:'no-store'});if(!r.ok){let msg='AI 擴圖失敗';try{const j=await r.json();msg=j.msg||msg}catch(e){}throw new Error(msg)}const out=await r.blob();if(!out.size)throw new Error('AI 沒有回傳圖片');await replace(old,out);closeSheets?.();toast?.('AI 擴圖完成 ♡');
    }catch(e){console.error('[AI OUTPAINT]',e);toast?.(e.message||'AI 擴圖目前無法使用')}finally{busy=false;setBusy?.(false);if(btn){btn.disabled=false;btn.textContent='開始 AI 擴圖'}}}

  function hook(){ensureUi();const c=typeof canvas!=='undefined'?canvas:null;if(!c||c.__bfExpandHooked)return;c.__bfExpandHooked=true;['selection:created','selection:updated','selection:cleared','object:added','object:removed'].forEach(ev=>c.on(ev,()=>setTimeout(sync,0)))}
  function boot(){ensureUi();hook();setInterval(hook,1200);console.info('[FRONT] generative AI outpaint enabled')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
