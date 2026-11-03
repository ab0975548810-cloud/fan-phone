(function(){
  'use strict';
  if(window.__benfuwanFrontHomeV1)return;
  window.__benfuwanFrontHomeV1=true;

  const byId=id=>document.getElementById(id);
  let syncToken=0;
  let catalogReady=false;

  function renderDraftState(state){
    const card=byId('home-design-card'),title=byId('home-design-title'),subtitle=byId('home-design-subtitle');
    if(!card||!title||!subtitle)return state;
    card.dataset.draftState=state;
    if(state==='loading'){
      title.textContent='我的設計';
      subtitle.textContent='正在檢查上次設計…';
    }else if(state==='ready'){
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

  async function syncHomeDraftCard(){
    const card=byId('home-design-card');
    const api=window.BenfuwanDesignDraft;
    if(!card||!api)return 'unavailable';
    if(!catalogReady)return renderDraftState('loading');
    const token=++syncToken;
    let state='empty';
    try{
      const raw=await api.readDraft(null,false);
      if(raw)state=api.inspectDraft(raw).ok?'ready':'invalid';
    }catch(error){
      console.warn('[FRONT HOME] draft state unavailable',error);
    }
    if(token!==syncToken)return card.dataset.draftState||state;
    return renderDraftState(state);
  }

  async function openHomeDesign(){
    const api=window.BenfuwanDesignDraft;
    const state=await syncHomeDraftCard();
    if(state==='loading'){
      window.toast?.('正在檢查上次設計，請稍候');
      return false;
    }
    const rows=await BenfuwanDraftStore.list();
    if(!rows.length){window.toast?.('目前沒有未完成設計');return false;}
    let panel=byId('design-library');
    if(!panel){
      panel=document.createElement('section');panel.id='design-library';panel.className='card';
      byId('design-draft-prompt').after(panel);
    }
    panel.replaceChildren();
    const heading=document.createElement('h3');heading.textContent='我的設計';panel.append(heading);
    const note=document.createElement('p');note.textContent='草稿只保存在此瀏覽器，不會定期到期。刪除草稿或清除網站資料會移除圖片。共用裝置請於使用後清理。';panel.append(note);
    for(const row of rows){
      const section=document.createElement('div'),title=document.createElement('p');
      title.textContent=row.name;section.append(title);
      function action(label,fn){
        const button=document.createElement('button');button.type='button';button.className='secondary';
        button.textContent=label;button.onclick=async()=>{try{await fn();}catch(error){toast(error.message);}};section.append(button);
      }
      action('繼續編輯',async()=>{if(!await api.continueEditing(row.key))toast('無法恢復，請查看首頁提示。');});
      action('重新命名',async()=>{
        const name=window.prompt('設計名稱',row.name)?.trim().slice(0,80);
        if(!name)return;
        const expected=row.revision||row.updatedAt, next=crypto.randomUUID();
        await BenfuwanDraftStore.change(row.key,expected,old=>({...old,name,revision:next}));
        api.renamed(row.key,expected,name,next);
        await openHomeDesign();
      });
      action('刪除',async()=>{
        if((await idbGet('cart'))?.draftKey===row.key || await idbGet('saved-cart:'+row.key))return toast('此設計仍在購物車中。');
        if(!window.confirm('確定刪除這份草稿及其中的圖片？'))return;
        await BenfuwanDraftStore.change(row.key,row.revision||row.updatedAt,()=>null);
        panel.remove();await api.refreshPrompt();await syncHomeDraftCard();
        if((await BenfuwanDraftStore.list()).length)await openHomeDesign();
      });
      panel.append(section);
    }
    panel.scrollIntoView({block:'center'});return true;
  }

  function openHomeTemplates(){
    window.toast?.('先選手機型號與殼款，再挑熱門模板');
    return window.startNewDesign?.();
  }

  window.openHomeDesign=openHomeDesign;
  window.openHomeTemplates=openHomeTemplates;

  const originalLoadAll=window.loadAll;
  if(typeof originalLoadAll==='function'){
    window.loadAll=async function(){
      const result=await originalLoadAll.apply(this,arguments);
      catalogReady=true;
      await syncHomeDraftCard();
      return result;
    };
  }

  window.BenfuwanFrontHomeV1=Object.freeze({syncHomeDraftCard,openHomeDesign,openHomeTemplates,isCatalogReady:()=>catalogReady});

  const home=byId('page-home');
  if(home)new MutationObserver(()=>{if(home.classList.contains('active'))syncHomeDraftCard()}).observe(home,{attributes:true,attributeFilter:['class']});
  window.addEventListener('pageshow',syncHomeDraftCard);
  window.addEventListener('load',()=>setTimeout(syncHomeDraftCard,0));
  syncHomeDraftCard();
})();
