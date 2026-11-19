'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('producerDesktop',Object.freeze({
  broadcastStatus:()=>ipcRenderer.invoke('producer:broadcast:status'),
  info:()=>ipcRenderer.invoke('producer:info'),
  openBroadcastSettings:()=>ipcRenderer.invoke('producer:settings'),
  authorizeAccount:value=>{
    if(!value||Object.prototype.toString.call(value)!=='[object Object]'||Object.keys(value).length!==2
      ||!Object.hasOwn(value,'platform')||!Object.hasOwn(value,'flowId')||value.platform!=='youtube'
      ||typeof value.flowId!=='string'||!/^[a-f0-9]{32}$/.test(value.flowId))return Promise.resolve({ok:false,reason:'invalid_authorization_request'});
    return ipcRenderer.invoke('producer:accounts:authorize',{platform:'youtube',flowId:value.flowId});
  },
}));
