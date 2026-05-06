import { contextBridge, ipcRenderer } from 'electron'

export interface ElectronAPI {
  app: {
    getVersion: () => Promise<string>
    getPlatform: () => Promise<NodeJS.Platform>
  }
  settings: {
    get: (key: string) => Promise<unknown>
    set: (key: string, value: unknown) => Promise<boolean>
    delete: (key: string) => Promise<boolean>
  }
  secrets: {
    get: (service: string, account: string) => Promise<string | null>
    set: (service: string, account: string, password: string) => Promise<boolean>
    delete: (service: string, account: string) => Promise<boolean>
  }
  shell: {
    openExternal: (url: string) => Promise<void>
  }
  window: {
    minimize: () => Promise<void>
    maximize: () => Promise<void>
    close: () => Promise<void>
    isMaximized: () => Promise<boolean>
    onMaximizeChange: (callback: (isMaximized: boolean) => void) => () => void
  }
  backend: {
    getStatus: () => Promise<{ running: boolean; port: number }>
  }
  update: {
    check: () => Promise<unknown>
    download: () => Promise<boolean>
    install: () => void
    onStatus: (callback: (status: string) => void) => () => void
    onAvailable: (callback: (info: unknown) => void) => () => void
    onProgress: (callback: (progress: unknown) => void) => () => void
    onDownloaded: (callback: (info: unknown) => void) => () => void
    onError: (callback: (error: string) => void) => () => void
  }
}

const electronAPI: ElectronAPI = {
  app: {
    getVersion: () => ipcRenderer.invoke('app:getVersion'),
    getPlatform: () => ipcRenderer.invoke('app:getPlatform')
  },
  settings: {
    get: (key) => ipcRenderer.invoke('settings:get', key),
    set: (key, value) => ipcRenderer.invoke('settings:set', key, value),
    delete: (key) => ipcRenderer.invoke('settings:delete', key)
  },
  secrets: {
    get: (service, account) => ipcRenderer.invoke('secrets:get', service, account),
    set: (service, account, password) => ipcRenderer.invoke('secrets:set', service, account, password),
    delete: (service, account) => ipcRenderer.invoke('secrets:delete', service, account)
  },
  shell: {
    openExternal: (url) => ipcRenderer.invoke('shell:openExternal', url)
  },
  window: {
    minimize: () => ipcRenderer.invoke('window:minimize'),
    maximize: () => ipcRenderer.invoke('window:maximize'),
    close: () => ipcRenderer.invoke('window:close'),
    isMaximized: () => ipcRenderer.invoke('window:isMaximized'),
    onMaximizeChange: (callback) => {
      const handler = (_event: Electron.IpcRendererEvent, isMaximized: boolean) => callback(isMaximized)
      ipcRenderer.on('window:maximizeChanged', handler)
      return () => ipcRenderer.removeListener('window:maximizeChanged', handler)
    }
  },
  backend: {
    getStatus: () => ipcRenderer.invoke('backend:getStatus')
  },
  update: {
    check: () => ipcRenderer.invoke('update:check'),
    download: () => ipcRenderer.invoke('update:download'),
    install: () => ipcRenderer.invoke('update:install'),
    onStatus: (callback) => {
      const handler = (_event: Electron.IpcRendererEvent, status: string) => callback(status)
      ipcRenderer.on('update:status', handler)
      return () => ipcRenderer.removeListener('update:status', handler)
    },
    onAvailable: (callback) => {
      const handler = (_event: Electron.IpcRendererEvent, info: unknown) => callback(info)
      ipcRenderer.on('update:available', handler)
      return () => ipcRenderer.removeListener('update:available', handler)
    },
    onProgress: (callback) => {
      const handler = (_event: Electron.IpcRendererEvent, progress: unknown) => callback(progress)
      ipcRenderer.on('update:progress', handler)
      return () => ipcRenderer.removeListener('update:progress', handler)
    },
    onDownloaded: (callback) => {
      const handler = (_event: Electron.IpcRendererEvent, info: unknown) => callback(info)
      ipcRenderer.on('update:downloaded', handler)
      return () => ipcRenderer.removeListener('update:downloaded', handler)
    },
    onError: (callback) => {
      const handler = (_event: Electron.IpcRendererEvent, error: string) => callback(error)
      ipcRenderer.on('update:error', handler)
      return () => ipcRenderer.removeListener('update:error', handler)
    }
  }
}

contextBridge.exposeInMainWorld('electron', electronAPI)
