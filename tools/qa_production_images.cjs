/* Isolated local upload -> Preview -> output decode -> guarded Take, no capture. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {chromium}=require('playwright');
const base=process.env.RAREIQ_QA_ORIGIN||'http://127.0.0.1:8768',destination=process.argv[2];
if(!destination||!path.isAbsolute(destination))throw Error('Absolute evidence directory required');
fs.mkdirSync(destination,{recursive:true});
async function main(){
  const marker=await fetch(base+'/__qa__/guest-fixture').then(r=>r.json());assert.equal(marker.isolated_guest_fixture,true);
  const browser=await chromium.launch({headless:true,channel:'msedge',args:['--mute-audio']}),pages=[],faults=[];
  const results={complete:false,hardware:false,externalBroadcast:false,layouts:[]};
  let sequence=0;
  const api=async(url,body)=>{const response=await fetch(base+url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const result=await response.json();assert.ok(response.ok,`${url}: ${result.reason||response.status}`);return result;};
  async function until(check,label){const end=Date.now()+20000;while(Date.now()<end){if(await check())return;await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Timed out: '+label);}
  async function page(){const p=await browser.newPage({viewport:{width:1920,height:1080}});pages.push(p);p.on('pageerror',error=>{if(error.message!=='read_blocked_in_guest_fixture')faults.push(error.message);});await p.addInitScript(()=>{window.qaCaptures=0;for(const method of ['getUserMedia','getDisplayMedia'])if(navigator.mediaDevices)navigator.mediaDevices[method]=async()=>{qaCaptures++;throw Error('Physical capture forbidden');};});return p;}
  const take=transition=>api('/api/production/switcher/take',{transition,duration_ms:250,request_id:'image_qa_'+Date.now()+'_'+(++sequence),expires_at:Date.now()/1000+30});
  try{
    const producer=await page();await producer.goto(base+'/control?workspace=studio');await producer.locator('#instantSplash').waitFor({state:'hidden'});
    await producer.waitForFunction(()=>document.querySelector('[data-studio-docks="ready"]')?._studioDocks);
    await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-greenroom'));
    await producer.locator('.production-image-library').waitFor();
    const png=await producer.evaluate(()=>{const canvas=document.createElement('canvas');canvas.width=800;canvas.height=450;const ctx=canvas.getContext('2d');ctx.fillStyle='#16334d';ctx.fillRect(0,0,800,450);ctx.strokeStyle='#f7df88';ctx.lineWidth=20;ctx.strokeRect(20,20,760,410);ctx.fillStyle='white';ctx.font='bold 44px sans-serif';ctx.textAlign='center';ctx.fillText('LOCAL IMAGE SOURCE',400,210);ctx.font='26px sans-serif';ctx.fillText('Entire frame · no camera required',400,260);return canvas.toDataURL('image/png').split(',')[1];});
    const initial=await api('/api/production/switcher'),name='Fixture-title-'+Date.now();
    await producer.locator('.production-image-library input[type="file"]').setInputFiles({name:name+'.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});
    const tile=producer.locator('.production-image-item').filter({hasText:name});await tile.waitFor();
    assert.equal((await api('/api/production/switcher')).generation,initial.generation,'import never changes Program');
    await api('/api/production/switcher/preview',{preview_sources:[]});
    await until(async()=>await producer.locator('[data-preview-count]').textContent().then(t=>t.startsWith('0 /')),'Preview cleared');
    await tile.click();
    const source=await until(async()=>{const state=await api('/api/production/switcher');return state.preview_sources.length===1&&state.preview_sources[0].startsWith('image:');},'image Preview').then(async()=> (await api('/api/production/switcher')).preview_sources[0]);
    assert.equal((await api('/api/production/switcher')).generation,initial.generation);
    const blocked=await fetch(base+'/api/production/switcher/take',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:'blocked_image_'+Date.now(),expires_at:Date.now()/1000+30})}).then(async r=>({status:r.status,body:await r.json()}));
    assert.equal(blocked.status,409);assert.equal(blocked.body.reason,'image_output_not_ready');
    const output=await page();await output.goto(base+'/output/studio');
    await until(async()=>{const s=await api('/api/production/switcher');return s.guest_output.ready_groups.some(group=>group.includes(source));},'same output decoded image');
    await until(()=>producer.locator('[data-room-take]').isEnabled(),'guarded Take enabled');await producer.locator('[data-room-transition]').selectOption('fade');await producer.locator('[data-room-take]').click();
    await until(async()=>{const s=await api('/api/production/switcher');return s.program_sources.includes(source)&&s.guest_output.rendered_generation===s.generation;},'image Program receipt');
    await output.screenshot({path:path.join(destination,'image-program.png')});
    for(const transition of ['cut','slide','zoom']){
      await api('/api/production/switcher/preview',{preview_sources:['camera:1',source],layout:'grid'});await take(transition);
      await until(async()=>{const s=await api('/api/production/switcher');return s.guest_output.rendered_generation===s.generation;},'mixed '+transition+' receipt');
      await api('/api/production/switcher/preview',{preview_sources:[source]});await take('cut');
    }
    await producer.reload();await producer.locator('#instantSplash').waitFor({state:'hidden'});await producer.waitForFunction(()=>document.querySelector('[data-studio-docks="ready"]')?._studioDocks);await producer.evaluate(()=>document.querySelector('[data-studio-docks="ready"]')._studioDocks.showTool('production-greenroom'));
    await producer.locator('.production-image-item').filter({hasText:name}).waitFor();results.reloadPreservedLibrary=true;
    for(const theme of ['dark','light'])for(const [width,height] of [[1920,1080],[3840,2160],[960,900]]){
      await producer.setViewportSize({width,height});await producer.evaluate(theme=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.operatorSkin=theme==='light'?'daylight':'ignite';},theme);
      const library=producer.locator('.production-image-library');await library.scrollIntoViewIfNeeded();
      const bounds=await library.evaluate(section=>{const rect=section.getBoundingClientRect();return {width:rect.width,scrollWidth:section.scrollWidth,clientWidth:section.clientWidth};});assert.ok(bounds.width>100);assert.ok(bounds.scrollWidth<=bounds.clientWidth+1,'image library overflow');
      await library.screenshot({path:path.join(destination,`image-library-${theme}-${width}.png`)});results.layouts.push({theme,width,...bounds});
    }
    const corrupt=await fetch(base+'/api/creator/assets',{method:'POST',headers:{'Content-Type':'image/png','X-RareIQ-Filename':'fixture-corrupt.png'},body:Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),Buffer.alloc(32)])}).then(r=>r.json());assert.ok(corrupt.created);
    await api('/api/production/switcher/preview',{preview_sources:['image:'+corrupt.asset.id]});
    const rejected=await fetch(base+'/api/production/switcher/take',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({request_id:'corrupt_image_'+Date.now(),expires_at:Date.now()/1000+30})}).then(async r=>({status:r.status,body:await r.json()}));assert.equal(rejected.status,409);assert.equal(rejected.body.reason,'image_output_not_ready');
    await api('/api/production/switcher/preview',{preview_sources:[]});
    for(const p of pages)assert.equal(await p.evaluate(()=>window.qaCaptures),0);
    assert.deepEqual(faults,[]);results.complete=true;results.importPreviewTake=true;results.transitions=['cut','fade','slide','zoom'];results.corruptImageBlocked=true;
  }finally{results.faults=faults;fs.writeFileSync(path.join(destination,'results.json'),JSON.stringify(results,null,2));await browser.close();}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
