/* Explicit Preview-only layout shortcuts. Polling never applies a recommendation. */
(function(host){
  'use strict';
  const ASSET=/^(image|video|text|browser):[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
  function sourceKind(id){
    if(/^camera:[1-4]$/.test(id))return 'camera';
    const guest=/^guest:[a-f0-9]{32}:(camera|screen|audio)$/.exec(id);if(guest)return guest[1]==='screen'?'content':guest[1];
    const asset=ASSET.exec(id);return asset?(asset[1]==='text'?'text':'content'):null;
  }
  function selectedSources(values){if(!Array.isArray(values)||values.length>6||new Set(values).size!==values.length||values.some(value=>typeof value!=='string'||!sourceKind(value)))throw Error('invalid_preview_sources');return values.slice();}
  function visualSources(values){return selectedSources(values).filter(value=>['camera','content'].includes(sourceKind(value)));}
  function leadFirst(values,lead){
    const sources=selectedSources(values),visuals=visualSources(sources);if(!visuals.includes(lead))throw Error('lead_not_selected');
    const ordered=[lead,...visuals.filter(value=>value!==lead)];let index=0;
    return sources.map(value=>['camera','content'].includes(sourceKind(value))?ordered[index++]:value);
  }
  function presetPlan(preset,values){
    const sources=selectedSources(values),visuals=visualSources(sources),content=visuals.find(value=>sourceKind(value)==='content');
    if(!visuals.length)return {available:false,label:'Choose a picture',reason:'Add a camera, screen, image, video or browser source to Preview. Text and mic-only sources do not need a picture layout.'};
    if(preset==='smart'){
      if(visuals.length===1)return {available:true,label:'Solo',sources,layout:'auto',reason:'Give the selected picture the full frame.'};
      if(content)return {available:true,label:'Presentation',sources:leadFirst(sources,content),layout:'spotlight',reason:'Make the selected screen or media prominent, with the other pictures alongside.'};
      return {available:true,label:visuals.length===2?'Interview':'Panel',sources,layout:'grid',reason:'Give the selected cameras equal space.'};
    }
    if(preset==='pip'&&visuals.length!==2)return {available:false,label:'Picture-in-picture',reason:'Select exactly two pictures for picture-in-picture. Text and mic-only sources do not count.'};
    if(visuals.length<2)return {available:false,label:preset==='grid'?'Equal grid':'Focus',reason:'Select at least two pictures to use this layout. Text and mic-only sources do not count.'};
    if(preset==='grid')return {available:true,label:'Equal grid',sources,layout:'grid',reason:'Give every selected picture equal space.'};
    if(preset==='focus'||preset==='pip')return {available:true,label:preset==='pip'?'Picture-in-picture':content?'Presentation':'Focus',sources:leadFirst(sources,content||visuals[0]),layout:preset==='pip'?'pip':'spotlight',reason:preset==='pip'?'Keep the lead picture large and place the other picture in a corner.':'Keep the lead picture large with the other pictures alongside.'};
    throw Error('invalid_layout_preset');
  }
  function applyPreset(preset,selected,apply){const plan=presetPlan(preset,selected());if(plan.available)apply(plan.sources,plan.layout);return plan;}
  function mount({controls,selected=()=>[],layout=()=> 'auto',busy=()=>false,apply=()=>{},name=id=>id,document=controls?.ownerDocument||host.document}={}){
    if(!controls||!document)return null;
    const section=document.createElement('section');section.className='production-layouts';section.setAttribute('aria-label','Preview layouts');
    section.innerHTML='<div class="production-layout-heading"><strong>Shape your Preview</strong><span>Uses only your selected sources</span></div><div class="production-layout-presets"><button class="production-layout-preset" type="button" data-layout-preset="smart"><strong>Smart suggestion</strong><span data-layout-description>Choose a picture</span></button><button class="production-layout-preset" type="button" data-layout-preset="grid"><strong>Equal grid</strong><span data-layout-description>Equal space for each picture</span></button><button class="production-layout-preset" type="button" data-layout-preset="focus"><strong data-layout-name>Focus</strong><span data-layout-description>A large lead picture</span></button><button class="production-layout-preset" type="button" data-layout-preset="pip"><strong>Picture-in-picture</strong><span data-layout-description>One picture over another</span></button></div><p class="production-layout-hint" role="status" aria-live="polite">Choose a layout to update Preview. Program changes only when you Take.</p><details class="production-layout-advanced"><summary>Advanced layout &amp; transitions</summary><div class="production-layout-manual"><label><span>Lead picture</span><select data-layout-lead aria-label="Lead picture"></select><small data-layout-lead-hint>Choose which selected picture appears first.</small></label></div></details>';
    controls.before(section);
    const one=selector=>section.querySelector(selector),manual=one('.production-layout-manual'),lead=one('[data-layout-lead]'),hint=one('.production-layout-hint'),buttons=[...section.querySelectorAll('[data-layout-preset]')],labels=[];
    for(const selector of ['[data-room-layout]','[data-room-transition]','[data-room-duration]']){const label=controls.querySelector(selector)?.closest('label');if(label){labels.push(label);manual.append(label);}}
    const manualLayout=manual.querySelector('[data-room-layout]');if(manualLayout&&!manualLayout.querySelector('option[value="pip"]')){const option=document.createElement('option');option.value='pip';option.textContent='Picture-in-picture';manualLayout.append(option);}
    let closed=false,leadSignature='';
    function snapshot(){try{return selectedSources(selected());}catch(_){return [];}}
    function render(){
      if(closed)return;const values=snapshot(),visuals=visualSources(values),locked=busy();
      for(const button of buttons){const preset=button.dataset.layoutPreset,plan=presetPlan(preset,values);button.disabled=locked||!plan.available;button.title=locked?'Wait for the current Preview change to finish.':plan.reason;button.dataset.active=String(plan.available&&layout()===plan.layout&&JSON.stringify(values)===JSON.stringify(plan.sources));if(preset==='smart')button.querySelector('[data-layout-description]').textContent=plan.available?plan.label:'Choose a picture';if(preset==='focus')button.querySelector('[data-layout-name]').textContent=plan.available?plan.label:'Focus';}
      const signature=JSON.stringify(visuals.map(id=>[id,String(name(id)).slice(0,80)]));
      if(signature!==leadSignature){leadSignature=signature;lead.replaceChildren();if(!visuals.length){const option=document.createElement('option');option.value='';option.textContent='No pictures selected';lead.append(option);}else for(const id of visuals){const option=document.createElement('option');option.value=id;option.textContent=String(name(id)).slice(0,80);lead.append(option);}}
      lead.value=visuals[0]||'';lead.disabled=locked||visuals.length<2;lead.title=locked?'Wait for the current Preview change to finish.':visuals.length<2?'Select at least two pictures to change their order.':'Move a selected picture to the lead position in Preview.';
      one('[data-layout-lead-hint]').textContent=visuals.length<2?'Select two or more pictures to change their order.':'The lead picture is large in Focus and picture-in-picture.';
      for(const label of labels)for(const control of label.querySelectorAll('select')){control.disabled=locked;control.title=locked?'Wait for the current Preview change to finish.':'';}
    }
    for(const button of buttons)button.addEventListener('click',()=>{if(closed||busy())return;try{const plan=applyPreset(button.dataset.layoutPreset,selected,apply);hint.textContent=plan.available?plan.label+' requested for Preview. Program is unchanged.':plan.reason;}catch(_){hint.textContent='Preview changed. Review your selected sources and try again.';}});
    lead.addEventListener('change',()=>{if(closed||busy())return;try{const sources=leadFirst(selected(),lead.value);apply(sources,layout());hint.textContent='Lead picture requested for Preview. Program is unchanged.';}catch(_){hint.textContent='That picture is no longer selected. Review Preview and try again.';render();}});
    render();return {render,close(){if(closed)return;closed=true;controls.prepend(...labels);section.remove();}};
  }
  const exported={sourceKind,selectedSources,visualSources,leadFirst,presetPlan,applyPreset,mount};if(typeof module==='object'&&module.exports)module.exports=exported;else host.ProducerLayouts=exported;
})(typeof window==='undefined'?globalThis:window);
