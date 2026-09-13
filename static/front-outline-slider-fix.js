/* 本福丸前台：描邊粗細滑桿觸控拖曳修正（iPhone / iPad） */
(function(){
  'use strict';
  if(window.__benfuwanOutlineSliderFixInstalled)return;
  window.__benfuwanOutlineSliderFixInstalled=true;

  function ensureCss(){
    if(document.getElementById('bf-outline-slider-fix-css'))return;
    const s=document.createElement('style');
    s.id='bf-outline-slider-fix-css';
    s.textContent=`
      #bf-os-width{
        width:100%;min-width:0;height:38px;margin:0;
        touch-action:none;-webkit-user-select:none;user-select:none;
        -webkit-appearance:none;appearance:none;background:transparent;
      }
      #bf-os-width::-webkit-slider-runnable-track{
        height:7px;border-radius:999px;background:#f2d6df;
      }
      #bf-os-width::-webkit-slider-thumb{
        -webkit-appearance:none;appearance:none;
        width:26px;height:26px;border-radius:50%;
        background:var(--pink);border:3px solid #fff;
        box-shadow:0 2px 8px rgba(180,70,105,.28);
        margin-top:-9.5px;
      }
      #bf-os-width::-moz-range-track{height:7px;border-radius:999px;background:#f2d6df}
      #bf-os-width::-moz-range-thumb{width:24px;height:24px;border-radius:50%;background:var(--pink);border:3px solid #fff}
      #bf-os-width-value{font-size:12px;font-weight:900;color:var(--pink-dark)}
    `;
    document.head.appendChild(s);
  }

  function bindRange(){
    const el=document.getElementById('bf-os-width');
    if(!el||el.dataset.bfDragFixed==='1')return false;
    el.dataset.bfDragFixed='1';

    const updateFromX=(clientX)=>{
      const r=el.getBoundingClientRect();
      if(!r.width)return;
      const min=Number(el.min||0),max=Number(el.max||100),step=Number(el.step||1)||1;
      let ratio=(clientX-r.left)/r.width;ratio=Math.max(0,Math.min(1,ratio));
      let v=min+ratio*(max-min);v=Math.round((v-min)/step)*step+min;
      v=Math.max(min,Math.min(max,v));
      el.value=String(v);
      const out=document.getElementById('bf-os-width-value');if(out)out.textContent=String(v);
    };

    let dragging=false,moved=false;
    el.addEventListener('touchstart',e=>{
      if(!e.touches?.length)return;
      dragging=true;moved=false;updateFromX(e.touches[0].clientX);
      e.preventDefault();e.stopPropagation();
    },{passive:false});
    el.addEventListener('touchmove',e=>{
      if(!dragging||!e.touches?.length)return;
      moved=true;updateFromX(e.touches[0].clientX);
      e.preventDefault();e.stopPropagation();
    },{passive:false});
    const finish=e=>{
      if(!dragging)return;
      dragging=false;
      // 只在放手時套用一次描邊，拖曳中不重算圖片，避免卡頓。
      el.dispatchEvent(new Event('input',{bubbles:true}));
      e?.preventDefault?.();e?.stopPropagation?.();
    };
    el.addEventListener('touchend',finish,{passive:false});
    el.addEventListener('touchcancel',finish,{passive:false});
    return true;
  }

  function boot(){
    ensureCss();
    if(bindRange())console.info('[FRONT] outline width slider touch-drag fixed');
    const obs=new MutationObserver(()=>bindRange());
    obs.observe(document.body,{childList:true,subtree:true});
  }

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
