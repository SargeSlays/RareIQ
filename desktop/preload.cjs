'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('producerDesktop',Object.freeze({
  broadcastStatus:()=>ipcRenderer.invoke('producer:broadcast:status'),
  info:()=>ipcRenderer.invoke('producer:info'),
  openBroadcastSettings:()=>ipcRenderer.invoke('producer:settings'),
}));
