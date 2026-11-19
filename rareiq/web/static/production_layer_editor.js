/* Local layer drafts. Only Apply changes authoritative Preview; Take stays separate. */
(function(host){
  'use strict';
  const SOURCE=/^(?:camera:[1-4]|producer:screen:[a-f0-9]{32}|guest:[a-f0-9]{32}:(?:camera|screen|audio)|(?:image|video|text|browser):[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})$/;
  const FIELDS=['x','y','width','height','opacity','z','locked','hidden','crop'],CROPS=['top','right','bottom','left'];
  const copy=value=>JSON.parse(JSON.stringify(value));
  const object=value=>Boolean(value&&typeof value==='object'&&!Array.isArray(value));
  const number=(value,min,max)=>typeof value==='number'&&Number.isFinite(value)&&value>=min&&value<=max;
  const quantize=value=>Math.round(value*1e6)/1e6;
  function defaults(index=0){return {x:0,y:0,width:1,height:1,crop:{top:0,right:0,bottom:0,left:0},opacity:1,z:index,locked:false,hidden:false};}
  function normalizeLayers(sources,value={}){
    if(!Array.isArray(sources)||sources.length>6||new Set(sources).size!==sources.length||sources.some(id=>!SOURCE.test(id))||!object(value))throw Error('invalid_layer_sources');
    const result={};
    for(const [index,id]of sources.entries()){
      const raw=Object.hasOwn(value,id)?value[id]:defaults(index);
      if(!object(raw)||Object.keys(raw).some(key=>!FIELDS.includes(key))||FIELDS.some(key=>!Object.hasOwn(raw,key))||
        !number(raw.x,0,1)||!number(raw.y,0,1)||!number(raw.width,.01,1)||!number(raw.height,.01,1)||!number(raw.opacity,0,1)||
        !Number.isInteger(raw.z)||raw.z<0||raw.z>100||typeof raw.locked!=='boolean'||typeof raw.hidden!=='boolean'||!object(raw.crop)||
        Object.keys(raw.crop).length!==4||CROPS.some(key=>!number(raw.crop[key],0,.95))||raw.crop.left+raw.crop.right>=1||raw.crop.top+raw.crop.bottom>=1)throw Error('invalid_layer_geometry');
      result[id]={x:quantize(raw.x),y:quantize(raw.y),width:quantize(raw.width),height:quantize(raw.height),crop:Object.fromEntries(CROPS.map(key=>[key,quantize(raw.crop[key])])),opacity:quantize(raw.opacity),z:raw.z,locked:raw.locked,hidden:raw.hidden};
      if(result[id].crop.left+result[id].crop.right>=1||result[id].crop.top+result[id].crop.bottom>=1)throw Error('invalid_layer_geometry');
    }
    return result;
  }
  function basis(state){
    const sources=Array.isArray(state?.preview_sources)?state.preview_sources.slice():state?.preview_slot?[`camera:${state.preview_slot}`]:[];
    return {sources,layout:state?.preview_layout||'auto',layers:state?.preview_layout==='custom'?normalizeLayers(sources,state.preview_layers||{}):{},compositionId:typeof state?.preview_composition_id==='string'&&/^[a-f0-9]{64}$/.test(state.preview_composition_id)?state.preview_composition_id:null,
      generation:Number.isSafeInteger(state?.generation)?state.generation:0,revision:Number.isSafeInteger(state?.preview_revision)?state.preview_revision:0};
  }
  const signature=value=>JSON.stringify(value);
  function createModel(){
    let base=null,draft={},selected=null,dirty=false,conflict=false,pending=null;
    const state=()=>({base:base?copy(base):null,layers:copy(draft),selected,dirty,conflict,pending:pending?copy(pending):null});
    return {
      state,
      observe(value,seed={}){
        const next=basis(value);
        if(base&&(next.generation<base.generation||next.generation===base.generation&&next.revision<base.revision))return state();
        if(pending&&next.layout==='custom'&&signature(next.sources)===signature(base.sources)&&signature(next.layers)===signature(draft)&&next.generation===base.generation){base=next;dirty=false;conflict=false;pending=null;return state();}
        if(base&&dirty){if(signature(next)!==signature(base))conflict=true;return state();}
        base=next;draft=normalizeLayers(next.sources,next.layout==='custom'?next.layers:seed);selected=next.sources.includes(selected)?selected:next.sources[0]||null;dirty=false;conflict=false;pending=null;return state();
      },
      select(id){if(!base?.sources.includes(id))throw Error('layer_not_selected');selected=id;return state();},
      edit(id,patch){
        if(!base?.sources.includes(id)||!object(patch))throw Error('layer_not_selected');
        if(draft[id].locked&&Object.keys(patch).some(key=>key!=='locked'))throw Error('layer_locked');
        const next=normalizeLayers(base.sources,{...draft,[id]:{...draft[id],...patch}});
        draft=next;dirty=true;pending=null;return state();
      },
      reset(id){if(draft[id]?.locked)throw Error('layer_locked');if(!base?.sources.includes(id))throw Error('layer_not_selected');draft[id]=defaults(base.sources.indexOf(id));dirty=true;pending=null;return state();},
      prepare(){
        if(!base||!base.sources.length)throw Error('layers_empty');if(conflict)throw Error('preview_revision_conflict');
        if(!pending)pending={preview_sources:base.sources.slice(),layout:'custom',layers:normalizeLayers(base.sources,draft),expected_generation:base.generation,expected_preview_revision:base.revision};
        return copy(pending);
      },
      accepted(value){const next=basis(value);if(next.layout!=='custom'||signature(next.sources)!==signature(base.sources)||signature(next.layers)!==signature(draft))throw Error('layer_apply_unconfirmed');base=next;dirty=false;conflict=false;pending=null;return state();},
      reload(value,seed={}){base=null;dirty=false;return this.observe(value,seed);},
    };
  }
  const clamp=(value,min=0,max=1)=>Math.max(min,Math.min(max,value));
  function moveLayer(layer,dx,dy,resize=false){return resize?{width:clamp(layer.width+dx,.01),height:clamp(layer.height+dy,.01)}:{x:clamp(layer.x+dx),y:clamp(layer.y+dy)};}
  function mount({after,read,apply,name=id=>id,mediaReceiver=null,room=()=>null,document:doc=host.document,busy=()=>false}={}){
    if(!after||typeof read!=='function'||typeof apply!=='function'||!doc)return null;
    const section=doc.createElement('details');section.className='production-layer-editor';
    section.innerHTML='<summary>Arrange layers <span>Position, crop and stack Preview pictures</span></summary><div class="production-layer-body"><p class="production-layer-intro">Edits stay in this draft until Apply to Preview. Use Take when the prepared picture is ready for Program.</p><div class="production-layer-stage" aria-label="Draft layer canvas"><div class="production-layer-picture"></div><div class="production-layer-hits" aria-label="Move layers with pointer or arrow keys"></div><span class="production-layer-draft-badge">DRAFT · PREVIEW ONLY</span></div><div class="production-layer-fields"><label class="production-layer-source"><span>Selected layer</span><select data-layer-source aria-label="Selected layer"></select></label><label><span>Left %</span><input data-layer-field="x" type="number" min="0" max="100" step="0.1"></label><label><span>Top %</span><input data-layer-field="y" type="number" min="0" max="100" step="0.1"></label><label><span>Width %</span><input data-layer-field="width" type="number" min="1" max="100" step="0.1"></label><label><span>Height %</span><input data-layer-field="height" type="number" min="1" max="100" step="0.1"></label><label><span>Opacity %</span><input data-layer-field="opacity" type="number" min="0" max="100" step="1"></label><label><span>Stack order</span><input data-layer-field="z" type="number" min="0" max="100" step="1"></label><fieldset class="production-layer-crops"><legend>Crop source edges %</legend><label>Top<input data-layer-crop="top" type="number" min="0" max="95" step="0.1"></label><label>Right<input data-layer-crop="right" type="number" min="0" max="95" step="0.1"></label><label>Bottom<input data-layer-crop="bottom" type="number" min="0" max="95" step="0.1"></label><label>Left<input data-layer-crop="left" type="number" min="0" max="95" step="0.1"></label></fieldset><label class="production-layer-check"><input data-layer-locked type="checkbox"> Lock edits</label><label class="production-layer-check"><input data-layer-hidden type="checkbox"> Hide picture</label></div><p class="production-layer-help">Arrow keys move the selected layer by 1%; hold Shift for 5%. Resize by dragging the corner or using Width/Height. Hide affects the picture only; use the audio mixer separately. A lock prevents edits and does not freeze the video.</p><div class="production-layer-actions"><button class="riq-button" type="button" data-layer-reset>Reset selected</button><button class="riq-button" type="button" data-layer-reload>Reload current Preview</button><button class="riq-button primary" type="button" data-layer-apply>Apply to Preview</button></div><p data-layer-status role="status" aria-live="polite"></p></div>';
    after.after(section);
    const sceneButton=doc.createElement('button');sceneButton.type='button';sceneButton.className='riq-button';sceneButton.dataset.layerSavePreview='';sceneButton.textContent='Create scene from Preview';section.querySelector('.production-layer-actions').append(sceneButton);
    const one=selector=>section.querySelector(selector),model=createModel(),hits=one('.production-layer-hits'),fields=[...section.querySelectorAll('[data-layer-field],[data-layer-crop]')];
    let closed=false,working=false,drag=null,message='Choose sources in Preview to arrange their layers.',view=null;
    const receiver={tracks:id=>typeof mediaReceiver==='function'?mediaReceiver()?.tracks?.(id)||{}:mediaReceiver?.tracks?.(id)||{}};
    const safeName=id=>String(name(id)||'Layer').slice(0,100);
    function seed(){
      const container=doc.querySelector('.greenroom-monitor-composition[data-composition-bus="preview"]');
      if(!container||!container.clientWidth||!container.clientHeight)return {};
      const bounds=container.getBoundingClientRect(),result={};
      for(const [index,node]of [...container.querySelectorAll('.composition-layer:not(.composition-outgoing)>.composition-tile')].entries()){
        const rect=node.getBoundingClientRect();if(!rect.width||!rect.height)continue;
        result[node.dataset.source]={...defaults(index),x:clamp((rect.left-bounds.left)/bounds.width),y:clamp((rect.top-bounds.top)/bounds.height),width:clamp(rect.width/bounds.width,.01),height:clamp(rect.height/bounds.height,.01)};
      }
      return result;
    }
    function note(text){message=text;one('[data-layer-status]').textContent=text;}
    function paint(){
      if(closed)return;const current=model.state(),selected=current.layers[current.selected],locked=Boolean(selected?.locked),unavailable=!selected,disabled=working||busy();
      const select=one('[data-layer-source]'),signature=current.base?.sources.join('|')||'';
      if(select.dataset.sources!==signature){select.replaceChildren();for(const id of current.base?.sources||[]){const option=doc.createElement('option');option.value=id;option.textContent=safeName(id);select.append(option);}select.dataset.sources=signature;}
      select.value=current.selected||'';select.disabled=disabled||unavailable;
      for(const input of fields){const key=input.dataset.layerField,crop=input.dataset.layerCrop,value=selected?(crop?selected.crop[crop]:selected[key]):0;input.value=String(Math.round((key==='z'?value:value*100)*1000)/1000);input.disabled=disabled||unavailable||locked;input.title=locked?'Unlock this layer to edit it.':unavailable?'Select a source in Preview first.':'';}
      one('[data-layer-locked]').checked=locked;one('[data-layer-locked]').disabled=disabled||unavailable;
      one('[data-layer-hidden]').checked=Boolean(selected?.hidden);one('[data-layer-hidden]').disabled=disabled||unavailable||locked;
      one('[data-layer-reset]').disabled=disabled||unavailable||locked;one('[data-layer-reload]').disabled=disabled;
      const commit=one('[data-layer-apply]');commit.disabled=disabled||!current.base?.sources.length||current.conflict;commit.title=current.conflict?'Preview changed elsewhere. Your draft is kept; reload Preview before applying.':!current.base?.sources.length?'Choose sources in Preview first.':'Apply this draft to Preview. Program is unchanged.';
      const canSave=Boolean(current.base?.layout==='custom'&&current.base.compositionId&&!current.dirty&&!current.conflict&&typeof host.ProducerLayerScenes?.savePreview==='function');sceneButton.disabled=disabled||!canSave;sceneButton.title=canSave?'Prepare a new scene from this confirmed Preview. Review and save its form; Program is unchanged.':'Apply this draft to Preview before creating a scene from it.';
      one('[data-layer-status]').textContent=current.conflict?'Preview changed elsewhere. Your draft is kept. Review it, then Reload current Preview to continue.':working?'Applying to Preview…':message;
      if(!drag){hits.replaceChildren();for(const id of current.base?.sources||[]){const layer=current.layers[id],box=doc.createElement('div');box.className='production-layer-hit';box.dataset.layerHit=id;box.dataset.selected=String(id===current.selected);box.dataset.locked=String(layer.locked);box.dataset.hidden=String(layer.hidden);box.setAttribute('role','button');box.tabIndex=0;box.setAttribute('aria-label',safeName(id)+(layer.locked?' · locked':' · move with arrow keys'));box.style.left=layer.x*100+'%';box.style.top=layer.y*100+'%';box.style.width=layer.width*100+'%';box.style.height=layer.height*100+'%';box.style.zIndex=String(layer.z);const label=doc.createElement('span');label.textContent=safeName(id)+(layer.hidden?' · hidden':'');box.append(label);hits.append(box);}
        if(selected&&!locked){const handle=doc.createElement('button');handle.type='button';handle.className='production-layer-resize';handle.dataset.layerResize=current.selected;handle.setAttribute('aria-label','Resize selected layer; Width and Height fields are also available');handle.style.left=clamp(selected.x+selected.width)*100+'%';handle.style.top=clamp(selected.y+selected.height)*100+'%';handle.textContent='↘';hits.append(handle);}}
      if(section.open&&host.ProducerCompositionView){if(!view)view=new host.ProducerCompositionView({container:one('.production-layer-picture'),mediaReceiver:receiver,muted:true,bus:'preview'});const next={...read(),preview_sources:current.base?.sources||[],preview_layout:'custom',preview_layers:current.layers};view.render(next,typeof room==='function'?room():room);}
    }
    function render(){if(closed)return;try{model.observe(read(),seed());paint();}catch(_){note('Layer controls could not load this Preview. Reload current Preview to retry.');}}
    function change(patch){try{model.edit(model.state().selected,patch);note('Unsaved layer draft. Apply to Preview when ready.');paint();}catch(error){note(error.message==='layer_locked'?'Unlock this layer before editing.':'Use valid percentages. Opposite crop edges must total less than100%.');paint();}}
    one('[data-layer-source]').addEventListener('change',event=>{try{model.select(event.target.value);paint();}catch(_){render();}});
    for(const input of fields)input.addEventListener('change',()=>{const value=Number(input.value),key=input.dataset.layerField;if(!Number.isFinite(value))return paint();if(key)change({[key]:key==='z'?value:value/100});else{const selected=model.state();change({crop:{...selected.layers[selected.selected].crop,[input.dataset.layerCrop]:value/100}});}});
    one('[data-layer-locked]').addEventListener('change',event=>change({locked:event.target.checked}));one('[data-layer-hidden]').addEventListener('change',event=>change({hidden:event.target.checked}));
    one('[data-layer-reset]').addEventListener('click',()=>{try{model.reset(model.state().selected);note('Selected layer reset in this draft. Apply to Preview when ready.');paint();}catch(_){paint();}});
    one('[data-layer-reload]').addEventListener('click',()=>{model.reload(read(),seed());note('Current Preview loaded. Program is unchanged.');paint();});
    one('[data-layer-apply]').addEventListener('click',async()=>{if(working||busy()||closed)return;let request;try{request=model.prepare();}catch(_){return paint();}working=true;paint();try{const next=await apply(request);if(closed)return;model.accepted(next);note('Applied to Preview. Use Take when the output is ready for Program.');}catch(error){if(!closed)note(error?.message==='preview_revision_conflict'?'Preview changed elsewhere. Your draft is kept; reload before applying.':'Apply could not be confirmed. Your draft and exact request are kept; check Preview, then retry.');}finally{working=false;if(!closed){model.observe(read(),seed());paint();}}});
    sceneButton.addEventListener('click',async()=>{const current=model.state();if(sceneButton.disabled||working||busy()||closed)return;working=true;paint();try{await host.ProducerLayerScenes.savePreview({compositionId:current.base.compositionId});if(!closed)note('Scene form opened from the confirmed Preview. Review it and choose Save scene. Program is unchanged.');}catch(_){if(!closed)note('Preview changed or the scene form could not open. Your draft is kept; reload Preview before trying again.');}finally{working=false;if(!closed)paint();}});
    hits.addEventListener('pointerdown',event=>{const target=event.target.closest('[data-layer-hit],[data-layer-resize]');if(!target||working||busy())return;const id=target.dataset.layerHit||target.dataset.layerResize;try{model.select(id);}catch(_){return;}const current=model.state(),layer=current.layers[id];if(layer.locked){paint();return;}const bounds=hits.getBoundingClientRect();if(!bounds.width||!bounds.height)return;drag={id,pointer:event.pointerId,x:event.clientX,y:event.clientY,layer:copy(layer),width:bounds.width,height:bounds.height,resize:Boolean(target.dataset.layerResize)};hits.setPointerCapture?.(event.pointerId);event.preventDefault();});
    hits.addEventListener('pointermove',event=>{if(!drag||drag.pointer!==event.pointerId)return;try{model.edit(drag.id,moveLayer(drag.layer,(event.clientX-drag.x)/drag.width,(event.clientY-drag.y)/drag.height,drag.resize));note('Unsaved layer draft. Apply to Preview when ready.');const hit=[...hits.querySelectorAll('[data-layer-hit]')].find(node=>node.dataset.layerHit===drag.id),layer=model.state().layers[drag.id];if(hit){hit.style.left=layer.x*100+'%';hit.style.top=layer.y*100+'%';hit.style.width=layer.width*100+'%';hit.style.height=layer.height*100+'%';}paint();}catch(_){}});
    const endDrag=()=>{if(!drag)return;drag=null;paint();};hits.addEventListener('pointerup',endDrag);hits.addEventListener('pointercancel',endDrag);hits.addEventListener('lostpointercapture',endDrag);
    hits.addEventListener('keydown',event=>{const id=event.target.closest('[data-layer-hit]')?.dataset.layerHit;if(!id||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)||working||busy())return;event.preventDefault();try{model.select(id);const layer=model.state().layers[id],step=event.shiftKey?.05:.01;model.edit(id,moveLayer(layer,event.key==='ArrowLeft'?-step:event.key==='ArrowRight'?step:0,event.key==='ArrowUp'?-step:event.key==='ArrowDown'?step:0));note('Unsaved layer draft. Apply to Preview when ready.');paint();[...hits.querySelectorAll('[data-layer-hit]')].find(node=>node.dataset.layerHit===id)?.focus();}catch(_){note('Unlock this layer before moving it.');}});
    section.addEventListener('toggle',()=>{if(section.open)render();else{view?.close();view=null;}});
    render();return {section,model,render,close(){closed=true;drag=null;view?.close();view=null;section.remove();}};
  }
  const api={defaults,normalizeLayers,createModel,moveLayer,mount};if(typeof module==='object'&&module.exports)module.exports=api;host.ProducerLayerEditor=api;
})(typeof window==='object'?window:globalThis);
