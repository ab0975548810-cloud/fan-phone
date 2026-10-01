(function(){
  'use strict';
  if(window.__benfuwanAdminShellV1)return;
  window.__benfuwanAdminShellV1=true;

  const mobile=window.matchMedia('(max-width:600px)');
  const body=document.body;
  const top=document.querySelector('.top');
  const nav=document.querySelector('.nav');
  const sidebar=document.getElementById('admin-sidebar');
  const menuToggle=document.getElementById('admin-menu-toggle');
  const menuClose=document.getElementById('admin-nav-close');
  const backdrop=document.getElementById('admin-nav-backdrop');
  const actionsToggle=document.getElementById('admin-actions-toggle');
  const title=document.getElementById('admin-workspace-title');
  if(!body||!top||!nav||!sidebar||!menuToggle||!title)return;

  const labels={orders:'訂單管理',commerce:'商品與營運','print-center':'列印中心',models:'品牌及型號',styles:'手機殼材質',assets:'素材庫',templates:'模板庫',security:'登入安全'};
  let returnFocus=null;

  function syncTitle(){
    const active=nav.querySelector('button.active[data-view]');
    const view=active?.dataset.view||'orders';
    title.textContent=labels[view]||active?.textContent?.trim()||'訂單管理';
    nav.querySelectorAll('button[data-view]').forEach(button=>{
      if(button===active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
    });
  }
  function closeActions(){top.classList.remove('admin-actions-open');actionsToggle?.setAttribute('aria-expanded','false')}
  function closeMenu(restore=false){
    body.classList.remove('admin-nav-open');
    menuToggle.setAttribute('aria-expanded','false');
    if(mobile.matches)sidebar.setAttribute('aria-hidden','true');else sidebar.removeAttribute('aria-hidden');
    if(restore&&returnFocus?.isConnected)returnFocus.focus();
    returnFocus=null;
  }
  function openMenu(){
    if(!mobile.matches)return;
    window.BenfuwanStewardV1?.close?.();
    closeActions();
    returnFocus=document.activeElement;
    body.classList.add('admin-nav-open');
    menuToggle.setAttribute('aria-expanded','true');
    sidebar.removeAttribute('aria-hidden');
    (nav.querySelector('button.active')||nav.querySelector('button'))?.focus();
  }
  function toggleActions(){
    const open=!top.classList.contains('admin-actions-open');
    if(open)closeMenu(false);
    top.classList.toggle('admin-actions-open',open);
    actionsToggle?.setAttribute('aria-expanded',String(open));
  }

  menuToggle.addEventListener('click',openMenu);
  menuClose?.addEventListener('click',()=>closeMenu(true));
  backdrop?.addEventListener('click',()=>closeMenu(true));
  actionsToggle?.addEventListener('click',event=>{event.stopPropagation();toggleActions()});
  nav.addEventListener('click',event=>{
    if(!event.target.closest('button[data-view]'))return;
    requestAnimationFrame(syncTitle);
    if(mobile.matches)closeMenu(true);
  });
  document.addEventListener('click',event=>{if(!top.contains(event.target))closeActions()});
  document.addEventListener('keydown',event=>{
    if(event.key!=='Escape')return;
    if(body.classList.contains('admin-nav-open')){closeMenu(true);return}
    closeActions();
  });
  const resize=()=>{closeActions();closeMenu(false)};
  mobile.addEventListener?.('change',resize);
  window.addEventListener('resize',resize,{passive:true});
  new MutationObserver(syncTitle).observe(nav,{subtree:true,childList:true,attributes:true,attributeFilter:['class']});
  syncTitle();
  closeMenu(false);

  window.BenfuwanAdminShellV1={openMenu,closeMenu,closeActions,syncTitle,isMobile:()=>mobile.matches};
})();
