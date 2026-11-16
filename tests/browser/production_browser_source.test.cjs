const test=require('node:test'),assert=require('node:assert/strict');
const source=require('../../tools/experiments/production_browser_source.js');
const studio='http://127.0.0.1:8765';
test('browser embed rejects local addresses, credentials, alternate protocols and Studio',()=>{
  for(const value of ['http://example.com','javascript:alert(1)','data:text/html,hi','file:///C:/secret','https://user:pass@example.com','https://example.com:8443','https://127.0.0.1','https://2130706433','https://0x7f000001','https://[::1]','https://localhost','https://camera.lan','https://x.local','https://x.test','https://x.internal','https://x.home','https://example.com.','https://x..com','https://example.com\\@127.0.0.1','https://example.com\n/path'])assert.throws(()=>source.validatedUrl(value,studio),undefined,value);
  assert.throws(()=>source.validatedUrl('https://studio.example.com/panel','https://studio.example.com'));
  assert.throws(()=>source.validatedUrl('https://example.com'));
  assert.equal(source.validatedUrl('https://Overlay.Example.com/widget?q=hello%20world#title',studio),'https://overlay.example.com/widget?q=hello%20world#title');
});
function fixture(){
  const events=new Map(),attrs={},states=[],order=[];let counter=0;
  const frame={style:{},setAttribute(k,v){attrs[k]=v;order.push(k);},removeAttribute(k){delete attrs[k];},addEventListener(k,fn){events.set(k,fn);},removeEventListener(k){events.delete(k);},remove(){this.removed=true;},set src(v){this.address=v;order.push('src');}};
  const document={createElement:()=>frame},container={ownerDocument:document,append(){order.push('append');}},view=source.mount({container,url:'https://overlay.example.com/view',studioOrigin:studio,onState:v=>states.push(v),makeToken:()=>String(++counter)});
  return {view,frame,attrs,states,order,load:()=>events.get('load')?.(),error:()=>events.get('error')?.()};
}
test('browser navigation starts sandboxed, inert and without media or referrer permissions',()=>{
  const f=fixture();assert.equal(f.attrs.sandbox,'allow-scripts');assert.equal(f.attrs.referrerpolicy,'no-referrer');assert.equal(f.attrs.inert,'');assert.equal(f.frame.tabIndex,-1);assert.equal(f.frame.style.pointerEvents,'none');assert.ok(f.attrs.allow.includes("camera 'none'"));assert.ok(f.attrs.allow.includes("microphone 'none'"));assert.ok(f.attrs.allow.includes("autoplay 'none'"));assert.ok(f.order.indexOf('sandbox')<f.order.indexOf('src'));assert.ok(f.order.indexOf('src')<f.order.indexOf('append'));
});
test('load never means ready; only current per-load token can record a visual review',()=>{
  const f=fixture();assert.equal(f.view.review('1'),false);f.load();const token=f.view.snapshot().reviewToken;assert.equal(f.view.snapshot().phase,'loaded_unverified');assert.equal(f.view.snapshot().ready,undefined);assert.equal(f.view.review('forged'),false);assert.equal(f.view.review(token),true);assert.equal(f.view.snapshot().phase,'visual_reviewed');assert.equal(f.view.snapshot().reviewToken,null);assert.equal(f.view.review(token),false);
  f.load();assert.equal(f.view.snapshot().phase,'loaded_unverified');assert.notEqual(f.view.snapshot().reviewToken,token);assert.equal(f.view.review(token),false);f.error();assert.equal(f.view.snapshot().phase,'unavailable');assert.equal(f.view.snapshot().reviewToken,null);
});
test('reload, replacement and destruction cannot retain an earlier review',()=>{
  const f=fixture();f.load();const token=f.view.snapshot().reviewToken;f.view.reload();assert.equal(f.view.snapshot().phase,'loading');assert.equal(f.view.review(token),false);f.load();assert.equal(f.view.review(f.view.snapshot().reviewToken),true);f.view.destroy();f.view.destroy();f.load();assert.equal(f.frame.removed,true);assert.equal(f.view.snapshot().phase,'closed');assert.equal(f.view.reload(),false);assert.equal(f.view.review(token),false);assert.equal(fixture().view.review(token),false);
});
