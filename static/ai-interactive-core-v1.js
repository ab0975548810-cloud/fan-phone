/* Generic MagicTouch full-frame segmentation. No head gate, crop or cloud call. */
(function(){
  'use strict';
  if(window.BenfuwanAiTools)return;
  let toolPromise=null,opened=false;
  const clamp=n=>Math.max(0,Math.min(1,n));
  async function tool(){
    if(!toolPromise)toolPromise=(async()=>{
      const imported=await import('/vendor/mediapipe/vision_bundle.mjs?v=1.0.1');
      const mod=imported.InteractiveSegmenter?imported:imported.default;
      if(!mod?.InteractiveSegmenter||!mod?.FilesetResolver)throw new Error('點選摳圖核心尚未準備好');
      const vision=await mod.FilesetResolver.forVisionTasks('/vendor/mediapipe/wasm');
      const modelAssetPath='/vendor/mediapipe/interactive_segmentation.task';
      let segmenter;
      try{
        segmenter=await mod.InteractiveSegmenter.createFromOptions(vision,{baseOptions:{modelAssetPath,delegate:'CPU'}});
      }catch(_){
        segmenter=await mod.InteractiveSegmenter.createFromOptions(vision,{baseOptions:{modelAssetPath}});
      }
      return {segmenter,BrushMode:mod.BrushMode||{POSITIVE:1,NEGATIVE:2}};
    })().catch(e=>{toolPromise=null;throw e});
    return toolPromise;
  }
  function normalizedStrokes(strokes,BrushMode){
    return strokes.filter(s=>s.points.length).map(s=>({brushMode:s.mode==='negative'?BrushMode.NEGATIVE:BrushMode.POSITIVE,
      point:s.points.map(p=>({x:clamp(p.x),y:clamp(p.y)})),isCompleted:true}));
  }
  async function segment(el,strokes){
    if(!strokes.some(s=>s.mode==='positive'&&s.points.length))throw new Error('請先點選或塗上要保留的主體');
    const core=window.BenfuwanAiRemoveV2,{width,height}=core.elementSize(el);
    if(!width||!height||width*height>32_000_000)throw new Error('圖片像素過大或尺寸無效');
    const inference=document.createElement('canvas'),ratio=Math.min(1,1536/Math.max(width,height));
    inference.width=Math.max(1,Math.round(width*ratio));inference.height=Math.max(1,Math.round(height*ratio));
    const g=inference.getContext('2d');g.fillStyle='#fff';g.fillRect(0,0,inference.width,inference.height);g.drawImage(el,0,0,inference.width,inference.height);
    const {segmenter,BrushMode}=await tool();
    let result,mask;
    try{
      segmenter.setImage(inference);
      result=segmenter.segment(normalizedStrokes(strokes,BrushMode));
      const w=result.width,h=result.height,data=result.getAsFloat32Array();
      if(!w||!h||w*h>32_000_000||data.length!==w*h)throw new Error('點選摳圖遮罩無效');
      mask=document.createElement('canvas');mask.width=w;mask.height=h;
      const mg=mask.getContext('2d'),pixels=mg.createImageData(w,h);
      for(let i=0;i<w*h;i++){
        if(!Number.isFinite(data[i]))throw new Error('點選摳圖遮罩無效');
        pixels.data.set([255,255,255,Math.round(clamp((data[i]-.12)/.78)*255)],i*4);
      }
      mg.putImageData(pixels,0,0);
      const blob=await core.compositeWithMask(el,mask);await core.validate(blob);return blob;
    }finally{result?.close?.();inference.width=inference.height=1;if(mask)mask.width=mask.height=1}
  }
  function dialog(title){
    const d=document.createElement('dialog');d.className='bf-ai-tool-dialog';
    d.innerHTML='<div class="bf-ai-tool-head"><b></b><button type="button" data-close aria-label="關閉">×</button></div><div data-body></div>';
    d.querySelector('b').textContent=title;document.body.append(d);return d;
  }
  function chooseMode(){
    if(opened)return Promise.resolve(null);opened=true;
    return new Promise(resolve=>{
      const d=dialog('AI 摳圖工具');
      d.querySelector('[data-body]').innerHTML='<div class="bf-ai-modes"><button type="button" data-ai-mode="general"><b>自動去背</b><span>人物、寵物、商品</span></button><button type="button" data-ai-mode="interactive"><b>點選摳圖</b><span>自己指定要留下的區域</span></button><button type="button" data-ai-mode="stamp"><b>印花摳圖</b><span>Logo、插畫、衣服／商品上的圖案</span></button></div>';
      const finish=value=>{d.close();d.remove();opened=false;resolve(value)};
      d.querySelector('[data-close]').onclick=()=>finish(null);
      d.addEventListener('cancel',e=>{e.preventDefault();finish(null)});
      d.querySelectorAll('[data-ai-mode]').forEach(b=>b.onclick=()=>finish(b.dataset.aiMode));
      d.showModal();
    });
  }
  function interactive(el){
    if(opened)return Promise.resolve(null);opened=true;
    return new Promise(resolve=>{
      const d=dialog('點選摳圖'),size=window.BenfuwanAiRemoveV2.elementSize(el);
      d.querySelector('[data-body]').innerHTML='<p>點選或塗出要留下的主體，使用「排除」修正背景。</p><div class="bf-ai-brushes"><button type="button" data-brush="positive" aria-pressed="true">保留</button><button type="button" data-brush="negative" aria-pressed="false">排除</button><button type="button" data-undo>撤銷一筆</button></div><canvas data-ai-strokes></canvas><div role="status" data-ai-status></div><button type="button" class="bf-ai-apply" data-ai-apply>產生透明圖</button>';
      const canvas=d.querySelector('canvas'),g=canvas.getContext('2d'),ratio=Math.min(1,900/Math.max(size.width,size.height));
      canvas.width=Math.max(1,Math.round(size.width*ratio));canvas.height=Math.max(1,Math.round(size.height*ratio));canvas.style.width='min(100%, '+(50*size.width/size.height)+'dvh)';
      let strokes=[],brush='positive',current=null,pointerId=null,busy=false,closed=false;
      const status=d.querySelector('[data-ai-status]');
      const draw=()=>{
        g.clearRect(0,0,canvas.width,canvas.height);g.drawImage(el,0,0,canvas.width,canvas.height);g.lineWidth=8;g.lineCap='round';
        for(const s of strokes){g.strokeStyle=s.mode==='negative'?'#4689da':'#ff5a92';g.fillStyle=g.strokeStyle;g.beginPath();s.points.forEach((p,i)=>{const x=p.x*canvas.width,y=p.y*canvas.height;i?g.lineTo(x,y):g.moveTo(x,y)});g.stroke();const p=s.points[0];g.beginPath();g.arc(p.x*canvas.width,p.y*canvas.height,4,0,Math.PI*2);g.fill()}
      };
      const finish=blob=>{if(closed)return;closed=true;d.close();d.remove();opened=false;resolve(blob)};
      const point=e=>{const r=canvas.getBoundingClientRect();return {x:clamp((e.clientX-r.left)/r.width),y:clamp((e.clientY-r.top)/r.height)}};
      canvas.onpointerdown=e=>{if(busy||pointerId!==null||(!e.isPrimary))return;e.preventDefault();pointerId=e.pointerId;canvas.setPointerCapture(e.pointerId);current={mode:brush,points:[point(e)]};strokes.push(current);draw()};
      canvas.onpointermove=e=>{if(current&&e.pointerId===pointerId){e.preventDefault();current.points.push(point(e));draw()}};
      const end=e=>{if(e.pointerId===pointerId){current=null;pointerId=null}};canvas.onpointerup=end;canvas.onpointercancel=end;
      d.querySelectorAll('[data-brush]').forEach(b=>b.onclick=()=>{if(busy)return;brush=b.dataset.brush;d.querySelectorAll('[data-brush]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)))});
      d.querySelector('[data-undo]').onclick=()=>{if(!busy){strokes.pop();draw()}};
      d.querySelector('[data-close]').onclick=()=>{if(!busy)finish(null)};
      d.addEventListener('cancel',e=>{e.preventDefault();if(!busy)finish(null)});
      d.querySelector('[data-ai-apply]').onclick=async()=>{
        if(busy||pointerId!==null)return;busy=true;d.querySelectorAll('button').forEach(b=>b.disabled=true);status.textContent='正在產生透明圖…';
        try{finish(await segment(el,strokes))}catch(e){status.textContent=e.message||'摳圖失敗，原圖已保留'}
        finally{busy=false;if(!closed)d.querySelectorAll('button').forEach(b=>b.disabled=false)}
      };
      try{draw();d.showModal()}catch(e){finish(null)}
    });
  }
  const css=document.createElement('link');css.rel='stylesheet';css.href='/static/ai-tools-v1.css?v=20261004a';document.head.append(css);
  window.BenfuwanAiTools={chooseMode,interactive,segment,normalizedStrokes};
})();
