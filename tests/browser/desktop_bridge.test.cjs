const test=require('node:test'),assert=require('node:assert/strict'),{install,openSources}=require('../../rareiq/web/static/desktop_bridge.js');
test('browser studio needs no native bridge and receives no event interception',()=>{let calls=0;assert.equal(install({addEventListener:()=>calls++},undefined),false);assert.equal(calls,0);});
test('desktop output setup opens native settings only for the matching control',async()=>{let click,opened=0,prevented=0,stopped=0;const button={};const document={addEventListener:(_name,fn)=>click=fn,querySelector:()=>button};assert.equal(install(document,{openBroadcastSettings:()=>{opened++;}}),true);assert.equal(button.textContent,'Broadcast setup');click({target:{closest:()=>null}});assert.equal(opened,0);click({target:{closest:()=>button},preventDefault:()=>prevented++,stopImmediatePropagation:()=>stopped++});assert.equal(opened,1);assert.equal(prevented,1);assert.equal(stopped,1);});
function sourcesFixture(){
  const calls=[],panel={isConnected:true,hidden:false,getClientRects:()=>[{}],scrollIntoView:value=>calls.push(['scroll',value])},workspace={querySelector:selector=>selector==='.production-greenroom'?panel:null,classList:{contains:name=>name==='active'&&workspace.active},_studioDocks:{showTool:id=>{calls.push(['tool',id]);return true;}}};
  const document={querySelector:selector=>selector==='.workspace[data-workspace="broadcast"]'?workspace:null},navigation={switchWorkspace:name=>{calls.push(['workspace',name]);workspace.active=true;return true;}};
  return {calls,panel,workspace,document,navigation};
}
test('Choose sources uses the existing workspace and dock navigation without selecting media',()=>{
  const f=sourcesFixture();assert.equal(openSources(f.document,f.navigation),true);
  assert.deepEqual(f.calls,[['workspace','broadcast'],['tool','production-greenroom'],['scroll',{block:'start',behavior:'auto'}]]);
});
test('Choose sources acknowledges only a mounted and visible source panel',()=>{
  const missing=sourcesFixture();missing.workspace._studioDocks=null;assert.equal(openSources(missing.document,missing.navigation),false);assert.deepEqual(missing.calls,[]);
  const hidden=sourcesFixture();hidden.panel.getClientRects=()=>[];assert.equal(openSources(hidden.document,hidden.navigation),false);assert.equal(hidden.calls.some(call=>call[0]==='scroll'),false);
  const rejected=sourcesFixture();rejected.navigation.switchWorkspace=()=>false;assert.equal(openSources(rejected.document,rejected.navigation),false);assert.deepEqual(rejected.calls,[]);
});
test('Choose sources can focus Add image without opening its picker',()=>{
  const f=sourcesFixture();let focused=false,scrolled=false;f.panel.querySelector=()=>({disabled:false,scrollIntoView:()=>{scrolled=true;},focus:()=>{focused=true;},click:()=>assert.fail('No file picker or capture may open automatically')});
  assert.equal(openSources(f.document,f.navigation),true);assert.equal(focused,true);assert.equal(scrolled,true);
});
