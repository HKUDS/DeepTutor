import { ipcMain, app, shell, BrowserWindow } from 'electron'
import log from 'electron-log'
import Store from 'electron-store'
import { keytarGet, keytarSet, keytarDelete } from './keytar'

const store = new Store({
  name: 'deeptutor-settings',
  encryptionKey: 'deeptutor-desktop-v1'
})

export function setupIpcHandlers(mainWindow: BrowserWindow): void {
  // App info
  ipcMain.handle('app:getVersion', () => app.getVersion())
  ipcMain.handle('app:getPlatform', () => process.platform)

  // Settings
  ipcMain.handle('settings:get', (_event, key: string) => {
    return store.get(key)
  })

  ipcMain.handle('settings:set', (_event, key: string, value: unknown) => {
    store.set(key, value)
    return true
  })

  ipcMain.handle('settings:delete', (_event, key: string) => {
    store.delete(key)
    return true
  })

  // Secure storage for API keys
  ipcMain.handle('secrets:get', async (_event, _service: string, account: string) => {
    return await keytarGet(account)
  })

  ipcMain.handle('secrets:set', async (_event, _service: string, account: string, password: string) => {
    return await keytarSet(account, password)
  })

  ipcMain.handle('secrets:delete', async (_event, _service: string, account: string) => {
    return await keytarDelete(account)
  })

  // External links
  ipcMain.handle('shell:openExternal', (_event, url: string) => {
    return shell.openExternal(url)
  })

  // Window controls
  ipcMain.handle('window:minimize', () => {
    mainWindow.minimize()
  })

  ipcMain.handle('window:maximize', () => {
    if (mainWindow.isMaximized()) {
      mainWindow.unmaximize()
    } else {
      mainWindow.maximize()
    }
  })

  ipcMain.handle('window:close', () => {
    mainWindow.close()
  })

  ipcMain.handle('window:isMaximized', () => {
    return mainWindow.isMaximized()
  })

  // Backend status
  ipcMain.handle('backend:getStatus', () => {
    return { running: true, port: 8001 }
  })

  log.info('IPC handlers registered')
}
