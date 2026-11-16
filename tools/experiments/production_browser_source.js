/* Experimental embed adapter. Not loaded by production pages or wired to Take.
 * URL checks are initial-address policy, not DNS/redirect/network isolation.
 * A frame load cannot prove visible content; review is only a past visual check.
 */
(function(host){
  'use strict';
  const PRIVATE_SUFFIXES=['localhost','local','internal','lan','home','test','invalid','onion','arpa'];
  function validatedUrl(value,studioOrigin){
    if(typeof value!=='string'||!value||value.length>2048||/[\s\u0000-\u001f\u007f\\]/.test(value))throw Error('invalid_browser_url');
    let url;try{url=new URL(value);}catch(_){throw Error('invalid_browser_url');}
    if(url.protocol!=='https:'||url.username||url.password||url.port)throw Error('browser_url_requires_public_https');
    const name=url.hostname.toLowerCase(),labels=name.split('.');
    if(name.length>253||labels.length<2||labels.some(label=>!label||label.length>63||!/^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(label))||!/[a-z]/.test(labels.at(-1))||PRIVATE_SUFFIXES.some(suffix=>name===suffix||name.endsWith('.'+suffix)))throw Error('browser_url_requires_public_hostname');
    let studio;try{studio=new URL(studioOrigin||host.location?.origin).hostname.toLowerCase();}catch(_){throw Error('browser_studio_origin_required');}
    if(name===studio)throw Error('browser_studio_url_forbidden');
    return url.href;
  }
  function mount({container,url,studioOrigin,document=container?.ownerDocument||host.document,onState=()=>{},makeToken=()=>host.crypto.randomUUID()}={}){
    const address=validatedUrl(url,studioOrigin);
    if(!container||!document)throw Error('browser_source_container_required');
    const frame=document.createElement('iframe');
    frame.title='Browser source preview';
    frame.setAttribute('sandbox','allow-scripts');
    frame.setAttribute('allow',"camera 'none'; microphone 'none'; geolocation 'none'; autoplay 'none'; display-capture 'none'; fullscreen 'none'; payment 'none'");
    frame.setAttribute('referrerpolicy','no-referrer');
    frame.setAttribute('inert','');frame.tabIndex=-1;frame.style.pointerEvents='none';
    let phase='loading',token=null,closed=false;
    const snapshot=()=>Object.freeze({phase,reviewToken:token});
    function change(next,reviewable=false){phase=next;token=reviewable?makeToken():null;onState(snapshot());}
    function loaded(){if(!closed)change('loaded_unverified',true);}
    function failed(){if(!closed)change('unavailable');}
    frame.addEventListener('load',loaded);frame.addEventListener('error',failed);
    // Restrictions are installed before navigation and insertion.
    frame.src=address;container.append(frame);onState(snapshot());
    return {
      frame,snapshot,
      review(value){if(closed||phase!=='loaded_unverified'||!value||value!==token)return false;change('visual_reviewed');return true;},
      reload(){if(closed)return false;change('loading');frame.src=address;return true;},
      destroy(){if(closed)return;closed=true;frame.removeEventListener('load',loaded);frame.removeEventListener('error',failed);frame.remove();frame.removeAttribute('src');change('closed');},
    };
  }
  const exported={validatedUrl,mount};if(typeof module==='object'&&module.exports)module.exports=exported;else host.ProducerBrowserSource=exported;
})(typeof window==='undefined'?globalThis:window);
