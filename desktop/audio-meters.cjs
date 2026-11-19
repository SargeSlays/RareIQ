'use strict';
// Public diagnostics only. Never forward media buffers, identifiers or URLs.
const plain=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const emptyBus=()=>({peak:0,rms:0,clipCount:0,clipped:false});
const emptyMeters=()=>({fresh:false,live:emptyBus(),vod:emptyBus()});
function cleanBus(v){
  if(!plain(v)||Object.keys(v).some(k=>!['peak','rms','clipCount','clipped'].includes(k))
    ||typeof v.peak!=='number'||!Number.isFinite(v.peak)||v.peak<0||v.peak>1
    ||typeof v.rms!=='number'||!Number.isFinite(v.rms)||v.rms<0||v.rms>1||v.rms>v.peak+1e-6
    ||!Number.isInteger(v.clipCount)||v.clipCount<0||v.clipCount>9600
    ||v.clipped!==undefined&&typeof v.clipped!=='boolean')return null;
  return {peak:v.peak,rms:v.rms,clipCount:v.clipCount,clipped:v.clipped===true||v.clipCount>0};
}
function clean(value,key){
  if(!plain(value)||Object.keys(value).some(k=>![key,'live','vod'].includes(k))||value[key]!==true)return emptyMeters();
  const live=cleanBus(value.live),vod=cleanBus(value.vod);
  return live&&vod?{fresh:true,live,vod}:emptyMeters();
}
module.exports={emptyMeters,cleanMeterHealth:value=>clean(value,'available'),cleanMeterStatus:value=>clean(value,'fresh')};
