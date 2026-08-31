const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/obs_source_audit.js'),'utf8');
function runtime(request){
  const nodes=new Map(),events={},calls=[];
  function node(){return {dataset:{},fields:{},handlers:{},children:[],
    querySelector(key){return this.fields[key]??=node();},replaceChildren(...children){this.children=children;},
    addEventListener(key,handler){this.handlers[key]=handler;}};}
  const get=id=>{if(!nodes.has(id))nodes.set(id,node());return nodes.get(id);};
  const context=vm.createContext({window:{},document:{getElementById:get,createElement:node,
    addEventListener:(name,fn)=>events[name]=fn},location:{origin:'http://127.0.0.1:9040'},AbortController});
  vm.runInContext(source,context);
  const options={request:async(...args)=>{calls.push(args);return request(...args);},format:item=>`${item.width} × ${item.height}`};
  const app=context.window.RareIQObsSourceAudit.init(options);
  return {app,get,calls,events,again:()=>context.window.RareIQObsSourceAudit.init(options),
    status:get('obsSourceAuditStatus'),rows:get('obsSourceAuditRows'),button:get('obsSourceCheck')};
}
const item={key:'set_chase',label:'Set Chase Bar',scene:'RareIQ Set Chase',url:'http://127.0.0.1:9040/overlay/set-chase',
  width:1280,height:320,state:'configured',issues:[]};
const report=(changes={})=>({ok:true,audit:{connected:true,read_only:true,checked_at:100,sources:[{...item}],
  diagnostic:{message:'Configuration only; check actual picture and audio.'},...changes}});
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};

test('source check is explicit, singleton and uses only the read-only route',async()=>{
  const app=runtime(async()=>report());
  assert.equal(app.calls.length,0);assert.equal(app.again(),app.app);
  await app.button.handlers.click();
  assert.equal(app.calls.length,1);
  const [url,options]=app.calls[0];
  assert.equal(url,'/api/production/obs/sources/check');assert.equal(options.method,'POST');
  assert.equal(options.timeoutMs,20000);assert.equal(options.retries,0);
  assert.deepEqual(JSON.parse(options.body),{base_url:'http://127.0.0.1:9040'});
  assert.equal(app.status.dataset.state,'configured');
  assert.match(app.status.querySelector('strong').textContent,/1 of 1 configured/);
  assert.match(app.status.querySelector('span').textContent,/actual picture and audio.*Snapshot/);
  const row=app.rows.children[0];
  assert.equal(row.querySelector('p').textContent,'1280 × 320');
  assert.equal(row.querySelector('code').textContent,item.url);
  assert.equal(row.querySelector('.obs-source-state').textContent,'Configured');
  assert.equal(row.querySelector('ul').hidden,true);
  assert.equal(app.button.disabled,false);
});

test('missing and review results have actionable labels and no all-clear',async()=>{
  const app=runtime(async()=>report({sources:[item,{...item,state:'missing',issues:[{message:'Add the clean source.'}]},
    {...item,state:'attention',issues:[{message:'Use 1280 × 320.'}]},{...item,state:'unavailable'}]}));
  await app.app.check();
  assert.equal(app.status.dataset.state,'attention');
  assert.match(app.status.querySelector('strong').textContent,/1 of 4 configured · 2 need attention · 1 not checked/);
  assert.equal(app.rows.children[1].querySelector('.obs-source-state').textContent,'Missing');
  assert.equal(app.rows.children[2].querySelector('ul').children[0].textContent,'Use 1280 × 320.');
});

test('disconnected and unknown states cannot render green even with inconsistent payloads',async()=>{
  const app=runtime(async()=>report({connected:false,sources:[item]}));
  await app.app.check();
  assert.equal(app.status.dataset.state,'unknown');
  assert.equal(app.rows.children[0].dataset.state,'unavailable');
  assert.equal(app.rows.children[0].querySelector('.obs-source-state').textContent,'Not checked');
  const unknown=runtime(async()=>report({sources:[{...item,state:'future-state'}]}));
  await unknown.app.check();
  assert.match(unknown.status.querySelector('strong').textContent,/0 of 1 configured · 0 need attention · 1 not checked/);
});

test('repeated clicks stay single-flight and old green rows disappear while checking',async()=>{
  const pending=deferred();let count=0;
  const app=runtime(async()=>++count===1?report():pending.promise);
  await app.app.check();
  assert.equal(app.rows.children.length,1);
  const first=app.app.check();await app.app.check();await app.app.check();
  assert.equal(app.calls.length,2);assert.equal(app.button.disabled,true);
  assert.equal(app.rows.children.length,0);assert.equal(app.status.dataset.state,'checking');
  pending.resolve(report());await first;
  assert.equal(app.button.disabled,false);
});

test('failed refresh clears earlier green results without exposing server errors',async()=>{
  let count=0;
  const app=runtime(async()=>{if(++count===1)return report();throw new Error('private-server-token');});
  await app.app.check();await app.app.check();
  assert.equal(app.rows.children.length,0);assert.equal(app.status.dataset.state,'unknown');
  assert.doesNotMatch(app.status.querySelector('span').textContent,/private-server-token/);
  assert.equal(app.button.disabled,false);
});

test('configuration changes abort pending check and late responses cannot repaint',async()=>{
  const pending=deferred();let count=0;
  const app=runtime(async()=>++count===1?pending.promise:report({sources:[{...item,state:'missing'}]}));
  const first=app.app.check();
  app.events['rareiq:api-start']({detail:{method:'POST',path:'/api/production/obs/settings'}});
  assert.equal(app.calls[0][1].signal.aborted,true);
  assert.equal(app.status.querySelector('strong').textContent,'Check needed');
  await app.app.check();
  pending.resolve(report());await first;
  assert.equal(app.rows.children[0].dataset.state,'missing');
  assert.equal(app.status.dataset.state,'attention');
  assert.equal(app.button.disabled,false);
});

test('bootstrap invalidates snapshot but unrelated and read requests do not',async()=>{
  const app=runtime(async()=>report());await app.app.check();
  for(const detail of [{method:'GET',path:'/api/production/obs/settings'},{method:'POST',path:'/api/unrelated'}]){
    app.events['rareiq:api-start']({detail});assert.equal(app.status.dataset.state,'configured');
  }
  app.events['rareiq:api-start']({detail:{method:'POST',path:'/api/production/obs/bootstrap'}});
  assert.equal(app.status.dataset.state,'unknown');assert.equal(app.rows.children.length,0);
});

test('empty or malformed reports fail closed',async()=>{
  for(const payload of [{},report({sources:[]}),report({sources:[null]}),report({connected:'yes'})]){
    const app=runtime(async()=>payload);await app.app.check();
    assert.equal(app.status.dataset.state,'unknown');assert.equal(app.rows.children.length,0);
    assert.equal(app.button.disabled,false);
  }
});

test('source labels and diagnostics are rendered as plain text',async()=>{
  const hostile='<img src=x onerror=alert(1)>';
  const app=runtime(async()=>report({sources:[{...item,label:hostile,issues:[{message:hostile}]}],diagnostic:{message:hostile}}));
  await app.app.check();const row=app.rows.children[0];
  assert.equal(row.querySelector('strong').textContent,hostile);
  assert.equal(row.querySelector('ul').children[0].textContent,hostile);
  assert.doesNotMatch(row.innerHTML,/onerror/);
});
