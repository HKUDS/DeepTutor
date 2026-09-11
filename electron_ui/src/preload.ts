import { contextBridge, ipcRenderer } from 'electron';

contextBridge.exposeInMainWorld('deeptutorApp', {
  start:     () => ipcRenderer.invoke('app:start'),
  stop:      () => ipcRenderer.invoke('app:stop'),
  restart:   () => ipcRenderer.invoke('app:restart'),
  getStatus: () => ipcRenderer.invoke('app:get-status'),
  getConfig: () => ipcRenderer.invoke('app:get-config'),
  onError: (cb: (msg: string) => void) => {
    const subscription = (_: Electron.IpcRendererEvent, msg: string) => cb(msg);
    ipcRenderer.on('app:error', subscription);
    return () => ipcRenderer.removeListener('app:error', subscription);
  },
});
