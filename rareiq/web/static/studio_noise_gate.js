/* Optional processing branch: never acquires or closes a physical input. */
(function(host){
  const modules=new WeakMap();
  function create(context,input,output,status){
    let node=null,loading=null,closed=false,settings={enabled:false,thresholdDb:-45};
    input.connect(output);
    function bypass(){if(node){try{input.disconnect(node);node.disconnect();node.port.close();}catch(_){}node=null;input.connect(output);}}
    async function configure(next){
      settings={enabled:next.enabled===true,thresholdDb:Math.max(-70,Math.min(-10,Number.isFinite(next.thresholdDb)?next.thresholdDb:-45))};
      if(closed)return;
      if(node){node.port.postMessage({type:'configure',...settings});if(!settings.enabled)status('Off');return;}
      if(!settings.enabled){status('Off');return;}
      status('Preparing…');
      if(loading)return loading;
      loading=Promise.resolve().then(async()=>{
        try{
          if(!context.audioWorklet||!host.AudioWorkletNode)throw Error('Unavailable');
          if(!modules.has(context))modules.set(context,context.audioWorklet.addModule('/static/studio_noise_gate.worklet.js?v=20260908-1').catch(error=>{modules.delete(context);throw error;}));
          await modules.get(context);
          if(closed||!settings.enabled)return;
          node=new host.AudioWorkletNode(context,'studio-noise-gate');
          node.port.onmessage=event=>{if(!closed&&settings.enabled&&['open','closed'].includes(event.data?.state))status(event.data.state==='open'?'Open · voice passing':'Closed · quiet input muted');};
          node.onprocessorerror=()=>{if(!closed){bypass();status('Unavailable · audio unfiltered');}};
          node.port.postMessage({type:'configure',...settings});
          input.disconnect(output);input.connect(node);node.connect(output);
        }catch(_){if(!closed){bypass();status('Unavailable · audio unfiltered');}}
        finally{loading=null;}
      });return loading;
    }
    return {configure,close(){closed=true;if(node){node.port.onmessage=null;node.port.close();node.disconnect();node=null;}}};
  }
  host.StudioNoiseGate={create};
})(typeof window==='undefined'?globalThis:window);
