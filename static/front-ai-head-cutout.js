/* 本福丸前台：AI 大頭互動摳圖。使用者先用筆刷指定頭部，直接以 MagicTouch mask 產生透明大頭素材。 */
(function(){
  'use strict';
  if(window.__bfFrontAiHeadCutout)return;window.__bfFrontAiHeadCutout=true;

  const by=id=>document.getElementById(id);
  let hookedCanvas=null,busy=false;
  function c(){try{return (typeof canvas!=='undefined'&&canvas)?canvas:null}catch(e){return null}}
  function active(){return c()?.getActiveObject?.()||null}
  function isPhoto(o){return !!(o&&o.type==='image'&&(o.role==='photo'||o.role==='slot-photo'))}

  function addCss(){
    if(by('bf-ai-head-front-css'))return;
    const s=document.createElement('style');s.id='bf-ai-head-front-css';s.textContent=`
      #bf-ai-head-btn{display:none}#bf-ai-head-btn.show{display:block}
      #bf-ai-head-btn i{color:#ff6f9a}
      #bf-ai-head-sheet-wrap{margin-top:10px;padding-top:10px;border-top:1px dashed rgba(161,87,195,.28)}
      #bf-ai-head-sheet-wrap .bf-ai-head-note{font-size:10px;color:#806e77;line-height:1.55;margin:5px 1px 1px}
      #bf-ai-head-sheet-btn{background:linear-gradient(135deg,#fff,#fff6fb);border-color:#e9b5f2;color:#9a48ba}
      #bf-ai-head-sheet-btn i{margin-right:6px}
      #bf-ai-head-guide{position:fixed;inset:0;z-index:999999;background:rgba(35,28,32,.72);display:flex;align-items:flex-end;justify-content:center;padding:0;box-sizing:border-box}
      #bf-ai-head-guide .panel{width:min(680px,100%);max-height:94vh;background:#fff;border-radius:22px 22px 0 0;box-shadow:0 -12px 40px rgba(0,0,0,.18);display:flex;flex-direction:column;overflow:hidden;padding-bottom:env(safe-area-inset-bottom)}
      #bf-ai-head-guide .head{padding:13px 16px 9px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #f4e9ee}
      #bf-ai-head-guide .head b{font-size:16px;color:#54484e}#bf-ai-head-guide .head button{border:0;background:#f7f2f4;border-radius:999px;padding:8px 12px;color:#6f6268;font-weight:700}
      #bf-ai-head-guide .hint{padding:9px 16px 8px;font-size:12px;line-height:1.55;color:#75666e;background:#fff9fb}
      #bf-ai-head-guide .stage-wrap{padding:8px 12px;display:flex;justify-content:center;overflow:auto;background:#f6f3f5;min-height:160px}
      #bf-ai-head-guide .stage{position:relative;display:inline-block;line-height:0;box-shadow:0 5px 20px rgba(0,0,0,.10);border-radius:12px;overflow:hidden;background:#fff}
      #bf-ai-head-guide canvas{display:block}#bf-ai-head-guide .mask,#bf-ai-head-guide .paint{position:absolute;inset:0;width:100%;height:100%}
      #bf-ai-head-guide .paint{touch-action:none;cursor:crosshair}
      #bf-ai-head-guide .tools{padding:9px 12px 5px;display:flex;gap:7px;flex-wrap:wrap;background:#fff}
      #bf-ai-head-guide .tools button{flex:1;min-width:78px;border:1px solid #eadfe4;background:#fff;border-radius:12px;padding:10px 7px;font-weight:800;color:#6e6067}
      #bf-ai-head-guide .tools button.on{border-color:#ff6f9a;background:#fff0f5;color:#d94c7b}#bf-ai-head-guide .tools button.neg.on{border-color:#ef6a6a;background:#fff1f1;color:#cf4545}
      #bf-ai-head-guide .status{min-height:20px;padding:2px 15px 7px;font-size:11px;line-height:1.45;color:#8a747e;text-align:center}
      #bf-ai-head-guide .actions{display:flex;gap:8px;padding:7px 12px 12px;background:#fff}
      #bf-ai-head-guide .actions button{border:0;border-radius:14px;padding:12px 10px;font-weight:900;font-size:14px}
      #bf-ai-head-guide .preview{flex:1;background:#fff0f5;color:#d94c7b;border:1px solid #ffc2d7!important}#bf-ai-head-guide .apply{flex:1.2;background:#ff5f93;color:#fff}
      #bf-ai-head-guide .actions button:disabled{opacity:.42}
    `;document.head.appendChild(s);
  }

  function ensureButton(){
    addCss();const bar=by('object-bar');if(!bar)return;
    let b=by('bf-ai-head-btn');
    if(!b){
      b=document.createElement('button');b.id='bf-ai-head-btn';b.type='button';b.title='AI 大頭：用筆刷指定要保留的頭部';b.innerHTML='<i class="fa-solid fa-user-large"></i>AI大頭';b.onclick=e=>{e.preventDefault();e.stopPropagation();run()};
      const outline=by('bf-ai-outline-btn'),del=[...bar.querySelectorAll('button')].find(x=>/deleteActive/.test(x.getAttribute('onclick')||''));
      if(outline)bar.insertBefore(b,outline);else if(del)bar.insertBefore(b,del);else bar.appendChild(b);
    }
    refresh();
  }

  function ensureSheetButton(){
    addCss();const box=document.querySelector('#sheet-upload .ai-box');if(!box||by('bf-ai-head-sheet-wrap'))return;
    const wrap=document.createElement('div');wrap.id='bf-ai-head-sheet-wrap';
    wrap.innerHTML='<b><i class="fa-solid fa-user-large"></i> AI 大頭摳圖 <span style="font-size:9px;padding:2px 6px;border-radius:999px;background:#fff;color:#a157c3">NEW</span></b><div class="bf-ai-head-note">先選取人物照片，再用手指大概塗過頭髮、臉與耳朵。AI 會依你的筆跡抓出要留下的大頭；不需要沿著邊緣慢慢描。</div><button id="bf-ai-head-sheet-btn" class="secondary wide" type="button"><i class="fa-solid fa-user-large"></i>AI 大頭｜塗選頭部</button>';
    box.appendChild(wrap);
    by('bf-ai-head-sheet-btn').onclick=e=>{e.preventDefault();run()};
    refresh();
  }

  function refresh(){
    const o=active(),ok=isPhoto(o),b=by('bf-ai-head-btn'),sheet=by('bf-ai-head-sheet-btn');
    if(b){b.classList.toggle('show',ok);b.disabled=busy||!ok;b.title=o?.aiHeadCutout?'這張已做過 AI 大頭摳圖':'AI 大頭：用筆刷指定要保留的頭部'}
    if(sheet){sheet.disabled=busy;sheet.innerHTML=busy?'<i class="fa-solid fa-spinner fa-spin"></i>AI 大頭處理中…':'<i class="fa-solid fa-user-large"></i>AI 大頭｜塗選頭部';sheet.title=ok?'AI 大頭｜塗選頭部':'請先選取畫布上的照片'}
  }

  function loadImage(src){return new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(new Error('大頭圖片載入失敗'));im.src=src})}
  function dataUrl(ca){return ca.toDataURL('image/png')}

  async function replaceObject(old,cut){
    const cv=c();if(!cv)throw new Error('畫布尚未載入');
    if(!cv.getObjects?.().includes(old))throw new Error('原始圖片狀態已改變，請重新選取照片再試一次');
    if(!cut?.canvas?.width||!cut?.canvas?.height)throw new Error('大頭圖片輸出為空，請重新預覽後再套用');
    const center=old.getCenterPoint(),idx=cv.getObjects().indexOf(old),displayW=Math.max(1,old.getScaledWidth?.()||((old.width||1)*(old.scaleX||1))),src=dataUrl(cut.canvas),el=await loadImage(src);
    const neo=new fabric.Image(el,{left:center.x,top:center.y,originX:'center',originY:'center',angle:old.angle||0,flipX:!!old.flipX,flipY:!!old.flipY,opacity:old.opacity??1,objectCaching:true});
    const scale=displayW/Math.max(1,neo.width);neo.set({scaleX:scale,scaleY:scale,role:old.role,slotId:old.slotId,slotMeta:old.slotMeta,clipPath:old.clipPath||undefined,originalName:old.originalName,materialType:old.materialType,aiBackgroundRemoved:true,aiHeadCutout:true,aiHeadMode:cut.mode,aiOutlineSource:old.aiOutlineSource,aiOutlineStrength:old.aiOutlineStrength,aiOutlineColor:old.aiOutlineColor});
    if(typeof styleEditableObject==='function')styleEditableObject(neo);
    cv.remove(old);cv.insertAt(neo,Math.max(0,idx),false);cv.setActiveObject(neo);neo.setCoords();cv.requestRenderAll?.();
    if(typeof recordHistory==='function')recordHistory();if(typeof renderLayerList==='function')renderLayerList();if(typeof syncSelection==='function')syncSelection();
    return neo;
  }

  function openGuide(el){
    const guide=window.BenfuwanInteractiveHead;if(!guide)return Promise.reject(new Error('AI 塗選工具尚未載入，請重新整理頁面'));
    const source=guide.snapshot(el);addCss();
    return new Promise(resolve=>{
      const oldOverflow=document.body.style.overflow;document.body.style.overflow='hidden';
      const root=document.createElement('div');root.id='bf-ai-head-guide';root.innerHTML=`
        <div class="panel">
          <div class="head"><b>AI 大頭｜塗選頭部</b><button type="button" data-act="cancel">取消</button></div>
          <div class="hint">用 <b style="color:#e65082">粉紅色「保留」</b> 大概塗過頭髮、臉、耳朵即可，不用沿邊描。若 AI 多抓到手或身體，再切到 <b style="color:#d34b4b">紅色「排除」</b> 塗掉它。</div>
          <div class="stage-wrap"><div class="stage"><canvas class="photo"></canvas><canvas class="mask"></canvas><canvas class="paint"></canvas></div></div>
          <div class="tools"><button type="button" data-mode="positive" class="on">✓ 保留</button><button type="button" data-mode="negative" class="neg">✕ 排除</button><button type="button" data-act="clear">清除重畫</button></div>
          <div class="status">先把要留下的「頭部範圍」塗一遍，再按 AI 預覽。</div>
          <div class="actions"><button type="button" class="preview" data-act="preview">AI 預覽</button><button type="button" class="apply" data-act="apply" disabled>套用大頭</button></div>
        </div>`;
      document.body.appendChild(root);
      const photo=root.querySelector('.photo'),mask=root.querySelector('.mask'),paint=root.querySelector('.paint'),stage=root.querySelector('.stage'),status=root.querySelector('.status');
      const previewBtn=root.querySelector('[data-act="preview"]'),applyBtn=root.querySelector('[data-act="apply"]');
      const maxW=Math.max(260,Math.min(620,window.innerWidth-24)),maxH=Math.max(260,Math.min(620,window.innerHeight*.56));
      const scale=Math.min(maxW/source.width,maxH/source.height,1),dw=Math.max(1,Math.round(source.width*scale)),dh=Math.max(1,Math.round(source.height*scale));
      [photo,mask,paint].forEach(x=>{x.width=dw;x.height=dh});stage.style.width=dw+'px';stage.style.height=dh+'px';photo.getContext('2d').drawImage(source,0,0,dw,dh);
      let mode='positive',strokes=[],current=null,lastResult=null,previewing=false;

      function redraw(){
        const g=paint.getContext('2d');g.clearRect(0,0,dw,dh);const all=current?[...strokes,current]:strokes;
        all.forEach(s=>{const pts=s.points||[];if(!pts.length)return;g.save();g.strokeStyle=s.mode==='negative'?'rgba(229,74,74,.92)':'rgba(255,79,139,.92)';g.fillStyle=g.strokeStyle;g.lineWidth=Math.max(10,Math.min(dw,dh)*.035);g.lineCap='round';g.lineJoin='round';g.beginPath();g.moveTo(pts[0].x*dw,pts[0].y*dh);if(pts.length===1)g.lineTo(pts[0].x*dw+.01,pts[0].y*dh+.01);else pts.slice(1).forEach(p=>g.lineTo(p.x*dw,p.y*dh));g.stroke();g.restore()});
      }
      function invalidate(){lastResult=null;applyBtn.disabled=true;mask.getContext('2d').clearRect(0,0,dw,dh);status.textContent='已更新筆刷，請再按一次 AI 預覽。'}
      function point(ev){const r=paint.getBoundingClientRect();return {x:Math.max(0,Math.min(1,(ev.clientX-r.left)/r.width)),y:Math.max(0,Math.min(1,(ev.clientY-r.top)/r.height))}}
      function begin(ev){if(previewing)return;ev.preventDefault();paint.setPointerCapture?.(ev.pointerId);current={mode,points:[point(ev)]};redraw()}
      function move(ev){if(!current||previewing)return;ev.preventDefault();const p=point(ev),q=current.points[current.points.length-1],dx=p.x-q.x,dy=p.y-q.y;if(dx*dx+dy*dy>.00002){current.points.push(p);redraw()}}
      function end(ev){if(!current)return;ev.preventDefault();if(current.points.length)strokes.push(current);current=null;redraw();invalidate()}
      paint.addEventListener('pointerdown',begin);paint.addEventListener('pointermove',move);paint.addEventListener('pointerup',end);paint.addEventListener('pointercancel',end);

      root.querySelectorAll('[data-mode]').forEach(btn=>btn.onclick=()=>{mode=btn.dataset.mode;root.querySelectorAll('[data-mode]').forEach(x=>x.classList.toggle('on',x===btn))});
      root.querySelector('[data-act="clear"]').onclick=()=>{strokes=[];current=null;lastResult=null;redraw();mask.getContext('2d').clearRect(0,0,dw,dh);applyBtn.disabled=true;status.textContent='已清除。用粉紅色「保留」重新塗過頭部。'};

      previewBtn.onclick=async()=>{
        if(previewing)return;if(!strokes.some(s=>s.mode==='positive'&&s.points.length)){status.textContent='請先用粉紅色「保留」筆刷塗一下頭髮、臉和耳朵。';return}
        previewing=true;previewBtn.disabled=true;applyBtn.disabled=true;status.textContent='AI 正在讀你塗的位置… 第一次使用可能需要載入模型，請稍等。';
        try{
          await new Promise(r=>requestAnimationFrame(()=>r()));lastResult=await guide.segment(source,strokes);guide.drawPreview(mask,lastResult,strokes);applyBtn.disabled=false;status.textContent='半透明粉紅區就是預計留下的範圍。不對的地方可用「排除」再塗，然後重新預覽。';
        }catch(e){console.error('[AI HEAD GUIDE PREVIEW]',e);lastResult=null;status.textContent=e.message||'AI 預覽失敗，請重新整理後再試一次'}finally{previewing=false;previewBtn.disabled=false}
      };

      function finish(value){document.body.style.overflow=oldOverflow;root.remove();if(!value){source.width=source.height=1}resolve(value)}
      root.querySelector('[data-act="cancel"]').onclick=()=>finish(null);
      applyBtn.onclick=()=>{
        if(!lastResult)return;
        applyBtn.disabled=true;previewBtn.disabled=true;status.textContent='正在套用大頭…';
        finish({source,result:lastResult,strokes:strokes.map(s=>({mode:s.mode,points:s.points.map(p=>({x:p.x,y:p.y}))}))});
      };
    });
  }

  async function run(){
    if(busy)return;const old=active();if(!isPhoto(old)){if(typeof toast==='function')toast('請先在畫布上選取一張人物照片');return}
    if(old.aiHeadCutout){if(typeof toast==='function')toast('這張照片已經是 AI 大頭摳圖 ♡');return}
    const guide=window.BenfuwanInteractiveHead;if(!guide){if(typeof toast==='function')toast('AI 塗選工具尚未載入，請重新整理頁面');return}
    busy=true;refresh();let selected=null;
    try{
      if(typeof closeSheets==='function')closeSheets();
      const sourceEl=old.getElement?.()||old._element;if(!sourceEl)throw new Error('讀不到原始照片');
      selected=await openGuide(sourceEl);if(!selected)return;

      // 互動式 segmentation 本身已輸出透明 mask。直接套用使用者剛確認的結果，
      // 不再中途呼叫 BiRefNet 去背替換 Fabric 物件，避免 preview 正常但套用時物件/尺寸失配。
      if(typeof setBusy==='function')setBusy(true,'正在套用你確認的大頭範圍…');
      const cut=guide.cut(selected.source,selected.result,selected.strokes);
      await replaceObject(old,cut);
      if(typeof toast==='function')toast('AI 大頭完成 ♡ 已套用你確認的頭部範圍');
    }catch(e){console.error('[FRONT AI HEAD APPLY]',e);if(typeof toast==='function')toast(e.message||'套用大頭失敗，請再試一次')}
    finally{
      if(selected?.source){selected.source.width=selected.source.height=1}
      busy=false;if(typeof setBusy==='function')setBusy(false);refresh();
    }
  }

  window.makeAiHeadCutout=run;

  function hook(){
    const cv=c();if(!cv||cv===hookedCanvas)return;hookedCanvas=cv;
    ['selection:created','selection:updated','selection:cleared','object:added','object:removed','object:modified'].forEach(evt=>cv.on(evt,()=>setTimeout(refresh,0)));
  }
  function boot(){ensureButton();ensureSheetButton();hook();setInterval(()=>{ensureButton();ensureSheetButton();hook();refresh()},700);console.info('[FRONT] guided AI head cutout enabled')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
