/* Saved browser sources join Preview only after an explicit source selection. */
(function(host){
  'use strict';
  const SOURCE=/^browser:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
  function sourceId(value){return typeof value==='string'&&SOURCE.test(value)?value:null;}
  function browserProblem(value,origin=host.location?.origin){
    if(!String(value?.name||'').trim())return 'Give this browser source a name.';
    if(String(value.name).trim().length>60)return 'Source names must be 60 characters or shorter.';
    if(!host.ProducerBrowserSource?.validatedUrl)return 'Browser sources are unavailable. Reload Studio and try again.';
    try{host.ProducerBrowserSource.validatedUrl(String(value.target_url||'').trim(),origin);return null;}
    catch(_){return 'Enter a public HTTPS website address without a password, a custom port, or a local Studio address.';}
  }
  function receipt(){const bytes=new Uint8Array(20);host.crypto.getRandomValues(bytes);return Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');}
  function mount({after,catalog=()=>[],selected=()=>[],busy=()=>false,select=()=>{},refresh=async()=>{},fetch:request=(...args)=>host.fetch(...args),document=after?.ownerDocument||host.document}={}){
    if(!after||!document)return null;
    const section=document.createElement('section');section.className='production-browser-library';section.setAttribute('aria-label','Browser sources');
    section.innerHTML='<div class="production-browser-heading"><strong>Browser sources</strong><button class="riq-button" type="button" data-browser-open aria-expanded="false">Add browser</button></div><p class="production-browser-guidance">Add a public HTTPS page, choose it for Preview, then review the actual picture in every connected Studio Output before Take. Some sites block embedding. Browser audio and interaction are unavailable.</p><a class="riq-button production-browser-review" href="/output/studio?browser-review=1" target="_blank" rel="noopener noreferrer">Review in Studio Output</a><form class="production-browser-form" hidden><label><span>Source name</span><input name="name" maxlength="60" required placeholder="Scoreboard"></label><label><span>Public HTTPS address</span><input name="target_url" type="url" maxlength="2048" required placeholder="https://example.com/overlay" autocomplete="off" spellcheck="false"></label><div class="production-browser-actions"><button class="riq-button primary" type="submit">Save browser source</button><button class="riq-button" type="button" data-browser-cancel>Cancel</button></div><p>Saving creates a new source and leaves Program unchanged.</p></form><p class="production-browser-feedback" role="status" aria-live="polite">Browser sources require a visual review in Studio Output before they can be taken.</p><div class="production-browser-list" aria-label="Saved browser sources"></div>';
    after.after(section);
    const one=selector=>section.querySelector(selector),openButton=one('[data-browser-open]'),form=one('form'),feedback=one('[role="status"]'),list=one('.production-browser-list'),entries=new Map(),pending=new Map();
    let saving=false,closed=false,controller=null;
    const note=text=>{feedback.textContent=text;};
    function render(){
      if(closed)return;
      const locked=saving||busy(),unavailable=!host.ProducerBrowserSource?.validatedUrl;
      for(const control of [openButton,...form.querySelectorAll('input,button')]){control.disabled=locked||unavailable;control.title=unavailable?'Browser sources are unavailable. Reload Studio and try again.':locked?'Wait for the current change to finish.':'';}
      section.setAttribute('aria-busy',String(saving));
      const assets=catalog().filter(asset=>sourceId(asset.id)),ids=new Set(assets.map(asset=>asset.id)),chosen=new Set(selected());
      for(const [id,entry] of entries)if(!ids.has(id)){entry.button.remove();entries.delete(id);}
      for(const asset of assets){
        let entry=entries.get(asset.id);if(!entry){const button=document.createElement('button'),label=document.createElement('span'),state=document.createElement('small');button.type='button';button.className='production-browser-item';button.append(label,state);entry={button,label,state};entries.set(asset.id,entry);list.append(button);button.addEventListener('click',()=>{if(!saving&&!busy())select(asset.id);});}
        const active=chosen.has(asset.id);entry.label.textContent=String(asset.name||'Browser source').slice(0,60);entry.state.textContent=active?'In Preview · review in Output':'Add to Preview';entry.button.setAttribute('aria-pressed',String(active));entry.button.disabled=locked;entry.button.title=locked?'Wait for the current change to finish.':active?'Remove this browser source from Preview.':'Add to Preview, then review in every connected Studio Output. Program is unchanged.';
      }
      list.hidden=!assets.length;
    }
    function showForm(show){form.hidden=!show;openButton.setAttribute('aria-expanded',String(show));if(show)one('[name="name"]').focus();else openButton.focus();}
    async function updateCatalog(){if(closed)return;try{await refresh(true);}catch(_){/* Keep a saved result or uncertain retry visible when refresh fails. */}}
    async function saveBrowser(value){
      if(closed||saving||busy())return;const problem=browserProblem(value);if(problem){note(problem);return;}
      const draft={name:value.name.trim(),target_url:host.ProducerBrowserSource.validatedUrl(value.target_url.trim(),host.location.origin)},key=JSON.stringify(draft);
      if(!pending.has(key)&&pending.size>=32){note('There are too many unconfirmed saves. Check the source library before adding another.');return;}
      const requestId=pending.get(key)||receipt();pending.set(key,requestId);saving=true;render();note('Saving browser source…');controller=new host.AbortController();const timer=host.setTimeout(()=>controller?.abort(),15000);
      try{
        const response=await request('/api/production/sources/browser',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({...draft,request_id:requestId}),signal:controller.signal});
        const result=await response.json();if(!response.ok||result.ok===false){if(response.status<500)pending.delete(key);throw Error('browser_save_failed');}
        if(!result.created&&!result.replayed)throw Error('browser_save_unconfirmed');pending.delete(key);await updateCatalog();if(!closed){form.reset();form.hidden=true;openButton.setAttribute('aria-expanded','false');note('Browser source saved. Choose it for Preview, then review its picture in every connected Studio Output. Program is unchanged.');}
      }catch(_){await updateCatalog();if(!closed)note('Save could not be confirmed. Your draft is kept. Check the library, then retry the same draft if it is missing.');}
      finally{host.clearTimeout(timer);controller=null;saving=false;render();if(!closed&&form.hidden)openButton.focus();}
    }
    openButton.addEventListener('click',()=>{if(!saving&&!busy())showForm(form.hidden);});one('[data-browser-cancel]').addEventListener('click',()=>showForm(false));form.addEventListener('submit',event=>{event.preventDefault();saveBrowser({name:one('[name="name"]').value,target_url:one('[name="target_url"]').value});});render();
    return {render,saveBrowser,close(){closed=true;controller?.abort();section.remove();}};
  }
  const exported={mount,sourceId,browserProblem};if(typeof module==='object'&&module.exports)module.exports=exported;else host.ProducerBrowserLibrary=exported;
})(typeof window==='undefined'?globalThis:window);
