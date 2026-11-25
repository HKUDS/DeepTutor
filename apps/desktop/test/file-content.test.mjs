import assert from 'node:assert/strict';
import test from 'node:test';
import { canCopyFileText, readFileText } from '../src/file-content.mjs';

test('clipboard text uses the served file bytes and keeps line endings', async () => {
  const source = '# 会话资料\r\n\r\n内容\r\n';
  const response = new Response(source, { headers: { 'content-type': 'text/markdown' } });
  assert.equal(await readFileText(response, '资料.md'), source);

  const utf16 = Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(source, 'utf16le')]);
  assert.equal(await readFileText(new Response(utf16), '资料.txt'), source);
});

test('file contents is unavailable for binary or oversized files', async () => {
  assert.equal(canCopyFileText(new Headers({ 'content-type': 'application/pdf' }), 'file.pdf'), false);
  assert.equal(canCopyFileText(new Headers({ 'content-type': 'application/vnd.ms-excel' }), 'report.csv'), true);
  const large = new Response(new Uint8Array(8 * 1024 * 1024 + 1), {
    headers: { 'content-type': 'text/plain' },
  });
  await assert.rejects(readFileText(large, 'notes.txt'), /exceeds the text limit/);
  const invalid = new Response(new Uint8Array([0xc3, 0x28]), {
    headers: { 'content-type': 'text/plain; charset=utf-8' },
  });
  await assert.rejects(readFileText(invalid, 'notes.txt'), TypeError);
});
