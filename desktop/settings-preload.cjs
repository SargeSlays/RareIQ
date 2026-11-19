'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('producerSettings',Object.freeze({
  openSources:()=>ipcRenderer.invoke('producer:sources:open'),
  viewOutput:()=>ipcRenderer.invoke('producer:output:view'),
  prepareOutput:value=>ipcRenderer.invoke('producer:broadcast:prepare',value),
  startBroadcast:value=>ipcRenderer.invoke('producer:broadcast:start',value),
  stopBroadcast:()=>ipcRenderer.invoke('producer:broadcast:stop'),
  stopBroadcastTarget:id=>ipcRenderer.invoke('producer:broadcast:stop-target',id),
  broadcastStatus:()=>ipcRenderer.invoke('producer:broadcast:status'),
  setLiveAudio:value=>ipcRenderer.invoke('producer:broadcast:audio',value),
  twitchAccount:value=>ipcRenderer.invoke('producer:accounts:twitch',value),
  status:()=>ipcRenderer.invoke('producer:destinations:status'),
  save:value=>ipcRenderer.invoke('producer:destinations:save',value),
  remove:id=>ipcRenderer.invoke('producer:destinations:remove',id),
  listOutputProfiles:()=>ipcRenderer.invoke('producer:profiles:list'),
  saveOutputProfile:value=>ipcRenderer.invoke('producer:profiles:save',value),
  removeOutputProfile:id=>ipcRenderer.invoke('producer:profiles:remove',id),
  selectOutputProfile:id=>ipcRenderer.invoke('producer:profiles:select',id),
  openPlatform:value=>ipcRenderer.invoke('producer:platform',value),
}));
