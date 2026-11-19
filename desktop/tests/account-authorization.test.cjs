'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {authorizationRequest,googleAuthorizationUrl,createAccountAuthorization}=require('../account-authorization.cjs');
const policy=require('../policy.cjs');
const ORIGIN='http://127.0.0.1:54321',FLOW='a'.repeat(32),REQUEST={platform:'youtube',flowId:FLOW};
const AUTH='https://accounts.google.com/o/oauth2/v2/auth';
const QUERY={client_id:'fixture.apps.googleusercontent.com',redirect_uri:'http://127.0.0.1:53124/callback',
  response_type:'code',scope:'https://www.googleapis.com/auth/youtube.readonly',access_type:'offline',prompt:'consent',
  state:'s'.repeat(43),code_challenge:'c'.repeat(43),code_challenge_method:'S256'};
const authorizationUrl=(changes={})=>AUTH+'?'+new URLSearchParams({...QUERY,...changes});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};

function fixture(){
  const frame={url:ORIGIN+'/control?workspace=settings'},contents={mainFrame:null};contents.mainFrame=frame;
  const event={sender:contents,senderFrame:frame},calls=[],opens=[];
  const endpoint=ORIGIN+'/api/production/accounts/youtube/authorization?flow_id='+FLOW;
  let trusted=true,handler,responseFactory=(url)=>response(url,{authorization_url:authorizationUrl()});
  function response(url,value,options={}){
    const reply=new Response(typeof value==='string'?value:JSON.stringify(value),{status:options.status||200,
      headers:{'Content-Type':'application/json',...options.headers}});
    Object.defineProperty(reply,'url',{value:options.url??url});
    if(options.redirected)Object.defineProperty(reply,'redirected',{value:true});
    return reply;
  }
  handler=createAccountAuthorization({origin:ORIGIN,
    trustedSender:incoming=>trusted&&policy.trustedMain(incoming,contents,ORIGIN)&&new URL(incoming.senderFrame.url).pathname==='/control',
    fetchImpl:async(url,options)=>{calls.push({url,options});return responseFactory(url,options);},
    openExternal:async url=>{opens.push(url);}});
  return {event,frame,contents,calls,opens,endpoint,response,run:(value=REQUEST,incoming=event)=>handler(incoming,value),
    set responseFactory(value){responseFactory=value;},set trusted(value){trusted=value;}};
}

test('authorization request allows only YouTube and a lowercase 32-hex flow identifier',()=>{
  assert.equal(authorizationRequest(REQUEST),true);
  for(const input of [null,[],{},'https://evil.example',{platform:'twitch',flowId:FLOW},{platform:'youtube',flowId:'A'.repeat(32)},
    {...REQUEST,url:'https://evil.example'},{...REQUEST,flowId:'../private'},{...REQUEST,flowId:3}])assert.equal(authorizationRequest(input),false);
});

test('Google authorization accepts only fixed readonly installed-app PKCE/offline parameters',()=>{
  assert.equal(googleAuthorizationUrl(authorizationUrl()),authorizationUrl());
  for(const changes of [{scope:QUERY.scope+' https://other.example/scope'},{scope:'https://www.googleapis.com/auth/youtube'},
    {client_id:'other-client'},{response_type:'token'},{access_type:'online'},{prompt:'none'},
    {state:'short'},{state:'a'.repeat(129)},{code_challenge:'short'},{code_challenge_method:'plain'},
    {redirect_uri:'https://127.0.0.1:53124/callback'},{redirect_uri:'http://localhost:53124/callback'},
    {redirect_uri:'http://[::1]:53124/callback'},{redirect_uri:'http://127.0.0.1:80/callback'},
    {redirect_uri:'http://127.0.0.1:65536/callback'},{redirect_uri:'http://127.0.0.1:053124/callback'},
    {redirect_uri:'http://127.0.0.1:53124/other'},{redirect_uri:'http://127.0.0.1:53124/callback?private=1'},
    {redirect_uri:'http://127.0.0.1:53124/callback#fragment'},{redirect_uri:'http://user@127.0.0.1:53124/callback'},
    {redirect_uri:'http://127.0.0.2:53124/callback'}])assert.equal(googleAuthorizationUrl(authorizationUrl(changes)),null);
  for(const value of [authorizationUrl()+'&scope='+encodeURIComponent(QUERY.scope),authorizationUrl()+'&access_token=private',
    authorizationUrl()+'#private',authorizationUrl().replace('accounts.google.com','accounts.google.com.evil.example'),
    authorizationUrl().replace('accounts.google.com','user@accounts.google.com'),
    authorizationUrl().replace('accounts.google.com','accounts.google.com:443'),
    authorizationUrl().replace('/o/oauth2/v2/auth?','/other?'),authorizationUrl().replace('https:','http:'),
    authorizationUrl()+'\n',null,'x'.repeat(8193)])assert.equal(googleAuthorizationUrl(value),null);
});

test('native handoff fetches only the trusted local flow lookup and returns no URL',async()=>{
  const f=fixture();assert.deepEqual(await f.run(),{ok:true});
  assert.deepEqual(f.opens,[authorizationUrl()]);assert.equal(f.calls.length,1);
  assert.equal(f.calls[0].url,f.endpoint);assert.equal(f.calls[0].options.method,'GET');
  assert.equal(f.calls[0].options.redirect,'error');assert.equal(f.calls[0].options.cache,'no-store');
  assert.deepEqual(f.calls[0].options.headers,{Accept:'application/json',Origin:ORIGIN});
  assert.ok(f.calls[0].options.signal instanceof AbortSignal);
  assert.equal(policy.allowedExternal(authorizationUrl()),false,'the general external navigation policy remains unchanged');
});

test('Google metadata handoff admits only readonly plus the explicit force-ssl upgrade',()=>{
  const edit='https://www.googleapis.com/auth/youtube.force-ssl',base=QUERY.scope;
  for(const scope of [base+' '+edit,edit+' '+base])assert.equal(googleAuthorizationUrl(authorizationUrl({scope})),authorizationUrl({scope}));
  for(const scope of [edit,base+' '+base,base+' '+edit+' '+edit,base+' '+edit+' arbitrary:write',base+'  '+edit])assert.equal(googleAuthorizationUrl(authorizationUrl({scope})),null);
});

test('unknown payloads, subframes, other contents and untrusted pages never fetch or open',async()=>{
  const f=fixture();
  for(const incoming of [{sender:{},senderFrame:f.frame},{sender:f.contents,senderFrame:{url:f.frame.url}}])
    assert.deepEqual(await f.run(REQUEST,incoming),{ok:false,reason:'local_operator_required'});
  for(const payload of [null,{...REQUEST,url:authorizationUrl()},{platform:'youtube',flowId:'bad'},{}])
    assert.deepEqual(await f.run(payload),{ok:false,reason:'invalid_authorization_request'});
  f.frame.url=ORIGIN+'/program';assert.deepEqual(await f.run(),{ok:false,reason:'local_operator_required'});
  f.frame.url='https://evil.example/control';assert.deepEqual(await f.run(),{ok:false,reason:'local_operator_required'});
  assert.deepEqual(f.calls,[]);assert.deepEqual(f.opens,[]);
});

test('expired flows and invalid or oversized server payloads fail without exposing data',async()=>{
  const factories=[
    (f,url)=>f.response(url,{ok:false,reason:'private callback code'},{status:409}),
    (f,url)=>f.response(url,{authorization_url:authorizationUrl()},{status:403}),
    (f,url)=>f.response(url,{authorization_url:authorizationUrl()},{url:'https://evil.example'}),
    (f,url)=>f.response(url,{authorization_url:authorizationUrl()},{redirected:true}),
    (f,url)=>f.response(url,{authorization_url:authorizationUrl()},{headers:{'Content-Type':'text/html'}}),
    (f,url)=>f.response(url,{authorization_url:authorizationUrl()},{headers:{'Content-Length':'16385'}}),
    (f,url)=>f.response(url,'x'.repeat(16385)),
    (f,url)=>f.response(url,'private not-json'),
    (f,url)=>f.response(url,{authorization_url:authorizationUrl(),access_token:'private'}),
    (f,url)=>f.response(url,{authorization_url:'https://evil.example/private'}),
    (f,url)=>f.response(url,{authorization_url:authorizationUrl({redirect_uri:ORIGIN+'/callback'})}),
  ];
  for(const make of factories){const f=fixture();f.responseFactory=url=>make(f,url);const result=await f.run();
    assert.equal(result.ok,false);assert.doesNotMatch(JSON.stringify(result),/private|https:/);assert.deepEqual(f.opens,[]);}
});

test('simultaneous same-flow clicks share one lookup/open; another flow waits and retries remain possible',async()=>{
  const f=fixture(),wait=deferred();f.responseFactory=()=>wait.promise;
  const first=f.run(),second=f.run();
  assert.deepEqual(await f.run({platform:'youtube',flowId:'b'.repeat(32)}),{ok:false,reason:'authorization_open_pending'});
  assert.equal(f.calls.length,1);wait.resolve(f.response(f.endpoint,{authorization_url:authorizationUrl()}));
  assert.deepEqual(await first,{ok:true});assert.deepEqual(await second,{ok:true});assert.equal(f.opens.length,1);
  f.responseFactory=url=>f.response(url,{authorization_url:authorizationUrl()});assert.deepEqual(await f.run(),{ok:true});
  assert.equal(f.opens.length,2,'another explicit click may reopen the current authorized handoff');
});

test('navigation or revocation during lookup prevents a stale external open',async()=>{
  for(const revoke of [f=>{f.frame.url=ORIGIN+'/control?workspace=broadcast';},f=>{f.contents.mainFrame={url:f.frame.url};},f=>{f.trusted=false;}]){
    const f=fixture(),wait=deferred();f.responseFactory=()=>wait.promise;const pending=f.run();
    revoke(f);wait.resolve(f.response(f.endpoint,{authorization_url:authorizationUrl()}));
    assert.deepEqual(await pending,{ok:false,reason:'local_operator_required'});assert.deepEqual(f.opens,[]);
  }
});

test('fetch and browser launch errors return only safe reasons and release the request lock',async()=>{
  const f=fixture();f.responseFactory=()=>{throw Error('https://private.example/secret-code');};
  assert.deepEqual(await f.run(),{ok:false,reason:'authorization_unavailable'});
  f.responseFactory=url=>f.response(url,{authorization_url:authorizationUrl()});assert.deepEqual(await f.run(),{ok:true});
  const opener=createAccountAuthorization({origin:ORIGIN,trustedSender:()=>true,
    fetchImpl:async url=>f.response(url,{authorization_url:authorizationUrl()}),openExternal:async()=>{throw Error('private code');}});
  assert.deepEqual(await opener(f.event,REQUEST),{ok:false,reason:'authorization_open_failed'});
});

test('actual preload exposes the existing lowercase fixed account action without renderer URLs',async()=>{
  let name,bridge;const calls=[];
  const electron={contextBridge:{exposeInMainWorld:(key,value)=>{name=key;bridge=value;}},
    ipcRenderer:{invoke:(...args)=>{calls.push(args);return Promise.resolve({ok:true});}}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../preload.cjs'),'utf8'),{require:()=>electron});
  assert.equal(name,'producerDesktop');assert.equal(Object.isFrozen(bridge),true);
  assert.equal((await bridge.authorizeAccount(REQUEST)).ok,true);
  assert.equal(calls[0][0],'producer:accounts:authorize');
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0][1])),REQUEST);
  for(const payload of [null,{...REQUEST,url:'https://evil.example'},Object.assign(Object.create({platform:'youtube'}),{flowId:FLOW,junk:1})])
    assert.equal((await bridge.authorizeAccount(payload)).ok,false);
  assert.equal(calls.length,1);
});

test('Main registers only the dedicated protected account handler',()=>{
  const main=fs.readFileSync(path.join(__dirname,'../main.cjs'),'utf8');
  assert.match(main,/require\('\.\/account-authorization\.cjs'\)/);
  assert.match(main,/ipcMain\.handle\('producer:accounts:authorize',authorizeAccount\)/);
  assert.match(main,/policy\.trustedMain\(event,studio\.webContents,origin\)/);
  assert.match(main,/new URL\(event\.senderFrame\.url\)\.pathname==='\/control'/);
});
