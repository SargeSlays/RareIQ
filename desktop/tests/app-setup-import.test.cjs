'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path');
const {parseAppConfiguration,createAppSetupImporter}=require('../app-setup-import.cjs');
const origin='http://127.0.0.1:8768',config={client_id:'fixture.apps.googleusercontent.com',client_secret:'synthetic-private-setup'};
function fixture(options={}){
 const e={senderFrame:{url:'file:///settings.html'}},calls=[],chosen=[],contents=JSON.stringify({installed:config});let closed=0;
 const handle={stat:async()=>({isFile:()=>true,size:Buffer.byteLength(contents)}),read:async(buffer,offset)=>{if(offset)return {bytesRead:0};const bytes=Buffer.from(contents);bytes.copy(buffer);return {bytesRead:bytes.length};},close:async()=>{closed++;}};
 const run=createAppSetupImporter({origin,trustedSender:v=>v===e,chooseFile:async options=>{chosen.push(options);return path.resolve('fixture.json');},fileSystem:{open:async()=>handle},fetchImpl:async(url,request)=>{calls.push({url,request});const r=new Response(JSON.stringify({ok:true,configured:true,replayed:false,client_secret:'must-not-return'}),{headers:{'Content-Type':'application/json'}});Object.defineProperty(r,'url',{value:url});return r;},...options});
 return {e,run,calls,chosen,handle,get closed(){return closed;}};
}
test('standard Google Desktop setup and owner-private Kick files accept only app configuration',()=>{
 assert.deepEqual(parseAppConfiguration('youtube',JSON.stringify({installed:{...config,project_id:'fixture-project',redirect_uris:['http://localhost']}})),config);
 assert.deepEqual(parseAppConfiguration('kick',JSON.stringify({client_id:'kick-app',client_secret:'synthetic-setup'})),{client_id:'kick-app',client_secret:'synthetic-setup'});
 for(const raw of [JSON.stringify({web:config}),JSON.stringify({installed:{...config,access_token:'no'}}),JSON.stringify({installed:{...config,token_uri:'https://foreign.invalid/token'}})])assert.throws(()=>parseAppConfiguration('youtube',raw),/invalid_app_configuration/);
});
test('trusted import privately posts fields and returns only configuration metadata',async()=>{
 const f=fixture(),r=await f.run(f.e,'youtube');assert.deepEqual(r,{ok:true,platform:'youtube',configured:true,replayed:false});assert.equal(f.closed,1);assert.equal(f.chosen[0].defaultPath,'F:/Users/jonat/Downloads');assert.equal(f.calls[0].url,origin+'/api/production/accounts/youtube/configure-app');assert.deepEqual(JSON.parse(f.calls[0].request.body),config);assert.equal(JSON.stringify(r).includes('private'),false);
});
test('untrusted calls and renderer filenames never open files or perform HTTP',async()=>{
 const f=fixture();assert.equal((await f.run({}, 'youtube')).reason,'local_operator_required');assert.equal((await f.run(f.e,{platform:'youtube',path:'private.json'})).reason,'invalid_app_provider');assert.equal(f.chosen.length,0);assert.equal(f.calls.length,0);
});
test('cancellation is harmless and navigation after native file selection stops ingestion',async()=>{
 const f=fixture({chooseFile:async()=>null});assert.deepEqual(await f.run(f.e,'youtube'),{ok:true,cancelled:true,platform:'youtube'});assert.equal(f.calls.length,0);
 const g=fixture({chooseFile:async()=>{g.e.senderFrame.url='file:///other.html';return path.resolve('fixture.json');}});assert.equal((await g.run(g.e,'youtube')).reason,'local_operator_required');assert.equal(g.calls.length,0);
});
test('oversized/nonregular files and malformed UTF8 are rejected with handles closed',async()=>{
 for(const mode of ['size','directory','encoding']){const f=fixture();f.handle.stat=async()=>({isFile:()=>mode!=='directory',size:mode==='size'?65537:1});if(mode==='encoding')f.handle.read=async(buffer,offset)=>{if(offset)return{bytesRead:0};buffer[0]=255;return{bytesRead:1};};const r=await f.run(f.e,'youtube');assert.equal(r.ok,false);assert.equal(f.closed,1);assert.equal(f.calls.length,0);assert.equal(JSON.stringify(r).includes('private'),false);}
});
test('server secret/error fields and oversized replies cannot cross IPC',async()=>{
 for(const mode of ['safe-error','raw-error','large']){const f=fixture({fetchImpl:async url=>{const body=mode==='large'?'x'.repeat(4097):JSON.stringify({ok:false,reason:mode==='safe-error'?'disconnect_before_app_setup':'private-secret'});const r=new Response(body,{status:409,headers:{'Content-Type':'application/json'}});Object.defineProperty(r,'url',{value:url});return r;}});const r=await f.run(f.e,'youtube');assert.equal(r.reason,mode==='safe-error'?'disconnect_before_app_setup':'app_setup_unavailable');assert.equal(JSON.stringify(r).includes('private-secret'),false);}
});
