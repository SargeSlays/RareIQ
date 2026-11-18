const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
test('native broadcast review refusal survives refreshes and clears on the next successful preparation',async()=>{
  const reports=[],intervals=[],nodes=new Map();let nativeActive=true;
  const element=()=>({hidden:false,dataset:{},setAttribute(){},append(){},replaceChildren(){},addEventListener(){},remove(){},focus(){},querySelector(selector){if(!nodes.has(selector))nodes.set(selector,element());return nodes.get(selector);}});
  const document={body:element(),createElement:element};
  const host={parent:{postMessage:value=>reports.push(value)},location:{origin:'http://127.0.0.1:8768'},setInterval:fn=>{intervals.push(fn);return 1;},clearInterval(){},fetch:async url=>({ok:true,json:async()=>url.endsWith('/session')?{session:{active:false,recording:{active:false}},native_encoding:{active:nativeActive}}:{obs:{streaming:false,recording:false}}})};
  const context={window:host,module:{exports:{}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../rareiq/web/static/production_browser_review.js'),'utf8'),context);
  const view={current:{tiles:[{source:{kind:'browser'},id:'browser-fixture',node:element(),browser:{snapshot:()=>({phase:'loaded_unverified'})}}]},preloads:new Map(),state:{},container:element(),_allTiles:()=>view.current.tiles,refresh(){}};
  const review=context.module.exports.mount({view,document});await review.open();
  assert.equal(reports.at(-1).open,false);assert.match(reports.at(-1).note,/End the show, stream and recording/);
  for(let i=0;i<3;i++)intervals[0]();
  assert.match(reports.at(-1).note,/End the show, stream and recording/);
  nativeActive=false;view.current.tiles=[];await review.open();assert.equal(reports.at(-1).note,'');assert.equal(reports.at(-1).finished,true);review.close();
});
