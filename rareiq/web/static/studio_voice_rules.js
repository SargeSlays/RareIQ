/* Exact voice bindings. Editing never arms recognition or executes an action. */
(function(host){
  'use strict';
  const clone=value=>JSON.parse(JSON.stringify(value));
  const endpoint='/api/production/voice/rules';
  function createModel(request){
    let revision=null,rules=[],editable=false,busy=false,epoch=0;
    return {
      state:()=>({revision,rules:clone(rules),editable,busy}),
      async load(){
        if(busy)throw Error('voice_rules_busy');
        busy=true;const token=++epoch;
        try{const data=await request(endpoint,{retries:0});
          if(token!==epoch)return null;
          if(data.ok!==true||!Number.isInteger(data.revision)||data.revision<0||!Array.isArray(data.rules))throw Error('voice_rules_unavailable');
          revision=data.revision;rules=clone(data.rules);editable=data.editable===true;return data;
        }finally{if(token===epoch)busy=false;}
      },
      async save(draft){
        if(busy||!editable||revision===null)throw Error('voice_rules_not_editable');
        busy=true;const token=++epoch;
        try{const data=await request(endpoint,{method:'PUT',retries:0,body:JSON.stringify({expected_revision:revision,rules:clone(draft)})});
          if(data.ok!==true||!Number.isInteger(data.revision)||data.revision<revision||!Array.isArray(data.rules))throw Error(data.reason||'voice_rules_unavailable');
          revision=data.revision;rules=clone(data.rules);return data;
        }finally{if(token===epoch)busy=false;}
      }
    };
  }
  function create({container,request}){
    if(!container)return null;
    const doc=host.document,model=createModel(request),root=doc.createElement('details');
    root.className='studio-voice-rules';
    root.innerHTML='<summary>Custom voice commands <span>Camera · scene · clip</span></summary><p>Choose an exact phrase without wake words. Say “Hey Sarge” before it unless Open flow is enabled. Existing camera and clip commands stay available.</p><p class="voice-rules-hint">English phrases and numbers · up to 24 commands · this computer only</p><div class="voice-rules-list"></div><div class="voice-rules-actions"><button type="button" class="riq-button" data-rule-add>Add command</button><button type="button" class="riq-button primary" data-rule-save>Save commands</button><button type="button" class="riq-button" data-rule-load>Reload saved commands</button></div><p class="voice-rules-status" role="status" aria-live="polite">Open to load your commands.</p>';
    container.append(root);
    const list=root.querySelector('.voice-rules-list'),status=root.querySelector('.voice-rules-status');
    let armed=false,loaded=false,loading=false,sceneOptions=[],availableActions=new Set(),dirty=false;
    const local=['localhost','127.0.0.1','[::1]','::1'].includes(host.location.hostname);
    const note=text=>{status.textContent=text;};
    function option(select,value,label){const item=doc.createElement('option');item.value=String(value);item.textContent=label;select.append(item);return item;}
    function field(label,element){const wrapper=doc.createElement('label'),name=doc.createElement('span');name.textContent=label;wrapper.append(name,element);return wrapper;}
    function refresh(){
      const disabled=!local||armed||loading||!loaded||!model.state().editable;
      for(const control of root.querySelectorAll('input,select,button'))control.disabled=disabled;
      root.querySelector('[data-rule-load]').disabled=!local||armed||loading;
      root.querySelector('[data-rule-add]').disabled=disabled||list.children.length>=24;
      root.querySelector('[data-rule-save]').disabled=disabled||!dirty;
      if(armed)note('Stop listening before editing commands.');
      else if(!local)note('Custom voice commands are available on the production computer.');
      else if(loaded&&!model.state().editable)note('Voice is listening in another tab. Stop listening, then reload.');
    }
    function addRow(rule={phrase:'',action_id:'program.take',params:{preview_slot:1,transition:'cut',duration_ms:500}}){
      const row=doc.createElement('div');row.className='voice-rule-row';
      const phrase=doc.createElement('input');phrase.type='text';phrase.maxLength=60;phrase.placeholder='close up';phrase.value=rule.phrase;phrase.autocomplete='off';
      const action=doc.createElement('select');
      for(const [id,label] of [['program.take','Switch camera'],['scene.take','Take scene'],['clip.save','Save clip']]){
        const opt=option(action,id,label);opt.disabled=!availableActions.has(id);
      }
      action.value=rule.action_id;
      const settings=doc.createElement('div');settings.className='voice-rule-settings';
      const remove=doc.createElement('button');remove.type='button';remove.className='riq-button';remove.textContent='Remove';remove.setAttribute('aria-label','Remove this voice command');
      row.append(field('Phrase',phrase),field('Action',action),settings,remove);
      function configure(params={}){
        settings.replaceChildren();
        if(action.value==='program.take'){
          const target=doc.createElement('select');target.dataset.param='preview_slot';
          for(let n=1;n<=4;n++)option(target,n,`Camera ${n}`);target.value=String(params.preview_slot||1);
          const transition=doc.createElement('select');transition.dataset.param='transition';
          for(const id of ['cut','fade','slide','zoom'])option(transition,id,id[0].toUpperCase()+id.slice(1));transition.value=params.transition||'cut';
          const duration=doc.createElement('select');duration.dataset.param='duration_ms';
          for(const n of [250,500,1000])option(duration,n,`${n} ms`);
          if(params.duration_ms!=null&&![250,500,1000].includes(params.duration_ms))option(duration,params.duration_ms,`${params.duration_ms} ms`);
          duration.value=String(params.duration_ms??500);
          settings.append(field('Camera',target),field('Transition',transition),field('Duration',duration));
        }else if(action.value==='scene.take'){
          const target=doc.createElement('select');target.dataset.param='scene_id';
          option(target,'',sceneOptions.length?'Choose a scene':'Save a production scene first');
          for(const scene of sceneOptions)option(target,scene.id,scene.name||scene.id);
          if(params.scene_id&&!sceneOptions.some(scene=>scene.id===params.scene_id))option(target,params.scene_id,'Saved scene unavailable');
          target.value=params.scene_id||'';settings.append(field('Scene',target));
        }else{
          const seconds=doc.createElement('select');seconds.dataset.param='seconds';
          for(const n of [15,30,60,120])option(seconds,n,`${n} seconds`);
          if(params.seconds!=null&&![15,30,60,120].includes(params.seconds))option(seconds,params.seconds,`${params.seconds} seconds`);
          seconds.value=String(params.seconds||15);settings.append(field('Replay length',seconds));
        }
      }
      configure(rule.params);
      row._rule=()=>{
        const params={};for(const control of settings.querySelectorAll('[data-param]'))params[control.dataset.param]=['preview_slot','duration_ms','seconds'].includes(control.dataset.param)?Number(control.value):control.value;
        if(action.value==='clip.save')params.name='Voice highlight';
        if(action.value==='scene.take'&&!params.scene_id)throw Error('choose_scene');
        return {phrase:phrase.value,action_id:action.value,params};
      };
      row.addEventListener('input',()=>{dirty=true;refresh();});
      row.addEventListener('change',()=>{dirty=true;refresh();});
      action.addEventListener('change',()=>{configure();dirty=true;refresh();});
      remove.addEventListener('click',()=>{row.remove();dirty=true;refresh();});
      list.append(row);
    }
    async function load(){
      if(loading||armed||!local)return;
      loading=true;refresh();note('Loading saved commands…');
      try{
        const data=await model.load();
        try{const scenes=await request('/api/production/scenes',{retries:0});sceneOptions=Array.isArray(scenes.scenes)?scenes.scenes:[];}catch(_){sceneOptions=[];}
        availableActions=new Set(data.actions.map(item=>item.id));list.replaceChildren();
        for(const rule of data.rules)addRow(rule);
        loaded=true;dirty=false;note(data.rules.length?`${data.rules.length} custom commands saved. Practice before using them on Program.`:'No custom commands yet. Add a phrase to get started.');
      }catch(_){note('Commands could not load. Your current production was unchanged; try Reload saved commands.');}
      finally{loading=false;refresh();}
    }
    root.querySelector('[data-rule-add]').addEventListener('click',()=>{if(list.children.length<24){addRow();dirty=true;refresh();list.lastElementChild.querySelector('input').focus();}});
    root.querySelector('[data-rule-load]').addEventListener('click',load);
    root.querySelector('[data-rule-save]').addEventListener('click',async()=>{
      if(loading||armed)return;
      let draft;try{draft=Array.from(list.children,row=>row._rule());}catch(_){note('Choose a saved scene for each scene command.');return;}
      loading=true;refresh();note('Saving commands…');
      try{const data=await model.save(draft);list.replaceChildren();for(const rule of data.rules)addRow(rule);dirty=false;note('Commands saved. Start listening with Practice first to check them.');}
      catch(error){const reason=error?.payload?.reason||error?.message;
        note(reason==='voice_rules_revision_conflict'?'Another tab changed the saved commands. Your draft is kept here. Copy any changes you need, then Reload saved commands.':reason==='stop_voice_before_editing_rules'?'Stop listening in every tab before saving. Your draft is kept here.':'Commands were not saved. Use unique English words/numbers, omit wake words, and keep the built-in phrases unchanged. Your draft is kept here.');}
      finally{loading=false;refresh();}
    });
    root.addEventListener('toggle',()=>{if(root.open&&!loaded)load();});
    refresh();return {setArmed(value){armed=Boolean(value);refresh();},load,root};
  }
  if(typeof module==='object'&&module.exports)module.exports={createModel,create};
  else host.StudioVoiceRulesFactory={createModel,create};
})(typeof window==='undefined'?globalThis:window);
