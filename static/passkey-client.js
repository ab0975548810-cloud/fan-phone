(function(){
  'use strict';

  function fromBase64url(value){
    const base=String(value||'').replace(/-/g,'+').replace(/_/g,'/');
    const padded=base+'='.repeat((4-base.length%4)%4),raw=atob(padded),out=new Uint8Array(raw.length);
    for(let i=0;i<raw.length;i++)out[i]=raw.charCodeAt(i);
    return out.buffer;
  }
  function toBase64url(value){
    if(value===null||value===undefined)return null;
    const bytes=new Uint8Array(value);let raw='';for(const byte of bytes)raw+=String.fromCharCode(byte);
    return btoa(raw).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  }
  function publicKeyOptions(raw){
    const out=structuredClone(raw||{});out.challenge=fromBase64url(out.challenge);
    if(out.user?.id)out.user.id=fromBase64url(out.user.id);
    for(const key of ['allowCredentials','excludeCredentials'])if(Array.isArray(out[key]))out[key]=out[key].map(item=>({...item,id:fromBase64url(item.id)}));
    return out;
  }
  function credentialJSON(credential){
    const response=credential.response||{},out={
      id:credential.id,rawId:toBase64url(credential.rawId),type:credential.type,
      authenticatorAttachment:credential.authenticatorAttachment||null,
      clientExtensionResults:credential.getClientExtensionResults?.()||{},response:{clientDataJSON:toBase64url(response.clientDataJSON)}
    };
    if(response.attestationObject){out.response.attestationObject=toBase64url(response.attestationObject);out.response.transports=response.getTransports?.()||[]}
    if(response.authenticatorData){out.response.authenticatorData=toBase64url(response.authenticatorData);out.response.signature=toBase64url(response.signature);out.response.userHandle=toBase64url(response.userHandle)}
    return out;
  }
  async function api(url,options={}){
    const response=await fetch(url,{...options,headers:{'Content-Type':'application/json',...(options.headers||{})},cache:'no-store'});
    let body={};try{body=await response.json()}catch(e){}
    if(!response.ok||body.status==='error'){const error=new Error(body.msg||'操作失敗，請稍後再試。');error.code=body.code||'';error.status=response.status;throw error}
    return body;
  }
  function supported(){return !!(window.PublicKeyCredential&&navigator.credentials&&typeof navigator.credentials.get==='function'&&typeof navigator.credentials.create==='function')}

  async function authenticate(){
    const options=await api('/api/auth/passkey/options',{method:'POST',body:'{}'});
    const credential=await navigator.credentials.get({publicKey:publicKeyOptions(options.publicKey)});
    if(!credential)throw new Error('未取得 Passkey 驗證結果。');
    return api('/api/auth/passkey/verify',{method:'POST',body:JSON.stringify({ceremony_id:options.ceremony_id,credential:credentialJSON(credential)})});
  }
  async function register(deviceLabel){
    const options=await api('/api/admin/passkey/register/options',{method:'POST',body:'{}'});
    const credential=await navigator.credentials.create({publicKey:publicKeyOptions(options.publicKey)});
    if(!credential)throw new Error('未取得 Passkey 設定結果。');
    return api('/api/admin/passkey/register/verify',{method:'POST',body:JSON.stringify({ceremony_id:options.ceremony_id,device_label:deviceLabel||'Face ID / Passkey',credential:credentialJSON(credential)})});
  }

  function showPassword(){
    const form=document.getElementById('password-form'),toggle=document.getElementById('password-toggle');
    form?.classList.add('show');toggle?.setAttribute('aria-expanded','true');form?.querySelector('input')?.focus();
  }
  async function bootLogin(){
    const button=document.getElementById('passkey-login-button'),message=document.getElementById('login-message'),toggle=document.getElementById('password-toggle');
    if(!button)return;
    toggle?.addEventListener('click',showPassword);
    if(!supported()){
      button.classList.add('hidden');toggle?.classList.add('hidden');showPassword();
      if(message)message.textContent='此瀏覽器不支援 Face ID / Passkey，請使用密碼登入。';
      return;
    }
    try{
      const status=await api('/api/auth/passkey/status',{headers:{}});
      if(!status.configured){button.classList.add('hidden');showPassword();if(message)message.textContent='Face ID 登入尚未完成伺服器設定，請使用密碼登入。';return}
      if(!status.has_credentials&&message)message.textContent='此裝置尚未設定 Face ID 登入，請先使用密碼登入後到後台啟用。';
    }catch(error){button.classList.add('hidden');showPassword();if(message){message.textContent=error.message;message.classList.add('error')}return}
    button.addEventListener('click',async()=>{
      button.disabled=true;if(message){message.textContent='請完成系統顯示的 Face ID 驗證。';message.classList.remove('error')}
      try{const result=await authenticate();location.assign(result.redirect||'/admin')}
      catch(error){
        if(error?.name==='NotAllowedError'){if(message)message.textContent='已取消 Face ID 驗證，可再次點擊或改用密碼登入。'}
        else{if(message){message.textContent=error.message||'Face ID 驗證失敗，請改用密碼登入。';message.classList.add('error')}if(error.code==='PASSKEY_NOT_REGISTERED')showPassword()}
      }finally{button.disabled=false}
    });
  }

  function formatDate(value){if(!value)return '尚未使用';try{return new Intl.DateTimeFormat('zh-TW',{dateStyle:'medium',timeStyle:'short'}).format(new Date(value))}catch(e){return String(value)}}
  async function loadAdminPasskeys(){
    const status=document.getElementById('passkey-admin-status'),list=document.getElementById('passkey-list'),enable=document.getElementById('passkey-enable');
    if(!status||!list||!enable)return;
    try{
      const data=await api('/api/admin/passkeys',{headers:{}});list.innerHTML='';
      if(!data.configured){status.textContent='伺服器尚未設定 Passkey 環境變數；密碼登入仍可正常使用。';enable.disabled=true;return}
      if(!supported()){status.textContent='此瀏覽器不支援 Passkey，請改用支援 Face ID 的 Safari。';enable.disabled=true;return}
      enable.disabled=false;const credentials=data.credentials||[];status.textContent=credentials.length?`已啟用 ${credentials.length} 個 Passkey。`:'尚未啟用 Face ID / Passkey。';
      if(!credentials.length){list.innerHTML='<div class="empty">登入後在支援 Face ID 的裝置按下方按鈕即可啟用。</div>';return}
      for(const item of credentials){
        const row=document.createElement('div');row.className='passkey-item';
        const info=document.createElement('div'),title=document.createElement('b'),meta=document.createElement('small'),remove=document.createElement('button');
        title.textContent=item.device_label||'Passkey';meta.textContent=`建立：${formatDate(item.created_at)}｜最後使用：${formatDate(item.last_used_at)}`;info.append(title,meta);
        remove.type='button';remove.className='btn danger mini';remove.textContent='移除';remove.addEventListener('click',async()=>{if(!confirm(`確定移除「${title.textContent}」？密碼登入仍會保留。`))return;remove.disabled=true;try{await api('/api/admin/passkeys/revoke',{method:'POST',body:JSON.stringify({credential_id:item.credential_id})});await loadAdminPasskeys()}catch(error){alert(error.message)}finally{remove.disabled=false}});
        row.append(info,remove);list.appendChild(row);
      }
    }catch(error){status.textContent=error.message;status.classList.add('bad');enable.disabled=true}
  }
  async function enableAdminPasskey(){
    const button=document.getElementById('passkey-enable'),status=document.getElementById('passkey-admin-status');if(!button)return;
    button.disabled=true;if(status){status.textContent='請完成系統顯示的 Face ID / Passkey 設定。';status.classList.remove('bad')}
    try{await register(/iPhone|iPad/i.test(navigator.userAgent)?'Apple 裝置 Face ID':'這台裝置的 Passkey');await loadAdminPasskeys()}
    catch(error){if(status){status.textContent=error?.name==='NotAllowedError'?'已取消設定，可隨時再次啟用。':(error.message||'Passkey 設定失敗，請稍後再試。');status.classList.add('bad')}}
    finally{button.disabled=false}
  }

  window.BenfuwanPasskeys={supported,authenticate,register,loadAdminPasskeys,enableAdminPasskey};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bootLogin,{once:true});else bootLogin();
})();
