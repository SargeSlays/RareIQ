/* Isolated browser UI fixture: every request/media object is simulated; no server/device access. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'../../rareiq/web/static');
const destination=process.argv[2];
if(!destination||!path.isAbsolute(destination))throw Error('Supply an absolute evidence directory.');
fs.mkdirSync(destination,{recursive:true});
async function main(){
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio']});
  const page=await browser.newPage({viewport:{width:1920,height:1080}}),faults=[];
  page.on('pageerror',error=>faults.push(error.message));
  await page.route('**/*',route=>route.request().url()==='https://studio-fixture.local/'?route.fulfill({contentType:'text/html',body:'<!doctype html><html data-theme="dark"><body class="pp-shell studiox-ui4 studiox-premium studiox-command-deck" data-operator-layout="v2" data-studiox-visual-system="unified"><main id="workspace"></main></body></html>'}):route.abort());
  try{
    await page.goto('https://studio-fixture.local/');
    const control=fs.readFileSync(path.join(root,'control.html'),'utf8');
    const styles=[...control.matchAll(/<link rel="stylesheet" href="\/static\/([^"?]+)/g)].map(match=>match[1]);
    for(const file of styles)await page.addStyleTag({content:fs.readFileSync(path.join(root,file),'utf8').replace(/@import[^;]+;/g,'')});
    await page.addStyleTag({content:'html,body{margin:0;min-height:100%;overflow:visible!important}body{background:var(--pp-bg);font-family:var(--pp-font-ui)}#workspace{box-sizing:border-box;padding:24px;width:100%;}'});
    await page.evaluate(()=>{
      let sequence=0;const id='a'.repeat(32);
      const person={id,name:'Guest <img src=x onerror=alert(1)>',state:'waiting',connected:true,media:{microphone:true,camera:true,screen:true,screen_audio:true},sources:{camera:`guest:${id}:camera`,screen:`guest:${id}:screen`,audio:`guest:${id}:audio`}};
      const switcher={generation:0,updated_at:0,program_sources:['camera:1'],preview_sources:['camera:2'],preview_layout:'auto',program_layout:'auto',slots:[{slot_id:1,source_id:'local',connected:true,production_readiness:{ready:true}},{slot_id:2,source_id:null,connected:false,production_readiness:{ready:false}}]};
      const room={ok:true,room_id:'room',active:true,revision:1,max_guests:6,participants:[person],invites:[],switcher,output:{connected:1,ready_sources:[],rendered_generation:0}};
      const fixture=window.fixture={room,switcher,requests:[],captures:0,stops:0,publishers:[],localStream:null,conferenceParticipants:[],conflictNext:false,receiver:null,activityFail:0,
        activityEvents:Array.from({length:25},(_,index)=>({id:index,timestamp:Date.now()/1000-index,actor_kind:index===0?'guest_session':index===1?'program_renderer':'local_operator',actor_id:'private-account-id',identity_verified:false,action:index===0?'guest.admit':index===1?'program.rendered':'program.take',target:id,outcome:index===0?'succeeded':index===1?'confirmed':'requested',details:{token:'private-token',peer_id:'private-peer-id'}}))};
      const response=(payload,status=200)=>({ok:status<400,status,json:async()=>JSON.parse(JSON.stringify(payload))});
      const push=()=>fixture.receiver?.emit();fixture.push=push;
      window.fetch=async(url,options={})=>{
        const body=options.body?JSON.parse(options.body):null;fixture.requests.push({url,body,method:options.method||'GET'});
        if(!body){if(url.endsWith('/activity'))return fixture.activityFail-->0?response({ok:false,reason:'fixture_activity_unavailable'},503):response({ok:true,events:fixture.activityEvents});return response(url==='/api/production/greenroom'?room:switcher);}
        if(body.expected_revision!==undefined){
          if(fixture.conflictNext){fixture.conflictNext=false;room.revision++;return response({ok:false,reason:'room_revision_conflict'},409);}
          if(body.expected_revision!==room.revision)return response({ok:false,reason:'room_revision_conflict'},409);
          room.revision++;
        }
        if(url==='/api/production/greenroom/invites'){
          const invite={id:'invite-'+(++sequence),label:body.label,status:'ready',expires_at:Date.now()/1000+3600};room.invites.push(invite);push();
          return response({ok:true,invite_id:invite.id,join_url:'https://studio-fixture.local/guest#invite='+'b'.repeat(64)});
        }
        if(url==='/guest/join'){
          const hostid='c'.repeat(32),host={...person,id:hostid,name:body.name,state:'waiting',connected:false,media:{microphone:false,camera:false,screen:false,screen_audio:false},sources:{audio:`guest:${hostid}:audio`,camera:`guest:${hostid}:camera`,screen:`guest:${hostid}:screen`}};room.participants.push(host);room.revision++;push();return response(host);
        }
        if(url==='/guest/leave'){const host=room.participants.find(p=>p.id==='c'.repeat(32));if(host)host.state='removed';room.revision++;push();return response({ok:true});}
        if(url.includes('/participants/')){const guest=room.participants.find(p=>url.endsWith('/'+p.id));guest.state=body.action==='admit'?'admitted':'removed';push();return response({ok:true});}
        if(url.endsWith('/preview')){switcher.preview_sources=body.preview_sources;switcher.preview_layout=body.layout;switcher.updated_at++;push();return response(switcher);}
        if(url.endsWith('/take')){const old=switcher.program_sources;switcher.program_sources=body.preview_sources;switcher.preview_sources=old;switcher.program_layout=body.layout;switcher.generation++;switcher.updated_at++;push();return response(switcher);}
        return response({ok:true});
      };
      Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:async()=>{fixture.captures++;const context=new AudioContext(),destination=context.createMediaStreamDestination(),stream=destination.stream;fixture.captureContext=context;const track=stream.getAudioTracks()[0],stop=track.stop.bind(track);track.stop=()=>{fixture.stops++;stop();context.close();};return stream;}}});
      window.ProducerGuestMedia={
        createReceiver(callbacks){const receiver={state:()=>({room,return_audio_owner:true}),tracks:()=>({camera:null,screen:null,microphone:null,screen_audio:null}),subscribe:()=>()=>{},setReturnStream:()=>{},emit:()=>callbacks.onState({room}),connect:async()=>{callbacks.onConnection({state:'connected',peer_id:'producer'});queueMicrotask(()=>receiver.emit());},close:()=>{}};fixture.receiver=receiver;return receiver;},
        createPublisher(options){const publisher={setTracks:tracks=>{publisher.tracks=tracks;},connect:async()=>{const guest=room.participants.find(p=>p.id==='c'.repeat(32));guest.connected=true;guest.media.microphone=true;room.revision++;push();},close:()=>{publisher.closed=true;}};fixture.publishers.push(publisher);return publisher;},
        createConferenceAudio(receiver){return {start:async()=>{},sync:()=>{fixture.conferenceParticipants=receiver.state()?.room.participants.map(p=>p.id)||[];},setLocalStream:stream=>{fixture.localStream=stream;},setMonitor:enabled=>{fixture.monitor=enabled;},close:()=>{}};}
      };
    });
    await page.addScriptTag({content:fs.readFileSync(path.join(root,'greenroom_controls.js'),'utf8')});
    await page.evaluate(()=>ProducerGreenroomControls.mount(document.getElementById('workspace')));
    await page.waitForFunction(()=>document.querySelector('[data-room-count]').textContent.includes('1 / 6'));
    assert.equal(await page.evaluate(()=>fixture.captures),0,'mount never captures');
    assert.equal(await page.locator('[data-guest-name] img').count(),0,'guest labels are text');
    assert.equal(await page.locator('[data-source-kind="camera"]').isDisabled(),true);
    await page.locator('[data-admit]').click();await page.waitForFunction(()=>fixture.room.participants[0].state==='admitted');
    assert.equal(await page.evaluate(()=>fixture.requests.filter(r=>r.url.endsWith('/take')).length),0,'admission never takes Program');
    await page.locator('[data-source-kind="camera"]').click();await page.waitForFunction(()=>fixture.switcher.preview_sources[0].startsWith('guest:'));
    assert.equal(await page.evaluate(()=>fixture.switcher.preview_sources.length),1,'offline legacy preview dropped');
    assert.equal(await page.locator('[data-room-take]').isDisabled(),true);
    await page.evaluate(()=>{fixture.room.output.ready_sources=[fixture.room.participants[0].sources.camera];fixture.push();});
    await page.locator('[data-room-take]').click();await page.waitForFunction(()=>fixture.switcher.generation===1);
    assert.match(await page.locator('[data-output-state]').textContent(),/waiting for output confirmation/);
    await page.evaluate(()=>{fixture.room.output.rendered_generation=1;fixture.push();});
    assert.match(await page.locator('[data-output-state]').textContent(),/reports this Program/);
    await page.getByLabel('Invitation label').fill('Retained draft');await page.evaluate(()=>{fixture.conflictNext=true;});
    await page.locator('.greenroom-invite button').click();await page.waitForFunction(()=>document.querySelector('.greenroom-notice').textContent.includes('changed in another tab'));
    assert.equal(await page.getByLabel('Invitation label').inputValue(),'Retained draft');
    await page.locator('.greenroom-invite button').click();await page.locator('.greenroom-share').waitFor({state:'visible'});
    await page.locator('[data-dismiss-invite]').click();assert.equal(await page.getByLabel('Private invitation link').inputValue(),'');
    const beforeMic=await page.evaluate(()=>fixture.requests.filter(r=>r.url.endsWith('/take')).length);
    await page.locator('[data-host-mic]').click();await page.waitForFunction(()=>document.querySelector('[data-host-mic]').textContent==='Stop my microphone');
    assert.equal(await page.evaluate(()=>fixture.captures),1);
    assert.equal(await page.evaluate(()=>fixture.requests.filter(r=>r.url.endsWith('/take')).length),beforeMic,'host mic is never automatically taken');
    assert.equal(await page.evaluate(()=>Boolean(fixture.localStream)),true);
    assert.equal(await page.evaluate(()=>fixture.conferenceParticipants.includes('c'.repeat(32))),false,'host internal guest excluded from mix-minus inputs');
    assert.equal(await page.evaluate(()=>fixture.requests.filter(r=>r.url.endsWith('/activity')).length),0,'closed history never fetches on mount or decisions');
    await page.evaluate(()=>{fixture.activityFail=1;});await page.locator('.greenroom-activity summary').click();
    await page.waitForFunction(()=>document.querySelector('[data-activity-status]').textContent.includes('could not load'));
    await page.locator('[data-activity-refresh]').click();await page.waitForFunction(()=>document.querySelectorAll('.greenroom-activity li').length===20);
    assert.equal(await page.locator('.greenroom-activity img').count(),0);const history=await page.locator('.greenroom-activity ol').textContent();
    assert.match(history,/<img src=x onerror=alert\(1\)> \(display name\)/);assert.match(history,/Identity not verified/);assert.match(history,/Renderer confirmed/);assert.match(history,/Requested/);assert.ok(!history.includes('private-'));
    await page.evaluate(()=>{fixture.activityFail=1;});await page.locator('[data-activity-refresh]').click();await page.waitForFunction(()=>document.querySelector('[data-activity-status]').textContent.includes('previous list'));
    assert.equal(await page.locator('.greenroom-activity li').count(),20);await page.evaluate(()=>{fixture.activityEvents=fixture.activityEvents.slice(0,3);});await page.locator('[data-activity-refresh]').click();await page.waitForFunction(()=>document.querySelectorAll('.greenroom-activity li').length===3);
    const results=[];
    for(const theme of ['dark','light'])for(const width of [390,960,1920,3840]){
      await page.setViewportSize({width,height:width>=1920?1080:900});await page.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.operatorSkin=theme==='light'?'daylight':'ignite';},theme);
      const dimensions=await page.evaluate(()=>({horizontal:document.documentElement.scrollWidth>innerWidth,innerScroll:[...document.querySelectorAll('.production-greenroom,.production-greenroom *')].filter(e=>['auto','scroll'].includes(getComputedStyle(e).overflowY)&&e.scrollHeight>e.clientHeight+2).length}));
      assert.equal(dimensions.horizontal,false,`${theme} ${width} width`);assert.equal(dimensions.innerScroll,0,`${theme} ${width} content flows down`);
      await page.screenshot({path:path.join(destination,`greenroom-${theme}-${width}.png`),fullPage:true,animations:'disabled'});results.push({theme,width,...dimensions});
    }
    await page.locator('[data-host-mic]').click();await page.waitForFunction(()=>fixture.stops===1);assert.equal(await page.evaluate(()=>fixture.localStream),null);
    await page.evaluate(()=>ProducerGreenroomControls.mount(document.getElementById('workspace')).close());
    assert.deepEqual(faults,[]);fs.writeFileSync(path.join(destination,'summary.json'),JSON.stringify({isolated:true,hardware:false,results,checks:['no capture on mount','safe guest labels','admit does not take','offline camera removed','output receipt gating','conflict draft preserved','invitation dismissed','explicit host microphone','host mix-minus exclusion','host track cleanup','activity lazy load','activity retry preserves rows','activity bounded to 20','literal names and private IDs omitted'],faults},null,2));
    console.log(JSON.stringify({passed:true,viewportThemeChecks:results.length,interactionChecks:14,hardware:false}));
  }finally{await browser.close();}
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
