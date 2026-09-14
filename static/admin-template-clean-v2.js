/* 本福丸模板工作台：移除會擋畫布的型號遮罩，回到背景可選／可移除的乾淨編輯畫布 */
(function(){
  'use strict';
  if(window.__benfuwanTemplateCleanV2Installed)return;
  window.__benfuwanTemplateCleanV2Installed=true;
  const by=id=>document.getElementById(id);

  function clean(){
    by('bf-tpl-model-mask')?.remove();
    by('bf-tpl-safe-note')?.remove();
    const wrap=by('canvas-wrap');
    if(wrap){
      wrap.style.overflow='hidden';
      wrap.style.backgroundColor='#fff';
    }
    const bgBtn=by('bf-tpl-bg-btn-v3');
    if(bgBtn&&!bgBtn.dataset.cleanLabel){
      bgBtn.dataset.cleanLabel='1';
      bgBtn.innerHTML='<span class="ico"><i class="fa-solid fa-palette"></i></span>底圖／背景';
    }
    const bg=by('bf-tpl-bg-v3');
    if(bg&&!by('bf-tpl-bg-clean-note')){
      const note=document.createElement('div');
      note.id='bf-tpl-bg-clean-note';
      note.style.cssText='font-size:10px;color:#8e8288;line-height:1.55;margin-top:8px';
      note.textContent='可選純色、透明、上傳底圖；不需要底圖時按「移除底圖」。手機殼型號遮罩不再蓋在編輯畫布上。';
      bg.appendChild(note);
    }
  }

  function boot(){
    clean();
    const obs=new MutationObserver(clean);
    obs.observe(document.documentElement,{childList:true,subtree:true});
    setInterval(clean,1200);
    console.info('[ADMIN] template clean canvas enabled');
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();