/* 本福丸後台：貼紙分類管理 + 大量貼紙效能優化 */
(function(){
  'use strict';
  if(window.__benfuwanAssetCategoriesInstalled)return;
  window.__benfuwanAssetCategoriesInstalled=true;

  const PAGE_SIZE=40;
  let shown=PAGE_SIZE;
  let batchMode=false;
  const selected=new Set();

  const h=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const categories=()=>{
    const raw=Array.isArray(assetsData?.categories)?assetsData.categories:[];
    return ['全部',...raw.filter((c,i)=>c&&c!=='全部'&&raw.indexOf(c)===i)];
  };
  const allStickers=()=>Array.isArray(assetsData?.stickers)?assetsData.stickers:[];
  const visibleList=()=>currentAsset==='全部'?allStickers():allStickers().filter(s=>(s.category||'全部')===currentAsset);

  function ensureCss(){
    if(document.getElementById('bf-asset-cat-css'))return;
    const s=document.createElement('style');s.id='bf-asset-cat-css';
    s.textContent=`
      #view-assets .asset-cat-actions{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
      #view-assets .asset-cat-actions .btn{padding:8px 12px}
      #asset-batchbar{display:none;align-items:center;gap:8px;flex-wrap:wrap;margin:0 0 12px;padding:10px 12px;border:1px solid #f0dce3;border-radius:14px;background:#fff7fa}
      #asset-batchbar.show{display:flex}
      #asset-batchbar input{min-width:150px;flex:1;border:1px solid #eadce1;border-radius:999px;padding:9px 12px;background:#fff}
      #asset-batchbar .count{font-size:12px;font-weight:900;color:#d95580;min-width:72px}
      #asset-grid .card.bf-selectable{cursor:pointer;transition:.1s ease;content-visibility:auto;contain-intrinsic-size:160px 170px}
      #asset-grid .card.bf-selected{border:2px solid var(--pink);background:#fff1f6;box-shadow:0 0 0 3px rgba(255,120,158,.08)}
      #asset-grid .card img{content-visibility:auto}
      .bf-asset-check{position:absolute;left:8px;top:8px;width:28px;height:28px;border-radius:50%;display:grid;place-items:center;background:#fff;border:1px solid #efcad5;color:#bbb;box-shadow:0 2px 8px rgba(0,0,0,.08);z-index:2;font-size:12px}
      .bf-selected .bf-asset-check{background:var(--pink);border-color:var(--pink);color:#fff}
      .bf-asset-more{grid-column:1/-1;display:flex;justify-content:center;align-items:center;gap:10px;padding:14px 0 4px;color:#8f8288;font-size:12px}
      .bf-uploading{opacity:.65;pointer-events:none}
      @media(max-width:800px){#view-assets .titlebar{align-items:flex-start}.asset-cat-actions{justify-content:flex-end}#asset-batchbar input{min-width:120px}}
    `;
    document.head.appendChild(s);
  }

  function ensureUi(){
    ensureCss();
    const view=document.getElementById('view-assets');if(!view)return;
    const title=view.querySelector('.titlebar');
    if(title&&!document.getElementById('bf-asset-cat-actions')){
      const oldUpload=title.querySelector('button');
      const wrap=document.createElement('div');wrap.id='bf-asset-cat-actions';wrap.className='asset-cat-actions';
      const add=document.createElement('button');add.className='btn alt';add.innerHTML='<i class="fa-solid fa-folder-plus"></i> 新增分類';add.onclick=createCategory;
      const rename=document.createElement('button');rename.className='btn alt';rename.innerHTML='<i class="fa-solid fa-pen"></i> 改名';rename.onclick=renameCategory;
      const remove=document.createElement('button');remove.className='btn danger';remove.innerHTML='<i class="fa-solid fa-folder-minus"></i> 刪除分類';remove.onclick=deleteCategory;
      const batch=document.createElement('button');batch.id='bf-batch-cat-btn';batch.className='btn alt';batch.innerHTML='<i class="fa-solid fa-check-double"></i> 批量分類';batch.onclick=toggleBatch;
      if(oldUpload){oldUpload.remove();oldUpload.id='bf-sticker-upload-btn';wrap.append(add,rename,remove,batch,oldUpload)}else wrap.append(add,rename,remove,batch);
      title.appendChild(wrap);
    }
    const panel=view.querySelector('.panel');
    if(panel&&!document.getElementById('asset-batchbar')){
      const bar=document.createElement('div');bar.id='asset-batchbar';
      bar.innerHTML='<span class="count" id="bf-asset-count">已選 0 張</span><button class="btn alt mini" id="bf-select-visible">全選目前分類</button><input id="bf-target-category" list="bf-category-list" placeholder="輸入分類，例如：貓咪"><datalist id="bf-category-list"></datalist><button class="btn mini" id="bf-move-assets">移到分類</button><button class="btn danger mini" id="bf-cancel-batch">取消</button>';
      panel.insertBefore(bar,panel.firstChild);
      document.getElementById('bf-select-visible').onclick=selectVisible;
      document.getElementById('bf-move-assets').onclick=moveSelected;
      document.getElementById('bf-cancel-batch').onclick=()=>{batchMode=false;selected.clear();syncBatchUi();renderAssets()};
    }
    refreshDatalist();syncBatchUi();
  }

  function refreshDatalist(){
    const dl=document.getElementById('bf-category-list');if(!dl)return;
    dl.innerHTML=categories().filter(c=>c!=='全部').map(c=>`<option value="${h(c)}"></option>`).join('');
  }

  function syncBatchUi(){
    const bar=document.getElementById('asset-batchbar'),btn=document.getElementById('bf-batch-cat-btn'),count=document.getElementById('bf-asset-count');
    bar?.classList.toggle('show',batchMode);
    if(btn)btn.innerHTML=batchMode?'<i class="fa-solid fa-xmark"></i> 結束選取':'<i class="fa-solid fa-check-double"></i> 批量分類';
    if(count)count.textContent=`已選 ${selected.size} 張`;
  }

  function resetPage(){shown=PAGE_SIZE}
  function toggleBatch(){batchMode=!batchMode;selected.clear();syncBatchUi();resetPage();renderAssets()}
  function toggleOne(id){if(selected.has(id))selected.delete(id);else selected.add(id);syncBatchUi();const card=document.querySelector(`#asset-grid .card[data-id="${CSS.escape(id)}"]`);if(card){card.classList.toggle('bf-selected',selected.has(id));const ck=card.querySelector('.bf-asset-check');if(ck)ck.innerHTML=selected.has(id)?'<i class="fa-solid fa-check"></i>':''}}
  function selectVisible(){
    const ids=visibleList().map(s=>String(s.id));
    const all=ids.length&&ids.every(id=>selected.has(id));
    ids.forEach(id=>all?selected.delete(id):selected.add(id));
    syncBatchUi();renderAssets();
  }

  async function api(body){return apiJson('/api/admin/sticker_category',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})}

  async function createCategory(){
    const name=(prompt('新增貼紙分類名稱，例如：貓咪','')||'').trim();if(!name)return;
    try{
      await api({action:'create',name});
      if(!assetsData.categories.includes(name))assetsData.categories.push(name);
      currentAsset=name;resetPage();renderAssetTabs();renderAssets();refreshDatalist();
    }catch(e){alert(e.message||'新增分類失敗')}
  }

  async function renameCategory(){
    const old=currentAsset;
    if(!old||old==='全部')return alert('請先點進要改名的分類');
    const name=(prompt(`把「${old}」改成：`,old)||'').trim();if(!name||name===old)return;
    try{
      const r=await api({action:'rename',old,new:name});
      assetsData.categories=categories().filter(c=>c!=='全部'&&c!==old);
      if(!assetsData.categories.includes(name))assetsData.categories.push(name);
      allStickers().forEach(s=>{if((s.category||'全部')===old)s.category=name});
      currentAsset=name;resetPage();renderAssetTabs();renderAssets();refreshDatalist();
      alert(`分類已改成「${name}」，共整理 ${r.moved||0} 張貼紙`);
    }catch(e){alert(e.message||'分類改名失敗')}
  }

  async function deleteCategory(){
    const old=currentAsset;
    if(!old||old==='全部')return alert('「全部」是系統分類，不能刪除');
    const count=allStickers().filter(s=>(s.category||'全部')===old).length;
    if(!confirm(`刪除分類「${old}」？\n\n${count} 張貼紙不會被刪掉，會移回「全部」。`))return;
    try{
      await api({action:'delete',name:old});
      assetsData.categories=categories().filter(c=>c!=='全部'&&c!==old);
      allStickers().forEach(s=>{if((s.category||'全部')===old)s.category='全部'});
      currentAsset='全部';selected.clear();batchMode=false;resetPage();renderAssetTabs();renderAssets();refreshDatalist();syncBatchUi();
    }catch(e){alert(e.message||'刪除分類失敗')}
  }

  async function moveSelected(){
    if(!selected.size)return alert('請先選擇貼紙');
    const input=document.getElementById('bf-target-category');
    const name=(input?.value||'').trim();if(!name)return alert('請輸入要移到的分類，例如：貓咪');
    try{
      const ids=[...selected];const r=await api({action:'move',name,ids});
      if(!assetsData.categories.includes(name))assetsData.categories.push(name);
      const wanted=new Set(ids);allStickers().forEach(s=>{if(wanted.has(String(s.id)))s.category=name});
      selected.clear();batchMode=false;currentAsset=name;resetPage();renderAssetTabs();renderAssets();refreshDatalist();syncBatchUi();if(input)input.value='';
      alert(`完成，${r.moved||0} 張貼紙已移到「${name}」`);
    }catch(e){alert(e.message||'批量分類失敗')}
  }

  function installRenderOverrides(){
    window.renderAssetTabs=function(){
      ensureUi();
      const cats=categories();if(!cats.includes(currentAsset))currentAsset='全部';
      const box=document.getElementById('asset-tabs');if(!box)return;
      box.innerHTML='';
      cats.forEach(c=>{const b=document.createElement('button');b.className='pill'+(c===currentAsset?' active':'');b.textContent=c;b.onclick=()=>{currentAsset=c;resetPage();renderAssetTabs();renderAssets()};box.appendChild(b)});
      refreshDatalist();
    };

    window.renderAssets=function(){
      ensureUi();
      const list=visibleList(),box=document.getElementById('asset-grid');if(!box)return;
      box.className='grid';box.innerHTML='';
      if(!list.length){box.innerHTML='<div class="empty">這個分類目前沒有素材</div>';return}
      const frag=document.createDocumentFragment();
      list.slice(0,shown).forEach(s=>{
        const id=String(s.id||'');
        const card=document.createElement('div');card.dataset.id=id;card.className='card'+(batchMode?' bf-selectable':'')+(selected.has(id)?' bf-selected':'');
        if(batchMode){const check=document.createElement('span');check.className='bf-asset-check';check.innerHTML=selected.has(id)?'<i class="fa-solid fa-check"></i>':'';card.appendChild(check);card.onclick=e=>{if(e.target.closest('.del'))return;toggleOne(id)}}
        const del=document.createElement('button');del.className='del';del.textContent='×';del.onclick=e=>{e.stopPropagation();deleteSticker(id)};card.appendChild(del);
        const img=document.createElement('img');img.loading='lazy';img.decoding='async';img.fetchPriority='low';img.src=s.url||'';img.alt='';card.appendChild(img);frag.appendChild(card);
      });
      box.appendChild(frag);
      if(shown<list.length){const more=document.createElement('div');more.className='bf-asset-more';more.innerHTML=`<span>已顯示 ${Math.min(shown,list.length)} / ${list.length}</span>`;const b=document.createElement('button');b.className='btn alt mini';b.textContent='顯示更多';b.onclick=()=>{shown+=PAGE_SIZE;renderAssets()};more.appendChild(b);box.appendChild(more)}
      syncBatchUi();
    };
  }

  function installFastUpload(){
    window.uploadStickers=async function(e){
      const fs=[...(e.target.files||[])];if(!fs.length)return;
      const def=currentAsset&&currentAsset!=='全部'?currentAsset:'貓咪';
      const cat=(prompt('這批貼紙要放在哪個分類？',def)||'').trim();if(!cat){e.target.value='';return}
      const fd=new FormData();fs.forEach(f=>fd.append('files',f));fd.append('category',cat);
      const btn=document.getElementById('bf-sticker-upload-btn');const old=btn?.innerHTML;
      if(btn){btn.classList.add('bf-uploading');btn.innerHTML=`<i class="fa-solid fa-spinner fa-spin"></i> 上傳中 ${fs.length} 張`}
      try{
        const r=await apiJson('/api/admin/batch_upload_stickers',{method:'POST',body:fd});
        const uploaded=Array.isArray(r.data)?r.data:[];
        if(!assetsData.categories.includes(cat))assetsData.categories.push(cat);
        if(uploaded.length)assetsData.stickers.push(...uploaded);else assetsLoaded=false;
        currentAsset=cat;resetPage();renderAssetTabs();renderAssets();refreshDatalist();
        alert(`上傳完成，共 ${fs.length} 張`);
      }catch(err){alert(err.message||'上傳失敗')}
      finally{if(btn){btn.classList.remove('bf-uploading');btn.innerHTML=old||'<i class="fa-solid fa-cloud-arrow-up"></i> 批量上傳'}e.target.value=''}
    };

    window.deleteSticker=async function(id){
      if(!confirm('確定刪除這張貼紙？'))return;
      try{
        await apiJson('/api/admin/delete_sticker',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})});
        assetsData.stickers=allStickers().filter(s=>String(s.id)!==String(id));selected.delete(String(id));renderAssets();
      }catch(e){alert(e.message||'刪除失敗')}
    };
  }

  function boot(){ensureUi();installRenderOverrides();installFastUpload();if(document.getElementById('view-assets')?.classList.contains('active')){renderAssetTabs();renderAssets()}console.info('[ADMIN] fast sticker library enabled: paged render + add/rename/delete categories')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();