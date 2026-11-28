import { clipboard, Menu, shell } from 'electron';
import { execFile } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';
import { canCopyFileText, mayOpenInBrowser, readFileText } from './file-content.mjs';

const runFile = promisify(execFile);
const openWithScript = fileURLToPath(new URL('./windows_open_with.py', import.meta.url));
const FILE_ROUTE = /^\/files\/(?:workspace-items\/ws_[a-f\d]{32}\/wsi_[a-f\d]{32}|(?:outputs|attachments)\/.+)$/;
const UNAVAILABLE_LINK = '#chat-file-unavailable-';

// Open With can run the file's associated command. Keep shell launch available
// for documents, media, and source types that Windows doesn't execute directly.
const DOCUMENT_EXTENSIONS = new Set([
  '.c', '.cc', '.cpp', '.css', '.csv', '.doc', '.docx', '.epub', '.gif', '.go', '.h',
  '.ini', '.jpeg', '.jpg', '.json', '.log', '.markdown', '.md',
  '.mov', '.mp3', '.mp4', '.odt', '.pdf', '.png', '.ppt', '.pptx', '.rs', '.rst',
  '.rtf', '.toml', '.tsv', '.txt', '.wav', '.webm', '.webp', '.xls', '.xlsx',
  '.xml', '.yaml', '.yml',
]);

function fileTarget(linkURL, pageURL, origin) {
  let url;
  try { url = new URL(linkURL); }
  catch { return null; }
  if (url.origin !== origin || url.username || url.password) return null;
  const href = url.href;
  const unavailable = url.hash.startsWith(UNAVAILABLE_LINK);
  url.hash = '';
  if (unavailable && url.href === pageURL.split('#', 1)[0]) return { href, url: null };
  if (!FILE_ROUTE.test(url.pathname)) return null;
  return { href, url };
}

function withChatFileLink(content, href, open) {
  return content.executeJavaScript(`(() => {
    for (const anchor of document.querySelectorAll('a[data-chat-file-link]')) {
      if (anchor.href !== ${JSON.stringify(href)}) continue;
      if (${open}) {
        anchor.focus({ preventScroll: true });
        anchor.click();
      }
      return true;
    }
    return false;
  })()`).catch(() => false);
}

function decodeHeader(value) {
  if (!value) return '';
  try { return decodeURIComponent(value); }
  catch { return ''; }
}

async function readMetadata(session, url, key) {
  const response = await session.fetch(url.href, {
    method: 'HEAD',
    headers: { 'x-deeptutor-desktop-file-key': key },
    credentials: 'include',
    redirect: 'error',
    cache: 'no-store',
    signal: AbortSignal.timeout(3000),
  });
  if (!response.ok) return null;
  const headers = response.headers;
  const decoded = decodeHeader(headers.get('x-deeptutor-local-file'));
  const original = path.isAbsolute(decoded) ? decoded : '';
  const disposition = headers.get('content-disposition') || '';
  const filename = decodeHeader(/filename\*=utf-8''([^;]+)/i.exec(disposition)?.[1]) ||
    /filename="([^"]+)"/i.exec(disposition)?.[1] || decodeHeader(url.pathname.split('/').pop());
  return { headers, original, filename };
}

async function openInBrowser(session, url) {
  const target = new URL(url);
  target.searchParams.set('view', 'browser');
  const response = await session.fetch(target.href, {
    method: 'HEAD', credentials: 'omit', redirect: 'manual', signal: AbortSignal.timeout(3000),
  });
  if (response.status === 401) {
    const login = new URL('/login', url);
    login.searchParams.set('next', target.pathname + target.search);
    await shell.openExternal(login.href);
  } else if (response.ok) {
    await shell.openExternal(target.href);
  } else {
    throw new Error('Unable to open the file in the browser');
  }
}

function canOpenInSystemApp(original) {
  return DOCUMENT_EXTENSIONS.has(path.extname(original).toLowerCase());
}

async function openWith(pythonPath, operation, original, handlerId) {
  if (!pythonPath || !canOpenInSystemApp(original)) throw new Error('File cannot be opened with a system app');
  const args = [openWithScript, operation, original];
  if (handlerId !== undefined) args.push(handlerId);
  const env = { ...process.env, PYTHONIOENCODING: 'utf-8' };
  delete env.ELECTRON_RUN_AS_NODE;
  delete env.DEEPTUTOR_DESKTOP_FILE_KEY;
  const { stdout } = await runFile(pythonPath, args, {
    windowsHide: true, encoding: 'utf8', maxBuffer: 256 * 1024,
    // The picker can stay open while the user is choosing an application.
    timeout: operation === 'list' ? 3000 : 0,
    env,
  });
  if (operation !== 'list') return;
  const handlers = JSON.parse(stdout);
  return handlers.filter(item => typeof item.id === 'string' && typeof item.label === 'string');
}

function notify(content, message, tone) {
  if (content.isDestroyed()) return;
  const detail = JSON.stringify({ message, tone });
  void content.executeJavaScript(
    `window.dispatchEvent(new CustomEvent('deeptutor:desktop-file-notice', { detail: ${detail} }));`,
  ).catch(() => {});
}

function saveAs(content, url, failed) {
  const session = content.session;
  const onDownload = (_event, item, sender) => {
    if (sender !== content || item.getURL() !== url.href || item.getInitiatorOrigin()) return;
    cleanup();
    item.once('done', (_doneEvent, state) => {
      if (state === 'interrupted') failed();
    });
  };
  const timeout = setTimeout(cleanup, 10000);
  function cleanup() {
    clearTimeout(timeout);
    session.removeListener('will-download', onDownload);
  }
  session.on('will-download', onDownload);
  try {
    // Keep Electron's native save prompt, including suggested name, cancel and overwrite.
    content.downloadURL(url.href);
  } catch (error) {
    cleanup();
    throw error;
  }
}

export function mountFileMenu(window, content, origin, key, t, pythonPath) {
  let latestRequest = 0;
  const session = content.session;
  content.on('context-menu', async (_event, params) => {
    const request = ++latestRequest;
    if (params.frame !== content.mainFrame || params.isEditable) return;
    const currentPage = content.getURL();
    const target = fileTarget(params.linkURL, currentPage, origin);
    if (!target) return;

    const stillHere = () =>
      !window.isDestroyed() && !content.isDestroyed() && content.getURL() === currentPage;
    if (!await withChatFileLink(content, target.href, false) || !stillHere() || request !== latestRequest) {
      return;
    }
    const resolve = () => target.url
      ? readMetadata(session, target.url, key).catch(() => null)
      : Promise.resolve(null);
    const file = await resolve();
    const canOpenInDefaultApp = canOpenInSystemApp(file?.original || '');
    const canOpenWith = Boolean(pythonPath && canOpenInDefaultApp);
    const handlers = canOpenWith
      ? await openWith(pythonPath, 'list', file.original).catch(() => [])
      : [];
    if (!stillHere() || request !== latestRequest) return;

    const report = (label, tone) => { if (stillHere()) notify(content, t(label), tone); };
    const action = (label, run, enabled = true, errorLabel = 'fileActionFailed') => ({
      label,
      enabled,
      click: async () => {
        if (!stillHere()) return;
        try { await run(); }
        catch { report(errorLabel, 'error'); }
      },
    });
    const readAction = (label, run, enabled, errorLabel) => action(label, async () => {
      const current = await resolve();
      if (!stillHere()) return;
      if (!current) throw new Error('File is unavailable');
      await run(current);
    }, enabled, errorLabel);
    const pathAction = (label, run, enabled = Boolean(file?.original)) => readAction(label, (current) => {
      if (!current.original) throw new Error('Original file is unavailable');
      return run(current.original);
    }, enabled);
    const useHandler = (handler) => (original) => openWith(pythonPath, 'open', original, handler.id);

    const vscode = handlers.find(handler => /^(?:Microsoft )?Visual Studio Code$/i.test(handler.label));
    const submenu = handlers.map(handler => pathAction(handler.label.replaceAll('&', '&&'), useHandler(handler)));
    if (canOpenWith) {
      submenu.push(pathAction(t('fileChooseApp'), (original) => openWith(pythonPath, 'picker', original)));
    }
    if (file && mayOpenInBrowser(file.headers, file.filename)) {
      submenu.push(readAction(t('fileOpenBrowser'), (current) => {
        if (!mayOpenInBrowser(current.headers, current.filename)) throw new Error('File has no safe browser preview');
        return openInBrowser(session, target.url);
      }, true));
    }

    const menu = [
      action(t('fileOpen'), async () => {
        if (!await withChatFileLink(content, target.href, true)) throw new Error('Chat link is unavailable');
      }),
      pathAction(t('fileOpenDefaultApp'), async (original) => {
        if (!canOpenInSystemApp(original)) throw new Error('File cannot be opened with a system app');
        const error = await shell.openPath(original);
        if (error) throw new Error(error);
      }, canOpenInDefaultApp),
      ...(vscode ? [pathAction(t('fileOpenVSCode'), useHandler(vscode))] : []),
      submenu.length ? { label: t('fileOpenWith'), submenu } : { label: t('fileOpenWith'), enabled: false },
      { type: 'separator' },
      readAction(t('fileSaveAs'), () => saveAs(content, target.url, () => report('fileActionFailed', 'error')), Boolean(file)),
      pathAction(t('fileCopyPath'), (original) => {
        clipboard.writeText(original);
        report('filePathCopied', 'success');
      }),
      readAction(t('fileCopyContent'), async (current) => {
        const response = await session.fetch(target.url.href, {
          credentials: 'include', redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(15000),
        });
        const text = await readFileText(response, current.filename);
        if (!stillHere()) return;
        clipboard.writeText(text);
        report('fileContentCopied', 'success');
      }, Boolean(file && canCopyFileText(file.headers, file.filename)), 'fileCopyFailed'),
      pathAction(t('fileReveal'), (original) => shell.showItemInFolder(original)),
    ];
    if (!file?.original) {
      const label = target.url?.pathname.startsWith('/files/attachments/')
        ? 'fileNoLocalPath'
        : 'fileOriginalUnavailable';
      menu.push({ type: 'separator' }, { label: t(label), enabled: false });
    }
    Menu.buildFromTemplate(menu).popup({ window, x: params.x, y: params.y });
  });
}
