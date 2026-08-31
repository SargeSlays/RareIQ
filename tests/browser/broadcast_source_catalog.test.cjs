const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/studiox.js'),'utf8');
function runtime(clipboard={writeText:async()=>{}}){
  const nodes=new Map(),messages=[];
  function node(){return {dataset:{},fields:{},attributes:{},handlers:{},children:[],
    querySelector(key){return this.fields[key]??=node();},replaceChildren(...children){this.children=children;},
    setAttribute(key,value){this.attributes[key]=value;},addEventListener(key,handler){this.handlers[key]=handler;}};}
  const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
  const context=vm.createContext({$:get,document:{createElement:node},location:{origin:'http://127.0.0.1:9040'},
    navigator:{clipboard},notify:(...args)=>messages.push(args)});
  vm.runInContext(source.slice(source.indexOf('function broadcastSourceFormat('),source.indexOf('async function bootstrapObs(')),context);
  vm.runInContext(source.slice(source.indexOf('function renderEncoderGuide('),source.indexOf('async function loadRecordingSettings(')),context);
  return {get,messages,render:context.renderEncoderGuide};
}
const chase={key:'set_chase',label:'Set Chase Bar',path:'/overlay/set-chase',width:1280,height:320,placement:'bottom-center',audio:false};
test('source guide displays strip dimensions and copies only the clean live source URL',async()=>{
  const copied=[],app=runtime({writeText:async url=>copied.push(url)});
  app.render({browser_source_details:[chase]});
  const row=app.get('recordingBrowserSources').children[0];
  assert.equal(row.dataset.source,'set_chase');
  assert.equal(row.querySelector('strong').textContent,'Set Chase Bar');
  assert.equal(row.querySelector('small').textContent,'1280 × 320 · Bottom strip · Silent');
  const button=row.querySelector('button');
  assert.equal(button.attributes['aria-label'],'Copy Set Chase Bar source URL');
  await button.handlers.click();
  assert.deepEqual(copied,['http://127.0.0.1:9040/overlay/set-chase']);
  assert.equal(app.messages[0][2],'success');
});
test('source guide explains the audio route and keeps legacy servers readable',()=>{
  const app=runtime();
  app.render({browser_source_details:[{...chase,key:'soundboard',audio:true}]});
  assert.match(app.get('recordingBrowserSources').children[0].querySelector('small').textContent,/Audio only · Control audio via OBS/);
  app.render({browser_sources:{set_chase:'/overlay/set-chase'}});
  const row=app.get('recordingBrowserSources').children[0];
  assert.equal(row.querySelector('code').textContent,'http://127.0.0.1:9040/overlay/set-chase');
  assert.match(row.querySelector('small').textContent,/Set dimensions in OBS/);
});
test('unavailable clipboard gives an actionable failure without claiming success',async()=>{
  const app=runtime(null);app.render({browser_source_details:[chase]});
  await app.get('recordingBrowserSources').children[0].querySelector('button').handlers.click();
  assert.equal(app.messages.length,1);assert.equal(app.messages[0][0],'Copy Failed');
  assert.equal(app.messages[0][2],'error');
});
