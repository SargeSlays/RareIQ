'use strict';
const {pathToFileURL}=require('node:url');
function studioOrigin(value){const url=new URL(value);if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||!url.port||url.username||url.password||url.pathname!=='/'||url.search||url.hash)throw Error('Untrusted studio address');return url.origin;}
function sameStudio(value,origin){try{return new URL(value).origin===origin;}catch(_){return false;}}
function trustedMain(event,contents,origin){return event.sender===contents&&event.senderFrame===contents.mainFrame&&sameStudio(event.senderFrame.url,origin);}
function allowedExternal(value){try{const url=new URL(value);return url.protocol==='https:'&&!url.username&&!url.password&&!url.port&&['www.twitch.tv','twitch.tv','dashboard.twitch.tv','dev.twitch.tv','studio.youtube.com','youtube.com','www.youtube.com','kick.com','www.kick.com','dashboard.kick.com'].includes(url.hostname);}catch(_){return false;}}
function applySessionPolicy(session,origin){
  session.setPermissionCheckHandler((contents,permission,requestingOrigin,details)=>{
    if(!sameStudio(requestingOrigin,origin)||!sameStudio(contents?.getURL?.(),origin))return false;
    return ['media','display-capture'].includes(permission)&&details?.isMainFrame===true;
  });
  session.setPermissionRequestHandler((_contents,_permission,callback)=>callback(false));
  session.setDisplayMediaRequestHandler((_request,callback)=>callback({}));
  session.on('will-download',event=>event.preventDefault());
}
module.exports={studioOrigin,sameStudio,trustedMain,allowedExternal,applySessionPolicy,fileUrl:pathToFileURL};
