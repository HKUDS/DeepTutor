import { autoUpdater } from 'electron-updater'
import { BrowserWindow, ipcMain } from 'electron'
import log from 'electron-log'

export function setupUpdater(mainWindow: BrowserWindow): void {
  autoUpdater.logger = log
  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = true

  autoUpdater.on('checking-for-update', () => {
    log.info('Checking for updates...')
    mainWindow.webContents.send('update:status', 'checking')
  })

  autoUpdater.on('update-available', (info) => {
    log.info('Update available:', info.version)
    mainWindow.webContents.send('update:available', info)
  })

  autoUpdater.on('update-not-available', () => {
    log.info('No updates available')
    mainWindow.webContents.send('update:status', 'up-to-date')
  })

  autoUpdater.on('error', (err) => {
    log.error('Update error:', err)
    mainWindow.webContents.send('update:error', err.message)
  })

  autoUpdater.on('download-progress', (progress) => {
    log.info(`Download progress: ${progress.percent.toFixed(1)}%`)
    mainWindow.webContents.send('update:progress', progress)
  })

  autoUpdater.on('update-downloaded', (info) => {
    log.info('Update downloaded:', info.version)
    mainWindow.webContents.send('update:downloaded', info)
  })

  // IPC handlers for update control
  ipcMain.handle('update:check', async () => {
    try {
      return await autoUpdater.checkForUpdates()
    } catch (error) {
      log.error('Check for updates failed:', error)
      return null
    }
  })

  ipcMain.handle('update:download', async () => {
    try {
      await autoUpdater.downloadUpdate()
      return true
    } catch (error) {
      log.error('Download update failed:', error)
      return false
    }
  })

  ipcMain.handle('update:install', () => {
    autoUpdater.quitAndInstall()
  })

  // Check for updates on startup (after 5 seconds)
  setTimeout(() => {
    autoUpdater.checkForUpdates().catch((err) => {
      log.error('Initial update check failed:', err)
    })
  }, 5000)
}
