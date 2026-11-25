import { fetch as nativeFetch } from 'expo/fetch';

import { ApiError } from '../src/services/apiClient';
import type { UploadPolicy } from '../src/services/knowledgeApi';
import {
  formatBytes,
  mimeTypeFor,
  uploadKnowledgeFiles,
  validatePickedFiles,
} from '../src/services/knowledgeUpload';

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));

const probe = nativeFetch as unknown as jest.Mock;

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
  responseURL = '';
  sentBody: unknown = null;
  aborted = false;
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
    this.aborted = true;
    this.onabort?.();
  }
  report(loaded: number, total: number, lengthComputable = true) {
    this.upload.onprogress?.({ lengthComputable, loaded, total });
  }
  respond(status: number, value?: unknown) {
    this.status = status;
    this.responseURL = this.url;
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
  probe.mockReset();
  // HEAD on a POST-only route is 405; the probe only cares that it is not 3xx.
  probe.mockResolvedValue({ status: 405, redirected: false });
});

afterAll(() => {
  globals.XMLHttpRequest = realXhr;
  globals.FormData = realFormData;
});

const origin = 'https://tutor.example.test';

/** Let the redirect probe resolve, then hand back the request it allowed. */
async function opened(count = 1): Promise<FakeXhr> {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    if (FakeXhr.instances.length >= count) return FakeXhr.instances[count - 1];
    await Promise.resolve();
  }
  throw new Error('the upload never opened a request');
}

async function settled(): Promise<void> {
  for (let attempt = 0; attempt < 10; attempt += 1) await Promise.resolve();
}

async function start(
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
  return { handle, xhr: await opened() };
}

test('streams one multipart part per file to the encoded upload route', async () => {
  const { handle, xhr } = await start([
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

test('the endpoint is checked for redirects before a byte is sent', async () => {
  const { handle, xhr } = await start();
  expect(probe).toHaveBeenCalledTimes(1);
  const [url, init] = probe.mock.calls[0] as [
    string,
    { method: string; redirect: string; credentials: string },
  ];
  expect(url).toBe(`${origin}/api/knowledge-bases/user%3Akb%3Aphysics/upload`);
  expect(init).toMatchObject({
    method: 'HEAD',
    // The one setting XHR cannot express; expo/fetch disables following on
    // both platforms for it.
    redirect: 'manual',
    credentials: 'include',
  });
  xhr.respond(200, { files: [], task_id: 't1' });
  await handle.promise;
});

test('a redirecting endpoint is refused before the file is sent', async () => {
  probe.mockResolvedValue({ status: 307, redirected: true });
  const handle = uploadKnowledgeFiles({
    origin,
    ref: 'user:kb:physics',
    files: [
      { uri: 'file:///cache/notes.pdf', name: 'notes.pdf', mimeType: 'application/pdf' },
    ],
  });
  await expect(handle.promise).rejects.toMatchObject({ kind: 'redirect', status: 307 });
  expect(FakeXhr.instances).toHaveLength(0);
});

test('a check that cannot be completed refuses the upload', async () => {
  probe.mockRejectedValue(new Error('dns'));
  const handle = uploadKnowledgeFiles({
    origin,
    ref: 'user:kb:physics',
    files: [
      { uri: 'file:///cache/notes.pdf', name: 'notes.pdf', mimeType: 'application/pdf' },
    ],
  });
  await expect(handle.promise).rejects.toMatchObject({ kind: 'network' });
  expect(FakeXhr.instances).toHaveLength(0);
});

test('a check that never answers times out instead of hanging', async () => {
  jest.useFakeTimers();
  try {
    probe.mockImplementation(
      (_url: string, init: { signal: AbortSignal }) =>
        new Promise((_resolve, reject) => {
          init.signal.addEventListener('abort', () => reject(new Error('aborted')));
        }),
    );
    const handle = uploadKnowledgeFiles({
      origin,
      ref: 'user:kb:physics',
      files: [
        { uri: 'file:///cache/notes.pdf', name: 'notes.pdf', mimeType: 'application/pdf' },
      ],
    });
    const outcome = handle.promise.catch(error => error as ApiError);
    jest.advanceTimersByTime(15_500);
    await expect(outcome).resolves.toMatchObject({ kind: 'timeout' });
    expect(FakeXhr.instances).toHaveLength(0);
  } finally {
    jest.useRealTimers();
  }
});

test('reports the bytes the platform actually wrote, and only when measurable', async () => {
  const seen: Array<[number, number]> = [];
  const { handle, xhr } = await start(undefined, {
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
    const { handle, xhr } = await start();
    xhr.respond(status, { detail: 'no' });
    await expect(handle.promise).rejects.toMatchObject({
      kind,
      status,
    });
  }
});

test('a refusal carries the reason the server gave with it', async () => {
  const { handle, xhr } = await start();
  xhr.respond(409, {
    detail:
      'The bound embedding model is unavailable or changed. Check the model settings or select a model to re-index this knowledge base.',
  });
  await expect(handle.promise).rejects.toMatchObject({
    kind: 'http',
    status: 409,
    detail:
      'The bound embedding model is unavailable or changed. Check the model settings or select a model to re-index this knowledge base.',
  });
});

test('an unreadable body is refused instead of treated as a success', async () => {
  const { handle, xhr } = await start();
  xhr.status = 200;
  xhr.responseText = '<html>proxy error</html>';
  xhr.onload?.();
  await expect(handle.promise).rejects.toMatchObject({
    kind: 'invalid-response',
  });
});

test('a transport error says the server was unreachable', async () => {
  const { handle, xhr } = await start();
  xhr.onerror?.();
  await expect(handle.promise).rejects.toMatchObject({ kind: 'network' });
});

test('a followed redirect is caught by the final URL, not the status', async () => {
  const { handle, xhr } = await start();
  // React Native follows a 307 and reports the target's 200 here.
  xhr.status = 200;
  xhr.responseURL = 'https://elsewhere.example.test/collect';
  xhr.responseText = JSON.stringify({ files: ['notes.pdf'], task_id: 't1' });
  xhr.onload?.();
  await expect(handle.promise).rejects.toMatchObject({ kind: 'redirect', status: 200 });
});

test('aborting settles the transfer as cancelled, not as a failure', async () => {
  const { handle, xhr } = await start();
  handle.abort();
  await expect(handle.promise).rejects.toBeInstanceOf(ApiError);
  await expect(handle.promise).rejects.toMatchObject({ kind: 'aborted' });
  // The socket is closed rather than left writing the file.
  expect(xhr.aborted).toBe(true);
  // Once settled, a late success cannot rewrite the outcome.
  xhr.respond(200, { files: [], task_id: 't1' });
});

test('a caller’s abort signal cancels the same transfer', async () => {
  const controller = new AbortController();
  const { handle, xhr } = await start(undefined, { signal: controller.signal });
  controller.abort();
  await expect(handle.promise).rejects.toMatchObject({ kind: 'aborted' });
  expect(xhr.aborted).toBe(true);
});

test('an already-aborted signal never checks or sends anything', async () => {
  const controller = new AbortController();
  controller.abort();
  const handle = uploadKnowledgeFiles({
    origin,
    ref: 'notes',
    files: [{ uri: 'file:///a.pdf', name: 'a.pdf', mimeType: 'application/pdf' }],
    signal: controller.signal,
  });
  await expect(handle.promise).rejects.toMatchObject({ kind: 'aborted' });
  expect(probe).not.toHaveBeenCalled();
  expect(FakeXhr.instances).toHaveLength(0);
});

test('cancelling during the redirect check never opens the upload', async () => {
  let release: (value: unknown) => void = () => {};
  probe.mockImplementation(
    () => new Promise(resolve => {
      release = resolve;
    }),
  );
  const handle = uploadKnowledgeFiles({
    origin,
    ref: 'notes',
    files: [{ uri: 'file:///a.pdf', name: 'a.pdf', mimeType: 'application/pdf' }],
  });
  handle.abort();
  await expect(handle.promise).rejects.toMatchObject({ kind: 'aborted' });
  release({ status: 405, redirected: false });
  await settled();
  expect(FakeXhr.instances).toHaveLength(0);
});

test('a stalled transfer is aborted, not merely rejected', async () => {
  jest.useFakeTimers();
  try {
    const { handle, xhr } = await start();
    const outcome = handle.promise.then(
      () => 'resolved',
      error => (error as ApiError).kind,
    );
    // Progress pushes the deadline out; silence does not.
    jest.advanceTimersByTime(30_000);
    xhr.report(5, 10);
    jest.advanceTimersByTime(59_000);
    expect(xhr.aborted).toBe(false);
    jest.advanceTimersByTime(1_500);
    await expect(outcome).resolves.toBe('timeout');
    // The dead socket stops writing the learner's file.
    expect(xhr.aborted).toBe(true);
    // Settled exactly once: a response arriving afterwards is ignored.
    xhr.respond(200, { files: ['notes.pdf'], task_id: 't1' });
    await settled();
    await expect(outcome).resolves.toBe('timeout');
  } finally {
    jest.useRealTimers();
  }
});

test('a transport that cannot start fails immediately', async () => {
  FakeXhr.failOnSend = new Error('no bridge');
  const { handle } = await start();
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
  // The refused pick still carries its copy, so the queue can release it.
  expect(rejected.map(entry => entry.uri)).toEqual([
    'file:///cache/essay.doc',
    'file:///cache/empty.pdf',
    'file:///cache/huge.pdf',
    'file:///cache/no-extension',
    'file:///cache/..',
  ]);
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
