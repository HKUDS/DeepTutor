'use strict';

/**
 * Application menu. Roles are used wherever Electron already knows the
 * behaviour (edit, zoom, fullscreen) so keyboard handling stays native; the
 * DeepTutor-specific entries delegate to the window manager and the service
 * supervisor.
 */

const path = require('node:path');
const { app, dialog, shell, Menu } = require('electron');

const DOCS_URL = 'https://deeptutor.info';

function buildMenu({ windows, service, config, logger, paths, isDev }) {
  const isMac = process.platform === 'darwin';
  const log = logger.scope('menu');

  const restartService = async () => {
    log.info('restart requested from menu');
    try {
      await service.restart();
    } catch (error) {
      log.error(`restart failed: ${error.message}`);
      dialog.showMessageBox({
        type: 'error',
        title: '服务重启失败',
        message: '无法重启本地服务',
        detail: error.message,
        buttons: ['好'],
      });
    }
  };

  const template = [];

  if (isMac) {
    template.push({
      label: app.name,
      submenu: [
        { role: 'about', label: '关于 DeepTutor' },
        { type: 'separator' },
        { role: 'services', label: '服务' },
        { type: 'separator' },
        { role: 'hide', label: '隐藏 DeepTutor' },
        { role: 'hideOthers', label: '隐藏其他' },
        { role: 'unhide', label: '显示全部' },
        { type: 'separator' },
        { label: '退出 DeepTutor', accelerator: 'Cmd+Q', click: () => app.quit() },
      ],
    });
  }

  template.push({
    label: '文件',
    submenu: [
      {
        label: '新建窗口',
        accelerator: 'CmdOrCtrl+N',
        click: () => windows.createSecondaryWindow(),
      },
      {
        label: '在浏览器中打开',
        accelerator: 'CmdOrCtrl+Shift+O',
        enabled: service.isReady(),
        click: () => service.url && windows.openExternal(service.url),
      },
      { type: 'separator' },
      {
        label: '重启本地服务',
        accelerator: 'CmdOrCtrl+Shift+R',
        click: restartService,
      },
      { type: 'separator' },
      { role: 'close', label: '关闭窗口' },
      ...(isMac ? [] : [{ role: 'quit', label: '退出' }]),
    ],
  });

  template.push({
    label: '编辑',
    submenu: [
      { role: 'undo', label: '撤销' },
      { role: 'redo', label: '重做' },
      { type: 'separator' },
      { role: 'cut', label: '剪切' },
      { role: 'copy', label: '复制' },
      { role: 'paste', label: '粘贴' },
      { role: 'selectAll', label: '全选' },
    ],
  });

  template.push({
    label: '视图',
    submenu: [
      { role: 'reload', label: '重新加载' },
      {
        label: '强制重新加载界面',
        accelerator: 'CmdOrCtrl+F5',
        click: () => windows.loadApp(),
      },
      { type: 'separator' },
      {
        label: '放大',
        accelerator: 'CmdOrCtrl+Plus',
        click: () => windows.stepZoom(0.1),
      },
      {
        label: '缩小',
        accelerator: 'CmdOrCtrl+-',
        click: () => windows.stepZoom(-0.1),
      },
      {
        label: '实际大小',
        accelerator: 'CmdOrCtrl+0',
        click: () => windows.setZoom(1),
      },
      { type: 'separator' },
      { role: 'togglefullscreen', label: '全屏' },
      {
        label: '开发者工具',
        accelerator: isMac ? 'Alt+Cmd+I' : 'Ctrl+Shift+I',
        visible: true,
        click: () => windows.toggleDevTools(),
      },
    ],
  });

  template.push({
    label: '窗口',
    submenu: [
      { role: 'minimize', label: '最小化' },
      ...(isMac
        ? [{ role: 'zoom', label: '缩放' }, { role: 'front', label: '前置全部窗口' }]
        : [{ role: 'zoom', label: '缩放' }]),
    ],
  });

  template.push({
    role: 'help',
    label: '帮助',
    submenu: [
      {
        label: 'DeepTutor 文档',
        click: () => windows.openExternal(DOCS_URL),
      },
      {
        label: '打开日志文件夹',
        click: () => shell.openPath(logger.dir || app.getPath('userData')),
      },
      {
        label: '打开配置文件夹',
        click: () => shell.openPath(app.getPath('userData')),
      },
      {
        label: '打开工作区目录',
        click: () => shell.openPath(paths.home()),
      },
      { type: 'separator' },
      {
        label: '运行诊断',
        click: () => {
          const status = service.getStatus();
          dialog.showMessageBox({
            type: 'info',
            title: '运行诊断',
            message: `状态：${status.state}`,
            detail: [
              `模式：${status.mode || '未启动'}`,
              `界面地址：${status.url || '—'}`,
              `后端地址：${status.backendUrl || '—'}`,
              `工作区：${paths.home()}`,
              `Python：${paths.python().command}`,
              `日志：${logger.filePath || '（未写入）'}`,
            ].join('\n'),
            buttons: ['好'],
          });
        },
      },
      { type: 'separator' },
      {
        label: '关于 DeepTutor',
        click: () => {
          dialog.showMessageBox({
            type: 'info',
            title: '关于 DeepTutor',
            message: `DeepTutor 桌面版 ${app.getVersion()}`,
            detail: [
              `Electron ${process.versions.electron}`,
              `Chromium ${process.versions.chrome}`,
              `Node ${process.versions.node}`,
              `平台 ${process.platform} ${process.arch}`,
              `运行模式 ${app.isPackaged ? '安装版' : '源码模式'}`,
            ].join('\n'),
            buttons: ['好'],
          });
        },
      },
    ],
  });

  return Menu.buildFromTemplate(template);
}

function installMenu(options) {
  const menu = buildMenu(options);
  Menu.setApplicationMenu(menu);
  return menu;
}

module.exports = { installMenu, buildMenu, DOCS_URL };
