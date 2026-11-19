'use strict';
// Saved routing contains public logical source IDs only: no URLs, devices or people.
const CATEGORIES=Object.freeze({voice:'Guest microphone',screen:'Guest screen audio',video:'Video audio',program:'Other Program audio',soundboard:'Soundboard audio',graphics:'Graphics audio',audience:'Audience alerts'});
const DEFAULT_AUDIO_ROUTING=Object.freeze(Object.fromEntries(Object.keys(CATEGORIES).map(category=>[category+':default',Object.freeze({live:true,vod:category==='voice'})])));
const GUEST=/^guest:[a-f0-9]{32}:(microphone|screen_audio)$/;
const VIDEO=/^video:[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const ASSET=/^(soundboard|graphics|audience):[A-Za-z0-9_-]{1,128}$/;
const plain=value=>value!==null&&typeof value==='object'&&!Array.isArray(value)&&[Object.prototype,null].includes(Object.getPrototypeOf(value));
const fail=()=>{throw Error('invalid_audio_routing');};
function validSourceId(value){return typeof value==='string'&&(GUEST.test(value)||VIDEO.test(value)||ASSET.test(value)||Object.hasOwn(DEFAULT_AUDIO_ROUTING,value));}
function categoryForSource(id){
  if(!validSourceId(id))fail();
  if(id.startsWith('guest:'))return id.endsWith(':microphone')?'voice':'screen';
  return id.slice(0,id.indexOf(':'));
}
function normalizeAudioRouting(value={}){
  if(!plain(value)||Object.keys(value).length>128)fail();
  const entries=[];
  for(const [id,route] of Object.entries(value)){
    if(!validSourceId(id)||!plain(route)||Object.keys(route).length!==2||typeof route.live!=='boolean'||typeof route.vod!=='boolean')fail();
    entries.push([id,{live:route.live,vod:route.vod}]);
  }
  return Object.fromEntries(entries);
}
function routeFor(source,routing={}){
  const id=typeof source==='string'?source:source?.id,category=categoryForSource(id);
  const valid=normalizeAudioRouting(routing),group=['voice','screen','video','program'].includes(category)?'program':category;
  const route=valid[id]??valid[category+':default']??valid[group+':default']??DEFAULT_AUDIO_ROUTING[category+':default'];
  return {...route};
}
function normalizeSourceManifest(value){
  if(!Array.isArray(value)||value.length>64)fail();
  const result=[],seen=new Set();
  for(const item of value){
    if(!plain(item)||!validSourceId(item.id)||Object.keys(item).some(key=>!['id','category','label'].includes(key)))fail();
    const category=categoryForSource(item.id);
    if(item.category!==category||item.label!==undefined&&item.label!==CATEGORIES[category])fail();
    if(!seen.has(item.id)){seen.add(item.id);result.push({id:item.id,category,label:CATEGORIES[category]});}
  }
  return result;
}
module.exports={CATEGORIES,DEFAULT_AUDIO_ROUTING,validSourceId,categoryForSource,normalizeAudioRouting,normalizeSourceManifest,routeFor};
