const HEADER = 'x-deeptutor-desktop-session';

export function planRequestHeaders(details, { sessionToken, frontendURL, contentsId, mainFrame }) {
  const { requestHeaders } = details;
  let headers;
  for (const name of Object.keys(requestHeaders)) {
    if (name.toLowerCase() === HEADER) {
      headers ??= { ...requestHeaders };
      delete headers[name];
    }
  }
  if (!sessionToken || contentsId == null || details.webContentsId !== contentsId || !mainFrame) return headers;
  const request = new URL(details.url);
  const front = new URL(frontendURL);
  if (details.initiatorOrigin && details.initiatorOrigin !== front.origin) return headers;
  const frame = details.frame;
  if (frame && (frame !== mainFrame || !frame.url.startsWith(front.origin + '/'))) return headers;
  if (!frame && details.resourceType !== 'webSocket') return headers;
  const method = details.method;
  const path = request.pathname;
  const planSettings = details.resourceType === 'xhr' && request.origin === front.origin &&
    ((method === 'GET' && /^\/api\/settings\/providers\/chatgpt-plan\/(status|models)$/.test(path)) ||
     (method === 'POST' && (/^\/api\/settings\/providers\/chatgpt-plan\/(start|add|cancel|disconnect|dismiss-welcome)$/.test(path) ||
                           path === '/api/settings/tests/llm/start')));
  const origin = Object.entries(requestHeaders).find(([name]) => name.toLowerCase() === 'origin')?.[1];
  const planSocket = details.resourceType === 'webSocket' && method === 'GET' &&
    request.protocol === 'ws:' && request.host === front.host && path === '/ws' && origin === front.origin;
  if (!planSettings && !planSocket) return headers;
  return { ...(headers ?? requestHeaders), [HEADER]: sessionToken };
}
