'use strict';

/**
 * Navigation policy for every webContents the shell creates.
 *
 * DeepTutor is a single-page app that talks to its own loopback origin. Anything
 * that leaves that origin — docs links, provider sign-in pages, citations — must
 * open in the user's real browser, never inside a window that has the preload
 * bridge attached. That single rule is what keeps the renderer sandboxed.
 */

const SAFE_EXTERNAL_PROTOCOLS = new Set(['http:', 'https:', 'mailto:', 'tel:']);

function parseUrl(raw, base) {
  try {
    return base ? new URL(raw, base) : new URL(raw);
  } catch {
    return null;
  }
}

function sameOrigin(target, appOrigin) {
  const url = parseUrl(target);
  if (!url || !appOrigin) return false;
  const origin = parseUrl(appOrigin);
  if (!origin) return false;
  return url.origin === origin.origin;
}

/**
 * @param {import('electron').WebContents} contents
 * @param {{ appOrigin: () => string|null, openExternal: (url: string) => void, logger: object }} options
 */
function attachExternalLinkPolicy(contents, { appOrigin, openExternal, logger, onNewWindow } = {}) {
  const log = logger ?? { info() {}, warn() {} };

  const openSafely = (rawUrl) => {
    const url = parseUrl(rawUrl);
    if (!url) {
      log.warn(`blocked malformed url: ${rawUrl}`);
      return false;
    }
    if (!SAFE_EXTERNAL_PROTOCOLS.has(url.protocol)) {
      log.warn(`blocked non-web protocol: ${url.protocol}`);
      return false;
    }
    openExternal(url.toString());
    return true;
  };

  contents.setWindowOpenHandler(({ url }) => {
    if (sameOrigin(url, appOrigin?.())) {
      log.info(`in-app popup: ${url}`);
      return {
        action: 'allow',
        overrideBrowserWindowOptions: {
          width: 1080,
          height: 780,
          autoHideMenuBar: true,
          backgroundColor: '#111214',
          webPreferences: {
            contextIsolation: true,
            nodeIntegration: false,
            sandbox: true,
            webSecurity: true,
            // Deliberately no preload: a popup never needs the desktop bridge.
          },
        },
      };
    }
    openSafely(url);
    return { action: 'deny' };
  });

  contents.on('did-create-window', (child) => {
    try {
      onNewWindow?.(child);
    } catch (error) {
      log.warn(`new window hook failed: ${error.message}`);
    }
    attachExternalLinkPolicy(child.webContents, { appOrigin, openExternal, logger, onNewWindow });
    // A popup is a transient window: closing it must not keep the app alive.
    child.on('closed', () => {});
  });

  const guard = (event, url) => {
    if (sameOrigin(url, appOrigin?.())) return;
    event.preventDefault();
    openSafely(url);
  };

  contents.on('will-navigate', (event, url) => guard(event, url));
  contents.on('will-redirect', (event, url) => guard(event, url));

  contents.on('will-attach-webview', (event) => {
    log.warn('blocked <webview> attach');
    event.preventDefault();
  });

  // Nothing in the app needs camera/geolocation/serial access; media is allowed
  // because the tutor has speech practice, and it still goes through the OS
  // permission prompt.
  const ALLOWED_PERMISSIONS = new Set(['media', 'fullscreen', 'clipboard-sanitized-write', 'notifications']);
  contents.session.setPermissionRequestHandler((_wc, permission, callback) => {
    const allowed = ALLOWED_PERMISSIONS.has(permission);
    if (!allowed) log.warn(`denied permission request: ${permission}`);
    callback(allowed);
  });
  contents.session.setPermissionCheckHandler((_wc, permission) => ALLOWED_PERMISSIONS.has(permission));
}

module.exports = { attachExternalLinkPolicy, sameOrigin, SAFE_EXTERNAL_PROTOCOLS };
