// Served Edge regression: synthetic clean-camera frames; never connects to hardware.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const origin=new URL(process.env.RAREIQ_QA_ORIGIN||'http://127.0.0.1:9040').origin;
const output=path.resolve(__dirname,'../.tmp/refinish/program-output');

(async()=>{
  await fs.mkdir(output,{recursive:true});
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  const connections=[],unexpected=[],previewRequests=[],errors=[];
  let writes=0,mediaStarts=0,sequence=0;
  try{
    const page=await browser.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:1});
    page.on('pageerror',error=>errors.push(error.message));
    const fixtures=await page.evaluate(()=>[1,2,3,4].map(slot=>{
      const canvas=document.createElement('canvas');canvas.width=640;canvas.height=360;
      const ctx=canvas.getContext('2d');
      const colors=['#315ca8','#22795c','#965931','#7a3e91'];
      ctx.fillStyle=colors[slot-1];ctx.fillRect(0,0,640,360);
      ctx.strokeStyle='#fff';ctx.lineWidth=8;ctx.strokeRect(4,4,632,352);
      ctx.fillStyle='#fff';ctx.font='bold 30px sans-serif';ctx.textAlign='center';
      ctx.fillText(`SYNTHETIC CAMERA ${slot}`,320,170);
      ctx.font='20px sans-serif';ctx.fillText('640 × 360 · entire frame visible',320,210);
      return canvas.toDataURL('image/jpeg',.9).split(',')[1];
    }));
    const frames=fixtures.map((base64,index)=>Buffer.concat([Buffer.from([index+1]),Buffer.from(base64,'base64')]));
    let switcher={generation:1,program_slot:1,transition:'cut',duration_ms:0};
    await page.addInitScript(()=>{
      window.qaMediaStarts=0;
      if(navigator.mediaDevices)navigator.mediaDevices.getUserMedia=async()=>{
        window.qaMediaStarts++;throw Error('Media blocked by Program QA');
      };
      HTMLMediaElement.prototype.play=function(){window.qaMediaStarts++;return Promise.reject(Error('Playback blocked by Program QA'));};
    });
    await page.route('**/*',route=>{
      const request=route.request(),url=new URL(request.url());
      if(/\/api\/camera-slots\/.*\/(stream|preview)/.test(url.pathname))previewRequests.push(url.pathname);
      if(!['GET','HEAD'].includes(request.method())){writes++;return route.abort();}
      if(url.origin!==origin){unexpected.push(url.origin+url.pathname);return route.abort();}
      if(url.pathname==='/api/production/switcher')return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(switcher)});
      if(url.pathname==='/program'||/^\/output\/camera\/[1-4]$/.test(url.pathname)||url.pathname.startsWith('/static/'))return route.continue();
      unexpected.push(url.pathname);return route.abort();
    });
    await page.routeWebSocket('**',socket=>{
      const match=new URL(socket.url()).pathname.match(/^\/ws\/output\/camera\/([1-4])$/);
      if(!match){unexpected.push(socket.url());socket.close();return;}
      const slot=Number(match[1]),connection={slot,id:++sequence,socket,closed:false,timer:null};
      connections.push(connection);
      const cleanup=()=>{connection.closed=true;clearInterval(connection.timer);};
      connection.close=()=>{cleanup();socket.close({code:1000,reason:'Synthetic disconnect'});};
      socket.onClose(cleanup);
      const send=()=>{
        if(connection.closed)return;
        socket.send(JSON.stringify({server_session:'program-qa-fixture',active_slot:slot,slots:[1,2,3,4].map(id=>({slot_id:id,source_id:`fixture-${id}`,connected:true,frame_age_seconds:0,display_name:`Synthetic camera ${id}`}))}));
        socket.send(frames[slot-1]);
      };
      connection.timer=setInterval(send,150);send();
    });
    const waitCamera=async slot=>{
      await page.waitForFunction(expected=>{
        const frame=document.querySelector('.program-frame:not(.out)');
        const image=frame?.contentDocument?.querySelector('img.live');
        return frame?.getAttribute('src')===`/output/camera/${expected}`&&image?.complete&&image.naturalWidth===640;
      },slot,{timeout:7000});
    };
    await page.goto(origin+'/program?program-qa='+Date.now());await waitCamera(1);
    const viewports=[[1920,1080],[3840,2160],[1366,768],[720,900],[1080,1920]];
    for(const [width,height] of viewports){
      await page.setViewportSize({width,height});
      const geometry=await page.evaluate(()=>{
        const bug=document.querySelector('.program-bug'),box=bug.getBoundingClientRect();
        const frame=document.querySelector('.program-frame:not(.out)'),rect=frame.getBoundingClientRect();
        const image=frame.contentDocument.querySelector('img.live');
        return {bug:{x:box.x,y:box.y,width:box.width,height:box.height,fit:getComputedStyle(bug).objectFit,loaded:bug.complete&&bug.naturalWidth>0},
          frame:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},
          child:{width:image.naturalWidth,height:image.naturalHeight,fit:frame.contentWindow.getComputedStyle(image).objectFit,visible:frame.contentWindow.getComputedStyle(image).visibility}};
      });
      assert.deepEqual(geometry.bug,{x:width-54,y:height-52,width:34,height:34,fit:'contain',loaded:true});
      assert.deepEqual(geometry.frame,{x:0,y:0,width,height});
      assert.deepEqual(geometry.child,{width:640,height:360,fit:'contain',visible:'visible'});
      await page.screenshot({path:path.join(output,`program-${width}x${height}.png`)});
    }
    await page.setViewportSize({width:1920,height:1080});
    switcher={generation:2,program_slot:2,transition:'fade',duration_ms:1200};await waitCamera(2);
    assert.equal(await page.locator('#program').getAttribute('data-transition'),'fade');
    assert.equal(await page.locator('.program-frame[src]').count(),2);
    // Both transitions are superseded before their delayed release can clear a reused view.
    switcher={generation:3,program_slot:3,transition:'zoom',duration_ms:1200};await waitCamera(3);
    switcher={generation:4,program_slot:4,transition:'slide',duration_ms:400};await waitCamera(4);
    await page.waitForTimeout(1500);await waitCamera(4);
    assert.equal(await page.locator('#program').getAttribute('data-transition'),'slide');
    assert.equal(await page.locator('.program-frame[src]').count(),1);
    assert.equal(await page.locator('.program-frame.out').getAttribute('src'),null);
    assert.deepEqual(connections.filter(connection=>!connection.closed).map(connection=>connection.slot),[4]);
    await page.screenshot({path:path.join(output,'program-latest-selection.png')});
    const current=connections.findLast(connection=>connection.slot===4&&!connection.closed);
    current.close();
    await page.waitForFunction(()=>{
      const doc=document.querySelector('.program-frame:not(.out)').contentDocument;
      return !doc.querySelector('img').hasAttribute('src')&&!doc.querySelector('img.live')&&doc.querySelector('figcaption').textContent.includes('disconnected');
    },null,{timeout:800});
    await waitCamera(4);
    assert.ok(connections.some(connection=>connection.slot===4&&connection.id>current.id&&!connection.closed));
    assert.deepEqual(previewRequests,[]);assert.deepEqual(unexpected,[]);assert.deepEqual(errors,[]);assert.equal(writes,0);
    for(const frame of page.frames())mediaStarts+=await frame.evaluate(()=>window.qaMediaStarts||0);
    assert.equal(mediaStarts,0);
    // Navigating away releases child subscriptions without forwarding any server connection.
    await page.goto('about:blank');
    await page.waitForTimeout(150);
    assert.equal(connections.filter(connection=>!connection.closed).length,0);
    console.log(JSON.stringify({passed:true,servedEdgeCases:9,viewportCases:viewports.length,transition:true,rapidLatestWins:true,outgoingRetired:true,disconnectReconnect:true,pagehideReleased:true,syntheticConnections:connections.length,realWebSocketConnections:0,apiWritesForwarded:0,previewRequests:previewRequests.length,mediaStarts,screenshots:output}));
  }finally{
    for(const connection of connections)clearInterval(connection.timer);
    await browser.close();
  }
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
