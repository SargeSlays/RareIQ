const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync(require.resolve('../../rareiq/web/static/studio_output_audio.js'),'utf8');
function target(){const listeners=new Map();return {listeners,addEventListener:(type,fn)=>listeners.set(type,fn),removeEventListener:(type,fn)=>{if(listeners.get(type)===fn)listeners.delete(type);}};}
test('Studio Output accepts only its Program status and resumes sound synchronously from its button',()=>{
  let clicking=false,resumed=0;const child={ProducerProgramOutput:{resumeAudio(){assert.equal(clicking,true);resumed++;}}};
  const output={dataset:{audioBlocked:'false'}};
  const frame={...target(),contentWindow:child,contentDocument:{querySelector:()=>output}},button={...target(),hidden:true};
  const host={...target(),location:{origin:'http://fixture.invalid'},document:{querySelector:s=>s==='iframe.program'?frame:button}};
  vm.runInNewContext(source,{window:host});
  const report=(source=child,origin=host.location.origin,blocked=true)=>host.listeners.get('message')({source,origin,data:{type:'producer-output-audio',blocked}});
  report({},host.location.origin);report(child,'https://foreign.invalid');report(child,host.location.origin,'true');assert.equal(button.hidden,true);
  report();assert.equal(button.hidden,false);assert.equal(resumed,0);
  clicking=true;button.listeners.get('click')();clicking=false;assert.equal(resumed,1);assert.equal(button.hidden,false,'only successful playback status hides the button');
  report(child,host.location.origin,false);assert.equal(button.hidden,true);
  output.dataset.audioBlocked='true';report();frame.listeners.get('load')();assert.equal(button.hidden,false,'iframe load cannot erase a blocked report received before load');
  output.dataset.audioBlocked='false';frame.listeners.get('load')();assert.equal(button.hidden,true,'load uses current child health');
  host.listeners.get('pagehide')();assert.equal(button.listeners.size,0);assert.equal(frame.listeners.size,0);assert.equal(host.listeners.has('message'),false);
});
