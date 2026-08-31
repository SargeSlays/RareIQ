/* Pure rotation math shared by browser-source rendering and regression tests. */
(function(root){
  "use strict";
  function pages(config={}){
    const size=config.cards_per_page===3?3:4, result=[];
    for(const [key,label] of [["case_hits","Case hits"],["top_hits","Top hits"]]){
      const cards=Array.isArray(config[key])?config[key].slice(0,32):[];
      for(let start=0;start<cards.length;start+=size)result.push({group:key,label,cards:cards.slice(start,start+size),start,total:cards.length});
    }
    return result;
  }
  function position(count,seconds,elapsed){
    const duration=Math.max(4,Math.min(30,Number(seconds)||8))*1000;
    const time=Number.isFinite(elapsed)?Math.max(0,elapsed):0;
    return {index:count>0?Math.floor(time/duration)%count:0,progress:count>1?(time%duration)/duration:1};
  }
  function artwork(value){
    if(typeof value!=="string"||value.length>500)return "";
    try{
      const path=decodeURIComponent(value);
      if(/[\\%?#]/.test(path)||path.split("/").some(p=>p===".."||p==="."))return "";
      return /^\/api\/(catalog-engine\/image\/[^/]+\/[^/]+|artwork-index\/image\/[^/]+)$/.test(path)?value:"";
    }catch{return "";}
  }
  const api={pages,position,artwork};
  if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.RareIQSetChase=api;
})(typeof window==="undefined"?{}:window);
