/* Original packaged Main/IPC/Settings with intercepted account HTTP only.
   No provider request, browser consent, credential, media or real message. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),net=require('node:net'),assert=require('node:assert/strict'),{_electron}=require('playwright');
const directory=process.argv[2],executable=process.argv[3],port=Number(process.argv[4]||8789),origin='http://127.0.0.1:'+port;
if(!directory||!path.isAbsolute(directory)||!/^f:/i.test(directory)||fs.existsSync(directory)||!executable||!path.isAbsolute(executable)||!Number.isInteger(port)||port<8772||port>8799)throw Error('Fresh F: evidence, tested EXE and unused isolated port required');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function main(){
 const probe=net.createServer();await new Promise((resolve,reject)=>{probe.once('error',reject);probe.listen({host:'127.0.0.1',port,exclusive:true},resolve);});await new Promise(resolve=>probe.close(resolve));fs.mkdirSync(directory,{recursive:false});
 const profile=path.join(directory,'profile'),env={};for(const key of ['SystemRoot','WINDIR','COMSPEC','USERPROFILE','LOCALAPPDATA','APPDATA','USERNAME','USERDOMAIN','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE'])if(process.env[key])env[key]=process.env[key];Object.assign(env,{PATH:process.env.SystemRoot+'\\System32;'+process.env.SystemRoot,TEMP:directory,TMP:directory,PRODUCER_DESKTOP_QA_PROFILE:profile,PRODUCER_DESKTOP_QA_PORT:String(port)});
 const result={passed:false,actualPackagedMain:true,actualNativeIpc:true,actualSettings:true,accountHttpIntercepted:true,realAuthorization:false,realCredentials:false,providerPosts:false,media:false,flows:[]};let app;
 try{
  app=await _electron.launch({executablePath:executable,args:['--preview'],env});app.context().setDefaultTimeout(15000);
  await app.evaluate(({app,BrowserWindow,shell,dialog},config)=>{
   const path=process.getBuiltinModule('node:path'),require=process.getBuiltinModule('node:module').createRequire(path.join(process.resourcesPath,'app.asar/package.json')),qa=globalThis.__replyConsentQa={outside:0,external:0,permissions:0,encoder:0,provider:0,dialogs:0,calls:[],approved:{},pending:{}};
   if(BrowserWindow.getAllWindows().length)throw Error('Guards must precede app windows');
   const platforms=['twitch','youtube','kick'],base=platform=>({platform,state:'authorized',reason:'account_authorized',expires_at:Date.now()/1000+3600,authorized:true,streaming_authorized:true,metadata_authorized:false,chat_reply_authorized:qa.approved[platform]===true,app_configured:true,public_label:platform==='twitch'?'synthetic_channel':'Synthetic '+platform,account_ref:'a'.repeat(64)});
   const publicAccount=platform=>qa.pending[platform]?{...base(platform),state:'pending',reason:'authorization_pending',authorization_kind:'replies',flow_id:platform==='twitch'?'a'.repeat(32):platform==='youtube'?'b'.repeat(32):'c'.repeat(32),...(platform==='twitch'?{user_code:'REPLY-CODE',verification_url:'https://www.twitch.tv/activate'}:{})}:base(platform);
   const fetch=globalThis.fetch;globalThis.fetch=async(url,options={})=>{
    const parsed=new URL(url);if(parsed.origin!==config.origin){qa.outside++;throw Error('Provider/network forbidden');}
    if(parsed.pathname==='/api/production/accounts'||parsed.pathname.startsWith('/api/production/accounts/')){
     const fields=parsed.pathname.split('/').slice(4),platform=fields[0],action=fields.slice(1).join('/');let body;
     if(!platform){if((options.method||'GET')!=='GET')throw Error('Status only');body={ok:true,accounts:platforms.map(publicAccount)};}
     else{if(!platforms.includes(platform)||!['check','cancel','replies/begin'].includes(action))throw Error('Unexpected account action');qa.calls.push({platform,action});if(action==='replies/begin')qa.pending[platform]=true;if(action==='cancel')qa.pending[platform]=false;body={ok:true,account:publicAccount(platform)};}
     const response=new Response(JSON.stringify(body),{status:200,headers:{'Content-Type':'application/json'}});Object.defineProperty(response,'url',{value:String(url)});return response;
    }
    if(parsed.pathname.endsWith('/viewer-chat/reply')){qa.provider++;throw Error('No message may be posted');}return fetch(url,options);
   };
   for(const [file,name]of [['twitch-connection.cjs','createTwitchResolver'],['kick-connection.cjs','createKickResolver'],['youtube-connection.cjs','createYouTubeResolver']])require(path.join(process.resourcesPath,'app.asar',file))[name]=()=>async()=>{qa.provider++;throw Error('Private credential lookup forbidden');};
   for(const [file,klass]of [['encoder.cjs','Encoder'],['shared-encoder.cjs','SharedEncoderGroup']])require(path.join(process.resourcesPath,'app.asar',file))[klass].prototype.start=async()=>{qa.encoder++;throw Error('Media forbidden');};
   shell.openExternal=async()=>{qa.external++;throw Error('Owner alone opens consent');};dialog.showSaveDialog=async()=>{qa.dialogs++;throw Error('No file chooser');};dialog.showMessageBox=async()=>{qa.dialogs++;return {response:0};};
   app.on('web-contents-created',(_event,contents)=>{contents.session.setPermissionCheckHandler(()=>false);contents.session.setPermissionRequestHandler((_c,_p,done)=>{qa.permissions++;done(false);});contents.session.setDisplayMediaRequestHandler((_r,done)=>{qa.permissions++;done(null);});contents.session.webRequest.onBeforeRequest((details,done)=>{const url=new URL(details.url),local=url.origin===config.origin||url.origin===config.origin.replace('http:','ws:'),file=['file:','data:','blob:','devtools:'].includes(url.protocol);if(!local&&!file)qa.outside++;done({cancel:!local&&!file});});});
  },{origin});
  const studio=await app.firstWindow();await studio.waitForURL(origin+'/control?workspace=studio&desktop=1',{timeout:90000});await studio.locator('#instantSplash').waitFor({state:'hidden'});assert.equal(path.resolve(await app.evaluate(({app})=>app.getPath('userData'))),path.resolve(profile));
  const opening=app.waitForEvent('window');await studio.locator('[data-viewer-enable-replies]').click();const settings=await opening;await settings.waitForFunction(()=>typeof producerSettings.twitchAccount==='function');
  for(const platform of ['twitch','youtube','kick']){
   const button=settings.locator('#'+platform+'EnableReplies');await button.waitFor({state:'visible'});await button.click();await settings.waitForFunction(p=>document.querySelector('#'+p+'Pending')?.hidden===false,platform);
   const pending=await settings.evaluate(async p=>p==='twitch'?producerSettings.twitchAccount({action:'status'}):producerSettings.providerAccount({platform:p,action:'status'}),platform);assert.equal(pending.account.authorization_kind,'replies');assert.equal(pending.account.authorized,true);assert.equal(pending.account.streaming_authorized,true);assert.equal(pending.account.chat_reply_authorized,false);
   assert.equal(await settings.locator('#'+platform+'Cancel').isEnabled(),true);if(platform==='twitch')assert.match(await settings.locator('#twitchCode').textContent(),/REPLY-CODE/);else assert.equal(await settings.locator('#'+platform+'Authorize').isVisible(),true);
   await settings.screenshot({path:path.join(directory,platform+'-native-pending.png'),fullPage:false});await settings.locator('#'+platform+'Cancel').click();await button.waitFor({state:'visible'});
   await app.evaluate((_electron,p)=>{__replyConsentQa.approved[p]=true;},platform);await settings.locator('#'+platform+'Check').click();await button.waitFor({state:'hidden'});const approved=await settings.evaluate(async p=>p==='twitch'?producerSettings.twitchAccount({action:'status'}):producerSettings.providerAccount({platform:p,action:'status'}),platform);assert.equal(approved.account.chat_reply_authorized,true);result.flows.push({platform,nativeBeginRoute:true,pendingPurpose:true,cancelPreservesPriorStreaming:true,publicApprovedFlag:true,consentNeverOpened:true});
  }
  const guards=await app.evaluate(()=>({outside:__replyConsentQa.outside,external:__replyConsentQa.external,permissions:__replyConsentQa.permissions,encoder:__replyConsentQa.encoder,provider:__replyConsentQa.provider,dialogs:__replyConsentQa.dialogs,calls:__replyConsentQa.calls}));for(const key of ['outside','external','permissions','encoder','provider','dialogs'])assert.equal(guards[key],0,key);for(const platform of ['twitch','youtube','kick'])assert.equal(guards.calls.filter(call=>call.platform===platform&&call.action==='replies/begin').length,1);result.guards=guards;result.passed=true;
 }catch(error){result.error=error.message;throw error;}
 finally{if(app)await app.close().catch(()=>{});await delay(250);try{const response=await fetch(origin+'/api/desktop/status',{signal:AbortSignal.timeout(1000)});if(response.ok)throw Error('Owned backend remained running');result.backendStopped=true;}catch(error){if(error.message==='Owned backend remained running'){result.cleanupError=error.message;process.exitCode=1;}else result.backendStopped=true;}fs.writeFileSync(path.join(directory,'results.json'),JSON.stringify(result,null,2));}
 console.log(JSON.stringify({passed:result.passed,nativeFlows:result.flows.length,realAuthorization:false,providerPosts:false,backendStopped:result.backendStopped}));
}
main().catch(error=>{console.error(error.stack);process.exitCode=1;});
