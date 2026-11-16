/* Persistent local video and immutable text sources; imports never change either bus. */
(function(host){
  'use strict';
  const SOURCE=/^(video|text):([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$/;
  const LIMIT=64*1024*1024;
  function sourceId(value){return typeof value==='string'&&SOURCE.test(value)?value:null;}
  function fileType(file){const type=String(file?.type||'').toLowerCase();return type?['video/mp4','video/webm'].includes(type)?type:null:({mp4:'video/mp4',webm:'video/webm'})[String(file?.name||'').split('.').pop().toLowerCase()]||null;}
  function uploadProblem(file){return !fileType(file)?'Choose an MP4 or WebM video.':!file.size?'This video is empty. Choose another file.':file.size>LIMIT?'Videos must be 64 MB or smaller.':null;}
  function textProblem(value){return !String(value?.name||'').trim()?'Give this text source a name.':String(value.name).trim().length>60?'Source names must be 60 characters or shorter.':!String(value?.text||'').trim()?'Enter the text to show on Program.':String(value.text).length>1000?'Text must be 1,000 characters or shorter.':String(value.text).split(/\r\n|\r|\n/).length>8?'Text must be 8 lines or fewer.':!['lower-third','center','top'].includes(value.position)?'Choose a text position.':null;}
  function receipt(){const bytes=new Uint8Array(20);host.crypto.getRandomValues(bytes);return Array.from(bytes,value=>value.toString(16).padStart(2,'0')).join('');}
  function mount({after,catalog=()=>[],selected=()=>[],busy=()=>false,select=()=>{},refresh=async()=>{},fetch:request=(...args)=>host.fetch(...args),document=after?.ownerDocument||host.document}={}){
    if(!after||!document)return null;
    const section=document.createElement('section');section.className='production-media-library';section.setAttribute('aria-label','Video and text sources');
    section.innerHTML='<div class="production-media-heading"><strong>Video &amp; text</strong><div><button class="riq-button" type="button" data-video-import>Add video</button><button class="riq-button" type="button" data-text-open aria-expanded="false">Add text</button><input type="file" accept="video/mp4,video/webm,.mp4,.webm" aria-label="Choose a production video" hidden></div></div><p class="production-media-guidance">MP4 or WebM · up to 64 MB. Preview pauses silently on the first frame. Take plays once from the beginning, with sound only in Studio Output. If sound is blocked, choose Enable output sound there. Text overlays the selected pictures.</p><form class="production-text-form" hidden><label><span>Source name</span><input name="name" maxlength="60" required placeholder="Opening title"></label><label><span>Text on screen · up to 1,000 characters and 8 lines</span><textarea name="text" maxlength="1000" rows="3" required placeholder="Welcome to the show"></textarea></label><label><span>Position</span><select name="position"><option value="lower-third">Lower third</option><option value="center">Center</option><option value="top">Top</option></select></label><div class="production-text-actions"><button class="riq-button primary" type="submit">Save text source</button><button class="riq-button" type="button" data-text-cancel>Cancel</button></div><p>Saving creates a new source. Choose it below to add it to Preview; Program stays unchanged.</p></form><p class="production-media-feedback" role="status" aria-live="polite">Add a video or text source, choose it for Preview, then Take when Studio Output is ready.</p><div class="production-media-list" aria-label="Saved video and text sources"></div>';
    after.after(section);
    const one=selector=>section.querySelector(selector),videoButton=one('[data-video-import]'),fileInput=one('input[type="file"]'),textButton=one('[data-text-open]'),form=one('form'),feedback=one('[role="status"]'),list=one('.production-media-list'),entries=new Map(),pending=new Map();
    let saving=false,closed=false,controller=null;
    const note=value=>{feedback.textContent=value;};
    function render(){
      if(closed)return;
      const locked=saving||busy();for(const control of [videoButton,textButton,...form.querySelectorAll('input,textarea,select,button')]){control.disabled=locked;control.title=locked?'Wait for the current change to finish.':'';}
      section.setAttribute('aria-busy',String(saving));
      const assets=catalog().filter(asset=>sourceId(asset.id)),ids=new Set(assets.map(asset=>asset.id)),chosen=new Set(selected());
      for(const [id,entry] of entries)if(!ids.has(id)){entry.button.remove();entries.delete(id);}
      for(const asset of assets){
        let entry=entries.get(asset.id);if(!entry){const button=document.createElement('button'),label=document.createElement('span'),state=document.createElement('small');button.type='button';button.className='production-media-item';button.append(label,state);entry={button,label,state};entries.set(asset.id,entry);list.append(button);button.addEventListener('click',()=>{if(!saving&&!busy())select(asset.id);});}
        const active=chosen.has(asset.id);entry.label.textContent=String(asset.name||'Source').slice(0,60);entry.state.textContent=(asset.id.startsWith('video:')?'Video':'Text')+' · '+(active?'In Preview':'Add to Preview');entry.button.setAttribute('aria-pressed',String(active));entry.button.disabled=locked;entry.button.title=locked?'Wait for the current change to finish.':active?'Remove this source from Preview.':'Add this source to Preview. Program is unchanged.';
      }
      list.hidden=!assets.length;
    }
    async function save(key,path,options){
      const id=pending.get(key)||receipt();pending.set(key,id);controller=new host.AbortController();const timer=host.setTimeout(()=>controller?.abort(),45000);
      try{
        const response=await request(path,{credentials:'same-origin',...options,headers:{...options.headers,'X-RareIQ-Request-Id':id},body:typeof options.body==='string'?JSON.stringify({...JSON.parse(options.body),request_id:id}):options.body,signal:controller.signal});
        const result=await response.json();if(!response.ok||result.ok===false){if(response.status<500)pending.delete(key);throw Error(result.reason||'source_save_failed');}
        if(!result.created&&!result.replayed)throw Error('source_save_unconfirmed');pending.delete(key);return result;
      }finally{host.clearTimeout(timer);controller=null;}
    }
    async function updateCatalog(){try{await refresh(true);}catch(_){/* Keep the saved/uncertain result visible even if the catalog refresh fails. */}}
    async function upload(file){
      if(closed||saving||busy())return;const problem=uploadProblem(file);if(problem){note(problem);fileInput.value='';return;}
      saving=true;render();note('Importing video…');
      try{await save('video:'+JSON.stringify([file.name,file.size,file.lastModified]),'/api/creator/assets',{method:'POST',headers:{'Content-Type':fileType(file),'X-RareIQ-Filename':String(file.name||'video').replace(/[^A-Za-z0-9._-]/g,'_').slice(0,100)},body:file});await updateCatalog();if(!closed)note('Video saved. Choose it below for Preview. A supported browser codec is required; Program is unchanged.');}
      catch(error){await updateCatalog();if(!closed)note(({file_signature_mismatch:'This file is not a supported video. Choose another MP4 or WebM.',asset_too_large:'Videos must be 64 MB or smaller.',asset_storage_unavailable:'The video could not be saved. Check local storage and retry.'})[error.message]||'Import could not be confirmed. Check the library, then retry the same file if it is missing.');}
      finally{saving=false;fileInput.value='';render();}
    }
    function showForm(show){form.hidden=!show;textButton.setAttribute('aria-expanded',String(show));if(show)one('[name="name"]').focus();else textButton.focus();}
    async function saveText(value){
      if(closed||saving||busy())return;const problem=textProblem(value);if(problem){note(problem);return;}
      const draft={name:value.name.trim(),text:value.text,position:value.position};saving=true;render();note('Saving text source…');
      try{await save('text:'+JSON.stringify(draft),'/api/production/sources/text',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(draft)});await updateCatalog();if(!closed){form.reset();showForm(false);note('Text source saved. Choose it below for Preview. Program is unchanged.');}}
      catch(_){await updateCatalog();if(!closed)note('Save could not be confirmed. Your draft is kept; check the library, then retry if it is missing.');}
      finally{saving=false;render();}
    }
    videoButton.addEventListener('click',()=>{if(!saving&&!busy())fileInput.click();});fileInput.addEventListener('change',()=>{if(fileInput.files?.[0])upload(fileInput.files[0]);});textButton.addEventListener('click',()=>showForm(form.hidden));one('[data-text-cancel]').addEventListener('click',()=>showForm(false));
    form.addEventListener('submit',event=>{event.preventDefault();saveText({name:one('[name="name"]').value,text:one('[name="text"]').value,position:one('[name="position"]').value});});render();
    return {render,upload,saveText,close(){closed=true;controller?.abort();section.remove();}};
  }
  const exported={mount,sourceId,fileType,uploadProblem,textProblem};if(typeof module==='object'&&module.exports)module.exports=exported;else host.ProducerMediaLibrary=exported;
})(typeof window==='undefined'?globalThis:window);
