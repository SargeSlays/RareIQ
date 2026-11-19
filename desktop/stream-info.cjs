'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),{randomUUID,createHash}=require('node:crypto');
const ID=/^[A-Za-z0-9_-]{1,80}$/,MAX_BYTES=512*1024;
const DESTINATION_ID=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const validId=v=>typeof v==='string'&&ID.test(v);
const plain=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const clone=v=>JSON.parse(JSON.stringify(v));
const fail=code=>{throw Object.assign(new Error(code),{code});};
function fields(value,override=false){
  const keys=override?['title','description','category','tags']:['title','description'];
  if(!plain(value)||Object.keys(value).length!==keys.length||Object.keys(value).some(k=>!keys.includes(k)))fail('invalid_stream_info');
  const result={};
  for(const key of keys){const text=value[key],max={title:100,description:5000,category:100,tags:300}[key];
    if(typeof text!=='string'||text.length>max||/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(text)||key!=='description'&&/[\r\n\t]/.test(text))fail('invalid_stream_info');
    result[key]=text;
  }return result;
}
function drafts(value){
  if(!plain(value)||Object.keys(value).some(k=>!['shared','overrides'].includes(k))||!plain(value.overrides)||Object.keys(value.overrides).length>50)fail('invalid_stream_info');
  const overrides={};for(const id of Object.keys(value.overrides).sort()){if(!DESTINATION_ID.test(id))fail('invalid_stream_info');overrides[id]=fields(value.overrides[id],true);}
  return {shared:fields(value.shared),overrides};
}
class StreamInfoStore{
  #directory;#file;#fs;#state=null;#queue=Promise.resolve();
  constructor({directory,fileSystem=fs}={}){if(typeof directory!=='string'||!path.isAbsolute(directory))fail('stream_info_storage_unavailable');this.#directory=directory;this.#file=path.join(directory,'stream-info.json');this.#fs=fileSystem;}
  #serial(fn){const result=this.#queue.then(fn);this.#queue=result.catch(()=>{});return result;}
  async #load(){
    if(this.#state)return;let raw;
    try{const stat=await this.#fs.lstat(this.#file);if(!stat.isFile()||stat.isSymbolicLink()||stat.size>MAX_BYTES)fail('stream_info_storage_invalid');raw=await this.#fs.readFile(this.#file,'utf8');}
    catch(error){if(error.code==='ENOENT'){this.#state={version:1,revision:0,shared:{title:'',description:''},overrides:{},receipts:[]};return;}fail(error.code==='stream_info_storage_invalid'?error.code:'stream_info_storage_unavailable');}
    try{const value=JSON.parse(raw);if(!plain(value)||value.version!==1||Object.keys(value).sort().join(',')!=='overrides,receipts,revision,shared,version'||!Number.isSafeInteger(value.revision)||value.revision<0||!Array.isArray(value.receipts)||value.receipts.length>128)throw Error();const normalized=drafts({shared:value.shared,overrides:value.overrides});const seen=new Set();for(const r of value.receipts){if(!plain(r)||Object.keys(r).sort().join(',')!=='fingerprint,requestId,revision'||!validId(r.requestId)||seen.has(r.requestId)||typeof r.fingerprint!=='string'||!/^[a-f0-9]{64}$/.test(r.fingerprint)||!Number.isSafeInteger(r.revision)||r.revision<1||r.revision>value.revision)throw Error();seen.add(r.requestId);}this.#state={...value,...normalized};}
    catch(_){fail('stream_info_storage_invalid');}
  }
  #public(){const {revision,shared,overrides}=this.#state;return clone({revision,shared,overrides});}
  public(){return this.#serial(async()=>{await this.#load();return this.#public();});}
  async #persist(next){
    const encoded=JSON.stringify(next);if(Buffer.byteLength(encoded,'utf8')>MAX_BYTES)fail('invalid_stream_info');
    const temporary=path.join(this.#directory,'.stream-info-'+randomUUID()+'.tmp');let handle;
    try{await this.#fs.mkdir(this.#directory,{recursive:true,mode:0o700});handle=await this.#fs.open(temporary,'wx',0o600);await handle.writeFile(encoded,'utf8');await handle.sync();await handle.close();handle=null;await this.#fs.rename(temporary,this.#file);}
    catch(_){try{await handle?.close();}catch(_){}try{await this.#fs.unlink(temporary);}catch(_){}fail('stream_info_storage_unavailable');}this.#state=next;
  }
  save(payload){
    return this.#serial(async()=>{if(!plain(payload)||Object.keys(payload).sort().join(',')!=='overrides,requestId,revision,shared'||typeof payload.requestId!=='string'||!ID.test(payload.requestId)||!Number.isSafeInteger(payload.revision)||payload.revision<0)fail('invalid_stream_info');const draft=drafts({shared:payload.shared,overrides:payload.overrides});await this.#load();
      const fingerprint=createHash('sha256').update(JSON.stringify({revision:payload.revision,...draft})).digest('hex'),receipt=this.#state.receipts.find(r=>r.requestId===payload.requestId);
      if(receipt){if(receipt.fingerprint!==fingerprint)fail('stream_info_request_conflict');if(receipt.revision!==this.#state.revision)fail('stream_info_revision_conflict');return {...this.#public(),replayed:true};}
      if(payload.revision!==this.#state.revision)fail('stream_info_revision_conflict');if(this.#state.revision>=Number.MAX_SAFE_INTEGER)fail('stream_info_storage_unavailable');const revision=this.#state.revision+1;
      await this.#persist({version:1,revision,...draft,receipts:[...this.#state.receipts,{requestId:payload.requestId,fingerprint,revision}].slice(-128)});return {...this.#public(),replayed:false};
    });
  }
}
function createStreamInfoActions({store,trustedSender,mutate,append}={}){
  const trusted=e=>{try{return trustedSender(e)===true;}catch(_){return false;}};
  return {
    list:async event=>{if(!trusted(event))throw Error('local_operator_required');const result=await store.public();if(!trusted(event))throw Error('local_operator_required');return result;},
    save:async(event,payload)=>{if(!trusted(event))throw Error('local_operator_required');return mutate(event,async()=>{const result=await store.save(payload);let warning=false;if(!result.replayed){try{await append({at:new Date().toISOString(),action:'stream_info.save',actor:'Desktop operator',identityVerified:false,revision:result.revision});}catch(_){warning=true;}}return {...result,...(warning?{activity_history_warning:true}:{})};});}
  };
}
module.exports={StreamInfoStore,createStreamInfoActions};
