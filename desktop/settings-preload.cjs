'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('producerSettings',Object.freeze({
  prepareOutput:value=>ipcRenderer.invoke('producer:broadcast:prepare',value),
  startBroadcast:value=>ipcRenderer.invoke('producer:broadcast:start',value),
  stopBroadcast:()=>ipcRenderer.invoke('producer:broadcast:stop'),
  broadcastStatus:()=>ipcRenderer.invoke('producer:broadcast:status'),
  status:()=>ipcRenderer.invoke('producer:destinations:status'),
  save:value=>ipcRenderer.invoke('producer:destinations:save',value),
  remove:id=>ipcRenderer.invoke('producer:destinations:remove',id),
  openPlatform:value=>ipcRenderer.invoke('producer:platform',value),
}));
