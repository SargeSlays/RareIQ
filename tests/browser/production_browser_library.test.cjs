const test=require('node:test'),assert=require('node:assert/strict');
const library=require('../../rareiq/web/static/production_browser_library.js'),adapter=require('../../rareiq/web/static/production_browser_source.js'),controls=require('../../rareiq/web/static/greenroom_controls.js');
const SOURCE='browser:12345678-1234-1234-1234-123456789abc',origin='http://127.0.0.1:8765';
test('browser form uses the shared public URL validator and fails closed without it',()=>{
  global.ProducerBrowserSource=adapter;
  try{assert.equal(library.sourceId(SOURCE),SOURCE);assert.equal(library.sourceId('browser:../secret'),null);assert.equal(library.browserProblem({name:'Score',target_url:'https://example.com/overlay'},origin),null);
    for(const url of ['http://example.com','https://localhost','https://user:pass@example.com','https://example.com:8443','javascript:alert(1)'])assert.match(library.browserProblem({name:'Score',target_url:url},origin),/public HTTPS/);
    delete global.ProducerBrowserSource;assert.match(library.browserProblem({name:'Score',target_url:'https://example.com'},origin),/unavailable/);
  }finally{delete global.ProducerBrowserSource;}
});
test('browser Take requires every output review and still requires one complete mixed composition',()=>{
  global.ProducerBrowserLibrary=library;
  try{const guest='guest:'+'a'.repeat(32)+':camera',switcher={program_sources:[],preview_sources:[SOURCE,guest],production_sources:[{id:SOURCE}]},room={participants:[{state:'admitted',connected:true,sources:{camera:guest},media:{camera:true}}],output:{connected:2,ready_groups:[[SOURCE,guest],[guest]]}};
    assert.equal(controls.sourceAvailable(SOURCE,switcher,room),true);assert.match(controls.takeReadiness(switcher,room).message,/every connected Studio Output/);room.output.ready_groups=[[SOURCE,guest],[SOURCE]];assert.equal(controls.takeReadiness(switcher,room).ready,true);
    room.output.ready_groups=[[SOURCE],[SOURCE]];assert.equal(controls.takeReadiness(switcher,room).ready,false);room.output.ready_groups=[[SOURCE,guest]];assert.equal(controls.takeReadiness(switcher,room).ready,false);assert.deepEqual(controls.togglePreview(SOURCE,switcher,room),[guest]);assert.deepEqual(switcher.program_sources,[]);switcher.production_sources=[];assert.equal(controls.sourceAvailable(SOURCE,switcher,room),false);
  }finally{delete global.ProducerBrowserLibrary;}
});
test('browser save retries the same receipt, blocks duplicate clicks and never selects or changes Program',async()=>{
  const savedLocation=global.location;global.location={origin};global.ProducerBrowserSource=adapter;
  class Element{
    constructor(){this.children=[];this.attributes={};this.queries=new Map();this.listeners=new Map();this.hidden=false;}
    setAttribute(name,value){this.attributes[name]=value;}querySelector(selector){if(!this.queries.has(selector))this.queries.set(selector,new Element());return this.queries.get(selector);}querySelectorAll(){return [];}
    append(...children){this.children.push(...children);}addEventListener(name,fn){this.listeners.set(name,fn);}remove(){this.removed=true;}focus(){}reset(){this.resetCalled=true;}
  }
  let section,finish,attempt=0,refreshes=0,selections=0;const requests=[],document={createElement:()=>new Element()},after={ownerDocument:document,after:node=>section=node};
  const view=library.mount({after,document,catalog:()=>[{id:SOURCE,name:'<b>Literal</b>'}],select:()=>selections++,refresh:async()=>refreshes++,fetch:async(path,options)=>{requests.push({path,body:JSON.parse(options.body)});if(++attempt===1){await new Promise(resolve=>finish=resolve);throw Error('uncertain');}return {ok:true,status:200,json:async()=>({ok:true,created:true,replayed:true})};}});
  try{const draft={name:'Score',target_url:'https://example.com/overlay'},first=view.saveBrowser(draft);assert.equal(section.querySelector('[data-browser-open]').disabled,true);await view.saveBrowser(draft);assert.equal(requests.length,1);finish();await first;await view.saveBrowser(draft);
    assert.equal(requests.length,2);assert.deepEqual(requests[0],requests[1]);assert.equal(refreshes,2);assert.equal(selections,0);assert.equal(section.querySelector('form').resetCalled,true);assert.equal(section.querySelector('.production-browser-list').children[0].children[0].textContent,'<b>Literal</b>');assert.match(section.innerHTML,/href="\/output\/studio\?browser-review=1" target="_blank" rel="noopener noreferrer"/);
  }finally{view.close();global.location=savedLocation;delete global.ProducerBrowserSource;}
});
