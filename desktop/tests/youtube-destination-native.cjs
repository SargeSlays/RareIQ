/* Original packaged Main/Settings/Windows storage; synthetic GET-only YouTube.
   The owned local backend runs the original selection router/service. No grants,
   credentials, device capture, ingest resolution, encoding or provider writes. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),net=require('node:net'),{spawn}=require('node:child_process'),{_electron}=require('playwright');
const evidence=process.argv[2],executablePath=process.argv[3],port=Number(process.argv[4]||8786),root=path.resolve(__dirname,'../..');
if(!evidence||!path.isAbsolute(evidence)||fs.existsSync(evidence)||!executablePath||!path.isAbsolute(executablePath)||!fs.existsSync(executablePath)||!Number.isInteger(port)||port<8772||port>8799)throw Error('Fresh F: evidence, packaged EXE and isolated port required');
if(process.platform==='win32'&&path.parse(path.resolve(evidence)).root.toLowerCase()!=='f:\\')throw Error('Evidence must use F:');
const origin='http://127.0.0.1:'+port,profile=path.join(evidence,'profile'),delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,label,timeout=20000){const deadline=Date.now()+timeout;while(Date.now()<deadline){if(await check())return;await delay(100);}throw Error('Timed out: '+label);}
async function available(){const probe=net.createServer();await new Promise((resolve,reject)=>{probe.once('error',reject);probe.listen({host:'127.0.0.1',port,exclusive:true},resolve);});await new Promise(resolve=>probe.close(resolve));}
const bootstrap=String.raw`
import asyncio, copy, json, os, sys, time
sys.path.insert(0, sys.argv.pop(1))
os.environ.pop('PRODUCER_DESKTOP_DATA_ROOT',None)
os.environ.pop('PRODUCER_DESKTOP_PYTHON',None)
import httpx
from fastapi import Request
from tools.qa_native_desktop_fixture import main
from rareiq.services.youtube_account_service import YouTubeAccountService
from rareiq.services.youtube_destination_service import CHANNELS_URL, BROADCASTS_URL, STREAMS_URL
state = {'renamed':False, 'delay':False, 'pending':0, 'calls':[], 'provider_writes':0}
record = {'client_id':'synthetic-native.apps.googleusercontent.com', 'channel_id':'UC'+'a'*22,
 'token_type':'bearer', 'access_token':'synthetic-private-native-token',
 'scopes':[YouTubeAccountService.SCOPE], 'expires_at':time.time()+3600}
ref = YouTubeAccountService.account_ref(record)
class Owner:
 async def with_stream_info_access(self, operation, *, require_edit=False):
  assert require_edit is False
  return await operation(copy.deepcopy(record), lambda:None)
async def provider(request):
 assert request.method == 'GET', 'Provider mutation forbidden'
 endpoint = str(request.url.copy_with(query=None))
 assert endpoint in (CHANNELS_URL,BROADCASTS_URL,STREAMS_URL)
 state['calls'].append({'method':request.method,'path':request.url.path})
 if state['delay']:
  state['delay']=False;state['pending']+=1
  try: await asyncio.sleep(2)
  finally: state['pending']-=1
 if endpoint == CHANNELS_URL:
  return httpx.Response(200,json={'items':[{'id':record['channel_id']}]})
 if endpoint == BROADCASTS_URL:
  return httpx.Response(200,json={'items':[{'id':'native-exact-broadcast',
   'snippet':{'channelId':record['channel_id'],'title':'Renamed synthetic broadcast' if state['renamed'] else 'Synthetic exact broadcast'},
   'status':{'lifeCycleStatus':'ready','privacyStatus':'unlisted'},
   'contentDetails':{'boundStreamId':'native-exact-stream','enableAutoStart':True,'enableAutoStop':False}}]})
 return httpx.Response(200,json={'items':[{'id':'native-exact-stream','snippet':{'channelId':record['channel_id']},
  'status':{'streamStatus':'inactive'},'cdn':{'ingestionType':'rtmp','ingestionInfo':{
   'rtmpsIngestionAddress':'rtmps://a.rtmps.youtube.com/live2','streamName':'synthetic-private-native-key'}}}]})
def setup(server, fixture_root):
 service = server.youtube_destination_service
 service.owner=Owner();service.http_factory=lambda:httpx.AsyncClient(transport=httpx.MockTransport(provider))
 public={'platform':'youtube','state':'authorized','authorized':True,'streaming_authorized':True,
  'metadata_authorized':False,'app_configured':True,'account_ref':ref,'public_label':'Synthetic YouTube channel',
  'reason':'account_authorized','expires_at':time.time()+3600}
 server.youtube_account_service.status=lambda:dict(public)
 async def check(): return dict(public)
 server.youtube_account_service.check=check
 @server.app.get('/__qa__/youtube-native')
 async def marker(): return {'isolated':True,'provider_writes':state['provider_writes'],'pending':state['pending'],'calls':list(state['calls'])}
 @server.app.post('/__qa__/youtube-native')
 async def mode(request:Request):
  body=await request.json();assert isinstance(body,dict) and set(body)=={'mode'}
  assert body['mode'] in ('renamed','delayed','normal')
  if body['mode']=='renamed':state['renamed']=True
  state['delay']=body['mode']=='delayed'
  return {'ok':True}
main(rehearsal=True,extra_setup=setup,extra_api_paths=('/api/production/accounts',))
`;
async function main(){
 await available();fs.mkdirSync(evidence,{recursive:false});let server,app,settings;
 const result={passed:false,actualPackagedMain:true,originalRouter:true,originalSelectionService:true,windowsEncryptedStore:true,syntheticProvider:true,realCredentials:false,realProvider:false,providerWrites:0,mediaTransport:false,physicalCapture:false,guards:[]};
 const marker=()=>fetch(origin+'/__qa__/youtube-native',{signal:AbortSignal.timeout(3000)}).then(response=>response.json());
 const mode=async value=>assert.equal((await fetch(origin+'/__qa__/youtube-native',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mode:value})}).then(response=>response.json())).ok,true);
 const guards=async()=>{const value=await app.evaluate(()=>{const qa=__youtubeDestinationNative;return {external:qa.external,externalWindows:qa.externalWindows,capture:qa.capture,permissions:qa.permissions,forbiddenControls:qa.forbiddenControls};});for(const [name,count] of Object.entries(value))assert.equal(count,0,name);result.guards.push(value);};
 async function launch(){
  const instance=await _electron.launch({executablePath,args:[],env:{...process.env,PRODUCER_DESKTOP_QA_ORIGIN:origin,PRODUCER_DESKTOP_QA_PROFILE:profile}});instance.context().setDefaultTimeout(20000);
  await instance.evaluate(({app,BrowserWindow,shell,dialog,desktopCapturer,ipcMain},origin)=>{
   const qa=globalThis.__youtubeDestinationNative={external:0,externalWindows:0,capture:0,permissions:0,forbiddenControls:0,links:[]};shell.openExternal=async()=>{qa.externalWindows++;throw Error('External navigation forbidden');};desktopCapturer.getSources=async()=>{qa.capture++;throw Error('Physical capture forbidden');};dialog.showMessageBox=async()=>{throw Error('No account, permission or broadcast confirmation expected');};
   const install=contents=>{contents.session.setPermissionCheckHandler(()=>false);contents.session.setPermissionRequestHandler((_contents,_permission,callback)=>{qa.permissions++;callback(false);});contents.session.setDisplayMediaRequestHandler((_request,callback)=>{qa.capture++;callback(null);});contents.session.webRequest.onBeforeRequest((details,callback)=>{const url=new URL(details.url),file=['file:','data:','blob:','devtools:'].includes(url.protocol),local=url.origin===origin||url.origin===origin.replace('http:','ws:');if(!file&&!local)qa.external++;callback({cancel:!file&&!local});});};app.on('web-contents-created',(_event,contents)=>install(contents));for(const window of BrowserWindow.getAllWindows())install(window.webContents);
   for(const channel of ['producer:broadcast:prepare','producer:broadcast:start','producer:broadcast:stop-target','producer:broadcast:audio','producer:output:view']){ipcMain.removeHandler(channel);ipcMain.handle(channel,()=>{qa.forbiddenControls++;throw Error('Capture and transmission forbidden');});}
  },origin);
  const studio=await instance.firstWindow();await studio.waitForURL(origin+'/control?workspace=studio&desktop=1');assert.equal(path.resolve(await instance.evaluate(({app})=>app.getPath('userData'))).toLowerCase(),path.resolve(profile).toLowerCase());const opened=instance.waitForEvent('window');await studio.evaluate(()=>producerDesktop.openBroadcastSettings());const panel=await opened;await panel.waitForFunction(()=>typeof producerSettings.youtubeDestinations==='function');
  await instance.evaluate(({ipcMain})=>{const channel='producer:youtube-destinations',original=ipcMain._invokeHandlers.get(channel);if(typeof original!=='function')throw Error('Original YouTube Main handler missing');ipcMain.removeHandler(channel);ipcMain.handle(channel,async(event,value)=>{if(value?.action==='link')__youtubeDestinationNative.links.push(JSON.parse(JSON.stringify(value)));return original(event,value);});});return {instance,panel};
 }
 const privateStore=()=>app.evaluate(async({app,safeStorage})=>{
  const fs=process.getBuiltinModule('node:fs'),path=process.getBuiltinModule('node:path'),raw=fs.readFileSync(path.join(app.getPath('userData'),'destinations.json'),'utf8'),saved=JSON.parse(raw);if(/accountRef|youtubeSelection|serverUrl|streamKey|synthetic-private/.test(raw))throw Error('Private destination fields leaked into plaintext');
  const decrypted=await safeStorage.decryptStringAsync(Buffer.from(saved.profiles[0].encrypted,'base64')),clear=JSON.parse(typeof decrypted==='string'?decrypted:decrypted.result),binding=clear.youtubeSelection;
  return {profiles:saved.profiles.length,receipts:saved.receipts.length,encryptedReferenceOnly:Object.keys(clear).sort().join(',')==='accountRef,allowInsecureRtmp,id,platform,youtubeSelection',exactBinding:binding.broadcastId==='native-exact-broadcast'&&binding.streamId==='native-exact-stream'&&/^[a-f0-9]{64}$/.test(binding.settingsFingerprint)&&/^[a-f0-9]{64}$/.test(clear.accountRef),privacyPinned:binding.privacyStatus==='unlisted'&&binding.autoStart===true&&binding.autoStop===false,noIngestStored:!Object.hasOwn(clear,'serverUrl')&&!Object.hasOwn(clear,'streamKey'),raw};
 });
 try{
  server=spawn(path.join(root,'.venv/Scripts/python.exe'),['-B','-c',bootstrap,root,path.join(evidence,'server'),String(port)],{cwd:root,windowsHide:true,stdio:['ignore','ignore','ignore'],env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'}});
  await until(async()=>{if(server.exitCode!==null)throw Error('Owned synthetic backend exited');try{return (await marker()).isolated===true;}catch(_){return false;}},'isolated original router fixture');
  let opened=await launch();app=opened.instance;settings=opened.panel;
  await settings.locator('[name="name"]').fill('Keep this manual destination draft');await until(()=>settings.locator('[data-youtube-load]').isEnabled(),'YouTube account enables exact selection');await settings.locator('[data-youtube-load]').click();await until(()=>settings.locator('[data-youtube-inspect]').isEnabled(),'existing broadcast list');await settings.locator('[data-youtube-inspect]').click();await settings.locator('[data-youtube-review]').waitFor({state:'visible'});assert.match(await settings.locator('[data-youtube-privacy]').textContent(),/Unlisted/);await settings.locator('[data-youtube-save]').click();await settings.locator('[data-youtube-status]').filter({hasText:'YouTube destination saved'}).waitFor();
  let status=await settings.evaluate(()=>producerSettings.status());assert.equal(status.destinations.length,1);const destination=status.destinations[0],id=destination.id;assert.equal(destination.platform,'youtube');assert.equal(destination.linkedAccount,true);assert.equal(destination.configured,true);assert.equal(destination.serverConfigured,false);assert.equal(destination.youtubePrivacyStatus,'unlisted');assert.equal(destination.verified,false);assert.equal(await settings.locator('[name="name"]').inputValue(),'Keep this manual destination draft');
  const exactRequest=await app.evaluate(()=>__youtubeDestinationNative.links[0]);assert.equal(exactRequest.action,'link');let stored=await privateStore();for(const key of ['encryptedReferenceOnly','exactBinding','privacyPinned','noIngestStored'])assert.equal(stored[key],true);const initialRaw=stored.raw;delete stored.raw;result.privateStore=stored;await settings.screenshot({path:path.join(evidence,'saved-youtube-destination.png'),fullPage:true});
  await guards();await app.close();app=null;await mode('renamed');opened=await launch();app=opened.instance;settings=opened.panel;status=await settings.evaluate(()=>producerSettings.status());assert.equal(status.destinations[0].id,id);const replay=await settings.evaluate(value=>producerSettings.youtubeDestinations(value),exactRequest);assert.equal(replay.ok,true);assert.equal(replay.destination.id,id);assert.equal(replay.destination.name,destination.name);assert.equal((await privateStore()).raw,initialRaw,'exact retry after title change must replay without a new write');
  const inspected=await settings.evaluate(()=>producerSettings.youtubeDestinations({action:'inspect',broadcastId:'native-exact-broadcast'}));assert.equal(inspected.selection.title,'Renamed synthetic broadcast');const dedup=await settings.evaluate(value=>producerSettings.youtubeDestinations(value),{...exactRequest,requestId:'native-youtube-dedup-after-reopen'});assert.equal(dedup.ok,true);assert.equal(dedup.destination.id,id);assert.equal((await settings.evaluate(()=>producerSettings.status())).destinations.length,1);
  const callsBefore=(await marker()).calls.length,untrustedWindow=app.waitForEvent('window'),untrustedId=await app.evaluate(async({BrowserWindow})=>{const path=process.getBuiltinModule('node:path'),window=new BrowserWindow({show:false,webPreferences:{sandbox:true,contextIsolation:true,nodeIntegration:false,preload:path.join(process.resourcesPath,'app.asar','settings-preload.cjs')}});await window.loadURL('data:text/html,<title>Untrusted selection</title>');return window.id;});const untrusted=await untrustedWindow;
  for(const value of [{action:'list'},{action:'inspect',broadcastId:'native-exact-broadcast'},exactRequest,{action:'cancel'}])assert.equal((await untrusted.evaluate(value=>producerSettings.youtubeDestinations(value),value)).reason,'local_operator_required');assert.equal((await marker()).calls.length,callsBefore);await app.evaluate(({BrowserWindow},id)=>BrowserWindow.fromId(id)?.destroy(),untrustedId);
  await mode('delayed');const cancelled=settings.evaluate(()=>producerSettings.youtubeDestinations({action:'inspect',broadcastId:'native-exact-broadcast'}));await until(async()=>(await marker()).pending>0,'awaited synthetic read');assert.equal((await settings.evaluate(()=>producerSettings.youtubeDestinations({action:'cancel'}))).cancelled,true);assert.equal((await cancelled).reason,'selection_cancelled');
  const beforeStale=(await privateStore()).raw;await mode('delayed');const stale=settings.evaluate(value=>producerSettings.youtubeDestinations(value),{...exactRequest,requestId:'native-stale-selection'}).catch(()=>null);await until(async()=>(await marker()).pending>0,'stale frame read in progress');await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows().find(window=>window.webContents.getURL().startsWith('file:')&&window.webContents.getURL().endsWith('/settings.html'))?.destroy());await stale;await until(async()=>(await marker()).pending===0,'stale frame read completes');await delay(200);
  await guards();await app.close();app=null;opened=await launch();app=opened.instance;settings=opened.panel;assert.equal((await privateStore()).raw,beforeStale,'destroyed settings frame cannot persist an awaited link');await guards();
  const proof=await marker();assert.equal(proof.provider_writes,0);assert.ok(proof.calls.length>0&&proof.calls.every(call=>call.method==='GET'));result.providerGets=proof.calls.length;result.reopened=true;result.exactRetryAfterRename=true;result.deduplicated=true;result.cancellationGuard=true;result.untrustedAndStaleFrameGuards=true;result.manualDraftPreserved=true;result.passed=true;
 }catch(error){result.error=error.message;if(settings&&!settings.isClosed())await settings.screenshot({path:path.join(evidence,'failure.png'),fullPage:true}).catch(()=>{});throw error;}
 finally{if(app)await app.close().catch(()=>{});if(server){const closed=new Promise(resolve=>{if(server.exitCode!==null)return resolve();server.once('close',resolve);});server.kill();await Promise.race([closed,delay(3000)]);result.ownedFixtureStopped=server.exitCode!==null||server.signalCode!==null;}if(result.passed&&!result.ownedFixtureStopped){result.passed=false;result.error='owned_fixture_cleanup_unconfirmed';process.exitCode=1;}fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2),{flag:'wx'});}
 console.log(JSON.stringify({passed:result.passed,actualPackagedMain:true,encryptedSelection:true,providerWrites:0,mediaTransport:false,physicalCapture:false}));
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
