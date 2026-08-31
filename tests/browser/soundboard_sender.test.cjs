const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').resolve(__dirname, '../../rareiq/web/static/soundboard_sender.js'), 'utf8');
const settle = async () => { for (let n=0;n<30;n++) await Promise.resolve(); };
function setup() {
  const elements = Object.fromEntries(['soundboardObsOutput','soundboardLocalMonitor','soundboardOutputStatus'].map(id=>[id,{}]));
  const requests = [], timers = new Map(), handlers = {};
  const server = {settings:{enabled:true,local_monitor:false,revision:1},failSave:false};
  let serial = 0;
  const context = vm.createContext({
    document:{getElementById:id=>elements[id]},
    crypto:{randomUUID:()=>String(++serial)}, AbortSignal, Blob,
    navigator:{sendBeacon:()=>true},
    localStorage:{getItem(){throw new Error('Routing must not depend on browser-local preferences');}},
    setInterval:(fn,ms)=>{timers.set(ms,fn);return ms;}, clearInterval:id=>timers.delete(id),
    addEventListener:(name,handler)=>{handlers[name]=handler;},
    fetch:async (url,options={})=>{
      const body = options.body ? JSON.parse(options.body) : null;
      requests.push({url,body});
      if (url.endsWith('/settings')) {
        if (body && server.failSave) return {ok:false};
        if (body) server.settings={...server.settings,...body,revision:server.settings.revision+1};
        const payload={...server.settings};return {ok:true,json:async()=>payload};
      }
      return {ok:true,json:async()=>({receivers:1,settings:{...server.settings}})};
    },
  });
  context.window=context;
  vm.runInContext(source,context);
  return {elements,requests,timers,handlers,server,output:context.RareIQSoundboardOutput};
}
test('fresh browsers inherit saved OBS output and disabled local monitoring', async () => {
  const app=setup(); await settle();
  assert.equal(app.elements.soundboardObsOutput.checked,true);
  assert.equal(app.elements.soundboardLocalMonitor.checked,false);
  assert.equal(app.elements.soundboardObsOutput.disabled,false);
  const audio={paused:false,ended:false,currentTime:2,volume:1};
  app.output.add(audio,{asset_id:'sound'},.6); await settle();
  assert.equal(audio.volume,0);
  assert.equal(app.requests.at(-1).body.voices[0].volume,.6);
  assert.match(app.elements.soundboardOutputStatus.textContent,/Digital output ready/);
});
test('routing changes save centrally and failures restore the displayed state', async () => {
  const app=setup(); await settle();
  app.elements.soundboardLocalMonitor.checked=true;
  await app.elements.soundboardLocalMonitor.onchange(); await settle();
  assert.equal(app.server.settings.local_monitor,true);
  app.server.failSave=true;
  app.elements.soundboardObsOutput.checked=false;
  await app.elements.soundboardObsOutput.onchange(); await settle();
  assert.equal(app.elements.soundboardObsOutput.checked,true);
  assert.equal(app.elements.soundboardObsOutput.disabled,false);
  assert.match(app.elements.soundboardOutputStatus.textContent,/was not saved/);
});
test('another browser can disable output and stale revisions cannot reenable it', async () => {
  const app=setup(); await settle();
  app.output.add({paused:false,ended:false,currentTime:1},{asset_id:'sound'},.5); await settle();
  app.server.settings={enabled:false,local_monitor:false,revision:2};
  await app.timers.get(3000)(); await settle();
  assert.equal(app.elements.soundboardObsOutput.checked,false);
  assert.equal(app.requests.at(-1).body.voices.length,0);
  app.server.settings={enabled:true,local_monitor:true,revision:1};
  await app.timers.get(3000)(); await settle();
  assert.equal(app.elements.soundboardObsOutput.checked,false);
  app.handlers.pagehide();
  assert.equal(app.timers.size,0);
});
