'use strict';

/**
 * System tray: keeps a way back into the app when the window is hidden, and
 * exposes the two operations users actually need from a tray — open, restart
 * the local service, quit. The tooltip doubles as a status indicator.
 */

const { app, Menu, Tray, nativeImage, shell } = require('electron');

const STATUS_LABEL = {
  idle: '未启动',
  probing: '检测中…',
  'starting-backend': '正在启动后端…',
  'starting-frontend': '正在启动界面…',
  ready: '已就绪',
  stopping: '正在停止…',
  error: '启动失败',
};

class TrayController {
  constructor({ windows, service, config, logger, iconPath }) {
    this.windows = windows;
    this.service = service;
    this.config = config;
    this.logger = logger.scope('tray');
    this.iconPath = iconPath;
    this.tray = null;
    this.status = service.getStatus();
  }

  create() {
    if (this.tray) return this.tray;
    let image = nativeImage.createFromPath(this.iconPath);
    if (image.isEmpty()) {
      this.logger.warn(`tray icon missing at ${this.iconPath}`);
      image = nativeImage.createEmpty();
    } else if (process.platform === 'darwin') {
      image = image.resize({ width: 18, height: 18 });
      image.setTemplateImage(true);
    } else {
      image = image.resize({ width: 16, height: 16 });
    }

    this.tray = new Tray(image);
    this.tray.setToolTip('DeepTutor');
    this.tray.on('click', () => this.windows.toggleVisibility());
    this.tray.on('double-click', () => this.windows.show());
    this.#refreshMenu();
    return this.tray;
  }

  update(status) {
    this.status = status;
    if (!this.tray) return;
    const label = STATUS_LABEL[status.state] || status.state;
    this.tray.setToolTip(`DeepTutor · ${label}${status.url ? `\n${status.url}` : ''}`);
    this.#refreshMenu();
  }

  #refreshMenu() {
    if (!this.tray) return;
    const status = this.status || {};
    const label = STATUS_LABEL[status.state] || status.state || '未知';
    const ready = status.state === 'ready';

    const menu = Menu.buildFromTemplate([
      { label: `DeepTutor · ${label}`, enabled: false },
      { type: 'separator' },
      { label: '显示主窗口', click: () => this.windows.show() },
      {
        label: '在浏览器中打开',
        enabled: ready && Boolean(status.url),
        click: () => status.url && this.windows.openExternal(status.url),
      },
      { type: 'separator' },
      {
        label: '重启本地服务',
        click: async () => {
          try {
            await this.service.restart();
          } catch (error) {
            this.logger.error(`tray restart failed: ${error.message}`);
          }
        },
      },
      {
        label: '打开日志文件夹',
        click: () => shell.openPath(app.getPath('userData')),
      },
      { type: 'separator' },
      {
        label: '关闭窗口时最小化到托盘',
        type: 'checkbox',
        checked: Boolean(this.config.get('behavior.closeToTray')),
        click: (item) => {
          const current = this.config.get('behavior');
          this.config.set({ behavior: { ...current, closeToTray: item.checked } });
        },
      },
      {
        label: '开机启动',
        type: 'checkbox',
        checked: Boolean(this.config.get('behavior.launchAtLogin')),
        click: (item) => {
          const current = this.config.get('behavior');
          this.config.set({ behavior: { ...current, launchAtLogin: item.checked } });
          app.setLoginItemSettings({ openAtLogin: item.checked, openAsHidden: true });
        },
      },
      { type: 'separator' },
      { label: '退出 DeepTutor', click: () => app.quit() },
    ]);

    this.tray.setContextMenu(menu);
  }

  destroy() {
    if (this.tray) {
      this.tray.destroy();
      this.tray = null;
    }
  }
}

module.exports = { TrayController, STATUS_LABEL };
