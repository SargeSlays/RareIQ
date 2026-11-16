const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../rareiq/web/static/greenroom_chat.js'),'utf8');
const settle=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
const ROOM='c'.repeat(32),GUEST='a'.repeat(32),OTHER='b'.repeat(32),TOKEN='d'.repeat(64);
const message=(id,text,channel='room',participant_id=null)=>({id,text,channel,participant_id,author_name:'<script>display name</script>',author_kind:'guest',identity_verified:false,created_at:1700000000});
function fixture(role='guest'){
  const all=[],timers=new Map(),requests=[];let serial=0,handler,doc;
  class Element{
    constructor(tag){this.tagName=tag;this.children=[];this.dataset={};this.attributes={};this.listeners={};this.textContent='';this.value='';this.hidden=false;this.disabled=false;this.scrollTop=0;this.scrollHeight=100;this.clientHeight=100;this.ownerDocument=doc;all.push(this);}
    setAttribute(name,value){this.attributes[name]=value;if(name.startsWith('data-'))this.dataset[name.slice(5).replace(/-([a-z])/g,(_,s)=>s.toUpperCase())]=value;if(name==='value')this.value=value;}
    append(...nodes){for(const n of nodes){n.parent=this;this.children.push(n);}}
    replaceChildren(...nodes){for(const n of this.children)n.parent=null;this.children=[];this.append(...nodes);}
    remove(){if(this.parent)this.parent.children=this.parent.children.filter(n=>n!==this);this.parent=null;}
    addEventListener(name,fn){this.listeners[name]=fn;}
    focus(){if(!this.disabled)doc.activeElement=this;}
    dispatch(name,extra={}){return this.listeners[name]?.({preventDefault(){},...extra});}
  }
  doc={createElement:tag=>new Element(tag),activeElement:null};doc.body=new Element('body');doc.activeElement=doc.body;
  const response=(payload,status=200)=>({ok:status<400,status,json:async()=>payload});
  handler=async(url,init)=>{const q=new URL(url,'http://fixture').searchParams,body=init.method==='POST'?JSON.parse(init.body):null;return response(body?{ok:true,room_id:ROOM,message:message(1,body.text,body.channel,body.participant_id||GUEST)}:{ok:true,room_id:ROOM,channel:q.get('channel'),participant_id:q.get('channel')==='private'?(q.get('participant_id')||GUEST):null,messages:[],latest_id:0});};
  const host={document:doc,URLSearchParams,AbortController,Uint8Array,crypto:require('node:crypto').webcrypto,setTimeout(fn,delay){const id=++serial;timers.set(id,{fn,delay});return id;},clearTimeout(id){timers.delete(id);},fetch(url,init){requests.push({url,init});return handler(url,init);}};host.window=host;vm.runInNewContext(source,host);
  const container=new Element('div'),chat=host.ProducerGreenroomChat.mount(container,{role});
  const get=attribute=>all.find(n=>Object.hasOwn(n.attributes,attribute));
  const type=text=>{get('data-chat-input').value=text;get('data-chat-input').dispatch('input');};
  const change=(attribute,value)=>{get(attribute).value=value;get(attribute).dispatch('change');};
  const fire=async(delay=0)=>{const entry=[...timers].find(([,t])=>t.delay===delay);if(entry){timers.delete(entry[0]);entry[1].fn();}await settle();};
  const join=async(extra={})=>{chat.update({active:true,roomId:role==='producer'?ROOM:'',participantId:role==='guest'?GUEST:'',token:role==='guest'?TOKEN:'',participants:[{id:GUEST,name:'One',state:'waiting'},{id:OTHER,name:'Two',state:'admitted'}],...extra});await fire();};
  return {chat,container,doc,all,get,type,change,fire,join,requests,timers,response,setHandler(fn){handler=fn;},send:()=>get('data-chat-input').parent.dispatch('submit')};
}
test('guest joins before reading; token stays in header and private sends never accept a recipient',async()=>{
  const f=fixture();assert.equal(f.requests.length,0);assert.match(f.get('data-chat-status').textContent,/Join backstage/);assert.equal(f.get('data-chat-send').disabled,true);
  await f.join();assert.equal(f.requests.length,1);assert.equal(f.requests[0].init.headers.Authorization,'Bearer '+TOKEN);assert.ok(!f.requests[0].url.includes(TOKEN));
  f.change('data-chat-channel','private');await f.fire();f.type('Private\nmessage');await f.send();
  const post=f.requests.find(r=>r.init.method==='POST'),body=JSON.parse(post.init.body);assert.equal(body.channel,'private');assert.equal(body.room_id,ROOM);assert.equal(body.text,'Private\nmessage');assert.ok(!Object.hasOwn(body,'participant_id'));assert.ok(!post.url.includes('participant_id'));
});
test('stale initial response cannot render or establish a room after token changes',async()=>{
  const f=fixture();let finish;f.setHandler(()=>new Promise(resolve=>finish=resolve));await f.join();
  f.chat.update({token:'e'.repeat(64),participantId:OTHER});finish(f.response({ok:true,room_id:ROOM,channel:'room',messages:[message(1,'OLD PRIVATE HISTORY')]}));await settle();
  assert.equal(f.get('data-chat-messages').children.length,0);assert.equal(f.get('data-chat-input').disabled,true);assert.ok(f.requests[0].init.signal.aborted);
});
test('changing private recipient retains separate drafts and ignores stale history',async()=>{
  const f=fixture('producer');await f.join();f.change('data-chat-channel','private');assert.equal(f.get('data-chat-send').disabled,true);
  f.change('data-chat-recipient',GUEST);f.type('To one');let finish;f.setHandler(()=>new Promise(resolve=>finish=resolve));await f.fire();
  f.change('data-chat-recipient',OTHER);assert.equal(f.get('data-chat-input').value,'');f.type('To two');finish(f.response({ok:true,room_id:ROOM,channel:'private',participant_id:GUEST,messages:[message(2,'for one','private',GUEST)]}));await settle();assert.equal(f.get('data-chat-messages').children.length,0);
  f.change('data-chat-recipient',GUEST);assert.equal(f.get('data-chat-input').value,'To one');f.change('data-chat-channel','room');assert.equal(f.get('data-chat-input').value,'');f.change('data-chat-channel','private');assert.equal(f.get('data-chat-input').value,'To one');
});
test('uncertain sends retain the exact request id and text on retry, preserving input focus',async()=>{
  const f=fixture();await f.join();let attempt=0;f.setHandler(async(url,init)=>{if(init.method==='POST'&&++attempt===1)throw Error('network');return f.response({ok:true,room_id:ROOM,message:message(7,'hello')});});
  f.type('hello');f.get('data-chat-input').focus();await f.send();assert.equal(f.get('data-chat-input').value,'hello');assert.equal(f.get('data-chat-input').readOnly,true);assert.equal(f.get('data-chat-send').textContent,'Retry same message');
  await f.send();const posts=f.requests.filter(r=>r.init.method==='POST');assert.equal(posts.length,2);assert.equal(posts[0].init.body,posts[1].init.body);assert.equal(f.get('data-chat-input').value,'');assert.equal(f.doc.activeElement,f.get('data-chat-input'));
});
test('new history is literal text and polling neither loses keyboard focus nor repeats history announcements',async()=>{
  const f=fixture();let messages=[message(1,'<img src=x onerror=alert(1)>')];f.setHandler(async()=>f.response({ok:true,room_id:ROOM,channel:'room',messages}));await f.join();
  const transcript=f.get('data-chat-messages'),row=transcript.children[0];assert.equal(row.children[1].textContent,'<img src=x onerror=alert(1)>');assert.equal(row.children[0].children[0].textContent,'<script>display name</script>');
  const live=f.all.find(n=>n.attributes.class==='greenroom-chat-announcement');assert.equal(live.textContent,'');f.get('data-chat-input').focus();await f.fire(1500);assert.equal(live.textContent,'');assert.equal(transcript.children[0],row);assert.equal(f.doc.activeElement,f.get('data-chat-input'));
  transcript.scrollHeight=800;transcript.scrollTop=0;messages=[...messages,message(2,'New')];await f.fire(1500);assert.equal(transcript.scrollTop,0);assert.equal(f.get('data-chat-new').hidden,false);assert.match(live.textContent,/New backstage/);
});
test('room closure and participant removal clear private content and cannot move a draft to another guest',async()=>{
  const f=fixture('producer');await f.join();f.change('data-chat-channel','private');f.change('data-chat-recipient',GUEST);f.type('Secret draft');f.chat.update({participants:[{id:OTHER,name:'Two',state:'admitted'}]});assert.equal(f.get('data-chat-recipient').value,'');assert.equal(f.get('data-chat-input').value,'');assert.equal(f.get('data-chat-send').disabled,true);
  f.change('data-chat-recipient',OTHER);f.type('Second draft');f.chat.update({active:false});assert.equal(f.get('data-chat-input').value,'');assert.equal(f.get('data-chat-messages').children.length,0);assert.equal(f.get('data-chat-input').disabled,true);
});
test('leave and destroy abort requests and ignore delayed reads and send receipts',async()=>{
  const f=fixture();await f.join();let finish;f.setHandler(()=>new Promise(resolve=>finish=resolve));f.type('Pending');const pending=f.send();f.chat.clear('You left.');finish(f.response({ok:true,room_id:ROOM,message:message(9,'Pending')}));await pending;assert.equal(f.get('data-chat-input').value,'');assert.equal(f.get('data-chat-status').textContent,'You left.');assert.ok(f.requests.at(-1).init.signal.aborted);
  f.chat.destroy();assert.equal(f.container.children.length,0);assert.equal(f.timers.size,0);assert.equal(f.container._greenroomChat,undefined);
});
test('polling never overlaps unresolved reads and exact channel guards reject foreign private history',async()=>{
  const f=fixture();let finish;f.setHandler(()=>new Promise(resolve=>finish=resolve));await f.join();await f.fire(1500);assert.equal(f.requests.length,1);finish(f.response({ok:true,room_id:ROOM,channel:'private',participant_id:OTHER,messages:[message(1,'foreign','private',OTHER)]}));await settle();assert.equal(f.get('data-chat-messages').children.length,0);assert.match(f.get('data-chat-status').textContent,/could not refresh/);
});
test('recoverable server rejection preserves editable draft and exposes only safe mapped text',async()=>{
  const f=fixture();await f.join();f.setHandler(async()=>f.response({ok:false,reason:'chat_rate_limited'},429));f.type('Keep this');await f.send();assert.equal(f.get('data-chat-input').value,'Keep this');assert.equal(f.get('data-chat-input').readOnly,false);assert.match(f.get('data-chat-status').textContent,/Wait a minute/);
  f.setHandler(async()=>f.response({ok:false,reason:'<secret token>'},403));await f.send();assert.ok(!f.get('data-chat-status').textContent.includes('secret'));
});
