const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {createController,normalize,account,googleAuthorizationUrl,VERIFY_URL}=require('../../rareiq/web/static/platform_accounts.js');
const accountSource=fs.readFileSync(require.resolve('../../rareiq/web/static/platform_accounts.js'),'utf8'),viewerSource=fs.readFileSync(require.resolve('../../rareiq/web/static/viewer_chat.js'),'utf8');
const NOW=1700000000,settle=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
const twitch=(extra={})=>({platform:'twitch',state:'not_authorized',reason:'authorization_required',authorized:false,app_configured:true,...extra});
const pending=(extra={})=>twitch({state:'pending',reason:'authorization_pending',flow_id:'a'.repeat(32),user_code:'ABCD-1234',verification_url:VERIFY_URL,expires_at:NOW+600,...extra});
const authorized=(extra={})=>twitch({state:'authorized',reason:'account_authorized',authorized:true,public_label:'Broadcaster',expires_at:NOW+3600,...extra});
const youtube=(extra={})=>({platform:'youtube',state:'not_authorized',reason:'authorization_required',authorized:false,app_configured:true,...extra});
const youtubePending=(extra={})=>youtube({state:'pending',reason:'authorization_pending',flow_id:'b'.repeat(32),expires_at:NOW+600,...extra});
const googleUrl=(extra={})=>'https://accounts.google.com/o/oauth2/v2/auth?'+new URLSearchParams({client_id:'test-client.apps.googleusercontent.com',redirect_uri:'http://127.0.0.1:54321/callback',response_type:'code',scope:'https://www.googleapis.com/auth/youtube.readonly',access_type:'offline',prompt:'consent',state:'s'.repeat(43),code_challenge:'c'.repeat(43),code_challenge_method:'S256',...extra});
const accounts=(value,youtubeValue={platform:'youtube',state:'unavailable',reason:'youtube_sign_in_setup_required'})=>({accounts:[value,youtubeValue,{platform:'kick',state:'unavailable',reason:'kick_public_callback_required'}]});
const response=(body,status=200)=>({ok:status<400,status,json:async()=>body});
function fixture(options={}){
  let handler=async()=>response(accounts(twitch())),serial=0,clock=NOW;const requests=[],timers=new Map(),changes=[];
  const config={now:()=>clock,setTimeout(fn,delay){const id=++serial;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},fetch(url,init){requests.push({url,init});return handler(url,init);},onChange:state=>changes.push(state),...options};
  const controller=createController(config),fire=async(delay=5000)=>{const entry=[...timers].find(([,timer])=>timer.delay===delay);if(entry){timers.delete(entry[0]);entry[1].fn();}await settle();};
  return {controller,requests,timers,changes,config,fire,setNow(value){clock=value;},setHandler(fn){handler=fn;}};
}
function uiFixture({viewer=false,accountValue=twitch(),youtubeValue,authorizeAccount,onUse=()=>{}}={}){
  let doc,serial=0;const all=[],requests=[],timers=new Map();
  class Element{
    constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.listeners={};this.textContent='';this.hidden=false;this.disabled=false;this.open=false;this.scrollTop=0;this.scrollHeight=100;this.clientHeight=100;this.ownerDocument=doc;all.push(this);}
    setAttribute(name,value){this.attributes[name]=value;if(name.startsWith('data-'))this.dataset[name.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;}
    append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}}
    remove(){if(this.parent)this.parent.children=this.parent.children.filter(node=>node!==this);this.parent=null;}
    replaceChildren(...nodes){this.children=[];this.append(...nodes);}
    addEventListener(name,fn){this.listeners[name]=fn;}
    focus(){doc.activeElement=this;}
    showModal(){this.open=true;}
    close(){this.open=false;this.dispatch('close');}
    dispatch(name,extra={}){if(this.disabled&&name==='click')return;return this.listeners[name]?.({preventDefault(){},...extra});}
  }
  doc={createElement:tag=>new Element(tag),activeElement:null};doc.body=new Element('body');doc.activeElement=doc.body;
  const feed={active:false,session_id:'a'.repeat(32),cursor:0,reset:true,messages:[],sources:[{platform:'twitch',implemented:true,state:'not_connected',reason:'credentials_required'}]};
  const host={document:doc,location:{hostname:'127.0.0.1'},URL,URLSearchParams,AbortController,setTimeout(fn,delay){const id=++serial;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},addEventListener(){},removeEventListener(){},fetch:async(url,init)=>{requests.push({url,init});if(url.startsWith('/api/production/viewer-chat?'))return response(feed);if(url==='/api/production/accounts')return response(accounts(accountValue,youtubeValue));return response({account:accountValue});}};host.window=host;vm.runInNewContext(accountSource,host);
  const api=viewer?(vm.runInNewContext(viewerSource,host),host.ProducerViewerChat.mount(doc.body,{now:()=>NOW})):host.ProducerPlatformAccounts.mount(doc.body,{now:()=>NOW,onUse,authorizeAccount});
  const get=(attribute,value)=>all.find(node=>Object.hasOwn(node.attributes,attribute)&&(value===undefined||node.attributes[attribute]===value));return {api,doc,all,get,requests,timers};
}

test('accounts stay lazy until open and read status every five seconds without beginning consent',async()=>{
  const f=fixture();assert.equal(f.requests.length,0);await f.controller.open();assert.equal(f.requests.length,1);assert.equal(f.requests[0].url,'/api/production/accounts');await f.fire();assert.equal(f.requests.length,2);assert.equal(f.requests.some(request=>request.init.method==='POST'),false);f.controller.close();assert.equal(f.timers.size,0);
});

test('missing developer app setup blocks Begin and gives a plain explanation',async()=>{
  const f=fixture();f.setHandler(async()=>response(accounts(twitch({app_configured:false,reason:'app_setup_required'}))));await f.controller.open();assert.equal(await f.controller.run('begin'),false);assert.equal(f.requests.length,1);
  const ui=uiFixture({accountValue:twitch({app_configured:false,reason:'app_setup_required'})});ui.api.open();await settle();assert.equal(ui.get('data-accounts-begin').disabled,true);assert.match(ui.get('data-account-note','twitch').textContent,/one-time app setup/);assert.doesNotMatch(ui.get('data-account-note','twitch').textContent,/client.?id|environment|secret/i);
});

test('pending codes accept only the fixed Twitch URL and bounded literal codes',()=>{
  for(const verification_url of ['https://twitch.tv.evil.test/activate','javascript:alert(1)','https://www.twitch.tv/activate?token=private']){const value=account(pending({verification_url}),NOW);assert.equal(value.state,'unavailable');assert.equal(value.user_code,undefined);assert.equal(value.verification_url,undefined);}
  for(const user_code of ['<img src=x onerror=alert(1)>','A'.repeat(33),'abcd\n1234'])assert.equal(account(pending({user_code}),NOW).state,'unavailable');
  assert.equal(account(pending(),NOW).verification_url,VERIFY_URL);assert.equal(normalize(accounts(twitch()),NOW).length,3);
});

test('duplicate Begin is serialized and explicit Cancel invalidates an unresolved Begin without losing stored authorization',async()=>{
  const f=fixture();await f.controller.open();let complete;f.setHandler(async(url)=>url.endsWith('/begin')?new Promise(resolve=>complete=resolve):response({account:authorized()}));const begin=f.controller.run('begin');assert.equal(await f.controller.run('begin'),false);const beginRequest=f.requests.at(-1);await f.controller.run('cancel');assert.equal(beginRequest.init.signal.aborted,true);complete(response({account:pending()}));await begin;
  assert.equal(f.controller.snapshot().accounts[0].state,'authorized');assert.match(f.controller.snapshot().status,/previously saved account is kept/);const posts=f.requests.filter(request=>request.init.method==='POST');assert.equal(posts.length,2);assert.ok(posts.every(request=>request.init.body==='{}'));assert.equal(posts[1].url,'/api/production/accounts/twitch/cancel');
});

test('closing pending consent clears code and timers without cancelling or forgetting the stored account',async()=>{
  const f=fixture();f.setHandler(async()=>response(accounts(pending())));await f.controller.open();assert.equal(f.controller.snapshot().accounts[0].state,'pending');f.controller.close();assert.equal(f.controller.snapshot().accounts.length,0);assert.equal(f.timers.size,0);assert.equal(f.requests.some(request=>request.init.method==='POST'),false);
});

test('closing or reopening ignores delayed old reads and never restores an old code',async()=>{
  const f=fixture();let complete;f.setHandler(()=>new Promise(resolve=>complete=resolve));const first=f.controller.open(),request=f.requests[0];f.controller.close();assert.equal(request.init.signal.aborted,true);f.setHandler(async()=>response(accounts(twitch())));await f.controller.open();complete(response(accounts(pending())));await first;assert.equal(f.controller.snapshot().accounts[0].state,'not_authorized');assert.equal(f.controller.snapshot().accounts[0].user_code,undefined);
});

test('code expiry clears code locally and polling never starts another consent flow',async()=>{
  const f=fixture();f.setHandler(async()=>response(accounts(pending({expires_at:NOW+5}))));await f.controller.open();f.setNow(NOW+6);await f.fire();const value=f.controller.snapshot().accounts[0];assert.equal(value.state,'not_authorized');assert.equal(value.reason,'authorization_expired');assert.equal(value.user_code,undefined);assert.equal(f.requests.some(request=>request.init.method==='POST'),false);
});

test('a code expiring before the next normal poll disappears even when the status read stalls',async()=>{
  const f=fixture();f.setHandler(async()=>response(accounts(pending({expires_at:NOW+1}))));await f.controller.open();assert.ok([...f.timers.values()].some(timer=>timer.delay===1000));let complete;f.setHandler(()=>new Promise(resolve=>complete=resolve));f.setNow(NOW+2);await f.fire(1000);
  assert.equal(f.changes.at(-1).accounts[0].state,'not_authorized');assert.equal(f.changes.at(-1).accounts[0].user_code,undefined);complete(response(accounts(twitch())));await settle();f.controller.close();
});

test('clipboard failures offer manual copy and a late clipboard result cannot restore a closed dialog',async()=>{
  const f=fixture({copy:async()=>{throw Error('private clipboard detail');}});f.setHandler(async()=>response(accounts(pending())));await f.controller.open();assert.equal(await f.controller.copy(),false);assert.match(f.controller.snapshot().status,/Select the code/);assert.doesNotMatch(f.controller.snapshot().status,/private/);
  let complete;const slow=fixture({copy:()=>new Promise(resolve=>complete=resolve)});slow.setHandler(async()=>response(accounts(pending())));await slow.controller.open();const copy=slow.controller.copy();slow.controller.close();complete();await copy;assert.equal(slow.controller.snapshot().status,'');assert.equal(slow.controller.snapshot().accounts.length,0);
});

test('an authorized account connects chat only on explicit Use and duplicate clicks are blocked',async()=>{
  let uses=0,complete;const f=fixture({onUse:()=>{uses++;return new Promise(resolve=>complete=resolve);}});f.setHandler(async()=>response(accounts(authorized())));await f.controller.open();await f.fire();assert.equal(uses,0);const use=f.controller.use('twitch');assert.equal(await f.controller.use('twitch'),false);assert.equal(uses,1);complete();assert.equal(await use,true);assert.equal(f.requests.some(request=>request.url.includes('/audience/')),false);
});

test('failed account refresh revokes Use and code display without exposing raw provider text',async()=>{
  const f=fixture();f.setHandler(async()=>response(accounts(authorized())));await f.controller.open();f.setHandler(async()=>{throw Error('private provider credential detail');});await f.fire();assert.equal(await f.controller.use('twitch'),false);assert.equal(f.controller.snapshot().stale,true);assert.doesNotMatch(f.controller.snapshot().status,/private|credential/);
});

test('dialog uses literal public labels, a constant external destination and native close focus restoration',async()=>{
  const ui=uiFixture({accountValue:authorized({public_label:'<script>display label</script>'})}),opener=ui.doc.createElement('button');opener.focus();ui.api.open(opener);await settle();assert.equal(ui.api.element.open,true);assert.ok(ui.all.some(node=>node.textContent==='Account ready · <script>display label</script>'));assert.equal(ui.get('data-accounts-link').attributes.href,VERIFY_URL);assert.equal(ui.get('data-accounts-link').attributes.rel,'noopener noreferrer');assert.equal(ui.get('data-accounts-pending').hidden,true);
  ui.api.element.dispatch('cancel');assert.equal(ui.api.element.open,false);assert.equal(ui.doc.activeElement,opener);assert.equal(ui.timers.size,0);assert.ok(ui.all.every(node=>!Object.hasOwn(node,'innerHTML')));
});

test('Viewer Manage accounts is lazy and its dialog never auto-begins sign-in',async()=>{
  const ui=uiFixture({viewer:true,accountValue:twitch({app_configured:false})});await settle();assert.equal(ui.requests.some(request=>request.url.includes('/accounts')),false);await ui.get('data-viewer-accounts').dispatch('click');await settle();assert.equal(ui.requests.filter(request=>request.url==='/api/production/accounts').length,1);assert.equal(ui.requests.some(request=>request.init.method==='POST'),false);assert.equal(ui.get('data-accounts-begin').disabled,true);ui.api.destroy();assert.equal(ui.timers.size,0);
});

test('Viewer preserves legacy Connect first and opens accounts only after missing authorization results',async()=>{
  const viewer=require('../../rareiq/web/static/viewer_chat.js');
  for(const code of [200,401]){const notices=[],requests=[],feed={active:false,session_id:'a'.repeat(32),cursor:0,reset:true,messages:[],sources:[]},controller=viewer.createController({fetch:async(url,init)=>{requests.push({url,init});return response(url.endsWith('/connect')?{reason:'credentials_required'}:feed,url.endsWith('/connect')?code:200);},setTimeout:()=>0,clearTimeout(){},onAccountRequired:platform=>notices.push(platform)});await controller.start();assert.equal(notices.length,0);assert.equal(await controller.run('connect','twitch'),false);assert.deepEqual(notices,['twitch']);assert.equal(requests.filter(request=>request.url.includes('/accounts')).length,0);assert.equal(requests.find(request=>request.url.endsWith('/connect')).init.body,'{}');controller.destroy();}
});

test('destroy aborts account requests and prevents late sign-in responses from restoring state',async()=>{
  const f=fixture();await f.controller.open();let complete;f.setHandler(()=>new Promise(resolve=>complete=resolve));const begin=f.controller.run('begin'),request=f.requests.at(-1);f.controller.destroy();assert.equal(request.init.signal.aborted,true);assert.equal(f.timers.size,0);complete(response({account:pending()}));await begin;assert.equal(f.controller.snapshot().open,false);assert.equal(f.controller.snapshot().accounts.length,0);
});

test('YouTube pending status has no code or authorization URL and requires a current bounded flow',()=>{
  const value=account(youtubePending({user_code:'DO-NOT-USE',authorization_url:'https://example.invalid/'}),NOW);assert.equal(value.state,'pending');assert.equal(value.user_code,undefined);assert.equal(value.authorization_url,undefined);assert.equal(value.flow_id,'b'.repeat(32));
  assert.equal(account(youtubePending({flow_id:'invalid'}),NOW).state,'unavailable');assert.equal(account(youtubePending({expires_at:NOW-1}),NOW).reason,'authorization_expired');
});

test('Google authorization validates exact readonly PKCE fields and a literal loopback callback',()=>{
  const valid=googleUrl();assert.equal(googleAuthorizationUrl(valid),valid);
  for(const url of [valid.replace('accounts.google.com','accounts.google.com.evil.test'),valid.replace('https://accounts.google.com/','https://accounts.google.com:443/'),valid+'#fragment',valid+'&state=duplicate',valid+'&unexpected=value',googleUrl({redirect_uri:'http://localhost:54321/callback'}),googleUrl({redirect_uri:'http://2130706433:54321/callback'}),googleUrl({redirect_uri:'http://127.0.0.1:80/callback'}),googleUrl({redirect_uri:'http://127.0.0.1:54321/callback?next=evil'}),googleUrl({scope:'https://www.googleapis.com/auth/youtube'}),googleUrl({code_challenge_method:'plain'}),googleUrl({state:'short'}),googleUrl({code_challenge:'short'}),googleUrl({client_id:'wrong-client.invalid'})])assert.equal(googleAuthorizationUrl(url),null);
});

test('YouTube Begin prepares a flow without opening Google and blocks cross-provider cancellation races',async()=>{
  let opened=0,complete;const f=fixture({authorizeAccount:async()=>{opened++;return {ok:true};}});f.setHandler(async()=>response(accounts(twitch(),youtube())));await f.controller.open();f.setHandler(url=>url.endsWith('/begin')?new Promise(resolve=>complete=resolve):Promise.resolve(response({account:youtube()})));
  const begin=f.controller.run('begin','youtube');assert.equal(await f.controller.run('begin','twitch'),false);assert.equal(await f.controller.run('cancel','twitch'),false);assert.equal(f.requests.at(-1).url,'/api/production/accounts/youtube/begin');assert.equal(f.requests.at(-1).init.body,'{}');complete(response({account:youtubePending()}));await begin;assert.equal(opened,0);assert.equal(f.controller.snapshot().accounts[1].state,'pending');
});

test('native Google opening sends only platform/flow, rejects duplicates, and does not connect chat',async()=>{
  let complete,uses=0;const calls=[],f=fixture({authorizeAccount:args=>{calls.push(args);return new Promise(resolve=>complete=resolve);},onUse:()=>{uses++;}});f.setHandler(async()=>response(accounts(twitch(),youtubePending())));await f.controller.open();assert.equal(calls.length,0);const opening=f.controller.openGoogle();assert.equal(await f.controller.openGoogle(),false);assert.equal(await f.controller.run('cancel','twitch'),false);assert.deepEqual(calls,[{platform:'youtube',flowId:'b'.repeat(32)}]);complete({ok:true});assert.equal(await opening,true);assert.equal(await f.controller.openGoogle(),false);assert.equal(uses,0);assert.equal(f.requests.filter(request=>request.url.includes('/authorization?')).length,0);
});

test('browser fallback reserves an unprivileged blank window and navigates only after current URL validation',async()=>{
  const navigations=[],windows=[],f=fixture({openWindow:(...args)=>{windows.push(args);return {opener:{},location:{replace:url=>navigations.push(url)},close(){assert.fail('successful Google window closed');}};}});f.setHandler(async()=>response(accounts(twitch(),youtubePending())));await f.controller.open();assert.equal(windows.length,0);f.setHandler(async()=>response({authorization_url:googleUrl()}));assert.equal(await f.controller.openGoogle(),true);assert.deepEqual(windows,[['about:blank','_blank']]);assert.deepEqual(navigations,[googleUrl()]);assert.equal(f.requests.at(-1).url,'/api/production/accounts/youtube/authorization?flow_id='+'b'.repeat(32));
});

test('invalid Google URL never navigates and closes the reserved window without leaking response text',async()=>{
  let closed=0,navigated=0;const f=fixture({openWindow:()=>({location:{replace(){navigated++;}},close(){closed++;}})});f.setHandler(async()=>response(accounts(twitch(),youtubePending())));await f.controller.open();f.setHandler(async()=>response({authorization_url:'https://private-secret.evil.test/'}));assert.equal(await f.controller.openGoogle(),false);assert.equal(navigated,0);assert.equal(closed,1);assert.doesNotMatch(f.controller.snapshot().status,/private-secret|evil/);
});

test('closing and reopening Google flows cannot navigate or close another flow reserved window',async()=>{
  const windows=[],completions=[],f=fixture({openWindow:()=>{const popup={closed:0,navigated:0,location:{replace(){popup.navigated++;}},close(){popup.closed++;}};windows.push(popup);return popup;}});f.setHandler(async()=>response(accounts(twitch(),youtubePending())));await f.controller.open();f.setHandler(()=>new Promise(resolve=>completions.push(resolve)));const first=f.controller.openGoogle();f.controller.close();assert.ok(windows[0].closed>0);
  f.setHandler(async()=>response(accounts(twitch(),youtubePending({flow_id:'c'.repeat(32)}))));await f.controller.open();f.setHandler(()=>new Promise(resolve=>completions.push(resolve)));const second=f.controller.openGoogle();completions[0](response({authorization_url:googleUrl()}));await first;assert.equal(windows[0].navigated,0);assert.equal(windows[1].closed,0);completions[1](response({authorization_url:googleUrl()}));assert.equal(await second,true);assert.equal(windows[1].navigated,1);assert.equal(windows[1].closed,0);
});

test('own-provider cancellation aborts Google authorization lookup and rejects its late URL',async()=>{
  let closed=0,navigated=0,complete;const f=fixture({openWindow:()=>({location:{replace(){navigated++;}},close(){closed++;}})});f.setHandler(async()=>response(accounts(twitch(),youtubePending())));await f.controller.open();f.setHandler((url,init)=>init.method==='POST'?Promise.resolve(response({account:youtube()})):new Promise(resolve=>complete=resolve));const opening=f.controller.openGoogle(),request=f.requests.at(-1);await f.controller.run('cancel','youtube');assert.equal(request.init.signal.aborted,true);assert.ok(closed>0);complete(response({authorization_url:googleUrl()}));assert.equal(await opening,false);assert.equal(navigated,0);assert.equal(f.controller.snapshot().accounts[1].state,'not_authorized');
});

test('expired or validating Google flows cannot be opened, while ready YouTube needs explicit Use',async()=>{
  let opens=0;const used=[],f=fixture({authorizeAccount:async()=>{opens++;return {ok:true};},onUse:platform=>used.push(platform)});f.setHandler(async()=>response(accounts(twitch(),youtubePending({reason:'validating_authorization'}))));await f.controller.open();assert.equal(await f.controller.openGoogle(),false);f.setHandler(async()=>response(accounts(twitch(),youtubePending({expires_at:NOW-1}))));await f.controller.refresh();assert.equal(await f.controller.openGoogle(),false);f.setHandler(async()=>response(accounts(twitch(),youtube({state:'authorized',authorized:true,public_label:'YouTube channel',expires_at:NOW+3600}))));await f.controller.refresh();assert.equal(opens,0);assert.equal(used.length,0);assert.equal(await f.controller.use('youtube'),true);assert.deepEqual(used,['youtube']);
});

test('YouTube dialog shows an explicit Google button without a code and uses safe native handoff',async()=>{
  const calls=[],ui=uiFixture({youtubeValue:youtubePending(),authorizeAccount:async args=>{calls.push(args);return {ok:true};}});ui.api.open();await settle();assert.equal(calls.length,0);assert.equal(ui.get('data-accounts-pending','youtube').hidden,false);assert.equal(ui.get('data-accounts-google-open').disabled,false);await ui.get('data-accounts-google-open').dispatch('click');assert.deepEqual(calls.map(value=>({...value})),[{platform:'youtube',flowId:'b'.repeat(32)}]);assert.equal(ui.get('data-accounts-google-open').disabled,true);assert.equal(ui.get('data-accounts-code').textContent,'');
});

test('Google flow expiry during lookup closes its blank window and rejects the late destination',async()=>{
  let complete,closed=0,navigated=0;const f=fixture({openWindow:()=>({location:{replace(){navigated++;}},close(){closed++;}})});f.setHandler(async()=>response(accounts(twitch(),youtubePending({expires_at:NOW+1}))));await f.controller.open();f.setHandler(()=>new Promise(resolve=>complete=resolve));const opening=f.controller.openGoogle();f.setNow(NOW+2);complete(response({authorization_url:googleUrl()}));assert.equal(await opening,false);assert.equal(navigated,0);assert.equal(closed,1);assert.match(f.controller.snapshot().status,/no longer active/);
});

test('a blocked popup or rejected native handoff is recoverable and never leaks a provider reason',async()=>{
  const blocked=fixture({openWindow:()=>null});blocked.setHandler(async()=>response(accounts(twitch(),youtubePending())));await blocked.controller.open();assert.equal(await blocked.controller.openGoogle(),false);assert.equal(blocked.requests.length,1);assert.match(blocked.controller.snapshot().status,/browser blocked/);assert.equal(blocked.controller.snapshot().busy,'');
  const native=fixture({authorizeAccount:async()=>({ok:false,reason:'private-provider-detail'})});native.setHandler(async()=>response(accounts(twitch(),youtubePending())));await native.controller.open();assert.equal(await native.controller.openGoogle(),false);assert.doesNotMatch(native.controller.snapshot().status,/private-provider/);assert.match(native.controller.snapshot().status,/could not be opened safely/);
});

test('Twitch and YouTube cancellation success keeps its history warning through polling and clears it on explicit retry',async()=>{
  for(const platform of ['twitch','youtube']){
    const ready=platform==='twitch'?authorized():youtube({state:'authorized',authorized:true,expires_at:NOW+3600}),f=fixture();f.setHandler(async()=>response(accounts(platform==='twitch'?pending():twitch(),platform==='youtube'?youtubePending():youtube())));await f.controller.open();
    f.setHandler(async(url,init)=>response(init.method==='POST'?{account:ready,activity_history_warning:true}:accounts(platform==='twitch'?ready:twitch(),platform==='youtube'?ready:youtube())));assert.equal(await f.controller.run('cancel',platform),true);assert.equal(f.controller.snapshot().activityHistoryWarning,true);assert.equal(f.controller.snapshot().stale,false);assert.match(f.controller.snapshot().status,/Sign-in cancelled.*previously saved account is kept.*Action completed.*activity history could not be saved/);assert.equal(f.controller.snapshot().accounts.find(value=>value.platform===platform).authorized,true);
    await f.fire();assert.equal(f.controller.snapshot().activityHistoryWarning,true);assert.match(f.controller.snapshot().status,/activity history could not be saved/);await f.controller.refresh();assert.equal(f.controller.snapshot().activityHistoryWarning,false);assert.doesNotMatch(f.controller.snapshot().status,/activity history/);f.controller.close();
  }
});
