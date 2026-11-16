/* Local image assets share the existing asset store and guarded Preview workflow. */
(function(host){
  'use strict';
  const IMAGE=/^image:([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$/;
  const LIMIT=8*1024*1024;
  function imageId(value){return typeof value==='string'&&IMAGE.exec(value)?.[1]||null;}
  function imageUrl(value){const id=imageId(value);return id?'/api/creator/assets/'+id:null;}
  function fileType(file){
    const known={'image/png':1,'image/jpeg':1,'image/webp':1,'image/gif':1};
    const type=String(file?.type||'').toLowerCase();
    if(type)return known[type]?type:null;
    return ({png:'image/png',jpg:'image/jpeg',jpeg:'image/jpeg',webp:'image/webp',gif:'image/gif'})[String(file?.name||'').split('.').pop().toLowerCase()]||null;
  }
  function uploadProblem(file){return !file||!fileType(file)?'Choose a PNG, JPEG, WebP or GIF image.':!file.size?'This image is empty. Choose another file.':file.size>LIMIT?'Images must be 8 MB or smaller.':null;}
  function mount({after,catalog=()=>[],selected=()=>[],busy=()=>false,select=()=>{},refresh=async()=>{},fetch:request=(...args)=>host.fetch(...args),document=after?.ownerDocument||host.document}={}){
    if(!after||!document)return null;
    const section=document.createElement('section');section.className='production-image-library';section.setAttribute('aria-label','Image sources');
    section.innerHTML='<div class="production-image-heading"><strong>Images</strong><button class="riq-button" type="button" data-image-import>Add image</button><input type="file" accept="image/png,image/jpeg,image/webp,image/gif,.png,.jpg,.jpeg,.webp,.gif" aria-label="Choose a production image" hidden></div><p class="production-image-feedback" role="status" aria-live="polite">Import a local image, add it to Preview, then Take when Studio Output is ready. PNG, JPEG, WebP or GIF · up to 8 MB.</p><div class="production-image-list" aria-label="Saved image sources"></div>';
    after.after(section);
    const button=section.querySelector('[data-image-import]'),input=section.querySelector('input'),feedback=section.querySelector('[role="status"]'),list=section.querySelector('.production-image-list'),entries=new Map();
    let uploading=false,closed=false;
    const note=text=>{feedback.textContent=text;};
    function render(){
      if(closed)return;
      button.disabled=uploading||busy();button.textContent=uploading?'Importing…':'Add image';button.setAttribute('aria-busy',String(uploading));button.title=button.disabled?'Wait for the current change to finish.':'Import an image saved on this computer.';
      const assets=catalog().filter(asset=>imageId(asset.id)),ids=new Set(assets.map(asset=>asset.id)),chosen=new Set(selected());
      for(const [id,entry] of entries)if(!ids.has(id)){entry.button.remove();entries.delete(id);}
      for(const asset of assets){
        let entry=entries.get(asset.id);
        if(!entry){
          const item=document.createElement('button'),image=document.createElement('img'),label=document.createElement('span'),state=document.createElement('small');
          item.type='button';item.className='production-image-item';image.alt='';image.loading='lazy';image.src=imageUrl(asset.id);item.append(image,label,state);entry={button:item,image,label,state,failed:false};entries.set(asset.id,entry);list.append(item);
          image.addEventListener('error',()=>{if(!closed){entry.failed=true;render();}});
          item.addEventListener('click',()=>{if(!uploading&&!busy()&&(!entry.failed||selected().includes(asset.id)))select(asset.id);});
        }
        const active=chosen.has(asset.id);entry.label.textContent=String(asset.name||'Image').slice(0,60);entry.state.textContent=entry.failed?'Image unavailable':active?'In Preview':'Add to Preview';entry.button.setAttribute('aria-pressed',String(active));entry.button.disabled=uploading||busy()||entry.failed&&!active;
        entry.button.title=entry.failed?'This image could not load. Import a valid image to replace it.':active?'Remove this image from Preview.':'Add this image to Preview. Program is unchanged.';
      }
      list.hidden=!assets.length;
    }
    async function upload(file){
      if(closed||uploading||busy())return;
      const problem=uploadProblem(file);if(problem){note(problem);input.value='';return;}
      uploading=true;render();note('Importing image…');
      try{
        const name=String(file.name||'image').replace(/[^A-Za-z0-9._-]/g,'_').slice(0,100);
        const response=await request('/api/creator/assets',{method:'POST',headers:{'Content-Type':fileType(file),'X-RareIQ-Filename':name},body:file});
        const result=await response.json();
        if(!response.ok||!result.created)throw Error(result.reason||'image_import_failed');
        await refresh(true);if(closed)return;
        note('Image saved. Choose it below to add it to Preview. Program is unchanged.');
      }catch(error){
        if(!closed){await refresh(true);note(({file_signature_mismatch:'This file is not a supported image. Choose another file.',asset_too_large:'Images must be 8 MB or smaller.',asset_storage_unavailable:'The image could not be saved. Check local storage and retry.'})[error.message]||'Import could not be confirmed. Check the image library before trying again.');}
      }finally{uploading=false;input.value='';render();}
    }
    button.addEventListener('click',()=>{if(!uploading&&!busy())input.click();});input.addEventListener('change',()=>{if(input.files?.[0])upload(input.files[0]);});render();
    return {render,upload,close(){closed=true;section.remove();}};
  }
  const exported={mount,imageId,imageUrl,fileType,uploadProblem};
  if(typeof module==='object'&&module.exports)module.exports=exported;else host.ProducerImageLibrary=exported;
})(typeof window==='undefined'?globalThis:window);
