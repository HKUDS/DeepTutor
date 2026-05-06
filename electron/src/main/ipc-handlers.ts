import { ipcMain, app, shell, BrowserWindow } from 'electron'
import log from 'electron-log'
import * as fs from 'fs'
import * as path from 'path'
import { keytarGet, keytarSet, keytarDelete } from './keytar'

// Simple JSON-based store
class SimpleStore {
  private filePath: string

  constructor(name: string) {
    this.filePath = path.join(app.getPath('userData'), `${name}.json`)
    this.ensureFile()
  }

  private ensureFile(): void {
    if (!fs.existsSync(this.filePath)) {
      fs.writeFileSync(this.filePath, '{}', 'utf-8')
    }
  }

  private read(): Record<string, unknown> {
    try {
      const data = fs.readFileSync(this.filePath, 'utf-8')
      return JSON.parse(data)
    } catch {
      return {}
    }
  }

  private write(data: Record<string, unknown>): void {
    fs.writeFileSync(this.filePath, JSON.stringify(data, null, 2), 'utf-8')
  }

  get(key: string): unknown {
    const data = this.read()
    return data[key]
  }

  set(key: string, value: unknown): void {
    const data = this.read()
    data[key] = value
    this.write(data)
  }

  delete(key: string): void {
    const data = this.read()
    delete data[key]
    this.write(data)
  }
}

const store = new SimpleStore('deeptutor-settings')

export function setupIpcHandlers(mainWindow: BrowserWindow): void {
  // App info
  ipcMain.handle('app:getVersion', () => app.getVersion())
  ipcMain.handle('app:getPlatform', () => process.platform)

  // Settings
  ipcMain.handle('settings:get', (_event, key: string) => {
    try {
      return store.get(key)
    } catch (error) {
      log.error('settings:get error:', error)
      return null
    }
  })

  ipcMain.handle('settings:set', (_event, key: string, value: unknown) => {
    try {
      store.set(key, value)
      return true
    } catch (error) {
      log.error('settings:set error:', error)
      return false
    }
  })

  ipcMain.handle('settings:delete', (_event, key: string) => {
    try {
      store.delete(key)
      return true
    } catch (error) {
      log.error('settings:delete error:', error)
      return false
    }
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
    // Security: Only allow http/https protocols
    try {
      const parsedUrl = new URL(url)
      if (!['http:', 'https:'].includes(parsedUrl.protocol)) {
        log.warn(`Blocked dangerous URL protocol: ${parsedUrl.protocol}`)
        return false
      }
      return shell.openExternal(url)
    } catch (error) {
      log.error('Invalid URL:', url)
      return false
    }
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
  // TODO: Get actual backend state instead of hardcoded values
  ipcMain.handle('backend:getStatus', () => {
    return { running: true, port: 8001 }
  })

  log.info('IPC handlers registered')
}
