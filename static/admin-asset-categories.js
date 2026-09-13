/* 本福丸後台：貼紙分類管理（新增 / 改名 / 批量移動） */
(function(){
  'use strict';
  if(window.__benfuwanAssetCategoriesInstalled)return;
  window.__benfuwanAssetCategoriesInstalled=true;

  let batchMode=false;
  const selected=new Set();

  const h=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
  const cats=()=>Array.isArray(window.assetsData?.categories)?window.assetsData.categories:['全部'];
  const visibleList=()=>window.currentAsset==='全部'?(window.assetsData?.stickers||[]):(window.assetsData?.stickers||[]).filter(s=>s.category===window.currentAsset);

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
      #asset-grid .card.bf-selectable{cursor:pointer;transition:.12s ease}
      #asset-grid .card.bf-selected{border:2px solid var(--pink);background:#fff1f6;box-shadow:0 0 0 3px rgba(255,120,158,.08)}
      .bf-asset-check{position:absolute;left:8px;top:8px;width:28px;height:28px;border-radius:50%;display:grid;place-items:center;background:#fff;border:1px solid #efcad5;color:#bbb;box-shadow:0 2px 8px rgba(0,0,0,.08);z-index:2;font-size:12px}
      .bf-selected .bf-asset-check{background:var(--pink);border-color:var(--pink);color:#fff}
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
      const batch=document.createElement('button');batch.id='bf-batch-cat-btn';batch.className='btn alt';batch.innerHTML='<i class="fa-solid fa-check-double"></i> 批量分類';batch.onclick=toggleBatch;
      if(oldUpload){oldUpload.remove();wrap.append(add,rename,batch,oldUpload)}else wrap.append(add,rename,batch);
      title.appendChild(wrap);
    }
    const panel=view.querySelector('.panel');
    if(panel&&!document.getElementById('asset-batchbar')){
      const bar=document.createElement('div');bar.id='asset-batchbar';
      bar.innerHTML='<span class="count" id="bf-asset-count">已選 0 張</span><button class="btn alt mini" id="bf-select-visible">全選目前分類</button><input id="bf-target-category" list="bf-category-list" placeholder="輸入分類，例如：貓咪"><datalist id="bf-category-list"></datalist><button class="btn mini" id="bf-move-assets">移到分類</button><button class="btn danger mini" id="bf-cancel-batch">取消</button>';
      panel.insertBefore(bar,panel.firstChild);
      document.getElementById('bf-select-visible').onclick=selectVisible;
      document.getElementById('bf-move-assets').onclick=moveSelected;
      document.getElementById('bf-cancel-batch').onclick=()=>{batchMode=false;selected.clear();syncBatchUi();window.renderAssets?.()};
    }
    refreshDatalist();syncBatchUi();
  }

  function refreshDatalist(){
    const dl=document.getElementById('bf-category-list');if(!dl)return;
    dl.innerHTML=cats().filter(c=>c&&c!=='全部').map(c=>`<option value="${h(c)}"></option>`).join('');
  }

  function syncBatchUi(){
    const bar=document.getElementById('asset-batchbar'),btn=document.getElementById('bf-batch-cat-btn'),count=document.getElementById('bf-asset-count');
    bar?.classList.toggle('show',batchMode);
    if(btn){btn.classList.toggle('btn',true);btn.innerHTML=batchMode?'<i class="fa-solid fa-xmark"></i> 結束選取':'<i class="fa-solid fa-check-double"></i> 批量分類'}
    if(count)count.textContent=`已選 ${selected.size} 張`;
  }

  function toggleBatch(){batchMode=!batchMode;selected.clear();syncBatchUi();window.renderAssets?.()}
  function toggleOne(id){if(selected.has(id))selected.delete(id);else selected.add(id);syncBatchUi();window.renderAssets?.()}
  function selectVisible(){
    const ids=visibleList().map(s=>String(s.id));
    const all=ids.length&&ids.every(id=>selected.has(id));
    ids.forEach(id=>all?selected.delete(id):selected.add(id));
    syncBatchUi();window.renderAssets?.();
  }

  async function api(body){return window.apiJson('/api/admin/sticker_category',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})}

  async function createCategory(){
    const name=(prompt('新增貼紙分類名稱，例如：貓咪','')||'').trim();if(!name)return;
    try{await api({action:'create',name});await window.loadAssets(true);window.currentAsset=name;window.renderAssetTabs();window.renderAssets();refreshDatalist()}
    catch(e){alert(e.message||'新增分類失敗')}
  }

  async function renameCategory(){
    const old=window.currentAsset;
    if(!old||old==='全部')return alert('請先點進要改名的分類，例如「可愛」');
    const name=(prompt(`把「${old}」改成：`,old)||'').trim();if(!name||name===old)return;
    try{const r=await api({action:'rename',old,new:name});await window.loadAssets(true);window.currentAsset=name;window.renderAssetTabs();window.renderAssets();refreshDatalist();alert(`分類已改成「${name}」，共整理 ${r.moved||0} 張貼紙`)}
    catch(e){alert(e.message||'分類改名失敗')}
  }

  async function moveSelected(){
    if(!selected.size)return alert('請先選擇貼紙');
    const input=document.getElementById('bf-target-category');
    const name=(input?.value||'').trim();if(!name)return alert('請輸入要移到的分類，例如：貓咪');
    try{const r=await api({action:'move',name,ids:[...selected]});await window.loadAssets(true);selected.clear();batchMode=false;window.currentAsset=name;window.renderAssetTabs();window.renderAssets();refreshDatalist();syncBatchUi();if(input)input.value='';alert(`完成，${r.moved||0} 張貼紙已移到「${name}」`)}
    catch(e){alert(e.message||'批量分類失敗')}
  }

  function installRenderOverride(){
    window.renderAssets=function(){
      ensureUi();
      const list=visibleList(),box=document.getElementById('asset-grid');if(!box)return;
      box.className='grid';box.innerHTML='';
      if(!list.length){box.innerHTML='<div class="empty">這個分類目前沒有素材</div>';return}
      list.forEach(s=>{
        const id=String(s.id||'');
        const card=document.createElement('div');card.className='card'+(batchMode?' bf-selectable':'')+(selected.has(id)?' bf-selected':'');
        if(batchMode){
          const check=document.createElement('span');check.className='bf-asset-check';check.innerHTML=selected.has(id)?'<i class="fa-solid fa-check"></i>':'';card.appendChild(check);
          card.onclick=e=>{if(e.target.closest('.del'))return;toggleOne(id)};
        }
        const del=document.createElement('button');del.className='del';del.textContent='×';del.onclick=e=>{e.stopPropagation();window.deleteSticker(id)};card.appendChild(del);
        const img=document.createElement('img');img.loading='lazy';img.src=s.url||'';img.alt='';card.appendChild(img);
        box.appendChild(card);
      });
      syncBatchUi();
    };
  }

  function boot(){ensureUi();installRenderOverride();if(document.getElementById('view-assets')?.classList.contains('active'))window.renderAssets?.();console.info('[ADMIN] sticker categories enabled: create / rename / batch move')}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
