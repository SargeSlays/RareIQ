/* Native Web Audio timbre effects and original synthesized cues. No capture or network. */
(function(host){
  'use strict';
  const presets=Object.freeze(['natural','deep','radio','robot','megaphone']);
  const cues=Object.freeze([{id:'chime',label:'Chime'},{id:'success',label:'Success tones'},{id:'buzzer',label:'Buzzer'},{id:'drumroll',label:'Drum roll'}].map(Object.freeze));
  function distortion(amount=35){
    const curve=new Float32Array(44100),k=Number(amount),deg=Math.PI/180;
    for(let i=0;i<curve.length;i++){const x=i*2/curve.length-1;curve[i]=(3+k)*x*20*deg/(Math.PI+k*Math.abs(x));}return curve;
  }
  // Deep shapes tone; it does not shift pitch.
  function connectPreset(context,input,output,preset='natural'){
    if(preset==='clean')preset='natural';
    if(!presets.includes(preset))throw Error('invalid_voice_preset');
    const nodes=[],oscillators=[];let tail=input,first=null,closed=false;
    const add=node=>{if(!first)first=node;tail.connect(node);tail=node;nodes.push(node);return node;};
    if(preset==='deep'){
      const low=add(context.createBiquadFilter());low.type='lowpass';low.frequency.value=1450;low.Q.value=.7;
      const bass=add(context.createBiquadFilter());bass.type='lowshelf';bass.frequency.value=210;bass.gain.value=8;
      const compressor=add(context.createDynamicsCompressor());compressor.threshold.value=-24;compressor.ratio.value=4;
    }else if(preset==='robot'){
      const mod=add(context.createGain());mod.gain.value=.58;
      const oscillator=context.createOscillator(),depth=context.createGain();oscillator.frequency.value=42;depth.gain.value=.42;
      oscillator.connect(depth);depth.connect(mod.gain);oscillator.start();oscillators.push(oscillator);nodes.push(depth);
      const band=add(context.createBiquadFilter());band.type='bandpass';band.frequency.value=1200;band.Q.value=.8;
    }else if(preset==='radio'){
      const high=add(context.createBiquadFilter());high.type='highpass';high.frequency.value=420;
      const low=add(context.createBiquadFilter());low.type='lowpass';low.frequency.value=3200;
      const compressor=add(context.createDynamicsCompressor());compressor.threshold.value=-30;compressor.ratio.value=8;
    }else if(preset==='megaphone'){
      const band=add(context.createBiquadFilter());band.type='bandpass';band.frequency.value=1650;band.Q.value=.75;
      const shaper=add(context.createWaveShaper());shaper.curve=distortion(55);shaper.oversample='2x';
      const compressor=add(context.createDynamicsCompressor());compressor.threshold.value=-28;compressor.ratio.value=10;
    }
    tail.connect(output);
    return {nodes,oscillators,close(){if(closed)return;closed=true;try{input.disconnect(first||output);}catch(_){}
      for(const oscillator of oscillators)try{oscillator.stop();}catch(_){}
      for(const node of [...nodes,...oscillators])try{node.disconnect();}catch(_){}
    }};
  }
  function cueBuffer(context,id){
    if(!cues.some(cue=>cue.id===id))throw Error('unknown_sound');
    const duration={chime:.9,success:1.1,buzzer:.55,drumroll:1.3}[id],rate=context.sampleRate;
    if(!Number.isFinite(rate)||rate<8000||rate>192000)throw Error('audio_unavailable');
    const buffer=context.createBuffer(1,Math.ceil(rate*duration),rate),samples=buffer.getChannelData(0);
    let seed=1729;
    for(let i=0;i<samples.length;i++){
      const t=i/rate,fade=Math.min(1,t/.008,(duration-t)/.04);let value=0;
      if(id==='chime')value=(Math.sin(2*Math.PI*880*t)+.45*Math.sin(2*Math.PI*1320*t))*Math.exp(-5*t)*.25;
      else if(id==='success'){
        const step=Math.min(2,Math.floor(t/.22)),local=t-step*.22;
        value=Math.sin(2*Math.PI*[523.25,659.25,783.99][step]*t)*Math.min(1,local/.008)*Math.exp(-5*local)*.3;
      }else if(id==='buzzer')value=(Math.sin(2*Math.PI*140*t)+.3*Math.sin(2*Math.PI*420*t))*.23;
      else{seed=(Math.imul(seed,1664525)+1013904223)>>>0;const hit=t%.085;value=((seed/4294967296)*2-1)*Math.exp(-hit*70)*(.13+.2*t/duration);}
      samples[i]=value*Math.max(0,fade);
    }
    return buffer;
  }
  const exported={presets,cues,distortion,connectPreset,cueBuffer};
  if(typeof module==='object'&&module.exports)module.exports=exported;
  else host.ProducerGuestAudioDSP=exported;
})(typeof window==='undefined'?globalThis:window);
