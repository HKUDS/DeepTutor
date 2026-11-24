const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('desktop', {
  platform: process.platform,
  status: () => ipcRenderer.invoke('desktop:status'),
  restart: () => ipcRenderer.invoke('desktop:restart'),
  logs: () => ipcRenderer.invoke('desktop:logs'),
  popupMenu: (id, position) => ipcRenderer.invoke('desktop:popupMenu', id, position),
  onStatus: callback => { ipcRenderer.on('desktop:status', (_event, state) => callback(state)); },
});
