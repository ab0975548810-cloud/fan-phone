/* 修正模板圖片調整：Fabric filter 正確參數 + 重開模板可同步數值 */
(function(){
  'use strict';
  if(window.__benfuwanImageToolsFilterFixInstalled)return;
  window.__benfuwanImageToolsFilterFixInstalled=true;
  const by=id=>document.getElementById(id),canvas=()=>window.visualCanvas||null;
  const isImage=o=>!!o&&o.type==='image'&&!o.isTplBg&&!o.isSlot;

  function setFilter(o,Klass,prop,value){
    if(!Klass)return;
    o.filters=o.filters||[];
    o.filters=o.filters.filter(f=>!(f instanceof Klass));
    if(Math.abs(value)>.0001)o.filters.push(new Klass({[prop]:value}));
  }
  function apply(){
    const o=canvas()?.getActiveObject(),F=window.fabric?.Image?.filters;if(!isImage(o)||!F)return;
    const b=Number(by('bf-it-bright')?.value||0)/100,c=Number(by('bf-it-contrast')?.value||0)/100,s=Number(by('bf-it-sat')?.value||0)/100,bl=Number(by('bf-it-blur')?.value||0)/100;
    setFilter(o,F.Brightness,'brightness',b);setFilter(o,F.Contrast,'contrast',c);setFilter(o,F.Saturation,'saturation',s);setFilter(o,F.Blur,'blur',bl);
    o.__bfAdjust={brightness:b,contrast:c,saturation:s,blur:bl};o.applyFilters();canvas().requestRenderAll();
  }
  function valueFromFilters(o,type,prop){const f=(o?.filters||[]).find(x=>String(x.type||x.constructor?.name||'').toLowerCase()===type.toLowerCase());return Number(f?.[prop]||0)}
  function sync(){
    const o=canvas()?.getActiveObject();if(!isImage(o))return;
    const a=o.__bfAdjust||{brightness:valueFromFilters(o,'Brightness','brightness'),contrast:valueFromFilters(o,'Contrast','contrast'),saturation:valueFromFilters(o,'Saturation','saturation'),blur:valueFromFilters(o,'Blur','blur')};
    const map={bright:a.brightness,contrast:a.contrast,sat:a.saturation,blur:a.blur};Object.entries(map).forEach(([k,v])=>{const n=Math.round(Number(v||0)*100),e=by('bf-it-'+k),t=by('bf-it-'+k+'-v');if(e)e.value=String(n);if(t)t.textContent=String(n)})
  }
  function patchSerialize(){if(!window.fabric?.Object||fabric.Object.prototype.__bfAdjustPatched)return;const old=fabric.Object.prototype.toObject;fabric.Object.prototype.toObject=function(props){const out=old.call(this,props);if(this.__bfAdjust)out.__bfAdjust=this.__bfAdjust;return out};fabric.Object.prototype.__bfAdjustPatched=true}
  function bind(){patchSerialize();['bright','contrast','sat','blur'].forEach(k=>{const e=by('bf-it-'+k);if(e&&!e.dataset.bfFilterFix){e.dataset.bfFilterFix='1';e.oninput=()=>{const v=by('bf-it-'+k+'-v');if(v)v.textContent=e.value;apply()}}});const c=canvas();if(c&&!c.__bfFilterFixHooked){c.__bfFilterFixHooked=true;['selection:created','selection:updated'].forEach(ev=>c.on(ev,()=>setTimeout(sync,0)))}}
  setInterval(bind,500);console.info('[ADMIN] template image filter fix enabled');
})();