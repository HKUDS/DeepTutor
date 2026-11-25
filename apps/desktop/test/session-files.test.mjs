import assert from 'node:assert/strict';
import test from 'node:test';
import { conversationPage, resolveDesktopFile, sessionFileMenu, sessionFileURL } from '../src/session-files.mjs';

const origin = 'http://127.0.0.1:18802';
const source = new URL('/files/attachments/session/id/notes.md?dt_workspace=course', origin);
const path = String.raw`C:\My notes\课堂.md`;

test('only first-party conversations and published file links have a desktop menu', () => {
  assert.ok(conversationPage(origin + '/chat/session?view=1', origin));
  assert.ok(conversationPage(origin + '/partners/groups/lesson', origin));
  assert.equal(conversationPage(source.href, origin), false);
  assert.equal(conversationPage('https://example.org/chat/session', origin), false);
  assert.equal(sessionFileURL(source.href, origin).href, source.href);
  for (const url of ['https://example.org/files/outputs/report.md', 'file:///C:/notes.md', origin + '/settings', origin + '/files/workspace-items/ws/item/file-storage']) {
    assert.equal(sessionFileURL(url, origin), null);
  }
});

test('look up the original file using the core session and the scope on the link', async () => {
  const session = { fetch: async (url, options) => {
    const endpoint = new URL(url);
    assert.equal(endpoint.origin, 'http://127.0.0.1:18801');
    assert.equal(endpoint.pathname, '/api/file-preview/desktop-file');
    assert.equal(endpoint.searchParams.get('source'), source.pathname + source.search);
    assert.equal(options.credentials, 'include');
    assert.equal(options.redirect, 'error');
    assert.equal(options.headers['X-DeepTutor-Desktop-Token'], 'desktop');
    return Response.json({ path });
  } };
  assert.equal(await resolveDesktopFile(session, 'http://127.0.0.1:18801', 'desktop', source), path);
  await assert.rejects(resolveDesktopFile({ fetch: () => new Response(null, { status: 404 }) }, origin, 'desktop', source));
});

test('the four native actions use the published browser URL or the original Windows path', async () => {
  const calls = [];
  const options = {
    source, path, resolvePath: () => path, t: key => key, onError: key => calls.push(key),
    shell: {
      openExternal: url => calls.push(['browser', url]),
      openPath: file => { calls.push(['open', file]); return ''; },
      showItemInFolder: file => calls.push(['reveal', file]),
    },
    clipboard: { writeText: text => calls.push(['copy', text]) },
  };
  for (const item of sessionFileMenu(options)) {
    assert.equal(item.enabled, true);
    await item.click();
  }
  assert.deepEqual(calls, [['browser', source.href], ['open', path], ['reveal', path], ['copy', path]]);
  const unsupported = sessionFileMenu({ ...options, path: 'example.exe' });
  assert.equal(unsupported.find(item => item.label === 'fileDefaultApp').enabled, false);
  options.shell.openPath = () => 'No associated app';
  await sessionFileMenu(options).find(item => item.label === 'fileDefaultApp').click();
  assert.equal(calls.at(-1), 'fileActionFailed');
  options.resolvePath = () => { throw new Error('File moved'); };
  await sessionFileMenu(options).find(item => item.label === 'fileCopyPath').click();
  assert.equal(calls.at(-1), 'fileUnavailable');
});
