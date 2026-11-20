const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../rareiq/web/static/viewer_chat.js'),'utf8');
const {createFeed,connection,connected,createReplyController}=require('../../rareiq/web/static/viewer_chat.js');
const settle=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
const message=(id,text='Message '+id,platform='twitch')=>({id,text,platform,display_name:'Viewer '+id,occurred_at:1700000000,received_at:1700000001});
const sources=()=>['twitch','youtube','kick'].map(platform=>({platform,implemented:true,state:'not_connected',connected:false,authorized:false,verified:false,reason:'explicit_connection_required',...(platform==='kick'?{dashboard_registration_approved:false}:{})}));
const payload=(messages=[],extra={})=>({active:true,session_id:'a'.repeat(32),cursor:messages.at(-1)?.id||0,reset:false,messages,sources:sources(),...extra});
function fixture(hostname='127.0.0.1'){
  let doc,serial=0,handler=async()=>response(payload([],{active:false}));const all=[],timers=new Map(),requests=[],listeners={};
  class Element{
    constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.listeners={};this.textContent='';this.hidden=false;this.disabled=false;this.scrollTop=0;this.scrollHeight=100;this.clientHeight=100;this.ownerDocument=doc;all.push(this);}
    setAttribute(name,value){this.attributes[name]=value;if(name.startsWith('data-'))this.dataset[name.slice(5).replace(/-([a-z])/g,(_,s)=>s.toUpperCase())]=value;}
    append(...nodes){for(const n of nodes){if(n.parent)n.parent.children=n.parent.children.filter(child=>child!==n);n.parent=this;this.children.push(n);}}
    replaceChildren(...nodes){for(const n of this.children)n.parent=null;this.children=[];this.append(...nodes);}
    remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);this.parent=null;}
    addEventListener(name,fn){this.listeners[name]=fn;}
    focus(){doc.activeElement=this;}
    dispatch(name,extra={}){if(this.disabled&&name==='click')return;return this.listeners[name]?.({preventDefault(){},...extra});}
  }
  doc={createElement:tag=>new Element(tag),activeElement:null};doc.body=new Element('body');doc.activeElement=doc.body;
  const response=(body,status=200)=>({ok:status<400,status,json:async()=>body});
  const host={document:doc,location:{hostname},URLSearchParams,AbortController,setTimeout(fn,delay){const id=++serial;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},fetch(url,init){requests.push({url,init});return handler(url,init);},addEventListener(name,fn){listeners[name]=fn;},removeEventListener(name,fn){if(listeners[name]===fn)delete listeners[name];}};host.window=host;vm.runInNewContext(source,host);
  const container=new Element('div'),chat=host.ProducerViewerChat.mount(container,{now:()=>1700000010}),get=(attribute,value)=>all.find(n=>Object.hasOwn(n.attributes,attribute)&&(value===undefined||n.attributes[attribute]===value));
  const fire=async(delay=2000)=>{const entry=[...timers].find(([,t])=>t.delay===delay);if(entry){timers.delete(entry[0]);entry[1].fn();}await settle();};
  return {chat,container,all,get,doc,timers,requests,listeners,response,fire,setHandler(fn){handler=fn;}};
}

test('combined feed deduplicates by platform and retains only the latest 300 messages',()=>{
  const feed=createFeed({now:()=>1700000010});feed.apply(payload([message(1),message(1),message(1,'YouTube','youtube')]));assert.equal(feed.snapshot().count,2);
  feed.apply(payload(Array.from({length:300},(_,i)=>message(i+2))));assert.equal(feed.snapshot().count,300);assert.equal(feed.snapshot().messages[0].id,2);
  feed.setFilter('youtube');assert.equal(feed.snapshot().messages.length,0);feed.setFilter('all');assert.equal(feed.snapshot().count,300);
});

test('filters and paused reading track only visible unread messages without discarding the combined buffer',()=>{
  const feed=createFeed({now:()=>1700000010});feed.apply(payload([message(1)]));feed.setFilter('youtube');feed.setPaused(true);feed.apply(payload([message(2),message(3,'YouTube','youtube')]));
  assert.equal(feed.snapshot().unread,1);assert.equal(feed.snapshot().messages[0].platform,'youtube');assert.equal(feed.snapshot().count,3);feed.setPaused(false);assert.equal(feed.snapshot().unread,0);
  feed.setFilter('all');assert.equal(feed.snapshot().messages.length,3);
});

test('session resets and inactive feeds clear previous messages; malformed responses cannot advance the cursor',()=>{
  const feed=createFeed({now:()=>1700000010});feed.apply(payload([message(1)]));assert.throws(()=>feed.apply(payload([message(2)],{cursor:-1})),/invalid_response/);assert.equal(feed.snapshot().cursor,1);
  feed.apply(payload([message(2)],{session_id:'b'.repeat(32),reset:true}));assert.deepEqual(feed.snapshot().messages.map(m=>m.id),[2]);
  feed.apply(payload([message(3)],{active:false}));assert.equal(feed.snapshot().count,0);assert.equal(feed.snapshot().active,false);
});

test('connection health requires all provenance flags and safely maps unavailable setup without raw provider errors',()=>{
  const online={platform:'twitch',implemented:true,state:'connected',connected:true,authorized:true,verified:true};assert.equal(connected(online),true);
  for(const change of [{connected:false},{authorized:false},{verified:false},{state:'reconnecting'}])assert.equal(connected({...online,...change}),false);
  assert.match(connection({platform:'youtube',implemented:true,reason:'credentials_required'}).text,/Account setup/);
  assert.equal(connection({platform:'kick',implemented:true}).blocked,true);
  assert.doesNotMatch(connection({platform:'twitch',reason:'secret-token-from-provider'}).text,/secret|token/);
});

test('mount reads status without enabling listening or connecting accounts; Kick remains disabled with an explanation',async()=>{
  const f=fixture();await settle();assert.equal(f.requests.length,2);assert.equal(f.requests[0].url,'/api/production/viewer-chat/reply-status');assert.ok(f.requests[1].url.startsWith('/api/production/viewer-chat?'));assert.equal(new URL(f.requests[1].url,'http://fixture').searchParams.has('session_id'),false);assert.equal(f.requests.some(r=>r.init.method==='POST'),false);
  assert.equal(f.get('data-viewer-connect','kick').disabled,true);assert.match(f.get('data-viewer-connect','kick').title,/approved/);assert.equal(f.get('data-viewer-start').disabled,false);
  assert.equal(f.container._viewerChat,f.chat);assert.equal(f.chat.element.dataset.broadcastPanel,'live');
});

test('explicit connect enables listening first, serializes clicks and posts no credentials',async()=>{
  const f=fixture();await settle();let finish;f.setHandler((url,init)=>init.method==='POST'&&url.endsWith('/listening')?new Promise(resolve=>finish=resolve):Promise.resolve(f.response(payload([]))));
  const pending=f.chat.controller.run('connect','twitch');assert.equal(await f.chat.controller.run('connect','youtube'),false);assert.equal(f.requests.at(-1).url,'/api/production/viewer-chat/listening');assert.equal(f.requests.at(-1).init.body,'{"enabled":true}');
  finish(f.response(payload([])));await pending;const posts=f.requests.filter(r=>r.init.method==='POST');assert.equal(posts.length,2);assert.equal(posts[1].url,'/api/production/audience/twitch/connect');assert.equal(posts[1].init.body,'{}');assert.equal(f.chat.controller.snapshot().busy,false);
  assert.equal(await f.chat.controller.run('connect','kick'),false);
});

test('literal viewer text and display names cannot create HTML; filter clicks preserve keyboard focus',async()=>{
  const f=fixture();await settle();f.setHandler(async()=>f.response(payload([{...message(1,'<img src=x onerror=alert(1)>'),display_name:'<script>name</script>'},message(2,'YT','youtube')])));await f.fire();
  const list=f.get('data-viewer-messages'),row=list.children[0];assert.equal(row.children[1].textContent,'<img src=x onerror=alert(1)>');assert.equal(row.children[0].children[1].textContent,'<script>name</script>');assert.ok(!Object.hasOwn(row,'innerHTML'));
  const filter=f.get('data-viewer-filter','youtube');filter.focus();filter.dispatch('click');assert.equal(list.children.length,1);assert.equal(list.children[0].children[1].textContent,'YT');assert.equal(f.doc.activeElement,filter);assert.equal(filter.attributes['aria-pressed'],'true');
});

test('paused reading preserves position and shows unread; Return to latest clears unread and focuses the transcript',async()=>{
  const f=fixture();await settle();let messages=[message(1)];f.setHandler(async()=>f.response(payload(messages)));await f.fire();const list=f.get('data-viewer-messages');list.scrollHeight=900;list.clientHeight=200;list.scrollTop=100;list.dispatch('scroll');
  messages=[...messages,message(2)];await f.fire();assert.equal(list.scrollTop,100);assert.equal(f.get('data-viewer-latest').hidden,false);assert.match(f.get('data-viewer-latest').textContent,/1 new/);
  f.get('data-viewer-latest').dispatch('click');assert.equal(list.scrollTop,900);assert.equal(f.chat.controller.snapshot().unread,0);assert.equal(f.get('data-viewer-latest').hidden,true);assert.equal(f.doc.activeElement,list);
});

test('failed reads preserve messages and cursor, expose retry and recover without duplication',async()=>{
  const f=fixture();await settle();f.setHandler(async()=>f.response(payload([message(1)])));await f.fire();f.setHandler(async()=>{throw Error('private provider detail');});await f.fire();
  assert.equal(f.get('data-viewer-messages').children.length,1);assert.equal(f.get('data-viewer-retry').hidden,false);assert.match(f.get('data-viewer-status').textContent,/Updates interrupted/);assert.doesNotMatch(f.get('data-viewer-status').textContent,/private provider/);
  f.setHandler(async()=>f.response(payload([message(1),message(2)])));await f.get('data-viewer-retry').dispatch('click');assert.equal(f.get('data-viewer-messages').children.length,2);assert.equal(f.get('data-viewer-retry').hidden,true);assert.match(f.requests.at(-1).url,/after=1/);
});

test('stop clears immediately, aborts pending reads and ignores their delayed messages',async()=>{
  const f=fixture();await settle();f.setHandler(async()=>f.response(payload([message(1)])));await f.fire();let finish;f.setHandler((url,init)=>init.method==='POST'?Promise.resolve(f.response(payload([],{active:false}))):new Promise(resolve=>finish=resolve));
  await f.fire();const old=f.requests.at(-1),oldRead=finish;let stopped=false;f.setHandler(async(url,init)=>{if(init.method==='POST')stopped=true;return f.response(payload([],{active:!stopped}));});
  const pending=f.chat.controller.run('stop');assert.equal(f.get('data-viewer-messages').children.length,0);assert.equal(old.init.signal.aborted,true);oldRead(f.response(payload([message(99,'late history')])));await pending;await settle();
  assert.equal(f.get('data-viewer-messages').children.length,0);assert.equal(f.chat.controller.snapshot().active,false);assert.ok(f.requests.some(r=>r.init.body==='{"enabled":false}'));
});

test('uncertain stop never refills private feed until an explicit new Start',async()=>{
  const f=fixture();await settle();f.setHandler(async()=>f.response(payload([message(1)])));await f.fire();f.setHandler(async(url,init)=>init.method==='POST'?f.response({reason:'unsafe-provider-text'},503):f.response(payload([message(1)])));
  await f.chat.controller.run('stop');assert.equal(f.get('data-viewer-messages').children.length,0);assert.match(f.get('data-viewer-status').textContent,/Stopping could not be confirmed/);await f.fire();assert.equal(f.get('data-viewer-messages').children.length,0);
  f.setHandler(async()=>f.response(payload([message(2)])));await f.chat.controller.run('start');assert.equal(f.get('data-viewer-messages').children.length,1);assert.equal(f.chat.controller.snapshot().active,true);
});

test('destroy aborts reads and commands, clears timers and prevents delayed completion from restoring the panel',async()=>{
  const f=fixture();await settle();let finish;f.setHandler(()=>new Promise(resolve=>finish=resolve));const pending=f.chat.controller.run('start');const request=f.requests.at(-1);f.chat.destroy();assert.equal(request.init.signal.aborted,true);assert.equal(f.timers.size,0);assert.equal(f.container.children.length,0);assert.equal(f.container._viewerChat,undefined);
  finish(f.response(payload([message(10)])));await pending;await settle();assert.equal(f.chat.controller.snapshot().count,0);assert.equal(f.timers.size,0);assert.equal(f.listeners.pagehide,undefined);
});

test('remote operators receive visible host-only guidance and cannot use platform connection buttons',async()=>{
  const f=fixture('studio.example');await settle();assert.equal(f.get('data-viewer-connect','twitch').disabled,true);assert.ok(f.all.some(n=>n.textContent==='Use the production host computer to connect or disconnect platforms.'));
});

test('viewer chat defaults to a visible right tool while existing saved choices and full-width backstage remain intact',()=>{
  const {normalize}=require('../../rareiq/web/static/studio_docks.js'),ids=['production-viewer-chat','production-greenroom'];const defaults=normalize(null,ids);
  assert.equal(defaults.tools['production-viewer-chat'].position,'right');assert.equal(defaults.tools['production-viewer-chat'].visible,true);assert.equal(defaults.tools['production-greenroom'].position,'bottom');
  const saved=normalize({version:1,tools:{'production-viewer-chat':{visible:false,position:'left'}}},ids);assert.equal(saved.tools['production-viewer-chat'].position,'left');assert.equal(saved.tools['production-viewer-chat'].visible,false);
});

test('client expires received messages after 20 minutes even when the next delta is empty',()=>{
  let now=1700000010;const feed=createFeed({now:()=>now});feed.apply(payload([message(1)]));assert.equal(feed.snapshot().count,1);now=1700001202;
  feed.apply(payload([],{cursor:1}));assert.equal(feed.snapshot().count,0);assert.equal(feed.snapshot().cursor,1);assert.equal(feed.snapshot().active,true);
});

test('successful Stop preserves its activity-history warning through polling until explicit status retry',async()=>{
  const f=fixture();await settle();f.setHandler(async(url,init)=>f.response(payload([],{active:false,...(init.method==='POST'?{activity_history_warning:true}:{})})));assert.equal(await f.chat.controller.run('stop'),true);
  assert.equal(f.chat.controller.snapshot().activityHistoryWarning,true);assert.match(f.get('data-viewer-status').textContent,/Viewer chat is stopped/);assert.match(f.get('data-viewer-status').textContent,/Action completed.*activity history could not be saved/);assert.doesNotMatch(f.get('data-viewer-status').textContent,/Stopping could not be confirmed/);
  await f.fire();assert.equal(f.chat.controller.snapshot().activityHistoryWarning,true);assert.match(f.get('data-viewer-status').textContent,/activity history could not be saved/);await f.chat.controller.refresh();assert.equal(f.chat.controller.snapshot().activityHistoryWarning,false);assert.doesNotMatch(f.get('data-viewer-status').textContent,/activity history/);
});

test('successful disconnect warns about history separately from current connection state',async()=>{
  const f=fixture();await settle();f.setHandler(async(url,init)=>f.response(init.method==='POST'?{platform:'twitch',state:'not_connected',activity_history_warning:true}:payload([],{active:false})));assert.equal(await f.chat.controller.run('disconnect','twitch'),true);assert.equal(f.chat.controller.snapshot().activityHistoryWarning,true);assert.match(f.get('data-viewer-status').textContent,/Action completed/);assert.equal(f.chat.controller.snapshot().stale,false);
});

test('history-warning Stop receipt stays confirmed even if the following status read fails, and next action clears warning',async()=>{
  const f=fixture();await settle();f.setHandler(async(url,init)=>{if(init.method==='POST')return f.response(payload([],{active:false,activity_history_warning:true}));throw Error('status unavailable');});assert.equal(await f.chat.controller.run('stop'),true);assert.equal(f.chat.controller.snapshot().activityHistoryWarning,true);assert.equal(f.chat.controller.snapshot().stale,true);assert.match(f.get('data-viewer-status').textContent,/Action completed/);assert.doesNotMatch(f.get('data-viewer-status').textContent,/Stopping could not be confirmed/);
  f.setHandler(async()=>f.response(payload([],{active:false})));await f.chat.controller.run('start');assert.equal(f.chat.controller.snapshot().activityHistoryWarning,false);
});

test('reply composer shows exactly ready All recipients and separates destination from reading filter',async()=>{
  const f=fixture();await settle();f.setHandler(async(url,init)=>{if(url.endsWith('/reply-status'))return f.response({ok:true,max_length:200,targets:['twitch','youtube','kick'].map(platform=>({platform,ready:platform==='twitch',reason:platform==='twitch'?'ready':'chat_send_permission_required'}))});if(init.method==='POST'){const body=JSON.parse(init.body);return f.response({ok:true,request_id:body.request_id,results:body.targets.map(platform=>({platform,state:'sent',reason:'chat_sent',retryable:false}))});}return f.response(payload([]));});
  await f.chat.replies.refresh();const draft=f.get('data-viewer-reply-text'),target=f.get('data-viewer-reply-target'),send=f.get('data-viewer-reply-send');draft.value='<literal & reply>';draft.dispatch('input');assert.equal(send.disabled,false);assert.match(f.get('data-viewer-reply-help').textContent,/Public reply to Twitch.*Excluded.*YouTube.*Permission.*Kick/);assert.equal(f.get('data-viewer-reply-recipients').children.length,1);
  target.value='twitch';target.dispatch('change');assert.equal(send.disabled,false);assert.equal(send.textContent,'Send to Twitch');f.get('data-viewer-filter','youtube').dispatch('click');assert.equal(target.value,'twitch');await f.get('data-viewer-composer').dispatch('submit');const body=JSON.parse(f.requests.find(r=>r.url.endsWith('/reply')).init.body);assert.deepEqual(body.targets,['twitch']);assert.equal(body.text,'<literal & reply>');assert.equal(draft.value,'');assert.equal(f.get('data-viewer-reply-receipt').children[0].textContent,'Twitch: Sent');
});

test('All ready chats posts exactly the two displayed ready recipients and names the excluded platform',async()=>{
  const f=fixture();await settle();f.setHandler(async(url,init)=>{if(url.endsWith('/reply-status'))return f.response({ok:true,max_length:200,targets:['twitch','youtube','kick'].map(platform=>({platform,ready:platform!=='kick',reason:platform==='kick'?'chat_send_permission_required':'ready'}))});if(init.method==='POST'){const body=JSON.parse(init.body);return f.response({ok:true,request_id:body.request_id,results:body.targets.map(platform=>({platform,state:'sent',reason:'chat_sent',retryable:false}))});}return f.response(payload([]));});await f.chat.replies.refresh();const draft=f.get('data-viewer-reply-text');draft.value='Two ready chats';draft.dispatch('input');assert.equal(f.get('data-viewer-reply-send').disabled,false);assert.equal(f.get('data-viewer-reply-recipients').children.length,2);assert.match(f.get('data-viewer-reply-help').textContent,/Public reply to Twitch, YouTube.*Excluded.*Kick/);await f.get('data-viewer-composer').dispatch('submit');assert.deepEqual(JSON.parse(f.requests.find(r=>r.url.endsWith('/reply')).init.body).targets,['twitch','youtube']);
});

function replyFixture(){
  const {createReplyController}=require('../../rareiq/web/static/viewer_chat.js'),requests=[],timers=new Set();let handle=(url,init)=>({ok:true,json:async()=>url.endsWith('/reply-status')?{ok:true,max_length:200,targets:['twitch','youtube','kick'].map(platform=>({platform,ready:true,reason:'ready'}))}:{ok:true,request_id:JSON.parse(init.body).request_id,results:JSON.parse(init.body).targets.map(platform=>({platform,state:'sent',reason:'chat_sent',retryable:false}))}});
  const controller=createReplyController({fetch:async(url,init)=>{requests.push({url,init});return handle(url,init);},setTimeout(){const token={};timers.add(token);return token;},clearTimeout(token){timers.delete(token);}});return {controller,requests,timers,setHandler(fn){handle=fn;}};
}

test('reply validation counts Unicode codepoints, requires explicit unique destinations and posts only on Send',async()=>{
  const f=replyFixture();await f.controller.refresh();assert.equal(f.requests.some(r=>r.init.method==='POST'),false);
  for(const [text,targets]of [['',['twitch']],['x'.repeat(201),['twitch']],['hi',[]],['hi',['twitch','twitch']],['hi',['unknown']]])assert.equal(await f.controller.send(text,targets),false);
  assert.equal(await f.controller.send('🎥'.repeat(200),['youtube']),true);const request=f.requests.at(-1);assert.equal(request.init.credentials,'same-origin');assert.deepEqual(JSON.parse(request.init.body).targets,['youtube']);assert.equal(f.timers.size,0);
});

test('partial replies keep one ID and explicit retry covers only backend-known failed recipients',async()=>{
  const f=replyFixture();await f.controller.refresh();f.setHandler((url,init)=>{const body=JSON.parse(init.body);return {ok:true,json:async()=>({ok:true,request_id:body.request_id,results:[{platform:'twitch',state:'sent',reason:'chat_sent',retryable:false},{platform:'youtube',state:body.retry_failed?'sent':'failed',reason:body.retry_failed?'chat_sent':'chat_provider_rate_limited',retryable:!body.retry_failed}]})};});
  assert.equal(await f.controller.send('Hello',['twitch','youtube']),true);const first=JSON.parse(f.requests.at(-1).init.body);assert.equal(await f.controller.send('Hello',['twitch','youtube']),false);assert.equal(await f.controller.send('Hello',['twitch','youtube'],{retryFailed:true}),true);const retry=JSON.parse(f.requests.at(-1).init.body);assert.equal(retry.request_id,first.request_id);assert.equal(retry.retry_failed,true);assert.equal(f.controller.snapshot().receipt.results[0].state,'sent');
});

test('lost reply response becomes uncertain, blocks identical resends and never exposes provider error text',async()=>{
  const f=replyFixture();await f.controller.refresh();f.setHandler(()=>{throw Error('secret-token-private-provider-detail');});assert.equal(await f.controller.send('Check',['kick']),false);assert.equal(f.controller.snapshot().receipt.results[0].state,'uncertain');assert.equal(await f.controller.send('Check',['kick']),false);assert.equal(await f.controller.send('Check',['kick'],{retryFailed:true}),false);assert.doesNotMatch(f.controller.snapshot().error,/secret|token|private/);assert.equal(f.requests.length,2);
});

test('sent and uncertain recipients stay protected while explicit known-failed retry remains available',async()=>{
  const f=replyFixture();await f.controller.refresh();f.setHandler((url,init)=>({ok:true,json:async()=>({ok:true,request_id:JSON.parse(init.body).request_id,results:[{platform:'twitch',state:'uncertain',reason:'chat_send_uncertain',retryable:true},{platform:'youtube',state:'failed',reason:'chat_provider_rate_limited',retryable:true}]})}));await f.controller.send('Mixed',['twitch','youtube']);assert.equal(f.controller.snapshot().receipt.results[0].retryable,false);assert.equal(await f.controller.send('Mixed',['twitch','youtube'],{retryFailed:true}),true);assert.equal(JSON.parse(f.requests.at(-1).init.body).retry_failed,true);
});

test('reply commands serialize clicks and destruction aborts timers without restoring UI',async()=>{
  const f=replyFixture();await f.controller.refresh();let finish;f.setHandler(()=>new Promise(resolve=>finish=resolve));const first=f.controller.send('Pending',['twitch']);assert.equal(await f.controller.send('Pending',['twitch']),false);const request=f.requests.at(-1);f.controller.destroy();assert.equal(request.init.signal.aborted,true);assert.equal(f.timers.size,0);finish({ok:true,json:async()=>({ok:true,request_id:JSON.parse(request.init.body).request_id,results:[{platform:'twitch',state:'sent',retryable:false}]})});await first;assert.equal(f.controller.snapshot().receipt,null);
});


test('reply controller rejects controls and unpaired surrogates before native transport',async()=>{
 const calls=[],controller=createReplyController({fetch:async(url,options)=>{calls.push(url);return {ok:true,json:async()=>({ok:true,max_length:200,targets:['twitch','youtube','kick'].map(platform=>({platform,ready:true,reason:'ready'}))})};}});
 await controller.refresh();const before=calls.length;for(const text of ['line\nline','tab\ttext','text\u007f','\ud800'])assert.equal(await controller.send(text,['twitch']),false);assert.equal(calls.length,before);controller.destroy();
});


test('reply errors preserve uncertainty after receipt storage failure and explain rehearsal',()=>{const {replyReason}=require('../../rareiq/web/static/viewer_chat.js');assert.doesNotMatch(replyReason('chat_storage_unavailable'),/nothing.*sent/i);assert.match(replyReason('chat_storage_unavailable'),/Check each platform/);assert.match(replyReason('rehearsal_active'),/Rehearsal/);});
