/* Lazy-load heavy template editor only when template work is actually opened. */
(function(){
  'use strict';
  if(window.__benfuwanTemplateLoaderInstalled)return;
  window.__benfuwanTemplateLoaderInstalled=true;

  const STACK=[
    '/static/admin-universal-templates.js?v=20260914h',
    '/static/admin-template-editor-v2.js?v=20260914h',
    '/static/admin-template-editor-v3.js?v=20260914h',
    '/static/admin-template-editor-v4.js?v=20260914h',
    '/static/admin-template-editor-v4-fix.js?v=20260914h',
    '/static/admin-global-canvas-bridge.js?v=20260914h',
    '/static/admin-template-clean-v2.js?v=20260914h',
    '/static/admin-template-outline-v2.js?v=20260914h',
    '/static/admin-template-image-tools-v2.js?v=20260914h',
    '/static/admin-template-image-tools-v2-fix.js?v=20260914h',
    '/static/admin-upload-optimizer.js?v=20260914h',
    '/static/admin-template-normalized-v5.js?v=20260914j',
    '/static/admin-ai-v5.js?v=20260915remove1',
    '/static/admin-template-history-v1.js?v=20260915a'
  ];
  let loading=null,loaded=false;

  function loadOne(src){return new Promise((resolve,reject)=>{if(document.querySelector(`script[src="${src}"]`))return resolve();const s=document.createElement('script');s.src=src;s.async=false;s.onload=resolve;s.onerror=()=>reject(new Error('模板工具載入失敗'));document.body.appendChild(s)})}
  async function ensure(){
    if(loaded)return;
    if(loading)return loading;
    loading=(async()=>{for(const src of STACK)await loadOne(src);loaded=true;window.__benfuwanTemplateStackReady=true;console.info('[ADMIN] template editor stack lazy-loaded')})().finally(()=>{loading=null});
    return loading;
  }
  window.benfuwanEnsureTemplateEditor=ensure;

  const baseOpen=window.openTemplateEditor;
  if(typeof baseOpen==='function'){
    window.openTemplateEditor=async function(...args){
      const btn=document.querySelector('#view-templates .titlebar .btn');
      const old=btn?.innerHTML;if(btn){btn.disabled=true;btn.textContent='載入編輯器…'}
      try{await ensure();return baseOpen.apply(this,args)}catch(e){console.error(e);alert(e.message||'模板編輯器載入失敗')}finally{if(btn){btn.disabled=false;if(old!=null)btn.innerHTML=old}}
    };
  }

  document.addEventListener('click',ev=>{
    const nav=ev.target.closest('[data-view="templates"]');
    if(nav)ensure().catch(console.error);
  },{passive:true});
})();
