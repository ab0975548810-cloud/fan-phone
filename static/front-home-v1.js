(function(){
  'use strict';
  if(window.__benfuwanFrontHomeV1)return;
  window.__benfuwanFrontHomeV1=true;

  const byId=id=>document.getElementById(id);
  let syncToken=0;

  async function syncHomeDraftCard(){
    const card=byId('home-design-card'),title=byId('home-design-title'),subtitle=byId('home-design-subtitle');
    const api=window.BenfuwanDesignDraft;
    if(!card||!title||!subtitle||!api)return 'unavailable';
    const token=++syncToken;
    let state='empty';
    try{
      const raw=await api.readDraft();
      if(raw)state=api.inspectDraft(raw).ok?'ready':'invalid';
    }catch(error){
      console.warn('[FRONT HOME] draft state unavailable',error);
    }
    if(token!==syncToken)return card.dataset.draftState||state;
    card.dataset.draftState=state;
    if(state==='ready'){
      title.textContent='繼續上次設計';
      subtitle.textContent='回到上次中斷的位置';
    }else if(state==='invalid'){
      title.textContent='我的設計';
      subtitle.textContent='舊設計需要重新開始';
    }else{
      title.textContent='我的設計';
      subtitle.textContent='有草稿時可從這裡繼續';
    }
    return state;
  }

  async function openHomeDesign(){
    const api=window.BenfuwanDesignDraft;
    const state=await syncHomeDraftCard();
    if(state==='ready'&&api)return api.continueEditing();
    if(state==='invalid'&&api){
      await api.refreshPrompt();
      byId('design-draft-prompt')?.scrollIntoView({behavior:'smooth',block:'center'});
      window.toast?.('舊設計需要先重新開始');
      return false;
    }
    window.toast?.('目前沒有未完成設計');
    return false;
  }

  function openHomeTemplates(){
    window.toast?.('先選手機型號與殼款，再挑熱門模板');
    return window.startNewDesign?.();
  }

  window.openHomeDesign=openHomeDesign;
  window.openHomeTemplates=openHomeTemplates;
  window.BenfuwanFrontHomeV1=Object.freeze({syncHomeDraftCard,openHomeDesign,openHomeTemplates});

  const home=byId('page-home');
  if(home)new MutationObserver(()=>{if(home.classList.contains('active'))syncHomeDraftCard()}).observe(home,{attributes:true,attributeFilter:['class']});
  window.addEventListener('pageshow',syncHomeDraftCard);
  window.addEventListener('load',()=>setTimeout(syncHomeDraftCard,0));
  syncHomeDraftCard();
})();
