import path from 'node:path';

// Match the chat preview's 8 MiB ceiling for text files.
const MAX_TEXT_BYTES = 8 * 1024 * 1024;
const TEXT_MIME = new Set([
  'application/javascript', 'application/json', 'application/toml', 'application/xml',
  'application/x-yaml', 'application/yaml',
]);
const TEXT_EXTENSIONS = new Set([
  '.c', '.cc', '.conf', '.cpp', '.css', '.csv', '.go', '.h', '.ini', '.js', '.json', '.jsx',
  '.log', '.markdown', '.md', '.py', '.rs', '.sql', '.toml', '.ts', '.tsv', '.tsx', '.txt',
  '.xml', '.yaml', '.yml',
]);

export function mediaType(headers) {
  return (headers.get('content-type') || '').split(';', 1)[0].trim().toLowerCase();
}

export function canCopyFileText(headers, filename) {
  const mime = mediaType(headers);
  const extension = path.extname(filename).toLowerCase();
  return Number(headers.get('content-length')) <= MAX_TEXT_BYTES && (
    mime.startsWith('text/') || TEXT_MIME.has(mime) ||
    (mime === 'application/vnd.ms-excel' && extension === '.csv') ||
    ((!mime || mime === 'application/octet-stream') &&
      TEXT_EXTENSIONS.has(extension))
  );
}

export async function readFileText(response, filename) {
  if (!response.ok || !canCopyFileText(response.headers, filename) || !response.body) {
    await response.body?.cancel();
    throw new Error('File cannot be copied as text');
  }
  const reader = response.body.getReader();
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > MAX_TEXT_BYTES) throw new Error('File exceeds the text limit');
      chunks.push(value);
    }
  } catch (error) {
    await reader.cancel().catch(() => {});
    throw error;
  } finally {
    reader.releaseLock();
  }
  const bytes = Buffer.concat(chunks, length);
  const charset = /;\s*charset\s*=\s*"?([^";\s]+)/i.exec(response.headers.get('content-type') || '')?.[1];
  const encoding = bytes[0] === 0xff && bytes[1] === 0xfe ? 'utf-16le' :
    bytes[0] === 0xfe && bytes[1] === 0xff ? 'utf-16be' : charset || 'utf-8';
  return new TextDecoder(encoding, { fatal: true }).decode(bytes);
}
