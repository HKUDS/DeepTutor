const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('desktop', {
  platform: process.platform,
  status: () => ipcRenderer.invoke('desktop:status'),
  restart: () => ipcRenderer.invoke('desktop:restart'),
  logs: () => ipcRenderer.invoke('desktop:logs'),
  onStatus: callback => { ipcRenderer.on('desktop:status', (_event, state) => callback(state)); },
});
