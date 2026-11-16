/* Real local fixture/browser, simulated capture and transport faults. No hardware. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const BASE='http://127.0.0.1:8768',destination=process.argv[2];
if(!destination||!path.isAbsolute(destination))throw Error('Absolute evidence directory required');
fs.mkdirSync(destination,{recursive:true});
async function main(){
  const marker=await fetch(BASE+'/__qa__/guest-fixture').then(r=>r.json());
  assert.equal(marker.isolated_guest_fixture,true);assert.equal(marker.hardware,false);
  const results={completed:false,browser:'headless Edge',server:'isolated loopback fixture',hardware:false,externalBroadcast:false,simulated:['generated microphone capture','browser permission denial','held signaling messages','socket constructor failure after deliberate disconnect']};
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio','--autoplay-policy=no-user-gesture-required']});
  const errors=[];let invitation=null,revoked=false,count=0;const stamp=Date.now();
  const request=async(url,body)=>{const response=await fetch(BASE+url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});assert.ok(response.ok,'fixture API status '+response.status);return response.json();};
  const mutate=async(url,body={})=>request(url,{...body,expected_revision:(await request('/api/production/greenroom')).revision,request_id:`recovery_${stamp}_${++count}`});
  async function until(check,label,ms=15000){const end=Date.now()+ms;while(Date.now()<end){if(await check())return;await new Promise(r=>setTimeout(r,100));}throw Error('Timed out: '+label);}
  async function page(){
    const page=await browser.newPage({viewport:{width:1280,height:1000}});page.on('pageerror',()=>errors.push('Unhandled browser error'));
    await page.addInitScript(()=>{
      window.qa={mode:'normal',deny:false,states:0,held:[],sockets:[],tracks:[],captures:0,captureHold:false,captureWaiters:[]};
      const Native=window.WebSocket;
      window.WebSocket=class extends Native{
        constructor(...args){if(qa.mode==='fail'&&String(args[0]).endsWith('/guest/ws'))throw Error('Simulated transport failure');super(...args);qa.sockets.push(this);this.addEventListener('message',event=>{try{if(JSON.parse(event.data).type==='state')qa.states++;}catch{}});}
        set onmessage(handler){super.onmessage=event=>{if(qa.mode==='hold'){qa.held.push(()=>handler?.(event));return;}handler?.(event);};}
        get onmessage(){return super.onmessage;}
      };
      navigator.mediaDevices.getUserMedia=async constraints=>{
        qa.captures++;if(qa.deny)throw new DOMException('Simulated denial','NotAllowedError');
        if(qa.captureHold)await new Promise(resolve=>qa.captureWaiters.push(resolve));
        const tracks=[];
        if(constraints.audio){const context=new AudioContext();qa.contexts??=[];qa.contexts.push(context);const output=context.createMediaStreamDestination();output.channelCount=1;await context.resume();tracks.push(...output.stream.getAudioTracks());}
        if(constraints.video){const canvas=document.createElement('canvas');canvas.width=320;canvas.height=180;canvas.getContext('2d').fillRect(0,0,320,180);tracks.push(...canvas.captureStream(1).getVideoTracks());}
        qa.tracks.push(...tracks);return new MediaStream(tracks);
      };
      navigator.mediaDevices.enumerateDevices=async()=>[{kind:'audioinput',deviceId:'fixture-mic',label:'Fixture microphone'}];
      navigator.mediaDevices.getDisplayMedia=async()=>navigator.mediaDevices.getUserMedia({video:true,audio:false});
    });
    return page;
  }
  try{
    const missing=await page();await missing.goto(BASE+'/guest');
    assert.equal(await missing.locator('#guestJoin').isDisabled(),true);
    await missing.locator('#guestMicrophone').click();
    assert.equal(await missing.locator('#guestJoin').isDisabled(),true,'capture completion must not enable a missing invite');
    await missing.locator('#guestMicrophone').click();
    assert.equal(await missing.locator('#guestJoin').isDisabled(),true,'capture stop must not enable a missing invite');
    assert.equal(await missing.evaluate(()=>qa.tracks.every(track=>track.readyState==='ended')),true);
    results.missingInviteStaysDisabled=true;
    await missing.locator('#guestMicrophone').click();await missing.evaluate(()=>qa.captureHold=true);await missing.locator('#guestCamera').click();
    await until(()=>missing.evaluate(()=>qa.captureWaiters.length===1),'camera permission held');
    assert.equal(await missing.locator('#guestMicrophone').isDisabled(),false,'mic off available during camera permission');
    await missing.locator('#guestMicrophone').click();assert.equal(await missing.evaluate(()=>qa.tracks.filter(t=>t.kind==='audio').every(t=>t.readyState==='ended')),true);
    await missing.evaluate(()=>{qa.captureHold=false;qa.captureWaiters.splice(0).forEach(resolve=>resolve());});
    await until(async()=>await missing.locator('#guestCamera').getAttribute('aria-pressed')==='true','requested camera settles independently');await missing.locator('#guestCamera').click();
    await missing.locator('#guestMicrophone').click();await missing.locator('summary').click();await missing.evaluate(()=>qa.captureHold=true);
    await missing.locator('#guestMicDevice').selectOption('fixture-mic');await until(()=>missing.evaluate(()=>qa.captureWaiters.length===1),'replacement microphone permission held');
    assert.equal(await missing.locator('#guestMicrophone').isDisabled(),false,'mic off available during replacement');await missing.locator('#guestMicrophone').click();
    await missing.evaluate(()=>{qa.captureHold=false;qa.captureWaiters.splice(0).forEach(resolve=>resolve());});
    await until(()=>missing.evaluate(()=>qa.tracks.every(t=>t.readyState==='ended')),'cancelled replacement tracks retired');
    assert.equal(await missing.locator('#guestMicrophone').getAttribute('aria-pressed'),'false');
    results.stopCaptureDuringOtherPermission=true;results.cancelReplacementCannotReopen=true;
    await missing.locator('#guestScreen').click();assert.match(await missing.locator('#guestMediaHint').innerText(),/private|on this device/i,'screen preview clearly stays local before joining');
    await missing.evaluate(()=>{const track=qa.tracks.filter(t=>t.kind==='video').at(-1);track.stop();track.dispatchEvent(new Event('ended'));});
    await until(async()=>await missing.locator('#guestScreen').getAttribute('aria-pressed')==='false','screen-ended event clears sharing');
    assert.match(await missing.locator('#guestDeviceStatus').innerText(),/screen.*(?:stopped|ended)|sharing.*stopped/i);results.privateScreenAndEndedFeedback=true;
    await missing.screenshot({path:path.join(destination,'missing-invitation.png'),fullPage:true});
    results.layouts=[];for(const theme of ['ignite','daylight'])for(const width of [390,960,1920,3840]){await missing.setViewportSize({width,height:width===3840?2160:1080});await missing.evaluate(value=>document.documentElement.setAttribute('data-operator-skin',value),theme);assert.equal(await missing.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,theme+' '+width+' feedback fits');await missing.screenshot({path:path.join(destination,`device-${theme}-${width}.png`),fullPage:true});results.layouts.push({theme,width,overflow:false});}
    await missing.close();

    const state=await request('/api/production/greenroom');assert.equal(state.active,true,'parent-owned fixture room must already be open');
    invitation=await mutate('/api/production/greenroom/invites',{label:'Recovery browser fixture',ttl_minutes:10});
    const guest=await page();let joins=0;guest.on('request',request=>{if(request.url()===BASE+'/guest/join')joins++;});
    await guest.goto(invitation.join_url);await guest.locator('#guestName').fill('Recovery browser fixture');
    await guest.locator('#guestMicrophone').click();await guest.evaluate(()=>qa.mode='hold');await guest.locator('#guestJoin').click();
    await until(()=>guest.evaluate(()=>qa.held.length>0),'real socket handshake held');
    assert.equal(await guest.locator('#guestMicrophone').isDisabled(),false,'active capture can be stopped while admission connects');
    await guest.locator('#guestMicrophone').click();
    assert.equal(await guest.evaluate(()=>qa.tracks.every(track=>track.readyState==='ended')),true,'mic off stops synthetic capture while connecting');
    await guest.evaluate(()=>{qa.mode='normal';for(const deliver of qa.held.splice(0))deliver();});
    await until(async()=>await guest.locator('#guestBadge').innerText()==='WAITING FOR PRODUCER','joined real fixture');
    results.stopCaptureDuringSlowJoin=true;
    const participant=(await request('/api/production/greenroom')).participants.find(p=>p.name==='Recovery browser fixture');assert.ok(participant?.connected);

    await guest.evaluate(()=>qa.deny=true);await guest.locator('#guestMicrophone').click();
    const denied=await guest.locator('#guestDeviceStatus').innerText();assert.match(denied,/permission was not granted/);
    const beforeStates=await guest.evaluate(()=>qa.states);
    await mutate('/api/production/greenroom/participants/'+participant.id,{action:'admit'});
    await until(()=>guest.evaluate(previous=>qa.states>previous,beforeStates),'another real room update');
    assert.equal(await guest.locator('#guestDeviceStatus').innerText(),denied,'room polling must preserve device guidance');
    results.permissionErrorPersistsAcrossRoomUpdate=true;
    await guest.screenshot({path:path.join(destination,'permission-feedback.png'),fullPage:true});

    const storedSession=await guest.evaluate(()=>sessionStorage.getItem('producer.guest.session.v1'));
    await guest.evaluate(()=>{qa.mode='fail';for(const socket of qa.sockets)if(socket.readyState===WebSocket.OPEN)socket.close(4000,'Simulated interruption');});
    await until(()=>guest.locator('#guestReconnect').isVisible(),'terminal network recovery control');
    assert.match(await guest.locator('#guestConnectionStatus').innerText(),/Retry connection/);
    assert.match(await guest.locator('#guestMediaHint').innerText(),/paused|not reaching|not being sent/i,'disconnected media status stays truthful');
    await guest.screenshot({path:path.join(destination,'retry-connection.png'),fullPage:true});
    await guest.evaluate(()=>qa.mode='normal');await guest.locator('#guestReconnect').click();
    await until(async()=>await guest.locator('#guestBadge').innerText()==='BACKSTAGE','reconnect to real fixture');
    assert.equal(await guest.locator('#guestReconnect').isVisible(),false);
    assert.equal(await guest.locator('#guestConnectionStatus').isVisible(),false);
    assert.equal(await guest.evaluate(()=>sessionStorage.getItem('producer.guest.session.v1')),storedSession);
    assert.equal(joins,1,'retry reuses session without consuming another invitation');
    const resumed=(await request('/api/production/greenroom')).participants.find(p=>p.id===participant.id);assert.ok(resumed?.connected);
    results.reconnectWithSameSession=true;results.noDuplicateJoin=true;

    await mutate('/api/production/greenroom/invites/'+invitation.invite_id+'/revoke');revoked=true;
    await until(async()=>await guest.locator('#guestBadge').getAttribute('data-connection-reason')==='guest_access_ended','real server revocation');
    assert.equal(await guest.locator('#guestReconnect').isVisible(),false);assert.equal(await guest.locator('#guestJoin').isDisabled(),true);
    const connections=await guest.evaluate(()=>qa.sockets.length);
    await guest.evaluate(()=>document.getElementById('guestReconnect').dispatchEvent(new Event('click')));
    await new Promise(resolve=>setTimeout(resolve,250));assert.equal(await guest.evaluate(()=>qa.sockets.length),connections,'revoked UI cannot reconnect');
    await guest.reload();await guest.locator('#guestJoin').click();
    await until(async()=>await guest.locator('#guestBadge').getAttribute('data-connection-reason')==='guest_access_ended','revoked saved session denied after reload');
    assert.equal(await guest.locator('#guestReconnect').isVisible(),false);assert.equal(await guest.locator('#guestJoin').isDisabled(),true);
    assert.equal((await request('/api/production/greenroom')).participants.find(p=>p.id===participant.id)?.connected,false);
    results.serverRevocationBlocksRetryAndReload=true;await guest.screenshot({path:path.join(destination,'revoked-invitation.png'),fullPage:true});
    assert.deepEqual(errors,[]);results.pageErrors=errors;results.completed=true;
    fs.writeFileSync(path.join(destination,'results.json'),JSON.stringify(results,null,2));console.log(JSON.stringify(results));
  }finally{
    fs.writeFileSync(path.join(destination,'results.json'),JSON.stringify(results,null,2));
    if(invitation&&!revoked)await mutate('/api/production/greenroom/invites/'+invitation.invite_id+'/revoke').catch(()=>{});
    await browser.close();
  }
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
