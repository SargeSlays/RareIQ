'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('producerCapturePicker', Object.freeze({
  list: () => ipcRenderer.invoke('producer:capture:list'),
  choose: id => ipcRenderer.invoke('producer:capture:choose', typeof id === 'string' ? id : null),
  cancel: () => ipcRenderer.invoke('producer:capture:cancel'),
}));
