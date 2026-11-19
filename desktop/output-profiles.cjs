'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),{randomUUID,createHash}=require('node:crypto');
const {normalizeAudioRouting,DEFAULT_AUDIO_ROUTING}=require('./audio-routing.cjs');
const MAX_PROFILES=20,MAX_RECEIPTS=256,MAX_BYTES=1024*1024,ID=/^[A-Za-z0-9_-]{1,80}$/;
const validId=value=>typeof value==='string'&&ID.test(value);
const FORMATS=new Set(['hd','fullhd','portrait']),CODECS=new Set(['auto','h264_nvenc','libx264']);
const SETTINGS=['name','format','fps','videoBitrateKbps','codec','keyframeSeconds','audioBitrateKbps','twitchVod','audioRouting'];
const clone=value=>JSON.parse(JSON.stringify(value)),plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
class OutputProfileError extends Error{constructor(code){super(code);this.code=code;this.name='OutputProfileError';}}
const fail=code=>{throw new OutputProfileError(code);};
function normalizeProfile(value){
  if(!plain(value)||Object.keys(value).some(key=>!SETTINGS.includes(key)))fail('invalid_output_profile_fields');
  const option=(key,fallback)=>value[key]===undefined?fallback:value[key];
  const normalized={name:value.name,format:option('format','hd'),fps:option('fps',30),videoBitrateKbps:option('videoBitrateKbps',4000),codec:option('codec','auto'),keyframeSeconds:option('keyframeSeconds',2),audioBitrateKbps:option('audioBitrateKbps',192),twitchVod:option('twitchVod',false)};
  if(typeof normalized.name!=='string'||!normalized.name.trim()||normalized.name.trim().length>60||/[\x00-\x1f\x7f]/.test(normalized.name))fail('invalid_output_profile_name');normalized.name=normalized.name.trim();
  if(!FORMATS.has(normalized.format)||![30,60].includes(normalized.fps)||!CODECS.has(normalized.codec)||typeof normalized.twitchVod!=='boolean')fail('invalid_output_profile_settings');
  for(const [key,min,max]of [['videoBitrateKbps',250,40000],['keyframeSeconds',1,10],['audioBitrateKbps',64,320]])if(!Number.isInteger(normalized[key])||normalized[key]<min||normalized[key]>max)fail('invalid_output_profile_settings');
  try{normalized.audioRouting=normalizeAudioRouting(option('audioRouting',DEFAULT_AUDIO_ROUTING));}catch(_){fail('invalid_output_profile_audio_routing');}
  return normalized;
}
function defaultProfiles(){return [['hd-balanced','HD balanced','hd',4000],['fullhd-quality','Full HD quality','fullhd',6000],['portrait-hd','Portrait HD','portrait',4000]].map(([id,name,format,videoBitrateKbps])=>({id,...normalizeProfile({name,format,videoBitrateKbps}),updatedAt:0}));}
class OutputProfileStore{
  #directory;#file;#fs;#state=null;#queue=Promise.resolve();
  constructor({directory,fileSystem=fs}={}){if(typeof directory!=='string'||!path.isAbsolute(directory))fail('output_profile_directory_required');this.#directory=directory;this.#file=path.join(directory,'output-profiles.json');this.#fs=fileSystem;}
  #serial(action){const result=this.#queue.then(action);this.#queue=result.catch(()=>{});return result;}
  async #load(){
    if(this.#state)return;let raw;
    try{const stat=await(this.#fs.lstat||this.#fs.stat).call(this.#fs,this.#file);if(!stat.isFile()||stat.isSymbolicLink?.()||stat.size>MAX_BYTES)fail('output_profile_storage_invalid');raw=await this.#fs.readFile(this.#file,'utf8');}
    catch(error){if(error.code==='ENOENT'){this.#state={version:1,profiles:defaultProfiles(),selectedProfileId:'hd-balanced',receipts:[]};return;}fail(error.code==='output_profile_storage_invalid'?error.code:'output_profile_storage_unavailable');}
    try{
      const value=JSON.parse(raw);if(!plain(value)||Object.keys(value).some(key=>!['version','profiles','selectedProfileId','receipts'].includes(key))||value.version!==1||!Array.isArray(value.profiles)||!value.profiles.length||value.profiles.length>MAX_PROFILES||!Array.isArray(value.receipts)||value.receipts.length>MAX_RECEIPTS)throw Error();
      const seen=new Set();for(const item of value.profiles){if(!plain(item)||!validId(item.id)||seen.has(item.id)||!Number.isSafeInteger(item.updatedAt)||item.updatedAt<0)throw Error();seen.add(item.id);const {id,updatedAt,...settings}=item;if(JSON.stringify(normalizeProfile(settings))!==JSON.stringify(settings))throw Error();}
      if(!seen.has(value.selectedProfileId))throw Error();const requests=new Set();for(const receipt of value.receipts){if(!plain(receipt)||Object.keys(receipt).sort().join(',')!=='fingerprint,id,requestId'||!validId(receipt.requestId)||requests.has(receipt.requestId)||!validId(receipt.id)||typeof receipt.fingerprint!=='string'||!/^[a-f0-9]{64}$/.test(receipt.fingerprint))throw Error();requests.add(receipt.requestId);}
      this.#state=value;
    }catch(_){fail('output_profile_storage_invalid');}
  }
  #public(){return clone({profiles:this.#state.profiles,selectedProfileId:this.#state.selectedProfileId});}
  public(){return this.#serial(async()=>{await this.#load();return this.#public();});}
  getProfile(id){return this.#serial(async()=>{await this.#load();const profile=this.#state.profiles.find(item=>item.id===(id??this.#state.selectedProfileId));if(!profile)fail('output_profile_not_found');return clone(profile);});}
  async #persist(next){
    const temporary=path.join(this.#directory,'.output-profiles-'+randomUUID()+'.tmp');let handle;
    try{await this.#fs.mkdir(this.#directory,{recursive:true,mode:0o700});handle=await this.#fs.open(temporary,'wx',0o600);await handle.writeFile(JSON.stringify(next),'utf8');await handle.sync();await handle.close();handle=null;await this.#fs.rename(temporary,this.#file);}
    catch(_){try{await handle?.close();}catch(_){}try{await this.#fs.unlink(temporary);}catch(_){}fail('output_profile_storage_unavailable');}this.#state=next;
  }
  save(payload){
    let input;try{if(!plain(payload)||Object.keys(payload).some(key=>!['id','requestId',...SETTINGS].includes(key))||!validId(payload.requestId)||payload.id!==undefined&&!validId(payload.id))fail('invalid_output_profile_fields');const {id,requestId,...settings}=payload;input={id:id||null,requestId,...normalizeProfile(settings)};}catch(error){return Promise.reject(error);}
    return this.#serial(async()=>{await this.#load();const {requestId,...fingerprintInput}=input,fingerprint=createHash('sha256').update(JSON.stringify(fingerprintInput)).digest('hex'),receipt=this.#state.receipts.find(item=>item.requestId===requestId);
      if(receipt){if(receipt.fingerprint!==fingerprint)fail('output_profile_request_conflict');if(!this.#state.profiles.some(item=>item.id===receipt.id))fail('output_profile_request_retired');return {...this.#public(),savedProfileId:receipt.id,replayed:true};}
      const previous=input.id?this.#state.profiles.find(item=>item.id===input.id):null;if(input.id&&!previous)fail('output_profile_not_found');if(!previous&&this.#state.profiles.length>=MAX_PROFILES)fail('output_profile_library_full');
      const {id:ignored,requestId:ignoredRequest,...settings}=input,id=previous?.id||randomUUID(),profile={id,...settings,updatedAt:Date.now()},next=clone(this.#state);next.profiles=previous?next.profiles.map(item=>item.id===id?profile:item):[...next.profiles,profile];next.selectedProfileId=id;next.receipts=[...next.receipts,{requestId,fingerprint,id}].slice(-MAX_RECEIPTS);await this.#persist(next);return {...this.#public(),savedProfileId:id,replayed:false};
    });
  }
  select(id){return this.#serial(async()=>{await this.#load();if(typeof id!=='string'||!this.#state.profiles.some(item=>item.id===id))fail('output_profile_not_found');if(id!==this.#state.selectedProfileId){const next=clone(this.#state);next.selectedProfileId=id;await this.#persist(next);}return this.#public();});}
  remove(id){return this.#serial(async()=>{await this.#load();if(typeof id!=='string'||!this.#state.profiles.some(item=>item.id===id))fail('output_profile_not_found');if(this.#state.profiles.length===1)fail('output_profile_required');const next=clone(this.#state);next.profiles=next.profiles.filter(item=>item.id!==id);if(next.selectedProfileId===id)next.selectedProfileId=next.profiles[0].id;await this.#persist(next);return this.#public();});}
}
module.exports={OutputProfileStore,OutputProfileError,normalizeProfile,defaultProfiles,MAX_PROFILES};
