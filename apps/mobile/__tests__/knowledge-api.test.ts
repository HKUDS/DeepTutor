jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));

import { ApiClient, ApiError } from '../src/services/apiClient';
import { KnowledgeApi, messageFor } from '../src/services/knowledgeApi';

function response(status: number, value?: unknown) {
  return {
    status,
    ok: status >= 200 && status < 300,
    redirected: false,
    json: async () => value,
  };
}

const origin = 'https://tutor.example.test';

function api(reply: unknown) {
  const fetcher = jest.fn().mockResolvedValue(reply);
  return { fetcher, api: new KnowledgeApi(new ApiClient(origin, fetcher)) };
}

const summary = {
  id: 'user:kb:physics',
  name: 'physics',
  is_default: false,
  assigned: false,
  read_only: false,
  status: 'processing',
  statistics: {
    raw_documents: 3,
    images: 1,
    content_lists: 12,
    rag_initialized: true,
    status: 'processing',
    progress: {
      stage: 'processing_file',
      message: 'Parsing chapter 1',
      current: 1,
      total: 3,
      progress_percent: 33.3,
      file_name: 'chapter 1.pdf',
      timestamp: '2026-01-01T00:00:00Z',
      retryable: true,
      error: '',
    },
  },
  metadata: {
    description: 'Mechanics',
    rag_provider: 'llamaindex',
    last_error: '',
    last_updated: '2026-01-02T00:00:00Z',
  },
};

test('reads the list the server returns, including the run in progress', async () => {
  const { api: knowledge } = api(response(200, [summary]));
  const bases = await knowledge.list();
  expect(bases).toEqual([
    {
      ref: 'user:kb:physics',
      id: 'user:kb:physics',
      name: 'physics',
      description: 'Mechanics',
      status: 'processing',
      isDefault: false,
      documentCount: 3,
      imageCount: 1,
      chunkCount: 12,
      ragInitialized: true,
      needsReindex: false,
      provider: 'llamaindex',
      assigned: false,
      readOnly: false,
      available: true,
      progress: {
        stage: 'processing_file',
        message: 'Parsing chapter 1',
        current: 1,
        total: 3,
        // The server's own figure is kept, not re-derived from current/total.
        percent: 33.3,
        fileName: 'chapter 1.pdf',
        error: '',
        retryable: true,
        updatedAt: '2026-01-01T00:00:00Z',
      },
      lastError: '',
      updatedAt: '2026-01-02T00:00:00Z',
    },
  ]);
});

test('a base with only a name is still addressable and reports what it knows', async () => {
  const { api: knowledge } = api(response(200, [{ name: 'notes' }]));
  const [base] = await knowledge.list();
  expect(base).toMatchObject({
    ref: 'notes',
    id: '',
    name: 'notes',
    status: 'unknown',
    documentCount: 0,
    available: true,
    progress: null,
  });
});

test('a percentage the server cannot compute is clamped rather than trusted', async () => {
  const { api: knowledge } = api(
    response(200, [
      {
        name: 'notes',
        status: 'ready',
        progress: { stage: 'completed', progress_percent: 140 },
      },
    ]),
  );
  const [base] = await knowledge.list();
  expect(base.progress?.percent).toBe(100);
});

test('an entry with neither a name nor an id is rejected instead of shown blank', async () => {
  const { api: knowledge } = api(response(200, [{}]));
  await expect(knowledge.list()).rejects.toMatchObject({
    kind: 'invalid-response',
  });
});

test('one base is read by its server handle, which is encoded into the path', async () => {
  const { api: knowledge, fetcher } = api(response(200, summary));
  const base = await knowledge.get('user:kb:physics');
  expect(base.name).toBe('physics');
  expect(fetcher.mock.calls[0][0]).toBe(
    `${origin}/api/knowledge-bases/user%3Akb%3Aphysics`,
  );
});

/**
 * React Native's FormData exposes `getParts()`; the standard one used by the
 * test runtime is iterable instead. Both must show the same field.
 */
function formFields(body: unknown): Array<[string, unknown]> {
  const form = body as {
    getParts?: () => Array<{ fieldName: string; string?: string }>;
    entries?: () => Iterable<[string, unknown]>;
  };
  if (typeof form.getParts === 'function') {
    return form.getParts().map(part => [part.fieldName, part.string]);
  }
  if (typeof form.entries === 'function') return [...form.entries()];
  throw new Error('Expected a FormData body');
}

test('creation posts a multipart name field and returns the name the server chose', async () => {
  const { api: knowledge, fetcher } = api(
    response(200, { message: 'created', name: 'biology', files: [], task_id: null }),
  );
  await expect(knowledge.create('biology')).resolves.toBe('biology');
  const init = fetcher.mock.calls[0][1] as {
    method: string;
    headers: Record<string, string>;
    body: unknown;
  };
  expect(init.method).toBe('POST');
  // No Content-Type: the platform has to add the multipart boundary itself.
  expect(init.headers).toEqual({ Accept: 'application/json' });
  expect(formFields(init.body)).toEqual([['name', 'biology']]);
});

test('a creation reply that never names the base cannot be followed up', async () => {
  const { api: knowledge } = api(response(200, { message: 'ok' }));
  await expect(knowledge.create('biology')).rejects.toMatchObject({
    kind: 'invalid-response',
  });
});

test('only the description is editable, and it is sent as a mergeable config', async () => {
  const { api: knowledge, fetcher } = api(response(200, { status: 'success' }));
  await knowledge.updateDescription('user:kb:physics', 'Mechanics');
  const init = fetcher.mock.calls[0][1] as {
    method: string;
    headers: Record<string, string>;
    body: string;
  };
  expect(fetcher.mock.calls[0][0]).toBe(
    `${origin}/api/knowledge-bases/user%3Akb%3Aphysics/config`,
  );
  expect(init.method).toBe('PUT');
  expect(init.headers['Content-Type']).toBe('application/json');
  expect(JSON.parse(init.body)).toEqual({ description: 'Mechanics' });
});

test('deletion must be confirmed by the server', async () => {
  const { api: knowledge, fetcher } = api(response(200, { message: 'deleted' }));
  await knowledge.remove('user:kb:physics');
  expect(fetcher.mock.calls[0][1].method).toBe('DELETE');

  const refused = api(response(200, {}));
  await expect(refused.api.remove('user:kb:physics')).rejects.toMatchObject({
    kind: 'invalid-response',
  });
});

test('the file listing keeps folders and their raw paths', async () => {
  const { api: knowledge } = api(
    response(200, {
      files: [
        {
          name: 'papers/one.pdf',
          type: 'file',
          size: 2048,
          modified: 1_700_000_000,
          mime_type: 'application/pdf',
        },
        { name: 'papers', type: 'folder', size: 0, modified: 0 },
      ],
    }),
  );
  const files = await knowledge.files('user:kb:physics');
  expect(files).toEqual([
    {
      name: 'papers/one.pdf',
      type: 'file',
      size: 2048,
      modified: 1_700_000_000,
      mimeType: 'application/pdf',
    },
    { name: 'papers', type: 'folder', size: 0, modified: 0, mimeType: '' },
  ]);
});

test('removing a document encodes each path segment but keeps the folders', async () => {
  const { api: knowledge, fetcher } = api(response(200, { status: 'ok' }));
  await knowledge.removeFile('user:kb:physics', 'papers/weekly notes.pdf');
  expect(fetcher.mock.calls[0][0]).toBe(
    `${origin}/api/knowledge-bases/user%3Akb%3Aphysics/files/papers/weekly%20notes.pdf`,
  );
  expect(fetcher.mock.calls[0][1].method).toBe('DELETE');
});

test('a base that never ran reports no progress rather than an empty stage', async () => {
  const { api: knowledge } = api(response(200, { status: 'not_started' }));
  await expect(knowledge.progress('notes')).resolves.toBeNull();
});

test('retry is a POST and a refusal keeps the status the server gave', async () => {
  const { api: knowledge, fetcher } = api(
    response(200, { status: 'started', message: 'retrying' }),
  );
  await knowledge.retry('notes');
  expect(fetcher.mock.calls[0][1].method).toBe('POST');

  const refused = api(response(409, { detail: 'not failed' }));
  await expect(refused.api.retry('notes')).rejects.toMatchObject({
    kind: 'http',
    status: 409,
  });
});

test('the upload policy is the server’s, with extensions normalised', async () => {
  const { api: knowledge, fetcher } = api(
    response(200, {
      extensions: ['.PDF', '.txt'],
      accept: '.pdf,.txt',
      max_file_size_bytes: 52_428_800,
      allow_any_extension: false,
    }),
  );
  await expect(knowledge.policy()).resolves.toEqual({
    extensions: ['.pdf', '.txt'],
    accept: '.pdf,.txt',
    maxFileSizeBytes: 52_428_800,
    allowAnyExtension: false,
  });
  expect(fetcher.mock.calls[0][0]).toBe(
    `${origin}/api/knowledge-bases/supported-file-types`,
  );
});

test('failures are explained in terms a learner can act on', () => {
  expect(messageFor(new ApiError('unauthorized', 'x', 401))).toBe(
    'Sign in again to manage your knowledge bases.',
  );
  expect(messageFor(new ApiError('timeout', 'x'))).toBe(
    'The server took too long to answer. Try again.',
  );
  expect(messageFor(new ApiError('network', 'x'))).toBe(
    'Could not reach the server. Check your connection.',
  );
  expect(messageFor(new ApiError('http', 'x', 404))).toBe(
    'This knowledge base no longer exists on the server.',
  );
  expect(messageFor(new ApiError('http', 'x', 409))).toBe(
    'The server refused this change in the base’s current state.',
  );
  expect(messageFor(new ApiError('http', 'x', 403))).toBe(
    'This knowledge base is read-only for your account.',
  );
  expect(messageFor(new Error('boom'))).toBe(
    'The server could not complete that request.',
  );
});
