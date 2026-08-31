const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const folder=path.resolve(__dirname,'../../rareiq/web/static');
const model=require(path.join(folder,'set_chase_state.js'));
const card={id:'kept',name:'Saved card',set_id:'set',language:'English',collector_number:'1/100',image_url:''};
const draft={set_id:'set',set_name:'Saved set',language:'English',theme:'auto',cards_per_page:4,seconds_per_page:8,accent:'',secondary:'',case_hits:[card],top_hits:[]};
const payload=(rows=[],extra={})=>({ok:true,results:rows,total:rows.length,set_total:130,
  rarities:[{value:'SAR',count:4},{value:'C',count:125},{value:'',count:1}],selected_rarities:['SAR'],...extra});
async function flush(){for(let i=0;i<15;i++)await Promise.resolve();}
async function editor({lateSets=false,loadedDraft=draft,framed=false,search=''}={}){
  class Node{
    constructor(){this.children=[];this.value='';this.handlers={};this.attributes={};this.classList={toggle(){}};this.checked=false;this.disabled=false;}
    append(...nodes){this.children.push(...nodes);}
    replaceChildren(...nodes){this.children=nodes;this.value=nodes[0]?.value||'';}
    get options(){return this.children;}
    setAttribute(key,value){this.attributes[key]=value;}
    addEventListener(event,fn){this.handlers[event]=fn;}
    showModal(){this.open=true;}
    close(){this.open=false;}
    focus(){this.focused=true;}
  }
  class Option extends Node{constructor(text,value){super();this.textContent=text;this.value=value;}}
  const elements=new Map(),requests=[],windowEvents={},timers=new Map(),bodyClasses=new Set();let timerId=0;
  const get=id=>{if(!elements.has(id))elements.set(id,new Node());return elements.get(id);};
  const context=vm.createContext({document:{getElementById:get,createElement:()=>new Node(),body:{classList:{add:value=>bodyClasses.add(value)}}},Option,URLSearchParams,AbortController,AbortSignal,
    structuredClone,location:{origin:'http://test',search},navigator:{clipboard:{}},setTimeout:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;},clearTimeout:id=>timers.delete(id),
    window:{self:1,top:framed?2:1,RareIQSetChase:model,addEventListener(event,fn){windowEvents[event]=fn;}},fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))});
  vm.runInContext(fs.readFileSync(path.join(folder,'set_chase_editor.js'),'utf8'),context);
  const reply=async(request,data,status=200)=>{request.resolve({ok:status<400,status,json:async()=>data});await flush();};
  const fail=async(request)=>{request.reject(new Error('Network unavailable'));await flush();};
  const pollStatus=async()=>{const timer=[...timers].find(([,value])=>value.delay===3000);if(!timer)return null;timers.delete(timer[0]);timer[1].fn();await flush();return requests.at(-1);};
  const loadSets=()=>reply(requests.find(r=>r.url==='/api/creator/set-chase/sets'),{ok:true,sets:[{set_id:'set',set_name:'Saved set',language:'English'},{set_id:'other',set_name:'Other set',language:'English'}]});
  if(!lateSets)await loadSets();
  await reply(requests.find(r=>r.url==='/api/creator/set-chase'),{ok:true,revision:0,visible:false,draft:structuredClone(loadedDraft)});
  if(lateSets)await loadSets();
  const searches=()=>requests.filter(r=>r.url.includes('/cards?'));
  await reply(searches().at(-1),payload([{...card,rarity:'SAR'}]));
  const inputs=()=>get('rarityOptions').children.map(label=>label.children[0]);
  const toggle=(rarity,checked)=>{const input=inputs().find(item=>item.value===rarity);input.checked=checked;input.onchange();};
  const params=()=>new URL(searches().at(-1).url,'http://test').searchParams;
  return {get,requests,searches,reply,fail,pollStatus,timers,inputs,toggle,params,windowEvents,bodyClasses};
}

test('compact editor mode only applies to the explicitly embedded Creator document',async()=>{
  for(const [framed,search,expected] of [[true,'?embed=creator',true],[false,'?embed=creator',false],[true,'',false]]){
    const app=await editor({framed,search});assert.equal(app.bodyClasses.has('creator-embedded'),expected);
    assert.equal(app.get('airState').textContent,'OFF AIR');
  }
});

test('highest rarity loads first; multiple levels combine with query and reset preserves the rotation',async()=>{
  const app=await editor();
  assert.equal(app.params().get('highest'),'true');
  assert.deepEqual(app.inputs().map(input=>[input.value,input.checked]),[['SAR',true],['C',false],['',false]]);
  app.get('cardQuery').value='Chase';app.toggle('C',true);
  assert.deepEqual(app.params().getAll('rarity'),['SAR','C']);assert.equal(app.params().get('q'),'Chase');
  assert.equal(app.params().has('highest'),false);assert.equal(app.get('catalogResults').children.length,0);
  await app.reply(app.searches().at(-1),payload([]));
  assert.match(app.get('catalogResults').children[0].textContent,/No cards match/);
  assert.equal(app.get('publish').disabled,false);
  app.get('clearFilters').onclick();
  assert.equal(app.params().get('highest'),'true');assert.equal(app.params().has('rarity'),false);assert.equal(app.params().get('q'),'');
  await app.reply(app.searches().at(-1),payload([card]));
  app.get('save').onclick();
  const posted=JSON.parse(app.requests.at(-1).options.body);
  assert.deepEqual(posted.config.case_hits,[card]);assert.deepEqual(posted.config.top_hits,[]);
});

test('late filter replies cannot replace newer results or reconstruct focused rarity controls',async()=>{
  const app=await editor(),focused=app.inputs()[1];
  app.toggle('C',true);const old=app.searches().at(-1);
  app.toggle('C',false);const latest=app.searches().at(-1);
  assert.equal(old.options.signal.aborted,true);
  await app.reply(latest,payload([{...card,id:'chase',name:'Chase',rarity:'SAR'}]));
  const rendered=app.get('catalogResults').children[0];
  await app.reply(old,payload(Array(10).fill(card)));
  assert.equal(app.get('catalogResults').children[0],rendered);
  assert.equal(app.inputs()[1],focused);assert.equal(focused.checked,false);
  assert.equal(app.get('searchStatus').textContent,'1 matching card · 130 in this set');
  assert.equal(app.get('catalogResults').attributes['aria-busy'],'false');
});

test('clearing selection hides every card and cancels pending searches instead of falling back to all',async()=>{
  const app=await editor();app.toggle('C',true);const pending=app.searches().at(-1),count=app.searches().length;
  app.get('clearRarities').onclick();
  assert.equal(app.searches().length,count);assert.equal(pending.options.signal.aborted,true);
  assert.ok(app.inputs().every(input=>!input.checked));
  assert.equal(app.get('searchStatus').textContent,'No rarity levels selected.');
  await app.reply(pending,payload([card]));
  assert.match(app.get('catalogResults').children[0].textContent,/Select at least one rarity/);
  app.toggle('SAR',true);await app.reply(app.searches().at(-1),payload([card]));
  const before=app.searches().length;app.toggle('SAR',false);
  assert.equal(app.searches().length,before);assert.equal(app.get('searchStatus').textContent,'No rarity levels selected.');
});

test('all rarities is explicit and unlisted remains a valid selected level',async()=>{
  const app=await editor();app.get('clearRarities').onclick();app.toggle('',true);
  assert.deepEqual(app.params().getAll('rarity'),['']);assert.equal(app.params().has('highest'),false);
  await app.reply(app.searches().at(-1),payload([card]));
  assert.deepEqual(app.inputs().map(input=>input.checked),[false,false,true]);
  app.get('allRarities').onclick();
  assert.equal(app.params().has('rarity'),false);assert.equal(app.params().has('highest'),false);
  await app.reply(app.searches().at(-1),payload([card],{selected_rarities:null}));
  assert.ok(app.inputs().every(input=>input.checked));
  app.toggle('C',false);assert.deepEqual(app.params().getAll('rarity'),['SAR','']);
});

test('changing sets resets old levels to the new highest tier and ignores stale results',async()=>{
  const app=await editor();app.toggle('C',true);const old=app.searches().at(-1);
  app.get('setPicker').value='1';app.get('useSet').onclick();
  assert.equal(app.get('discardDialog').open,true);app.get('discardChanges').onclick();
  assert.equal(app.params().get('set_id'),'other');assert.equal(app.params().get('highest'),'true');
  assert.equal(app.params().has('rarity'),false);assert.equal(app.get('rarityFilter').disabled,true);
  await app.reply(app.searches().at(-1),payload([],{set_total:0,rarities:[],selected_rarities:[]}));
  await app.reply(old,payload([card]));
  assert.equal(app.inputs().length,0);assert.equal(app.get('searchStatus').textContent,'0 matching cards · 0 in this set');
});

test('saved set is restored regardless of load order and selecting it again never clears cards',async()=>{
  for(const lateSets of [false,true]){
    const app=await editor({lateSets}),count=app.searches().length;
    assert.equal(app.get('setPicker').value,'0');assert.equal(app.get('useSet').disabled,true);
    app.get('useSet').onclick();assert.equal(app.searches().length,count);
    assert.equal(app.get('caseHits').children.length,1);
    app.get('save').onclick();assert.deepEqual(JSON.parse(app.requests.at(-1).options.body).config.case_hits,[card]);
  }
});

test('switching sets asks first; Keep editing and Escape preserve the existing draft',async()=>{
  const app=await editor(),count=app.searches().length;
  app.get('setPicker').value='1';app.get('useSet').onclick();
  assert.equal(app.get('discardDialog').open,true);assert.equal(app.get('keepEditing').focused,true);
  assert.equal(app.searches().length,count);app.get('keepEditing').onclick();
  assert.equal(app.get('discardDialog').open,false);assert.equal(app.get('setPicker').value,'0');
  app.get('setPicker').value='1';app.get('useSet').onclick();
  app.get('discardDialog').handlers.cancel();app.get('discardChanges').onclick();
  assert.equal(app.searches().length,count);assert.equal(app.get('caseHits').children.length,1);
});

test('unsaved edits are protected on reload and navigation; confirmed reload fetches saved state',async()=>{
  const app=await editor();let prevented=false;
  app.windowEvents.beforeunload({preventDefault(){prevented=true;}});assert.equal(prevented,false);
  app.get('theme').handlers.input();
  const event={preventDefault(){prevented=true;}};app.windowEvents.beforeunload(event);
  assert.equal(prevented,true);assert.equal(event.returnValue,'');
  const count=app.requests.length;app.get('reload').onclick();
  assert.equal(app.get('discardDialog').open,true);assert.equal(app.requests.length,count);
  app.get('keepEditing').onclick();assert.equal(app.requests.length,count);
  app.get('reload').onclick();app.get('discardChanges').onclick();
  assert.equal(app.requests.at(-1).url,'/api/creator/set-chase');
});

test('cards move between groups without duplication and retain their saved artwork',async()=>{
  const saved={...card,image_url:'/api/catalog-engine/image/en_set/kept.png'};
  const app=await editor({loadedDraft:{...draft,case_hits:[saved]}});
  const move=app.get('caseHits').children[0].children.find(n=>n.attributes?.['aria-label']==='Move Saved card to Top hits');
  move.onclick();
  assert.match(app.get('caseHits').children[0].textContent,/Add cards/);assert.equal(app.get('topHits').children.length,1);
  const article=app.get('catalogResults').children[0],actions=article.children[1].children[2];
  assert.equal(actions.children[0].textContent,'Move to case hits');assert.equal(actions.children[1].textContent,'In top hits');
  assert.equal(actions.children[1].disabled,true);
  actions.children[0].onclick();
  app.get('save').onclick();const posted=JSON.parse(app.requests.at(-1).options.body);
  assert.deepEqual(posted.config.case_hits,[saved]);assert.deepEqual(posted.config.top_hits,[]);
});

test('a full destination cannot remove a card from its existing group',async()=>{
  const full=Array.from({length:32},(_,i)=>({...card,id:`top${i}`}));
  const app=await editor({loadedDraft:{...draft,top_hits:full}});
  const move=app.get('caseHits').children[0].children.find(n=>n.attributes?.['aria-label']==='Move Saved card to Top hits');
  assert.equal(move.disabled,true);move.onclick();assert.match(app.get('editorStatus').textContent,/32 cards/);
  assert.equal(app.get('caseHits').children.length,1);assert.equal(app.get('topHits').children.length,32);
});

test('missing or failed artwork keeps an explicit placeholder in the card slot',async()=>{
  const saved={...card,image_url:'/api/catalog-engine/image/en_set/kept.png'};
  const app=await editor({loadedDraft:{...draft,case_hits:[saved]}});
  const missing=app.get('catalogResults').children[0].children[0];
  assert.equal(missing.className,'card-art');assert.equal(missing.children[0].textContent,'Artwork unavailable');
  const art=app.get('caseHits').children[0].children[0];assert.equal(art.children[0].src,saved.image_url);
  art.children[0].onerror();assert.equal(art.children[0].textContent,'Artwork unavailable');
  assert.match(art.attributes['aria-label'],/Saved card/);
});

test('live status refresh observes other windows without replacing the local editor',async()=>{
  const app=await editor();
  const original=app.get('caseHits').children[0];
  await app.reply(await app.pollStatus(),{ok:true,revision:0,visible:true,config:draft});
  assert.equal(app.get('airState').textContent,'LIVE · published strip');
  assert.equal(app.get('outputStatus').textContent,'On air: Saved set');
  await app.reply(await app.pollStatus(),{ok:true,revision:1,visible:false,config:draft});
  assert.equal(app.get('airState').textContent,'OFF AIR');
  assert.equal(app.get('syncStatus').hidden,false);assert.match(app.get('syncStatus').textContent,/another window/);
  assert.equal(app.get('save').disabled,true);assert.equal(app.get('publish').disabled,true);
  assert.equal(app.get('caseHits').children[0],original);
});

test('remote revisions preserve unsaved fields and require explicit reload before writes',async()=>{
  const app=await editor();app.get('theme').value='ember';app.get('theme').handlers.input();
  await app.reply(await app.pollStatus(),{ok:true,revision:8,visible:true,config:{...draft,set_name:'Different broadcast'}});
  assert.equal(app.get('theme').value,'ember');assert.match(app.get('previewStatus').textContent,/Unsaved edits/);
  assert.equal(app.get('outputStatus').textContent,'On air: Different broadcast');
  const count=app.requests.length;app.get('save').onclick();app.get('publish').onclick();
  assert.equal(app.requests.length,count);
  app.get('reload').onclick();assert.equal(app.get('discardDialog').open,true);
  app.get('keepEditing').onclick();assert.equal(app.get('theme').value,'ember');
  app.get('reload').onclick();app.get('discardChanges').onclick();
  await app.reply(app.requests.at(-1),{ok:true,revision:8,visible:false,draft});
  assert.equal(app.get('syncStatus').hidden,true);assert.equal(app.get('save').disabled,false);
});

test('connection loss is unknown, not off air, and recovery keeps the working draft',async()=>{
  const app=await editor();app.get('theme').value='ember';app.get('theme').handlers.input();
  const pending=await app.pollStatus();assert.equal(pending.url,'/api/creator/set-chase/status');
  assert.equal(await app.pollStatus(),null,'status requests are single flight');
  await app.fail(pending);
  assert.equal(app.get('airState').textContent,'CONNECTION LOST');
  assert.equal(app.get('save').disabled,true);assert.match(app.get('syncStatus').textContent,/retrying automatically/);
  assert.equal(app.get('theme').value,'ember');
  await app.reply(await app.pollStatus(),{ok:true,revision:0,visible:false,config:null});
  assert.equal(app.get('airState').textContent,'OFF AIR');assert.equal(app.get('save').disabled,false);
  assert.equal(app.get('publish').disabled,true,'unsaved edits still prevent publication');
  assert.equal(app.get('syncStatus').hidden,true);assert.equal(app.get('theme').value,'ember');
});

test('a late status read cannot undo an acknowledged publish',async()=>{
  const app=await editor(),pending=await app.pollStatus();
  app.get('publish').onclick();assert.equal(pending.options.signal.aborted,true);
  assert.equal(app.get('editorStatus').textContent,'Publishing saved draft…');
  assert.equal(app.get('publish').disabled,true);
  await app.reply(app.requests.at(-1),{ok:true,revision:1,visible:true,draft,program:draft});
  await app.reply(pending,{ok:true,revision:0,visible:false,config:null});
  assert.equal(app.get('airState').textContent,'LIVE · published strip');
  assert.equal(app.get('syncStatus').hidden,true);assert.equal(app.get('hide').disabled,false);
  assert.equal([...app.timers.values()].filter(timer=>timer.delay===3000).length,1);
});

test('uncertain writes never retry automatically or erase unsaved edits',async()=>{
  const app=await editor();app.get('theme').value='ember';app.get('theme').handlers.input();
  app.get('save').onclick();assert.equal(app.get('editorStatus').textContent,'Saving draft…');
  await app.fail(app.requests.at(-1));
  assert.equal(app.get('airState').textContent,'CONNECTION LOST');assert.equal(app.get('theme').value,'ember');
  await app.reply(await app.pollStatus(),{ok:true,revision:1,visible:false,config:null});
  assert.equal(app.get('save').disabled,true);assert.match(app.get('syncStatus').textContent,/Reload saved/);
  assert.equal(app.requests.filter(request=>request.options.method==='POST').length,1);
});

test('status conflicts are explicit and page lifecycle cancels late reads',async()=>{
  const app=await editor();app.get('save').onclick();
  await app.reply(app.requests.at(-1),{detail:'Settings changed in another window'},409);
  assert.equal(app.get('save').disabled,true);assert.equal(app.get('syncStatus').hidden,false);
  const pending=await app.pollStatus();app.windowEvents.pagehide();
  assert.equal(pending.options.signal.aborted,true);assert.equal(app.timers.size,0);
  await app.reply(pending,{ok:true,revision:0,visible:true,config:draft});
  assert.equal(app.timers.size,0);assert.notEqual(app.get('airState').textContent,'LIVE · published strip');
  app.windowEvents.pageshow({persisted:true});assert.ok(await app.pollStatus());
});

test('a stale editor can hide the confirmed live output without overwriting or adopting another draft',async()=>{
  const app=await editor();app.get('theme').value='ember';app.get('theme').handlers.input();
  const other={...draft,set_name:'Another saved draft'};
  await app.reply(await app.pollStatus(),{ok:true,revision:8,visible:true,config:other});
  assert.equal(app.get('hide').disabled,false);app.get('hide').onclick();
  const request=app.requests.at(-1);assert.equal(request.url,'/api/creator/set-chase/hide');
  assert.deepEqual(JSON.parse(request.options.body),{revision:8});
  await app.reply(request,{ok:true,revision:9,visible:false,draft:other,program:other});
  assert.equal(app.get('airState').textContent,'OFF AIR');assert.equal(app.get('hide').disabled,true);
  assert.equal(app.get('theme').value,'ember');assert.match(app.get('selectedSet').textContent,/Saved set/);
  assert.equal(app.get('save').disabled,true);assert.match(app.get('syncStatus').textContent,/another window/);
});
