/* Bounded raw-input speech capture. Output is always silence; no audio persistence. */
class StudioVoiceCapture extends AudioWorkletProcessor {
  constructor() {
    super();this.enabled=false;this.ratio=sampleRate/16000;this.weight=0;this.sum=0;
    this.frame=new Float32Array(160);this.frameIndex=0;this.pre=[];this.frames=[];
    this.voiced=0;this.quiet=0;this.active=false;this.waitQuiet=false;this.lastVoiceTime=0;this.startedVoiceTime=0;this.heartbeat=0;
    this.port.onmessage=event=>{if(event.data?.type==='enabled'){this.enabled=event.data.value===true;this.clear();}};
  }
  clear(){this.pre=[];this.frames=[];this.voiced=0;this.quiet=0;this.active=false;this.frameIndex=0;this.weight=0;this.sum=0;}
  frameReady(time) {
    const frame=this.frame.slice();let energy=0;for(const sample of frame)energy+=sample*sample;
    const speech=Math.sqrt(energy/frame.length)>=0.015;
    this.quiet=speech?0:this.quiet+1;
    if(this.waitQuiet){if(this.quiet>=50){this.waitQuiet=false;this.quiet=0;}return;}
    if(!this.active){
      this.pre.push(frame);if(this.pre.length>25)this.pre.shift();
      this.voiced=speech?this.voiced+1:0;
      if(this.voiced<3)return;
      this.active=true;this.startedVoiceTime=Math.max(0,time-.03);this.frames=this.pre;this.pre=[];
    }else this.frames.push(frame);
    if(speech)this.lastVoiceTime=time;
    if(this.quiet<50&&this.frames.length<600)return;
    const length=Math.min(96000,this.frames.length*160),buffer=new ArrayBuffer(44+length*2),view=new DataView(buffer);
    const ascii=(at,text)=>{for(let i=0;i<text.length;i++)view.setUint8(at+i,text.charCodeAt(i));};
    ascii(0,'RIFF');view.setUint32(4,36+length*2,true);ascii(8,'WAVE');ascii(12,'fmt ');
    view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);view.setUint32(24,16000,true);view.setUint32(28,32000,true);view.setUint16(32,2,true);view.setUint16(34,16,true);ascii(36,'data');view.setUint32(40,length*2,true);
    let index=0;for(const block of this.frames)for(const sample of block){if(index>=length)break;const value=Math.max(-1,Math.min(1,sample));view.setInt16(44+index++*2,Math.round(value<0?value*32768:value*32767),true);}
    this.enabled=false;this.waitQuiet=this.quiet<50;
    this.port.postMessage({type:'utterance',wav:buffer,startedContextTime:this.startedVoiceTime,endedContextTime:this.lastVoiceTime},[buffer]);this.clear();
  }
  process(inputs,outputs) {
    for(const output of outputs)for(const channel of output)channel.fill(0);
    this.heartbeat+=inputs[0]?.[0]?.length||128;
    if(this.heartbeat>=sampleRate){this.heartbeat=0;this.port.postMessage({type:'heartbeat'});}
    const channels=inputs[0];if(!this.enabled||!channels?.length)return true;
    for(let index=0;index<channels[0].length;index++){
      let value=0;for(const channel of channels)value+=channel[index]||0;value/=channels.length;
      let remaining=1;
      while(remaining>0){const take=Math.min(remaining,this.ratio-this.weight);this.sum+=value*take;this.weight+=take;remaining-=take;
        if(this.weight+1e-8>=this.ratio){this.frame[this.frameIndex++]=this.sum/this.ratio;this.sum=0;this.weight=0;
          if(this.frameIndex===160){this.frameIndex=0;this.frameReady(currentTime+(index+1)/sampleRate);if(!this.enabled)return true;}
        }
      }
    }
    return true;
  }
}
registerProcessor('studio-voice-capture',StudioVoiceCapture);
