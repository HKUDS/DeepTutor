import { ApiError } from '../src/services/apiClient';
import type { UploadPolicy } from '../src/services/knowledgeApi';
import {
  formatBytes,
  mimeTypeFor,
  uploadKnowledgeFiles,
  validatePickedFiles,
} from '../src/services/knowledgeUpload';

type ProgressHandler =
  | ((event: {
      lengthComputable: boolean;
      loaded: number;
      total: number;
    }) => void)
  | null;

/**
 * The transport is `XMLHttpRequest` because only it reports upload progress, so
 * the test drives the same callbacks React Native would.
 */
class FakeXhr {
  static instances: FakeXhr[] = [];
  static failOnSend: Error | null = null;
  upload: { onprogress: ProgressHandler } = { onprogress: null };
  method = '';
  url = '';
  async = false;
  headers: Record<string, string> = {};
  withCredentials = false;
  timeout = -1;
  status = 0;
  responseText = '';
  sentBody: unknown = null;
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  ontimeout: (() => void) | null = null;

  constructor() {
    FakeXhr.instances.push(this);
  }
  open(method: string, url: string, async: boolean) {
    this.method = method;
    this.url = url;
    this.async = async;
  }
  setRequestHeader(name: string, value: string) {
    this.headers[name] = value;
  }
  send(body: unknown) {
    if (FakeXhr.failOnSend) throw FakeXhr.failOnSend;
    this.sentBody = body;
  }
  abort() {
    this.onabort?.();
  }
  report(loaded: number, total: number, lengthComputable = true) {
    this.upload.onprogress?.({ lengthComputable, loaded, total });
  }
  respond(status: number, value?: unknown) {
    this.status = status;
    this.responseText = value === undefined ? '' : JSON.stringify(value);
    this.onload?.();
  }
}

/** Records the `{uri, name, type}` descriptors React Native streams from disk. */
class RecordingFormData {
  readonly parts: Array<[string, unknown]> = [];
  append(name: string, value: unknown) {
    this.parts.push([name, value]);
  }
}

const globals = globalThis as {
  XMLHttpRequest?: unknown;
  FormData?: unknown;
};
const realXhr = globals.XMLHttpRequest;
const realFormData = globals.FormData;

beforeEach(() => {
  FakeXhr.instances = [];
  FakeXhr.failOnSend = null;
  globals.XMLHttpRequest = FakeXhr;
  globals.FormData = RecordingFormData;
});

afterAll(() => {
  globals.XMLHttpRequest = realXhr;
  globals.FormData = realFormData;
});

const origin = 'https://tutor.example.test';

function start(
  files = [
    {
      uri: 'file:///cache/notes.pdf',
      name: 'notes.pdf',
      size: 10,
      mimeType: 'application/pdf',
    },
  ],
  options: {
    onProgress?: (loaded: number, total: number) => void;
    signal?: AbortSignal;
  } = {},
) {
  const handle = uploadKnowledgeFiles({
    origin,
    ref: 'user:kb:physics',
    files,
    ...options,
  });
  return { handle, xhr: FakeXhr.instances[0] };
}

test('streams one multipart part per file to the encoded upload route', async () => {
  const { handle, xhr } = start([
    {
      uri: 'file:///cache/notes.pdf',
      name: 'notes.pdf',
      size: 10,
      mimeType: 'application/pdf',
    },
    {
      uri: 'content://downloads/scan.jpg',
      name: 'scan.jpg',
      size: 20,
      mimeType: '',
    },
  ]);
  expect(xhr.method).toBe('POST');
  expect(xhr.url).toBe(
    `${origin}/api/knowledge-bases/user%3Akb%3Aphysics/upload`,
  );
  // The session is an HttpOnly cookie; the platform jar supplies it.
  expect(xhr.withCredentials).toBe(true);
  expect(xhr.headers).toEqual({ Accept: 'application/json' });
  expect((xhr.sentBody as RecordingFormData).parts).toEqual([
    [
      'files',
      {
        uri: 'file:///cache/notes.pdf',
        name: 'notes.pdf',
        type: 'application/pdf',
      },
    ],
    [
      'files',
      // An unknown type is declared as bytes rather than left empty.
      { uri: 'content://downloads/scan.jpg', name: 'scan.jpg', type: 'application/octet-stream' },
    ],
  ]);
  xhr.respond(200, { message: 'uploaded', files: ['notes.pdf'], task_id: 't1' });
  await expect(handle.promise).resolves.toEqual({
    taskId: 't1',
    files: ['notes.pdf'],
    message: 'uploaded',
  });
});

test('reports the bytes the platform actually wrote, and only when measurable', async () => {
  const seen: Array<[number, number]> = [];
  const { handle, xhr } = start(undefined, {
    onProgress: (loaded, total) => seen.push([loaded, total]),
  });
  xhr.report(5, 10);
  // A response with no content length cannot be turned into a percentage.
  xhr.report(9, 0, false);
  xhr.report(10, 10);
  expect(seen).toEqual([
    [5, 10],
    [10, 10],
  ]);
  xhr.respond(200, { files: ['notes.pdf'], task_id: 't1' });
  await handle.promise;
});

test('an HTTP failure is labelled with the status the server gave', async () => {
  const cases = [
    [401, 'unauthorized'],
    [302, 'redirect'],
    [413, 'http'],
    [500, 'http'],
  ] as const;
  for (const [status, kind] of cases) {
    FakeXhr.instances = [];
    const { handle, xhr } = start();
    xhr.respond(status, { detail: 'no' });
    await expect(handle.promise).rejects.toMatchObject({
      kind,
      status,
    });
  }
});

test('an unreadable body is refused instead of treated as a success', async () => {
  const { handle, xhr } = start();
  xhr.status = 200;
  xhr.responseText = '<html>proxy error</html>';
  xhr.onload?.();
  await expect(handle.promise).rejects.toMatchObject({
    kind: 'invalid-response',
  });
});

test('a transport error says the server was unreachable', async () => {
  const { handle, xhr } = start();
  xhr.onerror?.();
  await expect(handle.promise).rejects.toMatchObject({ kind: 'network' });
});

test('aborting settles the transfer as cancelled, not as a failure', async () => {
  const { handle, xhr } = start();
  handle.abort();
  await expect(handle.promise).rejects.toBeInstanceOf(ApiError);
  await expect(handle.promise).rejects.toMatchObject({ kind: 'aborted' });
  // Once settled, a late success cannot rewrite the outcome.
  xhr.respond(200, { files: [], task_id: 't1' });
});

test('a caller’s abort signal cancels the same transfer', async () => {
  const controller = new AbortController();
  const { handle } = start(undefined, { signal: controller.signal });
  controller.abort();
  await expect(handle.promise).rejects.toMatchObject({ kind: 'aborted' });
});

test('an already-aborted signal never opens a request', async () => {
  const controller = new AbortController();
  controller.abort();
  const handle = uploadKnowledgeFiles({
    origin,
    ref: 'notes',
    files: [{ uri: 'file:///a.pdf', name: 'a.pdf', mimeType: 'application/pdf' }],
    signal: controller.signal,
  });
  await expect(handle.promise).rejects.toMatchObject({ kind: 'aborted' });
  // Nothing was opened and no bytes were handed to the transport.
  expect(FakeXhr.instances[0].method).toBe('');
  expect(FakeXhr.instances[0].sentBody).toBeNull();
});

test('a stalled transfer times out rather than hanging on a dead socket', async () => {
  jest.useFakeTimers();
  try {
    const { handle, xhr } = start();
    const settled = handle.promise.catch(error => error as ApiError);
    // Progress pushes the deadline out; silence does not.
    jest.advanceTimersByTime(30_000);
    xhr.report(5, 10);
    jest.advanceTimersByTime(59_000);
    expect(xhr.status).toBe(0);
    jest.advanceTimersByTime(1_500);
    const error = await settled;
    expect(error).toMatchObject({ kind: 'timeout' });
  } finally {
    jest.useRealTimers();
  }
});

test('a transport that cannot start fails immediately', async () => {
  FakeXhr.failOnSend = new Error('no bridge');
  const { handle } = start();
  await expect(handle.promise).rejects.toMatchObject({ kind: 'network' });
});

const policy: UploadPolicy = {
  extensions: ['.pdf', '.txt'],
  accept: '.pdf,.txt',
  maxFileSizeBytes: 1000,
  allowAnyExtension: false,
};

function picked(name: string, size?: number) {
  return {
    uri: `file:///cache/${name}`,
    name,
    size,
    mimeType: '',
  };
}

test('pre-flight checks repeat the server’s limits without inventing new ones', () => {
  const { accepted, rejected } = validatePickedFiles(
    [
      picked('notes.pdf', 900),
      picked('essay.doc', 100),
      picked('empty.pdf', 0),
      picked('huge.pdf', 2000),
      picked('archive.zip', 100),
      picked('no-extension', 10),
      picked('..', 10),
    ],
    policy,
  );
  expect(accepted.map(file => file.name)).toEqual(['notes.pdf', 'archive.zip']);
  expect(rejected.map(entry => entry.name)).toEqual([
    'essay.doc',
    'empty.pdf',
    'huge.pdf',
    'no-extension',
    '..',
  ]);
  expect(rejected[2].reason).toContain('1000 B');
});

test('a picked path is flattened to the name the server will store', () => {
  const { accepted } = validatePickedFiles(
    [{ ...picked('chapter 1.pdf', 10), name: 'papers/chapter 1.pdf' }],
    policy,
  );
  expect(accepted).toEqual([
    {
      uri: 'file:///cache/chapter 1.pdf',
      name: 'chapter 1.pdf',
      size: 10,
      mimeType: 'application/pdf',
    },
  ]);
});

test('without a policy nothing is blocked on the client’s guess', () => {
  const { accepted, rejected } = validatePickedFiles(
    [picked('anything.exe', 10_000_000), picked('unknown-size.pdf')],
    null,
  );
  expect(rejected).toEqual([]);
  expect(accepted.map(file => file.name)).toEqual([
    'anything.exe',
    'unknown-size.pdf',
  ]);
});

test('a parser that accepts anything does not have its list second-guessed', () => {
  const { accepted } = validatePickedFiles([picked('data.bin', 10)], {
    ...policy,
    extensions: [],
    allowAnyExtension: true,
  });
  expect(accepted.map(file => file.name)).toEqual(['data.bin']);
});

test('an unknown size is not treated as an empty file', () => {
  const { accepted, rejected } = validatePickedFiles([picked('notes.pdf')], policy);
  expect(rejected).toEqual([]);
  expect(accepted).toHaveLength(1);
});

test('declared types follow the extension when the picker reports none', () => {
  expect(mimeTypeFor('.pdf')).toBe('application/pdf');
  expect(mimeTypeFor('.docx')).toBe(
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  );
  expect(mimeTypeFor('.unknown')).toBe('application/octet-stream');
});

test('sizes are shown in the unit a learner would use', () => {
  expect(formatBytes(0)).toBe('0 B');
  expect(formatBytes(512)).toBe('512 B');
  expect(formatBytes(1536)).toBe('1.5 KB');
  expect(formatBytes(52_428_800)).toBe('50 MB');
});
