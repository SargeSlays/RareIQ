'use strict';
const {createHash}=require('node:crypto');
const {normalizeAudioRouting}=require('./audio-routing.cjs');
const UUID=/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const ID=/^[A-Za-z0-9_-]{1,80}$/;
const MAX_RECEIPTS=64;
const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&[Object.prototype,null].includes(Object.getPrototypeOf(value));
const clone=value=>JSON.parse(JSON.stringify(value));
const freeze=value=>{for(const item of Object.values(value))Object.freeze(item);return Object.freeze(value);};
const fail=code=>Object.assign(new Error(code),{code});
const APPLY_ERRORS=new Set(['audio_routing_busy','audio_routing_timeout','audio_routing_cancelled','audio_routing_conflict']);
const REQUEST_ERRORS=new Set(['invalid_audio_request','invalid_audio_routing','audio_output_changed','audio_revision_conflict',
  'audio_request_conflict','audio_routing_busy','audio_routing_uncertain']);

class LiveAudioSession{
  #apply;#audit;#timeout;#generation=0;#outputId=null;#profileId=null;#revision=0;
  #savedBase=freeze({});#routing=freeze({});#uncertain=false;#historyWarning=false;#pending=null;#inFlight=null;#receipts=new Map();
  constructor({apply,audit=()=>{},timeoutMs=3000}={}){
    if(typeof apply!=='function'||typeof audit!=='function'||!Number.isInteger(timeoutMs)||timeoutMs<1||timeoutMs>30000)throw fail('invalid_audio_session');
    this.#apply=apply;this.#audit=audit;this.#timeout=timeoutMs;
  }
  get savedBase(){return this.#savedBase;}
  init(value){
    let routing;
    try{
      if(!plain(value)||Object.keys(value).sort().join(',')!=='audioRouting,outputId,profileId'
        ||typeof value.outputId!=='string'||!UUID.test(value.outputId)||typeof value.profileId!=='string'||!ID.test(value.profileId))throw Error();
      routing=normalizeAudioRouting(value.audioRouting);
    }catch(_){throw fail('invalid_audio_session');}
    this.close();this.#outputId=value.outputId;this.#profileId=value.profileId;
    this.#savedBase=freeze(clone(routing));this.#routing=freeze(clone(routing));
    return this.status();
  }
  status(){
    return {outputId:this.#outputId,revision:this.#revision,routing:clone(this.#routing),applying:Boolean(this.#inFlight),uncertain:this.#uncertain,historyWarning:this.#historyWarning,
      ...(this.#uncertain&&this.#pending?{pending:{requestId:this.#pending.requestId,expectedRevision:this.#pending.expectedRevision,audioRouting:clone(this.#pending.audioRouting)}}:{})};
  }
  close(){
    this.#generation++;this.#inFlight?.cancel();this.#inFlight=null;
    this.#outputId=this.#profileId=null;this.#revision=0;this.#savedBase=freeze({});this.#routing=freeze({});
    this.#uncertain=this.#historyWarning=false;this.#pending=null;this.#receipts.clear();
    return this.status();
  }
  #current(attempt){return attempt.generation===this.#generation&&attempt.outputId===this.#outputId;}
  #fingerprint(value){
    const ordered=Object.fromEntries(Object.entries(value.audioRouting).sort(([a],[b])=>a.localeCompare(b)));
    return createHash('sha256').update(JSON.stringify({outputId:value.outputId,expectedRevision:value.expectedRevision,audioRouting:ordered})).digest('hex');
  }
  #validate(value){
    if(!plain(value)||Object.keys(value).sort().join(',')!=='audioRouting,expectedRevision,outputId,requestId'
      ||typeof value.outputId!=='string'||!UUID.test(value.outputId)||!Number.isSafeInteger(value.expectedRevision)||value.expectedRevision<0
      ||typeof value.requestId!=='string'||!ID.test(value.requestId))throw fail('invalid_audio_request');
    let audioRouting;try{audioRouting=normalizeAudioRouting(value.audioRouting);}catch(_){throw fail('invalid_audio_routing');}
    return {outputId:value.outputId,expectedRevision:value.expectedRevision,requestId:value.requestId,audioRouting};
  }
  #race(promise,attempt){
    let timer;
    const timeout=new Promise((_,reject)=>{timer=setTimeout(()=>reject(fail('audio_routing_timeout')),this.#timeout);});
    return Promise.race([promise,attempt.cancelled,timeout]).finally(()=>clearTimeout(timer));
  }
  set(raw){
    let value,fingerprint;
    try{
      value=this.#validate(raw);
      if(value.outputId!==this.#outputId)throw fail('audio_output_changed');
      fingerprint=this.#fingerprint(value);
      const previous=this.#receipts.get(value.requestId);
      if(previous&&previous.fingerprint!==fingerprint)throw fail('audio_request_conflict');
      if(this.#inFlight){if(this.#inFlight.receipt===previous)return this.#inFlight.promise;throw fail('audio_routing_busy');}
      if(previous?.applied)return Promise.resolve({...this.status(),requestId:value.requestId,applied:true,replayed:true});
      if(this.#uncertain&&previous!==this.#pending)throw fail('audio_routing_uncertain');
      if(value.expectedRevision!==this.#revision)throw fail('audio_revision_conflict');
      const receipt=previous||{...value,fingerprint,applied:false};
      if(!previous){this.#receipts.set(value.requestId,receipt);while(this.#receipts.size>MAX_RECEIPTS)this.#receipts.delete(this.#receipts.keys().next().value);}
      let cancel;
      const cancelled=new Promise((_,reject)=>{cancel=()=>reject(fail('audio_routing_cancelled'));});
      const attempt={generation:this.#generation,outputId:this.#outputId,profileId:this.#profileId,receipt,cancelled,cancel,promise:null};
      this.#inFlight=attempt;
      attempt.promise=this.#execute(attempt);
      return attempt.promise;
    }catch(error){return Promise.reject(fail(REQUEST_ERRORS.has(error?.code)?error.code:'invalid_audio_request'));}
  }
  async #execute(attempt){
    const receipt=attempt.receipt;
    let acknowledged=false;
    try{
      const operation=Promise.resolve().then(()=>{
        if(!this.#current(attempt))throw fail('audio_routing_cancelled');
        return this.#apply({audioRouting:clone(receipt.audioRouting),requestId:receipt.requestId});
      });
      const ack=await this.#race(operation,attempt);
      if(!this.#current(attempt))throw fail('audio_routing_cancelled');
      if(!plain(ack)||ack.requestId!==receipt.requestId||ack.applied!==true||ack.ok!==undefined&&ack.ok!==true)throw fail('audio_routing_unavailable');
      if(this.#revision>=Number.MAX_SAFE_INTEGER)throw fail('audio_routing_unavailable');
      acknowledged=true;receipt.applied=true;
      this.#routing=freeze(clone(receipt.audioRouting));this.#revision++;
      this.#uncertain=false;this.#pending=null;
      let warning=false;
      try{
        const metadata=Object.freeze({profileId:attempt.profileId,requestId:receipt.requestId,revision:this.#revision});
        await this.#race(Promise.resolve().then(()=>{
          if(!this.#current(attempt))throw fail('audio_routing_cancelled');
          return this.#audit(metadata);
        }),attempt);
      }catch(_){if(!this.#current(attempt))throw fail('audio_routing_cancelled');warning=true;}
      if(!this.#current(attempt))throw fail('audio_routing_cancelled');
      this.#historyWarning=warning;
      if(this.#inFlight===attempt)this.#inFlight=null;
      return {...this.status(),requestId:receipt.requestId,applied:true,replayed:false};
    }catch(error){
      if(!this.#current(attempt))throw fail('audio_routing_cancelled');
      if(!acknowledged){this.#uncertain=true;this.#pending=receipt;}
      const code=APPLY_ERRORS.has(error?.code)?error.code:'audio_routing_unavailable';
      throw fail(code);
    }finally{if(this.#inFlight===attempt)this.#inFlight=null;}
  }
}

module.exports={LiveAudioSession,MAX_RECEIPTS};
