/* Real local browsers and SQLite chat. No hardware, real guests or broadcasting. */
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
  const results={completed:false,hardware:false,externalBroadcast:false,realBrowsers:true,realChatDatabase:true};
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio']});
  const faults=[],pages=[];let sequence=0;const stamp=Date.now();
  const api=async(url,body)=>{const r=await fetch(BASE+url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});assert.ok(r.ok,'Fixture API '+r.status);return r.json();};
  const room=()=>api('/api/production/greenroom');
  const mutate=async(url,body={})=>api(url,{...body,expected_revision:(await room()).revision,request_id:`chat_${stamp}_${++sequence}`});
  async function until(check,label){const end=Date.now()+15000;while(Date.now()<end){if(await check())return;await new Promise(r=>setTimeout(r,100));}throw Error('Timed out: '+label);}
  async function page(){const page=await browser.newPage({viewport:{width:1280,height:1000}});pages.push(page);page.on('pageerror',error=>faults.push(error.message));await page.addInitScript(()=>{window.qaCaptures=0;navigator.mediaDevices.getUserMedia=async()=>{qaCaptures++;throw Error('Physical capture forbidden in chat QA');};navigator.mediaDevices.getDisplayMedia=navigator.mediaDevices.getUserMedia;navigator.mediaDevices.enumerateDevices=async()=>[];});return page;}
  async function guest(label){const invite=await mutate('/api/production/greenroom/invites',{label,ttl_minutes:15});const p=await page();await p.goto(invite.join_url);await p.locator('#guestName').fill(label);await p.locator('#guestJoin').click();await until(async()=>await p.locator('[data-chat-input]').isEnabled(),'guest chat ready');const person=(await room()).participants.find(x=>x.name===label);assert.ok(person);return {page:p,person,invite};}
  const messages=p=>p.locator('[data-chat-messages]');
  const has=(p,text)=>messages(p).innerText().then(value=>value.includes(text));
  async function send(p,text,keyboard=false){await p.locator('[data-chat-input]').fill(text);if(keyboard)await p.locator('[data-chat-input]').press('Control+Enter');else await p.locator('[data-chat-send]').click();await until(()=>has(p,text),'message rendered');}
  async function channel(p,value,recipient){await p.locator('[data-chat-channel]').selectOption(value);if(recipient)await p.locator('[data-chat-recipient]').selectOption(recipient);await until(()=>p.locator('[data-chat-input]').isEnabled(),'conversation ready');}
  try{
    if((await room()).active)await mutate('/api/production/greenroom/room/close');
    await mutate('/api/production/greenroom/room/open');
    const producer=await page();await producer.goto(BASE+'/control?workspace=studio');await producer.locator('.production-greenroom .greenroom-chat').waitFor();
    const alice=await guest('Fixture Alice'),bob=await guest('Fixture Bob');
    const before=await room(),switcherBefore=await api('/api/production/switcher');
    await send(alice.page,'Hello backstage — shared room',true);await until(()=>has(bob.page,'Hello backstage'),'guest B receives shared');await until(()=>has(producer,'Hello backstage'),'producer receives shared');
    const html='<img src=x onerror="window.qaUnsafe=true"> literal text';await send(bob.page,html);assert.equal(await messages(alice.page).locator('img').count(),0);await until(()=>has(alice.page,html),'literal text delivered');assert.equal(await alice.page.evaluate(()=>Boolean(window.qaUnsafe)),false);
    await channel(alice.page,'private');await send(alice.page,'Private cue for Alice');await channel(producer,'private',alice.person.id);await until(()=>has(producer,'Private cue for Alice'),'producer receives Alice private');await send(producer,'Alice, you are next');await until(()=>has(alice.page,'Alice, you are next'),'private producer reply');
    assert.equal(await has(bob.page,'Private cue for Alice'),false);await channel(bob.page,'private');await send(bob.page,'Private cue for Bob');assert.equal(await has(bob.page,'Alice, you are next'),false);await channel(producer,'private',bob.person.id);await until(()=>has(producer,'Private cue for Bob'),'producer receives Bob private');assert.equal(await has(producer,'Private cue for Alice'),false);
    await alice.page.locator('[data-chat-input]').fill('Draft kept for Alice private');await channel(alice.page,'room');await alice.page.locator('[data-chat-input]').fill('Shared draft');await channel(alice.page,'private');assert.equal(await alice.page.locator('[data-chat-input]').inputValue(),'Draft kept for Alice private');await channel(alice.page,'room');assert.equal(await alice.page.locator('[data-chat-input]').inputValue(),'Shared draft');
    let dropped=false;
    await alice.page.route('**/guest/chat',async route=>{if(route.request().method()==='POST'&&!dropped){dropped=true;await route.fetch();await route.abort('failed');}else await route.continue();});
    await alice.page.locator('[data-chat-input]').fill('Retry creates one message');await alice.page.locator('[data-chat-send]').click();await until(async()=>/Retry same message/.test(await alice.page.locator('[data-chat-send]').innerText()),'uncertain delivery retry');await alice.page.locator('[data-chat-send]').click();await until(async()=>await alice.page.locator('[data-chat-input]').inputValue()==='','retry resolves');
    const history=await api('/api/production/greenroom/chat?channel=room');assert.equal(history.messages.filter(m=>m.text==='Retry creates one message').length,1);results.duplicateRetry=true;
    assert.equal((await room()).revision,before.revision,'chat does not change production revision');assert.equal((await api('/api/production/switcher')).generation,switcherBefore.generation,'chat does not take Program');
    assert.ok(await messages(alice.page).locator('time[datetime]').count());assert.match(await messages(alice.page).innerText(),/Fixture Alice/);results.sharedAndPrivate=true;results.senderAndTime=true;results.literalText=true;results.independentDrafts=true;results.noProductionChanges=true;
    results.layouts=[];
    for(const theme of ['dark','light'])for(const width of [390,960,1920,3840]){await alice.page.setViewportSize({width,height:width===3840?2160:width>=1920?1080:900});await alice.page.evaluate(value=>document.documentElement.setAttribute('data-operator-skin',value==='light'?'daylight':'ignite'),theme);assert.equal(await alice.page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'guest chat fits '+theme+' '+width);await alice.page.screenshot({path:path.join(destination,`guest-chat-${theme}-${width}.png`),fullPage:true});results.layouts.push({surface:'guest',theme,width,overflow:false});}
    for(const theme of ['dark','light'])for(const width of [960,1920,3840]){await producer.setViewportSize({width,height:1080});await producer.evaluate(value=>document.documentElement.setAttribute('data-operator-skin',value==='light'?'daylight':'ignite'),theme);await producer.locator('.greenroom-chat').scrollIntoViewIfNeeded();assert.equal(await producer.evaluate(()=>{const c=document.querySelector('.greenroom-chat');return c.scrollWidth>c.clientWidth+1;}),false,'producer chat fits '+theme+' '+width);await producer.locator('.greenroom-chat').screenshot({path:path.join(destination,`producer-chat-${theme}-${width}.png`)});results.layouts.push({surface:'producer',theme,width,overflow:false});}
    await mutate('/api/production/greenroom/invites/'+alice.invite.invite_id+'/revoke');await until(async()=>await alice.page.locator('[data-chat-input]').isDisabled(),'revoked chat disabled');assert.equal(await messages(alice.page).locator('li').count(),0);results.revocationClearsChat=true;
    await mutate('/api/production/greenroom/room/close');await until(async()=>await bob.page.locator('[data-chat-input]').isDisabled(),'closed room disables chat');await mutate('/api/production/greenroom/room/open');await until(async()=>await producer.locator('[data-chat-channel]').inputValue()==='room'&&await producer.locator('[data-chat-input]').isEnabled(),'new room ready');assert.equal(await messages(producer).locator('li').count(),0);assert.equal((await api('/api/production/greenroom/chat?channel=room')).messages.length,0);results.newRoomIsolation=true;
    for(const p of pages)assert.equal(await p.evaluate(()=>qaCaptures),0);results.blockedUnrelatedFixtureReads=faults.filter(x=>x==='read_blocked_in_guest_fixture').length;assert.deepEqual(faults.filter(x=>x!=='read_blocked_in_guest_fixture'),[]);results.completed=true;console.log(JSON.stringify(results));
  }finally{fs.writeFileSync(path.join(destination,'results.json'),JSON.stringify(results,null,2));await browser.close();}
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
