/* Generated pictures only, real isolated host/browser connections. No hardware. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const BASE='http://127.0.0.1:8768',destination=process.argv[2];
if(!destination||!path.isAbsolute(destination))throw Error('Absolute evidence directory required');
fs.mkdirSync(destination,{recursive:true});
async function main(){
  const marker=await fetch(BASE+'/__qa__/guest-fixture').then(r=>r.json());assert.equal(marker.isolated_guest_fixture,true);assert.equal(marker.hardware,false);
  const result={complete:false,hardware:false,realPeerConnections:true,generatedCameras:true};
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio','--autoplay-policy=no-user-gesture-required','--disable-background-timer-throttling','--disable-renderer-backgrounding']});
  const faults=[];let n=0;const stamp=Date.now();
  const api=async(url,body)=>{const r=await fetch(BASE+url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const data=await r.json();assert.ok(r.ok,'API '+(data.reason||r.status));return data;};
  const room=()=>api('/api/production/greenroom');
  const mutate=async(url,body={})=>api(url,{...body,expected_revision:(await room()).revision,request_id:`gallery_${stamp}_${++n}`});
  async function until(check,label,ms=20000){const end=Date.now()+ms;while(Date.now()<end){if(await check())return;await new Promise(r=>setTimeout(r,100));}throw Error('Timed out: '+label);}
  async function page(){const p=await browser.newPage({viewport:{width:1280,height:1000}});p.on('pageerror',e=>faults.push(e.message));return p;}
  async function guest(name,color,url){
    if(!url)url=(await mutate('/api/production/greenroom/invites',{label:name,ttl_minutes:15})).join_url;
    const p=await page();await p.addInitScript(({color})=>{window.qaTracks=[];window.qaViews=[];const Native=WebSocket;window.WebSocket=class extends Native{constructor(url,...rest){super(url,...rest);if(String(url).endsWith('/guest/view/ws'))qaViews.push(this);}};navigator.mediaDevices.getUserMedia=async request=>{if(request.audio)throw Error('Only generated camera requested by this test');const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;const context=canvas.getContext('2d');let x=0;setInterval(()=>{context.fillStyle=color;context.fillRect(0,0,640,360);context.fillStyle='#fff';context.font='36px sans-serif';context.fillText('Camera rehearsal',30,65);context.fillRect(x++%580,285,55,30);},80);const stream=canvas.captureStream(12);qaTracks.push(...stream.getTracks());return stream;};navigator.mediaDevices.enumerateDevices=async()=>[];navigator.mediaDevices.getDisplayMedia=async()=>{throw Error('Screen capture forbidden in gallery test');};},{color});
    await p.goto(url);await p.locator('#guestName').fill(name);await p.locator('#guestCamera').click();await p.locator('#guestJoin').click();await until(async()=>await p.locator('#guestBadge').innerText()==='WAITING FOR PRODUCER','guest joins waiting');
    const person=(await room()).participants.find(x=>x.name===name&&x.state==='waiting');assert.ok(person);return {page:p,person};
  }
  const tile=(p,id)=>p.locator(`.greenroom-guest[data-participant-id="${id}"]`);
  const picture=(p,id)=>p.locator(`.guest-room-person[data-room-participant="${id}"] video`).evaluateAll(nodes=>nodes.some(v=>v.videoWidth>0&&!v.hidden&&v.srcObject?.getVideoTracks().some(t=>t.readyState==='live')));
  try{
    if((await room()).active)await mutate('/api/production/greenroom/room/close');await mutate('/api/production/greenroom/room/open');
    const producer=await page();await producer.goto(BASE+'/control?workspace=studio');await producer.locator('.production-greenroom').waitFor();
    const output=await page();await output.goto(BASE+'/program');
    const a=await guest('Room Alice','#236598'),b=await guest('Room Bob','#985325');
    await until(()=>a.page.locator('#guestRoom').isVisible(),'waiting gallery');assert.equal(await picture(a.page,b.person.id),false);assert.equal(await picture(b.page,a.person.id),false);
    await tile(producer,a.person.id).locator('[data-admit]').click();await until(async()=>await a.page.locator('#guestBadge').innerText()==='BACKSTAGE','first admission');assert.equal(await picture(b.page,a.person.id),false);
    await tile(producer,b.person.id).locator('[data-admit]').click();await until(()=>picture(a.page,b.person.id),'Alice sees Bob');await until(()=>picture(b.page,a.person.id),'Bob sees Alice');
    assert.equal(await a.page.locator('#guestRoom video').evaluateAll(v=>v.every(x=>x.muted&&x.srcObject?.getAudioTracks().length===0)),true);result.admittedCameraGallery=true;result.waitingPrivacy=true;result.noDuplicateAudio=true;
    await a.page.locator('[data-chat-input]').fill('Ready in the room');await a.page.locator('[data-chat-send]').click();await until(()=>b.page.locator('[data-chat-messages]').innerText().then(t=>t.includes('Ready in the room')),'chat alongside gallery');result.chatAlongsideGallery=true;
    if((await api('/api/production/switcher')).preview_sources.length)await producer.locator('[data-preview-clear]').click();await until(async()=>(await api('/api/production/switcher')).preview_sources.length===0,'preview clear');
    await tile(producer,a.person.id).locator('[data-source-kind="camera"]').click();await until(async()=>(await api('/api/production/switcher')).preview_sources.includes(a.person.sources.camera),'Alice source prepared');await tile(producer,b.person.id).locator('[data-source-kind="camera"]').click();await until(()=>producer.locator('[data-room-take]').isEnabled(),'both cameras ready');await producer.locator('[data-room-take]').click();await until(async()=>(await api('/api/production/switcher')).program_sources.includes(b.person.sources.camera),'sources taken');
    await until(()=>output.locator('.composition-layer:not(.composition-outgoing) video').count().then(n=>n===2),'two camera output');result.producerSourceSelection=true;
    const oldViews=await b.page.evaluate(()=>qaViews.length);await b.page.evaluate(()=>qaViews.filter(s=>s.readyState===1).forEach(s=>s.close(4000,'Synthetic picture interruption')));await until(()=>b.page.evaluate(old=>qaViews.length>old&&qaViews.at(-1).readyState===1,oldViews),'new viewer socket');await until(()=>picture(b.page,a.person.id),'room view reconnect');assert.equal(await b.page.evaluate(()=>qaTracks.every(t=>t.readyState==='live')),true);result.pictureReconnectKeepsCapture=true;
    result.layouts=[];for(const theme of ['ignite','daylight'])for(const width of [390,960,1920,3840]){await a.page.setViewportSize({width,height:width===3840?2160:1080});await a.page.evaluate(t=>document.documentElement.setAttribute('data-operator-skin',t),theme);assert.equal(await a.page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await a.page.locator('#guestRoom').screenshot({path:path.join(destination,`room-${theme}-${width}.png`)});result.layouts.push({theme,width,overflow:false});}
    await producer.locator('.production-greenroom').screenshot({path:path.join(destination,'producer-room.png')});
    await tile(producer,b.person.id).locator('[data-wait]').click();await until(async()=>await b.page.locator('#guestBadge').innerText()==='WAITING FOR PRODUCER','return to waiting');await until(async()=>!(await picture(a.page,b.person.id))&&!(await picture(b.page,a.person.id)),'waiting clears borrowed pictures');
    const afterWait=await api('/api/production/switcher');assert.ok(![...afterWait.program_sources,...afterWait.preview_sources].includes(b.person.sources.camera));assert.equal(await b.page.evaluate(()=>qaTracks.every(t=>t.readyState==='live')),true);
    await tile(producer,b.person.id).locator('[data-admit]').click();await until(()=>picture(a.page,b.person.id),'readmit same session');assert.equal((await room()).participants.filter(p=>p.name==='Room Bob').length,1);assert.ok(!(await api('/api/production/switcher')).program_sources.includes(b.person.sources.camera));result.waitReadmitKeepsOffProgram=true;
    await tile(producer,b.person.id).locator('[data-remove]').click();assert.equal((await room()).participants.find(p=>p.id===b.person.id).state,'admitted');await tile(producer,b.person.id).locator('[data-remove-cancel]').click();await tile(producer,b.person.id).locator('[data-remove]').click();await tile(producer,b.person.id).locator('[data-remove-confirm]').click();await until(()=>b.page.locator('[data-chat-input]').isDisabled(),'removed loses chat');await until(()=>b.page.evaluate(()=>qaTracks.every(t=>t.readyState==='ended')),'removed capture stops');assert.equal(await b.page.locator('#guestRoom video').count(),0);
    await producer.locator(`[data-reinvite="${b.person.id}"]`).click();await until(async()=>String(await producer.locator('[data-open-invite]').getAttribute('href')).includes('#invite='),'fresh invitation ready');const link=await producer.locator('[data-open-invite]').getAttribute('href');assert.ok(link?.includes('#invite='));const rejoined=await guest('Room Bob return','#985325',link);assert.notEqual(rejoined.person.id,b.person.id);assert.equal(rejoined.person.state,'waiting');result.removeConfirmAndFreshReinvite=true;
    await a.page.locator('#guestLeave').click();await rejoined.page.locator('#guestLeave').click();assert.deepEqual(faults.filter(x=>x!=='read_blocked_in_guest_fixture'),[]);result.complete=true;console.log(JSON.stringify(result));
  }finally{fs.writeFileSync(path.join(destination,'room-results.json'),JSON.stringify(result,null,2));await browser.close();}
}
main().catch(e=>{console.error(e.message);process.exitCode=1;});
