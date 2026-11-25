import { win32 } from 'node:path';
import { localURL } from './config.mjs';

const SESSION_FILE = /^\/files\/(?:attachments\/[^/]+\/[^/]+\/[^/]+|workspace-items\/[^/]+\/[^/]+|outputs\/.+)$/;
const DOCUMENT_TYPES = new Set(
  '.md .markdown .txt .csv .tsv .pdf .docx .xlsx .pptx .odt .ods .odp .rtf .json .png .jpg .jpeg .gif .webp .bmp .mp3 .wav .m4a .mp4 .webm .ogg'.split(' '),
);

/** A native menu belongs to the foreground conversation, never to an embedded document. */
export function conversationPage(address, origin) {
  if (!URL.canParse(address)) return false;
  const url = new URL(address);
  return url.origin === origin && /^\/(?:chat(?:\/[^/]+)?|partners\/(?:groups\/)?[^/]+)?\/?$/.test(url.pathname);
}

export function sessionFileURL(address, origin) {
  if (!URL.canParse(address)) return null;
  const url = new URL(address);
  if (url.origin !== origin || url.username || url.password || !SESSION_FILE.test(url.pathname)) return null;
  url.hash = '';
  return url;
}

export async function resolveDesktopFile(session, backendURL, token, source) {
  const endpoint = new URL('/api/file-preview/desktop-file', localURL(backendURL));
  endpoint.searchParams.set('source', source.pathname + source.search);
  const response = await session.fetch(endpoint.href, {
    credentials: 'include', redirect: 'error', cache: 'no-store',
    headers: { 'X-DeepTutor-Desktop-Token': token },
  });
  if (!response.ok) throw new Error('File unavailable');
  const { path } = await response.json();
  // Only local drive files can be handed to Windows. The core authorizes the file and resolves its original path.
  if (typeof path !== 'string' || !/^[a-z]:\\/i.test(path) || path.slice(2).includes(':')) throw new Error('File unavailable');
  return path;
}

export function sessionFileMenu({ source, path, resolvePath, shell, clipboard, t, onError }) {
  const action = (key, run, enabled = true) => ({
    label: t(key), enabled,
    click: async () => {
      // The original may have moved or the conversation may have changed while the menu was open.
      try {
        if (await resolvePath() !== path) return onError('fileUnavailable');
      } catch { return onError('fileUnavailable'); }
      try { await run(); } catch { onError('fileActionFailed'); }
    },
  });
  return [
    action('fileBrowser', () => shell.openExternal(source.href)),
    action('fileDefaultApp', async () => {
      const error = await shell.openPath(path);
      if (error) throw new Error(error);
    }, DOCUMENT_TYPES.has(win32.extname(path).toLowerCase())),
    action('fileExplorer', () => shell.showItemInFolder(path)),
    action('fileCopyPath', () => clipboard.writeText(path)),
  ];
}
