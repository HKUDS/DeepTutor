'use strict';

/**
 * Headless smoke test.
 *
 *   npx electron . --smoke --smoke-out=./artifacts/smoke.json
 *
 * Boots the real application, waits for the local stack, verifies that the
 * DeepTutor UI actually rendered (DOM, IPC bridge, proxied API call, network
 * errors), captures a screenshot, writes a JSON report and exits with a status
 * code. Used to prove "it starts and the interface is complete" without a human
 * clicking around.
 */

const fs = require('node:fs');
const path = require('node:path');
const { session } = require('electron');

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Console noise that is produced by Chromium/Electron or by React's layout
 * bookkeeping rather than by anything the shell can fix. Recorded, not fatal.
 */
const BENIGN_CONSOLE_ERRORS = [
  /ResizeObserver loop (limit exceeded|completed with undelivered notifications)/i,
  /Electron Security Warning/i,
];

function isBenignConsoleError(message) {
  return BENIGN_CONSOLE_ERRORS.some((pattern) => pattern.test(message || ''));
}

function collectConsole(webContents, sink) {
  webContents.on('console-message', (...args) => {
    // Electron ≥ 36 passes a single details object; older versions pass
    // (event, level, message, line, sourceId). Support both.
    const details = args[0] && typeof args[0] === 'object' && 'message' in args[0]
      ? args[0]
      : { level: args[1], message: args[2], lineNumber: args[3], sourceId: args[4] };
    const level = typeof details.level === 'number'
      ? ['debug', 'info', 'warning', 'error'][details.level] || String(details.level)
      : String(details.level ?? 'info');
    if (level === 'error' || level === 'warning') {
      sink.push({ level, message: String(details.message).slice(0, 500), source: details.sourceId });
    }
  });
}

function collectNetwork(sess, sink) {
  sess.webRequest.onCompleted({ urls: ['http://127.0.0.1:*/*', 'http://localhost:*/*'] }, (details) => {
    if (details.statusCode >= 400) {
      sink.push({ url: details.url, status: details.statusCode, resourceType: details.resourceType });
    }
  });
  sess.webRequest.onErrorOccurred({ urls: ['http://127.0.0.1:*/*', 'http://localhost:*/*'] }, (details) => {
    sink.push({ url: details.url, error: details.error, resourceType: details.resourceType });
  });
}

async function waitFor(predicate, { timeoutMs, intervalMs = 500, label }) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return true;
    await delay(intervalMs);
  }
  throw new Error(`超时：${label || '等待条件'} (${timeoutMs}ms)`);
}

/** A stuck renderer must not hang the harness forever. */
function withTimeout(promise, ms, label) {
  let timer;
  const timeout = new Promise((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error(`超时：${label} (${ms}ms)`)), ms);
  });
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}

async function capture(win, target) {
  try {
    const image = await withTimeout(win.webContents.capturePage(), 15000, 'capturePage');
    fs.writeFileSync(target, image.toPNG());
    return target;
  } catch (error) {
    return `capture failed: ${error.message}`;
  }
}

function runSmoke({ app, service, windows, logger, outPath, timeoutMs = 240000 }) {
  const startedAt = Date.now();
  const consoleIssues = [];
  const networkIssues = [];
  const report = {
    ok: false,
    startedAt: new Date().toISOString(),
    app: { version: app.getVersion(), packaged: app.isPackaged },
    steps: [],
  };

  const outDir = path.dirname(outPath);
  fs.mkdirSync(outDir, { recursive: true });
  const shotPath = path.join(outDir, 'smoke-screenshot.png');

  const step = (name, detail) => {
    report.steps.push({ name, at: Date.now() - startedAt, ...detail });
    logger.info(`[smoke] ${name}${detail ? ` ${JSON.stringify(detail)}` : ''}`);
  };

  collectNetwork(session.defaultSession, networkIssues);

  const finish = async (code, error) => {
    try {
      const win = windows.mainWindow;
      if (win && !win.isDestroyed()) {
        const image = await withTimeout(win.webContents.capturePage(), 15000, 'final capturePage');
        fs.writeFileSync(shotPath, image.toPNG());
        report.screenshot = shotPath;
      }
    } catch (captureError) {
      report.screenshotError = captureError.message;
    }

    report.ok = code === 0;
    if (error) report.error = error.message || String(error);
    report.finishedAt = new Date().toISOString();
    report.durationMs = Date.now() - startedAt;
    report.consoleIssues = consoleIssues.slice(0, 40);
    report.networkIssues = networkIssues.slice(0, 40);
    report.service = service.getStatus();

    try {
      fs.writeFileSync(outPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');
      logger.info(`[smoke] report written to ${outPath}`);
    } catch (writeError) {
      logger.error(`[smoke] cannot write report: ${writeError.message}`);
    }

    logger.flush();
    app.exit(code);
  };

  (async () => {
    try {
      const win = windows.mainWindow;
      if (!win) throw new Error('主窗口未创建');
      collectConsole(win.webContents, consoleIssues);
      step('window-created');

      await waitFor(() => service.isReady(), { timeoutMs, label: '本地服务就绪' });
      step('service-ready', { mode: service.getStatus().mode, url: service.url });

      await waitFor(
        () => {
          const url = win.webContents.getURL();
          return url.startsWith(service.url);
        },
        { timeoutMs: 60000, label: '窗口加载界面地址' },
      );
      step('app-url-loaded', { url: win.webContents.getURL() });

      await delay(3500);
      report.bootScreenshot = await capture(win, path.join(outDir, 'smoke-screenshot-boot.png'));
      step('boot-screenshot', { path: report.bootScreenshot });

      await waitFor(() => !win.webContents.isLoadingMainFrame(), { timeoutMs: 60000, label: '主框架停止加载' });
      // SPA hydration + first data fetches.
      await delay(6000);

      step('dom-probe-start', { url: win.webContents.getURL() });
      const probe = await withTimeout(
        win.webContents.executeJavaScript(
        `(async () => {
           const bridge = typeof window.deeptutor === 'object' && window.deeptutor !== null;
           let ipc = null;
           let ipcError = null;
           if (bridge) {
             try {
               const info = await window.deeptutor.app.info();
               ipc = { version: info.version, packaged: info.packaged, hasRuntime: Boolean(info.runtime) };
             } catch (error) {
               ipcError = error.message;
             }
           }
           let proxy = null;
           try {
             // /api/* is proxied by the Next middleware to the Python backend,
             // so a 200 here proves UI -> frontend -> backend works end to end.
             const response = await fetch('/api/modules', { redirect: 'manual' });
             proxy = { status: response.status, ok: response.ok };
           } catch (error) {
             proxy = { error: error.message };
           }
           const text = (document.body && document.body.innerText || '').trim();
           return {
             title: document.title,
             href: location.href,
             bridge,
             ipc,
             ipcError,
             proxy,
             shellMarker: document.documentElement.dataset.deeptutorShell || null,
             textLength: text.length,
             textSample: text.slice(0, 400),
             interactive: document.querySelectorAll('button, a, input, [role="button"]').length,
             hasNav: Boolean(document.querySelector('nav, [role="navigation"], header, aside')),
             rootChildren: (document.getElementById('__next') || document.body).children.length,
           };
         })()`,
        true,
        ),
        30000,
        'DOM 探测',
      );

      report.page = probe;
      step('dom-probe', {
        title: probe.title,
        textLength: probe.textLength,
        interactive: probe.interactive,
        bridge: probe.bridge,
      });

      // Interaction check: click a real sidebar entry and confirm the SPA
      // router (and therefore the renderer's event loop) actually responds.
      const interaction = await withTimeout(
        win.webContents.executeJavaScript(
          `(async () => {
             const before = location.pathname + location.search;
             const anchors = Array.from(document.querySelectorAll('a[href^="/"]'))
               .filter((a) => a.offsetParent !== null)
               .filter((a) => {
                 try { return new URL(a.href).pathname !== location.pathname; } catch { return false; }
               });
             if (!anchors.length) return { skipped: '未找到可见的导航链接' };
             const target =
               anchors.find((a) => /calendar|notebook|task|kanban|knowledge|reading/i.test(a.getAttribute('href'))) ||
               anchors[0];
             const href = new URL(target.href).pathname;
             target.click();
             await new Promise((resolve) => setTimeout(resolve, 2500));
             return { before, href, after: location.pathname + location.search, changed: location.pathname === href };
           })()`,
          true,
        ),
        25000,
        '交互测试',
      );
      report.interaction = interaction;
      step('interaction', interaction);

      // Back to the chat surface so the final screenshot shows the home view.
      try {
        await win.webContents.executeJavaScript('history.back()', true);
        await delay(1200);
      } catch { /* not fatal */ }

      const consoleErrors = consoleIssues.filter(
        (issue) => issue.level === 'error' && !isBenignConsoleError(issue.message),
      );
      report.consoleErrors = consoleErrors;
      report.consoleNotices = consoleIssues.filter((issue) => isBenignConsoleError(issue.message));

      const checks = {
        bridgeExposed: probe.bridge === true,
        ipcRoundTrip: Boolean(probe.ipc) && !probe.ipcError,
        shellMarker: probe.shellMarker === 'electron',
        renderedContent: probe.textLength > 200,
        interactiveElements: probe.interactive > 5,
        layoutMounted: probe.rootChildren > 0,
        apiReachable: Boolean(probe.proxy) && probe.proxy.status === 200,
        navigationWorks: interaction.skipped ? true : interaction.changed === true,
        noSevereNetworkErrors: networkIssues.filter((issue) => issue.status >= 500).length === 0,
        noConsoleErrors: consoleErrors.length === 0,
      };
      report.checks = checks;

      const failed = Object.entries(checks).filter(([, value]) => !value).map(([key]) => key);
      if (failed.length) {
        step('checks-failed', { failed });
        return finish(1, new Error(`检查项未通过：${failed.join(', ')}`));
      }

      step('checks-passed');
      return finish(0);
    } catch (error) {
      logger.error(`[smoke] failed: ${error.stack || error.message}`);
      return finish(1, error);
    }
  })();
}

module.exports = { runSmoke };
