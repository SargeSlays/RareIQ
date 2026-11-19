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
      const person={id,name:'Guest <img src=x onerror=alert(1)>',state:'waiting',connected:true,program_audio:{microphone_muted:false,screen_muted:false},media:{microphone:true,camera:true,screen:true,screen_audio:true},sources:{camera:`guest:${id}:camera`,screen:`guest:${id}:screen`,audio:`guest:${id}:audio`}};
      const switcher={generation:0,updated_at:0,program_sources:['camera:1'],preview_sources:['camera:2'],preview_layout:'auto',program_layout:'auto',slots:[{slot_id:1,source_id:'local',connected:true,production_readiness:{ready:true}},{slot_id:2,source_id:null,connected:false,production_readiness:{ready:false}}]};
      const room={ok:true,room_id:'room',active:true,revision:1,max_guests:6,participants:[person],invites:[],switcher,output:{connected:1,ready_sources:[],rendered_generation:0}};
      const fixture=window.fixture={room,switcher,requests:[],captures:0,stops:0,publishers:[],localStream:null,conferenceParticipants:[],conflictNext:false,holdProgramAudio:false,releaseProgramAudio:null,receiver:null,activityFail:0,
        activityEvents:Array.from({length:25},(_,index)=>({id:index,timestamp:Date.now()/1000-index,actor_kind:index===0?'guest_session':index===1?'program_renderer':'local_operator',actor_id:'private-account-id',identity_verified:false,action:index===0?'guest.admit':index===1?'program.rendered':'program.take',target:id,outcome:index===0?'succeeded':index===1?'confirmed':'requested',details:{token:'private-token',peer_id:'private-peer-id'}}))};
      const response=(payload,status=200)=>({ok:status<400,status,json:async()=>JSON.parse(JSON.stringify(payload))});
      const push=()=>fixture.receiver?.emit();fixture.push=push;
      window.fetch=async(url,options={})=>{
        const body=options.body?JSON.parse(options.body):null;fixture.requests.push({url,body,method:options.method||'GET'});
        if(!body){if(url.endsWith('/activity'))return fixture.activityFail-->0?response({ok:false,reason:'fixture_activity_unavailable'},503):response({ok:true,events:fixture.activityEvents});return response(url==='/api/production/greenroom'?room:switcher);}
        if(body.expected_revision!==undefined){
          if(fixture.conflictNext){fixture.conflictNext=false;room.revision++;if(body.action==='program_audio')person.program_audio={microphone_muted:true,screen_muted:true};return response({ok:false,reason:'room_revision_conflict'},409);}
          if(body.expected_revision!==room.revision)return response({ok:false,reason:'room_revision_conflict'},409);
          room.revision++;
        }
        if(url==='/api/production/greenroom/invites'){
          const invite={id:'invite-'+(++sequence),label:body.label,status:'ready',expires_at:Date.now()/1000+3600};room.invites.push(invite);push();
          return response({ok:true,invite_id:invite.id,join_url:'http://127.0.0.1:8765/guest#invite='+'b'.repeat(64)});
        }
        if(url==='/guest/join'){
          const hostid='c'.repeat(32),host={...person,id:hostid,name:body.name,state:'waiting',connected:false,media:{microphone:false,camera:false,screen:false,screen_audio:false},sources:{audio:`guest:${hostid}:audio`,camera:`guest:${hostid}:camera`,screen:`guest:${hostid}:screen`}};room.participants.push(host);room.revision++;push();return response(host);
        }
        if(url==='/guest/leave'){const host=room.participants.find(p=>p.id==='c'.repeat(32));if(host)host.state='removed';room.revision++;push();return response({ok:true});}
        if(url.includes('/participants/')){
          const guest=room.participants.find(p=>url.endsWith('/'+p.id));
          if(body.action==='program_audio'){
            if(fixture.holdProgramAudio)await new Promise(resolve=>{fixture.releaseProgramAudio=()=>{fixture.holdProgramAudio=false;fixture.releaseProgramAudio=null;resolve();};});
            guest.program_audio={microphone_muted:body.microphone_muted,screen_muted:body.screen_muted};
          }else {guest.state=body.action==='admit'?'admitted':body.action==='wait'?'waiting':'removed';if(body.action==='wait'||body.action==='remove'){const sources=Object.values(guest.sources);switcher.preview_sources=switcher.preview_sources.filter(source=>!sources.includes(source));switcher.program_sources=switcher.program_sources.filter(source=>!sources.includes(source));}}
          push();return response({ok:true,participant:{id:guest.id,state:guest.state},program_audio:guest.program_audio});
        }
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
    const pictureSize=page.locator('[data-room-picture-size]');
    assert.equal(await pictureSize.getAttribute('aria-pressed'),'false','pictures start compact');
    const beforePictureSize=await page.evaluate(()=>{fixture.pictureVideos=[...document.querySelectorAll('.greenroom-guest video')];return {requests:fixture.requests.length,captures:fixture.captures};});
    await pictureSize.focus();await page.keyboard.press('Enter');assert.equal(await pictureSize.getAttribute('aria-pressed'),'true');
    assert.equal(await pictureSize.textContent(),'Compact pictures');
    assert.equal(await page.evaluate(()=>fixture.pictureVideos.every((video,index)=>video===document.querySelectorAll('.greenroom-guest video')[index])),true,'picture size preserves existing video nodes');
    assert.deepEqual(await page.evaluate(()=>({requests:fixture.requests.length,captures:fixture.captures})),beforePictureSize,'picture size never captures or changes room state');
    await page.keyboard.press('Space');assert.equal(await pictureSize.getAttribute('aria-pressed'),'false');
    assert.equal(await page.evaluate(()=>fixture.captures),0,'mount never captures');
    assert.equal(await page.locator('[data-guest-name] img').count(),0,'guest labels are text');
    assert.equal(await page.locator('[data-source-kind="camera"]').isDisabled(),true);
    const micMute=page.locator('[data-program-audio="microphone"]'),screenMute=page.locator('[data-program-audio="screen"]');
    await page.evaluate(()=>{fixture.room.participants[0].connected=false;fixture.room.participants[0].media.microphone=false;fixture.room.participants[0].media.screen=false;fixture.holdProgramAudio=true;fixture.push();});
    assert.equal(await micMute.isDisabled(),false,'waiting disconnected guests can be pre-muted');
    assert.equal(await screenMute.isDisabled(),false,'screen audio can be pre-muted before capture');
    const beforeMute=await page.evaluate(()=>({revision:fixture.room.revision,program:[...fixture.switcher.program_sources],preview:[...fixture.switcher.preview_sources]}));
    await micMute.click();await page.waitForFunction(()=>Boolean(fixture.releaseProgramAudio));
    assert.equal(await micMute.getAttribute('aria-pressed'),'false','pending mute is not shown as saved');
    assert.equal(await micMute.isDisabled(),true,'duplicate mute clicks are blocked while saving');
    const muteRequest=await page.evaluate(()=>fixture.requests.find(r=>r.body?.action==='program_audio').body);
    assert.equal(muteRequest.expected_revision,beforeMute.revision);assert.match(muteRequest.request_id,/^[a-f0-9]{40}$/);
    assert.deepEqual({microphone_muted:muteRequest.microphone_muted,screen_muted:muteRequest.screen_muted},{microphone_muted:true,screen_muted:false});
    await page.evaluate(()=>fixture.releaseProgramAudio());await page.waitForFunction(()=>document.querySelector('[data-program-audio="microphone"]').getAttribute('aria-pressed')==='true'&&!document.querySelector('[data-program-audio="microphone"]').disabled);
    assert.equal(await page.evaluate(()=>fixture.room.participants[0].state),'waiting','audio settings do not admit a guest');
    await page.evaluate(()=>{fixture.conflictNext=true;});await micMute.click();
    await page.waitForFunction(()=>document.querySelector('.greenroom-notice').textContent.includes('changed in another tab')&&!document.querySelector('[data-program-audio="microphone"]').disabled);
    assert.equal(await micMute.getAttribute('aria-pressed'),'true','conflict preserves authoritative concurrent mute');
    assert.equal(await screenMute.getAttribute('aria-pressed'),'true','conflict refresh includes other operator screen setting');
    await screenMute.click();await page.waitForFunction(()=>document.querySelector('[data-program-audio="screen"]').getAttribute('aria-pressed')==='false'&&!document.querySelector('[data-program-audio="screen"]').disabled);
    assert.equal(await micMute.getAttribute('aria-pressed'),'true','screen audio toggle preserves mic mute');
    const afterMute=await page.evaluate(()=>({program:fixture.switcher.program_sources,preview:fixture.switcher.preview_sources,captures:fixture.captures,takes:fixture.requests.filter(r=>r.url.endsWith('/take')).length,media:fixture.room.participants[0].media}));
    assert.deepEqual(afterMute.program,beforeMute.program);assert.deepEqual(afterMute.preview,beforeMute.preview);assert.equal(afterMute.captures,0);assert.equal(afterMute.takes,0);assert.equal(afterMute.media.microphone,false);assert.equal(afterMute.media.screen,false);
    await page.evaluate(()=>{const guest=fixture.room.participants[0];guest.connected=true;guest.media.microphone=true;guest.media.screen=true;guest.program_audio={microphone_muted:false,screen_muted:false};fixture.push();});
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
    const openInvite=page.locator('[data-open-invite]');
    assert.equal(await openInvite.getAttribute('href'),await page.getByLabel('Private invitation link').inputValue());
    assert.equal(await openInvite.getAttribute('target'),'_blank');
    assert.deepEqual((await openInvite.getAttribute('rel')).split(/\s+/).sort(),['noopener','noreferrer']);
    assert.equal(await openInvite.getAttribute('referrerpolicy'),'no-referrer');
    assert.match(await page.locator('[data-invite-hint]').textContent(),/opens on this computer only/);
    assert.equal(await page.evaluate(()=>fixture.captures),0,'creating an openable invitation never starts capture');
    // Do not follow the invitation: the loopback URL is simulated, and would leave this fixture.
    await page.locator('[data-dismiss-invite]').click();assert.equal(await page.getByLabel('Private invitation link').inputValue(),'');assert.equal(await openInvite.getAttribute('href'),null,'dismissal removes the private destination');
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
      await page.emulateMedia({reducedMotion:'reduce'});
      const compact=await page.locator('.greenroom-guest').first().boundingBox();assert.ok(compact.width<=361,`${theme} ${width} compact picture bound`);
      await pictureSize.click();const large=await page.locator('.greenroom-guest').first().boundingBox();assert.ok(large.width<=721,`${theme} ${width} large picture bound`);assert.ok(large.width>=compact.width,`${theme} ${width} deliberate larger pictures`);
      assert.ok((await pictureSize.boundingBox()).height>=42,'picture size is touch accessible');
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'large pictures fit narrow screens');
      await pictureSize.click();
      await page.screenshot({path:path.join(destination,`greenroom-${theme}-${width}.png`),fullPage:true,animations:'disabled'});results.push({theme,width,...dimensions});
    }
    await page.locator('[data-host-mic]').click();await page.waitForFunction(()=>fixture.stops===1);assert.equal(await page.evaluate(()=>fixture.localStream),null);
    const guest=page.locator('.greenroom-guest[data-participant-id="'+'a'.repeat(32)+'"]');
    await guest.locator('[data-wait]').click();await page.waitForFunction(()=>fixture.room.participants[0].state==='waiting');
    assert.equal(await guest.locator('[data-admit]').isVisible(),true);assert.equal(await guest.locator('[data-wait]').isVisible(),false);
    assert.equal(await page.evaluate(()=>document.activeElement?.hasAttribute('data-admit')),true,'waiting transition focuses its reversible action');
    assert.equal(await page.evaluate(()=>fixture.room.participants[0].connected),true,'waiting keeps the guest session');
    await guest.locator('[data-admit]').click();await page.waitForFunction(()=>fixture.room.participants[0].state==='admitted');
    const removals=await page.evaluate(()=>fixture.requests.filter(r=>r.body?.action==='remove').length);
    await guest.locator('[data-remove]').click();assert.equal(await guest.locator('.greenroom-remove-confirm').isVisible(),true);
    assert.equal(await page.evaluate(()=>fixture.requests.filter(r=>r.body?.action==='remove').length),removals,'opening confirmation does not end access');
    await guest.locator('[data-remove-cancel]').click();assert.equal(await guest.locator('.greenroom-remove-confirm').isVisible(),false);
    await guest.locator('[data-remove]').click();await guest.locator('[data-remove-confirm]').click();await page.waitForFunction(()=>fixture.room.participants[0].state==='removed');
    await page.locator('[data-reinvite="'+'a'.repeat(32)+'"]').click();await page.locator('.greenroom-share').waitFor({state:'visible'});
    assert.equal(await page.evaluate(()=>fixture.room.participants[0].state),'removed','reinvitation does not restore ended access');
    assert.equal(await page.evaluate(()=>fixture.requests.filter(r=>r.url==='/api/production/greenroom/invites').at(-1).body.label),'Guest <img src=x onerror=alert(1)>');
    await page.evaluate(()=>ProducerGreenroomControls.mount(document.getElementById('workspace')).close());
    const checks=['no capture on mount','safe guest labels','admit does not take','offline camera removed','output receipt gating','conflict draft preserved','invitation dismissed','explicit host microphone','host mix-minus exclusion','host track cleanup','activity lazy load','activity retry preserves rows','activity bounded to 20','literal names and private IDs omitted','offline waiting guest pre-mute','authoritative mute state and duplicate-click guard','independent audio flags and CAS metadata','conflicting audio change preserved','audio settings never capture or take Program','safe invitation target and local-only hint','compact picture default and keyboard resizing preserve video nodes','touch-size picture control and bounded sizes across themes/viewports/reduced motion'];
    assert.deepEqual(faults,[]);fs.writeFileSync(path.join(destination,'summary.json'),JSON.stringify({isolated:true,hardware:false,results,checks,faults},null,2));
    console.log(JSON.stringify({passed:true,viewportThemeChecks:results.length,interactionChecks:checks.length,hardware:false}));
  }finally{await browser.close();}
}
main().catch(error=>{console.error(error.message);process.exitCode=1;});
